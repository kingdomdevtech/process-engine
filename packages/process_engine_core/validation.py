"""Static checks on a definition, and the payload shapes both tiers must agree on.

None of this executes anything, which is why it is here rather than beside the
engine. The designer's API validates on save, refuses to publish a broken
definition, and badges the offending node — all without holding the code that
would run it. An engine host validates again before it starts, from this same
function, so the two can never disagree about what is publishable.

The delivery helpers are here for the same reason. ``combine_deliveries`` decides
what a step receives, and it must produce byte-identical input whether a step is
running for real or being previewed on its own; ``preview_result`` shapes the
answer to "test this step" wherever it was tested. One definition of each, shared,
rather than one per call site.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any

from croniter import croniter

from .models import ProcessDefinition, ProcessInstance, StepRun
from .plugin import ERROR_PORT, MAIN_PORT
from .registry import PluginRegistry

_WEBHOOK_PATH = re.compile(r"[A-Za-z0-9_-]+")


class DefinitionError(Exception):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = issues


def validate_detailed(definition: ProcessDefinition, registry: PluginRegistry) -> list[dict[str, Any]]:
    """Static checks; each issue is {"message": ..., "step_id": ...} (step_id
    optional) so the designer can badge the offending node."""
    issues: list[dict[str, Any]] = []

    def issue(message: str, step_id: str | None = None) -> None:
        entry: dict[str, Any] = {"message": message}
        if step_id:
            entry["step_id"] = step_id
        issues.append(entry)

    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for step in definition.steps:
        label = step.name or step.id
        if step.id in seen_ids:
            issue(f"duplicate step id {step.id!r}", step.id)
        seen_ids.add(step.id)
        if step.name:
            if step.name in seen_names:
                issue(f"duplicate step name {step.name!r}", step.id)
            seen_names.add(step.name)
        if step.plugin not in registry:
            issue(f"step {label!r} uses unknown plugin {step.plugin!r}", step.id)

    steps_by_id = {step.id: step for step in definition.steps}
    for conn in definition.connections:
        if conn.source not in steps_by_id or conn.target not in steps_by_id:
            issue(f"connection {conn.id} references a missing step")
            continue
        source = steps_by_id[conn.source]
        if source.plugin in registry:
            manifest = registry.get(source.plugin).manifest
            output_ports = {port.name for port in manifest.outputs} | {ERROR_PORT}
            if conn.source_port not in output_ports:
                issue(f"step {source.name or source.id!r} has no output port {conn.source_port!r}", source.id)
        target = steps_by_id[conn.target]
        if target.plugin in registry:
            manifest = registry.get(target.plugin).manifest
            if conn.target_port not in {port.name for port in manifest.inputs}:
                issue(f"step {target.name or target.id!r} has no input port {conn.target_port!r}", target.id)

    for trigger in definition.triggers:
        if trigger.type == "schedule" and not (trigger.cron and croniter.is_valid(trigger.cron)):
            issue(f"schedule trigger has an invalid cron expression {trigger.cron!r}")
        elif trigger.type == "webhook" and trigger.path and not _WEBHOOK_PATH.fullmatch(trigger.path):
            issue(f"webhook path {trigger.path!r} may only contain letters, digits, '-' and '_'")

    # cycle check (Kahn's algorithm) — the graph must stay acyclic; iterate with for_each
    indegree = {step_id: 0 for step_id in steps_by_id}
    adjacency: dict[str, list[str]] = defaultdict(list)
    for conn in definition.connections:
        if conn.source in indegree and conn.target in indegree:
            indegree[conn.target] += 1
            adjacency[conn.source].append(conn.target)
    queue = deque(step_id for step_id, degree in indegree.items() if degree == 0)
    processed = 0
    while queue:
        step_id = queue.popleft()
        processed += 1
        for nxt in adjacency[step_id]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if processed < len(steps_by_id):
        issue("definition contains a cycle (use the for_each plugin to iterate)")
    return issues


def validate(definition: ProcessDefinition, registry: PluginRegistry) -> list[str]:
    return [entry["message"] for entry in validate_detailed(definition, registry)]


def combine_deliveries(
    delivered: list[tuple[str, Any]], trigger_input: Any, has_incoming: bool
) -> tuple[Any, dict[str, list[Any]]]:
    """What a step receives as ``ctx.input`` / ``ctx.all_inputs``.

    Entry steps get the trigger payload. A step with exactly one delivery gets
    that payload directly; at a join it gets ``{port: [payloads]}``. Shared by
    real runs and single-step previews so both see identical input.
    """
    if not has_incoming:
        return trigger_input, ({MAIN_PORT: [trigger_input]} if trigger_input is not None else {})
    grouped: dict[str, list[Any]] = defaultdict(list)
    for port, payload in delivered:
        grouped[port].append(payload)
    grouped = dict(grouped)
    payloads = [payload for _, payload in delivered]
    return (payloads[0] if len(payloads) == 1 else dict(grouped)), grouped


def preview_result(
    step_run: StepRun, step_input: Any, resolved_config: dict[str, Any], based_on_run: str | None
) -> dict[str, Any]:
    """The designer's answer to "test this step", from a ``preview_step`` result.

    Built here rather than at the call site because there are two call sites: an
    engine host previews the step and posts this back through the queue, and the
    API renders it. The person in the designer must not be able to tell the
    difference between that and a preview answered on the spot.
    """
    return {
        "status": step_run.status.value,
        "input": step_input,
        "resolved_config": resolved_config,
        "outputs": step_run.outputs,
        "output": step_run.outputs.get(MAIN_PORT),
        "error": step_run.error,
        "attempts": step_run.attempts,
        "duration_ms": step_run.duration_ms,
        "based_on_run": based_on_run,
    }


def deliveries_from_run(
    definition: ProcessDefinition, step_id: str, instance: ProcessInstance | None
) -> list[tuple[str, Any]]:
    """Payloads a previous run delivered into ``step_id`` (for previews)."""
    runs = {run.step_id: run for run in (instance.step_runs if instance else [])}
    delivered: list[tuple[str, Any]] = []
    for conn in definition.connections:
        if conn.target != step_id:
            continue
        source = runs.get(conn.source)
        if source is not None and conn.source_port in source.outputs:
            delivered.append((conn.target_port, source.outputs[conn.source_port]))
    return delivered
