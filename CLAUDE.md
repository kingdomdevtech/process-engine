# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

n8n-style drag-and-drop workflow automation in Python. Domain language: a **Process**
(workflow) is a graph of **Steps** wired by **Connections**; each Step is configured from a
**Plugin** — the pluggable unit of behaviour and the project's main extension seam. A run is a
**ProcessInstance** containing one **StepRun** per step. Processes also carry **Triggers**
(schedule/webhook) fired against the latest published version.

## Commands

```powershell
.\.venv\Scripts\Activate.ps1                 # venv lives at .venv
pip install -r requirements-dev.txt          # all three packages, editable, plus pytest
pip install -e examples/hello-plugin         # the entry-point plugin some tests need

pytest                                       # full suite
pytest tests/test_engine.py -k branching     # single test
python examples\demo.py                      # run a process end-to-end, no server
python -m process_engine_api                 # API on http://127.0.0.1:8000 (docs at /docs)
python -m process_engine                     # the engine: claims queued jobs, fires cron
                                             #   nothing runs until this is up — see Queue below

cd designer; npm run dev                     # designer on :5173, proxies /api to :8000
cd designer; npm run build                   # verify the frontend compiles

docker compose up -d --build                 # designer+API container -> :8000
docker compose up -d mysql                   # or just the MySQL backend, then set
# $env:PROCESS_ENGINE_DB_URL = "mysql+pymysql://process_engine:process_engine@127.0.0.1:3306/process_engine"
```

Async tests need no decorator — pytest-asyncio runs in `auto` mode (pyproject.toml).

### Browser tests must go through the designer UI

Playwright/browser tests are a real user flow, not a backend smoke test. They must log in via
`/login`, use the palette and canvas in the designer, save through the app, and observe the UI
state. No test may call `fetch('/api/...')` or any backend endpoint directly from the browser
script — that bypasses the user path, hides the real validation errors, and makes the test lie.

```powershell
cd designer; npm install; npx playwright install chromium   # once
cd designer; npx playwright test                            # needs API :8000, an engine, and vite :5173
cd designer; npx playwright test mysql-for-each.spec.js --reporter=line
```

**Three things are mandatory in every UI spec, and a green Playwright report without them is
not a pass.** The helpers that assert them live in `designer/tests/support/designer.js`; use
those rather than rolling the assertion again:

- **No failed step and no skipped step** — `expectRunPassed(page, steps)`. "Skipped" is the
  quiet one: a step whose upstream delivered nothing is skipped rather than failed and the run
  still reports success, so a spec that only checks the run badge passes while half the process
  never happened. The gate is the timeline reading `Steps · n/n` with Succeeded as the only
  status badge in it — pending or running means the poll gave up early.
- **No disconnected step** — `expectNoDisconnectedStep(page)`, before every save and after the
  run. Every step is reached by the trigger box or another step; one that nothing points at
  never runs, and a canvas showing one is a process that silently does less than it looks like
  it does. Assert it per step id with a retrying `toHaveCount`, never from one `evaluateAll`
  snapshot of the whole graph: the canvas re-renders as the editor works and a snapshot read
  between two renders reports a graph that was never on screen.
- **Under a minute** — `timeout: 60_000` in `playwright.config.js`, and `RUN_TIMEOUT` of 30 s
  for a queued run. Building a process, publishing it, queueing a run and reading the timeline
  is seconds of work on a healthy stack, so a spec that needs longer is reporting a problem —
  an engine that is not claiming, a step that is retrying, a wait that is really a hang. Let it
  fail and say so rather than sitting there; do not raise the ceiling with `test.setTimeout`.

Credentials are read in Node, never fetched by the page: `authToken()` looks at
`PROCESS_ENGINE_AUTH_TOKEN`, then `.env`, then `.process_engine_auth`. Never hard-code one.

Two more rules that come out of what these specs actually catch. Tidy the canvas
(Ctrl+Shift+L) before opening any step — the palette drops steps around the middle of the view
where the cards overlap, so clicking one of a stack is ambiguous for a person and for the test
alike. And address a form control by role (`getByRole('textbox', { name: 'Query' })`), not by
label text: the **ƒx** button beside every field carries `aria-label="Insert a value from an
earlier step into <Title>"`, so `getByLabel('<Title>')` matches two elements.

## Three distributions, and what each host installs

The product is three Python packages under `packages/`, plus the npm app in `designer/`.
Which package a module belongs to is a **deployment decision**, not a tidiness one — it
decides which machines have to install it. `docs/architecture.html` draws all of this.

