"""Plugin registry and discovery.

A registry maps plugin keys to classes. *Which* classes depends on which tier
built it, and that is the point:

* the designer's API builds one of :class:`~process_engine_core.plugin.PluginSpec`
  subclasses — manifest and Config, no behaviour — via :func:`spec_registry`.
  Enough to draw the palette, generate every form and validate a definition.
* an engine host builds one of runnable ``Plugin`` subclasses via
  ``process_engine.registry.default_registry``.

Both registries answer the same keys, because the runnable class *is* the spec
class with an ``execute`` added. So the palette can only ever offer a step some
engine is able to run, while the API physically holds nothing that runs.

Two ways a Plugin reaches the engine:

1. **Built-in** — a spec module in ``process_engine_core/plugins/`` and its
   implementation in ``process_engine/plugins/``, listed in ``BUILTIN_SPECS`` and
   ``BUILTIN_PLUGINS`` respectively. This is the path for a new plugin: it lives
   in the repository, is reviewed, tested and versioned with the engine, and
   ships to every host that runs it without anyone remembering to copy a file.

2. **Entry point** — ship the Plugin as a pip package advertising it in the
   ``process_engine.plugins`` entry-point group (the standard Python plugin
   mechanism, the same one pytest and Airflow use)::

       [project.entry-points."process_engine.plugins"]
       hello = "hello_plugin:HelloPlugin"

   See ``examples/hello-plugin/`` for a complete package. It subclasses
   ``Plugin`` from this distribution and carries its own ``execute``, so the one
   package installs on both tiers: the API reads its manifest for the palette and
   never calls it. For something owned by another team on its own release cycle;
   installing it is a deployment step on every host that executes *and* on the
   API host that must offer it, so prefer a built-in.

There is deliberately no drop-in folder. Loose ``.py`` files were convenient on
one machine and a liability on two: a step that runs on whichever host claims it
cannot depend on a file somebody dropped on one of them.

Discovery runs at startup only, on both tiers — adding a plugin means a restart
of the API (so it appears in the palette) and of each engine (so it can run).
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import entry_points
from typing import Any, Iterator

from .plugin import PluginSpec

ENTRY_POINT_GROUP = "process_engine.plugins"


class PluginError(Exception):
    pass


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, type[PluginSpec]] = {}
        self._aliases: dict[str, str] = {}  # retired key -> current key

    def register(self, plugin_cls: type[PluginSpec]) -> type[PluginSpec]:
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

    def get(self, key: str) -> type[PluginSpec]:
        plugin_cls = self._plugins.get(key) or self._plugins.get(self._aliases.get(key, ""))
        if plugin_cls is None:
            raise PluginError(f"no plugin registered under key {key!r}")
        return plugin_cls

    def __contains__(self, key: str) -> bool:
        return key in self._plugins or key in self._aliases

    def __iter__(self) -> Iterator[type[PluginSpec]]:
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

    def keys(self) -> list[str]:
        """The registered keys, retired aliases excluded — as ``manifests()`` is."""
        return sorted(self._plugins)

    def executable(self, key: str, *, require: bool = False) -> bool:
        """Whether this registry's entry for ``key`` can actually run.

        False on the designer's API, which holds specs: a manifest and a Config,
        no behaviour. Nothing there should be asking — but a mistake should say
        so rather than raise ``AttributeError`` halfway into a run, which is what
        ``require=True`` is for (the ``Engine`` checks its whole registry that
        way when it is built).
        """
        if callable(getattr(self._plugins.get(key), "execute", None)):
            return True
        if require:
            raise PluginError(
                f"plugin {key!r} cannot execute here: this registry holds specifications, "
                "not implementations — build it with default_registry() on a host that runs steps"
            )
        return False

    # -- discovery -----------------------------------------------------------

    def load_builtins(self, module_name: str, attribute: str) -> None:
        """Register the built-ins listed by ``module_name``.

        The module and list are arguments because the two tiers load different
        ones: specs on the API host, implementations on an engine host.
        """
        module = import_module(module_name)
        for plugin_cls in getattr(module, attribute):
            self.register(plugin_cls)

    def load_entry_points(self) -> None:
        for entry_point in entry_points(group=ENTRY_POINT_GROUP):
            self.register(entry_point.load())


def spec_registry() -> PluginRegistry:
    """Specs for every built-in, plus any entry-point package installed.

    What the designer's API runs on. An entry-point plugin subclasses ``Plugin``
    and so brings its own ``execute`` — harmless here, since nothing on this tier
    calls one; it is registered for its manifest, so the palette stays in step
    with what the engine hosts can run.
    """
    registry = PluginRegistry()
    registry.load_builtins("process_engine_core.plugins", "BUILTIN_SPECS")
    registry.load_entry_points()
    return registry
