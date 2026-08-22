"""The Plugin contract — the extensibility seam, split along the deployment seam.

A Plugin is one pluggable step implementation, and it has always declared three
things. Two of them are *what the step is*, and the designer cannot draw a canvas
without them:

* ``manifest``  — identity, category and input/output ports (what the palette shows)
* ``Config``    — a pydantic model for its settings; the designer renders a form
  from its JSON Schema and the engine validates step config against it

The third is *what the step does*: ``execute()``. Only an engine host ever calls
it, and on the deployed shape that host is a different machine — so the two live
in different distributions:

* :class:`PluginSpec` (here, in ``process-engine-core``) carries the manifest and
  the Config. The designer's API installs only this, so it can offer a step and
  validate one without holding the code that performs it.
* :class:`Plugin` adds the abstract ``execute``, and the built-in implementations
  live in ``process-engine`` — installed on the engine hosts.

That is why the API cannot execute a step by accident rather than by policy: what
it holds has no ``execute`` to call. A plugin of your own subclasses ``Plugin``
and needs nothing but this package; ship it inside ``process_engine/plugins/`` or
as a pip package exposing an entry point in the ``process_engine.plugins`` group
(see ``examples/hello-plugin/``).
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


class PluginSpec:
    """What a step *is*: identity, ports, and the shape of its settings.

    Everything the designer needs and nothing that runs. A registry of these is
    enough to draw the palette, generate every config form and validate a
    definition — which is the whole job of the host that serves the designer.
    """

    manifest: ClassVar[PluginManifest]
    Config: ClassVar[type[BaseModel]] = EmptyConfig

    @classmethod
    def config_json_schema(cls) -> dict[str, Any]:
        return cls.Config.model_json_schema()


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


class Plugin(PluginSpec, ABC):
    """A step that can actually run. Implementations live on engine hosts."""

    @abstractmethod
    async def execute(self, ctx: PluginContext) -> PluginResult | dict[str, Any] | None:
        """Run the step.

        Return a PluginResult, a plain value (emitted on "main"), or None.
        Raise to signal failure — the engine applies the step's retry policy
        and error routing.
        """
