"""Delete files older than a cut-off — retention for downloads, exports, logs.

The form half. The delete happens on the engine host, inside its working
directory; the two brakes worth knowing about while filling this in:

* ``dry_run`` reports exactly what would go, deleting nothing — the sane first
  run of any new retention rule.
* ``keep_latest`` protects the N newest matches however old they are, so a
  backup folder that stopped receiving files does not empty itself.
"""

from typing import Literal

from pydantic import BaseModel, Field

from ..plugin import PluginManifest, PluginSpec
from ..ui import ui


class FilePurgeConfig(BaseModel):
    directory: str = Field(
        default="",
        title="Folder",
        description="Relative to the working directory. Leave blank for the working directory itself.",
        examples=["downloads/archive"],
        json_schema_extra=ui(group="Files to delete", widget="path"),
    )
    pattern: str = Field(
        default="*",
        title="File names matching",
        description="* stands for any text, so *.csv means every CSV file. * on its own means everything.",
        examples=["*.csv"],
        json_schema_extra=ui(group="Files to delete"),
    )
    recursive: bool = Field(
        default=False,
        title="Look in sub-folders too",
        json_schema_extra=ui(group="Files to delete"),
    )
    older_than_days: float = Field(
        ge=0,
        title="Delete files older than",
        description="Anything younger than this is left alone.",
        examples=[30],
        json_schema_extra=ui(group="Files to delete", unit="days"),
    )
    keep_latest: int = Field(
        default=0,
        ge=0,
        title="Always keep the newest",
        description="These survive however old they get, so a folder that stopped receiving files "
        "does not empty itself. 0 keeps none.",
        json_schema_extra=ui(group="Files to delete", unit="files"),
    )
    date_field: Literal["modified", "created", "accessed"] = Field(
        default="modified",
        title="Judge the age by",
        json_schema_extra=ui(
            group="Files to delete",
            advanced=True,
            labels={
                "modified": "When the file was last changed",
                "created": "When the file was created",
                "accessed": "When the file was last opened",
            },
        ),
    )

    dry_run: bool = Field(
        default=False,
        title="Practice run — delete nothing",
        description="Reports exactly what would go without touching it. Worth doing once for any "
        "new rule; check the step's output, then turn this off.",
        json_schema_extra=ui(group="Safety"),
    )
    ignore_errors: bool = Field(
        default=False,
        title="Carry on when a file cannot be deleted",
        description="Off: a file in use or read-only fails the step. On: it is listed in the output "
        "and the rest are still deleted.",
        json_schema_extra=ui(group="Safety"),
    )
    delete_empty_directories: bool = Field(
        default=False,
        title="Remove folders left empty",
        description="Never removes the folder above.",
        json_schema_extra=ui(group="Safety", advanced=True),
    )


class FilePurgeSpec(PluginSpec):
    manifest = PluginManifest(
        key="file_purge",
        name="Purge Old Files",
        description="Delete files older than a cut-off inside the working directory (glob, keep-latest, dry run).",
        category="files",
    )
    Config = FilePurgeConfig
