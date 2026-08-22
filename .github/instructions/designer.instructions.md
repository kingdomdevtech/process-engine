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
  (`group`, `advanced`, `widget`, `showIf`, `labels`, `secret`, `unit`, `placeholder`, …).
  Field components live in `components/fields/`.
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

- Edge `sourceHandle` becomes `Connection.source_port`.
- `position` is designer-owned, so a definition built by the API or a test has every step at
  (0,0). `layoutGraph` in `layout.js` lays those out in dependency order on load (`needsLayout`
  gates it) **without writing back**. The same function backs *Tidy up steps* (Ctrl+Shift+L),
  which does write positions and is undoable.
- `layout.js` also owns canvas orientation (`horizontal | vertical`, stored in `pe_canvas_dir`)
  — a per-browser preference, deliberately not part of the definition. `StepNode.jsx` reads it
  to move handles between the sides and the top/bottom; moving a handle needs
  `useUpdateNodeInternals` or the edges keep their old anchors. Flipping direction re-runs the
  layout, since old positions leave every edge doubling back.
- Undo/redo covers canvas *structure* only (drop / connect / delete / drag), by design.
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

Verify with `cd designer; npm run build` before claiming a frontend change works.
