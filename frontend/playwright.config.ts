import { defineConfig, devices } from "@playwright/test";

/**
 * Smoke test runner. Points at the real nginx on :8080 so the test exercises
 * the whole stack — no dev-server reliance. Run with `docker compose up -d`
 * first, then `npm run test:e2e`.
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:8080";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  retries: 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
