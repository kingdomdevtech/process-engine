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
    "name": "Nightly report",
    "folder": "Finance",
    "variables": {"region": "eu"},
    "steps": [
        {"id": "set", "name": "Prepare", "plugin": "transform", "config": {"values": {"msg": "hi"}}},
        {
            "id": "log",
            "name": "Say it",
            "plugin": "log",
            "config": {"message": "{{ steps.set.output.msg }}"},
            "position": {"x": 120, "y": 40},
        },
    ],
    "connections": [{"source": "set", "target": "log"}],
    "triggers": [
        {"type": "schedule", "cron": "*/15 * * * *", "enabled": True},
        {"type": "webhook", "path": "nightly", "enabled": True},
    ],
}


def test_clone_copies_the_graph_into_a_new_unpublished_process():
    client = make_client()
    original = client.post("/api/processes", json=DEFINITION).json()
    client.post(f"/api/processes/{original['id']}/publish")

    clone = client.post(f"/api/processes/{original['id']}/clone").json()

    assert clone["id"] != original["id"]
    assert clone["name"] == "Nightly report (copy)"
    assert clone["folder"] == "Finance"  # stays where the original lives
    assert clone["variables"] == {"region": "eu"}
    assert clone["status"] == "draft"
    assert clone["version"] == 1
    # step and connection ids are preserved so {{ steps.<id> }} keeps resolving
    assert [step["id"] for step in clone["steps"]] == ["set", "log"]
    assert clone["steps"][1]["config"] == {"message": "{{ steps.set.output.msg }}"}
    assert clone["steps"][1]["position"] == {"x": 120, "y": 40}
    assert clone["connections"][0]["source"] == "set"

    listing = {entry["id"]: entry for entry in client.get("/api/processes").json()}
    assert listing[clone["id"]]["latest_version"] == 0  # version history is not copied
    assert listing[original["id"]]["latest_version"] == 1


def test_clone_triggers_are_disabled_and_webhook_paths_cleared():
    client = make_client()
    original = client.post("/api/processes", json=DEFINITION).json()

    clone = client.post(f"/api/processes/{original['id']}/clone").json()

    assert [trigger["enabled"] for trigger in clone["triggers"]] == [False, False]
    assert clone["triggers"][0]["cron"] == "*/15 * * * *"  # schedule is kept, just off
    assert clone["triggers"][1]["path"] == ""  # would otherwise shadow the original's hook
    assert {trigger["id"] for trigger in clone["triggers"]}.isdisjoint(
        {trigger["id"] for trigger in original["triggers"]}
    )

    # the original is untouched
    after = client.get(f"/api/processes/{original['id']}").json()
    assert [trigger["enabled"] for trigger in after["triggers"]] == [True, True]
    assert after["triggers"][1]["path"] == "nightly"


def test_clone_is_independent_of_the_original():
    client = make_client()
    original = client.post("/api/processes", json=DEFINITION).json()
    clone = client.post(f"/api/processes/{original['id']}/clone").json()

    edited = {**clone, "steps": clone["steps"][:1], "name": "Edited copy"}
    client.put(f"/api/processes/{clone['id']}", json=edited)

    assert len(client.get(f"/api/processes/{original['id']}").json()["steps"]) == 2
    assert client.get(f"/api/processes/{clone['id']}").json()["name"] == "Edited copy"

    client.delete(f"/api/processes/{clone['id']}")
    assert client.get(f"/api/processes/{original['id']}").status_code == 200


def test_repeated_clones_get_distinct_names():
    client = make_client()
    original = client.post("/api/processes", json=DEFINITION).json()

    names = [client.post(f"/api/processes/{original['id']}/clone").json()["name"] for _ in range(3)]
    assert names == ["Nightly report (copy)", "Nightly report (copy 2)", "Nightly report (copy 3)"]


def test_clone_accepts_an_explicit_name_and_folder():
    client = make_client()
    original = client.post("/api/processes", json=DEFINITION).json()

    clone = client.post(
        f"/api/processes/{original['id']}/clone", json={"name": "  Q3 variant  ", "folder": " Ops "}
    ).json()

    assert clone["name"] == "Q3 variant"
    assert clone["folder"] == "Ops"
    # blank falls back to the generated name
    blank = client.post(f"/api/processes/{original['id']}/clone", json={"name": "   "}).json()
    assert blank["name"] == "Nightly report (copy)"


def test_clone_of_a_missing_process_is_404():
    assert make_client().post("/api/processes/nope/clone").status_code == 404


def test_clone_runs_on_its_own(engine_host):
    client = make_client()
    original = client.post("/api/processes", json=DEFINITION).json()
    clone = client.post(f"/api/processes/{original['id']}/clone").json()

    run = engine_host.run(client, clone["id"], draft=True)
    assert run["status"] == "succeeded"
    assert run["process_id"] == clone["id"]
    assert client.get(f"/api/processes/{original['id']}/runs").json() == []  # not the original's
