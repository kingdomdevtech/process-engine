"""A process's own history: what changed, who changed it, and the way back.

Two features that lean on each other. Every change to a definition appends an
entry carrying the draft as it stood afterwards, so *restore* is reading a row
rather than reconstructing a diff — and because that history goes when the
process does, the folders holding work nobody should lose by accident refuse
deletion instead.

The invariants worth guarding are the ones that would quietly cost someone their
work: a restore must not roll back a published version, must not hand out access
a snapshot happens to remember, and must itself be recorded so the state it
replaced is still reachable.
"""

from fastapi.testclient import TestClient

from process_engine_api import create_app
from process_engine_core.registry import spec_registry
from process_engine_core.storage import Database

TOKEN = "test-token"


def definition(name: str, message: str, folder: str = "") -> dict:
    return {
        "name": name,
        "folder": folder,
        "steps": [{"id": "say", "name": "say", "plugin": "log", "config": {"message": message}}],
        "connections": [],
    }


def make_client() -> TestClient:
    db = Database("sqlite://")
    client = TestClient(create_app(db=db, registry=spec_registry(), auth_token=TOKEN))
    client.db = db
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return client


def add_editor(admin: TestClient, username: str) -> TestClient:
    assert admin.post(
        "/api/users", json={"username": username, "password": "pw", "role": "editor"}
    ).status_code == 200
    session = admin.post("/api/auth/login", json={"username": username, "password": "pw"}).json()
    client = TestClient(admin.app)
    client.headers.update({"Authorization": f"Bearer {session['token']}"})
    return client


def history(client: TestClient, process_id: str) -> list[dict]:
    response = client.get(f"/api/processes/{process_id}/history")
    assert response.status_code == 200, response.text
    return response.json()


# ---- the trail -------------------------------------------------------------------


def test_every_change_to_a_process_is_recorded():
    client = make_client()
    process_id = client.post("/api/processes", json=definition("Trail", "one")).json()["id"]
    client.put(f"/api/processes/{process_id}", json=definition("Trail", "two"))
    client.post(f"/api/processes/{process_id}/publish")
    client.put(f"/api/processes/{process_id}/folder", json={"folder": "reports"})

    entries = history(client, process_id)
    # newest first, so the trail reads the way the panel shows it
    assert [entry["action"] for entry in entries] == ["moved", "published", "updated", "created"]
    assert all(entry["actor"] == "api-token" for entry in entries)
    assert "version 1" in next(entry["summary"] for entry in entries if entry["action"] == "published")


def test_a_share_is_recorded_but_carries_no_snapshot_to_restore():
    """Sharing changed who can reach the process, not the process. Offering to
    "restore" it would put an access list back under the name of an edit."""
    admin = make_client()
    add_editor(admin, "bob")
    process_id = admin.post("/api/processes", json=definition("Shared", "one")).json()["id"]
    assert admin.post(f"/api/processes/{process_id}/share", json={"usernames": ["bob"]}).status_code == 200

    shared = next(entry for entry in history(admin, process_id) if entry["action"] == "shared")
    assert shared["restorable"] is False
    assert "bob" in shared["summary"]

    restore = admin.post(f"/api/processes/{process_id}/history/{shared['id']}/restore")
    assert restore.status_code == 404


def test_a_clone_starts_its_own_history_naming_where_it_came_from():
    client = make_client()
    original = client.post("/api/processes", json=definition("Original", "one")).json()["id"]
    clone = client.post(f"/api/processes/{original}/clone").json()["id"]

    entries = history(client, clone)
    assert [entry["action"] for entry in entries] == ["created"]
    assert "Original" in entries[0]["summary"]
    # and the original's own history is untouched by being copied
    assert [entry["action"] for entry in history(client, original)] == ["created"]


def test_history_is_only_visible_to_someone_who_can_see_the_process():
    """Step names and shapes are as revealing as the definition, so the history
    goes behind the same 404 the definition does — never a 403."""
    admin = make_client()
    bob = add_editor(admin, "bob")
    ann = add_editor(admin, "ann")
    process_id = bob.post("/api/processes", json=definition("Bob's", "one")).json()["id"]

    assert ann.get(f"/api/processes/{process_id}/history").status_code == 404
    assert bob.get(f"/api/processes/{process_id}/history").status_code == 200
    assert admin.get(f"/api/processes/{process_id}/history").status_code == 200


# ---- restoring -------------------------------------------------------------------


