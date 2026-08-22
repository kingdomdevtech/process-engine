"""Cron scheduler: fires published processes that carry schedule triggers.

A single asyncio task ticks every TICK_SECONDS, computes due times with
croniter, and publishes each firing through a callback its host provides.
Missed windows while nothing was running are skipped (cron semantics), unlike
in-flight runs, which the durability layer resumes.

Cron belongs to the engine hosts: they are what executes, so automation carries
on while the designer's container is restarting — or gone. The due times live in
the database rather than in this object precisely because several engines may be
watching the same trigger; rolling a trigger's due time forward is how one of
them claims that firing, so a cron window fires once however many are up.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from croniter import croniter

from process_engine_core.models import ProcessDefinition, utcnow
from process_engine_core.storage import Database

logger = logging.getLogger("process_engine.scheduler")

TICK_SECONDS = 10
# How late a firing may be and still happen. A tick can slip by a second or two
# under load; an hour late means nothing was running when it came due, and cron
# skips those rather than stampeding on start-up.
LATE_TOLERANCE_SECONDS = 120


class Scheduler:
    def __init__(self, db: Database, launch: Callable[[ProcessDefinition, Any], str]) -> None:
        self.db = db
        self.launch = launch  # starts a background run, returns its run id
        self._task: asyncio.Task | None = None

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
                seen.add((definition.id, trigger.id))
                run_id = self._fire_if_due(definition, trigger, now)
                if run_id is not None:
                    fired.append(run_id)
        # forget triggers that were removed or unpublished
        self.db.forget_schedules(seen)
        return fired

    def _fire_if_due(self, definition: ProcessDefinition, trigger: Any, now: datetime) -> str | None:
        due = self.db.schedule_due(definition.id, trigger.id)
        if due is None:
            # first sighting: schedule forward from now, don't fire immediately
            self.db.arm_schedule(definition.id, trigger.id, croniter(trigger.cron, now).get_next(datetime))
            return None
        if now < due:
            return None
        # Claim before firing, and roll forward whether or not we go on to fire:
        # a window nobody was up for is spent, not owed.
        if not self.db.claim_schedule(
            definition.id, trigger.id, due, croniter(trigger.cron, now).get_next(datetime)
        ):
            return None  # another scheduler owns this firing
        if now - due > timedelta(seconds=LATE_TOLERANCE_SECONDS):
            logger.info(
                "cron %r on process %s was due %s and is too late to fire; skipping to the next window",
                trigger.cron,
                definition.id,
                due.isoformat(),
            )
            return None
        run_id = self.launch(
            definition,
            {"scheduled_at": now.isoformat(), "cron": trigger.cron, "trigger_id": trigger.id},
        )
        logger.info("cron %r fired process %s -> run %s", trigger.cron, definition.id, run_id)
        return run_id
