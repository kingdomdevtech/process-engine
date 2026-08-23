# Process Engine — repository instructions

n8n-style drag-and-drop workflow automation in Python. Domain language, used everywhere:
a **Process** is a graph of **Steps** wired by **Connections**; each Step is configured from
a **Plugin** (the pluggable unit of behaviour and the project's main extension seam). A run
is a **ProcessInstance** holding one **StepRun** per step. Processes also carry **Triggers**
(schedule/webhook) fired against the latest _published_ version.

Use those words. Don't call a Process a "workflow" or a Step a "node" in code, comments or
UI copy — the designer canvas is the only place "node" means anything.

## Three distributions, and what each host installs

Three Python packages under `packages/`, plus the npm app in `designer/`. Which package a
module belongs to is a **deployment decision**: it decides which machines have to install it.
`docs/architecture.html` draws all of this.

| Package | Answers | Installed on |
| --- | --- | --- |
| `process-engine-core` | what a process *is* — `models`, `storage`, `jobs`, `plugin`, `registry`, `validation`, `ui`, `workspace`, `secrets_store`, `security`, `urls`, `notifications`, and `plugins/` (manifests + `Config`, no behaviour) | every host |
| `process-engine` | what runs one — `engine`, `worker`, `scheduler`, `expressions`, and `plugins/` (the implementations, with `execute`) | engine hosts |
| `process-engine-api` | the designer's backend — `app`, `users`, `sso`, `datapicker` | the Linux container |

Both tiers depend on core; **neither depends on the other**. The API's distribution contains
no engine and no plugin implementation, so "the container cannot execute a step" is a property
of the install, not a promise — there is no `execute()` in the wheel to call. A
`fastapi`/`uvicorn` import inside `process_engine` is a design break; `process_engine_api`
importing `process_engine` is a worse one. Ask **"which hosts have to install this?"** before
adding a module — if the answer is "both", it belongs in core (that is why `urls.py`,
`notifications.py` and `workspace.py` live there).

The engine reads everything from the database, sub-process definitions included
(`definition_resolver=db.get_version`) — it never calls the API for anything.
`test_the_engine_reaches_the_database_without_the_api` proves it by running a queued job in a
fresh interpreter with `process_engine_api`/`fastapi`/`uvicorn`/`starlette` unimportable.

## Layers — keep them separate

1. **Definition** (core's `models.py`) — `ProcessDefinition` is a serializable JSON document.
   No UI concerns, no runtime state. Designer `position` fields are the only designer-owned
   data in it.
2. **Designer** (`designer/`) — React 18 + react-router + @xyflow/react + Tailwind v4, plain
   JSX, no TypeScript. See `.github/instructions/designer.instructions.md`.
3. **Engine** (`process_engine/engine.py`) — executes a definition and returns a
   `ProcessInstance`. It never touches storage or HTTP. `worker.py` composes engine +
   `storage.py` + registry, and that is the engine host's whole program.
   `process_engine_api/app.py` composes the same storage and a registry of plugin *specs*
   through `create_app(db, registry)` — but no engine, because its distribution has none.
   There is deliberately **no module-level `app`**, so importing the package has no side
   effects; `process_engine_api/__main__.py` builds one.

Notifications, scheduling and persistence are composed *around* a pure engine, by `worker.py`
for the run it claims. If you find yourself importing `storage` or `smtplib` into `engine.py`,
the design has been lost.

## Commands (PowerShell, Windows-first)

```powershell
.\.venv\Scripts\Activate.ps1                 # venv lives at .venv
pip install -r requirements-dev.txt          # all three packages, editable, plus pytest
pytest                                       # full suite
pytest tests/test_engine.py -k branching     # one test
python examples\demo.py                      # run a process end to end, no server
python -m process_engine_api                 # API on http://127.0.0.1:8000 (docs at /docs)
python -m process_engine                     # the engine: claims queued jobs, fires cron
                                             #   nothing runs until this is up
cd designer; npm run dev                     # designer on :5173, proxies /api and /help to :8000
cd designer; npm run build                   # verify the frontend compiles
cd designer; npx playwright test             # UI specs; needs API :8000, an engine, vite :5173
docker compose up -d --build                 # designer+API container -> :8000
```

Async tests need no decorator — pytest-asyncio runs in `auto` mode. A new plugin needs a
restart of the API _and_ every engine: both discovery paths resolve at startup only.

## Browser test rule

Playwright tests must use the real designer flow end-to-end: log in in the browser, add steps
from the palette, configure them in the UI, save through the app, and assert on the designer's
visible state. Never call the API directly from a Playwright test with `fetch()` or raw HTTP
requests — that skips the actual user path and hides the bug the browser would trigger.

Three assertions are **mandatory in every UI spec**; a green report without them is not a
pass. The helpers are in `designer/tests/support/designer.js` — use them rather than writing
the assertion again.

- `expectRunPassed(page, steps, { skipped })` — no failed step, and `Steps · n/n` counting only
  the succeeded ones. A step whose upstream delivered nothing is skipped, not failed, and the run
  still reports success, so checking only the run badge passes while half the process never ran.
  A Condition's untaken branch is the one honest skip: declare it with `{ skipped: n }` and the
  count is checked *exactly* — accounted for, never tolerated. Pending or running means the poll
  gave up early.
- `expectNoDisconnectedStep(page)` — before every save and after the run. Every step is
  reached by the trigger box or another step. Assert it per step id with a retrying
  `toHaveCount`, never one `evaluateAll` snapshot of the graph: the canvas re-renders while
  the editor works.
- Under a minute. `timeout: 60_000` in `playwright.config.js`, 30 s for a queued run. A spec
  that needs longer is reporting a stuck engine or a hanging wait — let it fail. Never raise
  the ceiling with `test.setTimeout`; split a long flow into two `test()`s in a
  `test.describe.serial` so each keeps its own budget.

Read the API token in Node via `authToken()` (env, then `.env`, then `.process_engine_auth`) —
never hard-code one, never fetch it from the page. Tidy the canvas (Ctrl+Shift+L) before
opening a step: palette drops overlap. Address controls by role
(`getByRole('textbox', { name: 'Query' })`) — the **ƒx** button's `aria-label` contains the
field title, so `getByLabel` matches two elements. An untyped (`Any`) field renders the value
editor and commits on **blur** — `fill()` then `blur()`.

`designer/tests/demo/` builds the demo processes. A spec there leaves a real published process
behind, so it uses a fixed name in the `demo` folder and clears the previous one with
`removeDemoProcess` — which moves it out of the folder first, because the API refuses to delete
one that is in it, and is therefore also the test of that guard. Any data the demo needs is
created by a step **in the process**, never by an API call.
`.github/prompts/new-ui-test.prompt.md` is the full walkthrough for writing one.

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
- **Every change to a process is audited, and a saved draft can be restored.** `process_audits`
  takes one row per `created | updated | published | shared | moved | restored`, with the actor,
  a summary and — for the kinds that changed the draft — a snapshot of it. `POST
  /processes/{id}/restore/{audit_id}` writes that snapshot back as a *new* draft plus a
  `restored` row: history only ever grows, and restoring never rewrites a published version.
  Rows are owned by the process and die with it. Write the audit where the change happens, not
  from the designer — the API is the only thing that can promise the trail is complete.
- **A connection carries the port the source really emits.** `validate()` rejects a
  `source_port` the source plugin's manifest does not declare (`error` aside), so anything
  authoring an arrow — the designer's `flowEdge`/`defaultPort`, a test, a migration — must take
  the step's `main` where it has one and otherwise its first output. Assuming `main` writes a
  definition that saves and then cannot be published: a Condition has only `true`/`false`.
- **A process in the `demo` folder cannot be deleted.** `PROTECTED_FOLDERS` in
  `process_engine_api/app.py` is the authority; the delete route answers **409** and
  `_visible_processes` stamps `protected` on each row so the designer can disable its own menu
  item. Moving it out is deliberately *not* guarded — that is the way out, and it leaves a
  `moved` audit row saying who did it. Never let the frontend decide which folders are
  protected, and never work around the guard by deleting the rows directly.
- **Preview and real runs must build step input identically** — both go through
  `combine_deliveries()` / `deliveries_from_run()`. Change those, never one call site.
  `Engine.preview_step()` really executes the plugin, so previewing a step with side effects
  performs them (the same trade-off n8n makes).
- **Renaming a plugin key breaks saved definitions.** Add the old key to `manifest.aliases`
  instead (see `send_email_smtp` → `send_email`). Aliases resolve in `registry.get()` and
  `__contains__` but are excluded from `manifests()`, so retired keys keep working without
  reappearing in the palette. Reshaping a config field is just as breaking — pair it with a
  `model_validator(mode="before")` mapping the retired keys.
- **A new plugin lives in this repository, and it is two modules**, one per side of the
  deployment seam: the **spec** (`manifest` + `Config`, no behaviour) in
  `packages/process_engine_core/plugins/<key>.py`, listed in `BUILTIN_SPECS`; the
  **implementation** (`class XPlugin(XSpec, Plugin)`, adding `async execute`) in
  `packages/process_engine/plugins/<key>.py`, listed in `BUILTIN_PLUGINS`. The API loads
  `spec_registry()`, an engine loads `default_registry()`, and both build the same
  `PluginRegistry` — so every key in the palette is a key some engine can run. There is
  deliberately no drop-in folder: a step runs on whichever host claims it, so it cannot depend
  on a loose file dropped on one of them. An entry-point pip package
  (`examples/hello-plugin`) is the only alternative, and has to be installed on every host
  that executes.
- **Every path a plugin takes must go through `workspace.resolve()`**, never `Path(cfg.x)`.
  A plugin that walks a tree re-checks each entry it discovers, not just the folder it was
  handed. `excel_refresh` and `send_email`'s `attachments` predate the sandbox and are a
  deliberate migration, not a drive-by fix.
- **Expressions are lookups, never eval.** `{{ dotted.path }}` resolves against
  `{trigger, steps, variables, input}` just before execution (`expressions.py`), _then_ the
  result is validated against the plugin's `Config`. A whole-string expression keeps its type.
- **Secrets resolve at execution time only.** The API exposes secret _names_; steps reference
  them as `{{ secrets.name }}`.
- **Durability**: the worker passes `on_update=db.save_instance`, so state persists after every
  step. RUNNING instances are re-queued on startup and resume by replaying SUCCEEDED steps from
  recorded outputs (side effects are at-least-once). `RunControl` gives cooperative pause/cancel
  between steps. A fresh queued run is persisted as a PENDING placeholder **before** dispatch
  (`enqueue_run`) so it is visible at once and re-dispatchable after a restart.
- **There is one execution mode, and it is not a mode.** The API writes **every** job to the
  `job_queue` table and executes nothing itself — background runs, the designer's Run button
  and single-step previews alike. Nothing happens until an engine is up. There is no switch,
  and no environment variable changes it. Engines run `python -m process_engine` to claim and execute
  (`claim_job`'s guarded `UPDATE` is the lock; `_renewed_claim` keeps touching the row so a
  slow run is not mistaken for a dead one; a lapsed lease lets another engine reclaim and
  replay). SQLite is fine for one machine; a shared MySQL/Postgres is required across hosts.
  - A worker owns the whole run: engine, per-step persistence, and that run's notifications.
    Pause/cancel travel through the `run_signals` table. `init_worker` rebuilds its stack from
    env vars alone (workers are spawned, never forked), which is what lets it run elsewhere.
  - A foreground run returns the **PENDING instance**, and the designer polls it.
  - A preview returns **202** plus a poll URL (`/previews/{id}`); the engine writes the answer
    into the job row and `GET` collects it. Both paths build the payload with
    `engine.preview_result`, so a client cannot tell which host answered. Never let a settled
    reply row become claimable as work again.
  - **Cron belongs to the engines**: due times live in `schedule_state` and `claim_schedule`'s
    guarded `UPDATE` makes a firing happen once however many are watching, so `create_app`
    starts no `Scheduler` at all — it could not run what one fired. A window nobody was up for
    is skipped, not owed.
  - Restart recovery skips runs that still have a job row — that host is still working.
  - Engines heartbeat into `workers`; `GET /api/queue` and `GET /api/workers` exist so the
    designer can say "nothing is listening" instead of spinning.
- **Split deployment**: a Linux container (designer + `process-engine-api` behind nginx, one
  origin — see `Dockerfile`, `deploy/nginx.conf`) and a Windows host running the engine. The
  install enforces it: the container takes `process_engine_core[mysql]` + `process_engine_api`
  and never `process_engine`; the Windows host takes `process_engine_core` +
  `process_engine[excel,mysql]` and never the API. Same
  `PROCESS_ENGINE_SECRET_KEY` on both or the engine cannot decrypt the secrets steps use. To
  serve the designer apart from its API, build it with `VITE_API_BASE=<api origin>`
  (`designer/src/api.js` `engineUrl` routes every API call, webhook/SSO/tour URL there).
  `PROCESS_ENGINE_PUBLIC_URL` is the API's own origin (OIDC callback);
  `PROCESS_ENGINE_DESIGNER_URL` is where SSO lands and run-links point. Auth is a
  `localStorage` Bearer token, not a cookie, so CORS stays `*`.
- **Auth**: every `/api` route needs a bearer credential _except_ `/api/auth/login`, the SSO
  endpoints, `/api/health` (a container probe holds no credential, so it answers liveness and
  nothing else) and `/api/hooks/*` (webhook capability URLs, deliberately token-free).
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
- Match the surrounding prose and comment style: comments explain _why_ a thing is the way it
  is, not what the line does. Don't add narration to code that reads fine.
- Prefer editing an existing module over adding one. This codebase is small on purpose.
- Docstrings are full sentences and are read by people configuring steps, not just developers.
- Update `docs/runbook.html` when operational behaviour or a plugin changes,
  `docs/developer-guide.html` when the plugin contract moves, `docs/architecture.html` when a
  module changes packages or a box on one of its diagrams moves, and `docs/guided-tour.html` +
  `tour.js` together when the interface moves.
