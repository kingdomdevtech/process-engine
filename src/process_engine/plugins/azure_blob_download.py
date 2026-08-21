"""Download a blob from Azure Blob Storage into the working directory.

Uses the Azure SDK (``pip install process-engine[azure]``). Four ways to sign
in, because which one is available depends entirely on where the engine runs:

* **Connection string** — what the portal's *Access keys* blade hands you, and
  the quickest thing to get working from a machine outside Azure.
* **Account key** — the same secret without the wrapper, for a named account.
* **SAS token** — a scoped, expiring signature; the least privilege of the
  three, and it stops working the day it expires (a support call worth
  expecting).
* **The machine's Azure identity** — no secret in the definition at all.
  Prefer it whenever the engine runs on an Azure VM, App Service or AKS with a
  managed identity granted *Storage Blob Data Reader*.

Keep whichever secret you use in the secrets store and reference it, e.g.
``"{{ secrets.azure_storage_key }}"``.

The destination is resolved through ``workspace``, so a step can only write
inside the configured working directory; the blob lands in a ``.part`` file
renamed on success. Emits the absolute ``path`` as well as the relative one —
wire it straight into ``send_email_ses``'s ``attachments`` or
``excel_refresh``'s ``workbook_path``.
"""

import asyncio
import logging
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .. import workspace
from ..plugin import Plugin, PluginContext, PluginManifest, PluginResult
from ..ui import ui, when
from . import _download

_CONNECTION_STRING = when("connect_using", "connection_string")
_ACCOUNT_KEY = when("connect_using", "account_key")
_SAS = when("connect_using", "sas_token")
_NAMED_ACCOUNT = when("connect_using", "account_key", "sas_token", "azure_identity")


