"""Delete files older than a cut-off — retention for downloads, exports, logs.

Everything happens inside the working directory (``workspace``): the folder to
purge is resolved there, and every entry the walk discovers is re-checked
against it, so a symlink or Windows junction planted in the tree cannot lead
the delete out of the sandbox. Symlinks themselves are never followed and
never deleted.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from process_engine_core import workspace
from process_engine_core.plugin import Plugin, PluginContext, PluginResult
from process_engine_core.plugins.file_purge import FilePurgeConfig, FilePurgeSpec

MAX_REPORTED = 500  # cap the per-file detail; runs are persisted as JSON


class FilePurgePlugin(FilePurgeSpec, Plugin):
    async def execute(self, ctx: PluginContext) -> PluginResult:
        # filesystem walks block; keep the engine's event loop free
        return PluginResult.main(await asyncio.to_thread(self._purge, ctx.config, ctx.logger))

    @classmethod
    def _purge(cls, cfg: FilePurgeConfig, logger: logging.Logger) -> dict:
        pattern = cfg.pattern.strip() or "*"
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise ValueError(f"pattern {pattern!r} must be relative and must not contain '..'")

        root = workspace.resolve(cfg.directory, must_exist=True)
        if not root.is_dir():
            raise NotADirectoryError(f"not a folder: {workspace.relative(root)}")

        cutoff = time.time() - cfg.older_than_days * 86_400
        matched, skipped = cls._matches(root, pattern, cfg.recursive)
        protected = {
            path
            for path, _ in sorted(matched, key=lambda item: cls._date_of(item[1], cfg), reverse=True)[
                : cfg.keep_latest
            ]
        }
        expired = [
            (path, stat)
            for path, stat in matched
            if path not in protected and cls._date_of(stat, cfg) <= cutoff
        ]

        deleted: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        freed = 0
        for path, stat in expired:
            entry = {
                "path": workspace.relative(path),
                "size_bytes": stat.st_size,
                "date": _isoformat(cls._date_of(stat, cfg)),
            }
            if not cfg.dry_run:
                try:
                    path.unlink()
                except OSError as exc:  # in use, read-only, permissions — keep going
                    errors.append({"path": entry["path"], "error": str(exc)})
                    continue
            freed += stat.st_size
            if len(deleted) < MAX_REPORTED:
                deleted.append(entry)

        removed_dirs = (
            cls._prune_empty(root) if cfg.delete_empty_directories and not cfg.dry_run else []
        )
        logger.info(
            "%s %d/%d file(s) under %s older than %s day(s)%s",
            "would delete" if cfg.dry_run else "deleted",
            len(expired) - len(errors),
            len(matched),
            workspace.relative(root),
            cfg.older_than_days,
            f", {len(errors)} failed" if errors else "",
        )

        result = {
            "directory": str(root),
            "relative_directory": workspace.relative(root),
            "pattern": pattern,
            "recursive": cfg.recursive,
            "older_than_days": cfg.older_than_days,
            "date_field": cfg.date_field,
            "cutoff": _isoformat(cutoff),
            "dry_run": cfg.dry_run,
            "matched_count": len(matched),
            "deleted_count": len(expired) - len(errors),
            "kept_count": len(matched) - len(expired),
            "freed_bytes": freed,
            "deleted": deleted,
            "truncated": len(expired) - len(errors) > len(deleted),
            "skipped": skipped,  # symlinks and anything resolving outside the sandbox
            "removed_directories": removed_dirs,
            "errors": errors,
        }
        if errors and not cfg.ignore_errors:
            raise RuntimeError(
                f"{len(errors)} of {len(expired)} file(s) could not be deleted; "
                f"first: {errors[0]['path']} — {errors[0]['error']}"
            )
        return result

    @staticmethod
    def _matches(root: Path, pattern: str, recursive: bool) -> tuple[list[tuple[Path, Any]], list[str]]:
        """Files under ``root`` matching ``pattern``, each proven to be inside the sandbox."""
        found: list[tuple[Path, Any]] = []
        skipped: list[str] = []
        for path in root.rglob(pattern) if recursive else root.glob(pattern):
            if path.is_symlink():
                skipped.append(workspace.relative(path))  # never follow a link out of the sandbox
                continue
            try:
                resolved = path.resolve()  # collapses junctions/links in any parent component
                if not workspace.is_within(resolved, root):
                    skipped.append(workspace.relative(path))
                    continue
                if not resolved.is_file():
                    continue
                found.append((resolved, resolved.stat()))
            except OSError:
                continue  # vanished or unreadable between the walk and the stat
        return found, skipped

    @staticmethod
    def _date_of(stat: Any, cfg: FilePurgeConfig) -> float:
        if cfg.date_field == "accessed":
            return stat.st_atime
        if cfg.date_field == "created":
            # st_birthtime where the platform has it; on Windows st_ctime *is* creation time
            return getattr(stat, "st_birthtime", stat.st_ctime)
        return stat.st_mtime

    @staticmethod
    def _prune_empty(root: Path) -> list[str]:
        """Remove folders left empty below ``root``; never ``root`` itself."""
        removed: list[str] = []
        folders = [path for path in root.rglob("*") if path.is_dir() and not path.is_symlink()]
        for folder in sorted(folders, key=lambda path: len(path.parts), reverse=True):
            try:
                if not workspace.is_within(folder.resolve(), root) or any(folder.iterdir()):
                    continue
                folder.rmdir()
                removed.append(workspace.relative(folder))
            except OSError:
                continue
        return removed


def _isoformat(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
