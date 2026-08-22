from typing import Any

from process_engine_core.plugin import Plugin, PluginContext, PluginResult
from process_engine_core.plugins.condition import ConditionConfig, ConditionSpec


class ConditionPlugin(ConditionSpec, Plugin):
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
