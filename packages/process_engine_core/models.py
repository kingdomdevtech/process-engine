"""Core domain models.

A ProcessDefinition is the design-time document: Steps wired together by
Connections. A ProcessInstance is one run of a definition; every executed
step is recorded as a StepRun.

Definitions are immutable once published — a running instance always
finishes on the version it started with.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RetryPolicy(BaseModel):
    """Per-step retry applied by the engine around Plugin.execute."""

    max_attempts: int = Field(default=1, ge=1)
    backoff_seconds: float = Field(default=1.0, ge=0)  # doubled after each failed attempt


class Position(BaseModel):
    """Designer-only canvas coordinates; the engine ignores them."""

    x: float = 0
    y: float = 0


class Viewport(BaseModel):
    """Designer-only canvas viewport; the engine ignores it."""

    x: float = 0
    y: float = 0
    zoom: float = 1.25


class Step(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str = ""  # unique display name, usable in expressions instead of the id
    plugin: str  # key of a registered Plugin
    config: dict[str, Any] = Field(default_factory=dict)  # may contain {{ expressions }}
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    timeout_seconds: float | None = None
    position: Position = Field(default_factory=Position)


class Connection(BaseModel):
    id: str = Field(default_factory=new_id)
    source: str  # step id
    source_port: str = "main"
    target: str  # step id
    target_port: str = "main"


class ProcessStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Trigger(BaseModel):
    """How a published process starts besides a manual run.

    * ``schedule``: fires on a 5-field cron expression (engine-side scheduler).
    * ``webhook``: fires on ``POST /api/hooks/{path}`` with the request body as
      trigger input; ``path`` defaults to the process id when empty.
    """

    id: str = Field(default_factory=new_id)
    type: Literal["schedule", "webhook"]
    enabled: bool = True
    cron: str = ""  # schedule only, e.g. "*/15 * * * *"
    path: str = ""  # webhook only; letters/digits/-/_
    description: str = ""


class NotificationEvent(StrEnum):
    """A moment in a run somebody may want an email about.

    ``COMPLETED`` means "however it turns out": a run reports under the most
    specific event subscribed to, so asking for both ``SUCCEEDED`` and
    ``COMPLETED`` is still one email per run (see ``notifications.event_for``).
    """

    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    COMPLETED = "completed"


class NotificationSettings(BaseModel):
    """Who to email about this process's runs, and when.

    Off by default: with no events selected nothing is ever sent, whatever the
    recipient list says. The mail relay itself is deployment-wide and lives in
    ``notifications.MailSettings`` — this is only the per-process subscription.
    """

    events: list[NotificationEvent] = Field(default_factory=list)
    notify_creator: bool = True  # applies to ProcessDefinition.created_by
    recipients: list[str] = Field(default_factory=list)  # additional addresses


class ProcessDefinition(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str = "Untitled process"
    folder: str = ""  # display grouping in the dashboard; "" means Uncategorized
    version: int = 1
    status: ProcessStatus = ProcessStatus.DRAFT
    created_by: str = ""  # username of whoever created it; server-set, never client-set
    # usernames this process is shared with. Server-set via /share, never taken
    # from a PUT: the designer round-trips a definition it has no business
    # editing access on. Admins see every process regardless of this list.
    shared_with: list[str] = Field(default_factory=list)
    viewport: Viewport = Field(default_factory=Viewport)
    steps: list[Step] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    triggers: list[Trigger] = Field(default_factory=list)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    variables: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class StepRun(BaseModel):
    step_id: str
    step_name: str = ""
    plugin: str = ""
    status: RunStatus = RunStatus.PENDING
    attempts: int = 0
    input: Any = None
    outputs: dict[str, Any] = Field(default_factory=dict)  # port -> emitted data
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: float | None = None  # wall clock of the whole step, retries and backoff included


class ProcessInstance(BaseModel):
    id: str = Field(default_factory=new_id)
    process_id: str
    process_version: int
    status: RunStatus = RunStatus.PENDING
    parent_run_id: str | None = None  # set when started as a for_each sub-process
    trigger_input: Any = None
    variables: dict[str, Any] = Field(default_factory=dict)
    step_runs: list[StepRun] = Field(default_factory=list)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
