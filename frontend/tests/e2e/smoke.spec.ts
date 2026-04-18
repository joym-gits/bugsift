import { expect, test } from "@playwright/test";

/**
 * Phase 10 smoke. Exercises the whole stack in the signed-out state —
 * the full install → configure → triage → approve flow requires a
 * registered GitHub App + an LLM key, which we don't assume in CI.
 *
 * When those are present, the same runner covers a richer flow; see
 * tests/e2e/README if you want to extend it.
 */

test("dashboard redirects signed-out visitor and renders the sign-in button", async ({ page }) => {
  // Root (/) returns a 307 redirect; Playwright follows and we land on /dashboard.
  await page.goto("/");
  await expect(page).toHaveURL(/\/dashboard\/?$/);
  await expect(page.getByRole("heading", { name: "bugsift" })).toBeVisible();
  await expect(page.getByRole("link", { name: /sign in with github/i })).toBeVisible();
});

test("signed-out dashboard shows the Phase 3 marketing panel and backend check", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByText(/phase/i)).toBeVisible();
  const backendCheck = page.getByRole("link", { name: /check backend/i });
  await expect(backendCheck).toBeVisible();
  await expect(backendCheck).toHaveAttribute("href", /\/api\/health$/);
});

test("signed-out settings page invites login", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("link", { name: /sign in with github/i })).toBeVisible();
});

test("signed-out history page invites login", async ({ page }) => {
  await page.goto("/history");
  await expect(page.getByRole("heading", { name: "History" })).toBeVisible();
  await expect(page.getByRole("link", { name: /sign in with github/i })).toBeVisible();
});

test("backend health endpoint responds", async ({ request }) => {
  const resp = await request.get("/api/health");
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  expect(body.status).toBe("ok");
  expect(body.version).toBeTruthy();
});

test("api/cards requires authentication", async ({ request }) => {
  const resp = await request.get("/api/cards");
  expect(resp.status()).toBe(401);
});
