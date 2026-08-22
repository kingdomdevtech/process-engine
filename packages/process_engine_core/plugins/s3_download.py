"""Download an object from an S3 bucket into the working directory — the form half.

Credentials resolve the same way as ``send_email_ses``:

1. Explicit ``access_key_id`` / ``secret_access_key`` in the step config —
   reference the secrets store, e.g. ``"{{ secrets.aws_secret_key }}"``.
2. The ambient boto3 chain (environment, shared config, EC2/ECS/Lambda role).
   Prefer this in AWS-hosted deployments — no credentials in definitions.

Either way the secret is resolved on the engine host at execution time, never
here: this package holds the shape of the form, not the values that fill it.
"""

from pydantic import BaseModel, Field

from ..plugin import PluginManifest, PluginSpec
from ..ui import ui


class S3DownloadConfig(BaseModel):
    bucket: str = Field(
        title="Bucket",
        description="The S3 bucket holding the file.",
        examples=["reports-bucket"],
        json_schema_extra=ui(group="File to download"),
    )
    key: str = Field(
        title="File in the bucket",
        description="The full path to the object, without the bucket name.",
        examples=["exports/{{ trigger.date }}/orders.csv"],
        json_schema_extra=ui(group="File to download"),
    )
    version_id: str = Field(
        default="",
        title="Version",
        description="Only for versioned buckets. Leave blank for the current version.",
        json_schema_extra=ui(group="File to download", advanced=True),
    )

    destination: str = Field(
        default="",
        title="Save as",
        description=(
            "Where to put it, relative to the working directory. End with a slash to mean "
            "“into this folder”, or leave blank to keep the file's own name. Anywhere outside "
            "the working directory is refused."
        ),
        examples=["downloads/orders.csv"],
        json_schema_extra=ui(group="Save to", widget="path"),
    )
    overwrite: bool = Field(
        default=True,
        title="Replace a file that is already there",
        description="Off: the step fails rather than overwriting.",
        json_schema_extra=ui(group="Save to"),
    )

    region: str = Field(
        default="us-east-1",
        title="AWS region",
        description="The region the bucket is in.",
        json_schema_extra=ui(group="Amazon S3"),
    )
    access_key_id: str = Field(
        default="",
        title="Access key ID",
        description="Leave blank to use the AWS credentials of the machine running the engine — "
        "the better choice when the engine runs inside AWS.",
        json_schema_extra=ui(group="Amazon S3", advanced=True),
    )
    secret_access_key: str = Field(
        default="",
        title="Secret access key",
        examples=["{{ secrets.aws_secret_key }}"],
        json_schema_extra=ui(group="Amazon S3", advanced=True, widget="password", secret=True),
    )
    session_token: str = Field(
        default="",
        title="Session token",
        description="Only for temporary credentials.",
        json_schema_extra=ui(group="Amazon S3", advanced=True, widget="password", secret=True),
    )
    endpoint_url: str = Field(
        default="",
        title="Custom endpoint",
        description="For S3-compatible storage such as MinIO or Ceph. Blank talks to AWS.",
        examples=["https://s3.example.internal"],
        json_schema_extra=ui(group="Amazon S3", advanced=True),
    )


class S3DownloadSpec(PluginSpec):
    manifest = PluginManifest(
        key="s3_download",
        name="S3 Download",
        description="Download an object from an S3 bucket into the engine's working directory.",
        category="files",
    )
    Config = S3DownloadConfig
