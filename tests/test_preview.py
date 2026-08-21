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


CHAIN = {
    "name": "preview demo",
    "steps": [
        {"id": "a", "name": "fetch", "plugin": "transform",
         "config": {"mode": "replace", "values": {"customer": "ACME", "total": 250}}},
        {"id": "b", "name": "shape", "plugin": "transform",
         "config": {"mode": "replace",
                    "values": {"who": "{{ steps.fetch.output.customer }}",
                               "greeting": "Hi {{ trigger.name }}"}}},
    ],
    "connections": [{"source": "a", "target": "b"}],
}


def seeded_client():
    client = make_client()
    process_id = client.post("/api/processes", json=CHAIN).json()["id"]
    run = client.post(f"/api/processes/{process_id}/run",
                      json={"draft": True, "trigger_input": {"name": "Rhia"}}).json()
    assert run["status"] == "succeeded"
    return client, process_id


# -- input visibility ---------------------------------------------------------------


def test_input_exposes_real_upstream_values():
    client, process_id = seeded_client()
    body = client.get(f"/api/processes/{process_id}/steps/b/input").json()

    assert body["trigger"] == {"name": "Rhia"}
    assert body["effective_input"] == {"customer": "ACME", "total": 250}

    source = body["sources"][0]
    assert source["label"] == "fetch"
    assert source["reference"] == "fetch"
    assert source["source_port"] == "main"
    assert source["has_data"] is True
    assert source["data"] == {"customer": "ACME", "total": 250}
    assert source["status"] == "succeeded"


def test_entry_step_input_is_the_trigger_payload():
    client, process_id = seeded_client()
    body = client.get(f"/api/processes/{process_id}/steps/a/input").json()
    assert body["sources"] == []
    assert body["effective_input"] == {"name": "Rhia"}


def test_input_without_any_run_still_lists_connected_sources():
    client = make_client()
    process_id = client.post("/api/processes", json=CHAIN).json()["id"]
    body = client.get(f"/api/processes/{process_id}/steps/b/input").json()
    assert body["run_id"] is None
    assert body["sources"][0]["has_data"] is False
    assert body["sources"][0]["data"] is None


def test_input_unknown_step_is_404():
    client, process_id = seeded_client()
    assert client.get(f"/api/processes/{process_id}/steps/ghost/input").status_code == 404


# -- output preview -----------------------------------------------------------------


def test_preview_executes_only_the_selected_step():
    client, process_id = seeded_client()
    body = client.post(f"/api/processes/{process_id}/steps/b/preview", json={}).json()

    assert body["status"] == "succeeded"
    # expressions resolved against the recorded run, not placeholders
    assert body["output"] == {"who": "ACME", "greeting": "Hi Rhia"}
    assert body["resolved_config"]["values"]["who"] == "ACME"
    assert body["input"] == {"customer": "ACME", "total": 250}
    assert body["duration_ms"] is not None


def test_preview_does_not_touch_run_history():
    client, process_id = seeded_client()
    before = client.get(f"/api/processes/{process_id}/runs").json()
    client.post(f"/api/processes/{process_id}/steps/b/preview", json={})
    after = client.get(f"/api/processes/{process_id}/runs").json()
    assert [entry["id"] for entry in before] == [entry["id"] for entry in after]


def test_preview_reports_step_failure_without_raising():
    client = make_client()
    definition = {
        "name": "bad expression",
        "steps": [{"id": "solo", "name": "solo", "plugin": "transform",
                   "config": {"values": {"x": "{{ steps.nope.output.y }}"}}}],
        "connections": [],
    }
    process_id = client.post("/api/processes", json=definition).json()["id"]
    body = client.post(f"/api/processes/{process_id}/steps/solo/preview", json={}).json()
    assert body["status"] == "failed"
    assert "cannot resolve" in body["error"]


def test_preview_of_unknown_step_is_422():
    client, process_id = seeded_client()
    response = client.post(f"/api/processes/{process_id}/steps/ghost/preview", json={})
    assert response.status_code == 422


def test_preview_can_pin_an_older_run():
    client, process_id = seeded_client()
    first = client.get(f"/api/processes/{process_id}/runs").json()[0]["id"]
    client.post(f"/api/processes/{process_id}/run",
                json={"draft": True, "trigger_input": {"name": "Later"}})

    latest = client.post(f"/api/processes/{process_id}/steps/b/preview", json={}).json()
    assert latest["output"]["greeting"] == "Hi Later"

    pinned = client.post(f"/api/processes/{process_id}/steps/b/preview", json={"run_id": first}).json()
    assert pinned["output"]["greeting"] == "Hi Rhia"
    assert pinned["based_on_run"] == first
