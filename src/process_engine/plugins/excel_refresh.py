"""Refresh Excel Power Query connections via COM automation.

Requirements: Windows, desktop Excel installed, and pywin32
(``pip install process-engine[excel]``). Excel COM automation is
single-instance-unfriendly — do not refresh the same workbook from two
runs at once, and run the engine in an interactive session (Excel COM in
Windows services needs extra DCOM configuration).
"""

import asyncio
import logging
from pathlib import Path

from pydantic import BaseModel, Field

from ..plugin import Plugin, PluginContext, PluginManifest
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


class ExcelRefreshPlugin(Plugin):
    manifest = PluginManifest(
        key="excel_refresh",
        name="Excel Power Query Refresh",
        description="Open a workbook, refresh its Power Query/data connections, and save. Windows + Excel + pywin32 required.",
        category="data",
    )
    Config = ExcelRefreshConfig

    async def execute(self, ctx: PluginContext) -> dict:
        # COM is blocking; keep the engine's event loop free
        return await asyncio.to_thread(self._refresh, ctx.config, ctx.logger)

    @staticmethod
    def _refresh(cfg: ExcelRefreshConfig, logger: logging.Logger) -> dict:
        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:
            raise RuntimeError(
                "pywin32 is required for excel_refresh: pip install process-engine[excel] "
                "(Windows with desktop Excel only)"
            ) from exc

        path = Path(cfg.workbook_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"workbook not found: {path}")

        pythoncom.CoInitialize()
        excel = None
        workbook = None
        try:
            excel = win32com.client.DispatchEx("Excel.Application")
            excel.Visible = cfg.visible
            excel.DisplayAlerts = False
            workbook = excel.Workbooks.Open(str(path), UpdateLinks=0)

            refreshed: list[str] = []
            if cfg.connections:
                for name in cfg.connections:
                    connection = workbook.Connections(name)
                    _disable_background_refresh(connection)
                    logger.info("refreshing connection %s", name)
                    connection.Refresh()
                    refreshed.append(name)
            else:
                for index in range(1, workbook.Connections.Count + 1):
                    connection = workbook.Connections(index)
                    _disable_background_refresh(connection)
                    refreshed.append(str(connection.Name))
                logger.info("RefreshAll on %s (%d connections)", path.name, len(refreshed))
                workbook.RefreshAll()

            excel.CalculateUntilAsyncQueriesDone()
            if cfg.save:
                workbook.Save()
            return {"workbook": str(path), "refreshed": refreshed, "saved": cfg.save}
        finally:
            if workbook is not None:
                workbook.Close(SaveChanges=False)
            if excel is not None:
                excel.Quit()
            pythoncom.CoUninitialize()


def _disable_background_refresh(connection) -> None:
    """Force a synchronous refresh so completion (and failure) is observable."""
    for attribute in ("OLEDBConnection", "ODBCConnection"):
        try:
            getattr(connection, attribute).BackgroundQuery = False
        except Exception:  # noqa: BLE001 — connection types expose different interfaces
            continue
