"""SQLAlchemy persistence — SQLite by default, MySQL (or Postgres) by URL.

Definitions and instances are stored as JSON documents (the same approach
n8n takes) with a few extracted columns for listing and filtering. The
``processes`` table always holds the editable draft; published versions are
immutable snapshots in ``process_versions``.

Select the backend with the ``PROCESS_ENGINE_DB_URL`` environment variable
(or pass a URL to ``Database``), e.g. for the dockerized MySQL in
``docker-compose.yml``:

    mysql+pymysql://process_engine:process_engine@127.0.0.1:3306/process_engine
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Integer,
    LargeBinary,
    String,
    create_engine,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from .models import ProcessDefinition, ProcessInstance, ProcessStatus, new_id, utcnow

NAME_MAX = 200  # width of ProcessRow.name; generated copy names are clamped to it


def as_utc(value: datetime) -> datetime:
    """A stored instant made comparable with ``utcnow()``.

    Same reason as ``iso_utc``: SQLite reads ``DateTime(timezone=True)`` back
    naive, and comparing a naive datetime with an aware one raises. Everything
    written here is UTC, so attaching the offset is a restoration, not a guess.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def iso_utc(value: datetime) -> str:
    """A stored instant as ISO-8601 *with* its UTC offset.

    Every timestamp written here is UTC (``utcnow``), but SQLite has no timezone
    type, so ``DateTime(timezone=True)`` columns read back naive and a plain
    ``isoformat()`` emits no offset. A browser parses an offset-less date-time as
    *local* time, which silently shifted every "x ago" in the designer by the
    viewer's own offset. Always send the offset and let the client localise.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class ProcessRow(Base):
    __tablename__ = "processes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(NAME_MAX))
    latest_version: Mapped[int] = mapped_column(Integer, default=0)  # 0 = never published
    definition: Mapped[dict] = mapped_column(JSON)  # the draft document
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProcessVersionRow(Base):
    __tablename__ = "process_versions"

    process_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    definition: Mapped[dict] = mapped_column(JSON)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InstanceRow(Base):
    __tablename__ = "process_instances"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    process_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RunSignalRow(Base):
    """A pause/cancel request for a run executing in another process.

    Every run executes on an engine host, so the ``RunControl`` for it always
    lives in another process — usually on another machine — and out of the
    API's reach. The request is written here and the worker polls it between
    steps. One row per run at most, cleared when the run settles.
    """

    __tablename__ = "run_signals"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    signal: Mapped[str] = mapped_column(String(10))  # "pause" | "cancel"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobRow(Base):
    """Work waiting for an engine host to pick it up.

    This table is the channel: workers run on *other* machines (a Windows box
    for Excel/COM, say) and the shared database is the only thing between them
    and the API. The API writes the job payload here; a worker claims the oldest
    row with a time-boxed lease, so a worker that dies mid-run releases the job
    for another to reclaim (the engine replays the persisted instance).

    Two ``kind``s share the queue, because the API host executes nothing at
    all — it holds no engine. A ``run`` job needs no answer sent back — the worker
    persists the instance, so the row is deleted once the run settles. A
    ``preview`` job *is* a request/reply: the browser is waiting, so the worker
    writes the result into ``result`` and the row lives on until the caller has
    collected it (or ``purge_jobs`` reaps it).
    """

    __tablename__ = "job_queue"

    job_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), default="run")  # "run" | "preview"
    payload: Mapped[dict] = mapped_column(JSON)  # definition snapshot + trigger/vars/resume
    # "queued" -> "claimed" -> ("done" | "failed"); runs never reach the last two
    status: Mapped[str] = mapped_column(String(10), default="queued")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # preview reply
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScheduleRow(Base):
    """When a schedule trigger is next due — the scheduler's memory, shared.

    It used to be a dict inside whichever process ran the scheduler, which was
    fine while exactly one did. Once the engine hosts schedule for themselves
    (so automation does not stop when the designer's container restarts) there
    can be several schedulers looking at the same cron, and a remembered-in-RAM
    due time would fire the same window once per process. Rolling the due time
    forward *is* the claim: whoever's guarded UPDATE lands owns that firing.
    """

    __tablename__ = "schedule_state"

    process_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    trigger_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_due: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkerRow(Base):
    """A worker's heartbeat, so the API can say whether anyone is listening.

    Nothing routes on this — it is pure observability, and it earns its place
    because of what the queue changes for the person in the designer: with the
    API executing nothing, "queued" is indistinguishable from "no worker is
    running" unless someone reports the difference. Rows go stale rather than
    being deleted; a worker that shuts down cleanly removes its own.
    """

    __tablename__ = "workers"

    worker_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(100), default="")
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SecretRow(Base):
    __tablename__ = "secrets"

    name: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[bytes] = mapped_column(LargeBinary)  # Fernet-encrypted
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SettingRow(Base):
    """Deployment settings an admin edits at runtime, one JSON document per key.

    Only the notification mail relay lives here today. Anything genuinely
    security-shaped (the file sandbox, the auth token) stays in the environment
    on purpose, so signing in to the designer cannot widen it.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserRow(Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(80), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="editor")
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


DB_URL_ENV = "PROCESS_ENGINE_DB_URL"
DEFAULT_DB_URL = "sqlite:///process_engine.db"


def copy_name(original: str, taken: set[str]) -> str:
    """Report -> Report (copy) -> Report (copy 2) -> ..., clamped to NAME_MAX."""
    stem = original[: NAME_MAX - len(" (copy 999)")]
    candidate = f"{stem} (copy)"
    counter = 2
    while candidate in taken:
        candidate = f"{stem} (copy {counter})"
        counter += 1
    return candidate


class Database:
    def __init__(self, url: str | None = None) -> None:
        url = url or os.environ.get(DB_URL_ENV, DEFAULT_DB_URL)
        kwargs: dict[str, Any] = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url or url == "sqlite://":
                kwargs["poolclass"] = StaticPool
        else:
            kwargs["pool_pre_ping"] = True  # survive MySQL idle-connection timeouts
        self.engine = create_engine(url, **kwargs)
        Base.metadata.create_all(self.engine)

    # -- processes (drafts) ---------------------------------------------------

    def save_process(self, definition: ProcessDefinition) -> ProcessDefinition:
        definition.updated_at = utcnow()
        with Session(self.engine) as session:
            row = session.get(ProcessRow, definition.id)
            if row is None:
                row = ProcessRow(id=definition.id, latest_version=0)
                session.add(row)
            else:
                definition.version = row.latest_version or definition.version
            row.name = definition.name
            row.definition = definition.model_dump(mode="json")
            row.updated_at = definition.updated_at
            session.commit()
        return definition

    def get_process(self, process_id: str) -> ProcessDefinition | None:
        with Session(self.engine) as session:
            row = session.get(ProcessRow, process_id)
            return ProcessDefinition.model_validate(row.definition) if row else None

    def list_processes(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.scalars(select(ProcessRow).order_by(ProcessRow.updated_at.desc())).all()
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    # folder lives in the definition document, so adding it needed no migration
                    "folder": (row.definition or {}).get("folder", ""),
                    "latest_version": row.latest_version,
                    "updated_at": iso_utc(row.updated_at),
                    # who may see this row: the API filters the listing on these,
                    # and the dashboard badges what is shared
                    "created_by": (row.definition or {}).get("created_by", ""),
                    "shared_with": (row.definition or {}).get("shared_with", []) or [],
                }
                for row in rows
            ]

    def delete_process(self, process_id: str) -> bool:
        with Session(self.engine) as session:
            row = session.get(ProcessRow, process_id)
            if row is None:
                return False
            session.delete(row)
            session.execute(delete(ProcessVersionRow).where(ProcessVersionRow.process_id == process_id))
            session.commit()
            return True

    def clone_process(
        self,
        process_id: str,
        *,
        name: str | None = None,
        folder: str | None = None,
        created_by: str | None = None,
    ) -> ProcessDefinition | None:
        """Copy a draft into a brand-new, never-published process.

        Step and connection ids are carried over deliberately: ``{{ steps.<id> }}``
        expressions inside the copied config must keep resolving. Only the process
        id is new, so nothing is shared with the original.

        Triggers come across *disabled*, and webhook paths are cleared (they fall
        back to the new process id) — a path resolves to one published process
        only, so a copy must never silently take over the original's schedule or
        webhook. Version history is not copied; the clone starts unpublished.

        ``created_by`` names the copy's owner: whoever cloned it, not the author
        of the original, since notifications addressed to "the creator" should
        follow the copy to the person now responsible for it.
        """
        with Session(self.engine) as session:
            row = session.get(ProcessRow, process_id)
            if row is None:
                return None
            source = ProcessDefinition.model_validate(row.definition)
            taken = set(session.scalars(select(ProcessRow.name)).all())

        clone = source.model_copy(deep=True)
        clone.id = new_id()
        clone.name = (name or "").strip()[:NAME_MAX] or copy_name(source.name, taken)
        if folder is not None:
            clone.folder = folder.strip()
        clone.version = 1
        clone.status = ProcessStatus.DRAFT
        clone.created_at = utcnow()
        clone.shared_with = []  # the copy starts private to whoever made it
        if created_by is not None:
            clone.created_by = created_by
        for trigger in clone.triggers:
            trigger.id = new_id()
            trigger.enabled = False
            if trigger.type == "webhook":
                trigger.path = ""
        return self.save_process(clone)

    # -- published versions ----------------------------------------------------

    def publish_process(self, process_id: str) -> ProcessDefinition | None:
        """Snapshot the current draft as the next immutable version."""
        with Session(self.engine) as session:
            row = session.get(ProcessRow, process_id)
            if row is None:
                return None
            draft = ProcessDefinition.model_validate(row.definition)
            row.latest_version += 1
            snapshot = draft.model_copy(deep=True)
            snapshot.version = row.latest_version
            snapshot.status = ProcessStatus.PUBLISHED
            session.add(
                ProcessVersionRow(
                    process_id=process_id,
                    version=row.latest_version,
                    definition=snapshot.model_dump(mode="json"),
                    published_at=utcnow(),
                )
            )
            draft.version = row.latest_version
            row.definition = draft.model_dump(mode="json")
            session.commit()
            return snapshot

    def latest_published_definitions(self) -> list[ProcessDefinition]:
        """The newest published version of every process (scheduler/webhook lookup)."""
        with Session(self.engine) as session:
            process_ids = session.scalars(select(ProcessRow.id)).all()
        definitions = []
        for process_id in process_ids:
            definition = self.get_version(process_id)
            if definition is not None:
                definitions.append(definition)
        return definitions

    def get_version(self, process_id: str, version: int | None = None) -> ProcessDefinition | None:
        """A published version; the latest one when version is None."""
        with Session(self.engine) as session:
            stmt = select(ProcessVersionRow).where(ProcessVersionRow.process_id == process_id)
            if version is None:
                stmt = stmt.order_by(ProcessVersionRow.version.desc()).limit(1)
            else:
                stmt = stmt.where(ProcessVersionRow.version == version)
            row = session.scalars(stmt).first()
            return ProcessDefinition.model_validate(row.definition) if row else None

    # -- instances ---------------------------------------------------------------

    def save_instance(self, instance: ProcessInstance) -> ProcessInstance:
        with Session(self.engine) as session:
            session.merge(
                InstanceRow(
                    id=instance.id,
                    process_id=instance.process_id,
                    status=instance.status.value,
                    data=instance.model_dump(mode="json"),
                    created_at=instance.started_at or utcnow(),
                )
            )
            session.commit()
        return instance

    def get_instance(self, instance_id: str) -> ProcessInstance | None:
        with Session(self.engine) as session:
            row = session.get(InstanceRow, instance_id)
            return ProcessInstance.model_validate(row.data) if row else None

    def get_instances_by_status(self, status: str) -> list[ProcessInstance]:
        with Session(self.engine) as session:
            rows = session.scalars(select(InstanceRow).where(InstanceRow.status == status)).all()
            return [ProcessInstance.model_validate(row.data) for row in rows]

    def list_instances(self, process_id: str | None = None) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            stmt = select(InstanceRow).order_by(InstanceRow.created_at.desc())
            if process_id is not None:
                stmt = stmt.where(InstanceRow.process_id == process_id)
            rows = session.scalars(stmt).all()
            return [
                {
                    "id": row.id,
                    "process_id": row.process_id,
                    "status": row.status,
                    "created_at": iso_utc(row.created_at),
                    # from the document rather than extracted columns — the run
                    # list shows a duration, and the JSON is already loaded
                    "started_at": (row.data or {}).get("started_at"),
                    "finished_at": (row.data or {}).get("finished_at"),
                }
                for row in rows
            ]

    # -- run signals (cross-process pause/cancel, queue mode only) -----------------

    def set_run_signal(self, run_id: str, signal: str) -> None:
        with Session(self.engine) as session:
            session.merge(RunSignalRow(run_id=run_id, signal=signal, created_at=utcnow()))
            session.commit()

    def get_run_signal(self, run_id: str) -> str | None:
        with Session(self.engine) as session:
            row = session.get(RunSignalRow, run_id)
            return row.signal if row else None

    def clear_run_signal(self, run_id: str) -> None:
        with Session(self.engine) as session:
            session.execute(delete(RunSignalRow).where(RunSignalRow.run_id == run_id))
            session.commit()

    # -- jobs (distributed queue: workers on other machines) -----------------------

    def enqueue_job(self, job_id: str, payload: dict[str, Any], kind: str = "run") -> None:
        """Publish work for a worker to claim. Re-enqueue re-queues."""
        with Session(self.engine) as session:
            session.merge(
                JobRow(
                    job_id=job_id,
                    kind=kind,
                    payload=payload,
                    status="queued",
                    result=None,
                    claimed_by=None,
                    claimed_at=None,
                    created_at=utcnow(),
                    finished_at=None,
                )
            )
            session.commit()

    def claim_job(self, worker_id: str, lease_seconds: float = 300.0) -> dict[str, Any] | None:
        """Atomically take the oldest claimable job, or None.

        Claimable means queued, or claimed so long ago that the worker holding
        it is assumed dead. The guarded ``UPDATE`` is the lock: only one
        worker's write flips a row to ``claimed``, so a lost race just moves on
        to the next candidate. No ``FOR UPDATE SKIP LOCKED`` — this stays
        portable to SQLite. The returned payload carries ``job_id``/``kind`` so
        the worker needs nothing else to dispatch it.
        """
        cutoff = utcnow() - timedelta(seconds=lease_seconds)
        # a finished preview reply is not work: only "claimed" rows time out
        claimable = (JobRow.status == "queued") | ((JobRow.status == "claimed") & (JobRow.claimed_at < cutoff))
        with Session(self.engine) as session:
            candidates = session.scalars(
                select(JobRow.job_id).where(claimable).order_by(JobRow.created_at)
            ).all()
            for job_id in candidates:
                result = session.execute(
                    update(JobRow).where(JobRow.job_id == job_id, claimable).values(
                        status="claimed", claimed_by=worker_id, claimed_at=utcnow()
                    )
                )
                if result.rowcount == 1:
                    row = session.get(JobRow, job_id)
                    payload = {**dict(row.payload), "job_id": job_id, "kind": row.kind}
                    session.commit()
                    return payload
                session.rollback()  # another worker won it; try the next
        return None

    def touch_job(self, job_id: str) -> None:
        """Renew a claim, so a slow job is never mistaken for a dead worker.

        The lease exists to recover work from a worker that died, but an Excel
        refresh can outlive any sane lease; without this, a second worker would
        claim a job still executing and run its side effects again. The worker
        holding the claim renews it while it works, which is what makes the
        lease mean "gone" rather than "slow".
        """
        with Session(self.engine) as session:
            session.execute(
                update(JobRow)
                .where(JobRow.job_id == job_id, JobRow.status == "claimed")
                .values(claimed_at=utcnow())
            )
            session.commit()

    def finish_job(self, job_id: str) -> None:
        """Drop a job whose answer lives elsewhere (a run persists its instance)."""
        with Session(self.engine) as session:
            session.execute(delete(JobRow).where(JobRow.job_id == job_id))
            session.commit()

    def complete_job(self, job_id: str, result: dict[str, Any], status: str = "done") -> None:
        """Record a job's reply for the caller waiting on it (previews)."""
        with Session(self.engine) as session:
            session.execute(
                update(JobRow)
                .where(JobRow.job_id == job_id)
                .values(status=status, result=result, finished_at=utcnow())
            )
            session.commit()

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """A job's lifecycle state and reply, for a caller polling it."""
        with Session(self.engine) as session:
            row = session.get(JobRow, job_id)
            if row is None:
                return None
            return {
                "job_id": row.job_id,
                "kind": row.kind,
                "status": row.status,
                "result": row.result,
                "claimed_by": row.claimed_by,
                "created_at": iso_utc(row.created_at),
                "finished_at": iso_utc(row.finished_at) if row.finished_at else None,
            }

    def count_queued_jobs(self, kind: str | None = None) -> int:
        """How much work is waiting or in flight — the depth an admin sees."""
        with Session(self.engine) as session:
            query = select(func.count()).select_from(JobRow).where(JobRow.status.in_(("queued", "claimed")))
            if kind is not None:
                query = query.where(JobRow.kind == kind)
            return int(session.scalar(query) or 0)

    def purge_jobs(self, older_than_seconds: float = 3600.0) -> int:
        """Reap settled preview replies nobody collected. Returns rows removed."""
        cutoff = utcnow() - timedelta(seconds=older_than_seconds)
        with Session(self.engine) as session:
            result = session.execute(
                delete(JobRow).where(JobRow.status.in_(("done", "failed")), JobRow.finished_at < cutoff)
            )
            session.commit()
            return int(result.rowcount or 0)

    # -- schedule state (one firing per cron window, whoever is running) -----------

    def schedule_due(self, process_id: str, trigger_id: str) -> datetime | None:
        with Session(self.engine) as session:
            row = session.get(ScheduleRow, (process_id, trigger_id))
            return as_utc(row.next_due) if row is not None else None

    def arm_schedule(self, process_id: str, trigger_id: str, next_due: datetime) -> None:
        """Record a trigger's first due time. Never fires: cron looks forward."""
        with Session(self.engine) as session:
            session.merge(ScheduleRow(process_id=process_id, trigger_id=trigger_id, next_due=next_due))
            session.commit()

    def claim_schedule(
        self, process_id: str, trigger_id: str, due: datetime, next_due: datetime
    ) -> bool:
        """Win the right to fire ``due``, rolling the trigger on to ``next_due``.

        The ``WHERE next_due = due`` is the lock: a second scheduler holding the
        same due time updates nothing and is told to stay out of it.
        """
        with Session(self.engine) as session:
            result = session.execute(
                update(ScheduleRow)
                .where(
                    ScheduleRow.process_id == process_id,
                    ScheduleRow.trigger_id == trigger_id,
                    ScheduleRow.next_due == due,
                )
                .values(next_due=next_due)
            )
            session.commit()
            return result.rowcount == 1

    def forget_schedules(self, keep: set[tuple[str, str]]) -> None:
        """Drop state for triggers that were removed, disabled or unpublished."""
        with Session(self.engine) as session:
            for row in session.scalars(select(ScheduleRow)).all():
                if (row.process_id, row.trigger_id) not in keep:
                    session.delete(row)
            session.commit()

    # -- workers (heartbeats, so the API can report whether anyone is listening) ----

    def worker_heartbeat(self, worker_id: str, hostname: str) -> None:
        with Session(self.engine) as session:
            session.merge(WorkerRow(worker_id=worker_id, hostname=hostname, last_seen=utcnow()))
            session.commit()

    def list_workers(self, stale_after_seconds: float = 60.0) -> list[dict[str, Any]]:
        """Workers seen recently enough to be considered alive, newest first."""
        cutoff = utcnow() - timedelta(seconds=stale_after_seconds)
        with Session(self.engine) as session:
            rows = session.scalars(
                select(WorkerRow).where(WorkerRow.last_seen >= cutoff).order_by(WorkerRow.last_seen.desc())
            ).all()
            return [
                {"worker_id": row.worker_id, "hostname": row.hostname, "last_seen": iso_utc(row.last_seen)}
                for row in rows
            ]

    def remove_worker(self, worker_id: str) -> None:
        with Session(self.engine) as session:
            session.execute(delete(WorkerRow).where(WorkerRow.worker_id == worker_id))
            session.commit()

    # -- secrets (values are Fernet-encrypted by SecretsManager) ------------------

    def set_secret(self, name: str, encrypted_value: bytes) -> None:
        with Session(self.engine) as session:
            session.merge(SecretRow(name=name, value=encrypted_value, updated_at=utcnow()))
            session.commit()

    def get_secret(self, name: str) -> bytes | None:
        with Session(self.engine) as session:
            row = session.get(SecretRow, name)
            return row.value if row else None

    def delete_secret(self, name: str) -> bool:
        with Session(self.engine) as session:
            row = session.get(SecretRow, name)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    def list_secret_names(self) -> list[str]:
        with Session(self.engine) as session:
            return list(session.scalars(select(SecretRow.name).order_by(SecretRow.name)).all())

    # -- settings (JSON document per key; see SettingRow) --------------------------

    def get_setting(self, key: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(SettingRow, key)
            return dict(row.value) if row else None

    def set_setting(self, key: str, value: dict[str, Any]) -> None:
        with Session(self.engine) as session:
            session.merge(SettingRow(key=key, value=value, updated_at=utcnow()))
            session.commit()

    # -- users --------------------------------------------------------------------

    @staticmethod
    def _user_public(row: UserRow) -> dict[str, Any]:
        return {
            "username": row.username,
            "role": row.role,
            "disabled": row.disabled,
            "created_at": iso_utc(row.created_at),
        }

    def create_user(self, username: str, password_hash: str, role: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            if session.get(UserRow, username) is not None:
                raise ValueError(f"user {username!r} already exists")
            row = UserRow(
                username=username, password_hash=password_hash, role=role,
                disabled=False, created_at=utcnow(),
            )
            session.add(row)
            session.commit()
            return self._user_public(row)

    def get_user(self, username: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(UserRow, username)
            if row is None:
                return None
            return {**self._user_public(row), "password_hash": row.password_hash}

    def update_user(
        self,
        username: str,
        password_hash: str | None = None,
        role: str | None = None,
        disabled: bool | None = None,
    ) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(UserRow, username)
            if row is None:
                return None
            if password_hash is not None:
                row.password_hash = password_hash
            if role is not None:
                row.role = role
            if disabled is not None:
                row.disabled = disabled
            session.commit()
            return self._user_public(row)

    def delete_user(self, username: str) -> bool:
        with Session(self.engine) as session:
            row = session.get(UserRow, username)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    def list_users(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.scalars(select(UserRow).order_by(UserRow.username)).all()
            return [self._user_public(row) for row in rows]
