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
- Engine tests drive `Engine` directly with `default_registry()`; API tests go through
  `process_engine_api.create_app(db, registry)` with a temp SQLite database. Never rely on a
  module-level `app` — there isn't one.
- An API test never gets a finished run back. Everything is queued, so a route under test
  answers with a PENDING instance or a 202, and the test then drives a worker to settle it.
  Asserting on a run's result straight out of a POST is testing a behaviour that no longer
  exists.
- Queue tests build the same stack the engine host does (`worker.init_worker` /
  `worker.serve` against a temp database), not a mock of it: the point of those tests is that a
  second process, given nothing but the database, reaches the same result.
- Tests rely on `.process_engine_auth` and `.process_engine_key` being auto-generated. Both are
  gitignored; don't commit or hard-code them.
- Prefer a real in-process run over mocking the engine. Mock only at the outside edge (SMTP,
  boto3, COM, HTTP).
- Browser/Playwright tests are designer-driven. They log in through the UI, add steps from the
  palette, configure them in the editor, save via the app, and assert on the visible process
  state. They never call `/api/*` directly from the script — a direct API request is not a
  user flow and is explicitly disallowed.
- A UI spec passes only with all three mandatory gates, from
  `designer/tests/support/designer.js`: `expectRunPassed(page, steps)` (no failed **and no
  skipped** step — `Steps · n/n`, Succeeded the only badge), `expectNoDisconnectedStep(page)`
  (every step reached by the trigger box or another step, asserted per step id with a retrying
  `toHaveCount`), and the 60-second per-test ceiling in `playwright.config.js` — a slow UI spec
  is a bug report, so never lift it with `test.setTimeout`.

What the suites guard, so a change lands in the right one:

| File | Guards |
| --- | --- |
| `test_engine.py` | DAG execution, port branching, skip cascade, retries, error routing |
| `test_preview.py` | `preview_step` builds input identically to a real run |
| `test_config_forms.py` | Generated schemas: `show_if` targets exist, enum wording, widget/type agreement, no required-but-hidden field, retired-key validators |
| `test_registry.py` | Both discovery paths, `manifest.aliases`, that the two tiers advertise exactly the same plugin keys, that only the engine's registry can execute, and that no drop-in folder came back |
| `test_notifications.py` | One email per run end, snapshotting, silent sub-process runs, `created_by` handling |
| `test_expressions.py` | `{{ dotted.path }}` resolution and type preservation |
| `test_file_plugins.py` | Sandbox containment, including entries discovered by a walk |
| `test_api.py` / `test_users.py` / `test_sso.py` / `test_http_auth.py` | Routes, roles, session revocation, OIDC |
| `test_sharing.py` | Who can see a process and its runs; 404-not-403 |
| `test_scheduler.py` | Cron/trigger firing against the latest published version, and firing once when several schedulers watch one database |
| `test_worker.py` | The queue: claim/lease, cross-process pause/cancel, queued previews, an engine host firing its own schedules, and that the engine runs a job with the whole web stack unimportable |

A new plugin needs behaviour tests **and** a pass through `test_config_forms.py` — and a spec
with no implementation (or the reverse) fails `test_registry.py` before either.
