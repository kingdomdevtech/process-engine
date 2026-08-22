"""Process Engine: the half that executes.

This distribution runs definitions — the engine itself, the plugin
implementations (and so the SDKs, drivers and COM libraries they need), the
queue worker and the scheduler. It is what you install on an engine host:
``python -m process_engine`` claims queued jobs and fires due schedules, and
serves no HTTP at all.

Everything a definition *is* — the documents, the storage, the plugin manifests
and their config schemas — comes from ``process_engine_core``, which the
designer's API installs on its own. Import the shared vocabulary from there;
this package's own surface is the executor.
"""

from .engine import DefinitionError, Engine, RunControl, validate
from .registry import PluginError, PluginRegistry, default_registry

__version__ = "0.1.0"

__all__ = [
    "DefinitionError",
    "Engine",
    "PluginError",
    "PluginRegistry",
    "RunControl",
    "default_registry",
    "validate",
]
