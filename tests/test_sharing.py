"""Who can see a process, and who can hand it on.

Admins see everything. Everyone else sees what they created plus what has been
shared with them, and can share on what they can reach. No-access reads as 404
rather than 403 throughout: a 403 confirms the id belongs to a real process,
which is a slow listing of other people's work.
"""

from fastapi.testclient import TestClient

from process_engine_api import create_app
from process_engine_core.registry import spec_registry
from process_engine_core.storage import Database

TOKEN = "test-token"

DEFINITION = {
    "name": "Shared demo",
    "steps": [{"id": "set", "plugin": "transform", "config": {"values": {"msg": "hi"}}}],
    "connections": [],
}


def make_admin() -> TestClient:
    """The static API token is an admin bootstrap credential."""
    db = Database("sqlite://")
    client = TestClient(create_app(db=db, registry=spec_registry(), auth_token=TOKEN))
    client.db = db  # what the engine_host fixture claims this test's jobs from
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return client


def add_editor(admin: TestClient, username: str) -> TestClient:
    assert admin.post("/api/users", json={"username": username, "password": "pw", "role": "editor"}).status_code == 200
    session = admin.post("/api/auth/login", json={"username": username, "password": "pw"}).json()
    client = TestClient(admin.app)
    client.headers.update({"Authorization": f"Bearer {session['token']}"})
    return client


def make_process(client: TestClient, name: str) -> str:
    return client.post("/api/processes", json={**DEFINITION, "name": name}).json()["id"]


def names(client: TestClient) -> set[str]:
    return {entry["name"] for entry in client.get("/api/processes").json()}


def test_editor_sees_only_their_own_until_it_is_shared():
    admin = make_admin()
    bob = add_editor(admin, "bob")
    ann = add_editor(admin, "ann")

    bob_process = make_process(bob, "Bob's work")
    make_process(ann, "Ann's work")

    assert names(bob) == {"Bob's work"}
    assert names(ann) == {"Ann's work"}
    # the admin sees both, plus nothing hidden from them
    assert names(admin) == {"Bob's work", "Ann's work"}

    # ann cannot reach it, and is told it does not exist rather than that it does
    assert ann.get(f"/api/processes/{bob_process}").status_code == 404
    assert ann.put(f"/api/processes/{bob_process}", json=DEFINITION).status_code == 404
    assert ann.delete(f"/api/processes/{bob_process}").status_code == 404
    assert ann.post(f"/api/processes/{bob_process}/publish").status_code == 404
    assert ann.post(f"/api/processes/{bob_process}/run", json={"draft": True}).status_code == 404
    assert ann.get(f"/api/processes/{bob_process}/runs").status_code == 404
    assert ann.get(f"/api/processes/{bob_process}/steps/set/input").status_code == 404

    bob.post(f"/api/processes/{bob_process}/share", json={"usernames": ["ann"]})

    assert names(ann) == {"Ann's work", "Bob's work"}
    assert ann.get(f"/api/processes/{bob_process}").status_code == 200
    assert ann.post(f"/api/processes/{bob_process}/run", json={"draft": True}).status_code == 200


def test_a_share_recipient_can_share_on():
    admin = make_admin()
    bob, ann, cat = add_editor(admin, "bob"), add_editor(admin, "ann"), add_editor(admin, "cat")
    process_id = make_process(bob, "Bob's work")

    bob.post(f"/api/processes/{process_id}/share", json={"usernames": ["ann"]})
    # access is flat: ann holds it exactly as bob does, including handing it on
    assert ann.post(f"/api/processes/{process_id}/share", json={"usernames": ["ann", "cat"]}).status_code == 200
    assert names(cat) == {"Bob's work"}


def test_sharing_never_displaces_the_creator():
    admin = make_admin()
    bob, ann = add_editor(admin, "bob"), add_editor(admin, "ann")
    process_id = make_process(bob, "Bob's work")

    # ann tries to share it to herself alone; bob owns it and cannot be shut out
    bob.post(f"/api/processes/{process_id}/share", json={"usernames": ["ann"]})
    ann.post(f"/api/processes/{process_id}/share", json={"usernames": ["ann"]})
    assert names(bob) == {"Bob's work"}

    # and the creator is never carried in the list itself
    shared = bob.post(f"/api/processes/{process_id}/share", json={"usernames": ["bob", "ann"]}).json()
    assert shared["shared_with"] == ["ann"]


