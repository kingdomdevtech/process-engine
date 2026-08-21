"""Call an HTTP endpoint.

Authentication is a single choice driving a handful of conditional fields, so
the common cases need no knowledge of HTTP headers:

* ``basic`` — username and password, sent as an ``Authorization: Basic`` header
* ``bearer`` — a token you already hold
* ``api_key`` — a named header or query parameter
* ``oauth2_client_credentials`` — client id/secret exchanged for a token at a
  token endpoint, then sent as a bearer token

Keep credentials out of process definitions: store them in the secrets manager
and reference them, e.g. ``"auth_password": "{{ secrets.api_password }}"``.

The OAuth2 token is fetched once per step execution and not cached across
runs — one extra round trip per call, in exchange for never serving a stale or
revoked token. Anything more exotic (mTLS, request signing, refresh-token
flows) still goes in ``headers`` or belongs in a dedicated plugin.
"""

from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, model_validator

from ..plugin import Plugin, PluginContext, PluginManifest, PluginResult
from ..ui import ui, when

AuthType = Literal["none", "basic", "bearer", "api_key", "oauth2_client_credentials"]

# The auth kinds each conditional field belongs to, so the designer only asks
# for a credential once it is actually part of the chosen scheme.
_BASIC = when("auth", "basic")
_BEARER = when("auth", "bearer")
_API_KEY = when("auth", "api_key")
_OAUTH2 = when("auth", "oauth2_client_credentials")


