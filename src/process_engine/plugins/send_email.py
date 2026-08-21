"""Send an email over generic SMTP, with file attachments.

For Amazon SES use the dedicated ``send_email_ses`` plugin instead — it
speaks the SES API (IAM credentials, message ids, configuration sets).
This plugin remains the choice for Exchange/Office 365, Gmail SMTP, or any
in-house relay.

Keep credentials out of process definitions: store them in the secrets
manager and reference them, e.g. ``"password": "{{ secrets.smtp_password }}"``.

Two settings were folded away once the configuration form grew up, and the
before-validator below keeps definitions written against them working:

* ``use_tls`` / ``use_ssl`` — two booleans for what is really one choice, and
  nonsense when both were set. Now ``encryption``.
* ``html`` — sent ``body`` itself as text/html, which fought ``body_html``.
  Now such a config moves ``body`` into ``body_html``; the message becomes
  multipart/alternative with a short plain-text part, which every client that
  rendered the old single-part message still renders the same way.
"""

import asyncio
import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ..plugin import Plugin, PluginContext, PluginManifest
from ..ui import ui


class SendEmailConfig(BaseModel):
    host: str = Field(
        title="Mail server",
        description="The SMTP address of your email provider.",
        examples=["smtp.office365.com"],
        json_schema_extra=ui(group="Mail server"),
    )
    port: int = Field(
        default=587,
        title="Port",
        description="587 for STARTTLS, 465 for SSL/TLS. Your provider's setup page will say.",
        json_schema_extra=ui(group="Mail server"),
    )
    encryption: Literal["starttls", "ssl", "none"] = Field(
        default="starttls",
        title="Encryption",
        json_schema_extra=ui(
            group="Mail server",
            labels={
                "starttls": "STARTTLS — usually port 587",
                "ssl": "SSL/TLS — usually port 465",
                "none": "None — only for a trusted internal relay",
            },
        ),
    )
    username: str = Field(
        default="",
        title="Username",
        description="Leave blank if the server accepts mail without signing in.",
        examples=["reports@example.com"],
        json_schema_extra=ui(group="Mail server"),
    )
    password: str = Field(
        default="",
        title="Password",
        examples=["{{ secrets.smtp_password }}"],
        json_schema_extra=ui(group="Mail server", widget="password", secret=True),
    )

    sender: str = Field(
        title="From",
        description="The address the message is sent from. Most providers require one you own.",
        examples=["reports@example.com"],
        json_schema_extra=ui(group="Message", widget="email"),
    )
    to: list[str] = Field(
        min_length=1,
        title="To",
        examples=[["ops@example.com"]],
        json_schema_extra=ui(group="Message", widget="emails", add_label="Add recipient"),
    )
    cc: list[str] = Field(
        default_factory=list,
        title="Cc",
        description="Optional. Copied in, and visible to everyone else on the message.",
        json_schema_extra=ui(group="Message", widget="emails", add_label="Add recipient"),
    )
    bcc: list[str] = Field(
        default_factory=list,
        title="Bcc",
        description="Optional. Copied in without the other recipients seeing them.",
        json_schema_extra=ui(group="Message", widget="emails", add_label="Add recipient"),
    )
    subject: str = Field(
        default="",
        title="Subject",
        examples=["Order {{ trigger.id }} shipped"],
        json_schema_extra=ui(group="Message"),
    )
    body_html: str = Field(
        default="",
        title="Message",
        description="Write the message here. Insert values from earlier steps with the ƒx button.",
        json_schema_extra={
            "format": "html",  # the designer renders the rich-text editor for this
            **ui(group="Message"),
        },
    )
    body: str = Field(
        default="",
        title="Plain-text version",
        description="Shown by mail clients that cannot display formatting. Written for you if left blank.",
        json_schema_extra=ui(group="Message", advanced=True, widget="textarea"),
    )
    attachments: list[str] = Field(
        default_factory=list,
        title="Attachments",
        description="Full paths to files on the machine running the engine.",
        examples=[[r"C:\reports\sales.xlsx"]],
        json_schema_extra=ui(group="Message", advanced=True, widget="files", add_label="Add file"),
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_retired_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "encryption" not in data and ("use_ssl" in data or "use_tls" in data):
            if data.get("use_ssl"):
                data["encryption"] = "ssl"
            else:
                data["encryption"] = "starttls" if data.get("use_tls", True) else "none"
        if data.pop("html", False) and not data.get("body_html"):
            data["body_html"] = data.get("body") or ""
            data["body"] = ""
        data.pop("use_tls", None)
        data.pop("use_ssl", None)
        return data


class SendEmailPlugin(Plugin):
    manifest = PluginManifest(
        key="send_email_smtp",
        name="Send Email (SMTP)",
        description="Send an email through any SMTP server, optionally with attachments.",
        category="communication",
        aliases=["send_email"],  # definitions saved before the SES split still resolve
    )
    Config = SendEmailConfig

    async def execute(self, ctx: PluginContext) -> dict:
        return await asyncio.to_thread(self._send, ctx.config)

    @staticmethod
    def _send(cfg: SendEmailConfig) -> dict:
        message = EmailMessage()
        message["From"] = cfg.sender
        message["To"] = ", ".join(cfg.to)
        if cfg.cc:
            message["Cc"] = ", ".join(cfg.cc)
        if cfg.bcc:
            message["Bcc"] = ", ".join(cfg.bcc)  # smtplib delivers to Bcc without transmitting the header
        message["Subject"] = cfg.subject
        if cfg.body_html:
            message.set_content(cfg.body or "This message is best viewed in an HTML-capable client.")
            message.add_alternative(cfg.body_html, subtype="html")
        else:
            message.set_content(cfg.body)

        attached: list[str] = []
        for item in cfg.attachments:
            path = Path(item)
            if not path.is_file():
                raise FileNotFoundError(f"attachment not found: {path}")
            content_type, _ = mimetypes.guess_type(path.name)
            maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
            message.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
            attached.append(path.name)

        smtp_cls = smtplib.SMTP_SSL if cfg.encryption == "ssl" else smtplib.SMTP
        with smtp_cls(cfg.host, cfg.port) as smtp:
            if cfg.encryption == "starttls":
                smtp.starttls()
            if cfg.username:
                smtp.login(cfg.username, cfg.password)
            smtp.send_message(message)

        return {"to": cfg.to, "cc": cfg.cc, "subject": cfg.subject, "attachments": attached}
