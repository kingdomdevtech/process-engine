from typing import Literal

from pydantic import BaseModel, Field

from ..plugin import PluginManifest, PluginSpec
from ..ui import ui


class LogConfig(BaseModel):
    message: str = Field(
        default="",
        title="Message",
        description="Written to the engine log. Use the ƒx button to include values from earlier steps.",
        examples=["order {{ input.id }} done"],
        json_schema_extra=ui(),
    )
    level: Literal["debug", "info", "warning", "error"] = Field(
        default="info",
        title="Importance",
        json_schema_extra=ui(
            labels={
                "debug": "Debug — detail while troubleshooting",
                "info": "Info — normal progress",
                "warning": "Warning — worth a look",
                "error": "Error — something went wrong",
            },
        ),
    )


class LogSpec(PluginSpec):
    manifest = PluginManifest(
        key="log",
        name="Log",
        description="Write a message to the engine log and pass the input through.",
        category="utility",
    )
    Config = LogConfig
