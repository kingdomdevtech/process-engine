from fastapi.testclient import TestClient

from process_engine_api import create_app
from process_engine_core.registry import spec_registry
from process_engine_core.storage import Database
from process_engine_api.users import hash_password, verify_password

TOKEN = "master-token"


def make_client() -> TestClient:
    db = Database("sqlite://")
    client = TestClient(create_app(db=db, registry=spec_registry(), auth_token=TOKEN))
    client.db = db  # what the engine_host fixture claims this test's jobs from
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return client


def test_password_hashing_roundtrip():
    stored = hash_password("hunter2")
    assert verify_password("hunter2", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("hunter2", "garbage")


def test_user_lifecycle_and_roles():
    admin = make_client()  # master token acts as admin

    # create an editor and an admin user
    assert admin.post("/api/users", json={"username": "bob", "password": "pw1", "role": "editor"}).status_code == 200
    assert admin.post("/api/users", json={"username": "alice", "password": "pw2", "role": "admin"}).status_code == 200
    # duplicates rejected
    assert admin.post("/api/users", json={"username": "bob", "password": "x"}).status_code == 422

    # bob logs in and can use the designer API
    bob_login = admin.post("/api/auth/login", json={"username": "bob", "password": "pw1"}).json()
    assert bob_login["role"] == "editor"
    bob = {"Authorization": f"Bearer {bob_login['token']}"}
    assert admin.get("/api/plugins", headers=bob).status_code == 200
    assert admin.get("/api/auth/me", headers=bob).json() == {"name": "bob", "role": "editor"}

    # but bob cannot manage users
    assert admin.get("/api/users", headers=bob).status_code == 403
    assert admin.post("/api/users", headers=bob, json={"username": "eve", "password": "x"}).status_code == 403

    # alice (admin) can
    alice_login = admin.post("/api/auth/login", json={"username": "alice", "password": "pw2"}).json()
    alice = {"Authorization": f"Bearer {alice_login['token']}"}
    listed = admin.get("/api/users", headers=alice).json()
    assert {user["username"] for user in listed} == {"bob", "alice"}
    assert all("password_hash" not in user for user in listed)

    # wrong password rejected
    assert admin.post("/api/auth/login", json={"username": "bob", "password": "nope"}).status_code == 401

    # disabling bob revokes his existing session immediately
    admin.put("/api/users/bob", json={"disabled": True})
    assert admin.get("/api/plugins", headers=bob).status_code == 401
    assert admin.post("/api/auth/login", json={"username": "bob", "password": "pw1"}).status_code == 401

    # re-enable + password reset
    admin.put("/api/users/bob", json={"disabled": False, "password": "pw3"})
    assert admin.post("/api/auth/login", json={"username": "bob", "password": "pw3"}).status_code == 200

    # delete
    assert admin.delete("/api/users/bob").json() == {"deleted": True}
    assert admin.delete("/api/users/bob").status_code == 404


def test_login_requires_no_prior_auth():
    client = make_client()
    client.post("/api/users", json={"username": "solo", "password": "pw"})
    anonymous = {"Authorization": ""}
    response = client.post("/api/auth/login", headers=anonymous,
                           json={"username": "solo", "password": "pw"})
    assert response.status_code == 200
    assert response.json()["username"] == "solo"
