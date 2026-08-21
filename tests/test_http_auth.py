"""The http_request authentication modes.

Every case asserts what actually goes on the wire, since that is the whole
contract: the step's job is to turn a filled-in form into the header the
service is expecting.
"""

import base64
import logging

import httpx
import pytest
from pydantic import ValidationError

from process_engine.plugin import PluginContext
from process_engine.plugins.http_request import HttpRequestPlugin


class Recorder(list):
    """The requests the plugin made, plus canned answers keyed by URL fragment."""

    def __init__(self) -> None:
        super().__init__()
        self.replies: dict[str, httpx.Response] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.append(request)
        for fragment, response in self.replies.items():
            if fragment in str(request.url):
                return response
        return httpx.Response(200, json={"ok": True})


@pytest.fixture
def captured(monkeypatch):
    recorder = Recorder()
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        return original(*args, **kwargs, transport=httpx.MockTransport(recorder.handle))

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return recorder


async def call(config: dict) -> dict:
    ctx = PluginContext(
        run_id="r1",
        step_id="s1",
        step_name="call",
        config=HttpRequestPlugin.Config(**config),
        input=None,
        all_inputs={},
        variables={},
        logger=logging.getLogger("test"),
    )
    result = await HttpRequestPlugin().execute(ctx)
    return result.outputs["main"]


BASE = {"url": "https://api.example.com/orders"}


async def test_no_auth_sends_no_authorization_header(captured):
    await call(BASE)
    assert "authorization" not in captured[0].headers


async def test_basic_auth_encodes_the_credentials(captured):
    await call({**BASE, "auth": "basic", "auth_username": "reports", "auth_password": "s3cret"})
    expected = base64.b64encode(b"reports:s3cret").decode()
    assert captured[0].headers["authorization"] == f"Basic {expected}"


async def test_bearer_auth_sends_the_token(captured):
    await call({**BASE, "auth": "bearer", "auth_token": "abc123"})
    assert captured[0].headers["authorization"] == "Bearer abc123"


async def test_api_key_goes_in_the_named_header(captured):
    await call(
        {**BASE, "auth": "api_key", "auth_api_key_name": "X-Shop-Key", "auth_api_key_value": "k-1"}
    )
    assert captured[0].headers["x-shop-key"] == "k-1"


async def test_api_key_can_go_in_the_query_string(captured):
    await call(
        {
            **BASE,
            "auth": "api_key",
            "auth_api_key_name": "apikey",
            "auth_api_key_value": "k-1",
            "auth_api_key_in": "query",
        }
    )
    assert captured[0].url.params["apikey"] == "k-1"
    assert "apikey" not in captured[0].headers


async def test_an_explicit_header_is_never_overwritten(captured):
    """A hand-written Authorization header stays the one that is sent."""
    await call({**BASE, "auth": "bearer", "auth_token": "abc", "headers": {"Authorization": "Custom mine"}})
    assert captured[0].headers["authorization"] == "Custom mine"


OAUTH2 = {
    **BASE,
    "auth": "oauth2_client_credentials",
    "auth_token_url": "https://login.example.com/token",
    "auth_client_id": "cid",
    "auth_client_secret": "csecret",
}


async def test_oauth2_exchanges_credentials_then_calls_with_the_token(captured):
    captured.replies["/token"] = httpx.Response(200, json={"access_token": "tok-42"})
    await call({**OAUTH2, "auth_scope": "orders.read"})

    token_request, api_request = captured
    assert token_request.method == "POST"
    body = token_request.content.decode()
    assert "grant_type=client_credentials" in body
    assert "client_id=cid" in body and "client_secret=csecret" in body
    assert "scope=orders.read" in body
    assert api_request.headers["authorization"] == "Bearer tok-42"


async def test_oauth2_can_send_the_client_credentials_as_basic_auth(captured):
    captured.replies["/token"] = httpx.Response(200, json={"access_token": "tok-42"})
    await call({**OAUTH2, "auth_client_auth": "basic"})

    token_request = captured[0]
    expected = base64.b64encode(b"cid:csecret").decode()
    assert token_request.headers["authorization"] == f"Basic {expected}"
    assert "client_secret" not in token_request.content.decode()


async def test_oauth2_reports_the_providers_reason_for_refusing(captured):
    captured.replies["/token"] = httpx.Response(400, json={"error": "invalid_scope"})
    with pytest.raises(RuntimeError, match="invalid_scope"):
        await call(OAUTH2)


async def test_oauth2_rejects_a_response_without_a_token(captured):
    captured.replies["/token"] = httpx.Response(200, json={"expires_in": 3600})
    with pytest.raises(RuntimeError, match="no access_token"):
        await call(OAUTH2)


@pytest.mark.parametrize(
    "config, missing",
    [
        ({"auth": "basic"}, "Username"),
        ({"auth": "bearer"}, "Token"),
        ({"auth": "api_key", "auth_api_key_value": ""}, "Key value"),
        ({"auth": "oauth2_client_credentials", "auth_client_id": "cid"}, "Token URL"),
    ],
)
def test_a_missing_credential_is_named(config, missing):
    """Validation happens before the call, so the message points at the form
    field rather than arriving as a 401 from the far end."""
    with pytest.raises(ValidationError, match=missing):
        HttpRequestPlugin.Config(**BASE, **config)


def test_credentials_are_only_required_for_the_chosen_scheme():
    HttpRequestPlugin.Config(**BASE)  # auth defaults to none; nothing else needed
