import { test, expect } from '@playwright/test'

test('a valid MySQL Query -> For Each process can be built and run successfully in the designer', async ({ page }) => {
  await page.goto('http://localhost:5173/login')
  await expect(page).toHaveURL(/\/login$/)

  await page.getByRole('button', { name: /Use an API token instead/i }).click()
  await page.locator('#pe-token').fill('dev-local-token')
  await page.getByRole('button', { name: /^Sign in$/i }).click()
  await expect(page).toHaveURL(/\/app$/)

  await page.goto('http://localhost:5173/app/processes/new')
  await expect(page).toHaveURL(/\/app\/processes\/new$/)

  const palette = page.locator('[data-tour="step-palette"]')
  await palette.getByRole('button', { name: /MySQL Query/i }).first().click()
  await palette.getByRole('button', { name: /For Each/i }).first().click()

  const mysqlCard = page.locator('[data-id^="mysql_query_"]').first()
  const forEachCard = page.locator('[data-id^="for_each_"]').first()

  await expect(page.locator('[data-id="__trigger__"]')).toBeVisible()
  await expect(mysqlCard).toBeVisible()
  await mysqlCard.click({ force: true })
  await expect(page.locator('#pe-step-name')).toBeVisible()
  await page.locator('#pe-step-name').fill('orders')
  await page.getByRole('tab', { name: 'JSON' }).click()
  await page.locator('textarea[aria-label="Step configuration as JSON"]').fill(
    JSON.stringify({
      connect_using: 'url',
      url: 'mysql+pymysql://process_engine:process_engine@127.0.0.1:3306/process_engine',
      query: 'SELECT 1 AS ok',
      params: {},
      max_rows: 10,
    }),
  )
  await page.getByRole('button', { name: 'Apply JSON' }).click()

  await expect(forEachCard).toBeVisible()
  await forEachCard.click({ force: true })
  await expect(page.locator('#pe-step-name')).toBeVisible()
  await page.locator('#pe-step-name').fill('for_each')
  await page.getByRole('tab', { name: 'JSON' }).click()
  await page.locator('textarea[aria-label="Step configuration as JSON"]').fill(
    JSON.stringify({ mode: 'next_step', items: '{{ steps.orders.output.rows }}' }),
  )
  await page.getByRole('button', { name: 'Apply JSON' }).click()

  await expect(page.locator('.react-flow__edge')).toHaveCount(2)
  await expect(page.locator('[data-id="__trigger__"]')).toBeVisible()
  await expect(page.locator('[data-id^="mysql_query_"]')).toBeVisible()
  await expect(page.locator('[data-id^="for_each_"]')).toBeVisible()
  await expect(page.getByText(/This process cannot run yet/i)).toHaveCount(0)

  await forEachCard.click({ force: true })
  await page.getByRole('tab', { name: 'Input' }).click()
  const inputSource = page.getByLabel('Input source')
  await expect(inputSource).toBeVisible()
  const selectedSource = await inputSource.inputValue()
  expect(selectedSource).not.toBe('__trigger__')
  expect(selectedSource).not.toBe('__effective__')
  await expect(page.getByRole('option', { name: 'Trigger data' })).toBeVisible()
  await expect(page.getByRole('option', { name: /orders/i })).toBeVisible()
  await expect(page.getByRole('option', { name: /Combined input/i })).toHaveCount(0)

  await page.getByRole('button', { name: /Save/i }).first().click()
  await expect(page.getByText('Saved')).toBeVisible({ timeout: 20_000 })

  await page.getByRole('button', { name: /Run draft/i }).first().click()
  const inspector = page.locator('[data-tour="inspector"]')
  await expect(inspector.getByText('Run detail')).toBeVisible({ timeout: 30_000 })
  await expect(inspector.getByText(/failed|skipped/i)).toHaveCount(0, { timeout: 30_000 })
  await expect(inspector.getByText(/^Succeeded$/)).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.react-flow__edge')).toHaveCount(2)
})
