"""Where this deployment lives, as far as a link in an email is concerned.

Both tiers need this and neither owns it: the API builds SSO redirects from it,
and an engine host puts "Open the run" links into notification email without
ever serving HTTP itself. Env-only, like the file sandbox — a URL a signed-in
user could edit is a URL an attacker could point at themselves.
"""

from __future__ import annotations

import os


def public_url() -> str:
    """Origin the browser reaches the *API* on — what an OIDC callback registers."""
    return os.environ.get("PROCESS_ENGINE_PUBLIC_URL", "http://localhost:5173").rstrip("/")


def designer_url() -> str:
    """Origin the designer is served from — where login lands and run links point.

    The same origin as the API unless the designer is deployed separately (a
    static host on another machine), in which case it is set explicitly. On an
    engine host, where nothing is served, setting it is the only way run links
    in notification email can point anywhere useful.
    """
    return os.environ.get("PROCESS_ENGINE_DESIGNER_URL", public_url()).rstrip("/")
