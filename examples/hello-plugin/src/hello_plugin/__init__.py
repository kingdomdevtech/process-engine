"""A minimal external Plugin, installed with ``pip install -e examples/hello-plugin``.

Use this layout for a plugin another team owns on its own release cycle. It has
to be pip-installed on every host that executes *and* on the API host that must
offer it in the palette, so a plugin belonging to this product goes in
``packages/process_engine_core/plugins/`` + ``packages/process_engine/plugins/``
instead.

It depends on ``process-engine-core`` and nothing else: that is the distribution
holding the contract, and it is the one both tiers install. Depending on the
engine would make this package unloadable on the API host, where its manifest is
read to draw the palette.
"""

from pydantic import BaseModel

from process_engine_core.plugin import Plugin, PluginContext, PluginManifest, PluginResult


class HelloConfig(BaseModel):
    greeting: str = "Hello"
    name: str = "world"


class HelloPlugin(Plugin):
    manifest = PluginManifest(
        key="hello",
        name="Hello",
        description="Emit a greeting.",
        category="examples",
    )
    Config = HelloConfig

    async def execute(self, ctx: PluginContext) -> PluginResult:
        return PluginResult.main({"message": f"{ctx.config.greeting}, {ctx.config.name}!"})
