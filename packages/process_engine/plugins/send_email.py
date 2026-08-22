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

from process_engine_core.plugin import Plugin, PluginContext
from process_engine_core.plugins.send_email import SendEmailConfig, SendEmailSpec


class SendEmailPlugin(SendEmailSpec, Plugin):
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
