"""Single sign-on via OpenID Connect: Microsoft Entra ID and Google.

A provider appears on the login screen when its client id/secret env vars
are set — no code changes:

    PROCESS_ENGINE_OIDC_GOOGLE_CLIENT_ID / PROCESS_ENGINE_OIDC_GOOGLE_CLIENT_SECRET
    PROCESS_ENGINE_OIDC_ENTRA_CLIENT_ID  / PROCESS_ENGINE_OIDC_ENTRA_CLIENT_SECRET
    PROCESS_ENGINE_OIDC_ENTRA_TENANT     (default "common")
    PROCESS_ENGINE_PUBLIC_URL            base URL the browser reaches the engine on
                                         (default http://localhost:5173, the dev proxy)
    PROCESS_ENGINE_DESIGNER_URL          base URL the designer is served from
                                         (default: same as PUBLIC_URL — single origin)
    PROCESS_ENGINE_SSO_AUTO_PROVISION    "true" to auto-create unknown users as editors

Register the callback URL with the provider:
    {PUBLIC_URL}/api/auth/sso/google/callback
    {PUBLIC_URL}/api/auth/sso/entra/callback

Flow: /api/auth/sso/{provider}/login redirects to the provider; the callback
exchanges the code server-side (confidential client), reads the verified
email from the userinfo endpoint, maps it to a local user (username ==
email), and hands the designer a normal session token via the URL fragment.
By default the email must belong to an existing, enabled user.

PUBLIC_URL is the engine's own origin — where the provider sends the callback,
so it is what gets registered above. DESIGNER_URL is where the browser lands
after login; the two are one origin unless the designer is deployed separately.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

# both tiers need these, so they live with the engine (a worker puts run links
# into notification email); re-exported here because this is where they are used
from process_engine_core.urls import designer_url, public_url  # noqa: F401


@dataclass(frozen=True)
class SSOProvider:
    key: str
    name: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    client_id: str
    client_secret: str
    scopes: str = "openid email profile"


def configured_providers() -> dict[str, SSOProvider]:
    providers: dict[str, SSOProvider] = {}
    google_id = os.environ.get("PROCESS_ENGINE_OIDC_GOOGLE_CLIENT_ID")
    google_secret = os.environ.get("PROCESS_ENGINE_OIDC_GOOGLE_CLIENT_SECRET")
    if google_id and google_secret:
        providers["google"] = SSOProvider(
            key="google",
            name="Google",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
            client_id=google_id,
            client_secret=google_secret,
        )
    entra_id = os.environ.get("PROCESS_ENGINE_OIDC_ENTRA_CLIENT_ID")
    entra_secret = os.environ.get("PROCESS_ENGINE_OIDC_ENTRA_CLIENT_SECRET")
    if entra_id and entra_secret:
        tenant = os.environ.get("PROCESS_ENGINE_OIDC_ENTRA_TENANT", "common")
        base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
        providers["entra"] = SSOProvider(
            key="entra",
            name="Microsoft",
            authorize_url=f"{base}/authorize",
            token_url=f"{base}/token",
            userinfo_url="https://graph.microsoft.com/oidc/userinfo",
            client_id=entra_id,
            client_secret=entra_secret,
        )
    return providers


def auto_provision_enabled() -> bool:
    return os.environ.get("PROCESS_ENGINE_SSO_AUTO_PROVISION", "").lower() in ("1", "true", "yes")


async def fetch_user_email(provider: SSOProvider, code: str, redirect_uri: str) -> str:
    """Exchange the authorization code and return the provider-verified email."""
    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(
            provider.token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": provider.client_id,
                "client_secret": provider.client_secret,
                "redirect_uri": redirect_uri,
            },
        )
        token_response.raise_for_status()
        access_token = token_response.json().get("access_token", "")
        userinfo_response = await client.get(
            provider.userinfo_url, headers={"Authorization": f"Bearer {access_token}"}
        )
        userinfo_response.raise_for_status()
        claims = userinfo_response.json()
    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if not email:
        raise ValueError("identity provider returned no email address")
    if claims.get("email_verified") is False:
        raise ValueError(f"email {email} is not verified with the provider")
    return email
