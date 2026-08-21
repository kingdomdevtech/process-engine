# Process Engine

<img src="designer/public/logo.svg" alt="Process Engine" width="300">

n8n-style drag-and-drop workflow automation, custom-built in Python.

A **Process** is a graph of **Steps**. Each Step is an instance of a **Plugin** — the
pluggable unit of behaviour. The engine executes process definitions and records
every run as a **Process Instance** with per-step inputs, outputs, and errors.

> Documentation (self-contained HTML, open directly in a browser):
> [docs/guided-tour.html](docs/guided-tour.html) — the hands-on walkthrough for using it ·
> [docs/developer-guide.html](docs/developer-guide.html) — setup and plugin development ·
> [docs/runbook.html](docs/runbook.html) — operations.
>
> The designer walks you around itself too: <kbd>Ctrl</kbd>+<kbd>K</kbd> → *Take the guided
> tour*, offered automatically the first time you open the dashboard. The API serves the same
> handbooks at `/help/…`, which is where that tour links for the long version.

## Architecture

```
designer/            React + React Flow canvas: auth, palette, form/JSON config,
        |            triggers, secrets, users, runs, undo/redo, validation badges,
        |            left-to-right or top-to-bottom canvas with one-command tidy-up
        |  HTTP (/api, bearer token)
src/process_engine/
  api.py             FastAPI app: auth, processes, publish, run, runs, plugins,
                     secrets, users, webhooks, pause/resume/cancel
  engine.py          async executor: ports, branching, joins, retries, error routing,
                     durability (resume), sub-processes, RunControl
  scheduler.py       cron scheduler for schedule triggers (croniter)
  registry.py        Plugin discovery: built-ins, entry points, drop-in files
  plugin.py          the Plugin contract (manifest + Config model + execute)
  expressions.py     safe {{ dotted.path }} resolution for step config
  workspace.py       filesystem sandbox: one working directory file plugins may touch
  secrets_store.py   named credentials, Fernet-encrypted at rest
  users.py           user accounts: PBKDF2 passwords, Fernet session tokens, roles
  storage.py         SQLAlchemy persistence (SQLite default, MySQL via Docker)
  models.py          ProcessDefinition / Step / Connection / Trigger / ProcessInstance
plugins/             drop-in folder for your custom Plugins (auto-discovered)
examples/hello-plugin  pip-installable Plugin discovered via entry point
```

Key semantics, borrowed from the tools that proved them:

