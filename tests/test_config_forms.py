"""Guards on the configuration forms.

The designer generates every step form from ``Config.model_json_schema()`` and
ships no per-plugin code, so a stale presentation hint is invisible until
someone opens the panel and finds a control missing. These tests read the same
schema the designer does.

The migrations at the bottom matter just as much: the fields a form shows were
reshaped, and definitions saved against the old shape have to keep running.
"""

import pytest
from pydantic import ValidationError

from process_engine.plugins._mysql import MySQLConnection
from process_engine.plugins.mysql_execute import MySQLExecuteConfig
from process_engine.plugins.send_email import SendEmailConfig
from process_engine_core.registry import spec_registry
from process_engine_core.ui import WIDGETS, ui

LIST_WIDGETS = {"tags", "emails", "files"}


def schemas():
    registry = spec_registry()
    for plugin_cls in registry:
        yield plugin_cls.manifest.key, plugin_cls.Config.model_json_schema()


def hints_in(schema) -> list[tuple[str, dict, dict]]:
    return [(name, spec, spec.get("x-ui", {})) for name, spec in schema.get("properties", {}).items()]


# ---- presentation hints -------------------------------------------------------


def test_every_field_carries_a_label():
    for key, schema in schemas():
        for name, spec, _ in hints_in(schema):
            assert spec.get("title"), f"{key}.{name} has no title for the form to label it with"


def test_declared_widgets_are_ones_the_designer_draws():
    for key, schema in schemas():
        for name, _, hints in hints_in(schema):
            widget = hints.get("widget")
            assert widget is None or widget in WIDGETS, f"{key}.{name} asks for unknown widget {widget!r}"


def test_widgets_match_the_shape_of_the_field():
    """A chip editor over a dict (or a name/value editor over a list) would
    silently fall back to raw JSON in the form."""
    for key, schema in schemas():
        for name, spec, hints in hints_in(schema):
            widget = hints.get("widget")
            if widget in LIST_WIDGETS:
                assert spec.get("type") == "array", f"{key}.{name} is {spec.get('type')}, not a list"
            elif widget == "keyvalue":
                assert spec.get("type") == "object", f"{key}.{name} is {spec.get('type')}, not a mapping"


def test_conditional_fields_point_at_a_real_field():
    for key, schema in schemas():
        properties = schema.get("properties", {})
        for name, _, hints in hints_in(schema):
            rule = hints.get("showIf")
            if not rule:
                continue
            target = rule["field"]
            assert target in properties, f"{key}.{name} is shown by {target!r}, which does not exist"
            allowed = properties[target].get("enum")
            if allowed:
                unknown = set(rule["in"]) - set(allowed)
                assert not unknown, f"{key}.{name} waits for {unknown}, which {target} can never hold"


def test_enum_wording_covers_only_real_options():
    """A renamed option would otherwise leave its old label behind, and the
    dropdown would quietly show the raw value again."""
    for key, schema in schemas():
        for name, spec, hints in hints_in(schema):
            labels = hints.get("labels")
            if not labels:
                continue
            options = set(spec.get("enum") or [])
            assert options, f"{key}.{name} has wording but no options"
            assert set(labels) <= options, f"{key}.{name} labels {set(labels) - options}, which it cannot hold"


def test_a_required_field_is_never_hidden_by_default():
    """Hiding something the plugin insists on leaves an unfixable validation
    error: the form reports it, and the field to fix it is not on screen."""
    for key, schema in schemas():
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            rule = properties.get(name, {}).get("x-ui", {}).get("showIf")
            if not rule:
                continue
            default = properties.get(rule["field"], {}).get("default")
            assert default in rule["in"], f"{key}.{name} is required but hidden until {rule['field']} changes"


def test_an_unknown_widget_is_rejected_where_it_is_written():
    with pytest.raises(ValueError, match="unknown widget"):
        ui(widget="slider")


# ---- migrations ---------------------------------------------------------------


@pytest.mark.parametrize(
    "saved, expected",
    [
        ({"use_tls": True, "use_ssl": False}, "starttls"),
        ({"use_tls": False, "use_ssl": True}, "ssl"),
        ({"use_tls": False, "use_ssl": False}, "none"),
        ({}, "starttls"),  # the old default
    ],
)
def test_smtp_encryption_replaces_the_two_booleans(saved, expected):
    config = SendEmailConfig(host="smtp.example.com", sender="a@example.com", to=["b@example.com"], **saved)
    assert config.encryption == expected


def test_smtp_legacy_html_flag_becomes_the_message_body():
    config = SendEmailConfig(
        host="smtp.example.com",
        sender="a@example.com",
        to=["b@example.com"],
        body="<p>Shipped</p>",
        html=True,
    )
    assert config.body_html == "<p>Shipped</p>"
    assert config.body == ""


def test_smtp_legacy_html_flag_defers_to_an_explicit_body_html():
    config = SendEmailConfig(
        host="smtp.example.com",
        sender="a@example.com",
        to=["b@example.com"],
        body="plain",
        body_html="<p>rich</p>",
        html=True,
    )
    assert config.body_html == "<p>rich</p>"
    assert config.body == "plain"


def test_mysql_connection_string_still_wins_when_it_is_the_only_thing_set():
    config = MySQLConnection(url="mysql+pymysql://u:p@db:3306/orders")
    assert config.connect_using == "url"


def test_mysql_defaults_to_the_individual_fields():
    assert MySQLConnection(host="db", database="orders").connect_using == "fields"


def test_mysql_url_mode_needs_a_connection_string():
    with pytest.raises(ValidationError, match="Connection string is required"):
        MySQLConnection(connect_using="url")


def test_mysql_execute_infers_the_procedure_mode():
    assert MySQLExecuteConfig(procedure="rebuild_report").action == "procedure"
    assert MySQLExecuteConfig(statement="DELETE FROM t").action == "statement"


def test_mysql_execute_still_insists_on_one_of_the_two():
    with pytest.raises(ValidationError, match="Statement is required"):
        MySQLExecuteConfig()
