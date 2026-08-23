"""HTTP API — what the designer (and any other client) talks to.

Authentication: every /api route requires ``Authorization: Bearer <token>``
(or ``X-API-Key``), except ``/api/auth/login``, the SSO endpoints,
``/api/health`` (a probe holds no credential) and ``/api/hooks/*`` — webhook
URLs are unguessable capability URLs called by external systems. The token
comes from
``PROCESS_ENGINE_AUTH_TOKEN`` (auto-generated into ``.process_engine_auth``
for development).

This module composes the layers rather than being one: ``process_engine_core``'s
storage, a registry of plugin *specs*, and the users/secrets/notification stores,
wired in ``create_app``.

**Nothing executes here.** This process cannot run a step even in principle: the
distribution it is installed from carries no plugin implementations and no
engine, only the manifests and config schemas the palette and the step forms are
generated from. Asking for a run — from the Run button, a schedule's webhook, or
the API directly — writes a job to the shared database, and an engine host
claims it. A single-step preview is the same queue with an answer coming back
(202 plus a poll URL). That is what lets this half be a Linux container while the
steps that need Windows and Excel run on a Windows box, with the database as the
only channel between them.

Create the app with ``create_app()`` or run ``python -m process_engine_api``.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from process_engine_core import workspace
from process_engine_core.jobs import enqueue_preview, enqueue_resume, enqueue_run
from process_engine_core.models import (
    NotificationEvent,
    ProcessDefinition,
    ProcessInstance,
    RunStatus,
    new_id,
    utcnow,
)
from process_engine_core.notifications import (
    EMAIL_PATTERN,
    MailSettings,
    MailSettingsStore,
    Notifier,
    event_for,
)
from process_engine_core.registry import PluginRegistry, spec_registry
from process_engine_core.secrets_store import SecretsManager
from process_engine_core.security import resolve_auth_token, resolve_fernet_key
from process_engine_core.storage import Database, iso_utc
from process_engine_core.validation import (
    combine_deliveries,
    deliveries_from_run,
    validate,
    validate_detailed,
)

from . import sso
from .datapicker import build_picker, reference_for
from .users import SESSION_TTL_SECONDS, UserManager

logger = logging.getLogger("process_engine_api")

# A worker heartbeats once per queue poll (2s by default), so anything unheard
# from for this long is treated as gone — long enough to survive a slow poll
# interval, short enough that "no workers online" appears while someone is still
# looking at the spinner it explains.
WORKER_STALE_SECONDS = 60.0


class RunRequest(BaseModel):
    trigger_input: Any = None
    variables: dict[str, Any] = Field(default_factory=dict)
    draft: bool = False  # run the draft instead of the latest published version
    version: int | None = None  # pin a specific published version
    # Accepted and ignored: every run is queued now, so every response is
    # immediate and every caller polls GET /api/runs/{id}. Kept so an older
    # client's request body is not a 422.
    background: bool = False


class SecretRequest(BaseModel):
    value: str


class FolderRequest(BaseModel):
    folder: str = ""


class CloneRequest(BaseModel):
    name: str | None = None  # defaults to "<original> (copy)", deduplicated
    folder: str | None = None  # defaults to the original's folder


class ShareRequest(BaseModel):
    usernames: list[str] = Field(default_factory=list)  # the whole list, not a delta


class PreviewRequest(BaseModel):
    run_id: str | None = None  # which recorded run supplies upstream data; newest by default
    trigger_input: Any = None
    variables: dict[str, Any] = Field(default_factory=dict)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "editor"


class UserUpdateRequest(BaseModel):
    password: str | None = None
    role: str | None = None
    disabled: bool | None = None


class MailSettingsRequest(BaseModel):
    """The relay form. A credential omitted (or null) keeps the stored one —
    the API never returns them, so the form has nothing to send back; an empty
    string is an explicit clear."""

    enabled: bool = True
    provider: str = "smtp"
    sender: str = ""
    # SMTP
    host: str = ""
    port: int = Field(default=587, ge=1, le=65535)
    encryption: str = "starttls"
    username: str = ""
    password: str | None = None
    # Amazon SES
    region: str = "us-east-1"
    access_key_id: str = ""
    configuration_set: str = ""
    secret_access_key: str | None = None


class TestEmailRequest(BaseModel):
    to: str = ""  # defaults to the signed-in user


def create_app(
    db: Database | None = None,
    registry: PluginRegistry | None = None,
    auth_token: str | None = None,
    notifier: Notifier | None = None,
) -> FastAPI:
    db = db or Database()
    # Specs, not implementations: manifests and config schemas, enough to draw
    # the palette, generate every step form and validate a definition — and
    # nothing that can be called. See process_engine_core.registry.
    registry = registry or spec_registry()
    secrets = SecretsManager(db)
    users = UserManager(db)
    mail_settings = MailSettingsStore(db)
    notifier = notifier or Notifier(mail_settings)
    token = auth_token or resolve_auth_token()
    pending: set[asyncio.Task] = set()  # in-flight notification sends, kept alive

    # -- notifications -------------------------------------------------------

    def _notify(definition: ProcessDefinition, instance: ProcessInstance, event: NotificationEvent) -> None:
        """Send the one notification this host has any business sending.

        A run's start and end are reported by whoever executed it, which is
        never this process. The exception is a run cancelled while it was still
        queued or paused: it ends *here*, so the email for it goes from here.

        Fire and forget — the run is already over and ``deliver`` swallows its
        own errors. The instance is copied because the caller goes on using it,
        and ``pending`` holds a reference only so the event loop cannot
        garbage-collect a send half way through.
        """
        snapshot = instance.model_copy(deep=True)
        task = asyncio.create_task(notifier.deliver(definition, snapshot, event))
        pending.add(task)
        task.add_done_callback(pending.discard)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Durability: re-publish runs whose job was lost. A row that still has a
        # job in the queue belongs to whichever engine host holds it — this
        # container restarting says nothing about that machine, and a lapsed
        # lease is how a dead worker's job is recovered. Cron is not started
        # here at all: schedules are claimed from the database by the engine
        # hosts, so automation carries on while this container is restarting.
        interrupted = [
            *db.get_instances_by_status(RunStatus.RUNNING.value),
            *db.get_instances_by_status(RunStatus.PENDING.value),
        ]
        for orphan in interrupted:
            if db.get_job(orphan.id) is not None:
                continue
            definition = db.get_version(orphan.process_id, orphan.process_version) or db.get_process(orphan.process_id)
            if definition is None:
                continue
            logger.info("re-queueing run %s, left without a job by a restart", orphan.id)
            enqueue_resume(db, definition, orphan)
        yield

    app = FastAPI(title="Process Engine", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- auth --------------------------------------------------------------------
    # Two credential kinds: user session tokens (issued by /api/auth/login) and
    # the static API token (machine/bootstrap credential, acts as admin).

    def require_auth(request: Request) -> None:
        supplied = ""
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            supplied = header[7:].strip()
        supplied = supplied or request.headers.get("x-api-key", "")
        principal = None
        if supplied:
            if hmac.compare_digest(supplied, token):
                principal = {"name": "api-token", "role": "admin"}
            else:
                principal = users.verify_token(supplied)
        if principal is None:
            raise HTTPException(status_code=401, detail="invalid or missing credentials",
                                headers={"WWW-Authenticate": "Bearer"})
        request.state.principal = principal

    def require_admin(request: Request) -> None:
        if request.state.principal.get("role") != "admin":
            raise HTTPException(status_code=403, detail="admin role required")

    api = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])
    auth = APIRouter(prefix="/api/auth")  # login is unauthenticated by definition
    hooks = APIRouter(prefix="/api/hooks")  # capability URLs: no bearer token

    @app.get("/api/health")
    def health() -> dict[str, str]:
        """Liveness for a container probe or load balancer.

        Unauthenticated because the thing that polls it holds no credential —
        the Docker HEALTHCHECK, nginx, a reverse proxy. It therefore says only
        that this process is answering: no version, no mode, no counts. What
        this installation is doing is ``/api/queue``, behind the bearer token.
        """
        return {"status": "ok"}

    @auth.post("/login")
    def login(body: LoginRequest) -> dict[str, Any]:
        user = users.authenticate(body.username, body.password)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid username or password")
        return {
            "token": users.issue_token(user["username"], user["role"]),
            "username": user["username"],
            "role": user["role"],
            "expires_in": SESSION_TTL_SECONDS,
        }

    @api.get("/auth/me")
    def whoami(request: Request) -> dict[str, Any]:
        return request.state.principal

    # -- single sign-on (OIDC: Google, Microsoft Entra ID) ---------------------------

    providers = sso.configured_providers()
    state_signer = Fernet(resolve_fernet_key())
    if providers and sso.designer_url() == sso.public_url() and not _designer_index().is_file():
        # The callback lands the browser on DESIGNER_URL. Defaulting it to this
        # origin is right when this process serves the designer too — and sends
        # everyone who signs in to a blank 404 when it does not, which is the
        # normal shape of a split deployment. Say so at startup, not per login.
        logger.warning(
            "SSO is configured but PROCESS_ENGINE_DESIGNER_URL is unset and no designer is served here; "
            "logins will be redirected to %s, which has no app to land on",
            sso.designer_url(),
        )

    def _sso_redirect_uri(provider_key: str) -> str:
        return f"{sso.public_url()}/api/auth/sso/{provider_key}/callback"

    @auth.get("/sso")
    def sso_providers() -> list[dict[str, str]]:
        return [{"key": p.key, "name": p.name} for p in providers.values()]

    @auth.get("/sso/{provider_key}/login")
    def sso_login(provider_key: str) -> RedirectResponse:
        provider = providers.get(provider_key)
        if provider is None:
            raise HTTPException(status_code=404, detail="SSO provider not configured")
        params = urlencode(
            {
                "client_id": provider.client_id,
                "response_type": "code",
                "redirect_uri": _sso_redirect_uri(provider_key),
                "scope": provider.scopes,
                "state": state_signer.encrypt(provider_key.encode()).decode(),
            }
        )
        return RedirectResponse(f"{provider.authorize_url}?{params}")

    @auth.get("/sso/{provider_key}/callback")
    async def sso_callback(
        provider_key: str, code: str = "", state: str = "", error: str = ""
    ) -> RedirectResponse:
        designer_url = sso.designer_url()

        def fail(message: str) -> RedirectResponse:
            return RedirectResponse(f"{designer_url}/#{urlencode({'sso_error': message})}")

        provider = providers.get(provider_key)
        if provider is None:
            return fail("SSO provider not configured")
        if error:
            return fail(error)
        try:
            state_ok = state_signer.decrypt(state.encode(), ttl=600).decode() == provider_key
        except (InvalidToken, ValueError):
            state_ok = False
        if not code or not state_ok:
            return fail("invalid or expired SSO state")
        try:
            email = await sso.fetch_user_email(provider, code, _sso_redirect_uri(provider_key))
        except Exception as exc:  # noqa: BLE001 — surface provider errors to the login screen
            return fail(f"SSO failed: {exc}")

        user = db.get_user(email)
        if user is None and sso.auto_provision_enabled():
            users.create(email, new_id() + new_id(), "editor")  # random unusable password
            user = db.get_user(email)
        if user is None or user["disabled"]:
            return fail(f"no active user for {email}; ask an admin to add you")
        session = users.issue_token(user["username"], user["role"])
        fragment = urlencode({"sso": session, "user": user["username"], "role": user["role"]})
        return RedirectResponse(f"{designer_url}/#{fragment}")

    # -- users (admin only) --------------------------------------------------------

    @api.get("/users", dependencies=[Depends(require_admin)])
    def list_users() -> list[dict[str, Any]]:
        return users.list()

    @api.post("/users", dependencies=[Depends(require_admin)])
    def create_user(body: UserCreateRequest) -> dict[str, Any]:
        try:
            return users.create(body.username.strip(), body.password, body.role)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    @api.put("/users/{username}", dependencies=[Depends(require_admin)])
    def update_user(username: str, body: UserUpdateRequest) -> dict[str, Any]:
        try:
            updated = users.update(username, password=body.password, role=body.role, disabled=body.disabled)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        if updated is None:
            raise HTTPException(status_code=404, detail="user not found")
        return updated

    @api.get("/users/directory")
    def user_directory(emails_only: bool = True) -> list[str]:
        """Active usernames, for the pickers an editor is allowed to use.

        Names only — someone choosing who to notify, or who to share a process
        with, has no business seeing roles or account status, which is what
        ``/users`` (admin-only) is for. ``emails_only`` is the default because
        the notification picker can only address a mailbox; the share picker
        passes ``false``, since sharing works for any account."""
        return [
            user["username"]
            for user in users.list()
            if not user["disabled"]
            and (not emails_only or EMAIL_PATTERN.fullmatch(user["username"]))
        ]

    @api.delete("/users/{username}", dependencies=[Depends(require_admin)])
    def delete_user(username: str) -> dict[str, bool]:
        if not users.delete(username):
            raise HTTPException(status_code=404, detail="user not found")
        return {"deleted": True}

    # -- notification relay (read by anyone, changed by admins) ---------------------

    @api.get("/notifications/mail")
    def get_mail_settings() -> dict[str, Any]:
        """The relay, minus the password. Readable by editors so the designer
        can warn that a process asking for email has nowhere to send it."""
        return mail_settings.public()

    @api.put("/notifications/mail", dependencies=[Depends(require_admin)])
    def set_mail_settings(body: MailSettingsRequest) -> dict[str, Any]:
        if body.provider not in ("smtp", "ses"):
            raise HTTPException(status_code=422, detail="provider must be smtp or ses")
        if body.encryption not in ("starttls", "ssl", "none"):
            raise HTTPException(status_code=422, detail="encryption must be starttls, ssl or none")
        current = mail_settings.get()
        mail_settings.save(
            MailSettings(
                enabled=body.enabled,
                provider=body.provider,
                sender=body.sender.strip(),
                host=body.host.strip(),
                port=body.port,
                encryption=body.encryption,
                username=body.username.strip(),
                region=body.region.strip(),
                access_key_id=body.access_key_id.strip(),
                configuration_set=body.configuration_set.strip(),
                # None means "unchanged"; "" is an explicit clear, for a relay
                # that went from authenticated to open (or from keys to a role)
                password=current.password if body.password is None else body.password,
                secret_access_key=(
                    current.secret_access_key if body.secret_access_key is None else body.secret_access_key
                ),
            )
        )
        return mail_settings.public()

    @api.post("/notifications/test", dependencies=[Depends(require_admin)])
    async def send_test_email(body: TestEmailRequest, request: Request) -> dict[str, str]:
        address = body.to.strip() or request.state.principal.get("name", "")
        if not EMAIL_PATTERN.fullmatch(address):
            raise HTTPException(status_code=422, detail=f"{address or 'that'} is not an email address")
        try:
            await notifier.send_test(address)
        except Exception as exc:  # noqa: BLE001 — the relay's own words are the useful part
            raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from None
        return {"sent_to": address}

    # -- process access ----------------------------------------------------------
    # An admin sees everything. Anyone else sees what they created and what has
    # been shared with them; sharing carries the same rights, including the right
    # to share on, which is what makes a team able to hand work over without an
    # admin in the loop.

    def _may_access(definition: ProcessDefinition, principal: dict[str, Any]) -> bool:
        if principal.get("role") == "admin":
            return True
        name = principal.get("name", "")
        return bool(name) and (definition.created_by == name or name in definition.shared_with)

    def _get_or_404(process_id: str, request: Request) -> ProcessDefinition:
        """The process, if the caller is allowed to know it exists.

        No-access is a 404 rather than a 403 on purpose: a 403 would confirm the
        id belongs to a real process, which is a listing of other people's work.
        """
        definition = db.get_process(process_id)
        if definition is None or not _may_access(definition, request.state.principal):
            raise HTTPException(status_code=404, detail="process not found")
        return definition

    # -- plugins -------------------------------------------------------------------

    @api.get("/plugins")
    def list_plugins() -> list[dict[str, Any]]:
        return registry.manifests()

    # -- workspace -------------------------------------------------------------------

    @api.get("/workspace", dependencies=[Depends(require_admin)])
    def get_workspace() -> dict[str, Any]:
        """The folder file plugins are confined to — read-only on purpose.

        It is deployment configuration (``PROCESS_ENGINE_WORK_DIR``), so nobody
        signed in to the designer can widen the sandbox their steps run inside.
        """
        return workspace.describe()

    # -- processes -------------------------------------------------------------------

    @api.post("/processes", response_model=ProcessDefinition)
    def create_process(definition: ProcessDefinition, request: Request) -> ProcessDefinition:
        # a process is saved with a single canonical name per step, because other
        # steps resolve against that name in "{{ steps.foo.output }}".
        details = validate_detailed(definition, registry)
        dupes = [entry["message"] for entry in details if "duplicate step name" in entry["message"].lower()]
        if dupes:
            raise HTTPException(status_code=422, detail={"issues": dupes})
        # the creator is whoever called, never whatever the client sent: it is an
        # identity, and notifications are addressed to it
        definition.created_by = request.state.principal.get("name", "")
        return db.save_process(definition)

    def _visible_processes(request: Request) -> list[dict[str, Any]]:
        """The listing rows this caller is allowed to see.

        ``created_by``/``shared_with`` live in the definition document, which
        ``list_processes`` already has in hand — so this filters without a second
        read, the same way ``folder`` is pulled out of the document.
        """
        principal = request.state.principal
        if principal.get("role") == "admin":
            return db.list_processes()
        name = principal.get("name", "")
        return [
            entry
            for entry in db.list_processes()
            if name and (entry["created_by"] == name or name in entry["shared_with"])
        ]

    @api.get("/processes")
    def list_processes(request: Request, folder: str | None = None) -> list[dict[str, Any]]:
        entries = _visible_processes(request)
        if folder is not None:
            entries = [entry for entry in entries if entry["folder"] == folder]
        return entries

    @api.get("/folders")
    def list_folders(request: Request) -> list[dict[str, Any]]:
        """Folders in use, with how many processes each holds.

        Counts only what the caller can see, so a folder does not advertise
        other people's work by being one larger than the list under it.
        """
        counts: dict[str, int] = {}
        for entry in _visible_processes(request):
            counts[entry["folder"]] = counts.get(entry["folder"], 0) + 1
        return [
            {"name": name, "count": count}
            for name, count in sorted(counts.items(), key=lambda item: (item[0] == "", item[0].lower()))
        ]

    @api.put("/processes/{process_id}/folder")
    def move_process(process_id: str, body: FolderRequest, request: Request) -> dict[str, str]:
        definition = _get_or_404(process_id, request)
        definition.folder = body.folder.strip()
        db.save_process(definition)
        return {"id": process_id, "folder": definition.folder}

    @api.get("/processes/{process_id}", response_model=ProcessDefinition)
    def get_process(process_id: str, request: Request) -> ProcessDefinition:
        return _get_or_404(process_id, request)

    @api.put("/processes/{process_id}", response_model=ProcessDefinition)
    def update_process(process_id: str, definition: ProcessDefinition, request: Request) -> ProcessDefinition:
        existing = _get_or_404(process_id, request)
        definition.id = process_id
        details = validate_detailed(definition, registry)
        dupes = [entry["message"] for entry in details if "duplicate step name" in entry["message"].lower()]
        if dupes:
            raise HTTPException(status_code=422, detail={"issues": dupes})
        # the designer PUTs the canvas it holds, which knows nothing about who
        # created the process or who it is shared with — carry both over rather
        # than let a save erase them, or let a client grant itself access
        definition.created_by = existing.created_by
        definition.shared_with = existing.shared_with
        return db.save_process(definition)

    @api.post("/processes/{process_id}/share", response_model=ProcessDefinition)
    def share_process(process_id: str, body: ShareRequest, request: Request) -> ProcessDefinition:
        """Set who this process is shared with, by username.

        Anyone who can reach the process can share it on — access is flat, so
        being shared in carries the same rights as creating it. The creator is
        never listed: they hold it by ownership, and removing them from a share
        list must not be able to lock them out.
        """
        definition = _get_or_404(process_id, request)
        known = {user["username"] for user in users.list() if not user["disabled"]}
        unknown = [name for name in body.usernames if name not in known]
        if unknown:
            raise HTTPException(status_code=422, detail=f"unknown or disabled user(s): {', '.join(unknown)}")
        definition.shared_with = sorted({name for name in body.usernames if name != definition.created_by})
        return db.save_process(definition)

    @api.post("/processes/{process_id}/clone", response_model=ProcessDefinition)
    def clone_process(
        process_id: str, request: Request, body: CloneRequest | None = None
    ) -> ProcessDefinition:
        """Copy a draft into a new process. Triggers come across disabled — see
        Database.clone_process. The copy belongs to whoever cloned it and starts
        unshared: inheriting the original's share list would hand its audience a
        process they never agreed to follow."""
        _get_or_404(process_id, request)  # 404 unless the caller can see the original
        body = body or CloneRequest()
        clone = db.clone_process(
            process_id,
            name=body.name,
            folder=body.folder,
            created_by=request.state.principal.get("name", ""),
        )
        if clone is None:
            raise HTTPException(status_code=404, detail="process not found")
        return clone

    @api.delete("/processes/{process_id}")
    def delete_process(process_id: str, request: Request) -> dict[str, bool]:
        _get_or_404(process_id, request)  # 404 for a process this caller cannot see
        if not db.delete_process(process_id):
            raise HTTPException(status_code=404, detail="process not found")
        return {"deleted": True}

    @api.post("/processes/{process_id}/validate")
    def validate_process(process_id: str, request: Request) -> dict[str, Any]:
        detailed = validate_detailed(_get_or_404(process_id, request), registry)
        return {"issues": [entry["message"] for entry in detailed], "detailed": detailed}

    @api.post("/processes/{process_id}/publish", response_model=ProcessDefinition)
    def publish_process(process_id: str, request: Request) -> ProcessDefinition:
        issues = validate(_get_or_404(process_id, request), registry)
        if issues:
            raise HTTPException(status_code=422, detail={"issues": issues})
        published = db.publish_process(process_id)
        assert published is not None  # existence checked above
        return published

    # -- runs -------------------------------------------------------------------------

    @api.post("/processes/{process_id}/run")
    def run_process(process_id: str, body: RunRequest, request: Request) -> dict[str, Any]:
        """Queue a run of this process and answer with it.

        There is no foreground run: nothing executes on this host, so asking for
        one publishes a job and returns the PENDING instance an engine host will
        claim. The reply is an instance either way, so a client that polls the
        run (as the designer does) needs no special case — and a step that needs
        Windows works from the Run button like any other.

        The definition is validated here rather than left to the worker, so an
        impossible run is a 422 in front of the person who asked instead of a
        failed run they have to go and read.
        """
        if body.draft:
            definition = _get_or_404(process_id, request)
        else:
            definition = db.get_version(process_id, body.version)
            if definition is None:
                _get_or_404(process_id, request)  # 404 when the process itself is missing
                raise HTTPException(
                    status_code=409,
                    detail="process has no published version; publish it or run with draft=true",
                )
        issues = validate(definition, registry)
        if issues:
            raise HTTPException(status_code=422, detail={"issues": issues})
        rid = enqueue_run(db, definition, trigger_input=body.trigger_input, variables=body.variables)
        queued_run = db.get_instance(rid)
        if queued_run is not None:
            return queued_run.model_dump(mode="json")
        return {"id": rid, "process_id": definition.id, "status": "pending", "queued": True}

    @api.get("/processes/{process_id}/runs")
    def list_runs(process_id: str, request: Request) -> list[dict[str, Any]]:
        _get_or_404(process_id, request)
        return db.list_instances(process_id)

    def _run_or_404(run_id: str, request: Request) -> ProcessInstance:
        """A run, if the caller may see the process that produced it.

        Run history is as revealing as the definition — step outputs, inputs and
        errors — so it inherits the process's access rather than being reachable
        by anyone who knows a run id.
        """
        instance = db.get_instance(run_id)
        if instance is None:
            raise HTTPException(status_code=404, detail="run not found")
        definition = db.get_process(instance.process_id) or db.get_version(instance.process_id)
        if definition is not None and not _may_access(definition, request.state.principal):
            raise HTTPException(status_code=404, detail="run not found")
        return instance

    def _recent_instance(process_id: str, run_id: str | None):
        if run_id:
            return db.get_instance(run_id)
        for entry in db.list_instances(process_id):  # newest first
            candidate = db.get_instance(entry["id"])
            if candidate is not None and candidate.step_runs:
                return candidate
        return None

    @api.get("/processes/{process_id}/steps/{step_id}/input")
    def step_input(process_id: str, step_id: str, request: Request, run_id: str | None = None) -> dict[str, Any]:
        """The actual values reaching this step: the trigger payload, each
        connected upstream step's recorded output, and the combined payload the
        engine would hand to the plugin."""
        definition = _get_or_404(process_id, request)
        if not any(step.id == step_id for step in definition.steps):
            raise HTTPException(status_code=404, detail="step not found in this process")
        instance = _recent_instance(process_id, run_id)
        runs = {run.step_id: run for run in (instance.step_runs if instance else [])}
        steps_by_id = {step.id: step for step in definition.steps}

        sources: list[dict[str, Any]] = []
        for conn in definition.connections:
            if conn.target != step_id:
                continue
            source = steps_by_id.get(conn.source)
            if source is None:
                continue
            run = runs.get(conn.source)
            sources.append(
                {
                    "step_id": conn.source,
                    "label": source.name or source.id,
                    "reference": reference_for(source),
                    "plugin": source.plugin,
                    "source_port": conn.source_port,
                    "target_port": conn.target_port,
                    "status": run.status.value if run else None,
                    "has_data": bool(run and conn.source_port in run.outputs),
                    "data": run.outputs.get(conn.source_port) if run else None,
                }
            )

        has_incoming = any(conn.target == step_id for conn in definition.connections)
        delivered = deliveries_from_run(definition, step_id, instance)
        effective, by_port = combine_deliveries(
            delivered, instance.trigger_input if instance else None, has_incoming
        )
        return {
            "run_id": instance.id if instance else None,
            "run_started_at": iso_utc(instance.started_at) if instance and instance.started_at else None,
            "trigger": instance.trigger_input if instance else None,
            "sources": sources,
            "effective_input": effective,
            "input_by_port": by_port,
        }

    @api.post("/processes/{process_id}/steps/{step_id}/preview")
    def preview_step(
        process_id: str, step_id: str, body: PreviewRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Ask an engine host to run just this step against a previous run's data.

        The plugin executes for real — side effects happen. Nothing is written
        to the run history.

        There is no plugin to call in this process, so this is the *request* half
        of an asynchronous request/reply: 202 with a ``preview_id``, and the
        caller polls the companion GET until a worker has answered. The answer
        has the shape ``engine.preview_result`` builds wherever it ran, so the
        Output tab cannot tell who produced it.
        """
        definition = _get_or_404(process_id, request)
        instance = _recent_instance(process_id, body.run_id)
        # the two checks the engine's preview_step would raise on, made here so
        # an impossible preview 422s at once instead of after a round trip
        step = next((s for s in definition.steps if s.id == step_id), None)
        if step is None:
            raise HTTPException(status_code=422, detail={"issues": [f"no step {step_id!r} in this process"]})
        if step.plugin not in registry:
            raise HTTPException(
                status_code=422, detail={"issues": [f"step uses unknown plugin {step.plugin!r}"]}
            )
        preview_id = enqueue_preview(
            db,
            definition,
            step_id,
            run_id=instance.id if instance else None,
            variables=body.variables,
            trigger_input=body.trigger_input,
        )
        response.status_code = 202
        return _preview_state(preview_id, {"job_id": preview_id, "status": "queued", "result": None})

    def _preview_state(preview_id: str, job: dict[str, Any]) -> dict[str, Any]:
        """A queued preview as the designer sees it: waiting, running, or answered.

        ``state`` is the job's lifecycle; the ``status`` inside a finished result
        is the step's own outcome. While waiting it also reports whether any
        worker is alive, because with the API executing nothing, "queued" and
        "nobody is out there to run this" look identical from a browser and only
        one of them is worth waiting for.
        """
        if job["status"] == "done":
            return {"state": "done", "preview_id": preview_id, **(job["result"] or {})}
        if job["status"] == "failed":
            return {
                "state": "failed",
                "preview_id": preview_id,
                "issues": (job["result"] or {}).get("issues", ["the worker could not run this step"]),
            }
        return {
            "state": "running" if job["status"] == "claimed" else "queued",
            "preview_id": preview_id,
            "worker": job.get("claimed_by"),
            "workers_online": len(db.list_workers(WORKER_STALE_SECONDS)),
        }

    @api.get("/processes/{process_id}/previews/{preview_id}")
    def preview_state(process_id: str, preview_id: str, request: Request) -> dict[str, Any]:
        """Collect a queued preview's answer, or report what it is waiting for."""
        _get_or_404(process_id, request)  # a preview is as revealing as the run
        job = db.get_job(preview_id)
        if job is None or job["kind"] != "preview":
            raise HTTPException(status_code=404, detail="preview not found")
        state = _preview_state(preview_id, job)
        if state["state"] in ("done", "failed"):
            db.finish_job(preview_id)  # collected; the reaper is only for the rest
        return state

    @api.get("/queue")
    def queue_status() -> dict[str, Any]:
        """How deep the queue is, and whether anything is out there to take it.

        Readable by any signed-in user on purpose: a run sitting at PENDING is
        the first thing an editor sees when no engine is running, and "ask an
        admin" is a worse answer than showing them. Hostnames stay in Settings —
        this is counts only. ``mode`` is always ``database``; it stays in the
        reply because a client should not have to know that to read the rest.
        """
        return {
            "mode": "database",
            "workers_online": len(db.list_workers(WORKER_STALE_SECONDS)),
            "queued": db.count_queued_jobs(),
        }

    @api.get("/workers", dependencies=[Depends(require_admin)])
    def list_workers() -> list[dict[str, Any]]:
        """The workers currently claiming jobs — deployment detail, so admin-only."""
        return db.list_workers(WORKER_STALE_SECONDS)

    @api.get("/processes/{process_id}/steps/{step_id}/picker")
    def step_data_picker(process_id: str, step_id: str, request: Request, run_id: str | None = None) -> dict[str, Any]:
        """Expressions this step can pull from: trigger data and every upstream
        step's outputs, with sample values from a recent run."""
        definition = _get_or_404(process_id, request)
        instance = None
        if run_id:
            instance = db.get_instance(run_id)
        else:
            recent = db.list_instances(process_id)
            for entry in recent:  # newest first; prefer one that actually produced data
                candidate = db.get_instance(entry["id"])
                if candidate is not None and candidate.step_runs:
                    instance = candidate
                    break
        return {
            "run_id": instance.id if instance else None,
            "groups": build_picker(definition, step_id, instance, registry),
        }

    @api.get("/runs/{run_id}", response_model=ProcessInstance)
    def get_run(run_id: str, request: Request) -> ProcessInstance:
        return _run_or_404(run_id, request)

    @api.post("/runs/{run_id}/pause")
    def pause_run(run_id: str, request: Request) -> dict[str, str]:
        instance = _run_or_404(run_id, request)
        if instance.status in (RunStatus.PENDING, RunStatus.RUNNING):
            # the run lives on an engine host, which polls run_signals between
            # steps — that table is how a request crosses the machine boundary
            db.set_run_signal(run_id, "pause")
            return {"id": run_id, "status": "pausing"}
        raise HTTPException(status_code=409, detail=f"run is {instance.status}; only an active run can pause")

    @api.post("/runs/{run_id}/resume")
    def resume_run(run_id: str, request: Request) -> dict[str, str]:
        instance = _run_or_404(run_id, request)
        if instance.status != RunStatus.PAUSED:
            raise HTTPException(status_code=409, detail=f"run is {instance.status}; only paused runs can resume")
        definition = db.get_version(instance.process_id, instance.process_version) or db.get_process(instance.process_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="process definition no longer exists")
        enqueue_resume(db, definition, instance)
        return {"id": run_id, "status": "running"}

    # async so the notification below is scheduled on the running loop rather
    # than in the sync-route threadpool, which has none
    @api.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str, request: Request) -> dict[str, str]:
        instance = _run_or_404(run_id, request)
        if instance.status in (RunStatus.PENDING, RunStatus.RUNNING):
            # the run is on an engine host, or still queued for one; the signal
            # reaches it between steps, or the moment it is claimed
            db.set_run_signal(run_id, "cancel")
            return {"id": run_id, "status": "cancelling"}
        if instance.status is RunStatus.PAUSED:
            # a paused run is on nobody's queue, so this is the one run this host
            # can end by itself: no signal to send, just the record
            instance.status = RunStatus.CANCELLED
            instance.finished_at = utcnow()
            db.save_instance(instance)
            # it ended here rather than on an engine host, so notify from here
            definition = db.get_version(instance.process_id, instance.process_version) or db.get_process(
                instance.process_id
            )
            event = event_for(definition.notifications, RunStatus.CANCELLED) if definition else None
            if event is not None:
                _notify(definition, instance, event)
            return {"id": run_id, "status": "cancelled"}
        raise HTTPException(status_code=409, detail=f"run already {instance.status}")

    # -- secrets (names only; values are write-only and encrypted at rest) -----------

    @api.get("/secrets")
    def list_secrets() -> list[str]:
        return secrets.names()

    @api.put("/secrets/{name}")
    def set_secret(name: str, body: SecretRequest) -> dict[str, str]:
        secrets.set(name, body.value)
        return {"name": name, "status": "stored"}

    @api.delete("/secrets/{name}")
    def delete_secret(name: str) -> dict[str, bool]:
        if not secrets.delete(name):
            raise HTTPException(status_code=404, detail="secret not found")
        return {"deleted": True}

    # -- webhooks (public capability URLs) ----------------------------------------------

    @hooks.post("/{slug}")
    async def fire_webhook(slug: str, request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001 — empty or non-JSON bodies are allowed
            payload = None
        for definition in db.latest_published_definitions():
            for trigger in definition.triggers:
                if trigger.type != "webhook" or not trigger.enabled:
                    continue
                if (trigger.path or definition.id) == slug:
                    rid = enqueue_run(db, definition, trigger_input=payload)
                    return {"run_id": rid, "process_id": definition.id, "status": "accepted"}
        raise HTTPException(status_code=404, detail="no webhook registered for this path")

    app.include_router(auth)
    app.include_router(api)
    app.include_router(hooks)
    _mount_docs(app)  # before the designer: its catch-all would swallow /help
    _mount_designer(app)
    return app


def _mount_docs(app: FastAPI) -> None:
    """Serve the handbooks (docs/) at /help when they are deployed alongside.

    The designer links the guided tour's long form from its own tour, so the
    document has to be reachable from the same origin. Read-only static files,
    unauthenticated like the landing page — they describe the product, not this
    installation's data. ``/docs`` is FastAPI's own OpenAPI UI, hence ``/help``.
    """
    folder = Path(os.environ.get("PROCESS_ENGINE_DOCS_DIR", "docs"))
    if not folder.is_dir():
        return

    app.mount("/help", StaticFiles(directory=folder), name="help")
    logger.info("serving the documentation from %s", folder.resolve())


def _designer_index() -> Path:
    """Where a built designer would be, served from this process."""
    return Path(os.environ.get("PROCESS_ENGINE_DESIGNER_DIST", "designer/dist")) / "index.html"


def _mount_designer(app: FastAPI) -> None:
    """Serve the built designer (designer/dist) from the API when present.

    Gives a single-origin deployment: landing page, designer and API on one
    port. In development the Vite dev server serves the UI instead and proxies
    /api here, so this quietly does nothing.
    """
    index = _designer_index()
    dist = index.parent
    if not index.is_file():
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        # An unknown /api path is a client error, not a client-side route. This
        # catch-all is registered last, so without the guard it answers a
        # mistyped or retired endpoint with the index page and a 200 — and a
        # health check pointed at a route that does not exist would pass.
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="no such API route")
        # static file if it exists, otherwise index.html so client-side routes work
        candidate = dist / full_path
        if full_path and candidate.is_file() and dist.resolve() in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(index)

    logger.info("serving the designer from %s", dist.resolve())
