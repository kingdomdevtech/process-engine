from fastapi.testclient import TestClient

from process_engine_api import create_app
from process_engine_core.registry import spec_registry
from process_engine_core.storage import Database

TOKEN = "test-token"


def make_client() -> TestClient:
    db = Database("sqlite://")
    client = TestClient(create_app(db=db, registry=spec_registry(), auth_token=TOKEN))
    client.db = db  # what the engine_host fixture claims this test's jobs from
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return client


DEFINITION = {
    "name": "Demo",
    "steps": [
        {"id": "set", "plugin": "transform", "config": {"values": {"msg": "hi"}}},
        {"id": "log", "plugin": "log", "config": {"message": "{{ steps.set.output.msg }}"}},
    ],
    "connections": [{"source": "set", "target": "log"}],
}


def test_api_requires_auth():
    client = make_client()
    anonymous_headers = {"Authorization": ""}
    assert client.get("/api/plugins", headers=anonymous_headers).status_code == 401
    assert client.get("/api/plugins", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/plugins").status_code == 200  # with the real token


def test_health_needs_no_credential():
    """The container's HEALTHCHECK and any load balancer in front of it poll
    this, and neither holds a token. It answers liveness only — what the
    installation is doing is /api/queue, behind the bearer token."""
    response = make_client().get("/api/health", headers={"Authorization": ""})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_plugins_endpoint_feeds_the_palette():
    response = make_client().get("/api/plugins")
    assert response.status_code == 200
    keys = {plugin["key"] for plugin in response.json()}
    assert {"http_request", "condition", "transform", "delay", "log", "for_each"} <= keys
    assert all("config_schema" in plugin for plugin in response.json())


def test_workspace_endpoint_reports_the_file_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("PROCESS_ENGINE_WORK_DIR", str(tmp_path))
    client = make_client()

    assert client.get("/api/workspace", headers={"Authorization": ""}).status_code == 401
    info = client.get("/api/workspace").json()
    assert info["path"] == str(tmp_path.resolve())
    assert info["env_var"] == "PROCESS_ENGINE_WORK_DIR"
    assert info["configured"] is True and info["exists"] is True


def test_handbooks_are_served_at_help(tmp_path, monkeypatch):
    """The designer's guided tour links the written walkthrough, so it has to
    be reachable from the same origin — and without a token, like the login
    page: these documents describe the product, not this installation."""
    (tmp_path / "guided-tour.html").write_text("<h1>tour</h1>", encoding="utf-8")
    monkeypatch.setenv("PROCESS_ENGINE_DOCS_DIR", str(tmp_path))
    client = make_client()

    page = client.get("/help/guided-tour.html", headers={"Authorization": ""})
    assert page.status_code == 200
    assert "tour" in page.text
    assert client.get("/help/nothing-here.html").status_code == 404


def test_the_spa_fallback_never_answers_for_the_api(tmp_path, monkeypatch):
    """A single-origin deployment serves the designer from a catch-all route.
    It is registered last, so an unknown /api path would otherwise come back as
    the index page with a 200 — a mistyped endpoint that looks like it worked,
    and a health check that passes without the route existing."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    monkeypatch.setenv("PROCESS_ENGINE_DESIGNER_DIST", str(dist))
    client = make_client()

    assert client.get("/app/settings").status_code == 200  # a client-side route
    assert client.get("/api/health").json() == {"status": "ok"}  # a real route
    missing = client.get("/api/not-a-route")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/json")


def test_full_lifecycle(engine_host):
    client = make_client()

    created = client.post("/api/processes", json=DEFINITION).json()
    process_id = created["id"]

    # nothing published yet -> running the published version is a conflict
    assert client.post(f"/api/processes/{process_id}/run", json={}).status_code == 409

    # but the draft runs
    draft_run = engine_host.run(client, process_id, draft=True)
    assert draft_run["status"] == "succeeded"

    published = client.post(f"/api/processes/{process_id}/publish").json()
    assert published["version"] == 1
    assert published["status"] == "published"

    run = engine_host.run(client, process_id)
    assert run["status"] == "succeeded"
    assert run["process_version"] == 1

    runs = client.get(f"/api/processes/{process_id}/runs").json()
    assert len(runs) == 2

    detail = client.get(f"/api/runs/{run['id']}").json()
    assert detail["step_runs"][1]["outputs"]["main"] == {"msg": "hi"}


def test_a_run_is_queued_not_executed_here():
    """The reply to Run is a PENDING instance, not a finished one.

    Nothing executes in this process, so the run exists as a row the moment it
    is asked for and stays PENDING until an engine host claims it. The designer
    needs no special case for that: it polls whatever it gets back.
    """
    client = make_client()
    process_id = client.post("/api/processes", json=DEFINITION).json()["id"]

    queued = client.post(f"/api/processes/{process_id}/run", json={"draft": True}).json()
    assert queued["status"] == "pending"
    assert queued["step_runs"] == []
    # visible in the run list straight away, so a queued run is never invisible
    assert [entry["id"] for entry in client.get(f"/api/processes/{process_id}/runs").json()] == [queued["id"]]
    assert client.get("/api/queue").json() == {"mode": "database", "workers_online": 0, "queued": 1}


def test_validation_endpoint_reports_issues_with_step_ids():
    client = make_client()
    bad = {
        "name": "Broken",
        "steps": [{"id": "x", "plugin": "ghost_plugin"}],
        "connections": [],
    }
    process_id = client.post("/api/processes", json=bad).json()["id"]
    body = client.post(f"/api/processes/{process_id}/validate").json()
    assert any("ghost_plugin" in issue for issue in body["issues"])
    assert any(entry.get("step_id") == "x" for entry in body["detailed"])
    # publishing a broken definition is refused
    assert client.post(f"/api/processes/{process_id}/publish").status_code == 422


def test_webhook_fires_published_process_without_bearer_token(engine_host):
    with make_client() as client:
        definition = {**DEFINITION, "triggers": [{"type": "webhook", "path": "hooky"}]}
        process_id = client.post("/api/processes", json=definition).json()["id"]
        client.post(f"/api/processes/{process_id}/publish")

        # a wrong bearer token proves /api/hooks/* needs no auth (capability URL)
        response = client.post("/api/hooks/hooky", json={"total": 9},
                               headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 200
        accepted = response.json()
        assert accepted["process_id"] == process_id

        engine_host.drain(client)
        run = client.get(f"/api/runs/{accepted['run_id']}").json()
        assert run["status"] == "succeeded"
        assert run["trigger_input"] == {"total": 9}

        # unknown slug -> 404
        assert client.post("/api/hooks/nope", json={}).status_code == 404


def test_the_background_flag_is_accepted_and_makes_no_difference(engine_host):
    """Every run is queued now, so an older client asking for a background one
    gets the same answer as everybody else rather than a 422."""
    with make_client() as client:
        process_id = client.post("/api/processes", json=DEFINITION).json()["id"]
        accepted = client.post(f"/api/processes/{process_id}/run",
                               json={"draft": True, "background": True}).json()
        assert accepted["status"] == "pending"
        engine_host.drain(client)
        assert client.get(f"/api/runs/{accepted['id']}").json()["status"] == "succeeded"


def test_secrets_are_write_only_and_usable_in_runs(engine_host):
    client = make_client()
    assert client.put("/api/secrets/api_key", json={"value": "s3cr3t"}).status_code == 200
    assert client.get("/api/secrets").json() == ["api_key"]

    definition = {
        "name": "uses secret",
        "steps": [{"id": "set", "plugin": "transform",
                   "config": {"values": {"key": "{{ secrets.api_key }}"}}}],
        "connections": [],
    }
    process_id = client.post("/api/processes", json=definition).json()["id"]
    run = engine_host.run(client, process_id, draft=True)
    assert run["status"] == "succeeded"
    assert run["step_runs"][0]["outputs"]["main"] == {"key": "s3cr3t"}

    assert client.delete("/api/secrets/api_key").json() == {"deleted": True}
    assert client.get("/api/secrets").json() == []


def test_run_control_endpoints_reject_bad_states(engine_host):
    client = make_client()
    # a run id nobody can produce is simply not found, whatever the verb
    assert client.post("/api/runs/nonexistent/cancel").status_code == 404
    assert client.post("/api/runs/nonexistent/pause").status_code == 404

    process_id = client.post("/api/processes", json=DEFINITION).json()["id"]
    run = engine_host.run(client, process_id, draft=True)
    # a finished run cannot be resumed, and is no longer active to pause
    assert client.post(f"/api/runs/{run['id']}/resume").status_code == 409
    assert client.post(f"/api/runs/{run['id']}/pause").status_code == 409
