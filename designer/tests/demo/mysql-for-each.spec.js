/**
 * The MySQL fan-out demo: build it, publish it, run it, read the answer.
 *
 * Everything in `tests/demo/` builds a **demo process** — a real, published
 * process left behind in the `demo` folder for someone to open and look at. So
 * this spec is a fixture as much as a test: it deletes both processes and builds
 * them again from scratch every run, which is why their names are fixed rather
 * than stamped, and why the delete has to go through the folder guard (a process
 * in `demo` cannot be deleted until it is moved out — see `removeDemoProcess`).
 *
 * What it builds:
 *
 *   Demo review one order (the sub-process, one order at a time)
 *     trigger ─┬─▶ log row                      two lanes, run at the same time
 *              └─▶ check amount ─true──▶ approve   UPDATE … 'approved'
 *                                └─false─▶ reject   UPDATE … 'on hold'
 *
 *   Demo MySQL orders fan-out (the parent)
 *     create table ▶ seed orders ▶ orders ▶ for each order ▶ review ▶ summary
 *
 * Everything happens the way a person would do it: sign in on `/login`, click
 * steps out of the palette, fill the generated forms, wire the graph from the
 * Input tab, tidy the canvas, save, press Run draft, and read the run timeline.
 * No `/api/...` call is made from inside the page — see the "Browser tests must
 * go through the designer UI" section of CLAUDE.md. In particular the demo
 * creates and seeds its own tables *as steps*, because a spec may not reach past
 * the UI to set one up.
 *
 * It covers:
 *
 *  1. rows out of `mysql_query`, one sub-process per row through `for_each`, and
 *     a value off each row written by a Log step;
 *  2. schedule and webhook triggers configured in the trigger box and nowhere
 *     else — not in the palette, not on a step;
 *  3. the first step connecting itself to the trigger box;
 *  4. every step after it connecting itself to the one before — on a real port,
 *     which for a Condition is its first branch and never a `main` it has not
 *     got;
 *  5. the Input tab offering an existing step, each branch of a branching step,
 *     and an existing process — and re-pointing the arrow when one is chosen;
 *  6. For Each detecting the list from the step above it, and refreshing that
 *     field on demand;
 *  7. Tidy up steps laying the graph out clear of the trigger box;
 *  8. two steps hanging off the trigger box running at the same time, one of
 *     them a Condition whose two branches write different rows;
 *  9. arrows that leave whichever side of a card faces the step they point at,
 *     so one canvas can be wired left-to-right and top-to-bottom at once;
 * 10. a process in the `demo` folder refusing to be deleted until it is moved.
 *
 * The canvas is tidied before any step is opened, because the palette drops its
 * steps around the middle of the view where the cards overlap — clicking one of
 * a stack is ambiguous for a person and for the test alike.
 *
 * It passes only if no step failed, no step nothing points at, and the only
 * skipped step is the branch the Condition did not take — `expectRunPassed`
 * (with its skip *declared and counted*) and `expectNoDisconnectedStep`.
 */

import { test, expect } from '@playwright/test'

import {
  DEMO_FOLDER,
  TRIGGER,
  addStep,
  dragNodeBelow,
  expandJson,
  expectArrowLeaves,
  expectConnected,
  expectNoDisconnectedStep,
  expectNotConnected,
  expectRunPassed,
  nodePosition,
  publish,
  removeDemoProcess,
  runDetail,
  save,
  select,
  signIn,
  stepPositions,
} from '../support/designer.js'

/* No timeout override: the 60s ceiling in playwright.config.js applies to each
   test here. Building a process, publishing it, queueing a run and reading the
   timeline is seconds of real work, so needing longer means something is wrong
   rather than slow. The two halves are separate tests so each gets its own
   budget — not because they are independent, which is what `serial` says. */
test.use({ viewport: { width: 1680, height: 1000 } })

const DB_URL = 'mysql+pymysql://process_engine:process_engine@127.0.0.1:3306/process_engine'
/* Fixed names, not stamped ones: a demo is meant to be found again, and every
   run of this spec deletes the pair and builds them from scratch. */
