"""The Plugin contract — the extensibility seam of the engine.

A Plugin is one pluggable step implementation. It declares:

* ``manifest``  — identity, category and input/output ports (what the
  designer's palette shows)
* ``Config``    — a pydantic model for its settings; the designer renders a
  form from its JSON Schema and the engine validates step config against it
* ``execute()`` — the runtime behaviour

Ship Plugins either inside this package (see ``process_engine/plugins/``) or
as a separate pip package exposing an entry point in the
``process_engine.plugins`` group (see ``examples/hello-plugin/``).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel

MAIN_PORT = "main"
ERROR_PORT = "error"


class Port(BaseModel):
    name: str
    description: str = ""


class PluginManifest(BaseModel):
    key: str  # unique registry key, e.g. "http_request"
    name: str
    description: str = ""
    category: str = "general"
    version: str = "1.0.0"
    icon: str = ""
    inputs: list[Port] = [Port(name=MAIN_PORT)]
    outputs: list[Port] = [Port(name=MAIN_PORT)]
    aliases: list[str] = []  # retired keys that still resolve here (renames stay backward compatible)


class EmptyConfig(BaseModel):
    pass


@dataclass
class PluginContext:
    """Everything a Plugin sees at execution time."""

    run_id: str
    step_id: str
    step_name: str
    config: BaseModel  # validated instance of the Plugin's Config model
    input: Any  # single upstream payload, or {port: [payloads]} at a join
    all_inputs: dict[str, list[Any]]  # every delivered payload, grouped by input port
    variables: dict[str, Any]
    logger: logging.Logger
    # awaitable (process_id, trigger_input) -> {run_id, status, output, error};
    # injected by the engine so plugins like for_each can run sub-processes
    run_subprocess: Any = None


@dataclass
class PluginResult:
    """Data emitted on output ports.

    Downstream steps connected to ports that emitted nothing do not run —
    that is how branching works.
    """

    outputs: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def main(cls, data: Any) -> "PluginResult":
        return cls(outputs={MAIN_PORT: data})

    @classmethod
    def on(cls, port: str, data: Any) -> "PluginResult":
        return cls(outputs={port: data})


class Plugin(ABC):
    manifest: ClassVar[PluginManifest]
    Config: ClassVar[type[BaseModel]] = EmptyConfig

    @abstractmethod
    async def execute(self, ctx: PluginContext) -> PluginResult | dict[str, Any] | None:
        """Run the step.

        Return a PluginResult, a plain value (emitted on "main"), or None.
        Raise to signal failure — the engine applies the step's retry policy
        and error routing.
        """

    @classmethod
    def config_json_schema(cls) -> dict[str, Any]:
        return cls.Config.model_json_schema()
