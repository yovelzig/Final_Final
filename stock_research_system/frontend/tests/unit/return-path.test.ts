import { describe, expect, it } from "vitest";

import { sanitizeReturnPath } from "@/lib/auth/return-path";

describe("sanitizeReturnPath", () => {
  it("passes through a same-origin absolute path", () => {
    expect(sanitizeReturnPath("/portfolios/123")).toBe("/portfolios/123");
  });

  it("falls back to the dashboard for null", () => {
    expect(sanitizeReturnPath(null)).toBe("/dashboard");
  });

  it("falls back to the dashboard for an empty string", () => {
    expect(sanitizeReturnPath("")).toBe("/dashboard");
  });

  it("rejects a protocol-relative open-redirect target", () => {
    expect(sanitizeReturnPath("//evil.com/phish")).toBe("/dashboard");
  });

  it("rejects an absolute URL", () => {
    expect(sanitizeReturnPath("https://evil.com")).toBe("/dashboard");
  });

  it("rejects a path that embeds a scheme", () => {
    expect(sanitizeReturnPath("/redirect?next=https://evil.com")).toBe("/dashboard");
  });

  it("rejects a path that does not start with a slash", () => {
    expect(sanitizeReturnPath("dashboard")).toBe("/dashboard");
  });
});
