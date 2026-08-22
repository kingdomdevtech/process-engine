"""The engine host's registry: the plugins that can actually run.

Same :class:`~process_engine_core.registry.PluginRegistry` the designer's API
builds — loaded from a different list. There it is ``BUILTIN_SPECS`` (manifest and
Config); here it is ``BUILTIN_PLUGINS``, the same classes with their ``execute``.
Every key answers in both, so the palette can only offer work some engine can do.
"""

from __future__ import annotations

from process_engine_core.registry import (
    ENTRY_POINT_GROUP,
    PluginError,
    PluginRegistry,
)

__all__ = ["ENTRY_POINT_GROUP", "PluginError", "PluginRegistry", "default_registry"]


def default_registry() -> PluginRegistry:
    """Runnable built-ins plus any entry-point packages installed on this host."""
    registry = PluginRegistry()
    registry.load_builtins("process_engine.plugins", "BUILTIN_PLUGINS")
    registry.load_entry_points()
    return registry