class AzureBlobDownloadConfig(BaseModel):
    container: str = Field(
        title="Container",
        description="The container holding the file.",
        examples=["reports"],
        json_schema_extra=ui(group="File to download"),
    )
    blob: str = Field(
        title="File in the container",
        description="The full path to the blob, without the container name.",
        examples=["exports/{{ trigger.date }}/orders.csv"],
        json_schema_extra=ui(group="File to download"),
    )
    version_id: str = Field(
        default="",
        title="Version",
        description="Only for containers with versioning switched on. Leave blank for the current version.",
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

    connect_using: Literal["connection_string", "account_key", "sas_token", "azure_identity"] = Field(
        default="connection_string",
        title="Sign in with",
        json_schema_extra=ui(
            group="Azure storage",
            labels={
                "connection_string": "A connection string",
                "account_key": "Account name and key",
                "sas_token": "A SAS token",
                "azure_identity": "The Azure identity of this machine",
            },
        ),
    )
    connection_string: str = Field(
        default="",
        title="Connection string",
        description="From the storage account's “Access keys” page in the Azure portal.",
        examples=["{{ secrets.azure_storage_connection }}"],
        json_schema_extra=ui(
            group="Azure storage", show_if=_CONNECTION_STRING, widget="password", secret=True
        ),
    )
    account: str = Field(
        default="",
        title="Storage account",
        description="The account name, or its full https://….blob.core.windows.net address "
        "(use the address for sovereign clouds).",
        examples=["mycompanyreports"],
        json_schema_extra=ui(group="Azure storage", show_if=_NAMED_ACCOUNT),
    )
    account_key: str = Field(
        default="",
        title="Account key",
        examples=["{{ secrets.azure_storage_key }}"],
        json_schema_extra=ui(group="Azure storage", show_if=_ACCOUNT_KEY, widget="password", secret=True),
    )
    sas_token: str = Field(
        default="",
        title="SAS token",
        description="The signature itself, with or without its leading “?”.",
        examples=["{{ secrets.azure_sas_token }}"],
        json_schema_extra=ui(group="Azure storage", show_if=_SAS, widget="password", secret=True),
    )

    @model_validator(mode="after")
    def _credentials_complete(self) -> "AzureBlobDownloadConfig":
        """Say which box is empty here, rather than letting the SDK fail vaguely."""
        missing = {
            "connection_string": ("connection_string", "Connection string is required"),
            "account_key": ("account_key", "Account key is required"),
            "sas_token": ("sas_token", "SAS token is required"),
        }.get(self.connect_using)
        if missing and not getattr(self, missing[0]).strip():
            raise ValueError(f"{missing[1]} to sign in this way")
        if self.connect_using != "connection_string" and not self.account.strip():
            raise ValueError("Storage account is required to sign in this way")
        return self


class AzureBlobDownloadPlugin(Plugin):
    manifest = PluginManifest(
        key="azure_blob_download",
        name="Azure Blob Download",
        description="Download a blob from Azure Blob Storage into the engine's working directory.",
        category="files",
    )
    Config = AzureBlobDownloadConfig

    async def execute(self, ctx: PluginContext) -> PluginResult:
        # the Azure SDK is blocking; keep the engine's event loop free
        return PluginResult.main(await asyncio.to_thread(self._download, ctx.config, ctx.logger))

    @staticmethod
    def _client(cfg: AzureBlobDownloadConfig):
        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError as exc:
            raise RuntimeError(
                "azure-storage-blob is required for azure_blob_download: "
                "pip install process-engine[azure]"
            ) from exc

        if cfg.connect_using == "connection_string":
            return BlobServiceClient.from_connection_string(cfg.connection_string)

        url = _account_url(cfg.account)
        if cfg.connect_using == "account_key":
            return BlobServiceClient(url, credential=cfg.account_key)
        if cfg.connect_using == "sas_token":
            return BlobServiceClient(url, credential=cfg.sas_token.strip().lstrip("?"))

        try:
            from azure.identity import DefaultAzureCredential
        except ImportError as exc:
            raise RuntimeError(
                "azure-identity is required to sign in with the machine's Azure identity: "
                "pip install process-engine[azure]"
            ) from exc
        return BlobServiceClient(url, credential=DefaultAzureCredential())

    @classmethod
    def _download(cls, cfg: AzureBlobDownloadConfig, logger: logging.Logger) -> dict:
        destination = _download.target_path(cfg.destination, cfg.blob, label="blob")
        _download.refuse_overwrite(destination, cfg.overwrite)

        service = cls._client(cfg)
        try:
            blob = service.get_blob_client(
                container=cfg.container,
                blob=cfg.blob,
                **({"version_id": cfg.version_id} if cfg.version_id else {}),
            )
            properties = cls._properties(blob, cfg)
            logger.info("downloading %s/%s -> %s", cfg.container, cfg.blob, destination)
            _download.download_to(destination, lambda partial: _read_into(blob, partial))
            account = str(getattr(service, "account_name", "") or cfg.account)
        finally:
            service.close()

        content_settings = getattr(properties, "content_settings", None)
        return {
            "account": account,
            "container": cfg.container,
            "blob": cfg.blob,
            "version_id": str(getattr(properties, "version_id", "") or cfg.version_id or ""),
            "path": str(destination),  # absolute: feed it to attachments / workbook_path
            "relative_path": workspace.relative(destination),
            "filename": destination.name,
            "size_bytes": destination.stat().st_size,
            "content_type": str(getattr(content_settings, "content_type", "") or ""),
            "last_modified": _download.isoformat(getattr(properties, "last_modified", None)),
            "etag": str(getattr(properties, "etag", "") or "").strip('"'),
        }

    @staticmethod
    def _properties(blob, cfg: AzureBlobDownloadConfig):
        """Blob metadata, with a readable error when it simply is not there."""
        try:
            return blob.get_blob_properties()
        except Exception as exc:  # azure.core's HttpResponseError, duck-typed to avoid the import
            status = getattr(exc, "status_code", None)
            if status in (403, 404) or type(exc).__name__ == "ResourceNotFoundError":
                raise FileNotFoundError(
                    f"{cfg.container}/{cfg.blob} not found or not readable (HTTP {status}) "
                    f"in storage account {cfg.account or 'from the connection string'}"
                ) from exc
            raise


def _read_into(blob, partial) -> None:
    with open(partial, "wb") as handle:
        blob.download_blob().readinto(handle)


def _account_url(account: str) -> str:
    """Accept either a bare account name or a full endpoint address."""
    value = account.strip().rstrip("/")
    return value if "://" in value else f"https://{value}.blob.core.windows.net"
