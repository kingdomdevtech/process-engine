"""Read rows from MySQL.

Parameters are bound by name (":name" placeholders) — never interpolate
values into the SQL string; put them in ``params`` instead, where they may
also be expressions.
"""

import asyncio
from typing import Any

from pydantic import Field
from sqlalchemy import text

from ..plugin import Plugin, PluginContext, PluginManifest, PluginResult
from ..ui import ui
from ._mysql import MySQLConnection, jsonable, open_engine


class MySQLQueryConfig(MySQLConnection):
    query: str = Field(
        title="Query",
        description="The SELECT statement to run. Write :name where a value goes, and fill it in below.",
        examples=["SELECT id, total FROM orders WHERE status = :status"],
        json_schema_extra=ui(group="Query", widget="sql"),
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        title="Values",
        description="One entry per :name in the query. Kept apart from the SQL, so a value can never "
        "change what the query does.",
        examples=[{"status": "{{ trigger.status }}"}],
        json_schema_extra=ui(group="Query", widget="keyvalue", key_label="Name", add_label="Add value"),
    )
    max_rows: int = Field(
        default=1000,
        ge=1,
        le=100_000,
        title="Row limit",
        description="Stop reading after this many rows. The output says whether anything was cut off.",
        json_schema_extra=ui(group="Query", advanced=True, unit="rows"),
    )


class MySQLQueryPlugin(Plugin):
    manifest = PluginManifest(
        key="mysql_query",
        name="MySQL Query",
        description="Run a SELECT against MySQL and emit the rows.",
        category="database",
    )
    Config = MySQLQueryConfig

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
