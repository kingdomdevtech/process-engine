"""Send email through Amazon SES.

Uses the SES v2 SendEmail API via boto3 (``pip install process-engine[aws]``).
Credentials resolve in this order:

1. Explicit ``access_key_id`` / ``secret_access_key`` in the step config —
   reference the secrets store, e.g. ``"{{ secrets.aws_secret_key }}"``.
2. The ambient boto3 chain (environment, shared config, EC2/ECS/Lambda role).
   Prefer this in AWS-hosted deployments — no credentials in definitions.

Attachments switch the call to SendRawEmail (MIME), which SES also uses for
custom headers; without attachments the simple templated form is used so SES
handles encoding.
"""

import asyncio
import mimetypes
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..plugin import Plugin, PluginContext, PluginManifest
from ..ui import ui


class SendEmailSESConfig(BaseModel):
    region: str = Field(
        default="us-east-1",
        title="AWS region",
        description="The region your verified SES sender lives in.",
        examples=["us-east-1"],
        json_schema_extra=ui(group="Amazon SES"),
    )
    access_key_id: str = Field(
        default="",
        title="Access key ID",
        description="Leave blank to use the AWS credentials of the machine running the engine — "
        "the better choice when the engine runs inside AWS.",
        json_schema_extra=ui(group="Amazon SES", advanced=True),
    )
    secret_access_key: str = Field(
        default="",
        title="Secret access key",
        examples=["{{ secrets.aws_secret_key }}"],
        json_schema_extra=ui(group="Amazon SES", advanced=True, widget="password", secret=True),
    )
    session_token: str = Field(
        default="",
        title="Session token",
        description="Only for temporary credentials.",
        json_schema_extra=ui(group="Amazon SES", advanced=True, widget="password", secret=True),
    )
    configuration_set: str = Field(
        default="",
        title="Configuration set",
        description="SES configuration set for open/click tracking or a dedicated IP pool.",
        json_schema_extra=ui(group="Amazon SES", advanced=True),
    )

    sender: str = Field(
        title="From",
        description="Must be an address or domain you have verified in SES.",
        examples=["Reports <reports@example.com>"],
        json_schema_extra=ui(group="Message"),
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
        json_schema_extra={"format": "html", **ui(group="Message")},
    )
    reply_to: list[str] = Field(
        default_factory=list,
        title="Reply to",
        description="Where replies go, when that is not the From address.",
        json_schema_extra=ui(group="Message", advanced=True, widget="emails", add_label="Add address"),
    )
    body: str = Field(
        default="",
        title="Plain-text version",
        description="Shown by mail clients that cannot display formatting.",
        json_schema_extra=ui(group="Message", advanced=True, widget="textarea"),
    )
    attachments: list[str] = Field(
        default_factory=list,
        title="Attachments",
        description="Full paths to files on the machine running the engine.",
        json_schema_extra=ui(group="Message", advanced=True, widget="files", add_label="Add file"),
    )


class SendEmailSESPlugin(Plugin):
    manifest = PluginManifest(
        key="send_email_ses",
        name="Send Email (AWS SES)",
        description="Send an email through Amazon SES, with HTML body and attachments.",
        category="communication",
    )
    Config = SendEmailSESConfig

    async def execute(self, ctx: PluginContext) -> dict:
        return await asyncio.to_thread(self._send, ctx.config)

    @staticmethod
    def _client(cfg: SendEmailSESConfig):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "boto3 is required for send_email_ses: pip install process-engine[aws]"
            ) from exc
        kwargs: dict[str, Any] = {"region_name": cfg.region}
        if cfg.access_key_id and cfg.secret_access_key:
            kwargs["aws_access_key_id"] = cfg.access_key_id
            kwargs["aws_secret_access_key"] = cfg.secret_access_key
            if cfg.session_token:
                kwargs["aws_session_token"] = cfg.session_token
        return boto3.client("sesv2", **kwargs)

    @classmethod
    def _send(cls, cfg: SendEmailSESConfig) -> dict:
        client = cls._client(cfg)
        destination = {"ToAddresses": cfg.to, "CcAddresses": cfg.cc, "BccAddresses": cfg.bcc}
        request: dict[str, Any] = {
            "FromEmailAddress": cfg.sender,
            "Destination": destination,
        }
        if cfg.reply_to:
            request["ReplyToAddresses"] = cfg.reply_to
        if cfg.configuration_set:
            request["ConfigurationSetName"] = cfg.configuration_set

        attached: list[str] = []
        if cfg.attachments:
            message, attached = cls._build_mime(cfg)
            request["Content"] = {"Raw": {"Data": message.as_bytes()}}
        else:
            body: dict[str, Any] = {}
            if cfg.body:
                body["Text"] = {"Data": cfg.body, "Charset": "UTF-8"}
            if cfg.body_html:
                body["Html"] = {"Data": cfg.body_html, "Charset": "UTF-8"}
            if not body:
                body["Text"] = {"Data": "", "Charset": "UTF-8"}
            request["Content"] = {
                "Simple": {"Subject": {"Data": cfg.subject, "Charset": "UTF-8"}, "Body": body}
            }

        response = client.send_email(**request)
        return {
            "message_id": response.get("MessageId"),
            "to": cfg.to,
            "cc": cfg.cc,
            "subject": cfg.subject,
            "attachments": attached,
            "region": cfg.region,
        }

    @staticmethod
    def _build_mime(cfg: SendEmailSESConfig) -> tuple[EmailMessage, list[str]]:
        message = EmailMessage()
        message["From"] = cfg.sender
        message["To"] = ", ".join(cfg.to)
        if cfg.cc:
            message["Cc"] = ", ".join(cfg.cc)
        if cfg.reply_to:
            message["Reply-To"] = ", ".join(cfg.reply_to)
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
        return message, attached
