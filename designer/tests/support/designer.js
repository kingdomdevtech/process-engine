/**
 * Shared helpers for the browser tests — and the gate every one of them has to
 * pass.
 *
 * These tests are a real user at the keyboard: sign in on `/login`, drag steps
 * out of the palette, fill the forms, save through the app, press Run, read the
 * answer off the screen. Nothing here calls `/api/...` from inside the page.
 * The one thing read outside the browser is the API token, which a person would
 * have been given rather than typed from memory — that is `authToken()`, and it
 * is read in Node, not fetched by the page.
 *
 * `expectRunPassed` and `expectNoDisconnectedStep` are the mandatory pass
 * criteria (see the "Browser tests must go through the designer UI" section of
 * CLAUDE.md). A green Playwright report is not a passing test on its own: a run
 * with an unaccounted-for skipped step, or a canvas with a step nothing reaches,
 * is a process that did not do the work. Assert both, in every UI spec.
 */

import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect } from '@playwright/test'

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

export const TRIGGER = '__trigger__'

/**
 * How long a queued run may take before the test calls it stuck.
 *
 * Deliberately short. A run of a few steps is claimed and finished in seconds;
 * waiting minutes for one only turns "no engine is listening" into a slow pass
 * of the clock instead of a failure that names the problem.
 */
export const RUN_TIMEOUT = 30_000

function fileText(path) {
  try {
    return readFileSync(path, 'utf8')
  } catch {
    return ''
  }
}

/**
 * The admin credential this deployment is running with.
 *
 * The same three places the engine looks, in the same order: the environment
 * wins, then `.env` (what `start-local.sh` exports), then the token file the
 * API generates on first start. Committing one would be committing a
 * credential, and hard-coding a fake one makes every spec fail at the login
 * page for a reason that has nothing to do with what it tests.
 */
export function authToken() {
  const fromEnvironment = process.env.PROCESS_ENGINE_AUTH_TOKEN
  if (fromEnvironment?.trim()) return fromEnvironment.trim()

  const declared = fileText(resolve(REPO, '.env')).match(/^\s*PROCESS_ENGINE_AUTH_TOKEN\s*=\s*(.+)$/m)
  if (declared?.[1]?.trim()) return declared[1].trim()

  const generated = fileText(resolve(REPO, '.process_engine_auth')).trim()
  if (generated) return generated

  throw new Error(
    'No API token found. Set PROCESS_ENGINE_AUTH_TOKEN, put it in .env, or start the API once so it writes .process_engine_auth.',
  )
}

/**
 * The guided tour opens itself for a first-time visitor once the dashboard
 * settles, and its backdrop swallows clicks. Leave through its own button, the
 * way a person would — that also marks it seen for the rest of the session.
 */
export async function dismissTour(page) {
  const skip = page.getByRole('button', { name: /^Skip tour$/ })
  await skip.click({ timeout: 4_000 }).catch(() => {})
  await expect(skip).toHaveCount(0)
}

/** Sign in with the API token, exactly as the login page offers it. */
export async function signIn(page) {
  await page.goto('/login')
  await page.getByRole('button', { name: /Use an API token instead/i }).click()
  await page.locator('#pe-token').fill(authToken())
  await page.getByRole('button', { name: /^Sign in$/ }).click()
  await expect(page).toHaveURL(/\/app$/)
  await dismissTour(page)
}

// ---- the dashboard -------------------------------------------------------------

/** The folder whose processes the API refuses to delete. */
export const DEMO_FOLDER = 'demo'

/* Where a demo process is moved on its way to being deleted. Any folder that is
   not the protected one would do; naming it after the demo keeps the two
   together if a run ever dies between the move and the delete. */
const ATTIC = `${DEMO_FOLDER} attic`

/**
 * Delete a demo process from the dashboard, guard and all — so a demo spec can
 * build the same process from scratch every run under a stable name.
 *
 * Which is only possible *through* the guard, and that makes this the test of
 * it. A process in the `demo` folder offers no usable Delete on the dashboard
 * and the API refuses one whatever the menu says (409), because the demos are
 * what a new person is shown first and a delete is one click away from a name
 * that looks disposable. It is a folder, though, and not a lock: moving it out
 * is an ordinary edit, and then it deletes like anything else. That is the whole
 * sequence a person would follow, and it is what runs here.
 *
 * Answers whether anything was removed, so a first run on a fresh install is
 * not a failure.
 */
