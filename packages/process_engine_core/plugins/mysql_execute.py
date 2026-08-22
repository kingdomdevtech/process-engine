"""Execute a MySQL statement or stored procedure — the form half.

``action`` picks between the two, so both sets of fields can never half-apply:

* ``statement``: any DML/DDL with ":name" bound parameters, run in a
  transaction (committed on success, rolled back on error).
* ``procedure`` + ``args``: CALL a stored procedure; every result set it
  produces is captured.

Reminder: the engine's retry policy re-runs failed steps — make statements
idempotent or leave ``max_attempts`` at 1 for non-idempotent writes.
"""

from typing import Any, Literal

from pydantic import Field, model_validator

from ..plugin import PluginManifest, PluginSpec
from ..ui import ui, when
from ._mysql import MySQLConnection


class MySQLExecuteConfig(MySQLConnection):
    action: Literal["statement", "procedure"] = Field(
        default="statement",
        title="Run",
        json_schema_extra=ui(
            group="Statement",
            labels={"statement": "A SQL statement", "procedure": "A stored procedure"},
        ),
    )
    statement: str = Field(
        default="",
        title="Statement",
        description="The SQL to run. Write :name where a value goes, and fill it in below.",
        examples=["UPDATE orders SET status = :status WHERE id = :id"],
        json_schema_extra=ui(group="Statement", widget="sql", show_if=when("action", "statement")),
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        title="Values",
        description="One entry per :name in the statement.",
        examples=[{"status": "shipped", "id": "{{ trigger.id }}"}],
        json_schema_extra=ui(
            group="Statement",
            widget="keyvalue",
            key_label="Name",
            add_label="Add value",
            show_if=when("action", "statement"),
        ),
    )
    procedure: str = Field(
        default="",
        title="Procedure name",
        examples=["rebuild_report"],
        json_schema_extra=ui(group="Statement", show_if=when("action", "procedure")),
    )
    args: list[Any] = Field(
        default_factory=list,
        title="Arguments",
        description="In the order the procedure declares them.",
        examples=[["{{ trigger.id }}"]],
        json_schema_extra=ui(
            group="Statement", widget="tags", add_label="Add argument", show_if=when("action", "procedure")
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _infer_action(cls, value: Any) -> Any:
        """Before the mode existed, an empty statement plus a procedure name meant CALL."""
        if isinstance(value, dict) and "action" not in value and value.get("procedure") and not value.get("statement"):
            return {**value, "action": "procedure"}
        return value

    @model_validator(mode="after")
    def _target_present(self) -> "MySQLExecuteConfig":
        if self.action == "statement" and not self.statement:
            raise ValueError("Statement is required")
        if self.action == "procedure" and not self.procedure:
            raise ValueError("Procedure name is required")
        return self


class MySQLExecuteSpec(PluginSpec):
    manifest = PluginManifest(
        key="mysql_execute",
        name="MySQL Execute",
        description="Run a statement or stored procedure against MySQL.",
        category="database",
    )
    Config = MySQLExecuteConfig
