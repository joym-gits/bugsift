import { expect, test } from "@playwright/test";

/**
 * Smoke tests against the bundled nginx on :8080. Signed-out only — the
 * full install → configure → triage flow requires a registered GitHub App
 * and an LLM key, which CI doesn't assume.
 */

test("root redirects to dashboard and shows the first-run hero", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/dashboard\/?$/);
  await expect(
    page.getByRole("heading", { name: /sift signal from noise/i }),
  ).toBeVisible();
  // No App is configured in CI, so the primary CTA routes to /onboarding
  // rather than straight to OAuth.
  const getStarted = page.getByRole("link", { name: /get started/i });
  await expect(getStarted).toBeVisible();
  await expect(getStarted).toHaveAttribute("href", "/onboarding");
});

test("signed-out dashboard describes the feature surface", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByText(/classify/i).first()).toBeVisible();
  await expect(page.getByText(/dedup \+ retrieve/i)).toBeVisible();
  await expect(page.getByText(/reproduce \+ draft/i)).toBeVisible();
});

test("signed-out settings shows sign-in empty state", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByText(/sign in to manage settings/i)).toBeVisible();
});

test("signed-out history shows sign-in empty state", async ({ page }) => {
  await page.goto("/history");
  await expect(page.getByText(/sign in to see history/i)).toBeVisible();
});

test("onboarding page renders anonymously", async ({ page }) => {
  // Critical: the page must not require auth before ever loading. The
  // exact inner step depends on whether an App is already configured
  // in the live DB, so we only assert the outer page header is present.
  await page.goto("/onboarding");
  await expect(page.getByRole("heading", { name: /get set up/i })).toBeVisible();
});

test("backend health endpoint responds", async ({ request }) => {
  const resp = await request.get("/api/health");
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  expect(body.status).toBe("ok");
});

test("api/cards requires authentication", async ({ request }) => {
  const resp = await request.get("/api/cards");
  expect(resp.status()).toBe(401);
});

test("api/github/app/manifest/status is public and returns the configured flag", async ({ request }) => {
  // The landing page reads this before login to decide between
  // "Sign in" and "Get started" CTAs. Either boolean value is fine
  // here — the point is the endpoint must not require auth.
  const resp = await request.get("/api/github/app/manifest/status");
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  expect(typeof body.configured).toBe("boolean");
});