def test_sharing_rejects_unknown_and_disabled_users():
    admin = make_admin()
    bob = add_editor(admin, "bob")
    add_editor(admin, "gone")
    process_id = make_process(bob, "Bob's work")

    assert bob.post(f"/api/processes/{process_id}/share", json={"usernames": ["nobody"]}).status_code == 422
    admin.put("/api/users/gone", json={"disabled": True})
    assert bob.post(f"/api/processes/{process_id}/share", json={"usernames": ["gone"]}).status_code == 422


def test_a_put_cannot_grant_itself_access():
    admin = make_admin()
    bob, ann = add_editor(admin, "bob"), add_editor(admin, "ann")
    process_id = make_process(bob, "Bob's work")
    bob.post(f"/api/processes/{process_id}/share", json={"usernames": ["ann"]})

    # ann can edit the process, but shared_with and created_by are server-owned:
    # a crafted PUT must not let her drop bob or add anyone
    ann.put(
        f"/api/processes/{process_id}",
        json={**DEFINITION, "created_by": "ann", "shared_with": ["ann", "cat"]},
    )
    stored = admin.get(f"/api/processes/{process_id}").json()
    assert stored["created_by"] == "bob"
    assert stored["shared_with"] == ["ann"]


def test_folders_count_only_what_the_caller_can_see():
    admin = make_admin()
    bob, ann = add_editor(admin, "bob"), add_editor(admin, "ann")
    bob.post("/api/processes", json={**DEFINITION, "name": "Bob's", "folder": "Team"})
    ann.post("/api/processes", json={**DEFINITION, "name": "Ann's", "folder": "Team"})

    def team_count(client: TestClient) -> int:
        return next(entry["count"] for entry in client.get("/api/folders").json() if entry["name"] == "Team")

    assert team_count(bob) == 1  # not 2 — a count must not advertise ann's work
    assert team_count(ann) == 1
    assert team_count(admin) == 2


def test_run_history_inherits_process_access():
    admin = make_admin()
    bob, ann = add_editor(admin, "bob"), add_editor(admin, "ann")
    process_id = make_process(bob, "Bob's work")
    run_id = bob.post(f"/api/processes/{process_id}/run", json={"draft": True}).json()["id"]

    # a run id is not a capability: step inputs, outputs and errors are as
    # revealing as the definition
    assert ann.get(f"/api/runs/{run_id}").status_code == 404
    assert ann.post(f"/api/runs/{run_id}/cancel").status_code == 404
    assert ann.post(f"/api/runs/{run_id}/resume").status_code == 404
    assert admin.get(f"/api/runs/{run_id}").status_code == 200

    bob.post(f"/api/processes/{process_id}/share", json={"usernames": ["ann"]})
    assert ann.get(f"/api/runs/{run_id}").status_code == 200


def test_a_clone_belongs_to_whoever_made_it_and_starts_private():
    admin = make_admin()
    bob, ann, cat = add_editor(admin, "bob"), add_editor(admin, "ann"), add_editor(admin, "cat")
    process_id = make_process(bob, "Bob's work")
    bob.post(f"/api/processes/{process_id}/share", json={"usernames": ["ann", "cat"]})

    clone = ann.post(f"/api/processes/{process_id}/clone").json()
    assert clone["created_by"] == "ann"
    # cat could see the original; the copy is ann's alone until she says otherwise
    assert clone["shared_with"] == []
    assert names(cat) == {"Bob's work"}


def test_settings_endpoints_are_admin_only():
    admin = make_admin()
    bob = add_editor(admin, "bob")

    # deployment configuration
    assert bob.get("/api/workspace").status_code == 403
    assert bob.get("/api/users").status_code == 403
    assert bob.put("/api/notifications/mail", json={"host": "x"}).status_code == 403
    assert admin.get("/api/workspace").status_code == 200

    # but what an editor needs in order to build is still readable
    assert bob.get("/api/plugins").status_code == 200
    assert bob.get("/api/secrets").status_code == 200
    assert bob.get("/api/notifications/mail").status_code == 200
    assert bob.get("/api/users/directory?emails_only=false").status_code == 200


def test_share_picker_lists_non_email_accounts_too():
    admin = make_admin()
    bob = add_editor(admin, "bob")
    add_editor(admin, "ann@example.com")

    assert set(bob.get("/api/users/directory?emails_only=false").json()) >= {"bob", "ann@example.com"}
    # the notification picker still only offers addressable mailboxes
    assert bob.get("/api/users/directory").json() == ["ann@example.com"]
