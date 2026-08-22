from typing import Any, Literal

from pydantic import BaseModel, Field

from ..plugin import PluginManifest, PluginSpec
from ..ui import ui


class TransformConfig(BaseModel):
    values: dict[str, Any] = Field(  # each value may be an expression
        default_factory=dict,
        title="Fields",
        description="Name each field and give it a value. Use the ƒx button to take a value from an earlier step.",
        examples=[{"order_id": "{{ trigger.id }}", "total": "{{ steps.fetch.output.amount }}"}],
        json_schema_extra=ui(
            widget="keyvalue", key_label="Field", value_label="Value", add_label="Add field"
        ),
    )
    mode: Literal["merge", "replace"] = Field(
        default="merge",
        title="Incoming data",
        json_schema_extra=ui(
            labels={
                "merge": "Keep it and add these fields",
                "replace": "Discard it and send only these fields",
            },
        ),
    )


class TransformSpec(PluginSpec):
    """Set or reshape data — the equivalent of n8n's "Edit Fields (Set)"."""

    manifest = PluginManifest(
        key="transform",
        name="Transform",
        description="Set fields, building on or replacing the input payload.",
        category="data",
    )
    Config = TransformConfig
