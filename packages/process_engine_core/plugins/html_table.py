"""Render rows as an HTML table — the form half.

``TableColumn`` is part of the settings, not the renderer: the designer builds a
column editor from it. Rendering lives on the engine hosts.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ..plugin import PluginManifest, PluginSpec
from ..ui import ui


class TableColumn(BaseModel):
    key: str  # row key, dotted path ("customer.name"), or 0-based index into list rows
    label: str = ""  # header text; defaults to the key, title-cased
    align: Literal["auto", "left", "center", "right"] = "auto"  # auto right-aligns numeric columns

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_key(cls, value: Any) -> Any:
        return {"key": value} if isinstance(value, str) else value


class HtmlTableConfig(BaseModel):
    rows: Any = Field(
        default=None,
        title="Rows",
        description="Where the rows come from. Leave empty to use whatever the previous step passed in.",
        examples=["{{ steps.query.output.rows }}"],
        json_schema_extra=ui(group="Data"),
    )
    columns: list[TableColumn] = Field(
        default_factory=list,
        title="Columns",
        description="Name the columns to show, in the order you want them. Leave empty to show everything. "
        "Switch to the JSON tab to also set a heading or alignment per column.",
        examples=[["id", {"key": "total", "label": "Total", "align": "right"}]],
        json_schema_extra=ui(group="Data", widget="tags", add_label="Add column"),
    )
    first_row_is_header: bool = Field(
        default=False,
        title="First row holds the headings",
        description="Only for rows that arrive as plain lists rather than named fields.",
        json_schema_extra=ui(group="Data", advanced=True),
    )
    max_rows: int = Field(
        default=500,
        ge=1,
        le=50_000,
        title="Row limit",
        description="Longer results are cut off, so an email never becomes enormous.",
        json_schema_extra=ui(group="Data", advanced=True, unit="rows"),
    )

    caption: str = Field(
        default="",
        title="Caption",
        description="Optional heading shown above the table.",
        examples=["Orders awaiting dispatch"],
        json_schema_extra=ui(group="Table"),
    )
    header: bool = Field(
        default=True,
        title="Show the heading row",
        json_schema_extra=ui(group="Table"),
    )
    empty_text: str = Field(
        default="No rows.",
        title="Text when there is nothing to show",
        json_schema_extra=ui(group="Table"),
    )
    null_text: str = Field(
        default="",
        title="Text for blank cells",
        description="Left empty, a missing value shows as an empty cell.",
        json_schema_extra=ui(group="Table", advanced=True),
    )

    theme: Literal["striped", "bordered", "minimal", "none"] = Field(
        default="striped",
        title="Style",
        json_schema_extra=ui(
            group="Appearance",
            labels={
                "striped": "Striped rows",
                "bordered": "Bordered",
                "minimal": "Minimal",
                "none": "Unstyled — my own stylesheet handles it",
            },
        ),
    )
    accent_color: str = Field(
        default="#1f2937",
        title="Accent colour",
        description="Fills the heading row; the minimal style uses it for the rule underneath.",
        json_schema_extra=ui(group="Appearance", widget="color"),
    )
    font_family: str = Field(
        default="Segoe UI, Arial, sans-serif",
        title="Font",
        description="Stick to fonts installed everywhere — email clients cannot download one.",
        json_schema_extra=ui(group="Appearance", advanced=True),
    )
    table_class: str = Field(
        default="",
        title="CSS class",
        description='Put on the <table> element. Pair it with the "Unstyled" style.',
        json_schema_extra=ui(group="Appearance", advanced=True),
    )


class HtmlTableSpec(PluginSpec):
    manifest = PluginManifest(
        key="html_table",
        name="HTML Table",
        description="Render rows as an HTML table, ready to drop into an email body.",
        category="data",
    )
    Config = HtmlTableConfig
