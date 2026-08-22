"""The engine host: claiming work from the queue and running it (worker.py).

There is one execution shape now. The designer's API writes every job — runs,
resumes and single-step previews alike — to the ``job_queue`` table, and engine
hosts elsewhere claim it. So these tests come at ``worker.py`` from both sides:
its functions called directly (fast and deterministic), the real ``serve`` loop
in a thread, and finally a *fresh interpreter* with the API and the whole web
stack made unimportable — which is the invariant the two-host deployment rests
on.
"""

import subprocess
import sys
import threading
import time
from datetime import timedelta

from fastapi.testclient import TestClient

from process_engine import worker
from process_engine_api import create_app
from process_engine_core.jobs import enqueue_run
from process_engine_core.models import (
    Connection,
    ProcessDefinition,
    RunStatus,
    Step,
    Trigger,
    utcnow,
)
from process_engine_core.registry import spec_registry
from process_engine_core.storage import Database

WORKER = "test-engine:0"


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


def claim_one(db, definition, trigger_input=None):
    """Publish a run the way the API does, then take it off the queue.

    Both halves of what an engine host sees: ``enqueue_run`` is the API's side of
    the boundary (placeholder instance + job row), ``claim_job`` is the lock that
    hands the job to exactly one worker.
    """
    run_id = enqueue_run(db, definition, trigger_input=trigger_input)
    job = db.claim_job(WORKER)
    assert job is not None and job["run_id"] == run_id
    return job


def test_run_job_executes_and_persists(tmp_path, monkeypatch):
    db, definition = seed(tmp_path, monkeypatch)
    worker.init_worker()  # what a worker does on start-up, here in-process
    job = claim_one(db, definition)

    assert worker.run_job(job) == "succeeded"

    stored = db.get_instance(job["run_id"])
    assert stored.status == RunStatus.SUCCEEDED
    assert [run.status for run in stored.step_runs] == [RunStatus.SUCCEEDED] * 2
    assert stored.started_at is not None and stored.finished_at is not None


def test_cancel_signal_wins_before_the_job_starts(tmp_path, monkeypatch):
    db, definition = seed(tmp_path, monkeypatch)
    worker.init_worker()
    job = claim_one(db, definition)
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
    job = claim_one(db, broken)

    assert worker.run_job(job) == "failed"

    stored = db.get_instance(job["run_id"])
    assert stored.status == RunStatus.FAILED  # not PENDING: never re-dispatched forever
    assert "does_not_exist" in stored.error


# -- the queue is the lock ---------------------------------------------------------


def test_claim_job_is_exclusive(tmp_path, monkeypatch):
    db, definition = seed(tmp_path, monkeypatch)
    run_id = enqueue_run(db, definition)

    first = db.claim_job("worker-a")
    second = db.claim_job("worker-b")

    assert first is not None and first["run_id"] == run_id
    assert second is None  # one job, claimed once


def test_serve_drains_queued_jobs(tmp_path, monkeypatch):
    db, definition = seed(tmp_path, monkeypatch)
    worker.init_worker()  # rebuild the module context against this test's database
    run_id = enqueue_run(db, definition)

    stop = threading.Event()
    loop = threading.Thread(target=worker.serve, kwargs={"stop": stop, "poll_seconds": 0.05})
    loop.start()
    try:
        stored = db.get_instance(run_id)
        for _ in range(200):
            stored = db.get_instance(run_id)
            if stored.status not in (RunStatus.PENDING, RunStatus.RUNNING):
                break
            time.sleep(0.05)
    finally:
        stop.set()
        loop.join(timeout=10)

    assert stored.status == RunStatus.SUCCEEDED
    assert db.claim_job("check") is None  # the job row is removed once the run settles


def test_claim_renewal_keeps_a_slow_job_from_being_stolen(tmp_path, monkeypatch):
    db, definition = seed(tmp_path, monkeypatch)
    run_id = enqueue_run(db, definition)

    db.claim_job("worker-a", lease_seconds=0.2)
    time.sleep(0.3)  # longer than the lease: without a renewal this is fair game
    db.touch_job(run_id)  # the worker holding it says it is still working

    assert db.claim_job("worker-b", lease_seconds=0.2) is None
    time.sleep(0.3)  # and once the renewals stop, the lease does lapse
    assert db.claim_job("worker-b", lease_seconds=0.2) is not None


