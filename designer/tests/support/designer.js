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
 * whose steps were skipped, or a canvas with a step nothing reaches, is a
 * process that did not do the work. Assert both, in every UI spec.
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

/** The run timeline in the editor's inspector. */
export function runDetail(page) {
  return page.locator('[data-tour="inspector"] .panel').filter({ hasText: 'Run detail' })
}

/**
 * MANDATORY. The run finished, every step succeeded, and none was skipped.
 *
 * "Skipped" is the quiet one: a step whose upstream emitted nothing is skipped
 * rather than failed, and the run still reports success — so a test that only
 * checks the run badge passes while half the process never happened. Pending
 * and running mean the poll gave up early. So the gate is: the timeline says
 * `Steps · n/n`, and the only status badge anywhere in it is Succeeded.
 */
export async function expectRunPassed(page, steps) {
  const detail = runDetail(page)
  await expect(detail).toBeVisible({ timeout: 30_000 })
  await expect(
    detail.getByText(new RegExp(`Steps\\s*·\\s*${steps}/${steps}`)),
    `all ${steps} steps should have succeeded`,
  ).toBeVisible({ timeout: RUN_TIMEOUT })

  for (const status of ['failed', 'skipped', 'pending', 'running', 'cancelled']) {
    await expect(detail.locator(`.badge-${status}`), `the run reports a ${status} step`).toHaveCount(0)
  }
  // one badge for the run itself, one per step
  await expect(detail.locator('.badge-succeeded')).toHaveCount(steps + 1)
}
