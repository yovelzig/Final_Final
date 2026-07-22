import { test as base, expect, type Page } from "@playwright/test";

export interface LearnerCredentials {
  email: string;
  password: string;
  displayName: string;
}

/** A fresh, collision-free email for every call, so parallel/repeated
 * E2E runs never fight over the same account. */
export function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`;
}

/** Registers a brand-new learner through the REAL registration flow
 * (never seeded directly into the database) and waits for the
 * post-registration redirect to the dashboard. */
export async function registerNewLearner(page: Page, options?: { displayName?: string }): Promise<LearnerCredentials> {
  const credentials: LearnerCredentials = {
    email: uniqueEmail("e2e"),
    password: "E2ePassword123!",
    displayName: options?.displayName ?? "E2E Learner",
  };

  await page.goto("/register");
  await page.getByLabel("Display name").fill(credentials.displayName);
  await page.getByLabel("Email").fill(credentials.email);
  await page.getByLabel("Password", { exact: true }).fill(credentials.password);
  await page.getByLabel("Confirm password").fill(credentials.password);
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL("**/dashboard");

  return credentials;
}

export async function login(page: Page, credentials: Pick<LearnerCredentials, "email" | "password">): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(credentials.email);
  await page.getByLabel("Password", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.waitForURL("**/dashboard");
}

/** A Playwright `test` extended with a `learner` fixture: every test
 * that uses it starts already registered and logged in, as its own
 * independent account. */
export const test = base.extend<{ learner: LearnerCredentials }>({
  // Named `provideFixture` (not Playwright's conventional `use`) purely
  // to avoid eslint-plugin-react-hooks misidentifying it as React's
  // `use()` hook - it is still called exactly as Playwright expects.
  learner: async ({ page }, provideFixture) => {
    const credentials = await registerNewLearner(page);
    await provideFixture(credentials);
  },
});

export { expect };
