"""Shared helpers for the MySQL plugins — the half that connects.

The settings model these read is ``process_engine_core.plugins._mysql``: the
designer needs it to draw the form, and needs nothing here.
"""

from __future__ import annotations

import base64
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from process_engine_core.plugins._mysql import MySQLConnection
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

__all__ = ["MySQLConnection", "jsonable", "open_engine"]


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
