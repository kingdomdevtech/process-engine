---
name: Tests
description: pytest conventions, what each suite guards, and how to build fixtures
applyTo: "tests/**/*.py"
---

# Tests

`pytest` (pytest-asyncio in **`auto` mode** — an `async def test_…` needs no decorator).
`testpaths = ["tests"]`, so bare `pytest` runs everything. Single test:
`pytest tests/test_engine.py -k branching`.

- One file per seam, named after it. Add to the existing file rather than starting a new one
  unless the seam is genuinely new.
- Build a `ProcessDefinition` in the test rather than loading a fixture file — `position` is
  designer-owned and may be left at (0,0).
- Engine tests drive `Engine` directly; API tests go through `create_app(db, registry)` with a
  temp SQLite database. Never rely on a module-level `app` — there isn't one.
- Tests rely on `.process_engine_auth` and `.process_engine_key` being auto-generated. Both are
  gitignored; don't commit or hard-code them.
- Prefer a real in-process run over mocking the engine. Mock only at the outside edge (SMTP,
  boto3, COM, HTTP).

What the suites guard, so a change lands in the right one:

| File | Guards |
| --- | --- |
| `test_engine.py` | DAG execution, port branching, skip cascade, retries, error routing |
| `test_preview.py` | `preview_step` builds input identically to a real run |
| `test_config_forms.py` | Generated schemas: `show_if` targets exist, enum wording, widget/type agreement, no required-but-hidden field, retired-key validators |
| `test_registry.py` | The three discovery paths and `manifest.aliases` |
| `test_notifications.py` | One email per run end, snapshotting, silent sub-process runs, `created_by` handling |
| `test_expressions.py` | `{{ dotted.path }}` resolution and type preservation |
| `test_file_plugins.py` | Sandbox containment, including entries discovered by a walk |
| `test_api.py` / `test_users.py` / `test_sso.py` / `test_http_auth.py` | Routes, roles, session revocation, OIDC |
| `test_scheduler.py` | Cron/trigger firing against the latest published version |

A new plugin needs behaviour tests **and** a pass through `test_config_forms.py`.
