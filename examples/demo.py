"""Run a process end-to-end without the API — the fastest way to see the engine work.

    python examples/demo.py
"""

import asyncio
import logging

from process_engine.engine import Engine
from process_engine.models import Connection, ProcessDefinition, Step
from process_engine.registry import PluginRegistry


async def main() -> None:
    registry = PluginRegistry()
    registry.load_builtins()

    definition = ProcessDefinition(
        name="Order triage",
        steps=[
            Step(
                id="enrich",
                name="enrich",
                plugin="transform",
                config={"values": {"total": "{{ trigger.total }}", "customer": "{{ trigger.customer }}"}},
            ),
            Step(
                id="check",
                name="check",
                plugin="condition",
                config={"left": "{{ steps.enrich.output.total }}", "operator": "greater_than", "right": 100},
            ),
            Step(
                id="big",
                name="big",
                plugin="log",
                config={"message": "Big order from {{ steps.enrich.output.customer }}: {{ steps.enrich.output.total }}"},
            ),
            Step(id="small", name="small", plugin="log", config={"message": "Small order"}),
        ],
        connections=[
            Connection(source="enrich", target="check"),
            Connection(source="check", source_port="true", target="big"),
            Connection(source="check", source_port="false", target="small"),
        ],
    )

    instance = await Engine(registry).run(definition, trigger_input={"total": 250, "customer": "ACME"})
    print(f"run {instance.id}: {instance.status}")
    for step_run in instance.step_runs:
        took = f"{step_run.duration_ms:.1f}ms" if step_run.duration_ms is not None else "-"
        print(f"  {step_run.step_name:<8} {step_run.status:<10} {took:>7} -> {step_run.outputs}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