const CHILD = 'Demo review one order'
const PARENT = 'Demo MySQL orders fan-out'

/* The demo's own table, created and seeded by its own first two steps. `REPLACE`
   rather than `INSERT` so a second run re-arms the demo instead of piling up
   rows: both orders go back to "new" and the branch decides them again. One
   above the threshold, one below, so both branches always happen. */
const CREATE_TABLE = [
  'CREATE TABLE IF NOT EXISTS demo_orders (',
  '  id INT PRIMARY KEY,',
  '  customer VARCHAR(60) NOT NULL,',
  '  amount DECIMAL(10,2) NOT NULL,',
  "  status VARCHAR(20) NOT NULL DEFAULT 'new'",
  ')',
].join('\n')
const SEED_ORDERS =
  'REPLACE INTO demo_orders (id, customer, amount, status) VALUES\n' +
  "  (1, 'Acme Corp', 900.00, 'new'),\n" +
  "  (2, 'Globex', 120.00, 'new')"
const READ_ORDERS = 'SELECT id, customer, amount, status FROM demo_orders ORDER BY id'
const READ_STATUSES = 'SELECT id, status FROM demo_orders ORDER BY id'
const APPROVE = "UPDATE demo_orders SET status = 'approved' WHERE id = :id"
const REJECT = "UPDATE demo_orders SET status = 'on hold' WHERE id = :id"

/** Fill in a MySQL step's connection, and one bound value if it takes one. */
async function configureMySQL(inspector, { field, sql, param }) {
  await inspector.getByRole('combobox', { name: 'Connect using' }).selectOption({ label: 'A connection string' })
  await inspector.getByRole('textbox', { name: 'Connection string' }).fill(DB_URL)
  await inspector.getByRole('textbox', { name: field }).fill(sql)
  if (!param) return
  /* Values stay out of the SQL — ":id" is bound, so a row's own id decides which
     row is updated and can never change what the statement does. */
  await inspector.getByRole('button', { name: 'Add value' }).click()
  await inspector.getByRole('textbox', { name: 'Name', exact: true }).fill(param.name)
  await inspector.getByRole('textbox', { name: 'Value', exact: true }).fill(param.value)
}

/**
 * Expand one step in the run timeline and hand back its Input and Outputs
 * blocks — scoped to that step, because more than one can be open at once and a
 * page-wide "the Outputs block" would then mean two different things.
 */
async function stepData(page, name) {
  const row = runDetail(page)
    .locator('li')
    .filter({ has: page.getByRole('button', { name, exact: true }) })
  await expect(row, `the timeline should list “${name}” once`).toHaveCount(1)
  const toggle = row.getByRole('button', { name, exact: true })
  if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click()
  return {
    input: row.locator('.section-label', { hasText: 'Input' }).locator('..'),
    outputs: row.locator('.section-label', { hasText: 'Outputs' }).locator('..'),
  }
}

/** The name of the one step a run skipped, read off its timeline. */
async function skippedStep(page) {
  const name = await runDetail(page)
    .locator('li')
    .filter({ has: page.locator('.badge-skipped') })
    .locator('button')
    .first()
    .textContent()
  return name.trim()
}