# -- the API publishes; nothing executes there -------------------------------------


def api(tmp_path, monkeypatch):
    """The designer's API over a file-backed database. It executes nothing."""
    url = f"sqlite:///{(tmp_path / 'queue.db').as_posix()}"
    monkeypatch.setenv("PROCESS_ENGINE_DB_URL", url)
    db = Database(url)
    return db, create_app(db=db, registry=spec_registry(), auth_token="t")


def test_run_is_enqueued_for_external_workers(tmp_path, monkeypatch):
    """The Run button must reach a worker, or Windows-only steps are unusable."""
    db, app = api(tmp_path, monkeypatch)
    with TestClient(app) as client:
        client.headers.update({"Authorization": "Bearer t"})
        created = client.post(
            "/api/processes",
            json={
                "name": "Queued",
                "steps": [{"id": "set", "plugin": "transform", "config": {"values": {"msg": "hi"}}}],
            },
        ).json()
        assert client.post(f"/api/processes/{created['id']}/publish").status_code == 200

        run = client.post(f"/api/processes/{created['id']}/run", json={}).json()
        # visible from the moment it is queued (PENDING placeholder), and still
        # only queued: this process holds no engine to run it
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "pending"
        assert run["step_runs"] == []

        # a worker elsewhere claims the job from the shared database and runs it
        worker.init_worker()
        job = db.claim_job("worker-1")
        assert job is not None and job["run_id"] == run["id"]
        assert worker.run_job(job) == "succeeded"

    assert db.get_instance(run["id"]).status == RunStatus.SUCCEEDED
    assert db.claim_job("worker-1") is None  # settled: the row is gone


def test_queued_preview_is_answered_by_a_worker(tmp_path, monkeypatch):
    db, app = api(tmp_path, monkeypatch)
    with TestClient(app) as client:
        client.headers.update({"Authorization": "Bearer t"})
        created = client.post(
            "/api/processes",
            json={
                "name": "Preview",
                "steps": [{"id": "set", "plugin": "transform", "config": {"values": {"msg": "hi"}}}],
            },
        ).json()
        pid = created["id"]

        queued = client.post(f"/api/processes/{pid}/steps/set/preview", json={})
        assert queued.status_code == 202  # accepted, not answered
        preview_id = queued.json()["preview_id"]
        assert queued.json()["state"] == "queued"

        # nothing is listening yet, and the caller is told so rather than left guessing
        waiting = client.get(f"/api/processes/{pid}/previews/{preview_id}").json()
        assert waiting == {
            "state": "queued",
            "preview_id": preview_id,
            "worker": None,
            "workers_online": 0,
        }

        worker.init_worker()
        job = db.claim_job("worker-1")
        assert job is not None and job["kind"] == "preview"
        assert worker.preview_job(job) == "succeeded"

        answer = client.get(f"/api/processes/{pid}/previews/{preview_id}").json()
        assert answer["state"] == "done"
        assert answer["status"] == "succeeded"
        assert answer["output"] == {"msg": "hi"}

        # collected once: the reply is gone and cannot be re-run as fresh work
        assert client.get(f"/api/processes/{pid}/previews/{preview_id}").status_code == 404
        assert db.claim_job("worker-1", lease_seconds=0.0) is None


def test_a_finished_preview_reply_is_never_reclaimed_as_work(tmp_path, monkeypatch):
    """A settled row is an answer, not a job whose worker went quiet."""
    db, _ = seed(tmp_path, monkeypatch)
    db.enqueue_job("p1", {"step_id": "set"}, kind="preview")
    db.claim_job("worker-a", lease_seconds=0.0)
    db.complete_job("p1", {"status": "succeeded"})

    assert db.claim_job("worker-b", lease_seconds=0.0) is None
    assert db.get_job("p1")["result"] == {"status": "succeeded"}


