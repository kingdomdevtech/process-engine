"""Cron scheduler: fires published processes that carry schedule triggers.

A single asyncio task ticks every TICK_SECONDS, computes due times with
croniter, and launches runs through a callback provided by the API layer.
Missed windows while the server is down are skipped (cron semantics), unlike
in-flight runs, which the durability layer resumes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable

from croniter import croniter

from .models import ProcessDefinition, utcnow
from .storage import Database

logger = logging.getLogger("process_engine.scheduler")

TICK_SECONDS = 10


class Scheduler:
    def __init__(self, db: Database, launch: Callable[[ProcessDefinition, Any], str]) -> None:
        self.db = db
        self.launch = launch  # starts a background run, returns its run id
        self._task: asyncio.Task | None = None
        self._next_due: dict[tuple[str, str], datetime] = {}

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                self.tick(utcnow())
            except Exception:  # noqa: BLE001 — the scheduler must survive bad definitions
                logger.exception("scheduler tick failed")
            await asyncio.sleep(TICK_SECONDS)

    def tick(self, now: datetime) -> list[str]:
        """One scheduling pass; separated from the loop for testability."""
        fired: list[str] = []
        seen: set[tuple[str, str]] = set()
        for definition in self.db.latest_published_definitions():
            for trigger in definition.triggers:
                if trigger.type != "schedule" or not trigger.enabled:
                    continue
                if not (trigger.cron and croniter.is_valid(trigger.cron)):
                    continue
                key = (definition.id, trigger.id)
                seen.add(key)
                due = self._next_due.get(key)
                if due is None:
                    # first sighting: schedule forward from now, don't fire immediately
                    self._next_due[key] = croniter(trigger.cron, now).get_next(datetime)
                    continue
                if now >= due:
                    run_id = self.launch(
                        definition,
                        {"scheduled_at": now.isoformat(), "cron": trigger.cron, "trigger_id": trigger.id},
                    )
                    logger.info("cron %r fired process %s -> run %s", trigger.cron, definition.id, run_id)
                    fired.append(run_id)
                    self._next_due[key] = croniter(trigger.cron, now).get_next(datetime)
        # forget triggers that were removed or unpublished
        self._next_due = {key: value for key, value in self._next_due.items() if key in seen}
        return fired
