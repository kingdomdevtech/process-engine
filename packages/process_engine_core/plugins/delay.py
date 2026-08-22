from pydantic import BaseModel, Field

from ..plugin import PluginManifest, PluginSpec
from ..ui import ui


class DelayConfig(BaseModel):
    seconds: float = Field(
        default=1.0,
        ge=0,
        title="Wait for",
        description="Pauses this run only — other runs carry on.",
        json_schema_extra=ui(unit="seconds"),
    )


class DelaySpec(PluginSpec):
    manifest = PluginManifest(
        key="delay",
        name="Delay",
        description="Wait, then pass the input through untouched.",
        category="flow",
    )
    Config = DelayConfig
