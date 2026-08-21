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
pip install -e ".[dev,excel,mysql]"          # excel=pywin32 (Windows), mysql=PyMySQL
pip install -e examples/hello-plugin         # example entry-point plugin

pytest                                       # full suite
pytest tests/test_engine.py -k branching     # single test
python examples\demo.py                      # run a process end-to-end, no server
python -m process_engine                     # API on http://127.0.0.1:8000 (docs at /docs)

cd designer; npm run dev                     # designer on :5173, proxies /api to :8000
cd designer; npm run build                   # verify the frontend compiles

docker compose up -d mysql                   # optional MySQL backend, then set
# $env:PROCESS_ENGINE_DB_URL = "mysql+pymysql://process_engine:process_engine@127.0.0.1:3306/process_engine"
```

Async tests need no decorator — pytest-asyncio runs in `auto` mode (pyproject.toml).

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
   refines that with the `x-ui` hints described under *Config forms* below. Schema
   `format: "html"` on a string field renders the HTML editor — see `send_email_ses`'s
   `body_html`. `schemaExample.js` turns a config schema
   into the pre-configured JSON behind *Show example* (JSON tab) and field placeholders; steer
   it with pydantic `Field(examples=[...])` rather than by special-casing a plugin in the
   designer. Selecting a step gives Input/Config/Output
   tabs (`StepInput` → `/steps/{id}/input`, `StepPanel`, `StepOutput` → `/steps/{id}/preview`);
   the **ƒx** button opens the picker fed by `/steps/{id}/picker`. Undo/redo covers canvas
   structure only (drop/connect/delete/drag), by design. Validation badges come from
   client-side required-field checks plus `/validate`'s `detailed[].step_id`; step-level
   issues badge the node, process-level ones surface in a banner over the canvas. `position`
   is designer-owned, so a definition built by the API or a test has every step at (0,0) —
   `layoutGraph` in `layout.js` lays those out in dependency order on load (`needsLayout`
   gates it) without writing back. That same function backs the *Tidy up steps* command
   (Ctrl+Shift+L), which does write positions and is undoable. `layout.js` also owns the
   canvas orientation (`horizontal | vertical`, stored in `pe_canvas_dir`): like the theme
   it is a per-browser preference, deliberately *not* part of the definition, and
   `StepNode.jsx` reads it to move its handles between the sides and the top/bottom — moving
   a handle needs `useUpdateNodeInternals` or the edges keep their old anchors. Flipping the
   direction re-runs the layout, since the old positions would leave every edge doubling
   back. A page contributes its own Ctrl+K entries through `useRegisterCommands`
   (`commands.js`); the palette lives above the router and knows nothing about the editor.
3. **Engine** (`engine.py`) — executes a definition, returns a `ProcessInstance`. Never
   touches storage or HTTP; `api.py` composes engine + `storage.py` + registry via
   `create_app(db, registry)`. There is deliberately no module-level `app` (no import side
   effects); `__main__.py` builds one.

### Plugin contract (`plugin.py`)

A Plugin = `manifest` (identity + input/output ports) + `Config` (pydantic model) +
`async execute(ctx) -> PluginResult | dict | None`. Failure = raise; the engine owns retries,
timeout, and error routing. Blocking work still goes through `await asyncio.to_thread(...)`
(see `excel_refresh.py`, `send_email.py`): each plugin attempt already executes on its own
worker thread, so blocking hurts only that step — but a blocked worker loop cannot enforce
`timeout_seconds` until the call returns. Emitting on a named port
(`PluginResult.on("true", data)`) is how branching happens.

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

Prefer writing a field so it needs no explanation: one `encryption` dropdown beats
`use_tls` + `use_ssl`, and `action: statement | procedure` beats "leave `statement` empty to
mean the procedure". Reshaping a field is as breaking as renaming a plugin key, so pair it
with a `model_validator(mode="before")` that maps the retired keys (see `send_email.py`,
`_mysql.py`, `mysql_execute.py`) and cover it in `test_config_forms.py`.

Renaming a plugin key is a breaking change for saved definitions — add the old key to
`manifest.aliases` instead (as `send_email_smtp` does for `send_email`). Aliases resolve in
`registry.get()`/`__contains__` but are excluded from `manifests()`, so retired keys keep
working without appearing in the palette.

Three discovery paths (`registry.py`), all resolved at startup only — a new plugin requires an
API restart:
- drop-in `.py` files in `./plugins` (or `PROCESS_ENGINE_PLUGINS_DIR`)
- pip packages with entry points in group `process_engine.plugins` (template: `examples/hello-plugin`)
- built-ins: must be imported **and** listed in `BUILTIN_PLUGINS` in `src/process_engine/plugins/__init__.py`

### Filesystem sandbox (`workspace.py`)

Step config is data an editor authors, so any plugin taking a path must resolve it with
`workspace.resolve()` — never `Path(cfg.some_path)`. Relative paths join onto the working
directory (`PROCESS_ENGINE_WORK_DIR`, default `./workdir`), absolute ones must already be
inside it, and containment is checked *after* symlink/junction resolution;
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

### Auth, users, secrets (api.py + users.py + secrets_store.py + sso.py + security.py)

- Every `/api` route needs a bearer credential **except** `/api/auth/login`, the SSO
  endpoints, and `/api/hooks/*` (webhook capability URLs, deliberately token-free).
- Credentials: user session tokens (Fernet, 12 h TTL, issued by `/api/auth/login` or the
  OIDC SSO callback) or the static API token (admin-role bootstrap/machine credential from
  `PROCESS_ENGINE_AUTH_TOKEN` / generated `.process_engine_auth`). Roles: `admin` (manages
  users) and `editor`. Disabling a user revokes sessions instantly (checked per request).
  Signing out is browser-side only — a session token stays valid until its TTL expires, so
  disabling the account is the only real revocation lever.
- **Who can see a process.** An admin sees every one; anyone else sees what they created
  (`created_by`) plus what is in `shared_with`, and sharing is *flat* — a recipient holds it
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
  relay, the file sandbox, users, the installed plugin inventory. Things an individual sets
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
  which runs a *published sub-process* per item via `ctx.run_subprocess` (wired from the
  engine's `definition_resolver`; depth-capped). This is deliberate — do not add loop edges.
- **Single-step preview**: `Engine.preview_step()` executes one step using a recorded run's
  outputs and returns a `StepRun` without persisting anything. Real-run and preview input
  must stay identical, so both build it through `combine_deliveries()` /
  `deliveries_from_run()` — change those, not one call site. The plugin really executes, so
  previewing a step with side effects performs them (same trade-off n8n makes).
- **Durability**: `api.py` passes `on_update=db.save_instance`, so instance state persists
  after every step. On startup, instances stuck in RUNNING are auto-resumed; resume replays
  SUCCEEDED steps from recorded outputs instead of re-executing (side effects are
  at-least-once). `RunControl` gives cooperative pause/cancel between steps; PAUSED runs
  keep PENDING steps and resume via the same replay path.
- A step runs when all incoming connections are *settled* (upstream emitted on that port, or
  the path is dead). Zero deliveries → step is SKIPPED and the skip cascades. Condition
  branching depends on this; don't "fix" skipped branches.
- **Ready steps run in parallel** — one asyncio task per step, and each plugin attempt
  executes on a worker thread with its own event loop (one pool per Engine,
  `PROCESS_ENGINE_STEP_WORKERS` sizes it; unset → `ThreadPoolExecutor` default). Connections
  are the only ordering guarantee, so never rely on `{{ steps.x }}` reaching a step that is
  not upstream of it. Orchestration, `on_update` persistence and notifications stay on the
  engine's loop; `ctx.run_subprocess` hops back to it thread-safely. A failure, pause or
  cancel stops *launching* steps; those already in flight finish and are recorded.
- `{{ dotted.path }}` expressions in step config are resolved **just before** execution
  against `{trigger, steps, variables, input}` (`expressions.py` — lookups only, never eval),
  *then* validated against the plugin's `Config`. A whole-string expression keeps its type.
- A failed step (after retries) routes `{error, step}` to its `error` port if connected;
  otherwise the whole run fails and remaining steps become SKIPPED.

### Queue mode (`worker.py`)

`PROCESS_ENGINE_RUN_WORKERS=N` moves background runs (manual `background: true`, schedule,
webhook, resume) into a pool of N spawned worker processes — n8n's queue mode without the
broker: the job carries a snapshot of the definition taken at enqueue time, and the shared
database coordinates everything else. Threads share one GIL; processes do not, which is what
makes CPU-bound plugin work scale. The parts that keep the rest of the design honest:

- A fresh run is persisted as a **PENDING placeholder before dispatch**, so it is visible
  immediately and — because the worker *resumes* that row — re-dispatched by the startup
  recovery sweep (which picks up PENDING as well as RUNNING) if the server dies while the
  job is still queued.
- A worker owns the whole run: the engine, per-step persistence, and that run's
  notifications, under the same rules as `api.py` — announce once, sub-runs silent, one
  email per run end. `init_worker` rebuilds its stack from the same env vars the API reads
  (workers are spawned, never forked).
- **Pause/cancel cross the process boundary through the `run_signals` table**: the API
  writes the request when the run id is not in its in-process `controls`, the worker polls
  between steps and clears the row when the run settles. A cancel queued before the job
  starts wins deterministically.
- Foreground runs and step previews stay in the API process — they need the result inside
  the HTTP response. SQLite copes with light queue-mode use; a shared MySQL/Postgres is the
  right backend once workers are on.

### Storage semantics (`storage.py`)

Definitions/instances are stored as JSON documents with a few extracted columns (n8n's
approach) via SQLAlchemy — SQLite by default, MySQL/Postgres by URL (`PROCESS_ENGINE_DB_URL`).
The `processes` table holds only the editable draft; `publish` snapshots an immutable copy
into `process_versions` and bumps `latest_version`. Runs execute the latest published version
unless `draft: true`. Preserve this immutability — running instances record the version they
used. The `settings` table is the one place an admin-editable *deployment* setting lives (one
JSON document per key; only the notification relay so far) — anything security-shaped stays
env-only, as the file sandbox does.

### Run notifications (`notifications.py`)

A process can email people when a run starts/succeeds/fails/finishes
(`ProcessDefinition.notifications`). The engine stays pure: it knows nothing about email, so
`api.py` composes this like everything else — the started event fires from the `on_update`
callback (the first time the engine reports the instance), terminal events after `engine.run`
returns.

The non-obvious parts, all of which have tests in `tests/test_notifications.py`:

- **One email per run end.** `event_for()` picks the *most specific* subscribed event, so
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
  one exception is `send_test`, which raises so *Send test email* can show the relay's own words.
- The relay is deployment-wide, admin-only to change, and sends over **SMTP or Amazon SES**
  (`provider`); SES goes out as raw MIME so both providers carry the byte-identical message
  built by `build_message`, and blank SES keys fall through to the ambient boto3 chain. Add a
  credential field to `SECRET_FIELDS` and it is Fernet-encrypted in the `settings` row and
  reported by `public()` only as `<field>_set`. The relay is deliberately *not* shared with the
  `send_email_*` plugins: a step sends mail as part of the work, a notification reports on it.

## Ops reference

`docs/runbook.html` is the self-contained operations runbook (COM/Excel constraints, SMTP
notes, troubleshooting). Update it when changing plugins or operational behaviour.

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
