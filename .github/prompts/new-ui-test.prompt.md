---
name: new-ui-test
description: Write a Playwright browser test that drives the designer as a person would, with the three mandatory pass gates
agent: agent
argument-hint: the user-visible flow to cover (e.g. "an HTTP step that retries and routes its error")
---

Add a Playwright browser test for: **${input:flow:Which user-visible flow should it cover?}**

Follow `.github/instructions/tests.instructions.md` and the "Browser tests must go through the
designer UI" section of `CLAUDE.md`. Before writing anything, read
`designer/tests/support/designer.js` end to end and
`designer/tests/demo/mysql-for-each.spec.js` as the worked example — most of what you need is
already a helper, and adding a second version of one is how two specs start disagreeing about
what a pass means.

**The rule that decides everything else: no `/api/...` call from inside the page.** No
`page.evaluate(() => fetch(...))`, no `page.request`, no API shortcut to create a process, seed a
table or read a result. Sign in on `/login`, click steps out of the palette, fill the generated
forms, wire the graph from the Input tab, save through the app, press Run, and read the answer off
the screen. A spec that reaches past the UI hides the validation errors a person would have hit and
reports a pass for a flow nobody can perform. Data the flow needs is created by a step **in the
process** — that is also a better demo. The credential is resolved in Node by `authToken()`
(`PROCESS_ENGINE_AUTH_TOKEN`, then `.env`, then `.process_engine_auth`); never hard-code or commit
one.

Do all of this:

1. **A docstring listing the user-visible facts it covers**, numbered, with each `test.step`
   referencing the one it proves. When a spec fails you want to know which promise broke.
2. **Build the process as a person would**, asserting the editor's own behaviour on the way: the
   first step wires itself to the trigger box, each one after joins the one before (on a real
   port — a Condition's first branch, never a `main` it has not got), and the Input tab re-points
   the incoming arrow when a different source is chosen.
3. **Tidy the canvas (`Ctrl+Shift+L`) before opening any step**, after clicking away from a form
   field — the palette drops steps where the cards overlap, and the shortcut is ignored while a
   field has focus.
4. **Address controls by role, not label text**: `getByRole('textbox', { name: 'Query' })`, since
   the **ƒx** button's `aria-label` makes `getByLabel` match two elements. Don't pass
   `{ exact: true }` on a required field (its label carries the `*`); do pass it for key/value
   rows (`Name`, `Value`). An untyped (`Any`) field commits on **blur** — `fill()` then `blur()`.
5. **Never assert on something the UI has not actually shown yet.** Two that bite: a node drag
   whose press lands where the canvas *was* hits the pane and moves nothing, silently — check the
   card moved (`dragNodeBelow` does) before reading any geometry off it; and `JsonTree` renders
   only two levels open, so a value deeper than that is not in the page text until `expandJson`
   has opened it.
6. **The three mandatory gates, all of them**, from `support/designer.js`:
   - `expectRunPassed(page, steps)` — no failed step and no skipped one. A branch is the only
     honest skip: declare it as `{ skipped: n }` and the count is checked exactly. Never leave a
     skip unaccounted for.
   - `expectNoDisconnectedStep(page)` — before every save and after the run.
   - the 60-second per-test ceiling in `playwright.config.js`. A slow UI spec is a bug report:
     let it fail. **Never `test.setTimeout`.** If the flow genuinely does more than fits, split it
     into two `test()`s in a `test.describe.serial` so each keeps its own budget.
7. **If it belongs in `designer/tests/demo/`** — i.e. it leaves a real published process behind —
   give it a fixed name in the `demo` folder and clear the previous one with
   `removeDemoProcess(page, name)`, which deletes *through* the folder's delete guard and is
   therefore also the test of it.

Then run it — `cd designer; npx playwright test <file> --reporter=line`, which needs the API on
`:8000`, vite on `:5173` and at least one `python -m process_engine` claiming jobs — and run it a
second time, because a spec that only passes on a clean install will fail on Monday. Report what
passed and what did not, verbatim; do not raise a timeout or drop a gate to get a green report.
