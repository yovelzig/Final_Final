import type { Page } from "@playwright/test";

import { expect, registerNewLearner, test } from "./fixtures";

/** Returns the exercise card containing the given exact prompt - the
 * prompt paragraph is always a direct child of the card's root div, so
 * every action for that exercise stays scoped to its own card even
 * when multiple exercise cards are mounted on the page at once. */
function cardFor(page: Page, prompt: string) {
  return page.getByText(prompt, { exact: true }).locator("xpath=..");
}

const EXERCISE_1_PROMPT = "Which of the following is NOT one of the three basic functions of money?";
const EXERCISE_2_PROMPT =
  "True or false: Money is considered a good store of value only if it keeps its purchasing power reasonably stable over time.";
const EXERCISE_3_PROMPT = "Which of these are functions of money? Select all that apply.";

/** Journey 2: register a brand-new learner, answer every exercise in
 * the first seeded lesson correctly, and verify the lesson is marked
 * complete with a correct, non-self-linking "Continue learning" CTA -
 * no mocking anywhere in this file, against the real backend and the
 * deterministic curriculum seeded by `global-setup.ts`. */
test("a learner who answers every exercise correctly sees the lesson marked complete with a Continue learning CTA", async ({
  page,
}) => {
  const learner = await registerNewLearner(page, { displayName: "Lesson Completion E2E Learner" });
  await expect(page.getByRole("heading", { name: new RegExp(`Welcome back, ${learner.displayName}`) })).toBeVisible();

  await page.getByRole("link", { name: "Learn", exact: true }).click();
  await page.waitForURL("**/learn");
  await page.getByRole("link", { name: /Investing Foundations/ }).click();
  await page.waitForURL("**/learn/*");

  // The link's accessible name includes the trailing duration badge
  // ("What Money Is For 15 min"), so this intentionally matches the lesson
  // title as a substring of the full accessible name rather than requiring
  // an exact match against it.
  await page
    .getByRole("link", {
      name: "What Money Is For",
    })
    .click();

  await expect(page).toHaveURL(/\/lessons\/[^/]+$/);
  const lessonUrl = page.url();
  await expect(page.getByRole("heading", { name: "What Money Is For", level: 1 })).toBeVisible();

  // Exercise 1: single choice - the odd one out is the correct answer.
  const card1 = cardFor(page, EXERCISE_1_PROMPT);
  await card1.getByRole("button", { name: "Start exercise" }).click();
  await card1.getByRole("radio", { name: "A guarantee of investment profit" }).check();
  await card1.getByRole("button", { name: "Submit answer" }).click();
  await expect(card1.getByText("Correct", { exact: true })).toBeVisible();
  await expect(
    card1.getByText(/Money's three classic functions are medium of exchange, store of value, and unit of account/)
  ).toBeVisible();

  // Exercise 2: true/false.
  const card2 = cardFor(page, EXERCISE_2_PROMPT);
  await card2.getByRole("button", { name: "Start exercise" }).click();
  await card2.getByRole("radio", { name: "True", exact: true }).check();
  await card2.getByRole("button", { name: "Submit answer" }).click();
  await expect(card2.getByText("Correct", { exact: true })).toBeVisible();
  await expect(card2.getByText(/If money's value swings wildly or steadily erodes/)).toBeVisible();

  // Exercise 3: multiple choice - select the three real functions, not the guaranteed-income distractor.
  const card3 = cardFor(page, EXERCISE_3_PROMPT);
  await card3.getByRole("button", { name: "Start exercise" }).click();
  await card3.getByRole("checkbox", { name: "Medium of exchange" }).check();
  await card3.getByRole("checkbox", { name: "Store of value" }).check();
  await card3.getByRole("checkbox", { name: "Unit of account" }).check();
  await expect(card3.getByRole("checkbox", { name: "Source of guaranteed income" })).not.toBeChecked();
  await card3.getByRole("button", { name: "Submit answer" }).click();
  await expect(card3.getByText("Correct", { exact: true })).toBeVisible();
  await expect(
    card3.getByText(/Medium of exchange, store of value, and unit of account are money's three functions/)
  ).toBeVisible();

  // Lesson-completion banner and a non-self-linking Continue-learning CTA.
  await expect(page.getByText("Lesson complete.")).toBeVisible();
  const continueLink = page.getByRole("link", { name: "Continue learning" });
  await expect(continueLink).toBeVisible();
  const href = await continueLink.getAttribute("href");
  expect(href).not.toBeNull();

  if (href === null) {
    throw new Error("Continue learning link has no href.");
  }

  const sourceUrl = new URL(lessonUrl);
  const destinationUrl = new URL(href, lessonUrl);

  // "**/lessons/*" matches both the source and destination lesson URL, so
  // waiting on that glob alone never proves navigation actually reached the
  // destination - assert the exact destination URL and heading instead.
  expect(destinationUrl.pathname).not.toBe(sourceUrl.pathname);

  await continueLink.click();

  await expect(page).toHaveURL(destinationUrl.toString());

  await expect(
    page.getByRole("heading", {
      name: "What Inflation Does to Purchasing Power",
      level: 1,
    })
  ).toBeVisible();
});