class HttpRequestConfig(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = Field(
        default="GET",
        title="Method",
        description="GET reads data; POST, PUT and PATCH send it; DELETE removes it.",
        json_schema_extra=ui(group="Request"),
    )
    url: str = Field(
        title="URL",
        description="The full web address to call, including https://",
        examples=["https://api.example.com/orders"],
        json_schema_extra=ui(group="Request"),
    )

    auth: AuthType = Field(
        default="none",
        title="Authentication",
        description="How this service checks who you are. Its documentation will say which one it expects.",
        json_schema_extra=ui(
            group="Authentication",
            labels={
                "none": "None — the endpoint is open",
                "basic": "Username and password",
                "bearer": "Bearer token",
                "api_key": "API key",
                "oauth2_client_credentials": "OAuth2 client credentials",
            },
        ),
    )
    auth_username: str = Field(
        default="",
        title="Username",
        examples=["reports"],
        json_schema_extra=ui(group="Authentication", show_if=_BASIC),
    )
    auth_password: str = Field(
        default="",
        title="Password",
        examples=["{{ secrets.api_password }}"],
        json_schema_extra=ui(group="Authentication", widget="password", secret=True, show_if=_BASIC),
    )
    auth_token: str = Field(
        default="",
        title="Token",
        description="Sent as “Authorization: Bearer …”.",
        examples=["{{ secrets.api_token }}"],
        json_schema_extra=ui(group="Authentication", widget="password", secret=True, show_if=_BEARER),
    )
    auth_api_key_name: str = Field(
        default="X-API-Key",
        title="Key name",
        description="The header or parameter name the service expects.",
        json_schema_extra=ui(group="Authentication", show_if=_API_KEY),
    )
    auth_api_key_value: str = Field(
        default="",
        title="Key value",
        examples=["{{ secrets.api_key }}"],
        json_schema_extra=ui(group="Authentication", widget="password", secret=True, show_if=_API_KEY),
    )
    auth_api_key_in: Literal["header", "query"] = Field(
        default="header",
        title="Send the key as",
        json_schema_extra=ui(
            group="Authentication",
            show_if=_API_KEY,
            labels={"header": "A request header", "query": "A query string parameter"},
        ),
    )
    auth_token_url: str = Field(
        default="",
        title="Token URL",
        description="Where the client id and secret are exchanged for a token.",
        examples=["https://login.example.com/oauth2/token"],
        json_schema_extra=ui(group="Authentication", show_if=_OAUTH2),
    )
    auth_client_id: str = Field(
        default="",
        title="Client ID",
        examples=["4f9c2b10-..."],
        json_schema_extra=ui(group="Authentication", show_if=_OAUTH2),
    )
    auth_client_secret: str = Field(
        default="",
        title="Client secret",
        examples=["{{ secrets.oauth_client_secret }}"],
        json_schema_extra=ui(group="Authentication", widget="password", secret=True, show_if=_OAUTH2),
    )
    auth_scope: str = Field(
        default="",
        title="Scope",
        description="Space-separated permissions to ask for. Leave blank unless the service asks for one.",
        examples=["orders.read"],
        json_schema_extra=ui(group="Authentication", show_if=_OAUTH2),
    )
    auth_client_auth: Literal["body", "basic"] = Field(
        default="body",
        title="Send client credentials",
        description="Providers differ; switch this if the token request is rejected as unauthorised.",
        json_schema_extra=ui(
            group="Authentication",
            advanced=True,
            show_if=_OAUTH2,
            labels={"body": "In the request body", "basic": "As a Basic auth header"},
        ),
    )

    headers: dict[str, str] = Field(
        default_factory=dict,
        title="Headers",
        description="Extra headers to send. Authentication above is added for you.",
        examples=[{"Accept": "application/json"}],
        json_schema_extra=ui(group="Request", widget="keyvalue", key_label="Header", add_label="Add header"),
    )
    body: Any = Field(
        default=None,
        title="Body",
        description="Sent as JSON. Leave empty for GET requests.",
        examples=[{"id": "{{ trigger.id }}"}],
        json_schema_extra=ui(group="Request", widget="json"),
    )
    timeout_seconds: float = Field(
        default=30,
        title="Timeout",
        description="Give up if the service has not answered within this long.",
        json_schema_extra=ui(group="Request", advanced=True, unit="seconds"),
    )
    fail_on_error_status: bool = Field(
        default=True,
        title="Treat error responses as a failure",
        description="On: a 4xx or 5xx response fails the step, so retries and the error output apply. "
        "Off: the response is passed on as-is for a later step to inspect.",
        json_schema_extra=ui(group="Request", advanced=True),
    )

    @model_validator(mode="after")
    def _credentials_present(self) -> "HttpRequestConfig":
        """Name the missing credential rather than letting the service reject the call."""
        required: dict[AuthType, list[tuple[str, str]]] = {
            "basic": [("auth_username", "Username")],
            "bearer": [("auth_token", "Token")],
            "api_key": [("auth_api_key_name", "Key name"), ("auth_api_key_value", "Key value")],
            "oauth2_client_credentials": [
                ("auth_token_url", "Token URL"),
                ("auth_client_id", "Client ID"),
                ("auth_client_secret", "Client secret"),
            ],
        }
        missing = [label for field, label in required.get(self.auth, []) if not getattr(self, field)]
        if missing:
            raise ValueError(f"{', '.join(missing)} is required for the chosen authentication")
        return self


class HttpRequestPlugin(Plugin):
    manifest = PluginManifest(
        key="http_request",
        name="HTTP Request",
        description="Call an HTTP endpoint and emit its response.",
        category="network",
    )
    Config = HttpRequestConfig

    async def execute(self, ctx: PluginContext) -> PluginResult:
        cfg: HttpRequestConfig = ctx.config
        headers = dict(cfg.headers)
        params: dict[str, str] = {}
        auth: httpx.Auth | None = None

        async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
            match cfg.auth:
                case "basic":
                    auth = httpx.BasicAuth(cfg.auth_username, cfg.auth_password)
                case "bearer":
                    headers.setdefault("Authorization", f"Bearer {cfg.auth_token}")
                case "api_key":
                    target = params if cfg.auth_api_key_in == "query" else headers
                    target.setdefault(cfg.auth_api_key_name, cfg.auth_api_key_value)
                case "oauth2_client_credentials":
                    token = await _client_credentials_token(client, cfg, ctx)
                    headers.setdefault("Authorization", f"Bearer {token}")

            response = await client.request(
                cfg.method,
                cfg.url,
                headers=headers,
                params=params or None,
                json=cfg.body,
                auth=auth,
            )
        if cfg.fail_on_error_status:
            response.raise_for_status()
        try:
            body = response.json()
        except ValueError:
            body = response.text
        return PluginResult.main(
            {"status": response.status_code, "headers": dict(response.headers), "body": body}
        )


async def _client_credentials_token(
    client: httpx.AsyncClient, cfg: HttpRequestConfig, ctx: PluginContext
) -> str:
    """Exchange the client credentials for an access token (RFC 6749 §4.4)."""
    form: dict[str, str] = {"grant_type": "client_credentials"}
    if cfg.auth_scope:
        form["scope"] = cfg.auth_scope
    auth: httpx.Auth | None = None
    if cfg.auth_client_auth == "basic":
        auth = httpx.BasicAuth(cfg.auth_client_id, cfg.auth_client_secret)
    else:
        form["client_id"] = cfg.auth_client_id
        form["client_secret"] = cfg.auth_client_secret

    ctx.logger.info("requesting an OAuth2 token from %s", cfg.auth_token_url)
    response = await client.post(cfg.auth_token_url, data=form, auth=auth)
    if response.is_error:
        # The body carries the provider's reason ("invalid_scope", …); the status alone does not.
        raise RuntimeError(
            f"OAuth2 token request failed with HTTP {response.status_code}: {response.text[:400]}"
        )
    payload = response.json()
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not token:
        raise RuntimeError("the OAuth2 token response contained no access_token")
    return str(token)
