import { describe, expect, it } from "vitest";

import { FinQuestApiError, parseApiError } from "@/lib/api/error";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("parseApiError", () => {
  it("parses a well-formed error envelope, including the correlation id", async () => {
    const response = jsonResponse(422, {
      error: {
        code: "VALIDATION_ERROR",
        message: "The request was invalid.",
        details: [{ field: "email", message: "Enter a valid email address." }],
        correlation_id: "abc-123",
      },
    });

    const error = await parseApiError(response);

    expect(error).toBeInstanceOf(FinQuestApiError);
    expect(error.status).toBe(422);
    expect(error.code).toBe("VALIDATION_ERROR");
    expect(error.message).toBe("The request was invalid.");
    expect(error.details).toEqual([{ field: "email", message: "Enter a valid email address." }]);
    expect(error.correlationId).toBe("abc-123");
  });

  it("falls back to a generic error for a non-envelope JSON body", async () => {
    const response = jsonResponse(500, { unexpected: "shape" });

    const error = await parseApiError(response);

    expect(error.code).toBe("UNKNOWN_ERROR");
    expect(error.correlationId).toBeNull();
    expect(error.message).toContain("500");
  });

  it("falls back to a generic error for a non-JSON body", async () => {
    const response = new Response("<html>not json</html>", { status: 502 });

    const error = await parseApiError(response);

    expect(error.code).toBe("UNKNOWN_ERROR");
    expect(error.status).toBe(502);
  });
});

describe("FinQuestApiError status helpers", () => {
  it.each([
    ["isAuthenticationError", 401],
    ["isForbidden", 403],
    ["isNotFound", 404],
    ["isValidationError", 422],
    ["isRateLimited", 429],
  ] as const)("%s is true only for status %d", (property, status) => {
    const error = new FinQuestApiError({ status, code: "X", message: "m" });
    expect(error[property]).toBe(true);
  });

  it("never exposes a stack trace or raw body through its public fields", () => {
    const error = new FinQuestApiError({ status: 500, code: "INTERNAL_ERROR", message: "Something went wrong." });
    expect(Object.keys(error)).not.toContain("stack");
    expect(error.message).toBe("Something went wrong.");
  });
});
