"""Safe ``{{ ... }}`` expression resolution for step config.

Supported forms (dotted-path lookups only — never code evaluation):

    {{ trigger.customer.id }}             data the run was started with
    {{ steps.fetch_order.output.total }}  a previous step's "main" output
    {{ steps.fetch_order.outputs.error }} any output port by name
    {{ variables.region }}                process variables
    {{ input.items.0.sku }}               this step's input payload

A string that consists of exactly one expression resolves to the raw value
(keeping its type); expressions embedded in a longer string are interpolated
as text. Dicts and lists are resolved recursively.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

_EXPR = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


class ExpressionError(Exception):
    pass


def resolve(value: Any, scope: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _resolve_string(value, scope)
    if isinstance(value, dict):
        return {key: resolve(item, scope) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, scope) for item in value]
    return value


def _resolve_string(text: str, scope: dict[str, Any]) -> Any:
    whole = _EXPR.fullmatch(text.strip())
    if whole:
        return _lookup(whole.group(1).strip(), scope)
    return _EXPR.sub(lambda match: _to_text(_lookup(match.group(1).strip(), scope)), text)


def _to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def _lookup(path: str, scope: dict[str, Any]) -> Any:
    current: Any = scope
    walked: list[str] = []
    for part in path.split("."):
        walked.append(part)
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, (list, tuple)) and part.lstrip("-").isdigit():
            try:
                current = current[int(part)]
            except IndexError:
                raise ExpressionError(f"cannot resolve {{{{ {path} }}}}: index {part} out of range") from None
        else:
            location = ".".join(walked[:-1]) or "scope root"
            raise ExpressionError(f"cannot resolve {{{{ {path} }}}}: no {part!r} at {location}") from None
    return current
