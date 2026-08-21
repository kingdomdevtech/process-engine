"""HTTP API — what the designer (and any other client) talks to.

Authentication: every /api route requires ``Authorization: Bearer <token>``
(or ``X-API-Key``), except ``/api/hooks/*`` — webhook URLs are unguessable
capability URLs called by external systems. The token comes from
``PROCESS_ENGINE_AUTH_TOKEN`` (auto-generated into ``.process_engine_auth``
for development).

Create the app with ``create_app()`` or run ``python -m process_engine``.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import sso, workspace
from . import worker as run_worker

from .datapicker import build_picker, reference_for
from .engine import (
    DefinitionError,
    Engine,
    RunControl,
    combine_deliveries,
    deliveries_from_run,
    validate,
    validate_detailed,
)
from .models import (
    NotificationEvent,
    ProcessDefinition,
    ProcessInstance,
    RunStatus,
    new_id,
    utcnow,
)
from .notifications import (
    EMAIL_PATTERN,
    MailSettings,
    MailSettingsStore,
    Notifier,
    event_for,
)
from .registry import PluginRegistry, default_registry
from .scheduler import Scheduler
from .secrets_store import SecretsManager
from .security import resolve_auth_token, resolve_fernet_key
from .storage import Database, iso_utc
from .users import SESSION_TTL_SECONDS, UserManager

logger = logging.getLogger("process_engine.api")


class RunRequest(BaseModel):
    trigger_input: Any = None
    variables: dict[str, Any] = Field(default_factory=dict)
    draft: bool = False  # run the draft instead of the latest published version
    version: int | None = None  # pin a specific published version
    background: bool = False  # return immediately; poll GET /api/runs/{id}


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
    registry = registry or default_registry()
    secrets = SecretsManager(db)
    users = UserManager(db)
    mail_settings = MailSettingsStore(db)
    notifier = notifier or Notifier(mail_settings)
    engine = Engine(
        registry,
        definition_resolver=lambda process_id: db.get_version(process_id),
        secrets=secrets.view(),
        # size of the step worker-thread pool; 0/unset → ThreadPoolExecutor default
        step_workers=int(os.environ.get("PROCESS_ENGINE_STEP_WORKERS", "0")) or None,
    )
    token = auth_token or resolve_auth_token()
    # queue mode: background runs execute in N child processes (one GIL each),
    # so CPU-bound plugin work scales across cores. 0/unset keeps them in-process.
    run_workers = int(os.environ.get("PROCESS_ENGINE_RUN_WORKERS", "0"))
    worker_pool: ProcessPoolExecutor | None = None
    if run_workers > 0:
        worker_pool = ProcessPoolExecutor(
            max_workers=run_workers,
            initializer=run_worker.init_worker,
            mp_context=multiprocessing.get_context("spawn"),  # never fork a live event loop
        )
    controls: dict[str, RunControl] = {}
    pending: set[asyncio.Task] = set()  # in-flight notification sends, kept alive
    chains: dict[str, asyncio.Task] = {}  # run id -> its last send, so they stay in order

    # -- run execution helpers -------------------------------------------------

    def _persist(instance: ProcessInstance) -> None:
        try:
            db.save_instance(instance)
        except Exception:  # noqa: BLE001 — persistence must not kill the run
            logger.exception("failed to persist run %s", instance.id)

    def _notify(definition: ProcessDefinition, instance: ProcessInstance, event: NotificationEvent) -> None:
        """Send a run notification without making the run wait for the relay.

        Fire and forget, with two things pinned down before letting go:

        * The instance is *copied*. The engine goes on mutating the live one as
          the run proceeds, so a "started" email composed a moment later would
          otherwise describe a run that had already finished.
        * Sends for one run are chained, so its "started" email cannot overtake
          its "finished" one when the whole run takes less time than an SMTP
          handshake.

        ``deliver`` swallows its own errors; ``pending`` holds a reference only
        so the loop cannot garbage-collect a send half way through.
        """
        snapshot = instance.model_copy(deep=True)
        previous = chains.get(instance.id)

        async def send() -> None:
            if previous is not None:
                await previous
            await notifier.deliver(definition, snapshot, event)

        task = asyncio.create_task(send())
        chains[instance.id] = task
        pending.add(task)

        def finished(completed: asyncio.Task) -> None:
            pending.discard(completed)
            if chains.get(instance.id) is completed:
                chains.pop(instance.id, None)

        task.add_done_callback(finished)

    def _updater(definition: ProcessDefinition, *, resuming: bool):
        """The engine's ``on_update`` for one run: persist, and announce the start.

        The engine reports the instance once before any step runs, which is the
        moment a "started" email should go out — and the first point at which a
        real instance exists to describe. Sub-process runs (``for_each``) share
        this callback but carry a ``parent_run_id``; they stay silent, so one
        run the user started means one email, not one per iteration. A resumed
        run announced itself when it first began.
        """
        announced = resuming

        def on_update(instance: ProcessInstance) -> None:
            nonlocal announced
            _persist(instance)
            if not announced and instance.parent_run_id is None:
                announced = True
                _notify(definition, instance, NotificationEvent.STARTED)

        return on_update

    async def _execute(
        definition: ProcessDefinition,
        *,
        trigger_input: Any = None,
        variables: dict[str, Any] | None = None,
        instance: ProcessInstance | None = None,
        run_id: str | None = None,
    ) -> ProcessInstance:
        rid = instance.id if instance is not None else run_id
        control = RunControl()
        controls[rid] = control
        try:
            result = await engine.run(
                definition,
                trigger_input=trigger_input,
                variables=variables,
                instance=instance,
                run_id=run_id,
                on_update=_updater(definition, resuming=instance is not None),
                control=control,
            )
        finally:
            controls.pop(rid, None)
        # PAUSED ends nothing, so event_for stays quiet until the run really finishes
        event = event_for(definition.notifications, result.status)
        if event is not None:
            _notify(definition, result, event)
        return result

    def _log_dispatch(rid: str, future) -> None:
        exc = future.exception()  # the callback fires only once the future is done
        if exc is not None:
            logger.error("worker run %s failed to execute: %s", rid, exc)

    def _launch_background(
        definition: ProcessDefinition,
        *,
        trigger_input: Any = None,
        variables: dict[str, Any] | None = None,
        instance: ProcessInstance | None = None,
    ) -> str:
        rid = instance.id if instance is not None else new_id()

        if worker_pool is not None:
            if instance is None:
                # visible immediately as a queued run, and — because the worker
                # resumes it from this row — recoverable after a restart
                _persist(
                    ProcessInstance(
                        id=rid,
                        process_id=definition.id,
                        process_version=definition.version,
                        status=RunStatus.PENDING,
                        trigger_input=trigger_input,
                        variables={**definition.variables, **(variables or {})},
                    )
                )
            future = worker_pool.submit(
                run_worker.run_job,
                {
                    # snapshot at enqueue time, so a draft edited while queued
                    # still runs what the caller submitted
                    "definition": definition.model_dump(mode="json"),
                    "run_id": rid,
                    "resume": instance is not None,
                    "trigger_input": trigger_input,
                    "variables": variables,
                },
            )
            future.add_done_callback(lambda f, rid=rid: _log_dispatch(rid, f))
            return rid

        async def guarded() -> None:
            try:
                await _execute(
                    definition,
                    trigger_input=trigger_input,
                    variables=variables,
                    instance=instance,
                    run_id=None if instance is not None else rid,
                )
            except DefinitionError as exc:
                logger.error("background run %s failed validation: %s", rid, exc.issues)
            except Exception:  # noqa: BLE001
                logger.exception("background run %s crashed", rid)

        asyncio.create_task(guarded())
        return rid

    scheduler = Scheduler(db, lambda definition, trigger_input: _launch_background(definition, trigger_input=trigger_input))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        scheduler.start()
        # durability: resume runs interrupted by a restart. PENDING rows are
        # queue-mode placeholders whose job never started — re-dispatch those too.
        interrupted = [
            *db.get_instances_by_status(RunStatus.RUNNING.value),
            *db.get_instances_by_status(RunStatus.PENDING.value),
        ]
        for orphan in interrupted:
            definition = db.get_version(orphan.process_id, orphan.process_version) or db.get_process(orphan.process_id)
            if definition is None:
                continue
            logger.info("resuming run %s interrupted by restart", orphan.id)
            _launch_background(definition, instance=orphan)
        yield
        await scheduler.stop()
        if worker_pool is not None:
            # queued jobs are dropped here; their PENDING rows re-dispatch on
            # the next startup. Runs already in a worker finish on their own.
            worker_pool.shutdown(wait=False, cancel_futures=True)

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
        designer_url = sso.public_url()

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
    async def run_process(process_id: str, body: RunRequest, request: Request) -> dict[str, Any]:
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
        if body.background:
            issues = validate(definition, registry)
            if issues:
                raise HTTPException(status_code=422, detail={"issues": issues})
            rid = _launch_background(definition, trigger_input=body.trigger_input, variables=body.variables)
            return {"id": rid, "process_id": definition.id, "status": "running", "background": True}
        try:
            instance = await _execute(
                definition, trigger_input=body.trigger_input, variables=body.variables, run_id=new_id()
            )
        except DefinitionError as exc:
            raise HTTPException(status_code=422, detail={"issues": exc.issues}) from None
        return instance.model_dump(mode="json")

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
    async def preview_step(process_id: str, step_id: str, body: PreviewRequest, request: Request) -> dict[str, Any]:
        """Run just this step against a previous run's data and return its output.

        The plugin executes for real — side effects happen. Nothing is written
        to the run history.
        """
        definition = _get_or_404(process_id, request)
        instance = _recent_instance(process_id, body.run_id)
        try:
            step_run, step_input_payload, resolved = await engine.preview_step(
                definition, step_id, instance, variables=body.variables, trigger_input=body.trigger_input
            )
        except DefinitionError as exc:
            raise HTTPException(status_code=422, detail={"issues": exc.issues}) from None
        return {
            "status": step_run.status.value,
            "input": step_input_payload,
            "resolved_config": resolved,
            "outputs": step_run.outputs,
            "output": step_run.outputs.get("main"),
            "error": step_run.error,
            "attempts": step_run.attempts,
            "duration_ms": step_run.duration_ms,
            "based_on_run": instance.id if instance else None,
        }

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
        control = controls.get(run_id)
        if control is not None:
            control.pause_requested = True
            return {"id": run_id, "status": "pausing"}
        if worker_pool is not None and instance.status in (RunStatus.PENDING, RunStatus.RUNNING):
            # the run lives in a worker process; it polls run_signals between steps
            db.set_run_signal(run_id, "pause")
            return {"id": run_id, "status": "pausing"}
        raise HTTPException(status_code=409, detail="run is not active on this server")

    @api.post("/runs/{run_id}/resume")
    def resume_run(run_id: str, request: Request) -> dict[str, str]:
        instance = _run_or_404(run_id, request)
        if instance.status != RunStatus.PAUSED:
            raise HTTPException(status_code=409, detail=f"run is {instance.status}; only paused runs can resume")
        definition = db.get_version(instance.process_id, instance.process_version) or db.get_process(instance.process_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="process definition no longer exists")
        _launch_background(definition, instance=instance)
        return {"id": run_id, "status": "running"}

    # async so the notification below is scheduled on the running loop rather
    # than in the sync-route threadpool, which has none
    @api.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str, request: Request) -> dict[str, str]:
        instance = _run_or_404(run_id, request)
        control = controls.get(run_id)
        if control is not None:
            control.cancel_requested = True
            return {"id": run_id, "status": "cancelling"}
        if worker_pool is not None and instance.status in (RunStatus.PENDING, RunStatus.RUNNING):
            # the run lives in a worker process (or is still queued for one);
            # the signal reaches it between steps, or the moment it starts
            db.set_run_signal(run_id, "cancel")
            return {"id": run_id, "status": "cancelling"}
        if instance.status in (RunStatus.PAUSED, RunStatus.RUNNING):
            instance.status = RunStatus.CANCELLED
            instance.finished_at = utcnow()
            db.save_instance(instance)
            # ended here rather than inside _execute, so notify from here too
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
                    rid = _launch_background(definition, trigger_input=payload)
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


def _mount_designer(app: FastAPI) -> None:
    """Serve the built designer (designer/dist) from the API when present.

    Gives a single-origin deployment: landing page, designer and API on one
    port. In development the Vite dev server serves the UI instead and proxies
    /api here, so this quietly does nothing.
    """
    dist = Path(os.environ.get("PROCESS_ENGINE_DESIGNER_DIST", "designer/dist"))
    index = dist / "index.html"
    if not index.is_file():
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        # static file if it exists, otherwise index.html so client-side routes work
        candidate = dist / full_path
        if full_path and candidate.is_file() and dist.resolve() in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(index)

    logger.info("serving the designer from %s", dist.resolve())
