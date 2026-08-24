/**
 * The MySQL order-review demo: build it, publish it, run it, read the answer.
 *
 * Everything in `tests/demo/` builds a **demo process** — a real, published
 * process left behind in the `demo` folder for someone to open and look at. So
 * this spec is a fixture as much as a test: it deletes the process and builds it
 * again from scratch every run, which is why the name is fixed rather than
 * stamped, and why the delete has to go through the folder guard (a process in
 * `demo` cannot be deleted until it is moved out — see `removeDemoProcess`).
 *
 * What it builds — one process, eight steps:
 *
 *   trigger (schedule) ─▶ create table ─▶ seed orders ─▶ orders
 *                                                          ├─▶ count orders
 *                                                          └─▶ for each order
 *                                                                 └─▶ check amount
 *                                                                      ├─true──▶ approve
 *                                                                      └─false─▶ reject
 *
 * **Why one process and not two.** The engine has no loop edges, so `for_each`
 * is the only repetition there is, and it repeats in one of two ways: running a
 * published sub-process once per item, or — as here — handing the whole
 * collection to the next step in this graph. Taking the second is what keeps
 * this to a single process, and the honest consequence is that the Condition
 * after it runs **once**, over the batch rather than per row: it reads the first
 * order out of the collection and the branch it picks updates *that* order, by
 * id, with a bound parameter. A Condition that runs once for every row is the
 * sub-process form, and nothing in a single process can stand in for it.
 *
 * Everything happens the way a person would do it: sign in on `/login`, click
 * steps out of the palette, fill the generated forms, wire the graph from the
 * Input tab, tidy the canvas, save, publish, press Run draft, and read the run
 * timeline. No `/api/...` call is made from inside the page — see the "Browser
 * tests must go through the designer UI" section of CLAUDE.md. In particular the
 * demo creates and seeds its own table *as steps*, because a spec may not reach
 * past the UI to set one up.
 *
 * It covers:
 *
 *  1. a schedule configured in the trigger box and nowhere else — not in the
 *     palette, not on a step;
 *  2. the first step connecting itself to the trigger box;
 *  3. every step after it connecting itself to the one before — on a real port,
 *     which for a Condition is its first branch and never a `main` it has not
 *     got;
 *  4. the Input tab offering an earlier step and each branch of a branching
 *     step, and re-pointing the arrow when one is chosen;
 *  5. two lanes off one query step, running at the same time;
 *  6. For Each handing every item to the next step in this process, with the
 *     list detected from the step feeding it and refreshed on demand;
 *  7. Tidy up steps laying the graph out clear of the trigger box;
 *  8. arrows that leave whichever side of a card faces the step they point at,
 *     so one canvas can be wired left-to-right and top-to-bottom at once;
 *  9. a process in the `demo` folder refusing to be deleted until it is moved;
 * 10. the run: the query's rows worked through, the count logged in the other
 *     lane, and one branch writing the order the rows named.
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
  openProcess,
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
   rather than slow. Building and running are separate tests so each gets its own
   budget — not because they are independent, which is what `serial` says. */
test.use({ viewport: { width: 1680, height: 1000 } })

const DB_URL = 'mysql+pymysql://process_engine:process_engine@127.0.0.1:3306/process_engine'

/* A fixed name, not a stamped one: a demo is meant to be found again, and every
   run of this spec deletes it and builds it from scratch. */
const DEMO = 'Demo MySQL order review'
/* The two processes this spec used to build, back when the fan-out went through
   a sub-process. Clearing them keeps the demo folder holding exactly what this
   spec leaves behind; both lines can go once every install has run this. */
const RETIRED = ['Demo MySQL orders fan-out', 'Demo review one order']

