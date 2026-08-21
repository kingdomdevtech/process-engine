"""Named credentials, encrypted at rest with Fernet (AES-128-CBC + HMAC).

Steps never store credentials — they reference them with
``{{ secrets.<name> }}``, which the engine resolves at execution time.
The API only ever exposes secret *names*; values are write-only.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from cryptography.fernet import Fernet

from .security import resolve_fernet_key
from .storage import Database


class SecretsManager:
    def __init__(self, db: Database, key: str | bytes | None = None) -> None:
        self.db = db
        self._fernet = Fernet(key or resolve_fernet_key())

    def set(self, name: str, value: str) -> None:
        self.db.set_secret(name, self._fernet.encrypt(value.encode("utf-8")))

    def get(self, name: str) -> str | None:
        token = self.db.get_secret(name)
        if token is None:
            return None
        return self._fernet.decrypt(token).decode("utf-8")

    def delete(self, name: str) -> bool:
        return self.db.delete_secret(name)

    def names(self) -> list[str]:
        return self.db.list_secret_names()

    def view(self) -> "SecretsView":
        return SecretsView(self)


class SecretsView(Mapping):
    """Read-only mapping handed to the engine for {{ secrets.name }} lookups."""

    def __init__(self, manager: SecretsManager) -> None:
        self._manager = manager

    def __getitem__(self, name: str) -> str:
        value = self._manager.get(name)
        if value is None:
            raise KeyError(name)
        return value

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self._manager.get(name) is not None

    def __iter__(self) -> Iterator[str]:
        return iter(self._manager.names())

    def __len__(self) -> int:
        return len(self._manager.names())
