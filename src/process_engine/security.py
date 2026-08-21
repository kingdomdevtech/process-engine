"""API auth token and secrets encryption key resolution.

Resolution order for both values:

1. Environment variable (set this in any shared or production deployment).
2. A local dotfile in the working directory — auto-generated on first use so
   development works out of the box. The generated value is logged once.
"""

from __future__ import annotations

import logging
import os
import secrets as stdlib_secrets
from pathlib import Path

from cryptography.fernet import Fernet

logger = logging.getLogger("process_engine.security")

AUTH_TOKEN_ENV = "PROCESS_ENGINE_AUTH_TOKEN"
AUTH_TOKEN_FILE = ".process_engine_auth"
SECRET_KEY_ENV = "PROCESS_ENGINE_SECRET_KEY"
SECRET_KEY_FILE = ".process_engine_key"


def _resolve(env_var: str, file_name: str, generate) -> str:
    value = os.environ.get(env_var)
    if value:
        return value
    path = Path(file_name)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    value = generate()
    path.write_text(value, encoding="utf-8")
    logger.warning(
        "generated a new value for %s and stored it in %s — set %s explicitly in production",
        env_var, path.resolve(), env_var,
    )
    return value


def resolve_auth_token() -> str:
    """The bearer token required on every /api call (webhook endpoints excepted)."""
    token = _resolve(AUTH_TOKEN_ENV, AUTH_TOKEN_FILE, lambda: stdlib_secrets.token_urlsafe(32))
    logger.info("designer/API auth token loaded (%d chars); clients send it as 'Authorization: Bearer <token>'", len(token))
    return token


def resolve_fernet_key() -> str:
    """The Fernet key that encrypts stored secrets at rest."""
    return _resolve(SECRET_KEY_ENV, SECRET_KEY_FILE, lambda: Fernet.generate_key().decode())
