"""Iterate over a collection by running a published sub-process per item.

This is the Camunda multi-instance / AWS Step Functions "Map state" pattern:
the graph stays acyclic, and iteration happens by fanning out a sub-process.
Each item's sub-process receives ``{"item": <item>, "index": <i>}`` as its
trigger input; reference them inside the sub-process as
``{{ trigger.item }}`` / ``{{ trigger.index }}``.
"""

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from ..plugin import Plugin, PluginContext, PluginManifest, PluginResult
from ..ui import ui


class ForEachConfig(BaseModel):
    items: Any = Field(
        default=None,
        title="List to work through",
        description="Must be a list — usually rows from an earlier step. Leave empty to use whatever "
        "the previous step passed in.",
        examples=["{{ steps.fetch.output.rows }}"],
        json_schema_extra=ui(),
    )
    process_id: str = Field(
        title="Process to run for each one",
        description="Must be published. Inside it, the item is {{ trigger.item }} and its position "
        "in the list is {{ trigger.index }}.",
        json_schema_extra=ui(),
    )
    parallel: int = Field(
        default=1,
        ge=1,
        le=16,
        title="Run at the same time",
        description="1 works through the list one at a time. Raise it to go faster, as long as "
        "whatever the sub-process touches can cope.",
        json_schema_extra=ui(advanced=True, unit="at once"),
    )
    continue_on_error: bool = Field(
        default=False,
        title="Carry on when an item fails",
        description="Off: the first failure stops this step. On: every item is attempted and the "
        "output reports how many failed.",
        json_schema_extra=ui(advanced=True),
    )


class ForEachPlugin(Plugin):
    manifest = PluginManifest(
        key="for_each",
        name="For Each",
        description="Run a published sub-process once per item of a collection.",
        category="flow",
    )
    Config = ForEachConfig

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