export async function removeDemoProcess(page, name) {
  await page.goto('/app')
  const search = page.getByLabel('Search processes and folders')
  const nothingYet = page.getByText('No processes yet')
  // the search box only exists once there is something to search
  await expect(search.or(nothingYet)).toBeVisible()
  if (await nothingYet.count()) return false

  await search.fill(name)
  /* List, not the default Grid: a grid card is itself `role="button"`, which
     makes ARIA treat everything inside it as presentation — so the card's own
     actions menu is not a button as far as the accessibility tree (or this
     locator) is concerned. The list rows expose it, and switching layout is
     something a person does with one click. */
  await page.getByRole('button', { name: 'List', exact: true }).click()
  const rowMenu = page.getByRole('button', { name: `Actions for ${name}` })
  await expect(rowMenu.first().or(page.getByText('Nothing matches'))).toBeVisible()
  if ((await rowMenu.count()) === 0) return false // never built on this install

  await rowMenu.first().click()
  const guarded = page.getByRole('menuitem', { name: `Delete — protected by “${DEMO_FOLDER}”` })
  if (await guarded.count()) {
    await expect(guarded, 'a process in the demo folder should not be deletable where it sits').toBeDisabled()
    // and *Move to folder…*, right above it and enabled, is the way out
    await page.getByRole('menuitem', { name: 'Move to folder…' }).click()
    await page.locator('#pe-prompt-input').fill(ATTIC)
    await page.getByRole('button', { name: /^Move$/ }).click()
    await expect(page.getByText('Moved', { exact: true })).toBeVisible()
    await rowMenu.first().click()
  }

  await page.getByRole('menuitem', { name: 'Delete', exact: true }).click()
  await page.getByRole('button', { name: /^Delete process$/ }).click()
  await expect(rowMenu, `“${name}” should be gone`).toHaveCount(0)
  return true
}

/**
 * Open a process from the dashboard by name, the way a person finds one again.
 *
 * Names, not ids, across a test boundary: a spec split into two `test()`s so
 * each gets its own budget should look the process up the way the product
 * offers it rather than handing an id from one test to the other.
 *
 * The row is addressed by its own actions menu, not by its text: the dashboard
 * also lists recent runs, and those rows carry the process name too.
 */
export async function openProcess(page, name) {
  await page.goto('/app')
  await page.getByLabel('Search processes and folders').fill(name)
  // List, not Grid — see `removeDemoProcess` for why the grid card hides its menu
  await page.getByRole('button', { name: 'List', exact: true }).click()
  const row = page
    .locator('table tbody tr')
    .filter({ has: page.getByRole('button', { name: `Actions for ${name}` }) })
  await expect(row, `“${name}” should be on the dashboard`).toHaveCount(1)
  // anywhere but the last cell, which stops the click to keep the menu usable
  await row.getByText(name, { exact: true }).click()
  await expect(page.getByLabel('Process name')).toHaveValue(name)
}

// ---- the canvas ---------------------------------------------------------------

/** Every step on the canvas, in the order React Flow drew them. */
export function stepIds(page) {
  return page.locator('.react-flow__node-step').evaluateAll((nodes) => nodes.map((node) => node.dataset.id))
}

/**
 * Add a step by clicking its palette entry, and answer with the id it was
 * given. Matched on the plugin key printed under the name, so "Log" cannot
 * collect a step whose description happens to mention logging.
 */
export async function addStep(page, pluginKey) {
  const before = await stepIds(page)
  const entry = page
    .locator('[data-tour="step-palette"] button')
    .filter({ has: page.getByText(pluginKey, { exact: true }) })
  await expect(entry).toHaveCount(1)
  await entry.click()
  await expect.poll(async () => (await stepIds(page)).length).toBe(before.length + 1)
  const added = (await stepIds(page)).find((id) => !before.includes(id))
  expect(added, 'the new step should have an id of its own').toBeTruthy()
  return added
}

/** Open a step (or the trigger box) in the inspector. */
export async function select(page, nodeId) {
  await page.locator(`.react-flow__node[data-id="${nodeId}"]`).click()
}

/** The arrow between two nodes, addressed the way the canvas labels it. */
export function arrow(page, source, target) {
  return page.locator(`.react-flow__edge[aria-label="Edge from ${source} to ${target}"]`)
}

export async function expectConnected(page, source, target) {
  await expect(arrow(page, source, target), `${source} should feed ${target}`).toHaveCount(1)
}

export async function expectNotConnected(page, source, target) {
  await expect(arrow(page, source, target), `${source} should no longer feed ${target}`).toHaveCount(0)
}

/**
 * MANDATORY. Every step is reached by something — the trigger box or another
 * step. A step nothing points at never runs, and a canvas that shows one is a
 * process that silently does less than it looks like it does.
 */
export async function expectNoDisconnectedStep(page) {
  const ids = await stepIds(page)
  expect(ids.length, 'the canvas should have at least one step').toBeGreaterThan(0)
  /* One retrying assertion per step rather than one snapshot of every edge:
     the canvas re-renders as the editor works, and a snapshot read between two
     of those renders reports an empty graph that was never on screen. */
  for (const id of ids) {
    await expect(
      page.locator(`.react-flow__edge[aria-label$=" to ${id}"]`),
      `step ${id} has no incoming arrow — nothing would run it`,
    ).toHaveCount(1)
  }
}

