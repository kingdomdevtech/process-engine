---
name: Python backend
description: Style, typing, async and composition conventions for the engine, API and storage
applyTo: "**/*.py"
---

# Python conventions

Python 3.11+, pydantic v2, SQLAlchemy 2.0, FastAPI (in `process-engine-api` only). No linter
or formatter is configured — match the file you are editing.

- `from __future__ import annotations` where the module already uses it; modern built-in
  generics (`list[str]`, `str | None`), never `typing.List` / `Optional`.
- Type every public signature. Pydantic models are the schema — don't hand-write parallel dicts.
- `match` statements over long `if/elif` chains on a literal (see `condition._evaluate`).
- Module-private helpers are `_`-prefixed and defined below the public class they support.
- Comments explain *why*: the constraint, the failure it avoids, the trade-off taken. Skip
  comments that restate the line. Module docstrings carry the design reasoning (`ui.py` is the
  model).
- No import side effects. `create_app(db, registry)` composes the app; `__main__.py` is the only
  place a live one is built.

## Async

Everything on the request/execution path is `async`. Any blocking call — COM, PyMySQL, smtplib,
boto3, filesystem walks over network shares — goes through `await asyncio.to_thread(...)`. The
engine runs each plugin attempt on a worker thread with its own event loop
(`PROCESS_ENGINE_STEP_WORKERS` sizes the pool), so blocking code hurts only its own step — but
`to_thread` stays the rule: a blocked loop cannot enforce `timeout_seconds`.

## Layering

Three distributions under `packages/`: `process-engine-core` (what a process *is* — models,
storage, jobs, the plugin contract, `ui`, `workspace`, `urls`, `notifications`, and the plugin
*specs*), `process-engine` (what runs one — engine, worker, scheduler, expressions, the plugin
*implementations*) and `process-engine-api` (the designer's backend). Both tiers import core;
**neither imports the other**, and the API distribution contains no engine at all — that is
what makes "the container cannot execute a step" a fact about the install rather than a rule
somebody has to remember. FastAPI and uvicorn belong to the API package; an import of either
inside `process_engine` or `process_engine_core` breaks the Windows engine host, which installs
no web stack. Before adding a module, ask **"which hosts have to install this?"** — if the
answer is "both", it belongs in core.

`engine.py` executes a definition and never imports storage, HTTP, or email. Persistence
(`on_update=db.save_instance`), scheduling and notifications are wired *around* a pure engine
by `worker.py`, which owns every run. Keep new cross-cutting behaviour on that seam, and where
the API needs part of it too, in a function in core that both call (`jobs.enqueue_run`) rather
than twice.

## Compatibility

Definitions are stored JSON documents, so field names are a wire format:

- Retiring a plugin key → add it to `manifest.aliases`, don't rename.
- Reshaping a config field → add a `model_validator(mode="before")` mapping the old keys
  (`send_email.py`, `_mysql.py`, `mysql_execute.py` are the examples) and cover it in
  `tests/test_config_forms.py`.
- Published versions in `process_versions` are immutable; migrations act on the draft.

## Secrets and paths

Secrets are Fernet-encrypted rows; the API exposes names only and `{{ secrets.x }}` resolves at
execution time. Any filesystem path from step config goes through `workspace.resolve()`. Neither
the sandbox root nor auth configuration is editable through the API — those stay env-only.