- **Draft vs published** — publishing snapshots an immutable version; runs record
  which version they used (Camunda's model).
- **Ports** — steps emit data on named output ports (`main`, `true`/`false`,
  `error`); a branch that emits nothing skips its downstream steps (n8n's model).
- **Expressions** — config values like `{{ steps.enrich.output.total }}` move data
  between steps; whole-string expressions keep their type. `{{ secrets.name }}`
  resolves encrypted credentials at execution time.
- **Retries / timeout / error routing** per step — exponential backoff, and a step
  failure can route to its `error` port instead of failing the run (Temporal's lesson).
- **Triggers** — `schedule` (cron, fired by the built-in scheduler) and `webhook`
  (`POST /api/hooks/{path}`, body becomes trigger input). Triggers fire the latest
  published version.
- **Durability** — instance state persists after every step; runs interrupted by a
  restart resume automatically, replaying completed steps from recorded outputs.
  Runs can be paused, resumed, and cancelled (`/api/runs/{id}/pause|resume|cancel`).
- **Loops** — the `for_each` plugin runs a published sub-process per item of a
  collection (Step Functions "Map" / Camunda multi-instance pattern); the graph
  itself stays acyclic.
- **File sandbox** — plugins that touch the disk (`s3_download`, `azure_blob_download`,
  `file_purge`) resolve
  every path inside one **working directory** (`PROCESS_ENGINE_WORK_DIR`, default
  `./workdir`). Relative paths are joined onto it, absolute ones must already be inside
  it, and symlinks are resolved before the check — so a definition can never reach
  system folders, the engine's database, or its key files.
- **Auth** — every API call needs a bearer credential: a user session from
  `POST /api/auth/login` (users have `admin`/`editor` roles) or the static API
  token (bootstrap/machine use, from `PROCESS_ENGINE_AUTH_TOKEN` or the generated
  `.process_engine_auth` file). Webhook URLs are token-free capability URLs.
- **Run notifications** — a process can email its creator and anyone else when a
  run *starts*, *succeeds*, *fails* or simply *finishes*. Each run is reported
  once, under the most specific event subscribed to, so `fails` + `finishes` is
  not two emails about one failure. Sending is best effort and off the run's
  path: a dead relay is logged, never fatal. The relay itself is deployment-wide
  (**Settings → Notifications**, admin only) and separate from the
  `send_email_*` steps, which keep their own settings. It sends through either
  an **SMTP server** or **Amazon SES** — SES with explicit keys or, inside AWS,
  the instance role. Credentials are encrypted at rest and never returned.

## Quickstart

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,excel]"          # excel extra = pywin32 for the Excel plugin
pip install -e examples/hello-plugin   # optional: example entry-point plugin

pytest                                  # run the test suite
python examples\demo.py                 # run a process end-to-end in the console
python examples\mysql_excel_demo.py     # seed the MySQL -> for_each -> Excel showcase (needs docker MySQL)
python -m process_engine                # start the API on http://127.0.0.1:8000
```

Designer (requires the API running):

```powershell
cd designer
npm install
npm run dev                             # http://localhost:5173, proxies /api to :8000
npm run build                           # production build; the API then serves it on :8000
```

The app is a multi-page product, not a single canvas: a public **landing page** at `/`,
sign-in at `/login`, then the workspace — **Dashboard** (`/app`), **Editor**
(`/app/processes/:id`), **Runs** (`/app/runs`) and **Settings** (`/app/settings`,
holding secrets, users, the working directory and the installed-plugin catalogue). After `npm run build`
the API serves the whole thing from port 8000, so a deployment is one origin.

Processes are organised into **folders** on the dashboard — collapsible groups with
search and a folder filter. A folder is just a label on the definition (set it in the
editor breadcrumb or with *Move…* on a card), so no schema migration is involved and
processes saved before folders existed simply show as *Uncategorized*.

Sign in first: the designer asks for credentials. Bootstrap with the API token
(printed to `.process_engine_auth` on first start, or set
`PROCESS_ENGINE_AUTH_TOKEN`), then create users in the **Users** panel —
`admin` manages users, `editor` designs and runs. SSO via **Google / Microsoft
Entra ID** activates when the `PROCESS_ENGINE_OIDC_*` env vars are set (see
`src/process_engine/sso.py`).

Drag plugins from the palette, connect them, then select a step — the inspector
gives it three tabs, the same shape n8n uses:

- **Input** — the real values reaching this step, from the most recent run:
  the trigger payload, each connected upstream step's output (pick which one
  from a dropdown), and the combined payload the plugin actually receives.
  Every value is a clickable node in a JSON tree; clicking one assigns the
  expression that addresses it to the config field you choose.
- **Config** — **Form view** (generated from the plugin's schema, with an HTML
  editor for HTML fields) or **JSON view**; both write the same JSON into the
  definition. Each assignable field also has an **ƒx** button opening the data
  picker for a searchable list of the same expressions. *Show example* in the
  JSON view reveals a pre-configured config for that plugin — *Use this* drops
  it into the editor, ready to edit before you apply it.
- **Output** — *Test this step*: runs only the selected step against the
  recorded run and shows what it produced, the config with expressions
  resolved, and the input it used. The plugin executes for real (side effects
  happen), but nothing is written to the run history.

**Run draft** colors nodes by step result; invalid steps get red badges;
Ctrl+Z / Ctrl+Shift+Z undo/redo canvas changes. With no step selected, the
inspector manages **Triggers** and recent runs.

The **layout menu** in the toolbar decides which way a process reads — left to
right or top to bottom — and *Tidy up steps* (Ctrl+Shift+L, or the Ctrl+K
palette) re-positions every step in dependency order, so a graph that has been
dragged into a tangle takes one keystroke to straighten out. The direction is a
per-browser preference rather than part of the definition, and both actions are
undoable.

### MySQL instead of SQLite

Storage is plain SQLAlchemy, so the backend is a URL. A ready-to-run MySQL 8 is
included via Docker:

```powershell
docker compose up -d mysql
pip install -e ".[mysql]"
$env:PROCESS_ENGINE_DB_URL = "mysql+pymysql://process_engine:process_engine@127.0.0.1:3306/process_engine"
python -m process_engine
```

Unset `PROCESS_ENGINE_DB_URL` to fall back to the local `process_engine.db` SQLite file.
Verify the backend any time with `python examples\mysql_smoke.py`.

### Where file steps may write

`s3_download`, `azure_blob_download` and `file_purge` take paths from step config — data
any editor can author — so they resolve every path inside a single **working directory**:

```powershell
$env:PROCESS_ENGINE_WORK_DIR = "D:\process-engine\files"   # default: .\workdir
python -m process_engine
```

`"downloads/orders.csv"` lands in `D:\process-engine\files\downloads\orders.csv`;
`"../../Windows/System32"`, `C:\Windows\...` and a symlink pointing out of the folder
all fail the step with `PathNotAllowed` before anything is read, written or deleted.
The root is deployment configuration, not an API setting — **Settings → Files** shows
it read-only, so nobody signed in to the designer can widen the sandbox they run in.
Give the folder its own disk or quota if processes download large files, and point
it somewhere the engine's service account can write but nothing critical lives.

## Writing a custom Plugin

Three integration paths, cheapest first:

**1. Drop-in file (zero packaging).** Put a `.py` file in `plugins/`
(override the folder with `PROCESS_ENGINE_PLUGINS_DIR`), restart the API, done —
it appears in the palette with a config form generated from its `Config` model.
See [plugins/uppercase.py](plugins/uppercase.py):

```python
from pydantic import BaseModel
from process_engine.plugin import Plugin, PluginContext, PluginManifest, PluginResult

class UppercaseConfig(BaseModel):
    text: str = "{{ input.message }}"   # expressions welcome

class UppercasePlugin(Plugin):
    manifest = PluginManifest(key="uppercase", name="Uppercase", category="custom")
    Config = UppercaseConfig

    async def execute(self, ctx: PluginContext) -> PluginResult:
        return PluginResult.main({"text": ctx.config.text.upper()})
```

**2. Pip package with an entry point (shareable, versioned).** One section in
`pyproject.toml` is the whole integration — see
[examples/hello-plugin](examples/hello-plugin/pyproject.toml):

```toml
[project.entry-points."process_engine.plugins"]
hello = "hello_plugin:HelloPlugin"
```

**3. Built-in** — add it to `src/process_engine/plugins/` and `BUILTIN_PLUGINS`.

Plugin rules of thumb:

- Raise on failure; the engine applies the step's retry policy and error routing.
- Run blocking work through `await asyncio.to_thread(...)` (see the Excel and
  email plugins) so one step never stalls the engine.
- Emit on named ports for branching: `PluginResult.on("true", data)`.
- Keep secrets out of config defaults; reference process variables instead:
  `"password": "{{ variables.smtp_password }}"`.

## Built-in plugins

| Key | What it does |
| --- | --- |
| `http_request` | Call an HTTP endpoint, emit status/headers/body |
| `condition` | Route input to `true`/`false` ports by comparison |
| `transform` | Set/reshape fields (n8n's "Edit Fields") |
| `delay` | Wait, pass input through |
| `log` | Log a templated message, pass input through |
| `for_each` | Run a published sub-process per item of a collection (loops) |
| `excel_refresh` | Refresh Excel Power Query connections via COM (Windows + Excel + `[excel]` extra) |
| `s3_download` | Download an S3 object into the working directory (`[aws]` extra; IAM or explicit keys) |
| `azure_blob_download` | Download an Azure blob into the working directory (`[azure]` extra; connection string, key, SAS or managed identity) |
| `file_purge` | Delete files past an age cut-off inside the working directory (glob, keep-latest, dry run) |
| `html_table` | Render rows as an HTML table (escaped, inline-styled) for an email body |
| `send_email_ses` | Amazon SES email: HTML body, placeholders, attachments, IAM or explicit keys |
| `send_email_smtp` | Generic SMTP email (Exchange, Gmail, in-house relay); accepts the retired `send_email` key |
| `mysql_query` | SELECT rows from MySQL with bound `:name` parameters |
| `mysql_execute` | Run a MySQL statement (transactional) or stored procedure |

## API

All routes require `Authorization: Bearer <session-or-api-token>` except
`/api/auth/login`, the SSO endpoints, and `/api/hooks/*`.

| Method & path | Purpose |
| --- | --- |
| `POST /api/auth/login`, `GET /api/auth/me` | User login (session token) / who am I |
| `GET /api/auth/sso` + `/api/auth/sso/{p}/login\|callback` | SSO discovery + OIDC flow (Google, Entra) |
| `GET/POST /api/users`, `PUT/DELETE /api/users/{name}` | User management (admin role) |
| `GET /api/secrets`, `PUT/DELETE /api/secrets/{name}` | Secrets: names only; values write-only, encrypted |
| `GET /api/users/directory` | Addressable usernames, for the notification recipient picker |
| `GET/PUT /api/notifications/mail`, `POST /api/notifications/test` | Notification relay (read by any user, changed/tested by admins; password never returned) |
| `GET /api/plugins` | Manifests + config JSON Schemas (feeds the palette) |
| `GET /api/workspace` | The working directory file plugins are confined to (read-only; set by env var) |
| `POST /api/processes` / `GET /api/processes[?folder=]` | Create draft / list (optionally one folder) |
| `GET /api/folders`, `PUT /api/processes/{id}/folder` | Folders in use with counts / move a process |
| `GET/PUT/DELETE /api/processes/{id}` | Read / update draft / delete |
| `POST /api/processes/{id}/validate` | Static checks; issues carry `step_id` for node badges |
| `POST /api/processes/{id}/publish` | Snapshot an immutable version (refused if invalid) |
| `POST /api/processes/{id}/run` | Execute: draft/published, sync or `{"background": true}` |
| `GET /api/processes/{id}/runs`, `GET /api/runs/{run_id}` | Run history / run detail |
| `GET /api/processes/{id}/steps/{step_id}/picker` | Expressions this step can pull from, with sample values |
| `GET /api/processes/{id}/steps/{step_id}/input` | Actual values reaching the step: trigger, each upstream output, combined payload |
| `POST /api/processes/{id}/steps/{step_id}/preview` | Test-run just this step on recorded data; returns output + resolved config |
| `POST /api/runs/{id}/pause\|resume\|cancel` | Run control (durable pause/resume) |
| `POST /api/hooks/{path}` | Webhook trigger — capability URL, no bearer token |

Interactive docs at `http://127.0.0.1:8000/docs` while the API is running.

## Roadmap

- **Observability**: run metrics dashboard, sub-run drill-down for `for_each`, OpenTelemetry.
- **Webhooks**: HMAC signature validation and per-hook secrets.
- **Scale-out**: queue-backed workers so multiple engine processes share the load.
- **Plugins**: config-migration hooks for plugin version upgrades; sandboxed third-party execution.
- **Audit log** of who edited/published/ran what.
