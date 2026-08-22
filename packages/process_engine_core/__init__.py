"""Process Engine core: the vocabulary both tiers share.

A Process is a graph of Steps wired by Connections; each Step is configured from
a Plugin. This distribution holds everything that describes such a process and
nothing that runs one:

* the definition and run documents (``models``) and the database they live in
  (``storage``, ``jobs``, ``secrets_store``),
* the plugin contract as far as *identity and configuration* go
  (``plugin.PluginSpec``, ``registry``, ``ui``) — the palette and every step form
  are generated from these,
* what the two tiers otherwise have to agree on: ``validation``, ``security``,
  ``notifications``, ``urls``, ``workspace``.

Executing a definition is ``process_engine``; serving the designer is
``process_engine_api``. Both depend on this; it depends on neither. That is what
lets the designer's container be installed without a single line of plugin
behaviour in it, and an engine host run with no web stack at all.
"""

from .models import (
    Connection,
    ProcessDefinition,
    ProcessInstance,
    ProcessStatus,
    RetryPolicy,
    RunStatus,
    Step,
    StepRun,
    Trigger,
)
from .plugin import (
    ERROR_PORT,
    MAIN_PORT,
    Plugin,
    PluginContext,
    PluginManifest,
    PluginResult,
    PluginSpec,
    Port,
)
from .registry import PluginError, PluginRegistry, spec_registry
from .validation import DefinitionError, validate, validate_detailed

__version__ = "0.1.0"

__all__ = [
    "Connection",
    "DefinitionError",
    "ERROR_PORT",
    "MAIN_PORT",
    "Plugin",
    "PluginContext",
    "PluginError",
    "PluginManifest",
    "PluginRegistry",
    "PluginResult",
    "PluginSpec",
    "Port",
    "ProcessDefinition",
    "ProcessInstance",
    "ProcessStatus",
    "RetryPolicy",
    "RunStatus",
    "Step",
    "StepRun",
    "Trigger",
    "spec_registry",
    "validate",
    "validate_detailed",
]
