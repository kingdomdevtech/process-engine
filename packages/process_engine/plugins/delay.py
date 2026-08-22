import asyncio

from process_engine_core.plugin import Plugin, PluginContext, PluginResult
from process_engine_core.plugins.delay import DelaySpec


class DelayPlugin(DelaySpec, Plugin):
    async def execute(self, ctx: PluginContext) -> PluginResult:
        await asyncio.sleep(ctx.config.seconds)
        return PluginResult.main(ctx.input)
