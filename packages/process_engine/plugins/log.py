from process_engine_core.plugin import Plugin, PluginContext, PluginResult
from process_engine_core.plugins.log import LogSpec


class LogPlugin(LogSpec, Plugin):
    async def execute(self, ctx: PluginContext) -> PluginResult:
        getattr(ctx.logger, ctx.config.level)(ctx.config.message)
        return PluginResult.main(ctx.input)
