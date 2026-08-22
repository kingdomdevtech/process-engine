---
name: Documentation
description: What each handbook is for and what must be updated alongside it
applyTo: "docs/**,README.md,CLAUDE.md"
---

# Documentation

`create_app` mounts `docs/` read-only at **`/help`** — not `/docs`, which is FastAPI's OpenAPI
UI. The vite dev server proxies `/help` alongside `/api`, so in-app links work in development
too. Every file there is self-contained HTML: no build step, no external assets, and they must
stay readable when opened straight off disk. They cross-link each other by bare filename, so
keep the four in the same folder.

- **`docs/architecture.html`** — the building blocks in diagrams: the three distributions and
  which host installs each, the plugin seam, the database as the only channel, and what a run
  and a preview actually do between the two hosts. It is where a new developer starts, so
  update it when a module changes packages or a box on one of its figures moves. The figures
  are hand-authored inline SVG for the same reason the pages have no build step.
- **`docs/guided-tour.html`** — the end-user walkthrough (build → publish → schedule → read
  runs). Its in-app counterpart is `designer/src/tour.js` + `components/Tour.jsx`, an ordered
  list of cards each pointing at a real element by `data-tour="<anchor>"`. A change that moves
  the interface is a change to **both** — keep the two in step.
- **`docs/runbook.html`** — operations: the Linux/Windows split, every environment variable,
  what to back up, COM/Excel constraints, mail, troubleshooting. Update it whenever a plugin
  gains a credential, a network dependency or a platform requirement, and whenever deployment
  behaviour changes.
- **`docs/developer-guide.html`** — the Plugin contract in full: ports, retries, blocking work,
  the sandbox, the config form as a UI contract, registration, compatibility, testing,
  packaging. It is where a contributor is sent, so it must not contradict
  `.github/instructions/plugins.instructions.md`.
- **`README.md`** — user-facing overview and getting started.
- **`CLAUDE.md`** — the authoritative design document: the reasoning behind every invariant.
  When a design constraint changes, this is where it is recorded, and
  `.github/copilot-instructions.md` plus `.github/instructions/*.instructions.md` are its
  condensed mirrors — update them together or they drift.

Write for the person configuring a step, not for a developer reading source. Explain the
constraint and what breaks without it, not the API surface.
