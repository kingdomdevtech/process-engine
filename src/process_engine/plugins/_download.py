"""Shared helpers for the plugins that fetch a file into the working directory.

Where a download lands, and what a half-finished one leaves behind, should not
depend on which cloud it came from — ``s3_download`` and
``azure_blob_download`` both go through here.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .. import workspace


def target_path(destination: str, source: str, *, label: str) -> Path:
    """Resolve where a downloaded object is saved, inside the sandbox.

    ``destination`` blank keeps the object's own file name; a trailing slash
    (or an existing folder) means "into this folder"; anything else is the file
    name to save it under. ``label`` names the source field in error messages
    ("key", "blob").
    """
    # PurePosixPath("a/b.csv").name — never ".." or a drive, whatever the object is called
    name = PurePosixPath(source.strip()).name
    raw = destination.strip()
    if not raw:
        if not name:
            raise ValueError(f"{label} {source!r} has no file name; set “Save as” to one")
        return workspace.resolve(name)

    target = workspace.resolve(raw)
    if raw.endswith(("/", "\\")) or target.is_dir():
        if not name:
            raise ValueError(f"“Save as” {raw!r} is a folder and {label} {source!r} has no file name")
        target = workspace.resolve(target / name)
    return target


def refuse_overwrite(destination: Path, overwrite: bool) -> None:
    if destination.exists() and not overwrite:
        raise FileExistsError(
            f"{workspace.relative(destination)} already exists; turn on “Replace a file that "
            f"is already there” to overwrite it"
        )


def download_to(destination: Path, fetch: Callable[[Path], None]) -> None:
    """Write through a ``.part`` file renamed on success.

    A failed or timed-out download then never leaves a truncated file behind
    for the next step to pick up as if it were complete.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    try:
        fetch(partial)
        partial.replace(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def isoformat(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")
