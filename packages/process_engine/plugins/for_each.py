"""Iterate over a collection by running a published sub-process per item.

``ctx.run_subprocess`` is wired by the engine from its ``definition_resolver``,
which on an engine host reads published versions straight out of the database —
so a fan-out over 500 rows needs no call to the API.
"""

import asyncio
from typing import Any

from process_engine_core.plugin import Plugin, PluginContext, PluginResult
from process_engine_core.plugins.for_each import ForEachConfig, ForEachSpec


class ForEachPlugin(ForEachSpec, Plugin):
    async def execute(self, ctx: PluginContext) -> PluginResult:
        cfg: ForEachConfig = ctx.config
        items = cfg.items if cfg.items is not None else ctx.input
        if not isinstance(items, list):
            raise ValueError(
                'for_each "items" must resolve to a list, e.g. "{{ steps.fetch.output.rows }}"'
            )
        if ctx.run_subprocess is None:
            raise RuntimeError("sub-process execution is not available in this engine configuration")

        semaphore = asyncio.Semaphore(cfg.parallel)

        async def run_item(index: int, item: Any) -> dict[str, Any]:
            async with semaphore:
                return await ctx.run_subprocess(cfg.process_id, {"item": item, "index": index})

        results = await asyncio.gather(*(run_item(i, item) for i, item in enumerate(items)))
        failed = [r for r in results if r["status"] != "succeeded"]
        if failed and not cfg.continue_on_error:
            raise RuntimeError(
                f"{len(failed)}/{len(items)} sub-process runs failed; first error: {failed[0]['error']}"
            )
        return PluginResult.main(
            {
                "count": len(items),
                "succeeded": len(results) - len(failed),
                "failed": len(failed),
                "results": results,
            }
        )
