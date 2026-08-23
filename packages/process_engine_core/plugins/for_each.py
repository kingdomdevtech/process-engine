"""Iterate over a collection by running a published sub-process per item.

This is the Camunda multi-instance / AWS Step Functions "Map state" pattern:
the graph stays acyclic, and iteration happens by fanning out a sub-process.
Each item's sub-process receives ``{"item": <item>, "index": <i>}`` as its
trigger input; reference them inside the sub-process as
``{{ trigger.item }}`` / ``{{ trigger.index }}``.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..plugin import PluginManifest, PluginSpec
from ..ui import ui, when


class ForEachConfig(BaseModel):
    mode: Literal["next_step", "process"] = Field(
        default="next_step",
        title="How to iterate",
        description="Default: hand each item to the next step in the graph. Switch to 'process' to run a published sub-process once per item.",
        json_schema_extra=ui(),
    )
    items: Any = Field(
        default=None,
        title="List to work through",
        description="Usually auto-detected from the previous step. Leave empty to use the upstream list "
        "that arrived on this input.",
        examples=["{{ steps.fetch.output.rows }}"],
        json_schema_extra=ui(advanced=True, placeholder="auto-detect from previous step"),
    )
    process_id: str | None = Field(
        default=None,
        title="Published process to run for each one",
        description="Used only in 'process' mode. Inside it, the item is {{ trigger.item }} and its position "
        "in the list is {{ trigger.index }}.",
        json_schema_extra=ui(show_if=when("mode", "process")),
    )
    parallel: int = Field(
        default=1,
        ge=1,
        le=16,
        title="Run at the same time",
        description="Only used in 'process' mode. 1 works through the list one at a time.",
        json_schema_extra=ui(advanced=True, unit="at once"),
    )
    continue_on_error: bool = Field(
        default=False,
        title="Carry on when an item fails",
        description="Off: the first failure stops this step. On: every item is attempted and the "
        "output reports how many failed.",
        json_schema_extra=ui(advanced=True),
    )


class ForEachSpec(PluginSpec):
    manifest = PluginManifest(
        key="for_each",
        name="For Each",
        description="Run a published sub-process once per item of a collection.",
        category="flow",
    )
    Config = ForEachConfig
