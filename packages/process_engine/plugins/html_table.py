"""Render a collection of rows as an HTML table.

The usual wiring is ``mysql_query`` (or ``http_request``) → ``html_table`` →
``send_email``, with the mail's ``body_html`` referencing
``{{ steps.<step>.output.html }}``.

Rows may be a list of dicts (the common case), a list of lists, a list of
scalars, or the whole envelope a row-producing step emits — ``{"rows": [...]}``
is unwrapped automatically, so chaining straight off ``mysql_query`` needs no
configuration at all.

Cell values are HTML-escaped: data cannot inject markup. Styling is written
inline because mail clients strip ``<style>`` blocks; pick the ``none`` theme
when a stylesheet does the styling instead.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from html import escape
from typing import Any

from process_engine_core.plugin import Plugin, PluginContext, PluginResult
from process_engine_core.plugins.html_table import HtmlTableConfig, HtmlTableSpec, TableColumn

_ROW_KEYS = ("rows", "items", "results", "records", "data")


class HtmlTablePlugin(HtmlTableSpec, Plugin):
    async def execute(self, ctx: PluginContext) -> PluginResult:
        cfg: HtmlTableConfig = ctx.config
        rows = _extract_rows(cfg.rows if cfg.rows is not None else ctx.input)
        truncated = len(rows) > cfg.max_rows
        rows = rows[: cfg.max_rows]

        columns = list(cfg.columns)
        if cfg.first_row_is_header and rows and isinstance(rows[0], (list, tuple)):
            header_row, rows = rows[0], rows[1:]
            if not columns:
                columns = [TableColumn(key=str(i), label=_text(v, "")) for i, v in enumerate(header_row)]
        if not columns:
            columns = _derive_columns(rows)

        return PluginResult.main(
            {
                "html": _render(cfg, rows, columns),
                "row_count": len(rows),
                "columns": [_label(column) for column in columns],
                "truncated": truncated,
            }
        )

def _extract_rows(source: Any) -> list[Any]:
    if source is None:
        return []
    if isinstance(source, (list, tuple)):
        return list(source)
    if isinstance(source, Mapping):
        for key in _ROW_KEYS:
            if isinstance(source.get(key), list):
                return source[key]
        return [source]  # a lone record renders as a one-row table
    raise ValueError(
        'html_table "rows" must resolve to a list of rows, e.g. "{{ steps.query.output.rows }}"'
    )


def _derive_columns(rows: list[Any]) -> list[TableColumn]:
    """Infer columns from the data: dict keys in first-seen order, else positions."""
    if not rows:
        return []
    if all(isinstance(row, Mapping) for row in rows):
        keys: dict[str, None] = {}
        for row in rows:
            keys.update(dict.fromkeys(key for key in row if isinstance(key, str)))
        return [TableColumn(key=key) for key in keys]
    width = max((len(row) for row in rows if isinstance(row, (list, tuple))), default=0)
    if width:
        return [TableColumn(key=str(i), label=f"Column {i + 1}") for i in range(width)]
    return [TableColumn(key="0", label="Value")]  # rows are scalars


def _cell(row: Any, key: str) -> Any:
    """Dotted-path lookup that yields None — not an error — for absent data."""
    if not isinstance(row, (Mapping, list, tuple)):
        return row  # a scalar row is its own single cell
    current: Any = row
    for part in key.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, (list, tuple)) and part.lstrip("-").isdigit():
            index = int(part)
            if not -len(current) <= index < len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _text(value: Any, null_text: str) -> str:
    if value is None:
        return null_text
    if isinstance(value, str):
        return value
    if isinstance(value, (Mapping, list, tuple)):
        return json.dumps(value, default=str, ensure_ascii=False)
    return str(value)


def _cell_html(value: Any, null_text: str) -> str:
    return escape(_text(value, null_text)).replace("\n", "<br>")


def _label(column: TableColumn) -> str:
    return column.label or column.key.replace("_", " ").replace(".", " ").strip().title()


def _alignment(column: TableColumn, values: list[Any]) -> str:
    if column.align != "auto":
        return column.align
    present = [value for value in values if value is not None]
    numeric = all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in present)
    return "right" if present and numeric else "left"


def _styles(cfg: HtmlTableConfig) -> dict[str, str]:
    """Inline style fragments per element; empty for the "none" theme."""
    if cfg.theme == "none":
        return {}
    accent = escape(cfg.accent_color, quote=True)
    table = f"border-collapse:collapse;width:100%;font-family:{escape(cfg.font_family, quote=True)};font-size:14px;color:#1f2937;"
    caption = "caption-side:top;text-align:left;font-weight:600;padding:0 0 8px;"
    if cfg.theme == "minimal":
        return {
            "table": table,
            "caption": caption,
            "th": f"padding:8px 10px;font-weight:600;border-bottom:2px solid {accent};white-space:nowrap;",
            "td": "padding:8px 10px;border-bottom:1px solid #eceff3;",
        }
    if cfg.theme == "bordered":
        border = "1px solid #d5dae1"
        return {
            "table": f"{table}border:{border};",
            "caption": caption,
            "th": f"padding:8px 10px;font-weight:600;background:{accent};color:#ffffff;border:{border};white-space:nowrap;",
            "td": f"padding:8px 10px;border:{border};",
        }
    return {  # striped
        "table": table,
        "caption": caption,
        "th": f"padding:8px 10px;font-weight:600;background:{accent};color:#ffffff;white-space:nowrap;",
        "td": "padding:8px 10px;border-bottom:1px solid #e4e8ee;",
        "stripe": "background:#f6f8fa;",
    }


def _attr(name: str, value: str) -> str:
    return f' {name}="{value}"' if value else ""


def _render(cfg: HtmlTableConfig, rows: list[Any], columns: list[TableColumn]) -> str:
    style = _styles(cfg)
    if not rows or not columns:
        if not cfg.empty_text:
            return ""
        muted = "font-family:Segoe UI, Arial, sans-serif;font-size:14px;color:#6b7280;" if style else ""
        return f"<p{_attr('style', muted)}>{escape(cfg.empty_text)}</p>"

    cells = [[_cell(row, column.key) for column in columns] for row in rows]
    aligns = [_alignment(column, [row[i] for row in cells]) for i, column in enumerate(columns)]

    out = [
        f'<table border="0" cellspacing="0" cellpadding="0"'
        f'{_attr("class", escape(cfg.table_class, quote=True))}{_attr("style", style.get("table", ""))}>'
    ]
    if cfg.caption:
        out.append(f'<caption{_attr("style", style.get("caption", ""))}>{escape(cfg.caption)}</caption>')
    if cfg.header:
        out.append("<thead><tr>")
        for column, align in zip(columns, aligns):
            th = f'{style["th"]}text-align:{align};' if style else ""
            out.append(f'<th scope="col"{_attr("style", th)}>{escape(_label(column))}</th>')
        out.append("</tr></thead>")
    out.append("<tbody>")
    for index, row in enumerate(cells):
        stripe = style.get("stripe", "") if index % 2 else ""
        out.append(f'<tr{_attr("style", stripe)}>')
        for value, align in zip(row, aligns):
            td = f'{style["td"]}text-align:{align};' if style else ""
            out.append(f'<td{_attr("style", td)}>{_cell_html(value, cfg.null_text)}</td>')
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)
