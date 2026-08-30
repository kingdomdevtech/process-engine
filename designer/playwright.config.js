import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  /* One minute per test, deliberately tight. Everything these tests do — build
     a process, publish it, queue a run, read the timeline — happens in seconds
     when the stack is healthy, so a test that needs longer is reporting a
     problem (an engine that is not claiming, a step that is retrying, a wait
     that is really a hang) and should fail rather than sit there. */
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  // Demo Processes share the dashboard folder, MySQL fixture table, and queue.
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    headless: false,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --strictPort',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: true,
    timeout: 120_000,
  },
})
