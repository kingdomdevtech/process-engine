"""Executes a ProcessDefinition and records a ProcessInstance.

Execution model:

* Entry steps (no incoming connection) receive the trigger input.
* A step runs once all of its incoming connections are settled — each
  upstream step either emitted on the connected port or that path is dead.
  If nothing was delivered, the step is SKIPPED; that is how the untaken
  branch of a condition dies out, and it cascades downstream.
* Every ready step runs as its own task, so independent branches execute
  in parallel — connections are the only ordering guarantee. Each plugin
  attempt executes on a worker thread with its own event loop (one pool
  per Engine, sized by ``step_workers``), so blocking plugin code slows
  only its own step, never the scheduler, the API or other runs.
  Orchestration, storage callbacks and notifications stay on the engine's
  loop; ``ctx.run_subprocess`` hops back to it thread-safely.
* Step config may contain {{ expressions }}; they are resolved against the
  run scope (trigger, steps, variables, input, secrets) just before
  execution, then validated against the Plugin's Config model.
* Retries with exponential backoff and an optional timeout wrap execute().
* A step that still fails after retries routes its error to the "error"
  port if anything is connected there; otherwise the run fails.

Durability and control:

* Pass ``on_update`` to persist the instance after every step — a restart
  can then resume mid-run.
* Pass ``instance`` to resume a PAUSED/interrupted run: steps that already
  SUCCEEDED are replayed from their recorded outputs instead of
  re-executing (completed work is never lost; interrupted steps re-run, so
  side effects are at-least-once).
* Pass a RunControl to request pause/cancel between steps.

Sub-processes:

* When the engine has a ``definition_resolver`` (the API wires it to
  published versions), plugins receive ``ctx.run_subprocess`` — the
  ``for_each`` plugin uses it to iterate a collection. Definitions stay
  acyclic; iteration happens via sub-processes, not loop edges.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from croniter import croniter
from pydantic import ValidationError

from .expressions import ExpressionError, resolve
from .models import (
    ProcessDefinition,
    ProcessInstance,
    RunStatus,
    Step,
    StepRun,
    new_id,
    utcnow,
)
from .plugin import ERROR_PORT, MAIN_PORT, PluginContext, PluginResult
from .registry import PluginRegistry

MAX_SUBPROCESS_DEPTH = 8
_WEBHOOK_PATH = re.compile(r"[A-Za-z0-9_-]+")


class DefinitionError(Exception):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = issues


class RunControl:
    """Cooperative pause/cancel signal, checked by the engine before it
    launches more steps; steps already in flight run to completion first."""

    def __init__(self) -> None:
        self.pause_requested = False
        self.cancel_requested = False

    def check(self) -> str | None:
        if self.cancel_requested:
            return "cancel"
        if self.pause_requested:
            return "pause"
        return None


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


class Engine:
    def __init__(
        self,
        registry: PluginRegistry,
        definition_resolver: Callable[[str], ProcessDefinition | None] | None = None,
        secrets: Mapping | None = None,
        step_workers: int | None = None,
    ) -> None:
        self.registry = registry
        self.definition_resolver = definition_resolver
        self.secrets = secrets
        self.step_workers = step_workers  # None → ThreadPoolExecutor's default sizing
        self._executor: ThreadPoolExecutor | None = None

    def _pool(self) -> ThreadPoolExecutor:
        # lazy, so an Engine used only for validation never spawns threads
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self.step_workers, thread_name_prefix="pe-step"
            )
        return self._executor

    async def run(
        self,
        definition: ProcessDefinition,
        trigger_input: Any = None,
        variables: dict[str, Any] | None = None,
        *,
        instance: ProcessInstance | None = None,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        on_update: Callable[[ProcessInstance], None] | None = None,
        control: RunControl | None = None,
        _depth: int = 0,
    ) -> ProcessInstance:
        issues = validate(definition, self.registry)
        if issues:
            raise DefinitionError(issues)

        resuming = instance is not None
        if resuming:
            trigger_input = instance.trigger_input
            prior = {r.step_id: r for r in instance.step_runs}
            instance.status = RunStatus.RUNNING
            instance.error = None
            instance.finished_at = None
            # a queued placeholder (queue mode) arrives here having never started
            instance.started_at = instance.started_at or utcnow()
        else:
            prior = {}
            instance = ProcessInstance(
                id=run_id or new_id(),
                process_id=definition.id,
                process_version=definition.version,
                status=RunStatus.RUNNING,
                parent_run_id=parent_run_id,
                trigger_input=trigger_input,
                variables={**definition.variables, **(variables or {})},
                started_at=utcnow(),
            )

        steps = {step.id: step for step in definition.steps}
        runs: dict[str, StepRun] = {}
        cached: set[str] = set()
        for step in definition.steps:
            previous = prior.get(step.id)
            if previous is not None and previous.status == RunStatus.SUCCEEDED:
                runs[step.id] = previous  # replayed, not re-executed
                cached.add(step.id)
            else:
                runs[step.id] = StepRun(step_id=step.id, step_name=step.name, plugin=step.plugin)
        instance.step_runs = [runs[step.id] for step in definition.steps]
        self._notify(on_update, instance)

        incoming: dict[str, list] = {step_id: [] for step_id in steps}
        outgoing: dict[str, list] = {step_id: [] for step_id in steps}
        for conn in definition.connections:
            incoming[conn.target].append(conn)
            outgoing[conn.source].append(conn)

        unsettled = {step_id: len(conns) for step_id, conns in incoming.items()}
        deliveries: dict[str, list[tuple[str, Any]]] = defaultdict(list)
        scope: dict[str, Any] = {
            "trigger": trigger_input,
            "variables": instance.variables,
            "secrets": self.secrets if self.secrets is not None else {},
            "steps": {},
        }

        async def run_subprocess(process_key: str, sub_input: Any) -> dict[str, Any]:
            if self.definition_resolver is None:
                raise RuntimeError("sub-process execution requires a definition resolver")
            if _depth + 1 >= MAX_SUBPROCESS_DEPTH:
                raise RuntimeError(f"sub-process depth limit ({MAX_SUBPROCESS_DEPTH}) exceeded")
            sub_definition = self.definition_resolver(process_key)
            if sub_definition is None:
                raise RuntimeError(f"no published process found for {process_key!r}")
            sub_instance = await self.run(
                sub_definition,
                trigger_input=sub_input,
                parent_run_id=instance.id,
                on_update=on_update,
                _depth=_depth + 1,
            )
            return {
                "run_id": sub_instance.id,
                "status": sub_instance.status.value,
                "output": _leaf_output(sub_definition, sub_instance),
                "error": sub_instance.error,
            }

        main_loop = asyncio.get_running_loop()

        async def run_subprocess_threadsafe(process_key: str, sub_input: Any) -> dict[str, Any]:
            # plugins execute on worker-thread loops; sub-processes must come
            # back to the engine's loop, where storage and notification
            # callbacks are safe to call
            return await asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(run_subprocess(process_key, sub_input), main_loop)
            )

        ready = deque(step_id for step_id, count in unsettled.items() if count == 0)
        running: set[asyncio.Task] = set()
        fatal: str | None = None
        paused = False
        cancelled = False

        async def execute_ready(step_id: str) -> tuple[str, dict[str, Any], str | None]:
            input_payload, all_inputs = combine_deliveries(
                deliveries.get(step_id, []), trigger_input, bool(incoming[step_id])
            )
            outputs, error = await self._execute_step(
                steps[step_id], runs[step_id], input_payload, all_inputs, scope, instance,
                run_subprocess_threadsafe,
            )
            return step_id, outputs, error

        def absorb(step_id: str, outputs: dict[str, Any], error: str | None) -> None:
            """Record a finished step and settle its downstream connections."""
            nonlocal fatal
            step = steps[step_id]
            if error is not None:
                if any(conn.source_port == ERROR_PORT for conn in outgoing[step_id]):
                    # routed failure: the error branch handles it, the run goes on
                    outputs = {ERROR_PORT: {"error": error, "step": step.name or step.id}}
                else:
                    if fatal is None:  # parallel failures: the first names the run error
                        fatal = f"step {step.name or step.id!r} failed: {error}"
                    return
            entry = {"output": outputs.get(MAIN_PORT), "outputs": outputs}
            scope["steps"][step_id] = entry
            if step.name:
                scope["steps"].setdefault(step.name, entry)
            self._settle_downstream(step_id, outputs, outgoing, unsettled, deliveries, ready)
            self._notify(on_update, instance)

        while ready or running:
            signal = control.check() if control is not None else None
            if signal == "cancel":
                cancelled = True
                break
            if signal == "pause":
                paused = True
                break

            # every ready step becomes its own task — independent branches run
            # in parallel; replays and skips settle synchronously and may ready
            # further steps within the same pass
            while ready:
                step_id = ready.popleft()
                if step_id in cached:
                    absorb(step_id, runs[step_id].outputs, None)  # durability replay
                elif incoming[step_id] and not deliveries.get(step_id):
                    # every upstream path is dead — cascade the skip
                    runs[step_id].status = RunStatus.SKIPPED
                    self._settle_downstream(step_id, {}, outgoing, unsettled, deliveries, ready)
                else:
                    running.add(asyncio.create_task(execute_ready(step_id)))

            if not running:
                continue  # replays/skips may have readied more; otherwise the loop ends
            done, running = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                absorb(*task.result())
            if fatal:
                break

        if running:
            # pause, cancel or a failure stops new launches; steps already in
            # flight run to completion so their work is recorded honestly
            for result in await asyncio.gather(*running):
                absorb(*result)

        if paused and fatal is None:
            instance.status = RunStatus.PAUSED
        else:
            for run in runs.values():
                if run.status == RunStatus.PENDING:
                    run.status = RunStatus.SKIPPED
            if cancelled:
                instance.status = RunStatus.CANCELLED
            elif fatal:
                instance.status = RunStatus.FAILED
            else:
                instance.status = RunStatus.SUCCEEDED
            instance.finished_at = utcnow()
        instance.error = fatal
        self._notify(on_update, instance)
        return instance

    async def preview_step(
        self,
        definition: ProcessDefinition,
        step_id: str,
        instance: ProcessInstance | None = None,
        variables: dict[str, Any] | None = None,
        trigger_input: Any = None,
    ) -> tuple[StepRun, Any, dict[str, Any]]:
        """Execute one step on its own, using data recorded by a previous run.

        This is the designer's "test this step": it resolves the step's
        expressions against the recorded run, executes the plugin for real, and
        returns ``(step_run, input, resolved_config)`` without touching the
        stored run history.

        The plugin really runs, so a step with side effects (send mail, write a
        row) will perform them — the same trade-off n8n makes when you test a
        single node.
        """
        step = next((s for s in definition.steps if s.id == step_id), None)
        if step is None:
            raise DefinitionError([f"no step {step_id!r} in this process"])
        if step.plugin not in self.registry:
            raise DefinitionError([f"step uses unknown plugin {step.plugin!r}"])

        if instance is not None and trigger_input is None:
            trigger_input = instance.trigger_input

        scope: dict[str, Any] = {
            "trigger": trigger_input,
            "variables": {**definition.variables, **(instance.variables if instance else {}), **(variables or {})},
            "secrets": self.secrets if self.secrets is not None else {},
            "steps": {},
        }
        steps_by_id = {s.id: s for s in definition.steps}
        for run in instance.step_runs if instance else []:
            entry = {"output": run.outputs.get(MAIN_PORT), "outputs": run.outputs}
            scope["steps"][run.step_id] = entry
            source = steps_by_id.get(run.step_id)
            if source is not None and source.name:
                scope["steps"].setdefault(source.name, entry)

        has_incoming = any(conn.target == step_id for conn in definition.connections)
        delivered = deliveries_from_run(definition, step_id, instance)
        input_payload, all_inputs = combine_deliveries(delivered, trigger_input, has_incoming)

        holder = ProcessInstance(
            id=f"preview-{new_id()[:8]}",
            process_id=definition.id,
            process_version=definition.version,
            variables=scope["variables"],
        )
        step_run = StepRun(step_id=step.id, step_name=step.name, plugin=step.plugin)
        resolved: dict[str, Any] = {}
        try:
            resolved = resolve(step.config, {**scope, "input": input_payload})
        except ExpressionError:
            pass  # _execute_step re-resolves and records the error properly

        await self._execute_step(step, step_run, input_payload, all_inputs, scope, holder, None)
        return step_run, input_payload, resolved

    @staticmethod
    def _notify(on_update: Callable[[ProcessInstance], None] | None, instance: ProcessInstance) -> None:
        if on_update is None:
            return
        try:
            on_update(instance)
        except Exception:  # noqa: BLE001 — persistence hiccups must not kill the run
            logging.getLogger("process_engine.engine").exception("on_update callback failed")

    @staticmethod
    def _settle_downstream(
        step_id: str,
        outputs: dict[str, Any],
        outgoing: dict[str, list],
        unsettled: dict[str, int],
        deliveries: dict[str, list[tuple[str, Any]]],
        ready: deque,
    ) -> None:
        for conn in outgoing[step_id]:
            if conn.source_port in outputs:
                deliveries[conn.target].append((conn.target_port, outputs[conn.source_port]))
            unsettled[conn.target] -= 1
            if unsettled[conn.target] == 0:
                ready.append(conn.target)

    async def _execute_step(
        self,
        step: Step,
        run: StepRun,
        input_payload: Any,
        all_inputs: dict[str, list[Any]],
        scope: dict[str, Any],
        instance: ProcessInstance,
        run_subprocess: Any,
    ) -> tuple[dict[str, Any], str | None]:
        plugin_cls = self.registry.get(step.plugin)
        run.status = RunStatus.RUNNING
        run.started_at = utcnow()
        run.input = input_payload
        # duration comes off the monotonic clock — wall timestamps can jump
        clock_started = time.perf_counter()

        def stop_clock() -> None:
            run.finished_at = utcnow()
            run.duration_ms = round((time.perf_counter() - clock_started) * 1000, 3)

        try:
            resolved = resolve(step.config, {**scope, "input": input_payload})
            config = plugin_cls.Config.model_validate(resolved)
        except (ExpressionError, ValidationError) as exc:
            run.status = RunStatus.FAILED
            run.error = str(exc)
            stop_clock()
            return {}, str(exc)

        logger = logging.getLogger(f"process_engine.run.{instance.id[:8]}.{step.name or step.id[:8]}")
        ctx = PluginContext(
            run_id=instance.id,
            step_id=step.id,
            step_name=step.name,
            config=config,
            input=input_payload,
            all_inputs=all_inputs,
            variables=instance.variables,
            logger=logger,
            run_subprocess=run_subprocess,
        )

        loop = asyncio.get_running_loop()
        last_error: str | None = None
        for attempt in range(1, step.retry.max_attempts + 1):
            run.attempts = attempt
            try:
                raw = await loop.run_in_executor(
                    self._pool(), self._call_plugin, plugin_cls, ctx, step.timeout_seconds
                )
                outputs = self._normalize(raw)
                run.outputs = outputs
                run.status = RunStatus.SUCCEEDED
                stop_clock()
                return outputs, None
            except Exception as exc:  # noqa: BLE001 — plugin code is arbitrary
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("attempt %d/%d failed: %s", attempt, step.retry.max_attempts, last_error)
                if attempt < step.retry.max_attempts:
                    await asyncio.sleep(step.retry.backoff_seconds * (2 ** (attempt - 1)))

        run.status = RunStatus.FAILED
        run.error = last_error
        stop_clock()
        return {}, last_error

    @staticmethod
    def _call_plugin(plugin_cls: type, ctx: PluginContext, timeout_seconds: float | None) -> Any:
        """Worker-thread entry: run one plugin attempt on its own event loop.

        Blocking plugin code stalls only this thread — the engine's loop keeps
        orchestrating other steps and runs. The timeout is enforced here so a
        cooperative (awaiting) plugin really is cancelled when it expires; a
        plugin that blocks through its timeout is abandoned only when it
        eventually returns, exactly as before.
        """
        coroutine = plugin_cls().execute(ctx)
        if timeout_seconds:
            coroutine = asyncio.wait_for(coroutine, timeout_seconds)
        return asyncio.run(coroutine)

    @staticmethod
    def _normalize(raw: PluginResult | dict[str, Any] | None) -> dict[str, Any]:
        if isinstance(raw, PluginResult):
            return raw.outputs
        return {MAIN_PORT: raw}


def _leaf_output(definition: ProcessDefinition, instance: ProcessInstance) -> Any:
    """The sub-process "result": main output of steps with no outgoing connection."""
    sources = {conn.source for conn in definition.connections}
    runs = {run.step_id: run for run in instance.step_runs}
    leaves: dict[str, Any] = {}
    for step in definition.steps:
        if step.id in sources:
            continue
        run = runs.get(step.id)
        if run is not None and run.status == RunStatus.SUCCEEDED:
            leaves[step.name or step.id] = run.outputs.get(MAIN_PORT)
    if len(leaves) == 1:
        return next(iter(leaves.values()))
    return leaves
