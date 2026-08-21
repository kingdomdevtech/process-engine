"""A minimal external Plugin, installed with ``pip install -e examples/hello-plugin``.

Use this layout for plugins you want to version, test, and share across
installations; use a drop-in file (see plugins/uppercase.py) for quick
local ones.
"""

from pydantic import BaseModel

from process_engine.plugin import Plugin, PluginContext, PluginManifest, PluginResult


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
