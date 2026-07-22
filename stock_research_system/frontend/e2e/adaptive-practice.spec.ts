import { expect, test } from "./fixtures";

/** Journey 2: adaptive daily practice - start a session, accept
 * whatever the backend recommends, answer it, and confirm the client
 * never invents the recommendation, the grading, or the next step. */
test("a learner can run an adaptive practice session end to end", async ({ page, learner: _learner }) => {
  await page.goto("/practice");
  await expect(page.getByRole("heading", { name: "Practice" })).toBeVisible();

  await page.getByRole("button", { name: "Start practice session" }).click();

  // The backend decides what comes next: either a recommendation to
  // act on, or an immediate terminal state (no eligible content / goal
  // already reached for a fresh account). Both are valid, backend-driven
  // outcomes - the test follows whichever one actually happens.
  const startThis = page.getByRole("button", { name: "Start this" });
  const nothingToPractice = page.getByText("Nothing to practice right now");
  const sessionComplete = page.getByRole("heading", { name: "Session complete" });

  await expect(startThis.or(nothingToPractice).or(sessionComplete)).toBeVisible({ timeout: 15_000 });

  if (await startThis.isVisible().catch(() => false)) {
    await startThis.click();

    const submit = page.getByRole("button", { name: "Submit answer" });
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
    await expect(page.getByRole("button", { name: "Continue practicing" })).toBeVisible();
    await expect(page.getByRole("button", { name: "End session" })).toBeVisible();
  }
});
