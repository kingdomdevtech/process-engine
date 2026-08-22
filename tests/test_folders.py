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


def definition(name: str, folder: str = "") -> dict:
    return {
        "name": name,
        "folder": folder,
        "steps": [{"id": "s", "plugin": "log"}],
        "connections": [],
    }


def test_folder_round_trips_and_appears_in_listing():
    client = make_client()
    created = client.post("/api/processes", json=definition("Nightly", "Finance")).json()
    assert created["folder"] == "Finance"
    assert client.get(f"/api/processes/{created['id']}").json()["folder"] == "Finance"

    listing = client.get("/api/processes").json()
    assert listing[0]["folder"] == "Finance"


def test_listing_filters_by_folder_and_folders_are_counted():
    client = make_client()
    client.post("/api/processes", json=definition("A", "Finance"))
    client.post("/api/processes", json=definition("B", "Finance"))
    client.post("/api/processes", json=definition("C", "Ops"))
    client.post("/api/processes", json=definition("D"))  # uncategorized

    assert len(client.get("/api/processes?folder=Finance").json()) == 2
    assert len(client.get("/api/processes?folder=Ops").json()) == 1
    assert len(client.get("/api/processes?folder=").json()) == 1  # uncategorized

    folders = client.get("/api/folders").json()
    assert folders == [
        {"name": "Finance", "count": 2},
        {"name": "Ops", "count": 1},
        {"name": "", "count": 1},  # uncategorized sorts last
    ]


def test_move_endpoint_reassigns_folder_without_touching_steps():
    client = make_client()
    created = client.post("/api/processes", json=definition("Report", "Ops")).json()

    moved = client.put(f"/api/processes/{created['id']}/folder", json={"folder": "  Finance  "}).json()
    assert moved["folder"] == "Finance"  # trimmed

    after = client.get(f"/api/processes/{created['id']}").json()
    assert after["folder"] == "Finance"
    assert len(after["steps"]) == 1  # definition otherwise untouched

    client.put(f"/api/processes/{created['id']}/folder", json={"folder": ""})
    assert client.get(f"/api/processes/{created['id']}").json()["folder"] == ""
    assert client.put("/api/processes/missing/folder", json={"folder": "x"}).status_code == 404


def test_processes_saved_before_folders_existed_default_to_uncategorized():
    client = make_client()
    legacy = {"name": "Legacy", "steps": [{"id": "s", "plugin": "log"}], "connections": []}
    created = client.post("/api/processes", json=legacy).json()
    assert created["folder"] == ""
    assert client.get("/api/processes").json()[0]["folder"] == ""
