"""Execute a MySQL statement or stored procedure — the execution half.

Reminder: the engine's retry policy re-runs failed steps — make statements
idempotent or leave ``max_attempts`` at 1 for non-idempotent writes.
"""

import asyncio
from typing import Any

from process_engine_core.plugin import Plugin, PluginContext, PluginResult
from process_engine_core.plugins.mysql_execute import MySQLExecuteConfig, MySQLExecuteSpec
from sqlalchemy import text

from ._mysql import jsonable, open_engine


class MySQLExecutePlugin(MySQLExecuteSpec, Plugin):
    async def execute(self, ctx: PluginContext) -> PluginResult:
        return PluginResult.main(await asyncio.to_thread(self._run, ctx.config))

    @staticmethod
    def _run(cfg: MySQLExecuteConfig) -> dict[str, Any]:
        engine = open_engine(cfg)
        try:
            if cfg.action == "procedure":
                raw = engine.raw_connection()
                try:
                    cursor = raw.cursor()
                    cursor.callproc(cfg.procedure, tuple(cfg.args))
                    result_sets: list[list[dict[str, Any]]] = []
                    while True:
                        if cursor.description:
                            columns = [description[0] for description in cursor.description]
                            result_sets.append(
                                [
                                    {column: jsonable(value) for column, value in zip(columns, row)}
                                    for row in cursor.fetchall()
                                ]
                            )
                        if not cursor.nextset():
                            break
                    raw.commit()
                    return {
                        "procedure": cfg.procedure,
                        "result_sets": result_sets,
                        "rowcount": cursor.rowcount,
                    }
                finally:
                    raw.close()
            with engine.begin() as connection:  # transaction: commit on success
                result = connection.execute(text(cfg.statement), cfg.params)
                return {
                    "rowcount": result.rowcount,
                    "lastrowid": jsonable(getattr(result, "lastrowid", None)),
                }
        finally:
            engine.dispose()
