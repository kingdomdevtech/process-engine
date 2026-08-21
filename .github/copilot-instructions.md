# Process Engine — repository instructions

n8n-style drag-and-drop workflow automation in Python. Domain language, used everywhere:
a **Process** is a graph of **Steps** wired by **Connections**; each Step is configured from
a **Plugin** (the pluggable unit of behaviour and the project's main extension seam). A run
is a **ProcessInstance** holding one **StepRun** per step. Processes also carry **Triggers**
(schedule/webhook) fired against the latest *published* version.

Use those words. Don't call a Process a "workflow" or a Step a "node" in code, comments or
UI copy — the designer canvas is the only place "node" means anything.

## Layers — keep them separate

1. **Definition** (`src/process_engine/models.py`) — `ProcessDefinition` is a serializable
   JSON document. No UI concerns, no runtime state. Designer `position` fields are the only
   designer-owned data in it.
2. **Designer** (`designer/`) — React 18 + react-router + @xyflow/react + Tailwind v4, plain
   JSX, no TypeScript. See `.github/instructions/designer.instructions.md`.
3. **Engine** (`src/process_engine/engine.py`) — executes a definition and returns a
   `ProcessInstance`. It never touches storage or HTTP. `api.py` composes engine + `storage.py`
   + registry through `create_app(db, registry)`; there is deliberately **no module-level
   `app`**, so importing the package has no side effects. `__main__.py` builds one.

Notifications, scheduling and persistence are composed in `api.py` around a pure engine. If
you find yourself importing `storage` or `smtplib` into `engine.py`, the design has been lost.

## Commands (PowerShell, Windows-first)

```powershell
.\.venv\Scripts\Activate.ps1                 # venv lives at .venv
pip install -e ".[dev,excel,mysql]"          # excel=pywin32 (Windows only), mysql=PyMySQL
pytest                                       # full suite
pytest tests/test_engine.py -k branching     # one test
python examples\demo.py                      # run a process end to end, no server
python -m process_engine                     # API on http://127.0.0.1:8000 (docs at /docs)
cd designer; npm run dev                     # designer on :5173, proxies /api and /help to :8000
cd designer; npm run build                   # verify the frontend compiles
```

Async tests need no decorator — pytest-asyncio runs in `auto` mode. A new plugin needs an API
restart: all three discovery paths resolve at startup only.

## Invariants — changing these breaks saved data or the design

- **The graph is a DAG.** `validate()` rejects cycles. Iteration is the `for_each` plugin
  running a published sub-process per item via `ctx.run_subprocess`. Never add loop edges.
- **A step runs when every incoming connection is settled** (upstream emitted on that port, or
  the path is dead). Zero deliveries → the step is SKIPPED and the skip cascades. Condition
  branching depends on this; skipped branches are not a bug to fix. Ready steps run in
  parallel — one task per step, each plugin attempt on a worker thread
  (`PROCESS_ENGINE_STEP_WORKERS` sizes the pool) — so connections are the only ordering
  guarantee.
- **Published versions are immutable.** `processes` holds the editable draft only; `publish`
  snapshots into `process_versions` and bumps `latest_version`. Runs record the version they
  used and execute the latest published one unless `draft: true`.
- **Preview and real runs must build step input identically** — both go through
  `combine_deliveries()` / `deliveries_from_run()`. Change those, never one call site.
  `Engine.preview_step()` really executes the plugin, so previewing a step with side effects
  performs them (the same trade-off n8n makes).
- **Renaming a plugin key breaks saved definitions.** Add the old key to `manifest.aliases`
  instead (see `send_email_smtp` → `send_email`). Aliases resolve in `registry.get()` and
  `__contains__` but are excluded from `manifests()`, so retired keys keep working without
  reappearing in the palette. Reshaping a config field is just as breaking — pair it with a
  `model_validator(mode="before")` mapping the retired keys.
- **Every path a plugin takes must go through `workspace.resolve()`**, never `Path(cfg.x)`.
  A plugin that walks a tree re-checks each entry it discovers, not just the folder it was
  handed. `excel_refresh` and `send_email`'s `attachments` predate the sandbox and are a
  deliberate migration, not a drive-by fix.
- **Expressions are lookups, never eval.** `{{ dotted.path }}` resolves against
  `{trigger, steps, variables, input}` just before execution (`expressions.py`), *then* the
  result is validated against the plugin's `Config`. A whole-string expression keeps its type.
- **Secrets resolve at execution time only.** The API exposes secret *names*; steps reference
  them as `{{ secrets.name }}`.
- **Durability**: `api.py` passes `on_update=db.save_instance`, so state persists after every
  step. RUNNING instances auto-resume on startup by replaying SUCCEEDED steps from recorded
  outputs (side effects are at-least-once). `RunControl` gives cooperative pause/cancel
  between steps.
- **Queue mode**: `PROCESS_ENGINE_RUN_WORKERS=N` executes background runs in N spawned worker
  processes (`worker.py`, one GIL each). Fresh runs persist as PENDING placeholders before
  dispatch (the worker resumes that row; startup recovery re-dispatches PENDING and RUNNING),
  pause/cancel travel through the `run_signals` table, and each worker owns its run's
  persistence and notifications. Foreground runs and previews stay in the API process.
- **Auth**: every `/api` route needs a bearer credential *except* `/api/auth/login`, the SSO
  endpoints, and `/api/hooks/*` (webhook capability URLs, deliberately token-free).
  Security-shaped configuration stays env-only — never make the sandbox root or auth settings
  editable through the API.
- **Process access**: an admin sees every process; anyone else sees what they created plus
  what is in `shared_with`, and sharing carries the same rights including re-sharing. Route
  reads through `_get_or_404(process_id, request)` and listings through `_visible_processes`
  — a new `/processes/...` route that skips them is a leak. No-access is **404, not 403**
  (a 403 confirms the id is real). `created_by`/`shared_with` are server-owned: carry them
  over on PUT, never take them from the client.
- **Settings is admin-only** (mail relay, file sandbox, users, plugin inventory). Per-user
  things live elsewhere on purpose — theme and the guided tour in the account menu, secrets
  on their own page — so do not add an editor-facing control to Settings. `GET /api/plugins`,
  `GET /api/secrets` and `GET /api/notifications/mail` must stay readable by editors: the
  palette, the config forms and the editor's notifications panel depend on them.

## Working style

- Read `CLAUDE.md` for the long form; it is the authoritative design document and explains the
  reasoning behind everything above. `README.md` is the user-facing overview.
- Match the surrounding prose and comment style: comments explain *why* a thing is the way it
  is, not what the line does. Don't add narration to code that reads fine.
- Prefer editing an existing module over adding one. This codebase is small on purpose.
- Docstrings are full sentences and are read by people configuring steps, not just developers.
- Update `docs/runbook.html` when operational behaviour or a plugin changes, and
  `docs/guided-tour.html` + `tour.js` together when the interface moves.
