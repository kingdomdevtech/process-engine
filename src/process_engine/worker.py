"""Queue mode: background runs executed by worker processes.

``PROCESS_ENGINE_RUN_WORKERS=N`` makes ``api.py`` dispatch background runs
(manual, scheduled, webhook, resumed) to a pool of N child processes instead
of executing them on its own event loop. That is n8n's queue mode scaled to
this project's shape: there is no broker — the job payload carries a snapshot
of the definition taken at enqueue time, and the shared database is the
coordination layer for state, pause/cancel signals and results. CPU-bound
plugin work is why this exists: threads share one GIL, processes do not.

A worker owns one run end to end. It executes the engine (steps still fan out
to the worker's own thread pool), persists after every step, sends the run's
notifications, and polls ``run_signals`` so pause/cancel reach it across the
process boundary. Workers are spawned, not forked, so ``init_worker`` rebuilds
everything from the same environment variables the API reads (database URL,
secret key, plugins dir, step workers).
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

from .engine import DefinitionError, Engine, RunControl
from .models import NotificationEvent, ProcessDefinition, ProcessInstance, RunStatus, utcnow
from .notifications import MailSettingsStore, Notifier, event_for
from .registry import default_registry
from .secrets_store import SecretsManager
from .storage import Database

logger = logging.getLogger("process_engine.worker")

SIGNAL_POLL_SECONDS = 1.0


@dataclass
class WorkerContext:
    db: Database
    engine: Engine
    notifier: Notifier


_context: WorkerContext | None = None


def init_worker() -> None:
    """ProcessPoolExecutor initializer: compose this worker's own stack."""
    global _context
    db = Database()
    engine = Engine(
        default_registry(),
        definition_resolver=lambda process_id: db.get_version(process_id),
        secrets=SecretsManager(db).view(),
        step_workers=int(os.environ.get("PROCESS_ENGINE_STEP_WORKERS", "0")) or None,
    )
    _context = WorkerContext(db=db, engine=engine, notifier=Notifier(MailSettingsStore(db)))


def run_job(job: dict[str, Any]) -> str:
    """Execute one background run; returns the final status for logs and tests."""
    if _context is None:  # the pool initializer normally ran already
        init_worker()
    return asyncio.run(_run_job(_context, job))


async def _run_job(context: WorkerContext, job: dict[str, Any]) -> str:
    definition = ProcessDefinition.model_validate(job["definition"])
    run_id: str = job["run_id"]
    resuming = bool(job.get("resume"))
    # fresh runs were persisted as a PENDING placeholder at enqueue time, so
    # both paths resume a stored instance; the fallback covers a lost row
    instance = context.db.get_instance(run_id)
    if instance is None:
        logger.warning("run %s has no stored instance; starting fresh", run_id)

    control = RunControl()

    def apply_signal(signal: str | None) -> None:
        if signal == "cancel":
            control.cancel_requested = True
        elif signal == "pause":
            control.pause_requested = True

    # a signal queued before the job even started must win deterministically
    apply_signal(context.db.get_run_signal(run_id))

    async def poll_signals() -> None:
        while True:
            await asyncio.sleep(SIGNAL_POLL_SECONDS)
            apply_signal(await asyncio.to_thread(context.db.get_run_signal, run_id))

    # the started email mirrors api._updater: announce on the engine's first
    # report, never for resumes or sub-process runs, and never block the run.
    # A PENDING placeholder re-dispatched after a restart has never announced.
    sends: list[asyncio.Task] = []
    announced = resuming and instance is not None and instance.status is not RunStatus.PENDING

    def on_update(updated: ProcessInstance) -> None:
        nonlocal announced
        try:
            context.db.save_instance(updated)
        except Exception:  # noqa: BLE001 — persistence must not kill the run
            logger.exception("failed to persist run %s", updated.id)
        if not announced and updated.parent_run_id is None:
            announced = True
            snapshot = updated.model_copy(deep=True)
            sends.append(
                asyncio.create_task(context.notifier.deliver(definition, snapshot, NotificationEvent.STARTED))
            )

    poller = asyncio.create_task(poll_signals())
    status = RunStatus.FAILED
    try:
        result = await context.engine.run(
            definition,
            trigger_input=job.get("trigger_input"),
            variables=job.get("variables"),
            instance=instance,
            run_id=run_id,
            on_update=on_update,
            control=control,
        )
        status = result.status
        await asyncio.gather(*sends)  # "started" must not overtake the final word
        event = event_for(definition.notifications, result.status)
        if event is not None:
            await context.notifier.deliver(definition, result, event)
    except DefinitionError as exc:
        logger.error("background run %s failed validation: %s", run_id, exc.issues)
        _mark_failed(context, instance, "; ".join(exc.issues))
    except Exception as exc:  # noqa: BLE001 — a crashed run must not wedge the worker
        logger.exception("background run %s crashed", run_id)
        _mark_failed(context, instance, f"{type(exc).__name__}: {exc}")
    finally:
        poller.cancel()
        await asyncio.gather(poller, return_exceptions=True)
        try:
            context.db.clear_run_signal(run_id)
        except Exception:  # noqa: BLE001
            logger.exception("could not clear the signal for run %s", run_id)
    return status.value


def _mark_failed(context: WorkerContext, instance: ProcessInstance | None, error: str) -> None:
    """Record the failure so a placeholder is not re-dispatched forever."""
    if instance is None:
        return
    instance.status = RunStatus.FAILED
    instance.error = error
    instance.finished_at = utcnow()
    try:
        context.db.save_instance(instance)
    except Exception:  # noqa: BLE001
        logger.exception("failed to persist the failure of run %s", instance.id)
