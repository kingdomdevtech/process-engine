import time

from fastapi.testclient import TestClient

from process_engine.api import create_app
from process_engine.registry import PluginRegistry
from process_engine.storage import Database

TOKEN = "test-token"


def make_client() -> TestClient:
    registry = PluginRegistry()
    registry.load_builtins()
    client = TestClient(create_app(db=Database("sqlite://"), registry=registry, auth_token=TOKEN))
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


def wait_for_terminal(client: TestClient, run_id: str, tries: int = 50) -> dict:
    for _ in range(tries):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("succeeded", "failed", "cancelled", "paused"):
            return run
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} never finished: {run}")


def test_api_requires_auth():
    client = make_client()
    anonymous_headers = {"Authorization": ""}
    assert client.get("/api/plugins", headers=anonymous_headers).status_code == 401
    assert client.get("/api/plugins", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/plugins").status_code == 200  # with the real token


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


def test_full_lifecycle():
    client = make_client()

    created = client.post("/api/processes", json=DEFINITION).json()
    process_id = created["id"]

    # nothing published yet -> running the published version is a conflict
    assert client.post(f"/api/processes/{process_id}/run", json={}).status_code == 409

    # but the draft runs
    draft_run = client.post(f"/api/processes/{process_id}/run", json={"draft": True}).json()
    assert draft_run["status"] == "succeeded"

    published = client.post(f"/api/processes/{process_id}/publish").json()
    assert published["version"] == 1
    assert published["status"] == "published"

    run = client.post(f"/api/processes/{process_id}/run", json={}).json()
    assert run["status"] == "succeeded"
    assert run["process_version"] == 1

    runs = client.get(f"/api/processes/{process_id}/runs").json()
    assert len(runs) == 2

    detail = client.get(f"/api/runs/{run['id']}").json()
    assert detail["step_runs"][1]["outputs"]["main"] == {"msg": "hi"}


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


def test_webhook_fires_published_process_without_bearer_token():
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

        run = wait_for_terminal(client, accepted["run_id"])
        assert run["status"] == "succeeded"
        assert run["trigger_input"] == {"total": 9}

        # unknown slug -> 404
        assert client.post("/api/hooks/nope", json={}).status_code == 404


def test_background_run_and_polling():
    with make_client() as client:
        process_id = client.post("/api/processes", json=DEFINITION).json()["id"]
        accepted = client.post(f"/api/processes/{process_id}/run",
                               json={"draft": True, "background": True}).json()
        assert accepted["background"] is True
        run = wait_for_terminal(client, accepted["id"])
        assert run["status"] == "succeeded"


def test_secrets_are_write_only_and_usable_in_runs():
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
    run = client.post(f"/api/processes/{process_id}/run", json={"draft": True}).json()
    assert run["status"] == "succeeded"
    assert run["step_runs"][0]["outputs"]["main"] == {"key": "s3cr3t"}

    assert client.delete("/api/secrets/api_key").json() == {"deleted": True}
    assert client.get("/api/secrets").json() == []


def test_run_control_endpoints_reject_bad_states():
    client = make_client()
    # a run id nobody can produce is simply not found, whatever the verb
    assert client.post("/api/runs/nonexistent/cancel").status_code == 404
    assert client.post("/api/runs/nonexistent/pause").status_code == 404

    process_id = client.post("/api/processes", json=DEFINITION).json()["id"]
    run = client.post(f"/api/processes/{process_id}/run", json={"draft": True}).json()
    # a finished run cannot be resumed, and is no longer active to pause
    assert client.post(f"/api/runs/{run['id']}/resume").status_code == 409
    assert client.post(f"/api/runs/{run['id']}/pause").status_code == 409