/** Where one node sits on the canvas, in flow coordinates. */
export function nodePosition(page, nodeId) {
  return page.locator(`.react-flow__node[data-id="${nodeId}"]`).evaluate((node) => {
    const [x, y] = (node.style.transform.match(/-?\d+(\.\d+)?/g) ?? ['0', '0']).map(Number)
    return { x, y }
  })
}

/** Where one node sits *and* how big it is, in flow coordinates.
 *
 * `offsetWidth`/`offsetHeight` are the card's layout size, which is the same
 * unit the transform is in — the viewport's zoom scales what you see without
 * changing either, so these compare directly with a point off an edge path.
 */
export function nodeBox(page, nodeId) {
  return page.locator(`.react-flow__node[data-id="${nodeId}"]`).evaluate((node) => {
    const [x, y] = (node.style.transform.match(/-?\d+(\.\d+)?/g) ?? ['0', '0']).map(Number)
    return { x, y, width: node.offsetWidth, height: node.offsetHeight }
  })
}

/** Where an arrow starts, read off the `M` of its own path. */
export function edgeStart(page, source, target) {
  return arrow(page, source, target)
    .locator('.react-flow__edge-path')
    .evaluate((path) => {
      const [x, y] = (path.getAttribute('d').match(/-?\d+(\.\d+)?/g) ?? []).slice(0, 2).map(Number)
      return { x, y }
    })
}

/**
 * The arrow leaves the named border of the step it comes from.
 *
 * This is the whole point of the floating edges: an arrow is anchored to
 * whichever side of the card faces the step it points at, so the same canvas can
 * be wired left-to-right and top-to-bottom. Asserting it needs the geometry
 * rather than a class name — nothing in the DOM says which side was chosen.
 */
export async function expectArrowLeaves(page, source, target, side) {
  await expect(arrow(page, source, target), `${source} should feed ${target}`).toHaveCount(1)
  await expect
    .poll(
      async () => {
        /* The canvas re-renders as the editor works and each read is a separate
           round trip, so a stale pair is normal rather than a failure — poll
           until one pair of reads agrees. */
        try {
          const box = await nodeBox(page, source)
          const start = await edgeStart(page, source, target)
          const border = {
            left: box.x,
            right: box.x + box.width,
            top: box.y,
            bottom: box.y + box.height,
          }[side]
          return Math.abs((side === 'left' || side === 'right' ? start.x : start.y) - border)
        } catch {
          return Number.POSITIVE_INFINITY
        }
      },
      { message: `the arrow from ${source} to ${target} should leave its ${side} border` },
    )
    .toBeLessThanOrEqual(2)
}

/**
 * Drag a step by hand, the way someone tidying up by eye would.
 *
 * `dx`/`dy` are screen pixels. React Flow starts a node drag from the pointer
 * events, so the move is stepped rather than teleported — one jump from press to
 * release looks like a click and leaves the node where it was.
 */
export async function dragNode(page, nodeId, dx, dy) {
  const node = page.locator(`.react-flow__node[data-id="${nodeId}"]`)
  const box = await node.boundingBox()
  const from = { x: box.x + box.width / 2, y: box.y + box.height / 2 }
  await page.mouse.move(from.x, from.y)
  await page.mouse.down()
  /* React Flow arms the drag on the first pointer move *after* the press, so
     nudge it a pixel before the real move — a single jump lands as one event
     with the press behind it and is read as a click, which leaves the node
     exactly where it was. */
  await page.mouse.move(from.x + Math.sign(dx || 1), from.y + Math.sign(dy || 1))
  await page.mouse.move(from.x + dx, from.y + dy, { steps: 12 })
  await page.mouse.up()
}

/**
 * Drag one step by hand until it sits directly below another.
 *
 * The deltas are worked out from the two cards on screen rather than passed in,
 * which keeps the move landing in the same place whatever the canvas is zoomed
 * to — and leaves the two centres in a straight vertical line, so which border
 * the arrow between them leaves is arithmetic rather than a guess about card
 * sizes.
 */
