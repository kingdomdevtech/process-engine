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

from process_engine_core.plugin import Plugin, PluginContext
from process_engine_core.plugins.send_email_ses import SendEmailSESConfig, SendEmailSESSpec


class SendEmailSESPlugin(SendEmailSESSpec, Plugin):
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
