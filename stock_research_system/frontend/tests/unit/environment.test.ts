import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const VALID_ENV = {
  NEXT_PUBLIC_FINQUEST_API_BASE_URL: "http://localhost:8080",
  NEXT_PUBLIC_APP_NAME: "FinQuest",
  FINQUEST_WEB_ORIGIN: "http://localhost:3000",
};

beforeEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("environment validation", () => {
  it("loads successfully with a complete, valid environment", async () => {
    for (const [key, value] of Object.entries(VALID_ENV)) vi.stubEnv(key, value);

    const { browserEnv } = await import("@/lib/environment");
    expect(browserEnv.NEXT_PUBLIC_FINQUEST_API_BASE_URL).toBe("http://localhost:8080");
    expect(browserEnv.NEXT_PUBLIC_APP_NAME).toBe("FinQuest");
  });

  it("throws a clear error when the browser-safe base URL is missing", async () => {
    vi.stubEnv("NEXT_PUBLIC_FINQUEST_API_BASE_URL", "");

    await expect(import("@/lib/environment")).rejects.toThrow(/browser-safe environment variables/i);
  });

  it("throws a clear error when the browser-safe base URL is not a valid URL", async () => {
    vi.stubEnv("NEXT_PUBLIC_FINQUEST_API_BASE_URL", "not-a-url");

    await expect(import("@/lib/environment")).rejects.toThrow();
  });

  it("defaults NEXT_PUBLIC_APP_NAME when unset", async () => {
    vi.stubEnv("NEXT_PUBLIC_FINQUEST_API_BASE_URL", "http://localhost:8080");
    const original = process.env.NEXT_PUBLIC_APP_NAME;
    delete process.env.NEXT_PUBLIC_APP_NAME;

    try {
      const { browserEnv } = await import("@/lib/environment");
      expect(browserEnv.NEXT_PUBLIC_APP_NAME).toBe("FinQuest");
    } finally {
      if (original !== undefined) process.env.NEXT_PUBLIC_APP_NAME = original;
    }
  });

  it("throws a clear error when a server-only variable is missing", async () => {
    for (const [key, value] of Object.entries(VALID_ENV)) vi.stubEnv(key, value);
    vi.stubEnv("FINQUEST_WEB_ORIGIN", "");

    const { getServerEnv } = await import("@/lib/environment");
    expect(() => getServerEnv()).toThrow(/server-only environment variables/i);
  });
});
