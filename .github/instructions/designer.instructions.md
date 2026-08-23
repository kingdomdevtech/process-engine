---
name: Designer (React + Tailwind v4)
description: Schema-driven forms, the semantic colour palette, canvas rules and command/tour registration
applyTo: "designer/**"
---

# Designer

React 18 + react-router + @xyflow/react + Tailwind v4, **plain JSX — no TypeScript**. A
multi-page app: `/login`, `/app` dashboard, `/app/processes/:id` editor, `/app/runs`,
`/app/settings`; `/` just redirects to `/app`. Vite proxies `/api` and `/help` to
`http://127.0.0.1:8000`; in the deployed container nginx does the same, so fetches are
same-origin either way (`VITE_API_BASE` only for a separately hosted designer).

## No per-plugin frontend code

The palette and every step config form are generated from `GET /api/plugins` (manifest plus
each Plugin's `Config.model_json_schema()`). Adding a plugin must require **zero** changes
here. If a plugin needs a different control, the answer is an `x-ui` hint or a `Field(examples=)`
on the Python side, not a special case in `SchemaForm.jsx`.

- `SchemaForm.jsx` picks a control from the JSON Schema type, then refines it with `x-ui`
  (`group`, `advanced`, `widget`, `showIf`, `labels`, `secret`, `unit`, `placeholder`,
  `detect`, …). Field components live in `components/fields/`.
- `detect: "array"` marks a field that names a list the step above already produces: the form
  fills it from the connected upstream step the first time it opens, and offers *Detect from
  the previous step* to do it again after the arrow moves. A hint, not a default — the field
  stays an expression a person can overwrite.
- `pluginMeta.jsx` is a *fallback* lookup for icons and category tints, keyed by plugin key
  then category — an unknown plugin still renders.
- `schemaExample.js` turns a config schema into the JSON behind *Show example* and into field
  placeholders.
- The product name lives only in `brand.js`.

## Colour is never literal

One semantic palette is declared twice (light / dark) at the top of `styles.css` in OKLCH and
exposed as utilities through `@theme inline`. Write `bg-surface`, `text-fg-muted`,
`border-line` — never `bg-white`, `text-slate-500`, `#hex`, or an arbitrary value. That is what
keeps light and dark in sync and makes a rebrand one edit.

- Tailwind is configured **in that CSS file**, not a JS config.
- `@layer components` there owns only the primitives repeated across screens: `.btn`, `.input`,
  `.card`, `.badge`, `.table`, `.nav-item`. Something used in three or more places earns a
  class; everything else is a utility at the call site.
- `@apply` resolves utilities only — a component class cannot `@apply` another component class.
- Contrast is a constraint: every foreground/background pair must clear WCAG AA (4.5:1 text,
  3:1 control borders and focus rings). Chroma values are fitted to sRGB on purpose; raising
  one may push it out of gamut, so re-check rather than nudging by eye.
- Dark mode is class-driven (`.dark` on `<html>`). Theme is `light | dark | system`, stored in
  `pe_theme` by `theme.js` and applied pre-paint by the inline script in `index.html` — moving
  that script reintroduces a flash of light on load.

## Canvas

- Edge `sourceHandle` becomes `Connection.source_port`. Every arrow the editor draws for you
  goes through `flowEdge(source, target, port)`, taking the port from `defaultPort(node)` — the
  step's `main` where it has one, otherwise the first thing it emits. Never assume `main`: a
  Condition has only `true`/`false`, and `validate()` rejects a connection on a port the
  manifest does not declare, so the editor would have authored a save that cannot be published.
- `position` is designer-owned, so a definition built by the API or a test has every step at
  (0,0). `layoutGraph` in `layout.js` lays those out in dependency order on load (`needsLayout`
  gates it) **without writing back**. The same function backs *Tidy up steps* (Ctrl+Shift+L),
  which does write positions and is undoable.
- `layout.js` also owns canvas orientation (`horizontal | vertical`, stored in `pe_canvas_dir`)
  — a per-browser preference, deliberately not part of the definition — and it decides **where
  the layout puts things, and nothing else**. Flipping direction re-runs the layout, since old
  positions no longer read as a flow.
- **Arrows follow the geometry, not the orientation.** `FloatingEdge.jsx` picks the two borders
  that face each other per edge (`facingSides`, judged against the cards' own size), so one
  canvas can be wired left-to-right and top-to-bottom at the same time and a hand-placed step
  is never left with an arrow doubling back to the wrong face of it. A source with several
  ports spreads its arrows along that border in port order, so a Condition's branches stay
  tellable apart. `StepNode.jsx` still moves its *handles* — where a connection is dragged
  from — with the orientation, and that needs `useUpdateNodeInternals` or React Flow keeps the
  old anchors and refuses to draw an edge whose handle has no known position.
- **The graph the editor holds is not the graph it draws.** A step with nothing upstream is
  the one the engine hands the trigger payload to, so the arrow from the trigger box is
  derived from that (`rootIds` → `canvasEdges` in `Editor.jsx`), never stored: it survives a
  reload, moves to whatever step a deletion left at the front, and cannot be dragged away.
  A new step joins the end of the flow — the step added before it feeds it.
- The trigger node is derived too, so React Flow's changes to it have nowhere to be applied —
  but keep its **measurement** (`triggerSize`). React Flow re-reads a node's handle positions
  from the DOM only while the node object carries `measured`, and does not draw an edge whose
  source handle has no position, so dropping it makes the trigger arrow vanish on every
  keystroke in a config field.
- `renderedNodes` re-applies `selected` *after* decorating a node: `decoratedNodes` is rebuilt
  from `nodes`, which does not carry it, and handing React Flow the decorated copy wholesale
  makes it report an empty selection back through `onSelectionChange`. `selectedId` is the one
  authority on what is selected.
- `StepInput`'s source select **edits** the graph rather than shadowing it — picking a step
  re-points the incoming arrow (`connectFrom`), and only steps this one cannot already reach
  are offered, since an arrow back would be a cycle. A branching step is offered once per
  branch (`step:<id>:<port>`, labelled `check amount (true)`), because "after the check" is not
  an answer the graph can hold. A published *process* is offered only for a step that can take
  one (`for_each`) and is wired by writing `process_id`, leaving the incoming arrow alone.
- Undo/redo covers canvas *structure* only (drop / connect / delete / drag), by design.
  `HistoryDialog.jsx` behind the toolbar's History button is the way back once the tab has been
  closed — every save is a `process_audits` entry, and one carrying a snapshot can be restored.
- The dashboard reads `protected` off each process row: a process in the `demo` folder shows a
  *protected* badge and a disabled Delete naming the folder, with *Move to folder…* enabled
  right above it. Never hard-code the folder list here — the API decides and reports it, and the
  API refuses the delete (409) whatever this menu offers.
- Validation badges come from client-side required-field checks plus `/validate`'s
  `detailed[].step_id`: step-level issues badge the node, process-level ones surface in a
  banner over the canvas.

## Panels, dialogs, commands, tour

- Selecting a step gives Input / Config / Output tabs (`StepInput` → `/steps/{id}/input`,
  `StepPanel`, `StepOutput` → `/steps/{id}/preview`); the **ƒx** button opens the picker fed by
  `/steps/{id}/picker`.
- `/steps/{id}/preview` may answer **202** with a poll URL instead of a result: in queue mode a
  Windows engine runs the step, so `StepOutput` polls `/previews/{id}` until it settles. The same
  goes for a Run that comes back PENDING. Treat "not finished yet" as a normal reply, not an
  error, and say who you are waiting for (`/api/workers`) rather than spinning silently.
- Shared UI lives in `components/ui/`. Use the promise-based `useDialogs()` `confirm`/`prompt`
  and the focus-trapped `Modal` — never `window.confirm` / `window.prompt` / `alert`.
- A page contributes Ctrl+K entries through `useRegisterCommands` (`commands.js`). The palette
  lives above the router and knows nothing about the editor.
- A guided-tour stop points at a real element by `data-tour="<anchor>"` (plus a `route` where
  it must navigate first). Adding a stop means adding that one attribute in `tour.js`; a
  missing anchor degrades to a centred card rather than breaking the walk. The editor registers
  `useLeaveGuard(dirty)` so a tour started mid-edit asks before navigating away.
- Moving the interface means updating `docs/guided-tour.html` too — the two are counterparts.

## Browser tests (`designer/tests/`)

A Playwright spec is a real user at the keyboard: sign in on `/login`, click steps out of the
palette, fill the generated forms, save through the app, press Run, read the timeline. It
never calls `/api/...` from inside the page. The API token is read in Node by `authToken()`
(env, then `.env`, then `.process_engine_auth`) — never hard-coded, never fetched by the page.

Three gates are **mandatory**, and a green report without them is not a pass. Use the helpers
in `tests/support/designer.js`:

- `expectRunPassed(page, steps, { skipped })` — no failed step, and `Steps · n/n` counting only
  the succeeded ones. A skipped step still reports a *successful* run, so checking the run badge
  alone passes while half the process never ran. A Condition's untaken branch is the one honest
  skip: declare it and the count is checked exactly, never merely tolerated.
- `expectNoDisconnectedStep(page)` — before every save and after the run. Assert per step id
  with a retrying `toHaveCount`, never one `evaluateAll` snapshot: the canvas re-renders as the
  editor works and a snapshot between two renders reports a graph that was never on screen.
- The 60-second per-test ceiling in `playwright.config.js`. A slow UI spec is a bug report
  (an engine not claiming, a wait that is really a hang) — let it fail; never `test.setTimeout`.
  Split a long flow into two `test()`s in a `test.describe.serial` instead.

Tidy the canvas (Ctrl+Shift+L) before opening a step — palette drops overlap. Address a
control by role (`getByRole('textbox', { name: 'Query' })`): the **ƒx** button's `aria-label`
contains the field title, so `getByLabel('<Title>')` matches two elements. An untyped (`Any`)
field renders the value editor and commits on **blur** — `fill()` then `blur()`.

`tests/demo/` builds the demo processes: a fixed name in the `demo` folder, deleted and rebuilt
every run via `removeDemoProcess` (which goes through the folder's 409 guard, and is therefore
also the test of it), with any data it needs created by a step in the process.

Verify with `cd designer; npm run build` before claiming a frontend change works.