def test_preview_of_a_broken_step_fails_without_a_round_trip(tmp_path, monkeypatch):
    db, app = api(tmp_path, monkeypatch)
    with TestClient(app) as client:
        client.headers.update({"Authorization": "Bearer t"})
        created = client.post("/api/processes", json={"name": "Preview", "steps": []}).json()

        response = client.post(f"/api/processes/{created['id']}/steps/nope/preview", json={})

        assert response.status_code == 422
        assert "nope" in response.json()["detail"]["issues"][0]
        assert db.count_queued_jobs() == 0  # never queued for a worker to discover


def test_queue_status_reports_whether_anyone_is_listening(tmp_path, monkeypatch):
    db, app = api(tmp_path, monkeypatch)
    with TestClient(app) as client:
        client.headers.update({"Authorization": "Bearer t"})

        assert client.get("/api/queue").json() == {"mode": "database", "workers_online": 0, "queued": 0}

        db.worker_heartbeat("win-host:123", "win-host")
        status = client.get("/api/queue").json()
        assert status["workers_online"] == 1
        assert [w["hostname"] for w in client.get("/api/workers").json()] == ["win-host"]

        db.remove_worker("win-host:123")  # a clean shutdown says so at once
        assert client.get("/api/queue").json()["workers_online"] == 0


def test_serve_answers_a_preview_from_the_queue(tmp_path, monkeypatch):
    """End to end through the real loop: claim, execute, reply, heartbeat."""
    db, definition = seed(tmp_path, monkeypatch)
    worker.init_worker()
    db.enqueue_job(
        "p1",
        {"definition": definition.model_dump(mode="json"), "step_id": "set", "run_id": None},
        kind="preview",
    )

    stop = threading.Event()
    loop = threading.Thread(target=worker.serve, kwargs={"stop": stop, "poll_seconds": 0.05})
    loop.start()
    try:
        for _ in range(200):
            job = db.get_job("p1")
            if job["status"] in ("done", "failed"):
                break
            time.sleep(0.05)
        assert db.list_workers(), "the loop must report itself as alive"
    finally:
        stop.set()
        loop.join(timeout=10)

    assert job["status"] == "done"
    assert job["result"]["output"] == {"msg": "hi"}
    assert db.list_workers() == []  # and stop reporting when it exits


# -- the engine host schedules for itself ------------------------------------------


def _publish_cron(db, name="Scheduled"):
    """A published process with a schedule trigger, armed to be due right now."""
    definition = ProcessDefinition(
        name=name,
        steps=[Step(id="set", plugin="transform", config={"values": {"msg": "hi"}})],
        triggers=[Trigger(type="schedule", cron="* * * * *")],
    )
    db.save_process(definition)
    db.publish_process(definition.id)
    return definition


def test_the_engine_host_fires_its_own_schedules(tmp_path, monkeypatch):
    """Automation must not depend on the designer's container being up."""
    db, _ = seed(tmp_path, monkeypatch)
    definition = _publish_cron(db)
    trigger_id = definition.triggers[0].id
    # a window that has just come due, so the first tick fires rather than arming
    db.arm_schedule(definition.id, trigger_id, utcnow() - timedelta(seconds=1))
    worker.init_worker()

    stop = threading.Event()
    loop = threading.Thread(target=worker.serve, kwargs={"stop": stop, "poll_seconds": 0.05})
    loop.start()
    try:
        run = None
        for _ in range(200):
            runs = db.list_instances(process_id=definition.id)
            if runs and runs[0]["status"] not in (RunStatus.PENDING.value, RunStatus.RUNNING.value):
                run = db.get_instance(runs[0]["id"])
                break
            time.sleep(0.05)
    finally:
        stop.set()
        loop.join(timeout=10)

    assert run is not None, "the cron never fired, or its run never executed"
    assert run.status == RunStatus.SUCCEEDED
    assert run.trigger_input["cron"] == "* * * * *"
    # the same worker claimed the run it enqueued — one queue, no special path
    assert db.schedule_due(definition.id, trigger_id) > utcnow()


