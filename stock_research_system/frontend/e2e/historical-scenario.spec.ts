import { expect, test } from "./fixtures";

/** Journey 4: a historical market scenario - the single most
 * safety-critical flow in the app. Verifies future price/outcome
 * information is genuinely absent from the page before the learner
 * explicitly reveals it, and only appears afterward. */
test("a learner decides on a historical scenario before seeing the outcome, then reveals it", async ({
  page,
  learner: _learner,
}) => {
  await page.goto("/scenarios");
  await expect(page.getByRole("heading", { name: "Historical scenarios" })).toBeVisible();

  await page.getByRole("link", { name: /E2ETEST decision scenario/ }).first().click();
  await page.waitForURL("**/scenarios/*");

  // Nothing about the eventual outcome may appear before the learner decides.
  await expect(page.getByText(/POSITIVE|NEGATIVE|FLAT/)).toHaveCount(0);
  await expect(page.getByText(/decision quality, not market luck/i)).toHaveCount(0);
  await expect(page.getByText("Reveal what happened")).toHaveCount(0);

  await page.getByRole("button", { name: "Start this scenario" }).click();

  await expect(page.getByRole("group", { name: "Your decision" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("radio").first().check();
  await page.getByRole("button", { name: "Submit decision" }).click();

  // After submitting a decision (but before revealing), decision-quality
  // feedback may appear, but the outcome/future data still must not.
  await expect(page.getByRole("button", { name: "Reveal what happened" }).or(page.getByText("outcome isn't available"))).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByText(/POSITIVE|NEGATIVE|FLAT/)).toHaveCount(0);

  const revealButton = page.getByRole("button", { name: "Reveal what happened" });
  if (await revealButton.isVisible().catch(() => false)) {
    await revealButton.click();

    await expect(page.getByText(/decision quality, not market luck/i)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/POSITIVE|NEGATIVE|FLAT/)).toBeVisible();
  }
});
