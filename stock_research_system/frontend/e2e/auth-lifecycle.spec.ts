import type { Page } from "@playwright/test";

import { expect, type LearnerCredentials, registerNewLearner, test } from "./fixtures";

/**
 * Journey 7: the authentication lifecycle - protected-route gating,
 * the safe `returnTo` redirect (including open-redirect rejection),
 * already-authenticated auth-page bounce, and logout. Real 15-minute
 * access-token expiry isn't waited out here (impractical for an E2E
 * run); the refresh single-flight/retry-once/failed-refresh-clears-
 * session contract is covered directly against a real `fetch` in
 * `tests/unit/api-client-refresh.test.ts`.
 */

/** Fills and submits the login form already on screen - unlike the
 * `login` fixture helper, this never re-navigates to a plain `/login`,
 * so it preserves whatever `returnTo` query string is already present. */
async function submitLoginForm(page: Page, credentials: Pick<LearnerCredentials, "email" | "password">): Promise<void> {
  await page.getByLabel("Email").fill(credentials.email);
  await page.getByLabel("Password", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "Log in" }).click();
}

async function logOut(page: Page): Promise<void> {
  await page.goto("/settings");
  // Scoped to the page content, since the sidebar's secondary nav also
  // has its own "Log out" button.
  await page.locator("#main-content").getByRole("button", { name: "Log out", exact: true }).click();
  await page.waitForURL("**/login");
}

test("an unauthenticated visitor hitting a protected route is bounced to login with a returnTo", async ({ page }) => {
  await page.goto("/portfolios");
  await page.waitForURL(/\/login\?returnTo=%2Fportfolios/);
});

test("logging in from a protected-route bounce returns to the original page", async ({ page }) => {
  const credentials = await registerNewLearner(page);
  await logOut(page);

  await page.goto("/portfolios/new");
  await page.waitForURL(/\/login\?returnTo=%2Fportfolios%2Fnew/);

  await submitLoginForm(page, credentials);
  await page.waitForURL("**/portfolios/new");
});

test("an already-authenticated visitor hitting /login is redirected straight to the dashboard", async ({ page }) => {
  await registerNewLearner(page);
  await page.goto("/login");
  await page.waitForURL("**/dashboard");
});

test("logout clears the session so protected routes redirect to login again", async ({ page }) => {
  await registerNewLearner(page);
  await logOut(page);

  await page.goto("/dashboard");
  await page.waitForURL(/\/login\?returnTo=%2Fdashboard/);
});

test("an open-redirect returnTo value is rejected in favor of the dashboard", async ({ page }) => {
  const credentials = await registerNewLearner(page);
  await logOut(page);

  await page.goto("/login?returnTo=https://evil.example.com");
  await submitLoginForm(page, credentials);

  await page.waitForURL("**/dashboard");
  expect(new URL(page.url()).hostname).not.toBe("evil.example.com");
});
