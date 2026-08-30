---
name: playwright-ui-test
description: Write or change a Playwright browser test for the designer. Use whenever a task involves designer/tests/**/*.spec.js — adding a spec, extending one, or debugging one that fails or hangs. Carries the UI-only rule, the three mandatory pass gates, the helper inventory in designer/tests/support/designer.js, and the locator conventions that this app's forms and canvas actually need.
---

# Playwright UI tests for the designer

A browser test here is **a person at the keyboard**, not a backend smoke test with a browser
attached. It signs in on `/login`, clicks steps out of the palette, fills the generated forms,
wires the graph from the Input tab, saves through the app, presses Run, and reads the answer off
the screen.

## The rule that decides everything else

**No `/api/...` call from inside the page.** No `page.evaluate(() => fetch('/api/...'))`, no
`page.request`, no `APIRequestContext` shortcut to set up a process, seed a table or read a
result. A spec that reaches past the UI bypasses the user path, hides the validation errors a
person would have hit, and reports a pass for a flow nobody can perform.

Consequences worth knowing before you start writing:

- **Fixtures are steps.** A demo that needs a table builds it with a `mysql_execute` step, in
  the process, on the canvas. That is also a better demo.
- **The credential is read in Node**, never fetched by the page: `authToken()` looks at
  `PROCESS_ENGINE_AUTH_TOKEN`, then `.env`, then `.process_engine_auth`. Never hard-code one,
  and never commit one.
- **The engine has to be up.** The API executes nothing; every run is queued. `npx playwright
  test` needs the API on `:8000`, vite on `:5173` and at least one `python -m process_engine`.
  "No engine is running right now" is what the designer says, and a spec that waits through it
  is failing slowly.

## The three mandatory gates

A green Playwright report is **not** a passing test on its own. Every UI spec asserts all three,
using the helpers in `designer/tests/support/designer.js` rather than rolling the assertion
again.

### 1. No failed step, and every skip declared — `expectRunPassed(page, steps, { skipped })`

"Skipped" is the quiet one: a step whose upstream delivered nothing is skipped rather than
failed and the run still reports **success**, so a spec that only checks the run badge passes
while half the process never happened. The timeline's `Steps · done/total` counts only
*succeeded* steps, so that number is the assertion.

A branch is the one honest reason for a skip — a Condition sends its input down one port and the
steps on the other are skipped by design. Declare how many and the count is checked exactly:

```js
await expectRunPassed(page, 6)                    // no branch: no skip allowed
await expectRunPassed(page, 4, { skipped: 1 })    // one Condition, one branch not taken
```

A skip is **accounted for, never tolerated**. If you cannot say which branch produced it, the
process is wrong, not the assertion.

### 2. No disconnected step — `expectNoDisconnectedStep(page)`

Before every save and after the run. Every step is reached by the trigger box or another step; a
step nothing points at never runs, and a canvas showing one is a process that silently does less
than it looks like it does.

Asserted per step id with a retrying `toHaveCount` — never from one `evaluateAll` snapshot of
the whole graph. `evaluateAll` does not auto-wait, the canvas re-renders as the editor works,
and a snapshot read between two renders reports a graph that was never on screen.

### 3. Under a minute

`timeout: 60_000` in `playwright.config.js`, `RUN_TIMEOUT` of 30 s for a queued run. Building a
process, publishing it, queueing a run and reading the timeline is seconds of work on a healthy
stack, so a spec that needs longer is reporting a problem — an engine that is not claiming, a
step that is retrying, a wait that is really a hang. **Let it fail and say so. Never
`test.setTimeout`, and never raise the ceiling.** If one flow genuinely does more than fits,
split it into two `test()`s inside a `test.describe.serial` so each gets its own budget.

## Conventions this app's UI actually requires

- **Tidy the canvas before opening any step** (`Ctrl+Shift+L`, after clicking away from a form
  field — the shortcut is ignored while one has focus). The palette drops steps around the
  middle of the view where the cards overlap, so clicking one of a stack is ambiguous for a
  person and for the test alike.
- **Address a form control by role, not by label text.** The **ƒx** button beside every field
  carries `aria-label="Insert a value from an earlier step into <Title>"`, so
  `getByLabel('Query')` matches two elements. Use
  `getByRole('textbox', { name: 'Query' })` — and *not* `{ exact: true }` on a required field,
  whose label carries its `*`. For a key/value row, `{ name: 'Name', exact: true }` and
  `{ name: 'Value', exact: true }`.
