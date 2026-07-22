import { defineConfig, devices } from "@playwright/test";

/**
 * E2E tests run against the REAL Next.js app, the REAL FastAPI backend,
 * and the REAL PostgreSQL/TimescaleDB/pgvector database (see
 * `e2e/README.md`) - nothing here is mocked. `webServer` is left
 * undefined deliberately: the caller is responsible for starting the
 * full stack first (`npm run dev` + the backend + the database, or the
 * Docker Compose stack) so these tests never accidentally start a
 * throwaway server pointed at the wrong backend.
 */
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["html", { open: "never" }], ["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
