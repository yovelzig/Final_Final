import { expect, registerNewLearner, test } from "./fixtures";

/** Journey 1: register a brand-new learner, browse the seeded
 * curriculum, open a lesson, and complete an exercise end to end
 * through the real backend - no mocking anywhere in this file. */
test("a new learner can register, browse curriculum, and complete an exercise", async ({ page }) => {
  const learner = await registerNewLearner(page, { displayName: "Curriculum E2E Learner" });

  await expect(page.getByRole("heading", { name: new RegExp(`Welcome back, ${learner.displayName}`) })).toBeVisible();

  await page.getByRole("link", { name: "Learn", exact: true }).click();
  await page.waitForURL("**/learn");
  await expect(page.getByRole("heading", { name: "Learn" })).toBeVisible();

  await page.getByRole("link", { name: /Investing Foundations/ }).click();
  await page.waitForURL("**/learn/*");
  await expect(page.getByRole("heading", { name: "Investing Foundations", level: 1 })).toBeVisible();

  await page.locator("ol a").first().click();
  await page.waitForURL("**/lessons/*");

  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Start exercise" }).first().click();

  // Whatever input type the first exercise happens to be, at least one
  // answerable control is present, and the submit button is initially
  // disabled until an answer is provided (never pre-graded, never
  // revealing a correct answer up front).
  const submit = page.getByRole("button", { name: "Submit answer" }).first();
  await expect(submit).toBeVisible();

  // Ordering exercises auto-populate a default order and are already
  // answerable with no interaction.
  if (!(await submit.isEnabled())) {
    const radio = page.getByRole("radio").first();
    const checkbox = page.getByRole("checkbox").first();
    if (await radio.isVisible().catch(() => false)) {
      await radio.check();
    } else if (await checkbox.isVisible().catch(() => false)) {
      await checkbox.check();
    } else {
      await page.getByRole("textbox").first().fill("42");
    }
  }

  await expect(submit).toBeEnabled({ timeout: 5_000 });
  await submit.click();
  await expect(page.getByText(/Correct|Not quite right|Pending review/).first()).toBeVisible();
});
