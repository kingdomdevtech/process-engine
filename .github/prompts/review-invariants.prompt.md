---
name: review-invariants
description: Review the working changes against the project's design invariants and compatibility rules
agent: agent
---

Review the current changes (`git diff` plus untracked files) against this project's invariants.
Report only real problems, most serious first, each as `file:line` with the concrete failure it
causes. Say so plainly if nothing is wrong — don't manufacture findings.

**Layering**
- Does `engine.py` still avoid storage, HTTP and email? Is new cross-cutting behaviour composed in
  `api.py` rather than pushed into the engine?
- Any module-level `app`, or import-time side effects?
- Did anything runtime- or UI-shaped leak into `ProcessDefinition`?

**Compatibility with saved data**
- A renamed plugin key without a `manifest.aliases` entry.
- A reshaped or renamed config field without a `model_validator(mode="before")` mapping the retired
  keys, and without `tests/test_config_forms.py` covering it.
- Anything that mutates a published version in `process_versions`.

**Engine semantics**
- A loop edge, or iteration added anywhere but `for_each` / `ctx.run_subprocess`.
- Step input built somewhere other than `combine_deliveries()` / `deliveries_from_run()` — preview
  and real runs must stay identical.
- "Fixing" a skipped branch: zero deliveries → SKIPPED, and the cascade is how condition branching
  works.
- A plugin catching its own failure instead of raising, or blocking the event loop without
  `asyncio.to_thread`.

**Security**
- A filesystem path built with `Path(...)` instead of `workspace.resolve()`, or a tree walk that
  checks only the root folder.
- A secret value returned by the API (names only), a secret resolved before execution time, or an
  expression path that evaluates rather than looks up.
- A new `/api` route that skips the bearer credential, or sandbox/auth configuration made editable
  through the API instead of staying env-only.

**Designer**
- A literal colour (`bg-white`, `text-slate-*`, hex, arbitrary value) instead of a semantic token.
- A component class `@apply`-ing another component class.
- Per-plugin frontend code — the palette and forms come from `/api/plugins`.
- `window.confirm` / `window.prompt` / `alert` instead of `useDialogs()`.
- A moved handle without `useUpdateNodeInternals`, or `layoutGraph` writing positions back on load.

**Docs and tests**
- Operational behaviour changed without `docs/runbook.html`; interface moved without both
  `docs/guided-tour.html` and `tour.js`.
- New behaviour with no test in the suite that guards that seam.

Finish by running `pytest`, and `cd designer; npm run build` if anything under `designer/` changed.
Report the actual results.
