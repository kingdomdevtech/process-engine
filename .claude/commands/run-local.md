---
description: Start the API, an engine and the designer locally, then smoke-test them
allowed-tools: Bash, PowerShell, Read, Glob, Grep
---

Bring the app up locally and prove it works. The API, an engine and the
designer, then a real request through each. Report the URLs and what you saw —
don't stop at "started".

## 1. Check what is already listening

Someone may have left a server running from an earlier session. Never kill a
process you did not start in this session without asking first.

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
                   "{0} PID={1} {2}" -f $_.LocalPort, $_.OwningProcess, $p.ProcessName }
```

A port that is already taken means skip that server and reuse it — but say so in
the report, and warn that a pre-existing API is running whatever Python code it
started with, so it will not reflect uncommitted backend changes. Offer to
restart it rather than doing so unprompted.

## 2. Start the servers (background, logs to a file)

The venv lives at `.venv`; call its interpreter directly rather than activating.
**Source `.env` first if it exists** — `start-local.sh` does, so a server started
without it lands on the SQLite fallback while everything else is on the MySQL
container, and the two disagree about every process and run. That database has to
be up: `docker compose up -d mysql`.

```bash
cd "<repo root>" && set -a && . ./.env && set +a && .venv/Scripts/python.exe -m process_engine_api > /tmp/pe-api.log 2>&1
cd "<repo root>" && set -a && . ./.env && set +a && .venv/Scripts/python.exe -m process_engine > /tmp/pe-engine.log 2>&1
cd "<repo root>/designer" && npm run dev > /tmp/pe-designer.log 2>&1
```

`.env` must have LF line endings, or every value picks up a trailing `\r` and the
DB URL and token break in ways that read as a wrong password.

All three with `run_in_background: true`. API → http://127.0.0.1:8000 (docs at
`/docs`), designer → http://localhost:5173 (proxies `/api` to :8000).

**The engine is not optional.** `process_engine_api` executes nothing: every run
and every step preview is queued through the database and claimed by an engine,
so without `python -m process_engine` the Run button leaves a PENDING run
spinning and the Output tab says nothing is listening. The engine serves no
HTTP — check it through the API (`/api/workers` for its heartbeat, `/api/queue`
for the backlog).

Read the logs before assuming success — uvicorn exits with code 3 and a
bind error when :8000 is taken, and `npm run dev` prints the real port it
picked, which is not always 5173.

If `.venv` or `designer/node_modules` is missing, install first:
`pip install -r requirements-dev.txt` and `cd designer; npm install`.

## 3. Drive the API

The static admin token is `PROCESS_ENGINE_AUTH_TOKEN` when `.env` sets it, and the
generated `.process_engine_auth` file otherwise — the env var wins, so read `.env`
first or you will authenticate against the wrong one. Both are gitignored. Every
`/api` route except `/api/auth/login`, the SSO endpoints, `/api/health` and
`/api/hooks/*` needs it as a bearer credential. Do not echo the token into the
transcript.

```bash
TOKEN=$(grep -h '^PROCESS_ENGINE_AUTH_TOKEN=' .env 2>/dev/null | cut -d= -f2- | tr -d '\r\n')
TOKEN=${TOKEN:-$(cat .process_engine_auth | tr -d '\r\n')}
curl -s -o /dev/null -w "health:%{http_code}\n" http://127.0.0.1:8000/api/health
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/plugins   # registered plugins
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/processes # saved processes
curl -s -o /dev/null -w "proxy:%{http_code}\n" -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:5173/api/plugins                                           # vite proxy is wired
```

Plugin count is the useful signal: registry discovery runs at startup only, so a
plugin you just added and a missing one look identical until you restart.

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/workers      # engines online
```

An empty list means nothing can run, whatever the other routes say.

## 4. Drive the designer, and look at the screenshot

Playwright (Python) with chromium is installed globally. There is no seeded user,
so log in through the login page's **token** mode, as a user would.

Note: Playwright here is Windows Python — write screenshots to `C:/tmp/...`, not
`/tmp/...`, or you will not find them afterwards.

```python
from pathlib import Path
from playwright.sync_api import sync_playwright

token = Path(".process_engine_auth").read_text().strip()
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto("http://localhost:5173/app", wait_until="networkidle")
    pg.get_by_text("Use an API token instead").click()
    pg.fill("#pe-token", token)
    pg.get_by_role("button", name="Sign in").click()
    pg.wait_for_url("**/app", timeout=15000)
    pg.wait_for_load_state("networkidle")
    pg.screenshot(path="C:/tmp/pe-dashboard.png", full_page=True)
    # into the editor — process cards are divs, not links, so click the title text
    pg.get_by_text("Untitled process").first.click()
    pg.wait_for_url("**/app/processes/**", timeout=15000)
    pg.wait_for_timeout(2000)          # let react-flow lay the canvas out
    pg.screenshot(path="C:/tmp/pe-editor.png")
    b.close()
```

Then **Read the PNGs**. A blank or login-page frame is a failure, not a pass.
The dashboard should show the stat tiles and the process list; the editor should
show the plugin palette, the step nodes on the canvas, and the right-hand rail.

If the target process name differs, click whatever card the dashboard actually
shows — or create one with **New process** and drop a step from the palette.

The snippet above is for *looking* at a running stack. The committed browser
suite is `designer/tests/*.spec.js` (`@playwright/test`, node), and it is the one
that has to pass:

```powershell
cd designer; npx playwright test --reporter=line
```

Its rules are in CLAUDE.md under _Browser tests must go through the designer UI_:
never call `/api/...` from inside the page, and every spec asserts
`expectRunPassed` (no failed and no skipped step) and `expectNoDisconnectedStep`
within the 60-second per-test ceiling.

## 5. Report

Give the user the two URLs, the plugin/process counts, whether an engine is
online, and what the screenshots showed. Flag anything you reused rather than
started, and leave the background servers running unless asked to stop them.
