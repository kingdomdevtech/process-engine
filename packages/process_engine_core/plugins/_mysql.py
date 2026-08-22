"""Connection settings shared by the MySQL plugins — the form half.

Opening a connection is ``process_engine.plugins._mysql``, on the engine hosts.
Only the settings live here, because only they are needed to draw the step.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ..ui import ui, when

_FIELDS = when("connect_using", "fields")
_URL = when("connect_using", "url")


class MySQLConnection(BaseModel):
    """Connection settings shared by the MySQL plugins.

    Prefer secrets for credentials: "password": "{{ secrets.mysql_password }}".

    ``url`` used to silently override the individual fields whenever it was
    non-empty, which is invisible in a form where both are on screen. The
    choice is now explicit; a definition that only sets ``url`` still selects
    the URL mode through the before-validator.
    """

    connect_using: Literal["fields", "url"] = Field(
        default="fields",
        title="Connect using",
        json_schema_extra=ui(
            group="Database",
            labels={"fields": "Server details", "url": "A connection string"},
        ),
    )
    url: str = Field(
        default="",
        title="Connection string",
        description="Full SQLAlchemy URL, mysql+pymysql://user:password@host:3306/database",
        examples=["mysql+pymysql://reports:secret@127.0.0.1:3306/orders"],
        json_schema_extra=ui(group="Database", show_if=_URL),
    )
    host: str = Field(
        default="127.0.0.1",
        title="Server",
        description="Host name or IP address of the MySQL server.",
        json_schema_extra=ui(group="Database", show_if=_FIELDS),
    )
    port: int = Field(
        default=3306,
        title="Port",
        json_schema_extra=ui(group="Database", show_if=_FIELDS),
    )
    database: str = Field(
        default="",
        title="Database",
        examples=["orders"],
        json_schema_extra=ui(group="Database", show_if=_FIELDS),
    )
    username: str = Field(
        default="",
        title="Username",
        examples=["process_engine"],
        json_schema_extra=ui(group="Database", show_if=_FIELDS),
    )
    password: str = Field(
        default="",
        title="Password",
        examples=["{{ secrets.mysql_password }}"],
        json_schema_extra=ui(group="Database", show_if=_FIELDS, widget="password", secret=True),
    )
    timeout_seconds: float = Field(
        default=30,
        ge=1,
        title="Connection timeout",
        description="Give up if the server has not accepted the connection within this long.",
        json_schema_extra=ui(group="Database", advanced=True, unit="seconds"),
    )

    @model_validator(mode="before")
    @classmethod
    def _infer_connect_using(cls, value: Any) -> Any:
        """A definition written before the mode existed said "url" by filling it in."""
        if isinstance(value, dict) and "connect_using" not in value and value.get("url"):
            return {**value, "connect_using": "url"}
        return value

    @model_validator(mode="after")
    def _connection_complete(self) -> "MySQLConnection":
        if self.connect_using == "url" and not self.url:
            raise ValueError("Connection string is required, or switch “Connect using” to server details")
        return self