- **An untyped field commits on blur.** `Any`-typed config fields (a Condition's *Value to
  check* / *Compared with*, For Each's *List to work through*) render the value editor, which
  only commits on blur so a number stays a number. `fill()` then `blur()`. Text, textarea and
  key/value fields commit on change.
- **Check a drag landed before asserting anything about where it landed.** React Flow arms a node
  drag from pointer events on the card itself, so a press aimed at coordinates the canvas has
  since moved (a tidy-up, a fit view) hits the pane and the node stays put — silently, leaving
  the geometry assertion after it reporting a layout nobody chose. `dragNodeBelow` re-reads the
  cards, moves, and confirms in flow coordinates that it worked; do the same for any drag of
  your own.
- **A JSON tree opens two levels.** `JsonTree` renders `depth < 2` expanded, so a value three
  deep — a row inside `rows` inside a sub-run's output — is not in the page text until it is
  opened. `expandJson(outputs)` first, then assert.
- **Scope a run's Input/Outputs block to its own step.** More than one step can be expanded at
  once, so a page-wide `.section-label` lookup silently means two things — filter the timeline
  `li` by the step's own toggle button first.
- **Names, not ids, across a test boundary.** A spec that builds one process and then picks it
  from another's form should select it by label; sharing an id between two `test()`s couples
  them for no gain.
- **A demo spec deletes and rebuilds.** Everything in `designer/tests/demo/` leaves a real
  published process behind under a fixed name, so it clears the pair first with
  `removeDemoProcess(page, name)` — which goes *through* the `demo` folder's delete guard
  (assert the disabled Delete, move it out, then delete) and is therefore also the test of it.

## What `support/designer.js` already gives you

Read it before adding a helper; extend it rather than duplicating one in a spec.

| Helper | What it does |
| --- | --- |
| `authToken()` | the admin credential, resolved in Node from env / `.env` / `.process_engine_auth` |
| `signIn(page)` | `/login` via the API-token form, then dismisses the guided tour |
| `dismissTour(page)` | leaves the tour through its own Skip button |
| `TRIGGER` | the trigger box's node id (`__trigger__`) |
| `RUN_TIMEOUT` | 30 s — how long a queued run may take before it is called stuck |
| `DEMO_FOLDER`, `removeDemoProcess(page, name)` | the protected folder, and the delete-through-the-guard sequence |
| `addStep(page, pluginKey)` | clicks the palette entry (matched on the plugin key) and answers with the new step's id |
| `stepIds(page)`, `select(page, nodeId)` | what is on the canvas; open one in the inspector |
| `arrow`, `expectConnected`, `expectNotConnected` | one arrow, addressed as the canvas labels it |
| `expectNoDisconnectedStep(page)` | **gate 2** |
| `nodePosition`, `nodeBox`, `stepPositions` | canvas geometry in flow coordinates |
| `edgeStart`, `expectArrowLeaves(page, a, b, side)` | which border an arrow leaves — the floating-edge behaviour |
| `dragNode(page, nodeId, dx, dy)` | a hand-placed step (stepped pointer moves; one jump reads as a click) |
| `dragNodeBelow(page, nodeId, referenceId)` | the same, aimed under another card — and it checks the card moved |
| `save(page)`, `publish(page)` | save through the app and assert the state chip / published version |
| `runDetail(page)` | the run timeline, in the editor inspector **or** the Runs page aside |
| `expandJson(scope)` | opens every collapsed node in a JSON tree — `JsonTree` only opens two levels |
| `expectRunPassed(page, steps, { skipped })` | **gate 1** |

## Running them

```powershell
cd designer; npm install; npx playwright install chromium   # once
cd designer; npx playwright test                            # needs API :8000, an engine, vite :5173
cd designer; npx playwright test demo/mysql-for-each.spec.js --reporter=line
```

`testDir` is `./tests`, so `tests/demo/` is picked up with no config change. Runs are **not
headless** — watching the canvas is most of the value when one of these fails.

## Writing a new spec

1. Say at the top of the file, in the docstring, what user-visible facts it covers — numbered,
   and referenced from each `test.step` that proves one. When a spec fails you want to know which
   promise broke, not which line threw.
2. Build the process the way a person would, asserting the editor's own behaviour as you go: the
   first step wires itself to the trigger box, each one after joins the one before, the Input tab
   re-points an arrow when a different source is chosen.
3. `expectNoDisconnectedStep` → `save` → (`publish`, if anything runs it as a sub-process).
4. Run it, then read the result out of the timeline — not out of the database.
5. Assert all three gates. Then run it twice in a row: a spec that only passes on a clean
   install is a spec that will fail on Monday.
