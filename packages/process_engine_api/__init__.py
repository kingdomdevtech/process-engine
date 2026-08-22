"""Designer API: the HTTP surface the designer talks to.

The deployable half that faces people. It is deployed *with* the designer — one
Linux container serving the built React app and this API — and it owns
everything that only exists because there is a browser: sign-in and sessions,
SSO, the process/run/secret endpoints, webhook URLs, and the expression picker.

It depends on ``process_engine_core`` and **not** on ``process_engine``: this
distribution contains no engine and no plugin implementation, so nothing here
can execute a step. Asking for a run writes a job to the shared database and an
engine host claims it — which is what lets that host be a Windows box with no
web stack on it at all, running the Excel/COM plugins where they work.

Create the app with ``create_app()`` or run ``python -m process_engine_api``.
"""

from .app import create_app

__all__ = ["create_app"]
__version__ = "0.1.0"
