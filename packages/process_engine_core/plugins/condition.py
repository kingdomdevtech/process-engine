from typing import Any, Literal

from pydantic import BaseModel, Field

from ..plugin import PluginManifest, PluginSpec, Port
from ..ui import ui, when

Operator = Literal[
    "equals",
    "not_equals",
    "contains",
    "greater_than",
    "less_than",
    "is_empty",
    "is_not_empty",
]

# The operators that compare against a second value; the two emptiness checks do not.
_BINARY = when("operator", "equals", "not_equals", "contains", "greater_than", "less_than")


class ConditionConfig(BaseModel):
    left: Any = Field(
        default=None,
        title="Value to check",
        description="Usually pulled from an earlier step with the ƒx button.",
        examples=["{{ steps.fetch.output.total }}"],
        json_schema_extra=ui(group="Condition"),
    )
    operator: Operator = Field(
        default="equals",
        title="Test",
        json_schema_extra=ui(
            group="Condition",
            labels={
                "equals": "is equal to",
                "not_equals": "is not equal to",
                "contains": "contains",
                "greater_than": "is greater than",
                "less_than": "is less than",
                "is_empty": "is empty",
                "is_not_empty": "is not empty",
            },
        ),
    )
    right: Any = Field(
        default=None,
        title="Compared with",
        examples=[250],
        json_schema_extra=ui(group="Condition", show_if=_BINARY),
    )


class ConditionSpec(PluginSpec):
    """Route the input payload to the "true" or "false" port."""

    manifest = PluginManifest(
        key="condition",
        name="Condition",
        description="Route the flow based on a comparison.",
        category="logic",
        outputs=[Port(name="true"), Port(name="false")],
    )
    Config = ConditionConfig
