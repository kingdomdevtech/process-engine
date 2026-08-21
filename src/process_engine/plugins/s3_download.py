"""Download an object from an S3 bucket into the working directory.

Uses boto3 (``pip install process-engine[aws]``). Credentials resolve the same
way as ``send_email_ses``:

1. Explicit ``access_key_id`` / ``secret_access_key`` in the step config —
   reference the secrets store, e.g. ``"{{ secrets.aws_secret_key }}"``.
2. The ambient boto3 chain (environment, shared config, EC2/ECS/Lambda role).
   Prefer this in AWS-hosted deployments — no credentials in definitions.

The destination is resolved through ``workspace``, so a step can only write
inside the configured working directory, and the object lands in a ``.part``
file renamed on success — both in ``_download.py``, shared with
``azure_blob_download`` so the two behave identically.

Emits the absolute ``path`` as well as the relative one — wire it straight
into ``send_email_ses``'s ``attachments`` or ``excel_refresh``'s
``workbook_path``.
"""

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field

from .. import workspace
from ..plugin import Plugin, PluginContext, PluginManifest, PluginResult
from ..ui import ui
from . import _download


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


class S3DownloadPlugin(Plugin):
    manifest = PluginManifest(
        key="s3_download",
        name="S3 Download",
        description="Download an object from an S3 bucket into the engine's working directory.",
        category="files",
    )
    Config = S3DownloadConfig

    async def execute(self, ctx: PluginContext) -> PluginResult:
        # boto3 is blocking; keep the engine's event loop free
        return PluginResult.main(await asyncio.to_thread(self._download, ctx.config, ctx.logger))

    @staticmethod
    def _client(cfg: S3DownloadConfig):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "boto3 is required for s3_download: pip install process-engine[aws]"
            ) from exc
        kwargs: dict[str, Any] = {"region_name": cfg.region}
        if cfg.access_key_id and cfg.secret_access_key:
            kwargs["aws_access_key_id"] = cfg.access_key_id
            kwargs["aws_secret_access_key"] = cfg.secret_access_key
            if cfg.session_token:
                kwargs["aws_session_token"] = cfg.session_token
        if cfg.endpoint_url:
            kwargs["endpoint_url"] = cfg.endpoint_url
        return boto3.client("s3", **kwargs)

    @classmethod
    def _download(cls, cfg: S3DownloadConfig, logger: logging.Logger) -> dict:
        destination = _download.target_path(cfg.destination, cfg.key, label="key")
        _download.refuse_overwrite(destination, cfg.overwrite)

        client = cls._client(cfg)
        reference: dict[str, str] = {"Bucket": cfg.bucket, "Key": cfg.key}
        if cfg.version_id:
            reference["VersionId"] = cfg.version_id

        head = cls._head(client, cfg, reference)
        logger.info("downloading s3://%s/%s -> %s", cfg.bucket, cfg.key, destination)
        extra = {"VersionId": cfg.version_id} if cfg.version_id else None
        _download.download_to(
            destination,
            lambda partial: client.download_file(cfg.bucket, cfg.key, str(partial), ExtraArgs=extra),
        )

        return {
            "bucket": cfg.bucket,
            "key": cfg.key,
            "version_id": str(head.get("VersionId") or cfg.version_id or ""),
            "path": str(destination),  # absolute: feed it to attachments / workbook_path
            "relative_path": workspace.relative(destination),
            "filename": destination.name,
            "size_bytes": destination.stat().st_size,
            "content_type": str(head.get("ContentType") or ""),
            "last_modified": _download.isoformat(head.get("LastModified")),
            "etag": str(head.get("ETag") or "").strip('"'),
        }

    @staticmethod
    def _head(client, cfg: S3DownloadConfig, reference: dict[str, str]) -> dict:
        """Object metadata, with a readable error when the key simply is not there."""
        try:
            return client.head_object(**reference)
        except Exception as exc:  # botocore's ClientError, duck-typed to avoid the import
            response = getattr(exc, "response", None)
            status = None
            if isinstance(response, dict):
                status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status in (403, 404):
                raise FileNotFoundError(
                    f"s3://{cfg.bucket}/{cfg.key} not found or not readable "
                    f"(HTTP {status}) in region {cfg.region}"
                ) from exc
            raise
