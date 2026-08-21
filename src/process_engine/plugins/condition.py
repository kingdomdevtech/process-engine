from typing import Any, Literal

from pydantic import BaseModel, Field

from ..plugin import Plugin, PluginContext, PluginManifest, PluginResult, Port
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


class ConditionPlugin(Plugin):
    """Route the input payload to the "true" or "false" port."""

    manifest = PluginManifest(
        key="condition",
        name="Condition",
        description="Route the flow based on a comparison.",
        category="logic",
        outputs=[Port(name="true"), Port(name="false")],
    )
    Config = ConditionConfig

    async def execute(self, ctx: PluginContext) -> PluginResult:
        cfg: ConditionConfig = ctx.config
        port = "true" if _evaluate(cfg.left, cfg.operator, cfg.right) else "false"
        return PluginResult.on(port, ctx.input)


def _evaluate(left: Any, operator: str, right: Any) -> bool:
    match operator:
        case "equals":
            return left == right
        case "not_equals":
            return left != right
        case "contains":
            try:
                return right in left
            except TypeError:
                return False
        case "greater_than":
            return float(left) > float(right)
        case "less_than":
            return float(left) < float(right)
        case "is_empty":
            return left in (None, "", [], {})
        case "is_not_empty":
            return left not in (None, "", [], {})
    return False
