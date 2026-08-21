import pytest
from pydantic import TypeAdapter

from process_engine.plugin import Plugin, PluginManifest, PluginResult
from process_engine.registry import PluginError, PluginRegistry


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
    registry = PluginRegistry()
    registry.load_builtins()
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
    registry = PluginRegistry()
    registry.load_builtins()
    checked = []
    for plugin_cls in registry:
        for name, field in plugin_cls.Config.model_fields.items():
            for example in field.examples or []:
                TypeAdapter(field.annotation).validate_python(example)  # raises on a bad example
                checked.append(f"{plugin_cls.manifest.key}.{name}")
    assert "http_request.url" in checked and "transform.values" in checked


def test_renamed_plugin_still_resolves_through_alias():
    registry = PluginRegistry()
    registry.load_builtins()
    # definitions saved before the SMTP/SES split referenced "send_email"
    assert "send_email" in registry
    assert registry.get("send_email") is registry.get("send_email_smtp")
    # the retired key is not advertised in the palette
    assert "send_email" not in {manifest["key"] for manifest in registry.manifests()}


def test_dropin_directory_discovery(tmp_path):
    (tmp_path / "shout.py").write_text(
        "from pydantic import BaseModel\n"
        "from process_engine.plugin import Plugin, PluginManifest, PluginResult\n"
        "\n"
        "class ShoutConfig(BaseModel):\n"
        "    text: str = ''\n"
        "\n"
        "class ShoutPlugin(Plugin):\n"
        "    manifest = PluginManifest(key='shout', name='Shout')\n"
        "    Config = ShoutConfig\n"
        "\n"
        "    async def execute(self, ctx):\n"
        "        return PluginResult.main({'text': ctx.config.text + '!'})\n",
        encoding="utf-8",
    )
    registry = PluginRegistry()
    loaded = registry.load_directory(tmp_path)
    assert [cls.manifest.key for cls in loaded] == ["shout"]
    assert "shout" in registry
