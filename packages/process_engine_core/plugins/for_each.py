"""Iterate over a collection by running a published sub-process per item.

This is the Camunda multi-instance / AWS Step Functions "Map state" pattern:
the graph stays acyclic, and iteration happens by fanning out a sub-process.
Each item's sub-process receives ``{"item": <item>, "index": <i>}`` as its
trigger input; reference them inside the sub-process as
``{{ trigger.item }}`` / ``{{ trigger.index }}``.
"""

from typing import Any

from pydantic import BaseModel, Field

from ..plugin import PluginManifest, PluginSpec
from ..ui import ui


class ForEachConfig(BaseModel):
    items: Any = Field(
        default=None,
        title="List to work through",
        description="Must be a list — usually rows from an earlier step. Leave empty to use whatever "
        "the previous step passed in.",
        examples=["{{ steps.fetch.output.rows }}"],
        json_schema_extra=ui(),
    )
    process_id: str = Field(
        title="Process to run for each one",
        description="Must be published. Inside it, the item is {{ trigger.item }} and its position "
        "in the list is {{ trigger.index }}.",
        json_schema_extra=ui(),
    )
    parallel: int = Field(
        default=1,
        ge=1,
        le=16,
        title="Run at the same time",
        description="1 works through the list one at a time. Raise it to go faster, as long as "
        "whatever the sub-process touches can cope.",
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
