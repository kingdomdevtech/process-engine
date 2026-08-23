# Process Engine

<img src="designer/public/logo.svg" alt="Process Engine" width="300">

n8n-style drag-and-drop workflow automation, custom-built in Python.

A **Process** is a graph of **Steps**. Each Step is an instance of a **Plugin** — the
pluggable unit of behaviour. The engine executes process definitions and records
every run as a **Process Instance** with per-step inputs, outputs, and errors.

> Documentation (self-contained HTML, open directly in a browser):
> [docs/guided-tour.html](docs/guided-tour.html) — the hands-on walkthrough for using it ·
> [docs/architecture.html](docs/architecture.html) — the building blocks in diagrams ·
> [docs/developer-guide.html](docs/developer-guide.html) — setup and plugin development ·
> [docs/runbook.html](docs/runbook.html) — operations.
>
> The designer walks you around itself too: <kbd>Ctrl</kbd>+<kbd>K</kbd> → *Take the guided
> tour*, offered automatically the first time you open the dashboard. The API serves the same
> handbooks at `/help/…`, which is where that tour links for the long version.

## Architecture

Three Python packages under `packages/`, and which one a module lives in is a
deployment decision: it decides which machines have to install it. Both tiers
depend on the core; **neither depends on the other**. The API's distribution
contains no engine and no plugin implementation at all, so "the designer's host
cannot execute a step" is a property of the install rather than a rule someone
has to remember — which is the whole point of the [two-host
deployment](#two-host-deployment-linux-designer--windows-engine).

```
designer/                      React + React Flow canvas: auth, palette, form/JSON config,
        |                      triggers, secrets, users, runs, undo/redo, validation badges,
        |                      left-to-right or top-to-bottom canvas with one-command tidy-up
        |  HTTP (/api, bearer token)
packages/process_engine_api/   the designer's server. Needs FastAPI; executes nothing
  |                            — it holds no engine to execute with
  app.py                       auth, processes, publish, run, runs, plugins, secrets,
  |                            users, webhooks, pause/resume/cancel, queue status
  users.py                     user accounts: PBKDF2 passwords, Fernet session tokens, roles
  sso.py                       OIDC single sign-on (Google, Microsoft Entra ID)
  datapicker.py                the expressions a step can pull from, with sample values
        |
packages/process_engine_core/  what a process *is*. Installed on every host
  models.py                    ProcessDefinition / Step / Connection / Trigger / ProcessInstance
  storage.py                   SQLAlchemy persistence (SQLite default, MySQL/Postgres by URL)
  jobs.py                      the queue: enqueue a run, a resume or a preview
  plugin.py                    the Plugin contract — PluginSpec (manifest + Config), Plugin (+ execute)
  plugins/                     every plugin's form half: manifest + Config, no behaviour
  registry.py                  Plugin discovery: built-ins and pip entry points
  ui.py                        the x-ui hints that turn a Config into a usable form
  workspace.py                 filesystem sandbox: one working directory file plugins may touch
  secrets_store.py             named credentials, Fernet-encrypted at rest
  notifications.py             run email over SMTP or Amazon SES
        |  the shared database — the only channel between the two hosts
packages/process_engine/       what runs one. No HTTP in either direction
  worker.py                    the engine host's program: claims jobs, runs them, fires cron
  engine.py                    async executor: ports, branching, joins, retries, error routing,
                               durability (resume), sub-processes, RunControl
  scheduler.py                 cron for schedule triggers (croniter), claimed in the database
  expressions.py               safe {{ dotted.path }} resolution for step config
  plugins/                     every plugin's behaviour half: `execute`, subclassing the spec
examples/hello-plugin          pip-installable Plugin discovered via entry point
```

[docs/architecture.html](docs/architecture.html) draws all of this — the seam
each plugin is split along, what crosses the database, and what a run and a
preview actually do between the two hosts.

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
- **Triggers** — `schedule` (cron, fired by the engine hosts, which claim each
  due time in the database so several engines never double-fire) and `webhook`
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
pip install -r requirements-dev.txt    # all three packages, editable, plus pytest
pip install -e examples/hello-plugin   # optional: example entry-point plugin

pytest                                  # run the test suite
python examples\demo.py                 # run a process end-to-end in the console
python examples\mysql_excel_demo.py     # seed the MySQL -> for_each -> Excel showcase (needs docker MySQL)
python -m process_engine_api            # start the API on http://127.0.0.1:8000
python -m process_engine                # start an engine — nothing runs until this is up
```

Two processes, even on one machine. The API executes nothing: every run and
every single-step preview is written to a queue in the database and claimed by
an engine, which serves no HTTP at all. That is not a mode to switch on — it is
the only path — and it is what lets the engine sit on a different machine
entirely. See [Two-host
deployment](#two-host-deployment-linux-designer--windows-engine).

Designer (requires the API running):

```powershell
cd designer
npm install
npm run dev                             # http://localhost:5173, proxies /api to :8000
npm run build                           # production build; the API then serves it on :8000
```

The app is a multi-page product, not a single canvas: a public **landing page** at `/`,
sign-in at `/login`, then the workspace — **Dashboard** (`/app`), **Editor**
(`/app/processes/:id`), **Runs** (`/app/runs`), **Secrets** (`/app/secrets`) and
**Settings** (`/app/settings`, admin-only: the mail relay, users, the working
directory, which engines are online and the installed-plugin catalogue). After
`npm run build` the API serves the whole thing from port 8000, so a deployment is
one origin.

Or take the container, which is that same single origin already built:

```powershell
docker compose up -d --build            # http://127.0.0.1:8000
```

nginx serves the designer and proxies `/api` to uvicorn beside it, so the browser
talks to one host and CORS never enters the picture. See the
[Dockerfile](Dockerfile) and [deploy/nginx.conf](deploy/nginx.conf).

Processes are organised into **folders** on the dashboard — collapsible groups with
search and a folder filter. A folder is just a label on the definition (set it in the
editor breadcrumb or with *Move…* on a card), so no schema migration is involved and
processes saved before folders existed simply show as *Uncategorized*.

Sign in first: the designer asks for credentials. Bootstrap with the API token
(printed to `.process_engine_auth` on first start, or set
`PROCESS_ENGINE_AUTH_TOKEN`), then create users in the **Users** panel —
`admin` manages users, `editor` designs and runs. SSO via **Google / Microsoft
Entra ID** activates when the `PROCESS_ENGINE_OIDC_*` env vars are set (see
[packages/process_engine_api/sso.py](packages/process_engine_api/sso.py)).

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
$env:PROCESS_ENGINE_DB_URL = "mysql+pymysql://process_engine:process_engine@127.0.0.1:3306/process_engine"
python -m process_engine_api
python -m process_engine        # same URL in its environment, or it watches a different database
```

Unset `PROCESS_ENGINE_DB_URL` to fall back to the local `process_engine.db` SQLite file.
Verify the backend any time with `python examples\mysql_smoke.py`.

### Two-host deployment: Linux designer, Windows engine

The Excel/COM plugins need Windows. Nothing else does, and a Windows box you
cannot expose an HTTP port on is a common constraint — so the two tiers split
along that line, with **the database as the only channel between them**:

```
┌─ Linux container ──────────────┐        ┌─ Windows host ─────────────────┐
│ nginx + designer/dist          │        │ python -m process_engine       │
│ python -m process_engine_api   │        │   claims jobs, runs them,      │
│   core[mysql] + api            │        │   fires its own cron           │
│   no engine installed,         │        │   core + engine[excel,mysql]   │
│   so it executes nothing       │        │   serves no HTTP either way    │
└──────────────┬─────────────────┘        └──────────────┬─────────────────┘
               └────────► shared MySQL / Postgres ◄──────┘
```

The split is enforced by what each host installs, not by configuration: the
container gets `process-engine-core` and `process-engine-api` and never
`process-engine`, so there is no `execute()` in it to call. Every run — including
the one behind the designer's *Run draft* button — and every single-step preview
becomes a row in `job_queue` that an engine claims. That is what makes *Test this
step* work on a plugin that only exists on Windows: the POST returns
`202 Accepted` and the designer polls for the answer (the Asynchronous
Request-Reply pattern), so the Output tab looks the same whichever host produced
it.

The engine also owns **cron**: due times live in `schedule_state` and a firing is
claimed there, so schedules keep running while the Linux container is restarting,
and running several engines double-fires nothing. Start one process per
concurrent run; if one dies mid-run its lease lapses and another reclaims the job
and replays the persisted instance.

**Settings → Execution** shows the queue depth and which engine hosts have
checked in — so "nothing is happening" is answerable without reading logs.

Use a single local environment template: [.env.example](.env.example). Keep the
same `PROCESS_ENGINE_DB_URL` and `PROCESS_ENGINE_SECRET_KEY` values on every host
that touches the same deployment, or the engine cannot decrypt the secrets your
steps use.

### Where file steps may write

`s3_download`, `azure_blob_download` and `file_purge` take paths from step config — data
any editor can author — so they resolve every path inside a single **working directory**:

```powershell
$env:PROCESS_ENGINE_WORK_DIR = "D:\process-engine\files"   # default: .\workdir
python -m process_engine
```

(Set it wherever the steps execute — the engine host, which is this same command
in a split deployment.)

`"downloads/orders.csv"` lands in `D:\process-engine\files\downloads\orders.csv`;
`"../../Windows/System32"`, `C:\Windows\...` and a symlink pointing out of the folder
all fail the step with `PathNotAllowed` before anything is read, written or deleted.
The root is deployment configuration, not an API setting — **Settings → Files** shows
it read-only, so nobody signed in to the designer can widen the sandbox they run in.
Give the folder its own disk or quota if processes download large files, and point
it somewhere the engine's service account can write but nothing critical lives.

## Writing a custom Plugin

**A plugin lives in this repository, and it is split down the same seam the
deployment is.** What a step *is* — its manifest and its `Config` — has to be on
the host that draws the palette and generates the form. What it *does* only ever
runs on an engine. So a plugin is two small modules:

```python
# packages/process_engine_core/plugins/uppercase.py — the form half, installed everywhere
from pydantic import BaseModel
from ..plugin import PluginManifest, PluginSpec

class UppercaseConfig(BaseModel):
    text: str = "{{ input.message }}"   # expressions welcome

class UppercaseSpec(PluginSpec):
    """Shout a value. One line an editor would understand — the palette shows it."""
    manifest = PluginManifest(key="uppercase", name="Uppercase", category="custom")
    Config = UppercaseConfig
```

```python
# packages/process_engine/plugins/uppercase.py — the behaviour, on engine hosts only
from process_engine_core.plugin import Plugin, PluginContext, PluginResult
from process_engine_core.plugins.uppercase import UppercaseSpec

class UppercasePlugin(UppercaseSpec, Plugin):
    async def execute(self, ctx: PluginContext) -> PluginResult:
        return PluginResult.main({"text": ctx.config.text.upper()})
```

List the spec in `BUILTIN_SPECS`
([core's `plugins/__init__.py`](packages/process_engine_core/plugins/__init__.py))
and the implementation in `BUILTIN_PLUGINS`
([the engine's](packages/process_engine/plugins/__init__.py)), restart both, and
it appears in the palette with a config form generated from its `Config` model —
no frontend code at all. The runnable class *is* the spec plus behaviour, so the
two halves cannot drift apart about the key or what the step accepts, and a test
fails if either half is missing its partner.

There is deliberately no drop-in folder for loose `.py` files. A step runs on
whichever host claims it, so it cannot depend on a file somebody dropped on one
of them — and a plugin in the repository gets reviewed, tested, and versioned
with the engine that runs it.

The one alternative is a **pip package with an entry point**, for a plugin
another team owns on its own release cycle. One section in `pyproject.toml` is
the whole integration — see
[examples/hello-plugin](examples/hello-plugin/pyproject.toml):

```toml
[project.entry-points."process_engine.plugins"]
hello = "hello_plugin:HelloPlugin"
```

It has to be installed on every host that executes, which is the reason to
prefer a built-in.

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
`/api/auth/login`, the SSO endpoints, `/api/health`, and `/api/hooks/*`.

| Method & path | Purpose |
| --- | --- |
| `GET /api/health` | Liveness for a container probe or load balancer — no credential, no detail |
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
| `POST /api/processes/{id}/run` | Queue a run of the draft or a published version; answers with the PENDING instance to poll |
| `GET /api/processes/{id}/runs`, `GET /api/runs/{run_id}` | Run history / run detail |
| `GET /api/processes/{id}/steps/{step_id}/picker` | Expressions this step can pull from, with sample values |
| `GET /api/processes/{id}/steps/{step_id}/input` | Actual values reaching the step: trigger, each upstream output, combined payload |
| `POST /api/processes/{id}/steps/{step_id}/preview` | Test-run just this step on recorded data; returns output + resolved config — or `202` and a poll URL when an engine host has to answer |
| `GET /api/processes/{id}/previews/{preview_id}` | Collect a queued preview's answer |
| `POST /api/runs/{id}/pause\|resume\|cancel` | Run control (durable pause/resume) |
| `GET /api/queue` | Queue depth and how many engine hosts are online — why a run is still pending |
| `GET /api/workers` | The engine hosts that have checked in (admin role) |
| `POST /api/hooks/{path}` | Webhook trigger — capability URL, no bearer token |

Interactive docs at `http://127.0.0.1:8000/docs` while the API is running.

## Roadmap

- **Observability**: run metrics dashboard, sub-run drill-down for `for_each`, OpenTelemetry.
- **Webhooks**: HMAC signature validation and per-hook secrets.
- **Plugins**: config-migration hooks for plugin version upgrades; sandboxed third-party execution.
- **Audit log** of who edited/published/ran what.
