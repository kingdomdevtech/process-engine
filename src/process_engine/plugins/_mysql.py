"""Shared helpers for the MySQL plugins."""

from __future__ import annotations

import base64
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

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


def open_engine(cfg: MySQLConnection) -> Engine:
    if cfg.connect_using == "url":
        url: str | URL = cfg.url
    else:
        url = URL.create(
            "mysql+pymysql",
            username=cfg.username or None,
            password=cfg.password or None,
            host=cfg.host,
            port=cfg.port,
            database=cfg.database or None,
        )
    try:
        return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": cfg.timeout_seconds})
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "the MySQL driver is not installed: pip install process-engine[mysql]"
        ) from exc


def jsonable(value: Any) -> Any:
    """Convert DB values to JSON-safe types for the run record."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(bytes(value)).decode("ascii")
    return str(value)