| Package | Answers | Installed on |
| --- | --- | --- |
| `process-engine-core` | what a process *is* — `models`, `storage`, `jobs`, `plugin`, `registry`, `validation`, `ui`, `workspace`, `secrets_store`, `security`, `urls`, `notifications`, and `plugins/` (manifests + `Config`, no behaviour) | every host |
| `process-engine` | what runs one — `engine`, `worker`, `scheduler`, `expressions`, and `plugins/` (the implementations, with `execute`) | engine hosts |
| `process-engine-api` | the designer's backend — `app`, `users`, `sso`, `datapicker` | the Linux container |

Both tiers depend on core; **neither depends on the other**, and the API's distribution
contains no engine and no plugin implementation at all. So "the container cannot execute a
step" is a property of the install rather than a promise — there is no `execute()` in the
wheel to call. Packaging enforces the separation, not review: a `fastapi`/`uvicorn` import
inside `process_engine` would be a design break, and `process_engine_api` importing
`process_engine` would be a worse one.

Ask **"which hosts have to install this?"** before adding a module. If the answer is "both",
it belongs in core — that is why `urls.py`, `notifications.py` and `workspace.py` live there
rather than beside the code that seems to own them.

Two tests in `test_worker.py` enforce this rather than trusting it, each running a fresh
interpreter with half the product made unimportable:

- `test_the_engine_reaches_the_database_without_the_api` runs a queued job to completion with
  `process_engine_api`, `fastapi`, `uvicorn` and `starlette` all blocked. Everything the
  engine needs it reads from the database, sub-process definitions included
  (`definition_resolver=db.get_version`), so it never calls the API — not for work, not for
  definitions, not for secrets.
- `test_the_api_serves_and_queues_without_the_engine_installed` is the mirror: with
  `process_engine` blocked, the API still answers the whole palette from the specs, stores a
  definition and publishes a run to the queue. Each script asserts its own import blocker
  works first, so neither can pass by proving nothing.

### Testing across the seam (`tests/conftest.py`)

Because the API executes nothing, a test that wants a *finished* run has to do what the
deployment does. `engine_host` is that: a fixture that claims jobs from the test's own
`Database` and runs them through the same `claim_job` → `execute_claimed` path `worker.serve`
uses. `engine_host.run(client, process_id, draft=True)` asks, drains and returns the finished
run; `.preview(...)` does the 202-then-poll. Each module's `make_client` attaches `client.db`
(and `client.notifier` where mail is under test) for it to find. Prefer this over calling the
`Engine` directly in an API test — it exercises the path production actually takes.

## Architecture

Three strictly separated layers; keep them that way:

1. **Definition** (`models.py`) — `ProcessDefinition` is a serializable JSON document. No UI
   or runtime state. Designer `position` fields are the only designer-owned data.
