import logging

import pytest

from process_engine.engine import Engine
from process_engine.models import Connection, ProcessDefinition, RunStatus, Step
from process_engine.plugin import PluginContext
from process_engine.plugins.html_table import HtmlTablePlugin
from process_engine.registry import PluginRegistry

ROWS = [
    {"id": 1, "customer": "Acme", "total": 120.5},
    {"id": 2, "customer": "Globex", "total": 80},
]


async def build(config=None, input_data=None) -> dict:
    ctx = PluginContext(
        run_id="r1",
        step_id="s1",
        step_name="table",
        config=HtmlTablePlugin.Config(**(config or {})),
        input=input_data,
        all_inputs={},
        variables={},
        logger=logging.getLogger("test"),
    )
    result = await HtmlTablePlugin().execute(ctx)
    return result.outputs["main"]


async def html_of(config=None, input_data=None) -> str:
    return (await build(config, input_data))["html"]


async def test_columns_derived_from_dict_rows():
    output = await build(input_data=ROWS)
    assert output["columns"] == ["Id", "Customer", "Total"]
    assert output["row_count"] == 2
    assert output["truncated"] is False
    assert "<th scope=\"col\"" in output["html"]
    assert "Acme" in output["html"] and "Globex" in output["html"]


async def test_unwraps_a_row_producing_envelope():
    # mysql_query emits {rows, count, truncated} — chaining needs no config
    output = await build(input_data={"rows": ROWS, "count": 2, "truncated": False})
    assert output["row_count"] == 2
    assert output["columns"] == ["Id", "Customer", "Total"]


async def test_explicit_columns_select_and_label():
    output = await build(
        {"columns": ["customer", {"key": "total", "label": "Amount", "align": "right"}]}, ROWS
    )
    assert output["columns"] == ["Customer", "Amount"]
    assert "<th" in output["html"] and "Id" not in output["html"]


async def test_numeric_columns_right_align_by_default():
    html = await html_of(input_data=ROWS)
    assert "text-align:right;\">120.5" in html
    assert "text-align:left;\">Acme" in html


async def test_values_are_escaped():
    html = await html_of(input_data=[{"name": "<script>alert(1)</script>"}])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


async def test_dotted_keys_and_missing_cells():
    rows = [{"customer": {"name": "Acme"}}, {"customer": {}}]
    output = await build({"columns": ["customer.name"], "null_text": "—"}, rows)
    assert output["columns"] == ["Customer Name"]
    assert "Acme" in output["html"]
    assert "—" in output["html"]


async def test_list_rows_with_first_row_as_header():
    rows = [["Region", "Units"], ["North", 10], ["South", 4]]
    output = await build({"first_row_is_header": True}, rows)
    assert output["columns"] == ["Region", "Units"]
    assert output["row_count"] == 2
    assert "North" in output["html"]


async def test_scalar_rows_render_a_single_column():
    output = await build(input_data=["alpha", "beta"])
    assert output["columns"] == ["Value"]
    assert output["row_count"] == 2


async def test_empty_rows_render_the_empty_text():
    html = await html_of({"empty_text": "Nothing today."}, [])
    assert html.startswith("<p") and html.endswith("Nothing today.</p>")
    assert "<table" not in html
    assert await html_of({"empty_text": ""}, []) == ""  # opt out of rendering anything


async def test_max_rows_truncates_and_reports():
    output = await build({"max_rows": 1}, ROWS)
    assert output["row_count"] == 1
    assert output["truncated"] is True


async def test_theme_none_emits_no_inline_styles():
    html = await html_of({"theme": "none", "table_class": "report"}, ROWS)
    assert "style=" not in html
    assert '<table border="0" cellspacing="0" cellpadding="0" class="report">' in html


async def test_caption_and_header_toggle():
    html = await html_of({"caption": "Q3 & Q4", "header": False}, ROWS)
    assert "Q3 &amp; Q4" in html
    assert "<thead>" not in html


async def test_non_list_rows_raise():
    with pytest.raises(ValueError, match="must resolve to a list"):
        await build(input_data="not rows")


async def test_runs_in_a_process_with_an_expression():
    definition = ProcessDefinition(
        steps=[
            Step(id="load", plugin="transform", config={"values": {"rows": "{{ trigger.rows }}"}}),
            Step(
                id="table",
                plugin="html_table",
                config={"rows": "{{ steps.load.output.rows }}", "columns": ["customer", "total"]},
            ),
        ],
        connections=[Connection(source="load", target="table")],
    )
    registry = PluginRegistry()
    registry.load_builtins()
    instance = await Engine(registry).run(definition, trigger_input={"rows": ROWS})

    assert instance.status == RunStatus.SUCCEEDED
    output = next(r for r in instance.step_runs if r.step_id == "table").outputs["main"]
    assert output["row_count"] == 2
    assert "Globex" in output["html"]
