"""The filesystem sandbox every file-handling Plugin resolves paths through.

A process definition is data that any *editor* can author, so a plugin that
takes a path must not be able to read ``C:\\Windows``, write into ``/etc``, or
touch the engine's own database and credential files. One working directory
answers that: paths in step config are interpreted **relative to it**, and an
absolute path is accepted only when it already points inside it.

The root comes from ``PROCESS_ENGINE_WORK_DIR`` (default ``./workdir``) — it is
deployment configuration, deliberately not an API setting, so a signed-in user
cannot widen the sandbox they run inside.

Containment is checked on the *resolved* path, so symlinks (and Windows
junctions) planted inside the working directory cannot lead out of it.
Plugins that walk a tree must re-check every entry they discover, not just the
folder they were given — see ``file_purge``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

WORK_DIR_ENV = "PROCESS_ENGINE_WORK_DIR"
DEFAULT_WORK_DIR = "workdir"


class PathNotAllowed(ValueError):
    """A step asked for a path outside the working directory."""


def work_dir() -> Path:
    """The sandbox root, resolved. Does not create it."""
    configured = os.environ.get(WORK_DIR_ENV, "").strip() or DEFAULT_WORK_DIR
    return Path(configured).expanduser().resolve()


def is_within(path: str | os.PathLike[str], root: Path | None = None) -> bool:
    """True if ``path`` (already resolved) is the root or sits under it."""
    root = root or work_dir()
    candidate = Path(path)
    return candidate == root or root in candidate.parents


def resolve(path: str | os.PathLike[str], *, must_exist: bool = False) -> Path:
    """Turn a step-supplied path into an absolute path inside the sandbox.

    Relative paths are joined onto the working directory; absolute ones must
    already be inside it. Raises ``PathNotAllowed`` otherwise — the engine
    turns that into a failed step with the offending path in the message.
    """
    root = work_dir()
    raw = str(path).strip()
    if not raw:
        raw = "."
    resolved = Path(raw).expanduser()
    resolved = (resolved if resolved.is_absolute() else root / resolved).resolve()
    if not is_within(resolved, root):
        raise PathNotAllowed(
            f"{raw!r} resolves to {resolved}, outside the working directory {root}. "
            f"Use a path inside it, or point {WORK_DIR_ENV} at another folder."
        )
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"{resolved} does not exist (working directory: {root})")
    return resolved


def relative(path: str | os.PathLike[str]) -> str:
    """Display form of a path: relative to the working directory when possible."""
    root = work_dir()
    resolved = Path(path)
    try:
        return resolved.relative_to(root).as_posix() or "."
    except ValueError:
        return str(resolved)


def describe() -> dict[str, Any]:
    """What the API reports about the sandbox (Settings → Files)."""
    root = work_dir()
    exists = root.is_dir()
    return {
        "path": str(root),
        "env_var": WORK_DIR_ENV,
        "configured": bool(os.environ.get(WORK_DIR_ENV, "").strip()),
        "exists": exists,
        "writable": bool(exists and os.access(root, os.W_OK)),
    }
