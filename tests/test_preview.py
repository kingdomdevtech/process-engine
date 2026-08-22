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


def seeded_client(engine_host):
    """A client whose process has one recorded run to preview against."""
    client = make_client()
    process_id = client.post("/api/processes", json=CHAIN).json()["id"]
    run = engine_host.run(client, process_id, draft=True, trigger_input={"name": "Rhia"})
    assert run["status"] == "succeeded"
    return client, process_id


# -- input visibility ---------------------------------------------------------------


def test_input_exposes_real_upstream_values(engine_host):
    client, process_id = seeded_client(engine_host)
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


def test_entry_step_input_is_the_trigger_payload(engine_host):
    client, process_id = seeded_client(engine_host)
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


def test_input_unknown_step_is_404(engine_host):
    client, process_id = seeded_client(engine_host)
    assert client.get(f"/api/processes/{process_id}/steps/ghost/input").status_code == 404


# -- output preview -----------------------------------------------------------------


def test_preview_executes_only_the_selected_step(engine_host):
    client, process_id = seeded_client(engine_host)
    body = engine_host.preview(client, process_id, "b")

    assert body["state"] == "done"
    assert body["status"] == "succeeded"
    # expressions resolved against the recorded run, not placeholders
    assert body["output"] == {"who": "ACME", "greeting": "Hi Rhia"}
    assert body["resolved_config"]["values"]["who"] == "ACME"
    assert body["input"] == {"customer": "ACME", "total": 250}
    assert body["duration_ms"] is not None


def test_preview_is_a_request_with_a_reply_to_collect(engine_host):
    """The POST cannot answer: nothing executes in the API process.

    So it 202s with a poll URL and says whether any engine is listening — that
    is the difference between "wait a moment" and "wait forever".
    """
    client, process_id = seeded_client(engine_host)
    accepted = client.post(f"/api/processes/{process_id}/steps/b/preview", json={})
    assert accepted.status_code == 202
    queued = accepted.json()
    assert queued["state"] == "queued"
    assert queued["workers_online"] == 0  # nobody has heartbeat in this test
    preview_id = queued["preview_id"]

    # polling before an engine has claimed it repeats the same waiting answer
    assert client.get(f"/api/processes/{process_id}/previews/{preview_id}").json()["state"] == "queued"

    engine_host.drain(client)
    answered = client.get(f"/api/processes/{process_id}/previews/{preview_id}").json()
    assert answered["state"] == "done"
    assert answered["output"] == {"who": "ACME", "greeting": "Hi Rhia"}
    # collected once; the reply is not left lying around to be re-executed
    assert client.get(f"/api/processes/{process_id}/previews/{preview_id}").status_code == 404


def test_preview_does_not_touch_run_history(engine_host):
    client, process_id = seeded_client(engine_host)
    before = client.get(f"/api/processes/{process_id}/runs").json()
    engine_host.preview(client, process_id, "b")
    after = client.get(f"/api/processes/{process_id}/runs").json()
    assert [entry["id"] for entry in before] == [entry["id"] for entry in after]


def test_preview_reports_step_failure_without_raising(engine_host):
    client = make_client()
    definition = {
        "name": "bad expression",
        "steps": [{"id": "solo", "name": "solo", "plugin": "transform",
                   "config": {"values": {"x": "{{ steps.nope.output.y }}"}}}],
        "connections": [],
    }
    process_id = client.post("/api/processes", json=definition).json()["id"]
    body = engine_host.preview(client, process_id, "solo")
    assert body["status"] == "failed"
    assert "cannot resolve" in body["error"]


def test_preview_of_unknown_step_is_422(engine_host):
    client, process_id = seeded_client(engine_host)
    response = client.post(f"/api/processes/{process_id}/steps/ghost/preview", json={})
    assert response.status_code == 422


def test_preview_can_pin_an_older_run(engine_host):
    client, process_id = seeded_client(engine_host)
    first = client.get(f"/api/processes/{process_id}/runs").json()[0]["id"]
    engine_host.run(client, process_id, draft=True, trigger_input={"name": "Later"})

    latest = engine_host.preview(client, process_id, "b")
    assert latest["output"]["greeting"] == "Hi Later"

    pinned = engine_host.preview(client, process_id, "b", run_id=first)
    assert pinned["output"]["greeting"] == "Hi Rhia"
    assert pinned["based_on_run"] == first