/* The demo's own table, created and seeded by its own first two steps. `REPLACE`
   rather than `INSERT` so a second run re-arms the demo instead of piling up
   rows: both orders go back to "new" and the branch decides them again. The
   first order is above the threshold, so which branch runs is not a matter of
   luck — the run either takes `approve` or the demo is broken. */
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
const APPROVE = "UPDATE demo_orders SET status = 'approved' WHERE id = :id"
const REJECT = "UPDATE demo_orders SET status = 'on hold' WHERE id = :id"

/* The order the branch is decided by, and the order both branches write — the
   same row of the collection For Each is working through, so the demo cannot be
   read as deciding one thing and updating another. */
const FIRST_AMOUNT = '{{ steps.for_each_order.output.items.0.amount }}'
const FIRST_ID = '{{ steps.for_each_order.output.items.0.id }}'

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

test.describe.serial('the MySQL order-review demo', () => {
  test('one process: a schedule, a query, two lanes and a branch that writes', async ({ page }) => {
    await signIn(page)

    await test.step('(9) last run’s demo processes are cleared out, guard and all', async () => {
      await removeDemoProcess(page, DEMO)
      for (const name of RETIRED) await removeDemoProcess(page, name)
    })

    await page.goto('/app/processes/new')
    await page.getByLabel('Folder').fill(DEMO_FOLDER)
    await page.getByLabel('Process name').fill(DEMO)

    const inspector = page.locator('[data-tour="inspector"]')
    const palette = page.locator('[data-tour="step-palette"]')
    const source = inspector.getByRole('combobox', { name: 'Input source' })

    await test.step('(1) the schedule is set in the trigger box, and nowhere else', async () => {
      await select(page, TRIGGER)
      await inspector.getByRole('button', { name: /^Schedule$/ }).click()
      await inspector.getByRole('button', { name: 'Every 15 min' }).click()
      await expect(inspector.getByLabel('Cron expression')).toHaveValue('*/15 * * * *')

      // and nowhere else: no trigger step to drop on the canvas
      for (const term of ['schedule', 'cron']) {
        await palette.getByLabel('Search steps').fill(term)
        await expect(palette.getByText(`No step matches “${term}”.`)).toBeVisible()
      }
      await palette.getByRole('button', { name: 'Clear search' }).click()
    })

    // ---- the demo makes its own data -------------------------------------------

    const createId = await addStep(page, 'mysql_execute')
    await test.step('(2) the first step wires itself to the trigger box', async () => {
      await expectConnected(page, TRIGGER, createId)
    })
    await page.locator('#pe-step-name').fill('create table')
    await configureMySQL(inspector, { field: 'Statement', sql: CREATE_TABLE })

    await test.step('(1) a step has no trigger configuration of its own', async () => {
      await expect(inspector.getByLabel('Cron expression')).toHaveCount(0)
      await expect(inspector.getByRole('button', { name: /^Schedule$/ })).toHaveCount(0)
    })

    const seedId = await addStep(page, 'mysql_execute')
    await expectConnected(page, createId, seedId)
    await page.locator('#pe-step-name').fill('seed orders')
    await configureMySQL(inspector, { field: 'Statement', sql: SEED_ORDERS })

    const ordersId = await addStep(page, 'mysql_query')
    await test.step('(3) and every step after joins the one before it', async () => {
      await expectConnected(page, seedId, ordersId)
    })
    await page.locator('#pe-step-name').fill('orders')
    // "Query" and not { exact: true }: a required field's label carries its *
    await configureMySQL(inspector, { field: 'Query', sql: READ_ORDERS })

    // ---- lane one: how many orders came back ------------------------------------

    const countId = await addStep(page, 'log')
    await expectConnected(page, ordersId, countId)
    await page.locator('#pe-step-name').fill('count orders')
    await inspector
      .getByRole('textbox', { name: 'Message' })
      .fill('{{ steps.orders.output.count }} orders to review')

    // ---- lane two: work through the rows, in parallel ---------------------------

    const forEachId = await addStep(page, 'for_each')
    await page.locator('#pe-step-name').fill('for each order')

    await test.step('(4)(5) pointing it back at the query makes it a second lane', async () => {
      await expectConnected(page, countId, forEachId)
      await inspector.getByRole('tab', { name: 'Input' }).click()
      await expect(source).toHaveValue(`step:${countId}`)
      await expect(source.getByRole('option', { name: 'orders', exact: true })).toHaveCount(1)
      await source.selectOption(`step:${ordersId}`)
      await expectNotConnected(page, countId, forEachId)
      await expectConnected(page, ordersId, forEachId)
      await inspector.getByRole('tab', { name: 'Config' }).click()
    })

    await test.step('(6) For Each hands every item to the next step in this process', async () => {
      /* The mode that keeps this to one process. The other one runs a published
         sub-process per item, which is the only way a Condition can be reached
         once per row — see the note at the top of this file. */
      await expect(inspector.getByRole('combobox', { name: 'How to iterate' })).toHaveValue('next_step')
      // so the sub-process picker belongs to the other mode and is not on the form
      await expect(
        inspector.getByRole('combobox', { name: 'Published process to run for each one' }),
      ).toHaveCount(0)
    })

    // ---- the branch ---------------------------------------------------------------

    const checkId = await addStep(page, 'condition')
    await expectConnected(page, forEachId, checkId)
    await page.locator('#pe-step-name').fill('check amount')

    const amount = inspector.getByRole('textbox', { name: 'Value to check' })
    const threshold = inspector.getByRole('textbox', { name: 'Compared with' })
    await amount.fill(FIRST_AMOUNT)
    await amount.blur() // an untyped field commits on blur, so a number stays one
    await inspector.getByRole('combobox', { name: 'Test' }).selectOption('greater_than')
    await threshold.fill('500')
    await threshold.blur()

    const approveId = await addStep(page, 'mysql_execute')
    await page.locator('#pe-step-name').fill('approve')
    await test.step('(3) “and then” off a Condition is its first branch, not a main port', async () => {
      await expectConnected(page, checkId, approveId)
      await inspector.getByRole('tab', { name: 'Input' }).click()
      await expect(source, 'the arrow should come off the true branch').toHaveValue(`step:${checkId}:true`)
      await inspector.getByRole('tab', { name: 'Config' }).click()
    })
    await configureMySQL(inspector, {
      field: 'Statement',
      sql: APPROVE,
      param: { name: 'id', value: FIRST_ID },
    })

    const rejectId = await addStep(page, 'mysql_execute')
    await page.locator('#pe-step-name').fill('reject')
    await test.step('(4) the other branch is a source the Input tab can name', async () => {
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
      param: { name: 'id', value: FIRST_ID },
    })

    await test.step('(5) both lanes come off the query and neither waits for the other', async () => {
      await expectConnected(page, ordersId, countId)
      await expectConnected(page, ordersId, forEachId)
      await expectNotConnected(page, countId, forEachId)
      await expectNotConnected(page, forEachId, countId)
    })

    await expectNoDisconnectedStep(page)
    await save(page)

    // ---- (7)(8) the canvas ---------------------------------------------------------

    await test.step('(7) tidy up lays the chain and both lanes out clear of the trigger box', async () => {
      // the shortcut is ignored while a form field has focus, so click away first
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
      const chain = [createId, seedId, ordersId]
      for (let index = 1; index < chain.length; index += 1) {
        expect(at[chain[index]].x, 'each step should sit right of the one feeding it').toBeGreaterThan(
          at[chain[index - 1]].x,
        )
        expect(at[chain[index]].y, 'one chain, one lane').toBe(at[chain[0]].y)
      }
      expect(at[countId].x, 'the two lanes should start alongside each other').toBe(at[forEachId].x)
      expect(at[countId].y).not.toBe(at[forEachId].y)
      expect(at[checkId].x, 'the branch follows the step feeding it').toBeGreaterThan(at[forEachId].x)
      expect(at[approveId].x, 'a branch sits right of the step feeding it').toBeGreaterThan(at[checkId].x)
      expect(at[rejectId].x).toBeGreaterThan(at[checkId].x)
    })

    await test.step('(8) an arrow leaves whichever side of the card faces where it is going', async () => {
      /* `reject` is laid out level with the check and to its right, so that
         arrow leaves the right-hand border — as does the trigger's, for the same
         reason. Both are exact: the two cards share a centre line, so this says
         what the geometry chose and not what the card sizes happened to be. */
      await expectArrowLeaves(page, checkId, rejectId, 'right')
      await expectArrowLeaves(page, TRIGGER, createId, 'right')

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
      await expectArrowLeaves(page, TRIGGER, createId, 'bottom')

      // left to right is how the demo is left, so put it back
      await page.getByRole('button', { name: 'Canvas layout' }).click()
      await page.getByRole('menuitem', { name: 'Left to right' }).click()
      await expectArrowLeaves(page, checkId, rejectId, 'right')
    })

    // ---- (6) For Each works out which list it is working through ------------------

    await test.step('(6) For Each detects the list from the step feeding it', async () => {
      await select(page, forEachId)
      const items = inspector.getByRole('textbox', { name: 'List to work through' })
      /* Detection reads the *saved* graph, which is why it is asserted after the
         save above and not when the step was dropped: it fills itself in the
         first time the form opens on a process that has an id — the detection is
         the documented default, not something to press a button for. */
      await expect(items).toHaveValue(/^\{\{ steps\.orders\.output(\.rows)? \}\}$/)

      // and refreshes on demand once the connection above it changes
      await items.fill('')
      await items.blur()
      await expect(items).toHaveValue('')
      await inspector.getByRole('button', { name: 'Detect from the previous step' }).click()
      await expect(items).toHaveValue(/^\{\{ steps\.orders\.output(\.rows)? \}\}$/)
    })

    await expectNoDisconnectedStep(page)
    await save(page)
    await expect(page.getByText(/This process cannot run yet/i)).toHaveCount(0)
    // the schedule fires the published version, so a demo left as a draft never runs
    await publish(page)
  })

  test('the run logs the row count, works through the rows, and takes one branch', async ({ page }) => {
    await signIn(page)
    await openProcess(page, DEMO)

    await test.step('(10) the run finishes with nothing failed and one branch skipped', async () => {
      await expectNoDisconnectedStep(page)
      await page.getByRole('button', { name: /^Run draft$/ }).click()
      /* Eight steps, seven of them run: the Condition sends its input down one
         port, so the step on the other is skipped by design. That is the one
         honest reason for a skip, which is why it is declared and counted rather
         than tolerated — and named, since which branch was taken is the point. */
      await expectRunPassed(page, 8, { skipped: 1 })
      await expectNoDisconnectedStep(page)
      expect(await skippedStep(page), 'the branch not taken should be the only skip').toBe('reject')
    })

    await test.step('(5)(10) the other lane was handed the row count', async () => {
      const { input } = await stepData(page, 'count orders')
      // the two orders the query returned — the message logs this same count
      await expect(input).toContainText(/count\s*2/)
    })

    await test.step('(6)(10) For Each worked through both rows', async () => {
      const { outputs } = await stepData(page, 'for each order')
      await expect(outputs).toContainText(/count\s*2/)
    })

    await test.step('(10) the branch updated the order its own row named', async () => {
      const { input, outputs } = await stepData(page, 'approve')
      // one row matched, in a transaction that committed: the UPDATE really landed
      await expect(outputs).toContainText(/rowcount\s*1/)
      /* And it was handed the collection For Each was working through, which is
         where its bound `:id` came from. The rows are three levels in and the
         tree opens two. */
      await expandJson(input)
      await expect(input).toContainText('Acme Corp')
    })
  })
})
