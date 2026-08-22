"""Shared scaffolding: an engine host, in this process.

The designer's API executes nothing. Asking it for a run publishes a job to the
database and answers with a PENDING instance; asking for a step preview answers
202 and a poll URL. So a test that wants a *finished* run has to do what the
deployment does — let an engine host claim the job.

That is what ``engine_host`` is. It drives the same code path ``worker.serve``
does (``claim_job`` → ``execute_claimed``), against the test's own ``Database``
object, which is what makes an in-memory SQLite work: a real worker process
would build its own connection from the environment and see an empty database.

It reads that object off ``client.db``, and the relay off ``client.notifier`` if
the test injected one — each test module's ``make_client`` attaches them, since
run notifications are sent by whoever executed the run, which is this host and
not the API.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from process_engine import worker

WORKER_ID = "test-engine:0"


class EngineHost:
    """Claims and executes what the API queued, like a worker on another machine."""

    def drain(self, client: TestClient, limit: int = 100) -> list[str]:
        """Execute every job waiting in the queue; returns each one's outcome."""
        db = client.db
        worker.init_worker(db, notifier=getattr(client, "notifier", None))
        outcomes: list[str] = []
        while len(outcomes) < limit:
            job = db.claim_job(WORKER_ID, lease_seconds=60)
            if job is None:
                return outcomes
            outcomes.append(worker.execute_claimed(job, WORKER_ID))
        raise AssertionError(f"the queue was still handing out work after {limit} jobs")

    def run(self, client: TestClient, process_id: str, **body: Any) -> dict[str, Any]:
        """Ask for a run, execute it here, and return the finished run document."""
        queued = client.post(f"/api/processes/{process_id}/run", json=body)
        assert queued.status_code == 200, queued.text
        run_id = queued.json()["id"]
        self.drain(client)
        return client.get(f"/api/runs/{run_id}").json()

    def preview(self, client: TestClient, process_id: str, step_id: str, **body: Any) -> dict[str, Any]:
        """Ask for a step preview, execute it here, and collect the answer."""
        queued = client.post(f"/api/processes/{process_id}/steps/{step_id}/preview", json=body)
        assert queued.status_code == 202, queued.text
        preview_id = queued.json()["preview_id"]
        self.drain(client)
        return client.get(f"/api/processes/{process_id}/previews/{preview_id}").json()


@pytest.fixture
def engine_host() -> EngineHost:
    return EngineHost()
