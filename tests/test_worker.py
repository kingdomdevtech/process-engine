"""Queue mode: background runs executed by worker processes (worker.py).

The first tests call ``run_job`` in-process to keep them fast and
deterministic; the spawn tests then prove the job really crosses a process
boundary (picklable payload, environment-driven ``init_worker``, shared
database as the coordination layer).
"""

import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor

from fastapi.testclient import TestClient

from process_engine import worker
from process_engine.api import create_app
from process_engine.models import (
    Connection,
    ProcessDefinition,
    ProcessInstance,
    RunStatus,
    Step,
    new_id,
)
from process_engine.registry import PluginRegistry
from process_engine.storage import Database


def seed(tmp_path, monkeypatch):
    """A file-backed database (shareable across processes) and a definition."""
    url = f"sqlite:///{(tmp_path / 'queue.db').as_posix()}"
    monkeypatch.setenv("PROCESS_ENGINE_DB_URL", url)
    definition = ProcessDefinition(
        name="Queued",
        steps=[
            Step(id="set", plugin="transform", config={"values": {"msg": "hi"}}),
            Step(id="log", plugin="log", config={"message": "{{ steps.set.output.msg }}"}),
        ],
        connections=[Connection(source="set", target="log")],
    )
    return Database(url), definition


def job_for(db, definition, trigger_input=None):
    """What api._launch_background enqueues: a placeholder row plus the payload."""
    rid = new_id()
    db.save_instance(
        ProcessInstance(
            id=rid,
            process_id=definition.id,
            process_version=definition.version,
            status=RunStatus.PENDING,
            trigger_input=trigger_input,
            variables=dict(definition.variables),
        )
    )
    return {
        "definition": definition.model_dump(mode="json"),
        "run_id": rid,
        "resume": False,
        "trigger_input": trigger_input,
        "variables": None,
    }


def test_run_job_executes_and_persists(tmp_path, monkeypatch):
    db, definition = seed(tmp_path, monkeypatch)
    worker.init_worker()  # what the pool initializer does, here in-process
    job = job_for(db, definition)

    assert worker.run_job(job) == "succeeded"

    stored = db.get_instance(job["run_id"])
    assert stored.status == RunStatus.SUCCEEDED
    assert [run.status for run in stored.step_runs] == [RunStatus.SUCCEEDED] * 2
    assert stored.started_at is not None and stored.finished_at is not None


def test_cancel_signal_wins_before_the_job_starts(tmp_path, monkeypatch):
    db, definition = seed(tmp_path, monkeypatch)
    worker.init_worker()
    job = job_for(db, definition)
    db.set_run_signal(job["run_id"], "cancel")  # cancelled while still queued

    assert worker.run_job(job) == "cancelled"

    stored = db.get_instance(job["run_id"])
    assert stored.status == RunStatus.CANCELLED
    assert all(run.status == RunStatus.SKIPPED for run in stored.step_runs)
    assert db.get_run_signal(job["run_id"]) is None  # cleared once the run settled


def test_invalid_definition_marks_the_placeholder_failed(tmp_path, monkeypatch):
    db, _ = seed(tmp_path, monkeypatch)
    worker.init_worker()
    broken = ProcessDefinition(name="Broken", steps=[Step(id="x", plugin="does_not_exist")])
    job = job_for(db, broken)

    assert worker.run_job(job) == "failed"

    stored = db.get_instance(job["run_id"])
    assert stored.status == RunStatus.FAILED  # not PENDING: never re-dispatched forever
    assert "does_not_exist" in stored.error


def test_job_executes_in_a_spawned_worker_process(tmp_path, monkeypatch):
    db, definition = seed(tmp_path, monkeypatch)
    job = job_for(db, definition, trigger_input={"who": "queue"})

    with ProcessPoolExecutor(
        max_workers=1,
        initializer=worker.init_worker,
        mp_context=multiprocessing.get_context("spawn"),
    ) as pool:
        assert pool.submit(worker.run_job, job).result(timeout=120) == "succeeded"

    stored = db.get_instance(job["run_id"])
    assert stored.status == RunStatus.SUCCEEDED
    assert stored.trigger_input == {"who": "queue"}


def test_api_queue_mode_runs_in_background_worker(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'queue.db').as_posix()}"
    monkeypatch.setenv("PROCESS_ENGINE_DB_URL", url)
    monkeypatch.setenv("PROCESS_ENGINE_RUN_WORKERS", "1")
    registry = PluginRegistry()
    registry.load_builtins()
    app = create_app(db=Database(url), registry=registry, auth_token="t")

    with TestClient(app) as client:  # lifespan owns the worker pool's shutdown
        client.headers.update({"Authorization": "Bearer t"})
        created = client.post(
            "/api/processes",
            json={
                "name": "Queued",
                "steps": [{"id": "set", "plugin": "transform", "config": {"values": {"msg": "hi"}}}],
            },
        ).json()
        assert client.post(f"/api/processes/{created['id']}/publish").status_code == 200

        started = client.post(f"/api/processes/{created['id']}/run", json={"background": True}).json()
        # the run is visible from the moment it is queued (PENDING placeholder)
        assert client.get(f"/api/runs/{started['id']}").status_code == 200

        for _ in range(300):  # first spawn on Windows takes a moment
            run = client.get(f"/api/runs/{started['id']}").json()
            if run["status"] not in ("pending", "running"):
                break
            time.sleep(0.1)
        assert run["status"] == "succeeded", run.get("error")
        assert run["step_runs"][0]["outputs"]["main"] == {"msg": "hi"}