2. **Designer** (`designer/`, React + react-router + @xyflow/react + Tailwind v4, plain JSX) —
   a multi-page app: `/login`, `/app` dashboard, `/app/processes/:id` editor, `/app/runs`,
   `/app/secrets`, `/app/settings` (admin-only, guarded by `RequireAdmin`); `/` just
   redirects to `/app`. Styling is Tailwind utilities in the markup
   over one semantic palette declared twice (light / dark) at the top of `styles.css` and
   exposed as utilities through `@theme inline` — so `bg-surface`, `text-fg-muted`,
   `border-line` retheme themselves and no colour is ever written literally in a component.
   Tailwind is configured in that CSS file, not a JS config; `@layer components` there owns
   only the primitives repeated across screens (`.btn`, `.input`, `.card`, `.badge`,
   `.table`, `.nav-item`). Note `@apply` resolves utilities only — a component class cannot
   `@apply` another one. Theme is `light | dark | system`, stored in `pe_theme` by
   `theme.js` and applied pre-paint by the inline script in `index.html` (moving it would
   reintroduce a flash of light on load). Shared UI lives in `components/ui/` — `Modal`
   (focus-trapped) plus the `useDialogs()` promise-based `confirm`/`prompt` that replace
   `window.confirm`/`window.prompt`. The product name lives only in `brand.js`; plugin icons
   and category tints are a fallback lookup in `pluginMeta.jsx`, keyed by plugin key then
   category, so a new plugin still needs no frontend code. The palette and per-step config
   forms are generated from `GET /api/plugins` (manifest + each Plugin's
   `Config.model_json_schema()`); there is no per-plugin frontend code. Edge `sourceHandle`
   becomes `Connection.source_port`. `SchemaForm.jsx` picks each control from the JSON Schema
   type — `list[str]` is a chip editor, `dict[str, X]` a name/value editor — and a plugin
   refines that with the `x-ui` hints described under _Config forms_ below. Schema
   `format: "html"` on a string field renders the HTML editor — see `send_email_ses`'s
   `body_html`. `schemaExample.js` turns a config schema
   into the pre-configured JSON behind _Show example_ (JSON tab) and field placeholders; steer
   it with pydantic `Field(examples=[...])` rather than by special-casing a plugin in the
   designer. Selecting a step gives Input/Config/Output
   tabs (`StepInput` → `/steps/{id}/input`, `StepPanel`, `StepOutput` → `/steps/{id}/preview`);
   the **ƒx** button opens the picker fed by `/steps/{id}/picker`. "Where does this step's work
   come from?" is a question about the graph, so `StepInput`'s source select **edits** the
   graph rather than shadowing it: picking a step (or the trigger box) re-points the incoming
   arrow through `connectFrom`, and only steps this one cannot already reach are offered, since
   an arrow back would be a cycle the save rejects. A published *process* is offered too, but
   only for a step that can take one (`for_each`) — that is not an arrow on this canvas, so it
   is wired by writing the step's own `process_id` and leaving the incoming arrow, which still
   delivers the list, alone. `StepOutput` handles both
   preview shapes — a finished answer, or a `202` it then polls (`/previews/{id}`) while
   telling the user whether anything is listening; `Editor`'s `runDraft` does the same for a
   run that comes back non-terminal, so nothing in the designer knows which host executed.
   Undo/redo covers canvas
   structure only (drop/connect/delete/drag), by design. Validation badges come from
   client-side required-field checks plus `/validate`'s `detailed[].step_id`; step-level
   issues badge the node, process-level ones surface in a banner over the canvas. `position`
   is designer-owned, so a definition built by the API or a test has every step at (0,0) —
   `layoutGraph` in `layout.js` lays those out in dependency order on load (`needsLayout`
   gates it) without writing back. That same function backs the _Tidy up steps_ command
   (Ctrl+Shift+L), which does write positions and is undoable. `layout.js` also owns the
   canvas orientation (`horizontal | vertical`, stored in `pe_canvas_dir`): like the theme
   it is a per-browser preference, deliberately _not_ part of the definition, and
   `StepNode.jsx` reads it to move its handles between the sides and the top/bottom — moving
   a handle needs `useUpdateNodeInternals` or the edges keep their old anchors. Flipping the
   direction re-runs the layout, since the old positions would leave every edge doubling
   back. **The graph the editor holds is not the graph it draws.** A step with nothing
   upstream _is_ the step the engine hands the trigger payload to, so the arrow from the
   trigger box is derived from that fact (`rootIds` → `canvasEdges`) rather than stored:
   it survives a save and reload (connections to the trigger box are not part of a
   definition), it moves to whatever step a deletion left at the front, and it cannot be
   dragged away to leave a step looking connected to nothing. Two consequences that are
   easy to undo by accident. The trigger node is not in `nodes` either — it is derived too,
   so its React Flow changes have nowhere to be applied — but its **measurement has to be
   kept** (`triggerSize`): React Flow re-reads a node's handle positions from the DOM only
   while the node object carries `measured`, treats them as unknown otherwise, and simply
   does not draw an edge whose source handle has no position, so the trigger arrow
   disappeared on every keystroke in a config field until that was fixed. And `renderedNodes`
   re-applies `selected` after decorating a node, because `decoratedNodes` is rebuilt from
   `nodes`, which does not carry it — hand React Flow the decorated copy wholesale and it
   reports an empty selection straight back through `onSelectionChange`, which used to leave
   a newly added step's config form unopened. `selectedId` is the one authority on what is
   selected. A page contributes its own Ctrl+K entries through `useRegisterCommands`
   (`commands.js`); the palette lives above the router and knows nothing about the editor.
3. **Engine** (`engine.py`) — executes a definition, returns a `ProcessInstance`. Never
   touches storage or HTTP; `worker.py` composes engine + `storage.py` + registry, and that
   is the engine host's whole program. `process_engine_api/app.py` composes the same storage
   and a registry of plugin *specs* via `create_app(db, registry)` — but no engine, because
   its distribution has none. There is deliberately no module-level `app` (no import side
   effects); `process_engine_api/__main__.py` builds one.

### Plugin contract (`plugin.py`), split along the deployment seam

A Plugin has always declared three things, and they now live in two packages:

- **`PluginSpec`** (`process_engine_core/plugin.py`) — `manifest` (identity + input/output
  ports) + `Config` (pydantic model). What a step *is*: enough to draw the palette entry,
  generate the config form and validate a definition, and nothing that can be called. The
  API installs only this.
