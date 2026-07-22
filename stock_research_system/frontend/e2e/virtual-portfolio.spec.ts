import { expect, test } from "./fixtures";

/** Journey 5: virtual portfolio - create a portfolio, preview and
 * execute a real trade against the backend, then explicitly replay the
 * exact same trade request with the exact same `Idempotency-Key` the
 * UI generated and confirm the backend returns the SAME transaction
 * (no duplicate), which the UI then also reflects. */
test("a learner can trade in a virtual portfolio, and idempotency-key replay never duplicates the trade", async ({
  page,
  learner: _learner,
}) => {
  await page.goto("/portfolios/new");
  await page.getByLabel("Portfolio name").fill("E2E Portfolio");
  await page.getByLabel("Starting cash (USD)").fill("10000");
  await page.getByRole("button", { name: "Create portfolio" }).click();
  // Matches a UUID specifically - `/portfolios/new` (where we already
  // are) also matches a naive `[^/]+$` pattern, which would resolve
  // immediately without ever waiting for the real post-creation redirect.
  await page.waitForURL(/\/portfolios\/[0-9a-f-]{36}$/);

  const portfolioId = new URL(page.url()).pathname.split("/").pop();
  expect(portfolioId).toBeTruthy();

  await page.getByRole("button", { name: "Trade" }).click();
  await page.waitForURL(/\/portfolios\/.+\/trade$/);

  await page.getByLabel("Ticker").fill("E2ETEST");
  await page.getByLabel("Quantity").fill("5");
  await page.getByRole("button", { name: "Preview trade" }).click();

  await expect(page.getByText(/BUY 5 E2ETEST/)).toBeVisible({ timeout: 15_000 });
  await page.getByLabel(/Why are you making this trade/).fill("Testing the E2E trade flow.");

  let capturedRequest: { url: string; headers: Record<string, string>; body: unknown } | null = null;
  await page.route("**/api/v1/portfolios/*/trades", async (route) => {
    if (route.request().method() === "POST" && capturedRequest === null) {
      capturedRequest = {
        url: route.request().url(),
        headers: await route.request().allHeaders(),
        body: route.request().postDataJSON(),
      };
    }
    await route.continue();
  });

  await page.getByRole("button", { name: "Confirm trade" }).click();
  await page.waitForURL(/\/portfolios\/[^/]+$/);
  await expect(page.getByText(/BUY/).first()).toBeVisible({ timeout: 15_000 });

  expect(capturedRequest).not.toBeNull();
  const first = capturedRequest!;
  const idempotencyKey = first.headers["idempotency-key"];
  const authorization = first.headers.authorization;
  expect(idempotencyKey).toBeTruthy();
  expect(authorization).toBeTruthy();
  if (!idempotencyKey || !authorization) throw new Error("unreachable: asserted above");

  // Replay the EXACT same request (same Idempotency-Key, same body) directly
  // against the real backend - this must return the SAME transaction, not
  // execute a second trade.
  const initialTransactionsResponse = await page.request.get(
    `${new URL(first.url).origin}/api/v1/portfolios/${portfolioId}/transactions`,
    { headers: { Authorization: authorization } }
  );
  const initialTransactions = (await initialTransactionsResponse.json()) as unknown[];

  const replayResponse = await page.request.post(first.url, {
    headers: { Authorization: authorization, "Idempotency-Key": idempotencyKey, "Content-Type": "application/json" },
    data: first.body as Record<string, unknown>,
  });
  expect(replayResponse.status()).toBeLessThan(300);
  const replayBody = (await replayResponse.json()) as { transaction: { transaction_id: string } };

  const finalTransactionsResponse = await page.request.get(
    `${new URL(first.url).origin}/api/v1/portfolios/${portfolioId}/transactions`,
    { headers: { Authorization: authorization } }
  );
  const finalTransactions = (await finalTransactionsResponse.json()) as { transaction_id: string }[];

  expect(finalTransactions).toHaveLength(initialTransactions.length);
  expect(finalTransactions.some((t) => t.transaction_id === replayBody.transaction.transaction_id)).toBe(true);
});
