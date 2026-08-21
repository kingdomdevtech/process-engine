---
name: Documentation
description: What each handbook is for and what must be updated alongside it
applyTo: "docs/**,README.md,CLAUDE.md"
---

# Documentation

`create_app` mounts `docs/` read-only at **`/help`** — not `/docs`, which is FastAPI's OpenAPI
UI. The vite dev server proxies `/help` alongside `/api`, so in-app links work in development
too. Both files are self-contained HTML: no build step, no external assets, and they must stay
readable when opened straight off disk.

- **`docs/runbook.html`** — operations: COM/Excel constraints, SMTP notes, environment
  variables, troubleshooting. Update it whenever a plugin gains a credential, a network
  dependency, or an operational failure mode.
- **`docs/guided-tour.html`** — the end-user walkthrough (build → publish → schedule → read
  runs). Its in-app counterpart is `designer/src/tour.js` + `components/Tour.jsx`, an ordered
  list of cards each pointing at a real element by `data-tour="<anchor>"`. A change that moves
  the interface is a change to **both** — keep the two in step.
- **`README.md`** — user-facing overview and getting started.
- **`CLAUDE.md`** — the authoritative design document: the reasoning behind every invariant.
  When a design constraint changes, this is where it is recorded, and
  `.github/copilot-instructions.md` plus `.github/instructions/*.instructions.md` are its
  condensed mirrors — update them together or they drift.

Write for the person configuring a step, not for a developer reading source. Explain the
constraint and what breaks without it, not the API surface.