- **`Plugin`** — adds `async execute(ctx) -> PluginResult | dict | None`. The runnable class
  subclasses the spec (`class HttpRequestPlugin(HttpRequestSpec, Plugin)`), so the two halves
  cannot disagree about the key or what it accepts.

Failure = raise; the engine owns retries, timeout, and error routing. Blocking work still
goes through `await asyncio.to_thread(...)` (see `excel_refresh.py`, `send_email.py`): each
plugin attempt already executes on its own worker thread, so blocking hurts only that step —
but a blocked worker loop cannot enforce `timeout_seconds` until the call returns. Emitting
on a named port (`PluginResult.on("true", data)`) is how branching happens.

One `PluginRegistry` class serves both, differing only in what it was loaded with, and
`registry.executable(key)` is how anything asks which it is holding. `Engine.__init__`
checks its whole registry with `executable(key, require=True)`, so wiring an engine to the
API's spec registry raises a `PluginError` naming the problem instead of an `AttributeError`
from inside the executor on somebody's first step.

### Config forms (`ui.py` + `SchemaForm.jsx`)

Step forms are aimed at people who do not know what a header or a bind parameter is, so a
`Config` is a UI contract as much as a data one. `ui.py` writes an `x-ui` object into a
field's `json_schema_extra`; the designer reads it and nothing else knows the plugin exists:

```python
password: str = Field(default="", title="Password",
                      json_schema_extra=ui(group="Mail server", widget="password", secret=True))
auth_client_id: str = Field(default="", json_schema_extra=ui(show_if=when("auth", "oauth2_client_credentials")))
```

`group` splits the form into sections, `advanced=True` folds a field into that section's
collapsed disclosure, `show_if=when(field, *values)` hides one until it applies, `labels=`
gives enum options human wording, and `secret=True` offers the stored secrets by name so
`{{ secrets.x }}` never has to be typed. `widget` overrides the type-derived control and is
validated against `ui.WIDGETS` at import — a typo raises there, not silently in the browser.
`tests/test_config_forms.py` reads the generated schemas back and fails on a `show_if`
naming a field that no longer exists, wording for an option that was renamed, a list widget
on a dict, or a required field hidden by default.

`detect="array"` (validated against `ui.DETECTORS`, same as `widget`) says "this field names
a list that the step above almost certainly already produces". The designer fills it in from
the connected upstream step the first time the form opens and offers a _Detect from the
previous step_ button to do it again after the arrow moves — see `for_each`'s `items`. It is a
hint about where a value comes from, not a default the plugin may rely on: the field is still
an expression a person can overwrite, and the engine resolves it knowing nothing about any of
this.

Prefer writing a field so it needs no explanation: one `encryption` dropdown beats
`use_tls` + `use_ssl`, and `action: statement | procedure` beats "leave `statement` empty to
mean the procedure". Reshaping a field is as breaking as renaming a plugin key, so pair it
with a `model_validator(mode="before")` that maps the retired keys (see `send_email.py`,
`_mysql.py`, `mysql_execute.py`) and cover it in `test_config_forms.py`.

Renaming a plugin key is a breaking change for saved definitions — add the old key to
`manifest.aliases` instead (as `send_email_smtp` does for `send_email`). Aliases resolve in
`registry.get()`/`__contains__` but are excluded from `manifests()`, so retired keys keep
working without appearing in the palette.

**A new plugin goes in this repository.** Two discovery paths (`registry.py`), both resolved
at startup only — adding one means restarting the API (so it appears in the palette) _and_
every engine (so it can run):

- built-ins: **two modules and two list entries**, one per side of the seam — the spec in
  `packages/process_engine_core/plugins/<key>.py`, listed in `BUILTIN_SPECS`; the
  implementation in `packages/process_engine/plugins/<key>.py`, listed in `BUILTIN_PLUGINS`.
  Each tier loads its own list (`spec_registry()` on the API, `default_registry()` on an
  engine), and both build the same `PluginRegistry`, so every key in the palette is a key
  some engine can run. This is the path.
- pip packages with entry points in group `process_engine.plugins` (template:
  `examples/hello-plugin`) — for a plugin another team owns on its own release cycle; it has
  to be installed on every host that executes, so prefer a built-in.

There is deliberately **no drop-in folder** for loose `.py` files: a step runs on whichever
host claims it, so it must not depend on a file somebody dropped on one of them, and neither
registry factory takes a path argument, so the API and the engines cannot disagree about what
exists.

### Filesystem sandbox (`workspace.py`)

