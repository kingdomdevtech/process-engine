"""The engine host: runs executed by worker processes.

``serve()`` is this package's program — the thing you start on the machine that
must do the work. It claims jobs from the shared database (``job_queue``), fires
the schedules recorded there, and needs no HTTP of its own in either direction.
That is what makes the two-host split possible: the designer and its API live on
Linux, this runs on a Windows box for the Excel/COM plugins, and the database is
the only thing between them. There is no broker — a job payload carries a
snapshot of the definition taken at enqueue time, and the same database carries
state, pause/cancel signals and results.

A worker owns one run end to end. It executes the engine (steps still fan out
to the worker's own thread pool), persists after every step, sends the run's
notifications, and polls ``run_signals`` so pause/cancel reach it across the
process boundary. Everything it needs it reads from the database itself —
including the sub-process definitions ``for_each`` runs, resolved through
``db.get_version``, so nothing here ever calls the API. Workers are spawned, not
forked, so ``init_worker`` rebuilds the whole stack from environment variables
alone (database URL, secret key, step workers) — nothing is inherited from
whoever started it.

Because *all* execution happens here, this also serves the designer's
single-step preview (``preview_job``). A run is fire-and-forget — the worker
persists the instance and the row is dropped — while a preview is
request/reply: someone is watching a spinner, so its answer goes back into the
job row for the API to hand on. Same queue, same claim, different reply path.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from process_engine_core.jobs import enqueue_run
from process_engine_core.models import (
    NotificationEvent,
    ProcessDefinition,
    ProcessInstance,
    RunStatus,
    utcnow,
)
from process_engine_core.notifications import MailSettingsStore, Notifier, event_for
from process_engine_core.secrets_store import SecretsManager
from process_engine_core.storage import Database
from process_engine_core.validation import DefinitionError, preview_result

from .engine import Engine, RunControl
from .registry import default_registry
from .scheduler import TICK_SECONDS, Scheduler

logger = logging.getLogger("process_engine.worker")

SIGNAL_POLL_SECONDS = 1.0


@dataclass
class WorkerContext:
    db: Database
    engine: Engine
    notifier: Notifier


_context: WorkerContext | None = None


def build_context(db: Database | None = None, notifier: Notifier | None = None) -> WorkerContext:
    """Compose an engine host's stack: database, engine, notifier.

    Everything comes from the environment by default — the database URL, the
    secret key, the step-pool size — because workers are spawned rather than
    forked and may be on another machine entirely, so nothing is inherited from
    whoever started them. The arguments are for a caller that already holds a
    stack: an embedded worker, or a test draining the queue in-process.
    """
    db = db or Database()
    engine = Engine(
        default_registry(),
        definition_resolver=lambda process_id: db.get_version(process_id),
        secrets=SecretsManager(db).view(),
        step_workers=int(os.environ.get("PROCESS_ENGINE_STEP_WORKERS", "0")) or None,
    )
    return WorkerContext(db=db, engine=engine, notifier=notifier or Notifier(MailSettingsStore(db)))


def init_worker(db: Database | None = None, notifier: Notifier | None = None) -> None:
    """Install this process's worker context. Called once before claiming work."""
    global _context
    _context = build_context(db, notifier)


def run_job(job: dict[str, Any]) -> str:
    """Execute one queued run; returns the final status for logs and tests."""
    if _context is None:  # serve() normally built the context already
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

    # announce on the engine's first
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


def preview_job(job: dict[str, Any]) -> str:
    """Execute one single-step preview and post the answer back to the queue.

    The designer's "test this step" when the deployment's work happens out here
    rather than in the API process (see ``serve``). Unlike a run there is nobody
    to persist to — a browser is waiting — so the reply goes into the job row
    and the API hands it on when the caller next polls.
    """
    if _context is None:
        init_worker()
    return asyncio.run(_preview_job(_context, job))


async def _preview_job(context: WorkerContext, job: dict[str, Any]) -> str:
    job_id: str = job["job_id"]
    try:
        definition = ProcessDefinition.model_validate(job["definition"])
        run_id = job.get("run_id")
        # the API chose which recorded run to preview against; load it by id so
        # both sides agree on "based on" even as newer runs land in between
        instance = context.db.get_instance(run_id) if run_id else None
        step_run, step_input, resolved = await context.engine.preview_step(
            definition,
            job["step_id"],
            instance,
            variables=job.get("variables"),
            trigger_input=job.get("trigger_input"),
        )
    except DefinitionError as exc:
        context.db.complete_job(job_id, {"issues": exc.issues}, status="failed")
        return "failed"
    except Exception as exc:  # noqa: BLE001 — the browser is waiting; answer with the reason
        logger.exception("preview job %s crashed", job_id)
        context.db.complete_job(job_id, {"issues": [f"{type(exc).__name__}: {exc}"]}, status="failed")
        return "failed"
    context.db.complete_job(job_id, preview_result(step_run, step_input, resolved, run_id))
    return step_run.status.value


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


# -- standalone worker (distributed queue) -----------------------------------------

POLL_SECONDS = 2.0
LEASE_SECONDS = 300.0  # a claim older than this is assumed dead and reclaimable
PURGE_EVERY_SECONDS = 300.0  # how often one worker sweeps uncollected preview replies
PREVIEW_KEEP_SECONDS = 3600.0


def _install_signal_handlers(stop: threading.Event) -> None:
    def handler(_signum: int, _frame: Any) -> None:
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):  # only settable from the main thread
            pass


