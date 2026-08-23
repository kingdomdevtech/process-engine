import asyncio
import threading

import pytest

from process_engine.engine import Engine, RunControl
from process_engine_core.validation import DefinitionError, validate, validate_detailed
from process_engine_core.models import Connection, ProcessDefinition, RetryPolicy, RunStatus, Step, Trigger
from process_engine_core.plugin import Plugin, PluginManifest, PluginResult
from process_engine.registry import default_registry


class FlakyPlugin(Plugin):
    manifest = PluginManifest(key="flaky", name="Flaky")
    calls = 0

    async def execute(self, ctx):
        type(self).calls += 1
        if type(self).calls < 3:
            raise RuntimeError("boom")
        return PluginResult.main({"ok": True})


class AlwaysFailPlugin(Plugin):
    manifest = PluginManifest(key="always_fail", name="Always fail")

    async def execute(self, ctx):
        raise RuntimeError("kaput")


class SlowPlugin(Plugin):
    manifest = PluginManifest(key="slow", name="Slow")

    async def execute(self, ctx):
        await asyncio.sleep(0.05)
        return PluginResult.main({"ok": True})


def make_registry(*extra):
    registry = default_registry()
    for plugin_cls in extra:
        registry.register(plugin_cls)
    return registry


def run_of(instance, step_id):
    return next(r for r in instance.step_runs if r.step_id == step_id)


def branching_definition():
    return ProcessDefinition(
        steps=[
            Step(id="enrich", name="enrich", plugin="transform",
                 config={"values": {"total": "{{ trigger.total }}"}}),
            Step(id="check", name="check", plugin="condition",
                 config={"left": "{{ steps.enrich.output.total }}", "operator": "greater_than", "right": 100}),
            Step(id="big", name="big", plugin="log", config={"message": "big"}),
            Step(id="small", name="small", plugin="log", config={"message": "small"}),
        ],
        connections=[
            Connection(source="enrich", target="check"),
            Connection(source="check", source_port="true", target="big"),
            Connection(source="check", source_port="false", target="small"),
        ],
    )


async def test_branching_skips_untaken_path():
    instance = await Engine(make_registry()).run(branching_definition(), trigger_input={"total": 250})
    assert instance.status == RunStatus.SUCCEEDED
    assert run_of(instance, "big").status == RunStatus.SUCCEEDED
    assert run_of(instance, "small").status == RunStatus.SKIPPED
    # the condition passes its input (enrich's output) through to the taken branch
    assert run_of(instance, "big").outputs == {"main": {"total": 250}}


async def test_other_branch_when_condition_false():
    instance = await Engine(make_registry()).run(branching_definition(), trigger_input={"total": 10})
    assert run_of(instance, "big").status == RunStatus.SKIPPED
    assert run_of(instance, "small").status == RunStatus.SUCCEEDED


async def test_retry_until_success():
    FlakyPlugin.calls = 0
    definition = ProcessDefinition(
        steps=[Step(id="flaky", plugin="flaky", retry=RetryPolicy(max_attempts=3, backoff_seconds=0))],
    )
    instance = await Engine(make_registry(FlakyPlugin)).run(definition)
    assert instance.status == RunStatus.SUCCEEDED
    assert run_of(instance, "flaky").attempts == 3


async def test_step_records_duration():
    definition = ProcessDefinition(steps=[Step(id="slow", plugin="slow")])
    instance = await Engine(make_registry(SlowPlugin)).run(definition)
    run = run_of(instance, "slow")
    assert run.duration_ms >= 40
    assert run.started_at is not None and run.finished_at is not None


async def test_skipped_step_has_no_duration():
    instance = await Engine(make_registry()).run(branching_definition(), trigger_input={"total": 250})
    assert run_of(instance, "big").duration_ms is not None
    assert run_of(instance, "small").duration_ms is None  # never executed


