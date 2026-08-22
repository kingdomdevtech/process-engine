"""Send mail over SMTP — the form half.

One ``encryption`` dropdown rather than a use_tls/use_ssl pair, and the retired
field names still load through the before-validator: reshaping a field is as
breaking as renaming a plugin, so the old keys keep working.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ..plugin import PluginManifest, PluginSpec
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


class SendEmailSpec(PluginSpec):
    manifest = PluginManifest(
        key="send_email_smtp",
        name="Send Email (SMTP)",
        description="Send an email through any SMTP server, optionally with attachments.",
        category="communication",
        aliases=["send_email"],  # definitions saved before the SES split still resolve
    )
    Config = SendEmailConfig
