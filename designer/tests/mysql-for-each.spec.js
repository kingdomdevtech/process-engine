/**
 * Read rows from MySQL, run a sub-process for each one, log a value off the row.
 *
 * Everything here happens the way a person would do it: sign in on `/login`,
 * click steps out of the palette, fill the generated forms, wire the graph from
 * the Input tab, tidy the canvas, save, press Run draft, and read the run
 * timeline. No `/api/...` call is made from inside the page — see the "Browser
 * tests must go through the designer UI" section of CLAUDE.md.
 *
 * It covers:
 *
 *  1. rows out of `mysql_query`, one sub-process per row through `for_each`,
 *     and a specific value off each row written by a Log step;
 *  2. schedule and webhook triggers configured in the trigger box and nowhere
 *     else — not in the palette, not on a step;
 *  3. the first step connecting itself to the trigger box;
 *  4. every step after it connecting itself to the one before;
 *  5. the Input tab offering both an existing step and an existing process, and
 *     re-pointing the arrow when a step is chosen;
 *  6. For Each detecting the list from the step above it, and refreshing that
 *     field on demand;
 *  7. Tidy up steps laying the chain out clear of the trigger box.
 *
 * The canvas is tidied before any step is opened, because a palette drops its
 * steps around the middle of the view where the cards overlap — clicking one of
 * a stack is ambiguous for a person and for the test alike.
 *
 * It passes only if the run has no failed step, no skipped step and no step
 * nothing points at — `expectRunPassed` and `expectNoDisconnectedStep`.
 */

import { test, expect } from '@playwright/test'

import {
  TRIGGER,
  addStep,
  expectConnected,
  expectNoDisconnectedStep,
  expectNotConnected,
  expectRunPassed,
  nodePosition,
  publish,
  runDetail,
  save,
  select,
  signIn,
  stepPositions,
} from './support/designer.js'

/* No timeout override: the 60s ceiling in playwright.config.js applies here
   too. The whole flow — two processes, a publish, a queued run and its two
   sub-runs — is seconds of real work, so needing longer means something is
   wrong rather than slow. */
test.use({ viewport: { width: 1680, height: 1000 } })

const DB_URL = 'mysql+pymysql://process_engine:process_engine@127.0.0.1:3306/process_engine'
/* Two rows, no table: the test is about iteration, not about seeded data, and a
   fixture table would make it fail for a reason it does not test. */
const QUERY = "SELECT 'alpha' AS name UNION ALL SELECT 'beta' AS name"