async def test_failed_step_duration_covers_retries():
    definition = ProcessDefinition(
        steps=[Step(id="doom", plugin="always_fail", retry=RetryPolicy(max_attempts=2, backoff_seconds=0.05))],
    )
    instance = await Engine(make_registry(AlwaysFailPlugin)).run(definition)
    run = run_of(instance, "doom")
    assert run.status == RunStatus.FAILED
    assert run.duration_ms >= 40  # the backoff sleep sits inside the step's clock


async def test_unrouted_failure_fails_run():
    definition = ProcessDefinition(
        steps=[
            Step(id="doom", name="doom", plugin="always_fail"),
            Step(id="after", plugin="log"),
        ],
        connections=[Connection(source="doom", target="after")],
    )
    instance = await Engine(make_registry(AlwaysFailPlugin)).run(definition)
    assert instance.status == RunStatus.FAILED
    assert "doom" in instance.error
    assert run_of(instance, "after").status == RunStatus.SKIPPED


async def test_error_port_routes_failure():
    definition = ProcessDefinition(
        steps=[
            Step(id="doom", plugin="always_fail"),
            Step(id="handler", plugin="log", config={"message": "{{ input.error }}"}),
        ],
        connections=[Connection(source="doom", source_port="error", target="handler")],
    )
    instance = await Engine(make_registry(AlwaysFailPlugin)).run(definition)
    assert instance.status == RunStatus.SUCCEEDED
    assert run_of(instance, "doom").status == RunStatus.FAILED
    handler = run_of(instance, "handler")
    assert handler.status == RunStatus.SUCCEEDED
    assert "kaput" in handler.input["error"]


class BlockingRendezvousPlugin(Plugin):
    """Blocks its worker thread until two steps are inside execute() at once.

    Succeeds only when independent steps really run in parallel on separate
    threads: a sequential or single-threaded engine would block on the first
    barrier wait and break it on timeout, failing the run.
    """

    manifest = PluginManifest(key="blocking_rendezvous", name="Blocking rendezvous")
    barrier: threading.Barrier | None = None

    async def execute(self, ctx):
        type(self).barrier.wait(timeout=5)  # deliberately blocking, no await
        return PluginResult.main({"ok": True})


async def test_independent_steps_run_in_parallel_threads():
    BlockingRendezvousPlugin.barrier = threading.Barrier(2)
    definition = ProcessDefinition(
        steps=[
            Step(id="a", plugin="blocking_rendezvous"),
            Step(id="b", plugin="blocking_rendezvous"),
        ],
    )
    instance = await Engine(make_registry(BlockingRendezvousPlugin)).run(definition)
    assert instance.status == RunStatus.SUCCEEDED
    assert run_of(instance, "a").status == RunStatus.SUCCEEDED
    assert run_of(instance, "b").status == RunStatus.SUCCEEDED


async def test_a_skipped_branch_does_not_reach_a_parallel_sibling():
    """The shape the demo sub-process uses: two steps hang off the trigger and run
    at once, one of them a condition. Exactly one of its branches is skipped, and
    the skip must stay on that branch — a cascade that reached the sibling would
    make the whole thing a chain that happens to look parallel.

    So a healthy run of this graph is 3 succeeded and 1 skipped, which is why the
    UI gate has to count skips rather than forbid them (see `expectRunPassed`).
    """
    # "note" and the taken branch must be inside execute() at the same time, so a
    # lane that only *looks* parallel leaves "note" waiting until the barrier
    # breaks and the run fails rather than quietly passing.
    BlockingRendezvousPlugin.barrier = threading.Barrier(2)
    definition = ProcessDefinition(
        steps=[
            Step(id="note", plugin="blocking_rendezvous"),  # runs beside the condition
            Step(id="check", name="check", plugin="condition",
                 config={"left": "{{ trigger.amount }}", "operator": "greater_than", "right": 500}),
            Step(id="approve", plugin="blocking_rendezvous"),
            Step(id="reject", plugin="log", config={"message": "on hold"}),
        ],
        connections=[
            Connection(source="check", source_port="true", target="approve"),
            Connection(source="check", source_port="false", target="reject"),
        ],
    )
    instance = await Engine(make_registry(BlockingRendezvousPlugin)).run(definition, trigger_input={"amount": 900})
    assert instance.status == RunStatus.SUCCEEDED
    assert run_of(instance, "note").status == RunStatus.SUCCEEDED
    assert run_of(instance, "approve").status == RunStatus.SUCCEEDED
    assert run_of(instance, "reject").status == RunStatus.SKIPPED
    statuses = [run.status for run in instance.step_runs]
    assert statuses.count(RunStatus.SKIPPED) == 1