def serve(
    stop: threading.Event | None = None,
    poll_seconds: float = POLL_SECONDS,
    lease_seconds: float = LEASE_SECONDS,
    schedule: bool | None = None,
) -> None:
    """Claim and execute queued jobs from the shared database until interrupted.

    This is the engine host: run it where the work must happen (a Windows box
    for Excel/COM) while the designer and its API live elsewhere. It owns each
    run end to end — engine, per-step persistence, notifications, pause/cancel
    via ``run_signals`` — so start one process per concurrent run. A crashed or killed worker's claim lapses after
    ``lease_seconds`` and another worker reclaims the job, replaying the
    persisted instance.

    It needs nothing from the designer's side to do its job. Single-step
    previews arrive through the same queue (``kind == "preview"``), as
    request/reply rather than fire-and-forget: the answer goes back into the job
    row, not the run history. And it runs its own cron — schedules live in the
    database, so published processes keep firing while the designer's container
    is restarting, or gone. Set ``PROCESS_ENGINE_WORKER_SCHEDULER=false`` to
    leave scheduling to something else; several workers scheduling at once is
    safe either way, since a firing is claimed in the database.

    Each loop also writes a heartbeat, which is the only way the designer can
    tell "queued behind other work" from "nothing is running out there".
    """
    if _context is None:
        init_worker()
    own_signals = stop is None
    stop = stop or threading.Event()
    if own_signals:
        _install_signal_handlers(stop)
    hostname = socket.gethostname()
    worker_id = f"{hostname}:{os.getpid()}"
    if schedule is None:
        schedule = os.environ.get("PROCESS_ENGINE_WORKER_SCHEDULER", "true").lower() not in ("0", "false", "no")
    # the scheduler only enqueues: the run itself is claimed like any other job,
    # by this worker or another, so a schedule needs no special execution path
    scheduler = Scheduler(
        _context.db,
        lambda definition, trigger_input: enqueue_run(_context.db, definition, trigger_input=trigger_input),
    )
    logger.info(
        "worker %s polling for jobs%s", worker_id, " and firing schedules" if schedule else ""
    )
    since_purge = 0.0
    since_tick = float(TICK_SECONDS)  # tick on the first pass, not a tick later
    try:
        while not stop.is_set():
            try:
                _context.db.worker_heartbeat(worker_id, hostname)
                if since_purge >= PURGE_EVERY_SECONDS:
                    since_purge = 0.0
                    _context.db.purge_jobs(PREVIEW_KEEP_SECONDS)
                if schedule and since_tick >= TICK_SECONDS:
                    since_tick = 0.0
                    scheduler.tick(utcnow())
            except Exception:  # noqa: BLE001 — bookkeeping must not stop the work
                logger.exception("worker %s could not complete its housekeeping", worker_id)
            job = _context.db.claim_job(worker_id, lease_seconds=lease_seconds)
            if job is None:
                stop.wait(poll_seconds)
                since_purge += poll_seconds
                since_tick += poll_seconds
                continue
            with _renewed_claim(job.get("job_id", ""), lease_seconds):
                execute_claimed(job, worker_id)
            # a long run is a long gap: count the time it took, not one poll
            since_tick = float(TICK_SECONDS)
    finally:
        try:
            _context.db.remove_worker(worker_id)  # a clean exit says so immediately
        except Exception:  # noqa: BLE001
            logger.debug("worker %s could not clear its heartbeat", worker_id, exc_info=True)
    logger.info("worker %s stopped", worker_id)


@contextmanager
def _renewed_claim(job_id: str, lease_seconds: float):
    """Keep renewing this worker's claim for as long as the job runs.

    A daemon thread rather than the running loop: the job owns the event loop
    and a plugin can block a thread of it for minutes, which is exactly when the
    renewal matters most.
    """
    if not job_id:
        yield
        return
    done = threading.Event()

    def renew() -> None:
        interval = max(lease_seconds / 3.0, 1.0)
        while not done.wait(interval):
            try:
                _context.db.touch_job(job_id)
            except Exception:  # noqa: BLE001 — a missed renewal only risks a reclaim
                logger.debug("could not renew the claim on job %s", job_id, exc_info=True)

    thread = threading.Thread(target=renew, name=f"claim-{job_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        done.set()
        thread.join(timeout=5)


def execute_claimed(job: dict[str, Any], worker_id: str) -> str:
    """Run one claimed job of either kind; one bad job must not stop the worker.

    The unit of work ``serve`` loops over, and the whole of what claiming a job
    commits this host to. A run's row is dropped when it settles; a preview's is
    left holding the answer for the API to collect.
    """
    kind = job.get("kind", "run")
    job_id = job.get("job_id", job.get("run_id", "?"))
    if kind == "preview":
        try:
            status = preview_job(job)
            logger.info("preview %s finished in worker %s: %s", job_id, worker_id, status)
            return status
        except Exception:  # noqa: BLE001
            # _preview_job answers the caller itself; this is the last resort,
            # and leaving the row claimed lets the lease hand it to someone else
            logger.exception("preview %s crashed in worker %s", job_id, worker_id)
            return "crashed"
    status = "crashed"
    try:
        status = run_job(job)
        logger.info("run %s finished in worker %s: %s", job_id, worker_id, status)
    except Exception:  # noqa: BLE001
        logger.exception("run %s crashed in worker %s", job_id, worker_id)
    finally:
        _context.db.finish_job(job_id)
    return status


def main() -> None:
    """The engine host's program: ``process-engine-worker`` / ``python -m process_engine``."""
    logging.basicConfig(
        level=os.environ.get("PROCESS_ENGINE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    serve(poll_seconds=float(os.environ.get("PROCESS_ENGINE_QUEUE_POLL_SECONDS", str(POLL_SECONDS))))


if __name__ == "__main__":
    main()