test.describe.serial('the MySQL orders fan-out demo', () => {
  test('a sub-process reviews one order in two parallel lanes, and writes the branch it took', async ({ page }) => {
    await signIn(page)

    await test.step('(10) last run’s demo processes are cleared out, guard and all', async () => {
      // the parent points at the child, so it goes first
      await removeDemoProcess(page, PARENT)
      await removeDemoProcess(page, CHILD)
    })

    await page.goto('/app/processes/new')
    await page.getByLabel('Folder').fill(DEMO_FOLDER)
    await page.getByLabel('Process name').fill(CHILD)

    const inspector = page.locator('[data-tour="inspector"]')
    const source = inspector.getByRole('combobox', { name: 'Input source' })

    // ---- lane one: say which order this is ------------------------------------

    const logId = await addStep(page, 'log')
    await test.step('(3) the first step wires itself to the trigger box', async () => {
      await expectConnected(page, TRIGGER, logId)
    })
    await page.locator('#pe-step-name').fill('log row')
    await inspector
      .getByRole('textbox', { name: 'Message' })
      .fill('order {{ trigger.item.id }} for {{ trigger.item.customer }}: {{ trigger.item.amount }}')

    // ---- lane two: decide it, in parallel -------------------------------------

    const checkId = await addStep(page, 'condition')
    await test.step('(4) a new step joins the end of the flow', async () => {
      await expectConnected(page, logId, checkId)
    })
    await page.locator('#pe-step-name').fill('check amount')

    await test.step('(5)(8) pointing it at the trigger box makes it a second lane', async () => {
      await inspector.getByRole('tab', { name: 'Input' }).click()
      await expect(source).toHaveValue(`step:${logId}`)
      await source.selectOption(TRIGGER)
      await expectNotConnected(page, logId, checkId)
      await expectConnected(page, TRIGGER, checkId)
      await inspector.getByRole('tab', { name: 'Config' }).click()
    })

    const amount = inspector.getByRole('textbox', { name: 'Value to check' })
    const threshold = inspector.getByRole('textbox', { name: 'Compared with' })
    await amount.fill('{{ trigger.item.amount }}')
    await amount.blur() // an untyped field commits on blur, so a number stays one
    await inspector.getByRole('combobox', { name: 'Test' }).selectOption('greater_than')
    await threshold.fill('500')
    await threshold.blur()

    // ---- the two branches ------------------------------------------------------

    const approveId = await addStep(page, 'mysql_execute')
    await page.locator('#pe-step-name').fill('approve')
    await test.step('(4) “and then” off a Condition is its first branch, not a main port', async () => {
      await expectConnected(page, checkId, approveId)
      await inspector.getByRole('tab', { name: 'Input' }).click()
      await expect(source, 'the arrow should come off the true branch').toHaveValue(`step:${checkId}:true`)
      await inspector.getByRole('tab', { name: 'Config' }).click()
    })
    await configureMySQL(inspector, {
      field: 'Statement',
      sql: APPROVE,
      param: { name: 'id', value: '{{ trigger.item.id }}' },
    })

    const rejectId = await addStep(page, 'mysql_execute')
    await page.locator('#pe-step-name').fill('reject')
    await test.step('(5) the other branch is a source the Input tab can name', async () => {
      await expectConnected(page, approveId, rejectId)
      await inspector.getByRole('tab', { name: 'Input' }).click()
      // a branching step is offered once per branch — "after the check" is not
      // an answer the graph could hold
      await expect(source.getByRole('option', { name: 'check amount (true)' })).toHaveCount(1)
      await expect(source.getByRole('option', { name: 'check amount (false)' })).toHaveCount(1)
      await expect(source.getByRole('option', { name: 'check amount', exact: true })).toHaveCount(0)

      await source.selectOption(`step:${checkId}:false`)
      await expectNotConnected(page, approveId, rejectId)
      await expectConnected(page, checkId, rejectId)
      await inspector.getByRole('tab', { name: 'Config' }).click()
    })
    await configureMySQL(inspector, {
      field: 'Statement',
      sql: REJECT,
      param: { name: 'id', value: '{{ trigger.item.id }}' },
    })

    await test.step('(8) both lanes start at the trigger box and neither waits for the other', async () => {
      await expectConnected(page, TRIGGER, logId)
      await expectConnected(page, TRIGGER, checkId)
      await expectNotConnected(page, logId, checkId)
      await expectNotConnected(page, checkId, logId)
    })

    await expectNoDisconnectedStep(page)
    await save(page)

    // ---- (7)(9) the canvas ------------------------------------------------------

    await test.step('(7) tidy up lays both lanes out clear of the trigger box', async () => {
      // the shortcut is ignored while a form field has focus, so click away first
      await select(page, TRIGGER)
      await page.keyboard.press('Control+Shift+L')
      await expect(page.getByText('Steps repositioned')).toBeVisible()

      const trigger = await nodePosition(page, TRIGGER)
      await expect
        .poll(async () => (await stepPositions(page))[checkId].x, {
          message: 'the lanes should start clear of the trigger box',
        })
        .toBeGreaterThan(trigger.x)

      const at = await stepPositions(page)
      expect(at[logId].x, 'the two lanes should start alongside each other').toBe(at[checkId].x)
      expect(at[logId].y).not.toBe(at[checkId].y)
      expect(at[approveId].x, 'a branch sits right of the step feeding it').toBeGreaterThan(at[checkId].x)
      expect(at[rejectId].x).toBeGreaterThan(at[checkId].x)
    })

    await test.step('(9) an arrow leaves whichever side of the card faces where it is going', async () => {
      /* `reject` is laid out level with the check and to its right, so that
         arrow leaves the right-hand border — as does the trigger's, for the same
         reason. Both are exact: the two cards share a centre line, so this says
         what the geometry chose and not what the card sizes happened to be. */
      await expectArrowLeaves(page, checkId, rejectId, 'right')
      await expectArrowLeaves(page, TRIGGER, logId, 'right')

      /* Now move the other branch under the check by hand. Its arrow leaves the
         bottom while `reject`'s still leaves the right: two directions on one
         canvas, with nothing switched and nothing stored. A hand-placed step
         must not be left with an arrow doubling back to the wrong face of it. */
      await dragNodeBelow(page, approveId, checkId)
      await expectArrowLeaves(page, checkId, approveId, 'bottom')
      await expectArrowLeaves(page, checkId, rejectId, 'right')

      // and the whole canvas can be laid out to read top to bottom instead
      await page.getByRole('button', { name: 'Canvas layout' }).click()
      await page.getByRole('menuitem', { name: 'Top to bottom' }).click()
      await expectArrowLeaves(page, checkId, rejectId, 'bottom')
      await expectArrowLeaves(page, TRIGGER, logId, 'bottom')

      // left to right is how the demo is left, so put it back
      await page.getByRole('button', { name: 'Canvas layout' }).click()
      await page.getByRole('menuitem', { name: 'Left to right' }).click()
      await expectArrowLeaves(page, checkId, rejectId, 'right')
    })

    await expectNoDisconnectedStep(page)
    await save(page)
    await expect(page.getByText(/This process cannot run yet/i)).toHaveCount(0)
    // for_each runs a *published* process, so a draft would never be found
    await publish(page)
  })

  test('the parent reads the orders, fans them out one per row, and reads the result back', async ({ page }) => {
    await signIn(page)

    await page.goto('/app/processes/new')
    await page.getByLabel('Folder').fill(DEMO_FOLDER)
    await page.getByLabel('Process name').fill(PARENT)

    const inspector = page.locator('[data-tour="inspector"]')
    const palette = page.locator('[data-tour="step-palette"]')
    const source = inspector.getByRole('combobox', { name: 'Input source' })

    await test.step('(2) schedule and webhook are configured in the trigger box', async () => {
      await select(page, TRIGGER)

      await inspector.getByRole('button', { name: /^Schedule$/ }).click()
      await inspector.getByRole('button', { name: 'Every 15 min' }).click()
      await expect(inspector.getByLabel('Cron expression')).toHaveValue('*/15 * * * *')

      await inspector.getByRole('button', { name: /^Webhook$/ }).click()
      await inspector.getByLabel('Webhook path').fill('demo_orders')
      await expect(inspector.getByText('POST /api/hooks/demo_orders')).toBeVisible()

      // and nowhere else: no trigger step to drop on the canvas
      for (const term of ['schedule', 'webhook', 'cron']) {
        await palette.getByLabel('Search steps').fill(term)
        await expect(palette.getByText(`No step matches “${term}”.`)).toBeVisible()
      }
      await palette.getByRole('button', { name: 'Clear search' }).click()
    })

    // ---- the demo makes its own data -------------------------------------------

    const createId = await addStep(page, 'mysql_execute')
    await test.step('(3) the first step wires itself to the trigger box', async () => {
      await expectConnected(page, TRIGGER, createId)
    })
    await page.locator('#pe-step-name').fill('create table')
    await configureMySQL(inspector, { field: 'Statement', sql: CREATE_TABLE })

    await test.step('(2) a step has no trigger configuration of its own', async () => {
      await expect(inspector.getByLabel('Cron expression')).toHaveCount(0)
      await expect(inspector.getByLabel('Webhook path')).toHaveCount(0)
      await expect(inspector.getByRole('button', { name: /^Schedule$/ })).toHaveCount(0)
      await expect(inspector.getByRole('button', { name: /^Webhook$/ })).toHaveCount(0)
    })

    const seedId = await addStep(page, 'mysql_execute')
    await expectConnected(page, createId, seedId)
    await page.locator('#pe-step-name').fill('seed orders')
    await configureMySQL(inspector, { field: 'Statement', sql: SEED_ORDERS })

    const ordersId = await addStep(page, 'mysql_query')
    await test.step('(4) and every step after joins the one before it', async () => {
      await expectConnected(page, seedId, ordersId)
    })
    await page.locator('#pe-step-name').fill('orders')
    // "Query" and not { exact: true }: a required field's label carries its *
    await configureMySQL(inspector, { field: 'Query', sql: READ_ORDERS })

    const forEachId = await addStep(page, 'for_each')
    await expectConnected(page, ordersId, forEachId)
    await page.locator('#pe-step-name').fill('for each order')

    const reviewId = await addStep(page, 'mysql_query')
    await expectConnected(page, forEachId, reviewId)
    await page.locator('#pe-step-name').fill('review')
    await configureMySQL(inspector, { field: 'Query', sql: READ_STATUSES })

    const summaryId = await addStep(page, 'log')
    await expectConnected(page, reviewId, summaryId)
    await page.locator('#pe-step-name').fill('summary')

    await expectNoDisconnectedStep(page)
    await save(page)

    // ---- (7) tidy up -------------------------------------------------------------

    await test.step('(7) tidy up lays the chain out clear of the trigger box', async () => {
      await select(page, TRIGGER)
      await page.keyboard.press('Control+Shift+L')
      await expect(page.getByText('Steps repositioned')).toBeVisible()

      const trigger = await nodePosition(page, TRIGGER)
      await expect
        .poll(async () => (await stepPositions(page))[createId].x, {
          message: 'the first step should sit clear of the trigger box',
        })
        .toBeGreaterThan(trigger.x)

      const at = await stepPositions(page)
      const chain = [createId, seedId, ordersId, forEachId, reviewId, summaryId]
      for (let index = 1; index < chain.length; index += 1) {
        expect(at[chain[index]].x, 'each step should sit right of the one feeding it').toBeGreaterThan(
          at[chain[index - 1]].x,
        )
        expect(at[chain[index]].y, 'one chain, one lane').toBe(at[chain[0]].y)
      }
    })

    // ---- (6) For Each works out which list it is iterating -----------------------

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

    // ---- (5) the Input tab: another step, or another process ----------------------

    await test.step('(5) the input source offers steps and processes', async () => {
      await inspector.getByRole('tab', { name: 'Input' }).click()
      await expect(source).toBeVisible()

      // the step feeding it is what the panel shows, because that is the arrow
      await expect(source).toHaveValue(`step:${ordersId}`)
      await expect(source.getByRole('option', { name: 'Trigger data' })).toHaveCount(1)
      await expect(source.getByRole('option', { name: 'orders', exact: true })).toHaveCount(1)
      // a step downstream of this one is not offered: that arrow would be a cycle
      await expect(source.getByRole('option', { name: 'summary', exact: true })).toHaveCount(0)
      // and an existing process is
      await expect(source.getByRole('option', { name: CHILD })).toHaveCount(1)
      // but never this one — every item would start the process again
      await expect(source.getByRole('option', { name: PARENT })).toHaveCount(0)
    })

    await test.step('(5) choosing a source re-connects the arrow', async () => {
      await source.selectOption(TRIGGER)
      await expectNotConnected(page, ordersId, forEachId)
      await expectConnected(page, TRIGGER, forEachId)

      await source.selectOption(`step:${ordersId}`)
      await expectConnected(page, ordersId, forEachId)
      await expectNotConnected(page, TRIGGER, forEachId)
    })

    await test.step('(5) choosing a process runs it once per item', async () => {
      await source.selectOption({ label: CHILD })
      // the arrow still delivers the list; the sub-process is what each item goes to
      await expectConnected(page, ordersId, forEachId)

      await inspector.getByRole('tab', { name: 'Config' }).click()
      await expect(inspector.getByRole('combobox', { name: 'How to iterate' })).toHaveValue('process')
      const chosen = inspector.getByRole('combobox', { name: 'Published process to run for each one' })
      await expect(chosen.locator('option:checked')).toHaveText(CHILD)
    })

    // ---- (1) what came back, in the parent's own log ------------------------------

    await test.step('the summary step reports what came back', async () => {
      await select(page, summaryId)
      await inspector
        .getByRole('textbox', { name: 'Message' })
        .fill(
          'reviewed {{ steps.for_each_order.output.count }} orders; order 1 is now ' +
            '{{ steps.review.output.rows.0.status }} and order 2 is {{ steps.review.output.rows.1.status }}',
        )
    })

    // ---- run it -------------------------------------------------------------------

    await expectNoDisconnectedStep(page)
    await save(page)
    await expect(page.getByText(/This process cannot run yet/i)).toHaveCount(0)

    await test.step('the run finishes with nothing failed and nothing skipped', async () => {
      await page.getByRole('button', { name: /^Run draft$/ }).click()
      await expectRunPassed(page, 6)
      await expectNoDisconnectedStep(page)
    })

    await test.step('(1) For Each reports one sub-run per row', async () => {
      const { outputs } = await stepData(page, 'for each order')
      // the two orders the query returned, both of them run to the end
      await expect(outputs).toContainText(/count\s*2/)
      await expect(outputs).toContainText(/succeeded\s*2/)
      await expect(outputs).toContainText(/failed\s*0/)
    })

    await test.step('(8) the two branches wrote different rows, and the parent reads them back', async () => {
      const { outputs } = await stepData(page, 'review')
      // the rows themselves are three levels in, and the tree opens two
      await expandJson(outputs)
      // 900 was approved and 120 put on hold — the condition really branched, and
      // each sub-process really updated the order it was handed
      await expect(outputs).toContainText('approved')
      await expect(outputs).toContainText('on hold')
    })

    await test.step('(1)(8) each sub-run logged its order and skipped the branch it did not take', async () => {
      await page.goto('/app/runs')
      await page.getByLabel('Search runs').fill(CHILD)

      const rows = page.locator('table tbody tr')
      await expect(rows, 'one sub-run per order').toHaveCount(2)
      await expect(page.locator('table tbody .badge-succeeded')).toHaveCount(2)

      const skipped = []
      for (const index of [0, 1]) {
        await rows.nth(index).click()
        // the row is only marked once its detail is the one on screen
        await expect(rows.nth(index)).toHaveClass(/is-selected/)
        /* Four steps, three of them run: the Condition sends its input down one
           port, so the steps on the other are skipped by design. That is the one
           honest reason for a skip, which is why it is declared and counted
           rather than tolerated. */
        await expectRunPassed(page, 4, { skipped: 1 })
        skipped.push(await skippedStep(page))
      }
      expect(skipped.slice().sort(), 'the two orders should have taken different branches').toEqual([
        'approve',
        'reject',
      ])

      await rows.first().click()
      // the order this sub-run was handed, as the Log step saw it
      const { input } = await stepData(page, 'log row')
      await expect(input).toContainText(/customer\s*"(Acme Corp|Globex)"/)
      await expect(input).toContainText(/index\s*[01]/)
    })
  })
})
