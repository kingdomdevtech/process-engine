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

from process_engine_core.plugin import Plugin, PluginContext
from process_engine_core.plugins.excel_refresh import ExcelRefreshConfig, ExcelRefreshSpec


class ExcelRefreshPlugin(ExcelRefreshSpec, Plugin):
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
