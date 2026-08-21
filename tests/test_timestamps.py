"""Every timestamp the API emits must carry its UTC offset.

The columns are ``DateTime(timezone=True)``, but SQLite has no timezone type, so
values read back are naive and a plain ``isoformat()`` drops the offset. A
browser parses an offset-less date-time as *local* time, which silently shifted
every "x ago" in the designer by the viewer's own UTC offset — a run from
seconds ago read as "8h ago" in UTC+8. Send the offset; let the client localise.
"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from process_engine.api import create_app
from process_engine.registry import PluginRegistry
from process_engine.storage import Database, iso_utc

TOKEN = "test-token"

DEFINITION = {
    "name": "Stamped",
    "steps": [{"id": "set", "plugin": "transform", "config": {"values": {"msg": "hi"}}}],
    "connections": [],
}


def make_client() -> TestClient:
    registry = PluginRegistry()
    registry.load_builtins()
    client = TestClient(create_app(db=Database("sqlite://"), registry=registry, auth_token=TOKEN))
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return client


def aware(value: str, field: str) -> datetime:
    """Parse an emitted timestamp, failing loudly when it has no offset."""
    assert value, f"{field} is missing"
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert stamp.tzinfo is not None, f"{field}={value!r} has no UTC offset; a browser reads it as local time"
    return stamp


def assert_recent(value: str, field: str) -> None:
    """The instant is now, wherever the reader sits — the offset makes it absolute."""
    delta = abs(datetime.now(timezone.utc) - aware(value, field))
    assert delta < timedelta(minutes=5), f"{field} is off by {delta}; the offset is probably wrong, not the clock"


def test_iso_utc_labels_naive_values_as_utc():
    naive = datetime(2026, 8, 17, 6, 14, 37)
    assert iso_utc(naive) == "2026-08-17T06:14:37+00:00"
    # an already-aware value keeps its instant, normalised to UTC
    tokyo = datetime(2026, 8, 17, 15, 14, 37, tzinfo=timezone(timedelta(hours=9)))
    assert iso_utc(tokyo) == "2026-08-17T06:14:37+00:00"


def test_process_list_updated_at_carries_offset():
    client = make_client()
    client.post("/api/processes", json=DEFINITION)
    entry = client.get("/api/processes").json()[0]
    assert_recent(entry["updated_at"], "processes[].updated_at")


def test_run_list_carries_offset_and_enough_to_show_a_duration():
    client = make_client()
    process_id = client.post("/api/processes", json=DEFINITION).json()["id"]
    client.post(f"/api/processes/{process_id}/run", json={"draft": True})

    run = client.get(f"/api/processes/{process_id}/runs").json()[0]
    assert_recent(run["created_at"], "runs[].created_at")

    # the Runs table computes DURATION from these two; without them the column
    # renders "—" for every row it will ever show
    started = aware(run["started_at"], "runs[].started_at")
    finished = aware(run["finished_at"], "runs[].finished_at")
    assert finished >= started


def test_user_list_created_at_carries_offset():
    client = make_client()
    client.post("/api/users", json={"username": "bob", "password": "pw1", "role": "editor"})
    bob = next(user for user in client.get("/api/users").json() if user["username"] == "bob")
    assert_recent(bob["created_at"], "users[].created_at")


def test_run_document_and_step_input_carry_offset():
    client = make_client()
    process_id = client.post("/api/processes", json=DEFINITION).json()["id"]
    run_id = client.post(f"/api/processes/{process_id}/run", json={"draft": True}).json()["id"]

    detail = client.get(f"/api/runs/{run_id}").json()
    assert_recent(detail["started_at"], "run.started_at")

    step_input = client.get(f"/api/processes/{process_id}/steps/set/input").json()
    assert_recent(step_input["run_started_at"], "run_started_at")
