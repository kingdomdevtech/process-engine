"""Builds the "assign from a previous step" picker offered in the designer.

For a given step, this walks the definition backwards to find every step that
can reach it, then flattens those steps' recorded outputs (from the most
recent run) into concrete expression paths such as
``{{ steps.fetch_order.output.customer.id }}``.

Sample values come from real run data, so the picker shows what a field
actually contains — the same trick n8n uses. Without a prior run the picker
still lists the upstream steps and their declared output ports.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any

from process_engine_core.models import ProcessDefinition, ProcessInstance
from process_engine_core.plugin import MAIN_PORT

_SAFE_REFERENCE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

MAX_PATHS_PER_STEP = 120
MAX_DEPTH = 6
CLOSE = " }}"  # a literal, not an f-string: "}}" inside an f-string collapses to "}"


def upstream_step_ids(definition: ProcessDefinition, step_id: str) -> list[str]:
    """Every step that can reach ``step_id``, in definition order."""
    incoming: dict[str, list[str]] = defaultdict(list)
    for conn in definition.connections:
        incoming[conn.target].append(conn.source)

    seen: set[str] = set()
    queue = deque(incoming.get(step_id, []))
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(incoming.get(current, []))
    return [step.id for step in definition.steps if step.id in seen]


def reference_for(step) -> str:
    """How to address a step inside an expression.

    Expressions are dotted paths, so a display name only works when it is a
    plain identifier ("fetch_order"). Anything else — spaces, dots, punctuation
    — falls back to the step id, which is always safe.
    """
    if step.name and _SAFE_REFERENCE.fullmatch(step.name):
        return step.name
    return step.id


def _flatten(value: Any, prefix: str, out: list[dict[str, Any]], depth: int = 0) -> None:
    if len(out) >= MAX_PATHS_PER_STEP or depth > MAX_DEPTH:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key.replace("_", "").isalnum():
                continue  # not addressable with dotted-path expressions
            _flatten(item, f"{prefix}.{key}", out, depth + 1)
        return
    if isinstance(value, list):
        out.append({"path": prefix, "type": "array", "preview": f"{len(value)} item(s)"})
        if value:
            _flatten(value[0], f"{prefix}.0", out, depth + 1)
        return
    out.append({"path": prefix, "type": _type_name(value), "preview": _preview(value)})


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    return {bool: "boolean", int: "number", float: "number", str: "string"}.get(type(value), "value")


def _preview(value: Any) -> str:
    text = "null" if value is None else str(value)
    return text if len(text) <= 48 else f"{text[:45]}…"


def build_picker(
    definition: ProcessDefinition,
    step_id: str,
    instance: ProcessInstance | None,
    registry=None,
) -> list[dict[str, Any]]:
    """Groups of selectable expressions for the given step."""
    groups: list[dict[str, Any]] = []

    trigger_fields: list[dict[str, Any]] = []
    if instance is not None and instance.trigger_input is not None:
        _flatten(instance.trigger_input, "{{ trigger", trigger_fields)
    groups.append(
        {
            "key": "trigger",
            "label": "Trigger data",
            "fields": [{**f, "path": f["path"] + CLOSE} for f in trigger_fields]
            or [{"path": "{{ trigger }}", "type": "value", "preview": "run input"}],
        }
    )

    runs_by_step = {run.step_id: run for run in (instance.step_runs if instance else [])}
    steps_by_id = {step.id: step for step in definition.steps}

    for upstream_id in upstream_step_ids(definition, step_id):
        step = steps_by_id[upstream_id]
        reference = reference_for(step)
        run = runs_by_step.get(upstream_id)
        fields: list[dict[str, Any]] = []
        if run is not None and run.outputs:
            for port, payload in run.outputs.items():
                base = (
                    f"{{{{ steps.{reference}.output"
                    if port == MAIN_PORT
                    else f"{{{{ steps.{reference}.outputs.{port}"
                )
                collected: list[dict[str, Any]] = []
                _flatten(payload, base, collected)
                fields.extend({**f, "path": f["path"] + CLOSE, "port": port} for f in collected)
        if not fields:
            ports = [MAIN_PORT]
            if registry is not None and step.plugin in registry:
                ports = [port.name for port in registry.get(step.plugin).manifest.outputs]
            fields = [
                {
                    "path": f"{{{{ steps.{reference}.output }}}}"
                    if port == MAIN_PORT
                    else f"{{{{ steps.{reference}.outputs.{port} }}}}",
                    "type": "value",
                    "preview": "run the process to see sample data",
                    "port": port,
                }
                for port in ports
            ]
        groups.append(
            {
                "key": upstream_id,
                "label": step.name or step.id,
                "plugin": step.plugin,
                "fields": fields,
            }
        )
    return groups
