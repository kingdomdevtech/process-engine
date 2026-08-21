"""Drop-in Plugin example — the fastest way to add a custom step.

Any ``.py`` file in this folder defining a Plugin subclass is discovered at
startup (see process_engine/registry.py). No packaging, no install, no
changes to the engine: write the class, restart the server, and it appears
in the designer's palette with a config form generated from its Config model.
"""

from pydantic import BaseModel

from process_engine.plugin import Plugin, PluginContext, PluginManifest, PluginResult


class UppercaseConfig(BaseModel):
    text: str = "{{ input.message }}"  # expressions welcome, like any built-in


class UppercasePlugin(Plugin):
    manifest = PluginManifest(
        key="uppercase",
        name="Uppercase",
        description="Emit the configured text in upper case.",
        category="custom",
    )
    Config = UppercaseConfig

    async def execute(self, ctx: PluginContext) -> PluginResult:
        return PluginResult.main({"text": ctx.config.text.upper()})
