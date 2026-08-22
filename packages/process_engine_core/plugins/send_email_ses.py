"""Send mail through Amazon SES — the form half.

Blank keys fall through to the ambient boto3 credential chain, which is the right
answer when the engine host runs inside AWS.
"""

from pydantic import BaseModel, Field

from ..plugin import PluginManifest, PluginSpec
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


class SendEmailSESSpec(PluginSpec):
    manifest = PluginManifest(
        key="send_email_ses",
        name="Send Email (AWS SES)",
        description="Send an email through Amazon SES, with HTML body and attachments.",
        category="communication",
    )
    Config = SendEmailSESConfig
