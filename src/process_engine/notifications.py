"""Email people about a run: started, succeeded, failed, or simply finished.

A notification is not a step. A ``send_email`` step exists because the process
*author* wanted mail sent as part of the work; a notification goes out because
somebody wants to know how the process itself is doing, whether or not it has
an email step in it. That difference decides the whole shape of this module:

* The **transport** is deployment-wide — one relay, configured once by an admin
  under Settings › Notifications and stored here (an SMTP server or Amazon SES;
  credentials encrypted at rest with the same Fernet key as the secrets
  manager). Steps keep their own mail settings; nothing shared, nothing to
  migrate.
* The **subscription** is per process — ``ProcessDefinition.notifications``
  says which events matter and who hears about them.

A finished run produces exactly one email, under the most specific event the
process subscribed to (:func:`event_for`), so asking for both "succeeded" and
"finished" is not two messages about the same run.

Delivery is best effort by design. The engine has already done the work by the
time anything here runs, so a relay that is down, misconfigured or merely slow
must never fail a run or hold up an API response: :meth:`Notifier.deliver`
logs and returns instead of raising, and the API dispatches it as a background
task. The one exception is :meth:`Notifier.send_test`, which raises so the
admin pressing "Send test email" is told exactly what went wrong.
"""

from __future__ import annotations

import asyncio
import logging
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import getaddresses
from html import escape
from typing import Any, Callable, Literal

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field

from . import sso
from .models import (
    NotificationEvent,
    NotificationSettings,
    ProcessDefinition,
    ProcessInstance,
    RunStatus,
)
from .security import resolve_fernet_key
from .storage import Database

logger = logging.getLogger("process_engine.notifications")

#: Key the relay settings are stored under in the ``settings`` table.
MAIL_SETTINGS_KEY = "notification_mail"

