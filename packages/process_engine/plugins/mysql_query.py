"""Read rows from MySQL — the execution half.

Parameters are bound by name (":name" placeholders) — never interpolate
values into the SQL string; they arrive in ``params``, apart from the SQL.
"""

import asyncio
from typing import Any

from process_engine_core.plugin import Plugin, PluginContext, PluginResult
from process_engine_core.plugins.mysql_query import MySQLQueryConfig, MySQLQuerySpec
from sqlalchemy import text

from ._mysql import jsonable, open_engine


class MySQLQueryPlugin(MySQLQuerySpec, Plugin):
    async def execute(self, ctx: PluginContext) -> PluginResult:
        return PluginResult.main(await asyncio.to_thread(self._run, ctx.config))

    @staticmethod
    def _run(cfg: MySQLQueryConfig) -> dict[str, Any]:
        engine = open_engine(cfg)
        truncated = False
        rows: list[dict[str, Any]] = []
        try:
            with engine.connect() as connection:
                result = connection.execute(text(cfg.query), cfg.params)
                for index, row in enumerate(result):
                    if index >= cfg.max_rows:
                        truncated = True
                        break
                    rows.append({key: jsonable(value) for key, value in row._mapping.items()})
        finally:
            engine.dispose()
        return {"rows": rows, "count": len(rows), "truncated": truncated}