test('rows from MySQL are iterated one sub-process per row, and a row value is logged', async ({ page }) => {
  /* Unique per run: these land in the same database a person is using, and the
     run history is searched by name further down. */
  const stamp = Date.now().toString(36)
  const childName = `pw ${stamp} row logger`
  const parentName = `pw ${stamp} orders fan-out`

  await signIn(page)

  // ---- the sub-process: one Log step, run once per row -------------------------

  let childId
  await test.step('a published sub-process logs one row', async () => {
    await page.goto('/app/processes/new')
    await page.getByLabel('Folder').fill('playwright')
    await page.getByLabel('Process name').fill(childName)

    const logId = await addStep(page, 'log')

    // (3) the only step wires itself to the trigger box
    await expectConnected(page, TRIGGER, logId)

    await page.locator('#pe-step-name').fill('log row')
    await page
      .locator('[data-tour="inspector"]')
      .getByRole('textbox', { name: 'Message' })
      .fill('row {{ trigger.index }}: {{ trigger.item.name }}')

    await expectNoDisconnectedStep(page)
    await save(page)
    // for_each runs a *published* process, so a draft would never be found
    await publish(page)

    childId = page.url().match(/\/app\/processes\/([^/?#]+)/)?.[1]
    expect(childId, 'the saved sub-process should have an id in the URL').toBeTruthy()
  })

  // ---- the parent: trigger box, three steps, one arrow each --------------------

  await page.goto('/app/processes/new')
  await page.getByLabel('Folder').fill('playwright')
  await page.getByLabel('Process name').fill(parentName)

  const inspector = page.locator('[data-tour="inspector"]')
  const palette = page.locator('[data-tour="step-palette"]')

  await test.step('(2) schedule and webhook are configured in the trigger box', async () => {
    await select(page, TRIGGER)

    await inspector.getByRole('button', { name: /^Schedule$/ }).click()
    await inspector.getByRole('button', { name: 'Every 15 min' }).click()
    await expect(inspector.getByLabel('Cron expression')).toHaveValue('*/15 * * * *')

    await inspector.getByRole('button', { name: /^Webhook$/ }).click()
    await inspector.getByLabel('Webhook path').fill(`pw_${stamp}`)
    await expect(inspector.getByText(`POST /api/hooks/pw_${stamp}`)).toBeVisible()

    // and nowhere else: no trigger step to drop on the canvas
    for (const term of ['schedule', 'webhook', 'cron']) {
      await palette.getByLabel('Search steps').fill(term)
      await expect(palette.getByText(`No step matches “${term}”.`)).toBeVisible()
    }
    await palette.getByRole('button', { name: 'Clear search' }).click()
  })

  const ordersId = await addStep(page, 'mysql_query')

  await test.step('(3) the first step wires itself to the trigger box', async () => {
    await expectConnected(page, TRIGGER, ordersId)
  })

  await test.step('the query is configured on its generated form', async () => {
    await page.locator('#pe-step-name').fill('orders')
    await inspector.getByRole('combobox', { name: 'Connect using' }).selectOption({ label: 'A connection string' })
    await inspector.getByRole('textbox', { name: 'Connection string' }).fill(DB_URL)
    // "Query" and not { exact: true }: a required field's label carries its *
    await inspector.getByRole('textbox', { name: 'Query' }).fill(QUERY)
  })

  await test.step('(2) a step has no trigger configuration of its own', async () => {
    await expect(inspector.getByLabel('Cron expression')).toHaveCount(0)
    await expect(inspector.getByLabel('Webhook path')).toHaveCount(0)
    await expect(inspector.getByRole('button', { name: /^Schedule$/ })).toHaveCount(0)
    await expect(inspector.getByRole('button', { name: /^Webhook$/ })).toHaveCount(0)
  })

  const forEachId = await addStep(page, 'for_each')
  await test.step('(4) a new step wires itself to the previous one', async () => {
    await expectConnected(page, ordersId, forEachId)
  })
  await page.locator('#pe-step-name').fill('for each row')

  const summaryId = await addStep(page, 'log')
  await test.step('(4) and so does the next', async () => {
    await expectConnected(page, forEachId, summaryId)
  })
  await page.locator('#pe-step-name').fill('summary')

  await expectNoDisconnectedStep(page)
  await save(page)

  // ---- (7) tidy up ------------------------------------------------------------

  await test.step('(7) tidy up lays the chain out clear of the trigger box', async () => {
    // the shortcut is ignored while a form field has focus, so click away first
    await select(page, TRIGGER)
    await page.keyboard.press('Control+Shift+L')
    await expect(page.getByText('Steps repositioned')).toBeVisible()

    const trigger = await nodePosition(page, TRIGGER)
    await expect
      .poll(async () => (await stepPositions(page))[ordersId].x, {
        message: 'the first step should sit clear of the trigger box',
      })
      .toBeGreaterThan(trigger.x)

    const at = await stepPositions(page)
    expect(at[forEachId].x, 'each step should sit right of the one feeding it').toBeGreaterThan(at[ordersId].x)
    expect(at[summaryId].x).toBeGreaterThan(at[forEachId].x)
    // one chain, one lane
    expect(at[forEachId].y).toBe(at[ordersId].y)
    expect(at[summaryId].y).toBe(at[ordersId].y)
  })

  // ---- (6) For Each works out which list it is iterating ----------------------

  const items = inspector.getByRole('textbox', { name: 'List to work through' })

  await test.step('(6) For Each detects the list from the step above it', async () => {
    await select(page, forEachId)
    // it fills itself in the first time the form opens — the detection is the
    // documented default, not something to press a button for
    await expect(items).toHaveValue(/^\{\{ steps\.orders\.output(\.rows)? \}\}$/)

    // and refreshes on demand once the connection above it changes
    await items.fill('')
    await items.blur()
    await expect(items).toHaveValue('')
    await inspector.getByRole('button', { name: 'Detect from the previous step' }).click()
    await expect(items).toHaveValue(/^\{\{ steps\.orders\.output(\.rows)? \}\}$/)
  })

  // ---- (5) the Input tab: another step, or another process ---------------------

  await test.step('(5) the input source offers steps and processes', async () => {
    await inspector.getByRole('tab', { name: 'Input' }).click()
    const source = inspector.getByRole('combobox', { name: 'Input source' })
    await expect(source).toBeVisible()

    // the step feeding it is what the panel shows, because that is the arrow
    await expect(source).toHaveValue(`step:${ordersId}`)
    await expect(source.getByRole('option', { name: 'Trigger data' })).toHaveCount(1)
    await expect(source.getByRole('option', { name: 'orders', exact: true })).toHaveCount(1)
    // a step downstream of this one is not offered: that arrow would be a cycle
    await expect(source.getByRole('option', { name: 'summary', exact: true })).toHaveCount(0)
    // and an existing process is
    await expect(source.getByRole('option', { name: childName })).toHaveCount(1)
    // but never this one — every item would start the process again
    await expect(source.getByRole('option', { name: parentName })).toHaveCount(0)
  })

  await test.step('(5) choosing a source re-connects the arrow', async () => {
    const source = inspector.getByRole('combobox', { name: 'Input source' })

    await source.selectOption(TRIGGER)
    await expectNotConnected(page, ordersId, forEachId)
    await expectConnected(page, TRIGGER, forEachId)

    await source.selectOption(`step:${ordersId}`)
    await expectConnected(page, ordersId, forEachId)
    await expectNotConnected(page, TRIGGER, forEachId)
  })

  await test.step('(5) choosing a process runs it once per item', async () => {
    await inspector.getByRole('combobox', { name: 'Input source' }).selectOption(`process:${childId}`)
    // the arrow still delivers the list; the sub-process is what each item goes to
    await expectConnected(page, ordersId, forEachId)

    await inspector.getByRole('tab', { name: 'Config' }).click()
    await expect(inspector.getByRole('combobox', { name: 'How to iterate' })).toHaveValue('process')
    await expect(inspector.getByRole('combobox', { name: 'Published process to run for each one' })).toHaveValue(childId)
  })

  // ---- (1) the value off the row, in the parent's own log ----------------------

  await test.step('the summary step reports what came back', async () => {
    await select(page, summaryId)
    await inspector
      .getByRole('textbox', { name: 'Message' })
      .fill(
        'iterated {{ steps.for_each_row.output.count }} rows; first was ' +
          '{{ steps.for_each_row.output.results.0.output.item.name }}',
      )
  })

  // ---- run it -----------------------------------------------------------------

  await expectNoDisconnectedStep(page)
  await save(page)
  await expect(page.getByText(/This process cannot run yet/i)).toHaveCount(0)

  await test.step('the run finishes with nothing failed and nothing skipped', async () => {
    await page.getByRole('button', { name: /^Run draft$/ }).click()
    await expectRunPassed(page, 3)
    await expectNoDisconnectedStep(page)
  })

  await test.step('(1) For Each reports one sub-run per row', async () => {
    const detail = runDetail(page)
    await detail.getByRole('button', { name: 'for each row' }).click()
    const outputs = detail.locator('.section-label', { hasText: 'Outputs' }).locator('..')
    // the two rows the query returned, both of them run to the end
    await expect(outputs).toContainText(/count\s*2/)
    await expect(outputs).toContainText(/succeeded\s*2/)
    await expect(outputs).toContainText(/failed\s*0/)
  })

  await test.step('(1) each sub-run logged its own row value', async () => {
    await page.goto('/app/runs')
    await page.getByLabel('Search runs').fill(childName)

    const rows = page.locator('table tbody tr')
    await expect(rows, 'one sub-run per row of the query').toHaveCount(2)
    await expect(page.locator('table tbody .badge-succeeded')).toHaveCount(2)

    await rows.first().click()
    const detail = page.locator('aside.card').filter({ hasText: 'Run detail' })
    await expect(detail.getByText(/Steps\s*·\s*1\/1/)).toBeVisible()

    await detail.getByRole('button', { name: 'log row' }).click()
    // the row this sub-run was handed, as the Log step saw it
    const input = detail.locator('.section-label', { hasText: 'Input' }).locator('..')
    await expect(input).toContainText(/name\s*"(alpha|beta)"/)
    await expect(input).toContainText(/index\s*[01]/)
  })
})
