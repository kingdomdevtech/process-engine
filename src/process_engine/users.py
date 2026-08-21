"""User accounts for the designer.

Passwords are hashed with PBKDF2-HMAC-SHA256 (stdlib, salted per user).
Sessions are stateless Fernet tokens carrying username+role with a TTL —
no session table required, and revocation happens by disabling the user
(checked on every request).

The static API token (security.resolve_auth_token) stays valid as a
machine/bootstrap credential with the admin role: use it to create the
first real user, and for CI/scripts.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets as stdlib_secrets
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .security import resolve_fernet_key
from .storage import Database

PBKDF2_ITERATIONS = 200_000
SESSION_TTL_SECONDS = 12 * 3600  # sessions expire after 12 hours

ROLES = ("admin", "editor")


def hash_password(password: str) -> str:
    salt = stdlib_secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


class UserManager:
    def __init__(self, db: Database, key: str | bytes | None = None) -> None:
        self.db = db
        self._fernet = Fernet(key or resolve_fernet_key())

    # -- accounts -----------------------------------------------------------------

    def create(self, username: str, password: str, role: str = "editor") -> dict[str, Any]:
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if not username or not password:
            raise ValueError("username and password are required")
        return self.db.create_user(username, hash_password(password), role)

    def update(
        self,
        username: str,
        password: str | None = None,
        role: str | None = None,
        disabled: bool | None = None,
    ) -> dict[str, Any] | None:
        if role is not None and role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        password_hash = hash_password(password) if password else None
        return self.db.update_user(username, password_hash=password_hash, role=role, disabled=disabled)

    def delete(self, username: str) -> bool:
        return self.db.delete_user(username)

    def list(self) -> list[dict[str, Any]]:
        return self.db.list_users()

    # -- sessions -----------------------------------------------------------------

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        user = self.db.get_user(username)
        if user is None or user["disabled"]:
            return None
        if not verify_password(password, user["password_hash"]):
            return None
        return {"username": user["username"], "role": user["role"]}

    def issue_token(self, username: str, role: str) -> str:
        payload = json.dumps({"u": username, "r": role}).encode("utf-8")
        return self._fernet.encrypt(payload).decode("ascii")

    def verify_token(self, token: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(self._fernet.decrypt(token.encode("ascii"), ttl=SESSION_TTL_SECONDS))
        except (InvalidToken, ValueError, UnicodeDecodeError):
            return None
        user = self.db.get_user(payload.get("u", ""))
        if user is None or user["disabled"]:
            return None  # disabling a user revokes their sessions immediately
        return {"name": user["username"], "role": user["role"]}