def test_restoring_puts_the_earlier_draft_back():
    client = make_client()
    process_id = client.post("/api/processes", json=definition("Revertible", "first")).json()["id"]
    client.put(f"/api/processes/{process_id}", json=definition("Revertible", "second"))

    created = next(entry for entry in history(client, process_id) if entry["action"] == "created")
    restored = client.post(f"/api/processes/{process_id}/history/{created['id']}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["steps"][0]["config"]["message"] == "first"
    assert client.get(f"/api/processes/{process_id}").json()["steps"][0]["config"]["message"] == "first"


def test_a_restore_is_itself_recorded_so_it_can_be_undone():
    client = make_client()
    process_id = client.post("/api/processes", json=definition("Round trip", "first")).json()["id"]
    client.put(f"/api/processes/{process_id}", json=definition("Round trip", "second"))

    created = next(entry for entry in history(client, process_id) if entry["action"] == "created")
    client.post(f"/api/processes/{process_id}/history/{created['id']}/restore")

    entries = history(client, process_id)
    assert entries[0]["action"] == "restored"
    # the state the restore replaced is still on the trail, so back is available
    second = next(entry for entry in entries if entry["action"] == "updated")
    client.post(f"/api/processes/{process_id}/history/{second['id']}/restore")
    assert client.get(f"/api/processes/{process_id}").json()["steps"][0]["config"]["message"] == "second"


def test_restoring_an_old_draft_leaves_published_versions_alone():
    """Running instances record the version they used, so a published snapshot is
    immutable — a restore edits the draft and nothing else. What a schedule runs
    does not change until somebody publishes again."""
    client = make_client()
    process_id = client.post("/api/processes", json=definition("Published", "first")).json()["id"]
    client.post(f"/api/processes/{process_id}/publish")
    client.put(f"/api/processes/{process_id}", json=definition("Published", "second"))
    client.post(f"/api/processes/{process_id}/publish")

    created = next(entry for entry in history(client, process_id) if entry["action"] == "created")
    restored = client.post(f"/api/processes/{process_id}/history/{created['id']}/restore").json()

    assert restored["steps"][0]["config"]["message"] == "first"
    assert restored["version"] == 2, "the draft still belongs to the latest published version"
    assert client.db.get_version(process_id, 2).steps[0].config["message"] == "second"
    assert client.db.get_version(process_id).version == 2, "nothing was un-published"


def test_a_snapshot_cannot_grant_access_it_remembers():
    """`created_by`/`shared_with` are server-owned everywhere else for the same
    reason: an old snapshot must not be a way to re-add someone who was removed,
    or to claim a process by restoring an entry that names you."""
    admin = make_client()
    bob = add_editor(admin, "bob")
    ann = add_editor(admin, "ann")
    process_id = bob.post("/api/processes", json=definition("Bob's", "one")).json()["id"]
    bob.post(f"/api/processes/{process_id}/share", json={"usernames": ["ann"]})
    bob.put(f"/api/processes/{process_id}", json=definition("Bob's", "two"))
    bob.post(f"/api/processes/{process_id}/share", json={"usernames": []})

    shared_era = next(entry for entry in history(bob, process_id) if entry["action"] == "updated")
    restored = bob.post(f"/api/processes/{process_id}/history/{shared_era['id']}/restore").json()

    assert restored["created_by"] == "bob"
    assert restored["shared_with"] == [], "restoring must not re-share what was unshared"
    assert ann.get(f"/api/processes/{process_id}").status_code == 404


def test_a_history_entry_belonging_to_another_process_is_not_restorable():
    client = make_client()
    mine = client.post("/api/processes", json=definition("Mine", "one")).json()["id"]
    theirs = client.post("/api/processes", json=definition("Theirs", "other")).json()["id"]
    entry = history(client, theirs)[0]

    assert client.post(f"/api/processes/{mine}/history/{entry['id']}/restore").status_code == 404
    assert client.get(f"/api/processes/{mine}").json()["steps"][0]["config"]["message"] == "one"


# ---- protected folders -----------------------------------------------------------


def test_a_process_in_the_demo_folder_cannot_be_deleted():
    client = make_client()
    process_id = client.post("/api/processes", json=definition("Demo run", "one", folder="demo")).json()["id"]

    refused = client.delete(f"/api/processes/{process_id}")
    assert refused.status_code == 409
    assert "demo" in refused.json()["detail"]
    assert client.get(f"/api/processes/{process_id}").status_code == 200


def test_the_folder_is_the_protection_not_a_lock():
    """Moving out is an ordinary edit, and then it deletes like anything else —
    which is how the demo spec rebuilds its processes from scratch each run."""
    client = make_client()
    process_id = client.post("/api/processes", json=definition("Demo run", "one", folder="Demo")).json()["id"]

    moved = client.put(f"/api/processes/{process_id}/folder", json={"folder": "attic"})
    assert moved.status_code == 200
    assert moved.json()["protected"] is False
    assert client.delete(f"/api/processes/{process_id}").status_code == 200
    assert client.get(f"/api/processes/{process_id}").status_code == 404


def test_the_listing_says_which_rows_are_protected():
    """The designer reads it off the row rather than keeping its own copy of the
    rule — one authority for which folders are undeletable."""
    client = make_client()
    client.post("/api/processes", json=definition("In demo", "one", folder="demo"))
    client.post("/api/processes", json=definition("Elsewhere", "two", folder="reports"))

    rows = {entry["name"]: entry["protected"] for entry in client.get("/api/processes").json()}
    assert rows == {"In demo": True, "Elsewhere": False}


def test_deleting_a_process_takes_its_history_with_it():
    """A history is a process's own record, not a recycle bin — which is exactly
    why anything you cannot afford to lose is protected from deletion instead."""
    client = make_client()
    process_id = client.post("/api/processes", json=definition("Doomed", "one")).json()["id"]
    client.put(f"/api/processes/{process_id}", json=definition("Doomed", "two"))
    assert len(client.db.list_audits(process_id)) == 2

    assert client.delete(f"/api/processes/{process_id}").status_code == 200
    assert client.db.list_audits(process_id) == []