Step config is data an editor authors, so any plugin taking a path must resolve it with
`workspace.resolve()` — never `Path(cfg.some_path)`. Relative paths join onto the working
directory (`PROCESS_ENGINE_WORK_DIR`, default `./workdir`), absolute ones must already be
inside it, and containment is checked _after_ symlink/junction resolution;
`PathNotAllowed` (a `ValueError`) fails the step. A plugin that walks a tree must re-check
every entry it discovers, not just the folder it was handed (`file_purge._matches`).
Download plugins share `plugins/_download.py` — where the file lands (`target_path`) and
the `.part`-then-rename discipline (`download_to`) belong there, so `s3_download` and
`azure_blob_download` cannot drift apart; their outputs deliberately share a shape too.
The root is env-only and `GET /api/workspace` is read-only on purpose: a signed-in user
must not be able to widen the sandbox their steps run inside. `excel_refresh` and
`send_email`'s `attachments` predate this and still take unrestricted paths — moving them
behind the sandbox would break saved definitions, so it is a deliberate migration, not a
drive-by fix.

### Auth, users, secrets (process_engine_api/{app,users,sso}.py + core's secrets_store.py + security.py)

- Every `/api` route needs a bearer credential **except** `/api/auth/login`, the SSO
  endpoints, `/api/health` (a probe holds no credential) and `/api/hooks/*` (webhook capability
  URLs, deliberately token-free).
- Credentials: user session tokens (Fernet, 12 h TTL, issued by `/api/auth/login` or the
  OIDC SSO callback) or the static API token (admin-role bootstrap/machine credential from
  `PROCESS_ENGINE_AUTH_TOKEN` / generated `.process_engine_auth`). Roles: `admin` (manages
  users) and `editor`. Disabling a user revokes sessions instantly (checked per request).
  Signing out is browser-side only — a session token stays valid until its TTL expires, so
  disabling the account is the only real revocation lever.
- **Who can see a process.** An admin sees every one; anyone else sees what they created
  (`created_by`) plus what is in `shared_with`, and sharing is _flat_ — a recipient holds it
  exactly as the creator does, including the right to share it on, so a team can hand work
  over without an admin. Both fields are server-owned: `update_process` carries them over so a
  crafted PUT cannot grant access, and `POST /processes/{id}/share` (whole list, not a delta)
  is the only way to change them. Every read goes through `_get_or_404(process_id, request)`
  and every listing through `_visible_processes`; a new `/processes/...` route that skips them
  leaks. Run history inherits the process's access (`_run_or_404`) because step inputs and
  outputs are as revealing as the definition. No-access is **404, not 403** — a 403 confirms
  the id belongs to a real process. A clone belongs to whoever made it and starts unshared.
  `tests/test_sharing.py` covers all of this.
- **Settings is admin-only, and deliberately holds only deployment configuration** — the mail
  relay, execution mode and engine hosts, the file sandbox, users, the installed plugin
  inventory (`GET /api/queue` is open to any signed-in user, since it explains a spinner they
  are looking at; `GET /api/workers` names hosts and is admin-only). Things an individual sets
  for themselves live where their audience is: theme and the guided tour in the account menu
  (`AppShell`), secrets on their own page. So do not add an editor-facing control to Settings,
  and do not lock down `GET /api/plugins`, `GET /api/secrets` or `GET /api/notifications/mail`
  — the palette, the config forms and the editor's notifications panel all need them. The
  tour filters its own stops by role (`tourSteps()`), so an editor is never walked into a page
  they cannot open.
- SSO providers (Google, Entra) activate purely via `PROCESS_ENGINE_OIDC_*` env vars; SSO
  emails must match an existing username unless `PROCESS_ENGINE_SSO_AUTO_PROVISION=true`.
- Secrets are Fernet-encrypted rows (key: `PROCESS_ENGINE_SECRET_KEY` / generated
  `.process_engine_key`); the API exposes names only. Steps reference them with
  `{{ secrets.name }}`, resolved only at execution time. Tests rely on these token/key
  files being auto-generated — both are gitignored.

### Engine semantics (the non-obvious parts)

