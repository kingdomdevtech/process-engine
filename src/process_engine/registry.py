"""Plugin registry and discovery.

Three ways a Plugin reaches the engine, cheapest first:

1. **Drop-in file** — put a ``.py`` file defining a Plugin subclass into the
   drop-in folder (``./plugins`` by default, override with the
   ``PROCESS_ENGINE_PLUGINS_DIR`` environment variable). No packaging, no
   install; it is discovered at startup.

2. **Entry point** — ship the Plugin as a pip package advertising it in the
   ``process_engine.plugins`` entry-point group (the standard Python plugin
   mechanism, the same one pytest and Airflow use)::

       [project.entry-points."process_engine.plugins"]
       hello = "hello_plugin:HelloPlugin"

   See ``examples/hello-plugin/`` for a complete package.

3. **Built-in** — added to ``process_engine/plugins/`` inside this package.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import sys
from importlib import import_module
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Iterator

from .plugin import Plugin

ENTRY_POINT_GROUP = "process_engine.plugins"
PLUGINS_DIR_ENV = "PROCESS_ENGINE_PLUGINS_DIR"
DEFAULT_PLUGINS_DIR = "plugins"


class PluginError(Exception):
    pass


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, type[Plugin]] = {}
        self._aliases: dict[str, str] = {}  # retired key -> current key

    def register(self, plugin_cls: type[Plugin]) -> type[Plugin]:
        """Register a Plugin class; usable as a class decorator."""
        manifest = getattr(plugin_cls, "manifest", None)
        if manifest is None:
            raise PluginError(f"{plugin_cls.__name__} defines no manifest")
        existing = self._plugins.get(manifest.key)
        if existing is not None and existing is not plugin_cls:
            raise PluginError(f"duplicate plugin key {manifest.key!r} ({existing.__name__} vs {plugin_cls.__name__})")
        self._plugins[manifest.key] = plugin_cls
        for alias in getattr(manifest, "aliases", []):
            self._aliases[alias] = manifest.key
        return plugin_cls

    def get(self, key: str) -> type[Plugin]:
        plugin_cls = self._plugins.get(key) or self._plugins.get(self._aliases.get(key, ""))
        if plugin_cls is None:
            raise PluginError(f"no plugin registered under key {key!r}")
        return plugin_cls

    def __contains__(self, key: str) -> bool:
        return key in self._plugins or key in self._aliases

    def __iter__(self) -> Iterator[type[Plugin]]:
        return iter(self._plugins.values())

    def __len__(self) -> int:
        return len(self._plugins)

    def manifests(self) -> list[dict[str, Any]]:
        """Manifest plus config JSON Schema per Plugin — what the designer's
        palette and config forms are generated from."""
        return [
            {**cls.manifest.model_dump(), "config_schema": cls.config_json_schema()}
            for cls in sorted(self._plugins.values(), key=lambda cls: cls.manifest.key)
        ]

    # -- discovery -----------------------------------------------------------

    def load_builtins(self) -> None:
        module = import_module("process_engine.plugins")
        for plugin_cls in module.BUILTIN_PLUGINS:
            self.register(plugin_cls)

    def load_entry_points(self) -> None:
        for entry_point in entry_points(group=ENTRY_POINT_GROUP):
            self.register(entry_point.load())

    def load_directory(self, path: str | Path) -> list[type[Plugin]]:
        """Discover Plugins from loose ``.py`` files — the zero-packaging path.

        Every concrete Plugin subclass defined in a top-level ``.py`` file in
        the folder is registered. Files starting with ``_`` are skipped.
        """
        folder = Path(path)
        if not folder.is_dir():
            return []
        loaded: list[type[Plugin]] = []
        for file in sorted(folder.glob("*.py")):
            if file.name.startswith("_"):
                continue
            module_name = f"process_engine_dropin_{file.stem}"
            spec = importlib.util.spec_from_file_location(module_name, file)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, Plugin)
                    and obj.__module__ == module_name
                    and not inspect.isabstract(obj)
                ):
                    loaded.append(self.register(obj))
        return loaded


def default_registry(plugins_dir: str | Path | None = None) -> PluginRegistry:
    """Registry with built-ins, entry-point packages, and drop-in files loaded."""
    registry = PluginRegistry()
    registry.load_builtins()
    registry.load_entry_points()
    registry.load_directory(plugins_dir or os.environ.get(PLUGINS_DIR_ENV, DEFAULT_PLUGINS_DIR))
    return registry
