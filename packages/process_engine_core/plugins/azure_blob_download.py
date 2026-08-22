"""Download a blob from Azure Storage into the working directory — the form half.

Four ways to sign in, chosen by ``connect_using`` so no two half-apply. Whichever
it is, the credential is resolved on the engine host at execution time; nothing
here reads one.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ..plugin import PluginManifest, PluginSpec
from ..ui import ui, when


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


class AzureBlobDownloadSpec(PluginSpec):
    manifest = PluginManifest(
        key="azure_blob_download",
        name="Azure Blob Download",
        description="Download a blob from Azure Blob Storage into the engine's working directory.",
        category="files",
    )
    Config = AzureBlobDownloadConfig