#: Deliberately loose — enough to tell an address from a username like "admin",
#: not an attempt to out-parse RFC 5322.
EMAIL_PATTERN = re.compile(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+")

#: How a finished run may be reported, most specific first. A status missing
#: here (PAUSED, and RUNNING mid-flight) ends no run, so it notifies nobody.
FINISHED_EVENTS: dict[RunStatus, tuple[NotificationEvent, ...]] = {
    RunStatus.SUCCEEDED: (NotificationEvent.SUCCEEDED, NotificationEvent.COMPLETED),
    RunStatus.FAILED: (NotificationEvent.FAILED, NotificationEvent.COMPLETED),
    RunStatus.CANCELLED: (NotificationEvent.COMPLETED,),
}

#: Subject-line wording per outcome, and the accent colour of the HTML banner.
_WORDING: dict[str, tuple[str, str]] = {
    RunStatus.RUNNING.value: ("started", "#2563eb"),
    RunStatus.SUCCEEDED.value: ("succeeded", "#16a34a"),
    RunStatus.FAILED.value: ("failed", "#dc2626"),
    RunStatus.CANCELLED.value: ("was cancelled", "#c2410c"),
    RunStatus.PAUSED.value: ("was paused", "#ca8a04"),
}


class MailSettings(BaseModel):
    """The relay notification email is sent through: an SMTP server or Amazon SES.

    Mirrors the ``send_email_smtp`` / ``send_email_ses`` steps' server fields on
    purpose — an admin who has configured one of those already knows how to fill
    this in. ``sender`` is common to both; the rest is per provider.
    """

    enabled: bool = True
    provider: Literal["smtp", "ses"] = "smtp"
    sender: str = ""

    # SMTP
    host: str = ""
    port: int = Field(default=587, ge=1, le=65535)
    encryption: Literal["starttls", "ssl", "none"] = "starttls"
    username: str = ""
    password: str = ""

    # Amazon SES. Leaving the keys blank uses the ambient boto3 credential chain
    # (instance role, shared config, environment) — the better choice inside AWS.
    region: str = "us-east-1"
    access_key_id: str = ""
    secret_access_key: str = ""
    configuration_set: str = ""

    @property
    def configured(self) -> bool:
        """Enough to send with: somewhere to send it, and someone to send it as."""
        if not self.sender.strip():
            return False
        if self.provider == "ses":
            return bool(self.region.strip())  # credentials may come from the role
        return bool(self.host.strip())

    @property
    def active(self) -> bool:
        """Configured *and* switched on — the check before sending anything."""
        return self.enabled and self.configured


#: Credentials: Fernet-encrypted before they reach the database, and never
#: returned by the API — :meth:`MailSettingsStore.public` reports only whether
#: each one is set.
SECRET_FIELDS = ("password", "secret_access_key")


class MailSettingsStore:
    """Reads and writes :class:`MailSettings`, keeping credentials encrypted.

    Everything except :data:`SECRET_FIELDS` is stored as plain JSON, so the row
    stays readable/debuggable; the credentials are the only values that never
    leave the server.
    """

    def __init__(self, db: Database, key: str | bytes | None = None) -> None:
        self.db = db
        self._fernet = Fernet(key or resolve_fernet_key())

    def get(self) -> MailSettings:
        """The stored relay, or an empty (unconfigured) one."""
        raw = self.db.get_setting(MAIL_SETTINGS_KEY)
        if not raw:
            return MailSettings()
        data = dict(raw)
        credentials: dict[str, str] = {}
        for field in SECRET_FIELDS:
            token = data.pop(f"{field}_encrypted", "") or ""
            data.pop(field, None)  # never stored in clear; ignore it if it ever was
            if not token:
                continue
            try:
                credentials[field] = self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
            except (InvalidToken, ValueError, UnicodeDecodeError):
                # a rotated PROCESS_ENGINE_SECRET_KEY orphans it: say so rather
                # than silently authenticating with an empty string
                logger.error("stored mail %s could not be decrypted — re-enter it in Settings", field)
        settings = MailSettings.model_validate(data)
        for field, value in credentials.items():
            setattr(settings, field, value)
        return settings

    def save(self, settings: MailSettings) -> MailSettings:
        data = settings.model_dump()
        for field in SECRET_FIELDS:
            value = data.pop(field, "") or ""
            data[f"{field}_encrypted"] = (
                self._fernet.encrypt(value.encode("utf-8")).decode("ascii") if value else ""
            )
        self.db.set_setting(MAIL_SETTINGS_KEY, data)
        return settings

    def public(self) -> dict[str, Any]:
        """What the API may hand back: everything except the credentials."""
        settings = self.get()
        data = settings.model_dump(exclude=set(SECRET_FIELDS))
        return {
            **data,
            **{f"{field}_set": bool(getattr(settings, field)) for field in SECRET_FIELDS},
            "configured": settings.configured,
            "active": settings.active,
        }


# -- who hears about it, and when ------------------------------------------------


def event_for(settings: NotificationSettings, status: RunStatus) -> NotificationEvent | None:
    """The single event a finished run is reported under, or None for silence.

    Most specific first: a failed run belonging to a process subscribed to both
    ``failed`` and ``completed`` is reported as ``failed`` — one email, worded
    for what actually happened.
    """
    for event in FINISHED_EVENTS.get(status, ()):
        if event in settings.events:
            return event
    return None


def recipients_for(definition: ProcessDefinition) -> list[str]:
    """Addresses to notify about this process, in a stable, de-duplicated order.

    The creator is stored as a username, which is an email address for anyone
    signed in through SSO but need not be for a locally created account (or the
    ``api-token`` principal). Anything that is not an address is dropped rather
    than handed to the relay as a bad recipient.
    """
    settings = definition.notifications
    candidates: list[str] = []
    if settings.notify_creator and definition.created_by:
        candidates.append(definition.created_by)
    candidates.extend(settings.recipients)

    seen: set[str] = set()
    addresses: list[str] = []
    for candidate in candidates:
        address = (candidate or "").strip()
        if not EMAIL_PATTERN.fullmatch(address) or address.lower() in seen:
            continue
        seen.add(address.lower())
        addresses.append(address)
    return addresses


# -- the message ------------------------------------------------------------------


def _stamp(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(timezone.utc).strftime("%d %b %Y %H:%M:%S UTC")


def _duration(instance: ProcessInstance) -> str:
    if instance.started_at is None or instance.finished_at is None:
        return "—"
    seconds = (instance.finished_at - instance.started_at).total_seconds()
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes} min {seconds} s"


def _failure(instance: ProcessInstance) -> tuple[str, str] | None:
    """(step label, error) of the step that ended the run, when one did."""
    for run in instance.step_runs:
        if run.status == RunStatus.FAILED and run.error:
            return run.step_name or run.step_id, run.error
    return None


def render(
    definition: ProcessDefinition,
    instance: ProcessInstance,
    event: NotificationEvent,
    base_url: str = "",
) -> tuple[str, str, str]:
    """Build ``(subject, plain text, html)`` for one notification.

    Worded from the run's *status*, not from the event: someone subscribed to
    "finished" still wants a mail that says the run failed. The two bodies say
    the same thing — the HTML one is what almost every client will show, the
    text one is what the rest (and any archive grep) get.
    """
    status = instance.status.value
    verb, accent = _WORDING.get(status, (status, "#475569"))
    name = definition.name or "Untitled process"
    subject = f"{name} — run {verb}"

    link = f"{base_url}/app/runs?run={instance.id}" if base_url else ""
    failure = _failure(instance)
    rows: list[tuple[str, str]] = [
        ("Process", name),
        ("Folder", definition.folder or "Uncategorized"),
        ("Version", str(instance.process_version)),
        ("Run", instance.id),
        ("Started", _stamp(instance.started_at)),
    ]
    if event is not NotificationEvent.STARTED:
        rows.append(("Finished", _stamp(instance.finished_at)))
        rows.append(("Duration", _duration(instance)))
    if failure:
        rows.append(("Failed step", failure[0]))
    if instance.error:
        rows.append(("Error", instance.error))

    text_lines = [f"{name} — run {verb}.", ""]
    text_lines += [f"{label}: {value}" for label, value in rows]
    if link:
        text_lines += ["", f"Open the run: {link}"]
    text = "\n".join(text_lines) + "\n"

    cells = "".join(
        f'<tr><td style="padding:6px 16px 6px 0;color:#64748b;white-space:nowrap;'
        f'vertical-align:top">{escape(label)}</td>'
        f'<td style="padding:6px 0;color:#0f172a;word-break:break-word">{escape(value)}</td></tr>'
        for label, value in rows
    )
    button = (
        f'<p style="margin:24px 0 0"><a href="{escape(link)}" '
        f'style="display:inline-block;padding:9px 16px;border-radius:8px;background:{accent};'
        f'color:#ffffff;text-decoration:none;font-weight:600">Open the run</a></p>'
        if link
        else ""
    )
    html = (
        '<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;'
        'font-size:14px;line-height:1.5;color:#0f172a">'
        f'<p style="margin:0 0 4px;font-size:16px;font-weight:700">'
        f'<span style="color:{accent}">●</span> {escape(name)} — run {escape(verb)}</p>'
        '<table style="border-collapse:collapse;margin-top:12px">'
        f"{cells}</table>{button}"
        '<p style="margin:24px 0 0;font-size:12px;color:#94a3b8">'
        "You are on this process's notification list. Change it in the designer, "
        "on the process itself.</p></div>"
    )
    return subject, text, html


def build_message(
    settings: MailSettings, to: list[str], subject: str, text: str, html: str
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.sender
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message["Auto-Submitted"] = "auto-generated"  # keeps out-of-office replies away
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def smtp_send(settings: MailSettings, message: EmailMessage) -> None:
    """Blocking SMTP delivery. Raises whatever smtplib raises."""
    smtp_cls = smtplib.SMTP_SSL if settings.encryption == "ssl" else smtplib.SMTP
    with smtp_cls(settings.host, settings.port, timeout=30) as smtp:
        if settings.encryption == "starttls":
            smtp.starttls()
        if settings.username:
            smtp.login(settings.username, settings.password)
        smtp.send_message(message)


def ses_send(settings: MailSettings, message: EmailMessage) -> None:
    """Blocking delivery through the Amazon SES v2 API. Raises what boto3 raises.

    Sent as raw MIME so SES carries byte-for-byte what SMTP would have: same
    multipart/alternative, same headers, one code path building the message.
    """
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover — depends on the install extras
        raise RuntimeError(
            "boto3 is required to send notifications through SES: pip install process-engine[aws]"
        ) from exc

    kwargs: dict[str, Any] = {"region_name": settings.region}
    if settings.access_key_id and settings.secret_access_key:
        kwargs["aws_access_key_id"] = settings.access_key_id
        kwargs["aws_secret_access_key"] = settings.secret_access_key
    client = boto3.client("sesv2", **kwargs)

    request: dict[str, Any] = {
        "FromEmailAddress": settings.sender,
        # SES takes the envelope recipients separately from the headers
        "Destination": {"ToAddresses": [address for _, address in getaddresses(message.get_all("To", []))]},
        "Content": {"Raw": {"Data": message.as_bytes()}},
    }
    if settings.configuration_set:
        request["ConfigurationSetName"] = settings.configuration_set
    client.send_email(**request)


def send_message(settings: MailSettings, message: EmailMessage) -> None:
    """Deliver through whichever provider is configured."""
    if settings.provider == "ses":
        ses_send(settings, message)
    else:
        smtp_send(settings, message)


class Notifier:
    """Turns a run event into an email, if anyone asked for one.

    ``send`` is injectable so tests (and any future transport) can stand in for
    SMTP; ``public_url`` resolves the base URL used for the "Open the run"
    link, shared with SSO because it is the same question — what URL does the
    browser reach this deployment on.
    """

    def __init__(
        self,
        store: MailSettingsStore,
        send: Callable[[MailSettings, EmailMessage], None] = send_message,
        public_url: Callable[[], str] = sso.public_url,
    ) -> None:
        self.store = store
        self.send = send
        self.public_url = public_url

    async def deliver(
        self, definition: ProcessDefinition, instance: ProcessInstance, event: NotificationEvent
    ) -> list[str]:
        """Send one notification; return the addresses it reached.

        Returns an empty list — never raises — when the process is not
        subscribed to this event, has no valid recipient, or the relay is off
        or unreachable. The run is already over; nothing here may disturb it.
        """
        try:
            if event not in definition.notifications.events:
                return []
            recipients = recipients_for(definition)
            if not recipients:
                return []
            settings = self.store.get()
            if not settings.active:
                logger.warning(
                    "run %s wanted a %s notification but no mail relay is configured",
                    instance.id, event.value,
                )
                return []
            subject, text, html = render(definition, instance, event, self.public_url())
            message = build_message(settings, recipients, subject, text, html)
            await asyncio.to_thread(self.send, settings, message)
            logger.info("emailed %s about run %s (%s)", ", ".join(recipients), instance.id, event.value)
            return recipients
        except Exception:  # noqa: BLE001 — a notification must not break anything
            logger.exception("could not send the %s notification for run %s", event.value, instance.id)
            return []

    async def send_test(self, address: str) -> None:
        """Prove the relay works, straight from Settings. Raises on failure."""
        settings = self.store.get()
        if not settings.configured:
            raise ValueError("set a mail server and a From address first")
        message = build_message(
            settings,
            [address],
            "Process Engine test email",
            "This is a test message. Your notification relay is working.\n",
            '<div style="font-family:system-ui,sans-serif;font-size:14px">'
            "<p>This is a test message. Your notification relay is working.</p></div>",
        )
        await asyncio.to_thread(self.send, settings, message)
