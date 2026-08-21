"""Process Engine: n8n-style workflow automation.

A Process is a graph of Steps; each Step is configured from a Plugin — the
pluggable unit of behaviour. The engine executes ProcessDefinitions and
records ProcessInstances.
"""

from .engine import DefinitionError, Engine, RunControl, validate, validate_detailed
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
    Port,
)
from .registry import PluginError, PluginRegistry, default_registry

__version__ = "0.1.0"

__all__ = [
    "Connection",
    "DefinitionError",
    "Engine",
    "ERROR_PORT",
    "MAIN_PORT",
    "Plugin",
    "PluginContext",
    "PluginError",
    "PluginManifest",
    "PluginRegistry",
    "PluginResult",
    "Port",
    "ProcessDefinition",
    "ProcessInstance",
    "ProcessStatus",
    "RetryPolicy",
    "RunControl",
    "RunStatus",
    "Step",
    "StepRun",
    "Trigger",
    "default_registry",
    "validate",
    "validate_detailed",
]
