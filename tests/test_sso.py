from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

import process_engine_api.sso
from process_engine_api import create_app
from process_engine_core.registry import spec_registry
from process_engine_core.storage import Database

TOKEN = "master-token"


def make_client() -> TestClient:
    db = Database("sqlite://")
    client = TestClient(create_app(db=db, registry=spec_registry(), auth_token=TOKEN))
    client.db = db  # what the engine_host fixture claims this test's jobs from
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return client


def configure_google(monkeypatch):
    monkeypatch.setenv("PROCESS_ENGINE_OIDC_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("PROCESS_ENGINE_OIDC_GOOGLE_CLIENT_SECRET", "client-secret")

    async def fake_fetch(provider, code, redirect_uri):
        assert provider.key == "google" and code == "auth-code"
        return "sso.user@example.com"

    monkeypatch.setattr(process_engine_api.sso, "fetch_user_email", fake_fetch)


def fragment_of(response) -> dict[str, list[str]]:
    return parse_qs(urlparse(response.headers["location"]).fragment)


def test_sso_providers_empty_without_config():
    assert make_client().get("/api/auth/sso").json() == []


def test_sso_login_and_callback_issue_session(monkeypatch):
    configure_google(monkeypatch)
    client = make_client()
    client.post("/api/users", json={"username": "sso.user@example.com", "password": "x", "role": "editor"})

    providers = client.get("/api/auth/sso").json()
    assert providers == [{"key": "google", "name": "Google"}]

    login = client.get("/api/auth/sso/google/login", follow_redirects=False)
    assert login.status_code == 307
    location = urlparse(login.headers["location"])
    assert location.netloc == "accounts.google.com"
    query = parse_qs(location.query)
    assert query["client_id"] == ["client-id"]
    state = query["state"][0]

    callback = client.get(
        f"/api/auth/sso/google/callback?code=auth-code&state={state}", follow_redirects=False
    )
    fragment = fragment_of(callback)
    assert "sso" in fragment and fragment["user"] == ["sso.user@example.com"]

    session_headers = {"Authorization": f"Bearer {fragment['sso'][0]}"}
    me = client.get("/api/auth/me", headers=session_headers).json()
    assert me == {"name": "sso.user@example.com", "role": "editor"}


def test_sso_unknown_email_rejected_without_auto_provision(monkeypatch):
    configure_google(monkeypatch)
    client = make_client()  # no matching user created
    state = parse_qs(urlparse(client.get("/api/auth/sso/google/login", follow_redirects=False)
                              .headers["location"]).query)["state"][0]
    callback = client.get(
        f"/api/auth/sso/google/callback?code=auth-code&state={state}", follow_redirects=False
    )
    assert "sso_error" in fragment_of(callback)


def test_sso_auto_provision_creates_editor(monkeypatch):
    configure_google(monkeypatch)
    monkeypatch.setenv("PROCESS_ENGINE_SSO_AUTO_PROVISION", "true")
    client = make_client()
    state = parse_qs(urlparse(client.get("/api/auth/sso/google/login", follow_redirects=False)
                              .headers["location"]).query)["state"][0]
    callback = client.get(
        f"/api/auth/sso/google/callback?code=auth-code&state={state}", follow_redirects=False
    )
    fragment = fragment_of(callback)
    assert fragment["role"] == ["editor"]
    users = client.get("/api/users").json()
    assert any(user["username"] == "sso.user@example.com" for user in users)


def test_sso_bad_state_rejected(monkeypatch):
    configure_google(monkeypatch)
    client = make_client()
    callback = client.get(
        "/api/auth/sso/google/callback?code=auth-code&state=forged", follow_redirects=False
    )
    assert "sso_error" in fragment_of(callback)
