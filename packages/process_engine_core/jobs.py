"""Publishing work to the queue — the one thing both tiers write.

The designer's API cannot execute anything, so asking for a run means writing a
row: the ``job_queue`` table *is* the channel between the Linux container and
the Windows engine hosts. An engine host publishes too, when its own scheduler
fires a cron or a person resumes a paused run from the designer, so the payloads
live here rather than in either half — a claimed job has to mean the same thing
whoever wrote it.

Three shapes, all claimed by the same worker loop:

* **a fresh run** — a PENDING placeholder instance first, then the job. The
  placeholder is what makes a queued run visible in the run list immediately
  instead of appearing only once some worker picks it up, and it is what the
  restart sweep re-dispatches if the row outlives the job.
* **a resume** — the instance already exists (paused, or interrupted by a
  restart); the worker replays its recorded steps rather than re-executing them.
* **a preview** — request/reply rather than fire-and-forget: somebody is
  watching a spinner, so the answer goes back into the job row for the API to
  collect, not into the run history.

Every payload carries a *snapshot* of the definition taken now, so editing the
draft while the job waits cannot change what runs.
"""

from __future__ import annotations

from typing import Any

from .models import ProcessDefinition, ProcessInstance, RunStatus, new_id
from .storage import Database


def enqueue_run(
    db: Database,
    definition: ProcessDefinition,
    trigger_input: Any = None,
    variables: dict[str, Any] | None = None,
) -> str:
    """Publish a fresh run: PENDING placeholder, then the job. Returns the run id."""
    run_id = new_id()
    db.save_instance(
        ProcessInstance(
            id=run_id,
            process_id=definition.id,
            process_version=definition.version,
            status=RunStatus.PENDING,
            trigger_input=trigger_input,
            variables={**definition.variables, **(variables or {})},
        )
    )
    db.enqueue_job(run_id, _run_payload(definition, run_id, resume=False,
                                        trigger_input=trigger_input, variables=variables))
    return run_id


def enqueue_resume(db: Database, definition: ProcessDefinition, instance: ProcessInstance) -> str:
    """Publish a resume of an existing run. Returns its (unchanged) run id.

    No placeholder: the instance is already stored, and it is what the worker
    replays from — SUCCEEDED steps come back from their recorded outputs rather
    than being executed again.
    """
    db.enqueue_job(instance.id, _run_payload(definition, instance.id, resume=True))
    return instance.id


def enqueue_preview(
    db: Database,
    definition: ProcessDefinition,
    step_id: str,
    *,
    run_id: str | None = None,
    variables: dict[str, Any] | None = None,
    trigger_input: Any = None,
) -> str:
    """Publish a single-step preview. Returns the id to poll for the answer."""
    preview_id = new_id()
    db.enqueue_job(
        preview_id,
        {
            "definition": definition.model_dump(mode="json"),
            "step_id": step_id,
            # which recorded run supplies the upstream data, pinned by id so both
            # sides agree on "based on" even as newer runs land in between
            "run_id": run_id,
            "variables": variables or {},
            "trigger_input": trigger_input,
        },
        kind="preview",
    )
    return preview_id


def _run_payload(
    definition: ProcessDefinition,
    run_id: str,
    *,
    resume: bool,
    trigger_input: Any = None,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "definition": definition.model_dump(mode="json"),
        "run_id": run_id,
        "resume": resume,
        "trigger_input": trigger_input,
        "variables": variables,
    }