export async function dragNodeBelow(page, nodeId, referenceId) {
  /* A press that lands a moment after the canvas moved — a tidy-up, a fit view —
     hits the pane where the card used to be and the node stays put, silently, so
     an arrow assertion after it would report geometry nobody chose. Read the two
     cards, move, then check in flow coordinates that the card really is below
     the other one, and say where it ended up if three tries never get it there. */
  let moved
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const card = await page.locator(`.react-flow__node[data-id="${nodeId}"]`).boundingBox()
    const under = await page.locator(`.react-flow__node[data-id="${referenceId}"]`).boundingBox()
    await dragNode(
      page,
      nodeId,
      under.x + under.width / 2 - (card.x + card.width / 2),
      under.y + under.height * 2.5 - (card.y + card.height / 2),
    )
    moved = await nodeBox(page, nodeId)
    const reference = await nodeBox(page, referenceId)
    // clear of the bottom of the card above, and on its centre line
    if (moved.y > reference.y + reference.height) return
  }
  throw new Error(
    `dragging ${nodeId} below ${referenceId} left it at ${JSON.stringify(moved)} — the press did not reach the card`,
  )
}

/** Where each step sits, so a layout assertion can read the canvas. */
export async function stepPositions(page) {
  const entries = await page.locator('.react-flow__node-step').evaluateAll((nodes) =>
    nodes.map((node) => {
      const [x, y] = (node.style.transform.match(/-?\d+(\.\d+)?/g) ?? ['0', '0']).map(Number)
      return [node.dataset.id, { x, y }]
    }),
  )
  return Object.fromEntries(entries)
}

// ---- saving and running --------------------------------------------------------

export async function save(page) {
  await page.getByRole('button', { name: /^Save$/ }).click()
  // the persistent save-state chip, which reads "Unsaved" until the PUT lands
  await expect(page.getByText('Saved', { exact: true })).toBeVisible()
  // and a first save turns /processes/new into the id it was given
  await expect(page).toHaveURL(/\/app\/processes\/(?!new(\/|$))[^/?#]+/)
}

export async function publish(page) {
  await page.getByRole('button', { name: /^Publish$/ }).click()
  await expect(page.getByText(/Published version \d+/)).toBeVisible()
}

/**
 * The run timeline, wherever it is on screen: the editor's inspector while the
 * process is being built, or the Runs page when a finished run is opened there.
 * The gate below reads the same thing either way, which is what lets a spec
 * check a sub-process run it never had open in the editor.
 */
export function runDetail(page) {
  return page.locator('[data-tour="inspector"] .panel, aside.card').filter({ hasText: 'Run detail' })
}

/**
 * Open every collapsed branch of a JSON tree inside `scope`.
 *
 * `JsonTree` renders two levels open and the rest closed, so a value further in
 * — a row of a query result, a field of an item — is genuinely not on screen and
 * asserting on the block's text would be asserting on a person's first glance
 * rather than on the data. Opening a node reveals more closed nodes, hence the
 * passes; each pass clicks from the bottom up so the earlier toggles keep their
 * positions while the later ones grow children.
 */
export async function expandJson(scope, passes = 4) {
  for (let pass = 0; pass < passes; pass += 1) {
    const closed = scope.locator('button[aria-expanded="false"]')
    const count = await closed.count()
    if (count === 0) return
    for (let index = count - 1; index >= 0; index -= 1) await closed.nth(index).click()
  }
}

/**
 * MANDATORY. The run finished and every step it was supposed to run succeeded.
 *
 * "Skipped" is the quiet one: a step whose upstream delivered nothing is skipped
 * rather than failed, and the run still reports success — so a test that only
 * checks the run badge passes while half the process never happened. Pending and
 * running mean the poll gave up early. The timeline counts only succeeded steps
 * in `Steps · done/total`, so that number *is* the assertion.
 *
 * A branch is the one honest reason for a skip: a Condition sends its input down
 * one port, and the steps on the other are skipped by design. Declare how many
 * with `{ skipped: n }` and the count is checked exactly — a skip is never
 * tolerated, only accounted for. Leave it out and none is allowed, which is what
 * a spec without a branch should say.
 */
export async function expectRunPassed(page, steps, { skipped = 0, timeout = RUN_TIMEOUT } = {}) {
  const detail = runDetail(page)
  const ran = steps - skipped
  await expect(detail).toBeVisible({ timeout: 30_000 })
  await expect(
    detail.getByText(new RegExp(`Steps\\s*·\\s*${ran}/${steps}`)),
    skipped
      ? `${ran} of ${steps} steps should have succeeded, with ${skipped} skipped by a branch`
      : `all ${steps} steps should have succeeded`,
  ).toBeVisible({ timeout })

  for (const status of ['failed', 'pending', 'running', 'cancelled']) {
    await expect(detail.locator(`.badge-${status}`), `the run reports a ${status} step`).toHaveCount(0)
  }
  await expect(
    detail.locator('.badge-skipped'),
    `exactly ${skipped} step(s) should have been skipped by a branch`,
  ).toHaveCount(skipped)
  // one badge for the run itself, one per step that ran
  await expect(detail.locator('.badge-succeeded')).toHaveCount(ran + 1)
}
