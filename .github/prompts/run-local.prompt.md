---
name: run-local
description: Start the API, an engine and the designer locally, then smoke-test them
agent: agent
---

Bring the app up locally and prove it works — the API, an engine and the designer, then a real
request through each. Report the URLs and what you saw; don't stop at "started".

## 1. Check what is already listening

Never kill a process you did not start in this session without asking first.

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
                   "{0} PID={1} {2}" -f $_.LocalPort, $_.OwningProcess, $p.ProcessName }
```

A port already taken means reuse that server — but say so, and warn that a pre-existing API is
running whatever Python code it started with, so it will not reflect uncommitted backend changes.
Offer to restart it rather than doing so unprompted.

## 2. Start the servers

The venv lives at `.venv`; call its interpreter directly rather than activating.

```powershell
.venv\Scripts\python.exe -m process_engine_api  # http://127.0.0.1:8000, docs at /docs
.venv\Scripts\python.exe -m process_engine      # the engine: claims jobs, fires cron
cd designer; npm run dev                        # http://localhost:5173, proxies /api and /help
```

**All three, not two.** The API executes nothing — every run and every step preview is queued
through the database and claimed by an engine — so without `python -m process_engine` the
designer's Run button leaves a PENDING run spinning forever. `GET /api/workers` should show the
engine's heartbeat once it is up, and `GET /api/queue` reports the depth.

Read the output before assuming success: uvicorn exits with a bind error when :8000 is taken, and
`npm run dev` prints the port it actually picked, which is not always 5173. If `.venv` or
`designer/node_modules` is missing, install first: `pip install -r requirements-dev.txt` and
`cd designer; npm install`.

## 3. Drive the API

The static admin token is the generated `.process_engine_auth` file (gitignored). Every `/api`
route except `/api/auth/login`, the SSO endpoints and `/api/hooks/*` needs it as a bearer
credential. **Do not echo the token into the transcript.**

Check `/api/health`, then `/api/plugins` and `/api/processes` with the bearer token, then the same
`/api/plugins` call through `http://127.0.0.1:5173` to prove the vite proxy is wired. Plugin count
is the useful signal: registry discovery runs at startup only, so a plugin you just added and a
missing one look identical until you restart.

Then `/api/workers` — an empty list means nothing can run, whatever the other routes say.

## 4. Report

Give the two URLs, the plugin and process counts, whether an engine is online, and anything that
looked wrong. Flag whatever you reused rather than started, and leave the servers running unless
asked to stop them.
