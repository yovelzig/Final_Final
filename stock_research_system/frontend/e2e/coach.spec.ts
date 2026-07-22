import { expect, test } from "./fixtures";

/** Journey: the personalized learning coach - a grounded concept
 * explanation, and the interrupt/approve flow for starting a practice
 * session. */
test("a learner can ask the coach a grounded question and gets an answer", async ({ page, learner: _learner }) => {
  await page.goto("/coach");
  await page.getByRole("button", { name: "New conversation" }).click();
  await page.waitForURL(/\/coach\/.+/);

  await page.getByLabel("Ask your coach").fill("What is diversification?");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText(/diversif/i).last()).toBeVisible({ timeout: 20_000 });
  // Never exposes internal state.
  await expect(page.getByText(/chunk_id|embedding vector/i)).toHaveCount(0);
});

test("starting a practice session requires explicit approval before anything happens", async ({ page, learner: _learner }) => {
  await page.goto("/coach");
  await page.getByRole("button", { name: "New conversation" }).click();
  await page.waitForURL(/\/coach\/.+/);

  await page.getByLabel("Ask your coach").fill("I'd like to start my daily practice session for financial skills.");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("Needs your approval")).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Approved")).toBeVisible({ timeout: 20_000 });
});