async def test_failure_lets_inflight_sibling_finish():
    definition = ProcessDefinition(
        steps=[
            Step(id="doom", name="doom", plugin="always_fail"),
            Step(id="side", plugin="slow"),
        ],
    )
    instance = await Engine(make_registry(AlwaysFailPlugin, SlowPlugin)).run(definition)
    assert instance.status == RunStatus.FAILED
    assert "doom" in instance.error
    # "side" was already in flight when doom failed; it runs to completion
    assert run_of(instance, "side").status == RunStatus.SUCCEEDED


async def test_parallel_join_receives_both_payloads():
    definition = ProcessDefinition(
        steps=[
            Step(id="a", plugin="transform", config={"values": {"from": "a"}, "mode": "replace"}),
            Step(id="b", plugin="transform", config={"values": {"from": "b"}, "mode": "replace"}),
            Step(id="join", plugin="log"),
        ],
        connections=[
            Connection(source="a", target="join"),
            Connection(source="b", target="join"),
        ],
    )
    instance = await Engine(make_registry()).run(definition)
    assert instance.status == RunStatus.SUCCEEDED
    join_input = run_of(instance, "join").input
    assert {"from": "a"} in join_input["main"] and {"from": "b"} in join_input["main"]


async def test_cycle_rejected():
    definition = ProcessDefinition(
        steps=[Step(id="a", plugin="log"), Step(id="b", plugin="log")],
        connections=[Connection(source="a", target="b"), Connection(source="b", target="a")],
    )
    with pytest.raises(DefinitionError, match="cycle"):
        await Engine(make_registry()).run(definition)


async def test_unknown_plugin_rejected():
    definition = ProcessDefinition(steps=[Step(id="x", plugin="does_not_exist")])
    with pytest.raises(DefinitionError, match="unknown plugin"):
        await Engine(make_registry()).run(definition)


# -- durability: pause / resume / cancel --------------------------------------------


class CountingPlugin(Plugin):
    manifest = PluginManifest(key="counting", name="Counting")
    executions = 0

    async def execute(self, ctx):
        type(self).executions += 1
        return PluginResult.main({"n": type(self).executions})


class ScriptedControl(RunControl):
    """Deterministic control: returns the scripted signals, then None forever."""

    def __init__(self, script):
        super().__init__()
        self.script = list(script)

    def check(self):
        return self.script.pop(0) if self.script else None


def chain_definition():
    return ProcessDefinition(
        steps=[
            Step(id="a", plugin="counting"),
            Step(id="b", plugin="counting"),
            Step(id="c", plugin="counting"),
        ],
        connections=[Connection(source="a", target="b"), Connection(source="b", target="c")],
    )


async def test_pause_then_resume_replays_completed_steps():
    CountingPlugin.executions = 0
    engine = Engine(make_registry(CountingPlugin))
    definition = chain_definition()

    paused = await engine.run(definition, control=ScriptedControl([None, "pause"]))
    assert paused.status == RunStatus.PAUSED
    assert run_of(paused, "a").status == RunStatus.SUCCEEDED
    assert run_of(paused, "b").status == RunStatus.PENDING
    assert CountingPlugin.executions == 1

    resumed = await engine.run(definition, instance=paused)
    assert resumed.status == RunStatus.SUCCEEDED
    assert [run_of(resumed, sid).status for sid in "abc"] == [RunStatus.SUCCEEDED] * 3
    # step "a" was replayed from its recorded outputs, not re-executed
    assert CountingPlugin.executions == 3