def test_the_designer_api_leaves_scheduling_to_the_engine_hosts(tmp_path, monkeypatch):
    """Cron belongs to the hosts that can execute; the API starts no scheduler.

    Two schedulers would be safe — ``claim_schedule`` makes a firing happen once
    however many are watching — but a firing here would queue work nobody asked
    this container for, and hide the fact that it cannot run any of it.
    """
    db, app = api(tmp_path, monkeypatch)
    definition = _publish_cron(db)
    with TestClient(app):  # lifespan starts everything the API tier has
        time.sleep(0.3)
    assert db.schedule_due(definition.id, definition.triggers[0].id) is None
    assert db.count_queued_jobs() == 0


# -- the engine needs nothing but the database -------------------------------------

# Run in a fresh interpreter with the API and the whole web stack made
# unimportable. If the engine had grown a dependency on either, this raises
# instead of running the job.
STANDALONE = """
import sys

BLOCKED = ("process_engine_api", "fastapi", "uvicorn", "starlette")


class Blocker:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in BLOCKED:
            raise ImportError(f"{fullname} is not installed on an engine host")
        return None


sys.meta_path.insert(0, Blocker())

from process_engine import worker
from process_engine_core.storage import Database

db = Database(sys.argv[1])
worker.init_worker()
job = db.claim_job("standalone-engine")
print(worker.run_job(job))
"""


def test_the_engine_reaches_the_database_without_the_api(tmp_path, monkeypatch):
    """The engine host installs no web stack and talks to nobody but the database.

    This is the invariant the two-host deployment rests on: the engine
    distribution depends on ``process-engine-core`` and nothing else of ours, so
    a Windows engine needs neither FastAPI nor a running API to claim work and
    execute it. It also proves ``init_worker`` rebuilds the whole stack from
    environment variables alone, which is what lets a worker be another machine.
    """
    db, definition = seed(tmp_path, monkeypatch)
    run_id = enqueue_run(db, definition, trigger_input={"who": "nobody"})

    script = tmp_path / "standalone_engine.py"
    script.write_text(STANDALONE, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script), str(db.engine.url)],
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("succeeded"), result.stdout
    stored = db.get_instance(run_id)
    assert stored.status == RunStatus.SUCCEEDED
    assert stored.trigger_input == {"who": "nobody"}


# The mirror of the above, and the reason the container ships no engine: serve
# the palette, save a process and ask for a run with the *engine* distribution
# made unimportable. If the API had reached for an Engine, a plugin or the
# worker, this raises instead of queueing the job.
API_ONLY = """
import sys

BLOCKED = ("process_engine",)


class Blocker:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in BLOCKED:
            raise ImportError(f"{fullname} is not installed on the designer's host")
        return None


sys.meta_path.insert(0, Blocker())

try:  # the block has to be real, or this test passes without proving anything
    import process_engine
    raise SystemExit("the import blocker is not working")
except ImportError:
    pass

from fastapi.testclient import TestClient

from process_engine_api import create_app
from process_engine_core.registry import spec_registry
from process_engine_core.storage import Database

db = Database(sys.argv[1])
with TestClient(create_app(db=db, registry=spec_registry(), auth_token="t")) as client:
    client.headers.update({"Authorization": "Bearer t"})
    palette = client.get("/api/plugins").json()
    created = client.post("/api/processes", json={
        "name": "No engine here",
        "steps": [{"id": "set", "plugin": "transform", "config": {"values": {"msg": "hi"}}}],
    }).json()
    run = client.post(f"/api/processes/{created['id']}/run", json={"draft": True}).json()
    print(len(palette), run["status"], db.count_queued_jobs())
"""


def test_the_api_serves_and_queues_without_the_engine_installed(tmp_path, monkeypatch):
    """The designer's container installs core and the API — never the engine.

    That is what makes "execution happens on Windows" structural rather than a
    setting somebody could get wrong: there is no ``Engine``, no plugin
    implementation and no worker in that image to run a step with, even by
    accident. What is left still has to do the API's whole job — advertise the
    palette from the *specs*, store a definition, and publish a run to the queue.
    """
    db, _ = seed(tmp_path, monkeypatch)

    script = tmp_path / "api_only.py"
    script.write_text(API_ONLY, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script), str(db.engine.url)],
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    palette_size, status, queued = result.stdout.strip().splitlines()[-1].split()
    assert int(palette_size) >= 15  # the whole palette, generated from the specs
    assert status == "pending"  # queued for an engine host, not executed here
    assert int(queued) == 1
