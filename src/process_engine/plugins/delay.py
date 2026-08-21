import asyncio

from pydantic import BaseModel, Field

from ..plugin import Plugin, PluginContext, PluginManifest, PluginResult
from ..ui import ui


class DelayConfig(BaseModel):
    seconds: float = Field(
        default=1.0,
        ge=0,
        title="Wait for",
        description="Pauses this run only — other runs carry on.",
        json_schema_extra=ui(unit="seconds"),
    )


class DelayPlugin(Plugin):
    manifest = PluginManifest(
        key="delay",
        name="Delay",
        description="Wait, then pass the input through untouched.",
        category="flow",
    )
    Config = DelayConfig

    async def execute(self, ctx: PluginContext) -> PluginResult:
        await asyncio.sleep(ctx.config.seconds)
        return PluginResult.main(ctx.input)
