"""Call an HTTP endpoint — the form half.

``auth`` selects one scheme and ``show_if`` hides the rest, so a definition can
never carry two half-configured credentials.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ..plugin import PluginManifest, PluginSpec
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


class HttpRequestSpec(PluginSpec):
    manifest = PluginManifest(
        key="http_request",
        name="HTTP Request",
        description="Call an HTTP endpoint and emit its response.",
        category="network",
    )
    Config = HttpRequestConfig
