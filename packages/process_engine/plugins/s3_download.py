"""Download an object from an S3 bucket into the working directory.

Uses boto3 (``pip install process-engine[aws]``).

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

from process_engine_core import workspace
from process_engine_core.plugin import Plugin, PluginContext, PluginResult
from process_engine_core.plugins.s3_download import S3DownloadConfig, S3DownloadSpec

from . import _download


class S3DownloadPlugin(S3DownloadSpec, Plugin):
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
