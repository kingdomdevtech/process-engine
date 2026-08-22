"""Presentation hints for plugin config fields.

The designer builds every step form from ``Config.model_json_schema()`` and
ships no per-plugin frontend code, so anything a plugin wants to say about
*how* a field should be edited has to travel inside the schema. These helpers
write a single ``x-ui`` object per field — its own namespace, so it can never
collide with a JSON Schema keyword and pydantic's validator ignores it.

Nothing here is required. An unannotated field still renders: the designer
picks a widget from the JSON Schema type, so ``list[str]`` is a tag editor and
``dict[str, str]`` a key/value editor whether or not anyone said so. Annotate
to improve the wording, group related fields, or fold expert knobs away behind
"Advanced".

    class Config(BaseModel):
        host: str = Field(
            title="Mail server",
            description="The address your email provider gave you.",
            json_schema_extra=ui(group="Mail server", placeholder="smtp.office365.com"),
        )

The recognised widgets are listed in :data:`WIDGETS`; all are optional, since
the type usually implies the right one. ``ui()`` rejects a name outside that
set as the plugin is imported, because the designer would otherwise fall back
to the raw JSON editor without saying why.
"""

from __future__ import annotations

from typing import Any

__all__ = ["WIDGETS", "ui", "when"]

#: Every widget the designer knows how to draw. A name outside this set would
#: fall back to the raw JSON editor without saying why, so ``ui()`` rejects it
#: as the plugin module is imported rather than at the moment someone opens the
#: form.
WIDGETS = frozenset(
    {
        "tags",  # list of anything, one chip per entry
        "emails",  # tags, checked as email addresses
        "files",  # tags, presented as file paths
        "keyvalue",  # dict, a name/value row per entry
        "email",  # a single address
        "password",  # masked, with the stored-secret picker
        "color",
        "sql",
        "textarea",
        "path",
        "html",
        "json",  # the raw editor — how to opt back out of an inferred widget
    }
)


def ui(
    *,
    group: str | None = None,
    advanced: bool = False,
    widget: str | None = None,
    placeholder: str | None = None,
    secret: bool = False,
    labels: dict[str, str] | None = None,
    show_if: dict[str, Any] | None = None,
    unit: str | None = None,
    add_label: str | None = None,
    key_label: str | None = None,
    value_label: str | None = None,
) -> dict[str, Any]:
    """Build the ``json_schema_extra`` payload describing how to edit a field.

    ``group``      section heading; fields sharing one are rendered together
    ``advanced``   tuck the field into the group's collapsed "Advanced" area
    ``widget``     override the widget implied by the type (see module docs)
    ``placeholder``ghost text shown while the field is empty
    ``secret``     offer the stored-secret picker beside the input
    ``labels``     human wording per enum value, ``{"not_equals": "is not"}``
    ``show_if``    visibility condition — build it with :func:`when`
    ``unit``       suffix rendered inside the control, e.g. ``"seconds"``
    ``add_label``  wording of a tag/key-value editor's add button
    ``key_label``  / ``value_label``  column headings of a key/value editor
    """
    if widget is not None and widget not in WIDGETS:
        raise ValueError(f"unknown widget {widget!r}; expected one of {', '.join(sorted(WIDGETS))}")
    hints: dict[str, Any] = {
        "group": group,
        "advanced": advanced or None,
        "widget": widget,
        "placeholder": placeholder,
        "secret": secret or None,
        "labels": labels,
        "showIf": show_if,
        "unit": unit,
        "addLabel": add_label,
        "keyLabel": key_label,
        "valueLabel": value_label,
    }
    return {"x-ui": {key: value for key, value in hints.items() if value is not None}}


def when(field: str, *values: Any) -> dict[str, Any]:
    """Show a field only while ``field`` holds one of ``values``.

    Used for the modal configs — an HTTP step's client id matters only under
    OAuth2, and asking for it the rest of the time is just noise::

        auth_client_id: str = Field(default="", json_schema_extra=ui(show_if=when("auth", "oauth2")))

    The condition is evaluated against the step's own config in the designer.
    It is presentation only: a hidden field keeps whatever value it holds, and
    the plugin still has to validate what it actually needs.
    """
    return {"field": field, "in": list(values)}
