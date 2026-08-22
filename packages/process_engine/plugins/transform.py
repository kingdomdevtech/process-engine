from process_engine_core.plugin import Plugin, PluginContext, PluginResult
from process_engine_core.plugins.transform import TransformConfig, TransformSpec


class TransformPlugin(TransformSpec, Plugin):
    async def execute(self, ctx: PluginContext) -> PluginResult:
        cfg: TransformConfig = ctx.config
        base = dict(ctx.input) if cfg.mode == "merge" and isinstance(ctx.input, dict) else {}
        return PluginResult.main({**base, **cfg.values})
