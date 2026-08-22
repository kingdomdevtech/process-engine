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

from typing import Any

import httpx
from process_engine_core.plugin import Plugin, PluginContext, PluginResult
from process_engine_core.plugins.http_request import HttpRequestConfig, HttpRequestSpec


class HttpRequestPlugin(HttpRequestSpec, Plugin):
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
