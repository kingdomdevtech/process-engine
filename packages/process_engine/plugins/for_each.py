"""Iterate over a collection by running a published sub-process per item.

``ctx.run_subprocess`` is wired by the engine from its ``definition_resolver``,
which on an engine host reads published versions straight out of the database —
so a fan-out over 500 rows needs no call to the API.
"""

import asyncio
import re
from typing import Any

from process_engine_core.plugin import Plugin, PluginContext, PluginResult
from process_engine_core.plugins.for_each import ForEachConfig, ForEachSpec

_STALE_ITEM_REF = re.compile(r"^(?:trigger|steps|variables|input|secrets)(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")


class ForEachPlugin(ForEachSpec, Plugin):
    async def execute(self, ctx: PluginContext) -> PluginResult:
        cfg: ForEachConfig = ctx.config

        def detect_items(value: Any) -> Any:
            if value is None:
                return None
            if isinstance(value, str) and not value.strip():
                return None
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                for key in ("items", "rows", "values"):
                    candidate = value.get(key)
                    if isinstance(candidate, list):
                        return candidate
            return value

        raw_items = cfg.items
        if isinstance(raw_items, str):
            raw_items = raw_items.strip()
            if not raw_items:
                raw_items = None
            elif _STALE_ITEM_REF.match(raw_items):
                # A saved dotted path such as "steps.fetch.output.rows" is stale
                # once the upstream step is gone or disconnected; it is not a
                # literal list to iterate, so keep the low-effort auto-detect.
                raw_items = None

        items = detect_items(raw_items if raw_items is not None else ctx.input)
        if not isinstance(items, list):
            # A stale or incomplete saved expression is better treated as "no
            # explicit list yet" than as a hard failure: the upstream input can
            # still hold the collection we want to iterate. Users can keep the
            # default low-effort flow without a manual config step.
            fallback = detect_items(ctx.input)
            if isinstance(fallback, list):
                items = fallback
            else:
                raise ValueError(
                    'for_each "items" must resolve to a list, e.g. "{{ steps.fetch.output.rows }}"'
                )

        use_process = cfg.mode == "process" or bool(cfg.process_id)
        if not use_process:
            return PluginResult.main(
                {
                    "count": len(items),
                    "items": items,
                    "results": [{"item": item, "index": i} for i, item in enumerate(items)],
                }
            )

        if not cfg.process_id:
            raise ValueError('for_each process mode requires a process_id')
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
