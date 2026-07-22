import { expect, test } from "./fixtures";

/** Journey 3: diagnostic assessment - every question and its scoring
 * come from the backend; the client only renders what it's given and
 * never computes a skill result itself. */
test("a learner can complete a diagnostic assessment", async ({ page, learner: _learner }) => {
  // A full diagnostic can have up to 10 items, each a real round trip
  // to the backend - longer than Playwright's default 30s test timeout.
  test.setTimeout(90_000);

  await page.goto("/diagnostic");
  await expect(page.getByRole("heading", { name: "Diagnostic" })).toBeVisible();

  await page.getByRole("button", { name: "Start diagnostic" }).click();

  const progressBar = page.getByRole("progressbar", { name: "Progress" });
  await expect(progressBar).toBeVisible({ timeout: 15_000 });
  const totalItems = Number(await progressBar.getAttribute("aria-valuemax"));
  expect(totalItems).toBeGreaterThan(0);

  for (let answered = 0; answered < totalItems; answered += 1) {
    // Wait for the CURRENT item's progress count before interacting -
    // guards against a stale reference to the previous (already-
    // submitted, still momentarily visible) item's disabled controls,
    // since two diagnostic items can render identical markup.
    await expect(progressBar).toHaveAttribute("aria-valuenow", String(answered));

    const submit = page.getByRole("button", { name: "Submit answer" });
    await expect(submit).toBeVisible({ timeout: 15_000 });

    // Ordering exercises auto-populate a default order and are already
    // answerable with no interaction - only pick an input for the other
    // types, which start incomplete.
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

    // Confirm the backend has actually recorded this answer before the
    // next loop iteration queries for "the" submit button again.
    await expect(progressBar).toHaveAttribute("aria-valuenow", String(answered + 1), { timeout: 15_000 });
  }

  await expect(page.getByRole("heading", { name: "Diagnostic complete" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/You completed \d+ of \d+ questions\./)).toBeVisible();
});
