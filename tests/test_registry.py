import inspect

import pytest
from pydantic import TypeAdapter

from process_engine.registry import PluginError, PluginRegistry, default_registry
from process_engine_core.plugin import Plugin, PluginManifest, PluginResult
from process_engine_core.registry import spec_registry


class DummyPlugin(Plugin):
    manifest = PluginManifest(key="dummy", name="Dummy")

    async def execute(self, ctx):
        return PluginResult.main({})


class ImposterPlugin(Plugin):
    manifest = PluginManifest(key="dummy", name="Imposter")

    async def execute(self, ctx):
        return PluginResult.main({})


def test_register_and_get():
    registry = PluginRegistry()
    registry.register(DummyPlugin)
    assert registry.get("dummy") is DummyPlugin
    assert "dummy" in registry


def test_duplicate_key_rejected():
    registry = PluginRegistry()
    registry.register(DummyPlugin)
    with pytest.raises(PluginError, match="duplicate"):
        registry.register(ImposterPlugin)


def test_unknown_key_raises():
    with pytest.raises(PluginError, match="no plugin"):
        PluginRegistry().get("ghost")


def test_builtins_expose_manifest_and_schema():
    registry = default_registry()
    manifests = {m["key"]: m for m in registry.manifests()}
    expected = {"http_request", "condition", "transform", "delay", "log", "excel_refresh",
                "send_email_smtp", "send_email_ses", "for_each", "mysql_query", "mysql_execute",
                "html_table"}
    assert expected <= set(manifests)
    assert "url" in manifests["http_request"]["config_schema"]["properties"]
    assert [p["name"] for p in manifests["condition"]["outputs"]] == ["true", "false"]
    assert "workbook_path" in manifests["excel_refresh"]["config_schema"]["properties"]
    assert "attachments" in manifests["send_email_smtp"]["config_schema"]["properties"]
    ses_properties = manifests["send_email_ses"]["config_schema"]["properties"]
    assert {"region", "sender", "body_html"} <= set(ses_properties)
    assert ses_properties["body_html"]["format"] == "html"


def test_declared_field_examples_are_valid_values():
    """The designer builds its "pre-configured JSON" out of these — a stale
    example would hand the user a config the plugin then rejects."""
    registry = default_registry()
    checked = []
    for plugin_cls in registry:
        for name, field in plugin_cls.Config.model_fields.items():
            for example in field.examples or []:
                TypeAdapter(field.annotation).validate_python(example)  # raises on a bad example
                checked.append(f"{plugin_cls.manifest.key}.{name}")
    assert "http_request.url" in checked and "transform.values" in checked


def test_renamed_plugin_still_resolves_through_alias():
    registry = default_registry()
    # definitions saved before the SMTP/SES split referenced "send_email"
    assert "send_email" in registry
    assert registry.get("send_email") is registry.get("send_email_smtp")
    # the retired key is not advertised in the palette
    assert "send_email" not in {manifest["key"] for manifest in registry.manifests()}


def test_a_new_plugin_only_needs_to_be_listed():
    """A built-in that is imported but missing from BUILTIN_PLUGINS is invisible:
    it does not reach the palette and no engine can run it."""
    from process_engine.plugins import BUILTIN_PLUGINS

    registry = default_registry()
    assert {cls.manifest.key for cls in BUILTIN_PLUGINS} <= {m["key"] for m in registry.manifests()}


# -- the two registries: same palette, one of them can execute ---------------------


def test_both_tiers_advertise_exactly_the_same_plugins():
    """The API builds its registry from specs, an engine from the real plugins.

    A key in one and not the other is the worst kind of bug in this split: a step
    the designer offers that no engine can run, or one an engine holds that never
    appears in the palette. So the two lists have to be identical, key for key —
    which they are because a spec and its plugin are one class hierarchy, not two
    hand-kept lists.
    """
    specs = {manifest["key"]: manifest for manifest in spec_registry().manifests()}
    plugins = {manifest["key"]: manifest for manifest in default_registry().manifests()}

    assert set(specs) == set(plugins)
    # and the same manifest, not merely the same names: the palette entry, the
    # ports the canvas draws and the config form all come off the spec half
    assert specs == plugins


def test_only_the_engine_registry_can_execute():
    """The built-ins the API tier loads carry no ``execute`` at all.

    This is the structural half of "nothing runs in the container": not a mode or
    a flag, but a registry of ``PluginSpec`` classes — manifest and Config, no
    behaviour. Asking one to run is a programming error, caught here.

    Only the built-ins: an entry-point plugin is another package, installed on
    whichever hosts need it, and it ships the real thing wherever it lands.
    """
    from process_engine_core.plugins import BUILTIN_SPECS

    specs, plugins = spec_registry(), default_registry()
    builtin_keys = {cls.manifest.key for cls in BUILTIN_SPECS}

    assert specs.executable("log") is False
    assert plugins.executable("log") is True
    assert not any(specs.executable(key) for key in builtin_keys)
    assert all(plugins.executable(key) for key in plugins.keys())

    with pytest.raises(PluginError, match="cannot execute"):
        specs.executable("log", require=True)


def test_an_engine_refuses_a_registry_that_cannot_run_anything():
    """Wiring an Engine to the API's registry is a mistake worth catching early.

    Otherwise the first step of somebody's run dies with an ``AttributeError``
    from inside the executor, which says nothing about what is actually wrong.
    """
    from process_engine.engine import Engine

    with pytest.raises(PluginError, match="cannot execute"):
        Engine(spec_registry())
    Engine(default_registry())  # the engine host's own registry is fine


def test_there_is_no_drop_in_folder():
    """Loose .py files were removed on purpose: a step runs on whichever host
    claims it, so it cannot depend on a file somebody dropped on one of them."""
    assert not hasattr(PluginRegistry, "load_directory")
    assert "plugins_dir" not in inspect.signature(default_registry).parameters
