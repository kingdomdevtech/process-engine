/**
 * The Excel Power Query refresh demo: build it through the designer, publish
 * it, run it, and read the refresh result from the visible run timeline.
 *
 * This is a real demo Process left in the protected `demo` folder. It has a
 * fixed name and is rebuilt through the UI on every run, matching the MySQL
 * order-review demo beside it. The workbook is a checked-in artifact made by
 * `python examples/mysql_excel_demo.py --make-workbook`; before this spec can
 * run, open it once in Excel and grant the MySQL credential for the Windows
 * account running the engine. Power Query stores that credential per user.
 *
 * It builds:
 *
 *   trigger -> refresh workbook -> log result
 *
 * The workbook builder owns its source data. This Process focuses on the
 * refresh step, which selects its named `MySQL - demo_orders` connection. Its
 * result has a `refreshed_at` column sourced from MySQL's CURRENT_TIMESTAMP.
 */

import { expect, test } from '@playwright/test'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  DEMO_FOLDER,
  TRIGGER,
  addStep,
  expandJson,
  expectConnected,
  expectNoDisconnectedStep,
  expectRunPassed,
  openProcess,
  publish,
  removeDemoProcess,
  runDetail,
  save,
  signIn,
} from '../support/designer.js'

test.use({ viewport: { width: 1680, height: 1000 } })

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
const DEMO = 'Demo Excel Power Query refresh'
const RETIRED = ['Demo - Order review + Excel refresh', 'Demo - Triage one order']
const WORKBOOK = resolve(REPO, 'workdir', 'demo-orders.xlsx')

test.describe.serial('the Excel Power Query refresh demo', () => {
  test('builds and publishes a connected Process through the designer', async ({ page }) => {
    await signIn(page)
    await removeDemoProcess(page, DEMO)
    for (const name of RETIRED) await removeDemoProcess(page, name)

    await page.goto('/app/processes/new')
    await page.getByLabel('Folder').fill(DEMO_FOLDER)
    await page.getByLabel('Process name').fill(DEMO)

    const inspector = page.locator('[data-tour="inspector"]')

    const refreshId = await addStep(page, 'excel_refresh')
    await expectConnected(page, TRIGGER, refreshId)
    await page.locator('#pe-step-name').fill('refresh Power Query workbook')
    await inspector.getByRole('textbox', { name: 'Workbook' }).fill(WORKBOOK)
    const connections = inspector.getByRole('textbox', { name: 'Connections to refresh' })
    await connections.fill('MySQL - demo_orders')
    await connections.press('Enter')
    await expect(inspector.getByText('MySQL - demo_orders', { exact: true })).toBeVisible()
    await expect(inspector.getByLabel('Save the workbook afterwards')).toBeChecked()

    const logId = await addStep(page, 'log')
    await expectConnected(page, refreshId, logId)
    await page.locator('#pe-step-name').fill('log refreshed workbook')
    await inspector.getByRole('textbox', { name: 'Message' }).fill('Power Query refresh completed')

    await expectNoDisconnectedStep(page)
    await save(page)
    await expect(page.getByText(/This process cannot run yet/i)).toHaveCount(0)
    await publish(page)
  })

  test('refreshes the named Excel connection with no failed or disconnected step', async ({ page }) => {
    await signIn(page)
    await openProcess(page, DEMO)
    await expectNoDisconnectedStep(page)
    await page.getByRole('button', { name: /^Run draft$/ }).click()
    await expectRunPassed(page, 2, { timeout: 60_000 })
    await expectNoDisconnectedStep(page)

    const refresh = runDetail(page)
      .locator('li')
      .filter({ has: page.getByRole('button', { name: 'refresh Power Query workbook', exact: true }) })
    await expect(refresh).toHaveCount(1)
    const toggle = refresh.getByRole('button', { name: 'refresh Power Query workbook', exact: true })
    if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click()
    await expandJson(refresh)
    await expect(refresh).toContainText('MySQL - demo_orders')
    await expect(refresh).toContainText('demo-orders.xlsx')
  })
})