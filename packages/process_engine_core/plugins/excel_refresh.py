"""Refresh Excel Power Query connections via COM automation — the form half.

The step is offered by any designer; it can only *run* on a Windows host with
desktop Excel and pywin32 (``pip install process-engine[excel]``). That asymmetry
is the reason this package exists: the palette needs the settings, and nothing on
the designer's host could execute them even if it wanted to.
"""

from pydantic import BaseModel, Field

from ..plugin import PluginManifest, PluginSpec
from ..ui import ui


class ExcelRefreshConfig(BaseModel):
    workbook_path: str = Field(
        title="Workbook",
        description="Full path to the .xlsx file, as seen from the machine running the engine.",
        examples=[r"C:\reports\sales.xlsx"],
        json_schema_extra=ui(widget="path"),
    )
    connections: list[str] = Field(
        default_factory=list,
        title="Connections to refresh",
        description="The names as they appear in Excel under Data → Queries & Connections. "
        "Leave empty to refresh every one of them.",
        examples=[["Query - Orders"]],
        json_schema_extra=ui(widget="tags", add_label="Add connection"),
    )
    save: bool = Field(
        default=True,
        title="Save the workbook afterwards",
        json_schema_extra=ui(),
    )
    visible: bool = Field(
        default=False,
        title="Show the Excel window",
        description="Only useful when watching a refresh that misbehaves.",
        json_schema_extra=ui(advanced=True),
    )


class ExcelRefreshSpec(PluginSpec):
    manifest = PluginManifest(
        key="excel_refresh",
        name="Excel Power Query Refresh",
        description="Open a workbook, refresh its Power Query/data connections, and save. Windows + Excel + pywin32 required.",
        category="data",
    )
    Config = ExcelRefreshConfig