async def test_cancel_marks_remaining_steps_skipped():
    CountingPlugin.executions = 0
    engine = Engine(make_registry(CountingPlugin))
    instance = await engine.run(chain_definition(), control=ScriptedControl([None, "cancel"]))
    assert instance.status == RunStatus.CANCELLED
    assert run_of(instance, "a").status == RunStatus.SUCCEEDED
    assert run_of(instance, "b").status == RunStatus.SKIPPED
    assert run_of(instance, "c").status == RunStatus.SKIPPED


# -- for_each sub-process iteration ---------------------------------------------------


def sub_definition():
    return ProcessDefinition(
        id="sub",
        version=1,
        steps=[
            Step(id="echo", name="echo", plugin="transform",
                 config={"mode": "replace",
                         "values": {"echo": "{{ trigger.item }}", "idx": "{{ trigger.index }}"}}),
        ],
    )


async def test_for_each_runs_subprocess_per_item():
    resolver = {"sub": sub_definition()}
    engine = Engine(make_registry(), definition_resolver=resolver.get)
    definition = ProcessDefinition(
        steps=[Step(id="fan", plugin="for_each",
                    config={"mode": "process", "items": "{{ trigger.items }}", "process_id": "sub", "parallel": 2})],
    )
    instance = await engine.run(definition, trigger_input={"items": ["a", "b", "c"]})
    assert instance.status == RunStatus.SUCCEEDED
    result = run_of(instance, "fan").outputs["main"]
    assert result["count"] == 3 and result["failed"] == 0
    assert [r["output"]["echo"] for r in result["results"]] == ["a", "b", "c"]
    assert [r["output"]["idx"] for r in result["results"]] == [0, 1, 2]


async def test_for_each_detects_array_in_trigger_payload_without_manual_items():
    resolver = {"sub": sub_definition()}
    engine = Engine(make_registry(), definition_resolver=resolver.get)
    definition = ProcessDefinition(
        steps=[Step(id="fan", plugin="for_each", config={"mode": "process", "process_id": "sub"})],
    )
    instance = await engine.run(definition, trigger_input={"rows": ["a", "b", "c"]})
    assert instance.status == RunStatus.SUCCEEDED
    result = run_of(instance, "fan").outputs["main"]
    assert result["count"] == 3 and result["failed"] == 0
    assert [r["output"]["echo"] for r in result["results"]] == ["a", "b", "c"]


async def test_for_each_treats_blank_items_as_auto_detect():
    resolver = {"sub": sub_definition()}
    engine = Engine(make_registry(), definition_resolver=resolver.get)
    definition = ProcessDefinition(
        steps=[Step(id="fan", plugin="for_each", config={"mode": "process", "items": "", "process_id": "sub"})],
    )
    instance = await engine.run(definition, trigger_input={"rows": ["a", "b", "c"]})
    assert instance.status == RunStatus.SUCCEEDED
    result = run_of(instance, "fan").outputs["main"]
    assert result["count"] == 3 and result["failed"] == 0
    assert [r["output"]["echo"] for r in result["results"]] == ["a", "b", "c"]


async def test_for_each_ignores_stale_item_reference_and_uses_upstream_input():
    resolver = {"sub": sub_definition()}
    engine = Engine(make_registry(), definition_resolver=resolver.get)
    definition = ProcessDefinition(
        steps=[Step(id="fan", plugin="for_each",
                    config={"mode": "process", "items": "steps.fetch.output.rows", "process_id": "sub"})],
    )
    instance = await engine.run(definition, trigger_input={"rows": ["a", "b", "c"]})
    assert instance.status == RunStatus.SUCCEEDED
    result = run_of(instance, "fan").outputs["main"]
    assert result["count"] == 3 and result["failed"] == 0
    assert [r["output"]["echo"] for r in result["results"]] == ["a", "b", "c"]


