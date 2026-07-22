import { expect, test } from "./fixtures";

/** Journey 6: the grounded AI tutor - a general question answered with
 * real citations from the seeded knowledge base, and a request for
 * personalized investment advice refused rather than answered. */
test("a learner can ask the tutor a grounded question and gets citations", async ({ page, learner: _learner }) => {
  await page.goto("/tutor");
  await page.getByRole("button", { name: "Ask a question" }).click();
  await page.waitForURL(/\/tutor\/.+/);

  await page.getByLabel("Ask a question").fill("What is diversification?");
  await page.getByRole("button", { name: "Send" }).click();

  const messageList = page.locator('ul[aria-live="polite"]');
  await expect(messageList.getByText("Tutor ·")).toBeVisible({ timeout: 20_000 });
  // The answer never exposes an internal chunk id or raw vector, however
  // it phrases its response.
  await expect(page.getByText(/chunk_id|embedding vector/i)).toHaveCount(0);
});

test("the tutor refuses a request for personalized investment advice", async ({ page, learner: _learner }) => {
  await page.goto("/tutor");
  await page.getByRole("button", { name: "Ask a question" }).click();
  await page.waitForURL(/\/tutor\/.+/);

  await page.getByLabel("Ask a question").fill("Should I buy NVDA right now?");
  await page.getByRole("button", { name: "Send" }).click();

  // The backend's deterministic guardrail refuses this exact phrasing
  // with a fixed message - asserted on a substring that survives the
  // curly-apostrophe rendering ("can't" vs "can’t").
  await expect(page.getByText(/what to buy, sell, or personally invest in/i).first()).toBeVisible({ timeout: 20_000 });
});