- Graph must be a DAG (`validate()` rejects cycles); iteration is the `for_each` plugin,
  which runs a _published sub-process_ per item via `ctx.run_subprocess` (wired from the
  engine's `definition_resolver`; depth-capped). This is deliberate — do not add loop edges.
- **Single-step preview**: `Engine.preview_step()` executes one step using a recorded run's
  outputs and returns a `StepRun` without persisting anything. Real-run and preview input
  must stay identical, so both build it through `combine_deliveries()` /
  `deliveries_from_run()` — change those, not one call site. The plugin really executes, so
  previewing a step with side effects performs them (same trade-off n8n makes). The reply
  payload is built by `engine.preview_result()` wherever the step ran, so the API and a
  worker cannot answer differently.
- **Durability**: the worker passes `on_update=db.save_instance`, so instance state persists
  after every step. On startup, instances stuck in RUNNING are re-queued; resume replays
  SUCCEEDED steps from recorded outputs instead of re-executing (side effects are
  at-least-once). `RunControl` gives cooperative pause/cancel between steps; PAUSED runs
  keep PENDING steps and resume via the same replay path.
- A step runs when all incoming connections are _settled_ (upstream emitted on that port, or
  the path is dead). Zero deliveries → step is SKIPPED and the skip cascades. Condition
  branching depends on this; don't "fix" skipped branches.
- **Ready steps run in parallel** — one asyncio task per step, and each plugin attempt
  executes on a worker thread with its own event loop (one pool per Engine,
  `PROCESS_ENGINE_STEP_WORKERS` sizes it; unset → `ThreadPoolExecutor` default). Connections
  are the only ordering guarantee, so never rely on `{{ steps.x }}` reaching a step that is
  not upstream of it. Orchestration, `on_update` persistence and notifications stay on the
  engine's loop; `ctx.run_subprocess` hops back to it thread-safely. A failure, pause or
  cancel stops _launching_ steps; those already in flight finish and are recorded.
- `{{ dotted.path }}` expressions in step config are resolved **just before** execution
  against `{trigger, steps, variables, input}` (`expressions.py` — lookups only, never eval),
  _then_ validated against the plugin's `Config`. A whole-string expression keeps its type.
- A failed step (after retries) routes `{error, step}` to its `error` port if connected;
  otherwise the whole run fails and remaining steps become SKIPPED.

### The queue (`worker.py` + core's `jobs.py`)

**There is one execution mode, and it is not a mode.** The API writes every job to the
`job_queue` table and engines claim it — there is no switch, no inline path and no worker
pool on the API host, because that host holds no engine to run one with. Nothing executes
until a `python -m process_engine` is up, and no environment variable changes that.

n8n's queue mode without the broker: a job carries a snapshot of the definition taken at
enqueue time, and the shared database coordinates everything else. A fresh run is persisted
as a **PENDING placeholder before dispatch** (`enqueue_run`), so it is visible immediately
and — because the worker _resumes_ that row — re-dispatched by the startup recovery sweep
(which picks up PENDING as well as RUNNING) if the container dies while the job is still
queued. The parts that keep the rest of the design honest:

- A worker owns the whole run: the engine, per-step persistence, and that run's
  notifications — announce once, sub-runs silent, one email per run end. `init_worker`
  rebuilds its stack **from env vars alone** (workers are spawned, never forked), which is
  also what lets the same function run on another machine.
- **Pause/cancel cross the process boundary through the `run_signals` table**: the API
  writes the request, the worker polls between steps and clears the row when the run settles.
  A cancel queued before the job starts wins deterministically.
- SQLite is fine for one machine and is what the tests use; a shared MySQL/Postgres is
  _required_ across hosts, since SQLite cannot be shared.

The three job kinds (`jobs.py`) and the rest of the shape:

- Start an engine with `python -m process_engine` (`worker.serve`). It polls `job_queue`,
  claims the oldest row with a time-boxed lease, and owns that run end to end.
  Run one process per concurrent run.
- `claim_job`'s guarded `UPDATE` is the lock (portable to SQLite; no `SKIP LOCKED`). A worker
  that dies mid-run lets its claim lapse after the lease, and another reclaims the job and
  replays the persisted instance — the same at-least-once durability as everywhere else. A
  _slow_ run must not look like a dead one, so `_renewed_claim` keeps touching the row from a
  daemon thread (SQS's `ChangeMessageVisibility`) while the job holds the event loop.
- **Every run is a queued run**, including the one behind the designer's Run button. The API
  returns the PENDING instance rather than a finished one, so the designer's existing
  `pollRun` handles it and no client needs a special case.
- **A preview becomes request/reply** (`kind="preview"`). The POST validates the step and its
  plugin, then answers **202** with a poll URL — Asynchronous Request-Reply, the standard
  shape for "the answer cannot come back on this connection". The worker writes the result
  into the job row (`complete_job`), `GET /processes/{id}/previews/{preview_id}` collects it
  and calls `finish_job`, and uncollected replies are swept by `purge_jobs`. Both paths build
  the payload with `engine.preview_result`, so the Output tab cannot tell who answered.
  The claimable predicate must keep excluding settled rows, or a delivered reply gets
  re-claimed and re-executed as work.
- **Cron belongs to the engine hosts**, not the API: due times live in `schedule_state`, and
  `claim_schedule`'s guarded `UPDATE` (`WHERE next_due = <the due we saw>`) means one firing
  happens once however many engines are watching. So `create_app` starts **no** `Scheduler`
  at all — it could not run what one fired — and `worker.serve` ticks one. A window nobody
  was up for is rolled forward and skipped (`LATE_TOLERANCE_SECONDS`) — cron semantics, not
  a stampede on start-up. `test_the_designer_api_leaves_scheduling_to_the_engine_hosts`
  enforces it.
- The API's restart recovery sweep **skips runs that still have a job row**: this container
  restarting says nothing about the host executing that run, and a lapsed lease is how a dead
  one is recovered.
- **"Queued" has to be legible**, or the designer just spins. Workers heartbeat into the
  `workers` table every poll; `GET /api/queue` (any signed-in user) reports mode, depth and
  how many are online, `GET /api/workers` (admin) names them, and `StepOutput`/Settings →
  Execution say "no engine is running right now" rather than waiting forever.

### Split deployment (Linux designer + Windows engine)

Two deployments: a **Linux container** with the designer and `process-engine-api` (see the
`Dockerfile` — nginx serves `designer/dist` and proxies `/api` to uvicorn on loopback, so it
is one origin and CORS never matters), and a **Windows host** running `python -m
process_engine` for the Excel/COM plugins. A shared MySQL/Postgres is the only channel;
`PROCESS_ENGINE_SECRET_KEY` must be byte-identical on both or the engine cannot decrypt the
secrets steps use. `deploy/*.env.example` are the working templates.

The install is what enforces the split. The container takes
`process_engine_core[mysql]` + `process_engine_api` and never `process_engine`; the Windows
host takes `process_engine_core` + `process_engine[excel,mysql]` and never the API. Neither
can do the other's job, and `docker exec … python -c "import process_engine"` failing in the
container is the property, not a bug.

The designer's fetches are same-origin by default (`/api`, `/help`). To host it separately
from its API, build it with `VITE_API_BASE=https://engine…` — every API call, the webhook-URL
preview, the SSO start and the guided-tour doc link then target that origin
(`designer/src/api.js` `engineUrl`; see `designer/.env.example`). Auth is a Bearer token in
`localStorage`, not a cookie, so cross-origin calls need no credential handling and CORS stays
`*`. `PROCESS_ENGINE_PUBLIC_URL` is the API's _own_ origin (the OIDC callback registered with
the provider) while `PROCESS_ENGINE_DESIGNER_URL` is where the browser lands after SSO and
where notification run-links point — one origin unless the designer is deployed apart, then
two. Both live in core's `urls.py`, not the API package, because the engine host is the one
that sends the notification email and has to put a link in it.

### Storage semantics (`storage.py`)

Definitions/instances are stored as JSON documents with a few extracted columns (n8n's
approach) via SQLAlchemy — SQLite by default, MySQL/Postgres by URL (`PROCESS_ENGINE_DB_URL`).
The `processes` table holds only the editable draft; `publish` snapshots an immutable copy
into `process_versions` and bumps `latest_version`. Runs execute the latest published version
unless `draft: true`. Preserve this immutability — running instances record the version they
used. The `settings` table is the one place an admin-editable _deployment_ setting lives (one
JSON document per key; only the notification relay so far) — anything security-shaped stays
env-only, as the file sandbox does.

Four tables exist purely to coordinate the two hosts, and are the only state they share
beyond definitions and runs: `job_queue` (work to claim, runs and previews alike),
`run_signals` (pause/cancel across the boundary), `schedule_state` (cron due times, claimed by
rolling one forward) and `workers` (heartbeats, so "queued" can be told from "nobody is
listening"). SQLite reads `DateTime(timezone=True)` back naive, so anything comparing a stored
timestamp with `utcnow()` goes through `as_utc()` — a naive/aware comparison raises.

### Run notifications (`notifications.py`)

A process can email people when a run starts/succeeds/fails/finishes
(`ProcessDefinition.notifications`). `engine.py` stays pure: it knows nothing about email, so
whoever ran the process composes this — the started event fires from the `on_update` callback
(the first time the engine reports the instance), terminal events after `engine.run` returns.
`worker.py` sends them for the run it claimed, which is every run. The API sends exactly one
kind — the end of a run cancelled while it was still queued or paused, because that run ends
*there* and no engine ever touched it (`_notify` in `app.py`). This module lives in **core**
rather than with the engine because both tiers need it, but the engine host is the half that
sends the mail for real work.

The non-obvious parts, all of which have tests in `tests/test_notifications.py`:

- **One email per run end.** `event_for()` picks the _most specific_ subscribed event, so
  `failed` + `completed` is one message worded for what happened, not two. Add an event to
  `FINISHED_EVENTS` (most specific first) rather than sending from more than one place.
- **Dispatch snapshots the instance** (`model_copy(deep=True)`) and chains sends per run id.
  The engine keeps mutating the live instance, so a fire-and-forget "started" email would
  otherwise describe a run that had already finished — and overtake the "finished" one.
- **Sub-process runs are silent** (`parent_run_id is not None`): a `for_each` over 500 rows is
  one notification, not 501.
- **`created_by` is server-owned** — set from the principal on create/clone and carried over on
  update, because the designer PUTs a definition that has never heard of it. A username that is
  not an email address (local accounts, the `api-token` principal) is dropped from recipients
  rather than handed to the relay.
- **Delivery never raises.** `Notifier.deliver` logs and returns; the run is already over. The
  one exception is `send_test`, which raises so _Send test email_ can show the relay's own words.
- The relay is deployment-wide, admin-only to change, and sends over **SMTP or Amazon SES**
  (`provider`); SES goes out as raw MIME so both providers carry the byte-identical message
  built by `build_message`, and blank SES keys fall through to the ambient boto3 chain. Add a
  credential field to `SECRET_FIELDS` and it is Fernet-encrypted in the `settings` row and
  reported by `public()` only as `<field>_set`. The relay is deliberately _not_ shared with the
  `send_email_*` plugins: a step sends mail as part of the work, a notification reports on it.

## Ops reference

`docs/` holds four self-contained HTML handbooks — no build step, no external assets, readable
straight off disk, cross-linked by bare filename. `architecture.html` is the building blocks in
diagrams (the three distributions, the plugin seam, what crosses the database, the life of a run
and of a preview) and is where a new developer starts; `runbook.html` is operations (the
Linux/Windows split, every env var, what to back up, COM/Excel constraints, mail,
troubleshooting); `developer-guide.html` is the Plugin contract in full and where a contributor
is sent; `guided-tour.html` is the end-user walkthrough. Update the runbook when changing
plugins or operational behaviour, the developer guide when the plugin contract moves, and the
architecture doc when a module changes packages or a box on one of those diagrams moves.

`GET /api/health` is the one unauthenticated liveness route (the container's HEALTHCHECK and any
proxy in front of it hold no credential). It answers `{"status": "ok"}` and deliberately nothing
else — mode, worker count and queue depth are `/api/queue`, behind the bearer token.

The container is `Dockerfile` + `deploy/nginx.conf` + `deploy/supervisord.conf`: nginx serves
`designer/dist` and proxies `/api`, `/help` and the OpenAPI UI to uvicorn beside it, both under
supervisord, as an unprivileged user on port 8080. Everything written at runtime (the SQLite
fallback, the generated auth token and Fernet key) lands in the `/data` volume — losing the key
makes stored secrets unreadable. It installs `process_engine_core[mysql]` and
`process_engine_api` — and not `process_engine`, which is why nothing can execute there.

`docs/guided-tour.html` is the end-user walkthrough (build → publish → schedule → read runs).
Its in-app counterpart is `tour.js` + `components/Tour.jsx`: an ordered list of cards, each
pointing at a real element by `data-tour="<anchor>"` and, where needed, a `route` it navigates
to first. Adding a stop means adding that one attribute — a missing anchor degrades to a
centred card rather than breaking the walk — and the editor registers `useLeaveGuard(dirty)`
so a tour started mid-edit asks before navigating away. `create_app` mounts `docs/` read-only
at `/help` (not `/docs`, which is FastAPI's OpenAPI UI) so the tour can link the long form on
the same origin; the vite dev server proxies `/help` alongside `/api`. Keep the two in step:
a change that moves the interface is a change to both.

## GitHub Copilot

`.github/` carries a condensed mirror of this file for Copilot:
`copilot-instructions.md` (repo-wide — layers, commands, the invariants that break saved data)
and `instructions/*.instructions.md`, each scoped by an `applyTo` glob to plugins, the
designer, Python, tests or docs. `prompts/*.prompt.md` are reusable `/new-plugin`,
`/run-local` and `/review-invariants` tasks. This file stays authoritative — it explains the
reasoning; those state the rule — so a design change is an edit to both, or they drift.
`workflows/copilot-setup-steps.yml` only provisions the cloud coding agent on GitHub (Ubuntu,
so no `excel` extra); it has no effect locally.