async def test_for_each_ignores_missing_step_reference_in_items_expression_and_uses_upstream_input():
    resolver = {"sub": sub_definition()}
    engine = Engine(make_registry(), definition_resolver=resolver.get)
    definition = ProcessDefinition(
        steps=[Step(id="fan", plugin="for_each",
                    config={"mode": "process", "items": "{{ steps.fetch.output.rows }}", "process_id": "sub"})],
    )
    instance = await engine.run(definition, trigger_input={"rows": ["a", "b", "c"]})
    assert instance.status == RunStatus.SUCCEEDED
    result = run_of(instance, "fan").outputs["main"]
    assert result["count"] == 3 and result["failed"] == 0
    assert [r["output"]["echo"] for r in result["results"]] == ["a", "b", "c"]


async def test_for_each_uses_valid_step_reference_when_previous_step_output_is_a_list():
    resolver = {"sub": sub_definition()}
    engine = Engine(make_registry(), definition_resolver=resolver.get)
    definition = ProcessDefinition(
        steps=[
            Step(id="orders", name="orders", plugin="transform",
                 config={"mode": "replace", "values": {"rows": ["a", "b", "c"]}}),
            Step(id="fan", plugin="for_each",
                 config={"mode": "process", "items": "{{ steps.orders.output.rows }}", "process_id": "sub"}),
        ],
        connections=[{"id": "c1", "source": "orders", "source_port": "main", "target": "fan", "target_port": "main"}],
    )
    instance = await engine.run(definition)
    assert instance.status == RunStatus.SUCCEEDED
    result = run_of(instance, "fan").outputs["main"]
    assert result["count"] == 3 and result["failed"] == 0
    assert [r["output"]["echo"] for r in result["results"]] == ["a", "b", "c"]


async def test_for_each_continue_on_error_collects_failures():
    failing_sub = ProcessDefinition(id="boom", version=1,
                                    steps=[Step(id="f", plugin="always_fail")])
    engine = Engine(make_registry(AlwaysFailPlugin), definition_resolver={"boom": failing_sub}.get)
    definition = ProcessDefinition(
        steps=[Step(id="fan", plugin="for_each",
                    config={"mode": "process", "items": [1, 2], "process_id": "boom", "continue_on_error": True})],
    )
    instance = await engine.run(definition)
    assert instance.status == RunStatus.SUCCEEDED
    result = run_of(instance, "fan").outputs["main"]
    assert result["failed"] == 2 and result["succeeded"] == 0


# -- secrets and trigger validation --------------------------------------------------


async def test_secrets_resolve_in_config():
    engine = Engine(make_registry(), secrets={"api_key": "s3cr3t"})
    definition = ProcessDefinition(
        steps=[Step(id="set", plugin="transform", config={"values": {"key": "{{ secrets.api_key }}"}})],
    )
    instance = await engine.run(definition)
    assert run_of(instance, "set").outputs["main"] == {"key": "s3cr3t"}


def test_invalid_cron_and_webhook_path_flagged():
    definition = ProcessDefinition(
        steps=[Step(id="s", plugin="log")],
        triggers=[
            Trigger(type="schedule", cron="not a cron"),
            Trigger(type="webhook", path="bad path!"),
        ],
    )
    issues = validate(definition, make_registry())
    assert any("invalid cron" in issue for issue in issues)
    assert any("webhook path" in issue for issue in issues)


def test_validate_detailed_carries_step_id():
    definition = ProcessDefinition(steps=[Step(id="ghost", plugin="nope")])
    detailed = validate_detailed(definition, make_registry())
    assert any(entry.get("step_id") == "ghost" for entry in detailed)
