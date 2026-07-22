import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api/client";
import { getAccessTokenSnapshot, setAccessToken } from "@/lib/auth/token-store";

/**
 * Covers the API client's 401 -> single-flight-refresh -> retry-once
 * contract (`lib/api/client.ts`): every concurrent 401 must await the
 * SAME refresh call, the original request is retried at most once,
 * and a failed refresh clears the in-memory session rather than
 * looping.
 */

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  setAccessToken(null);
});

afterEach(() => {
  vi.restoreAllMocks();
  setAccessToken(null);
});

describe("apiClient 401 handling", () => {
  it("refreshes once and retries the original request after a successful refresh", async () => {
    let targetCallCount = 0;
    let refreshCallCount = 0;

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/auth/refresh")) {
        refreshCallCount += 1;
        return jsonResponse(200, {
          authenticated: true,
          accessToken: "new-token",
          accessTokenExpiresAt: "2026-01-01T00:00:00Z",
        });
      }
      targetCallCount += 1;
      if (targetCallCount === 1) {
        return jsonResponse(401, { error: { code: "UNAUTHENTICATED", message: "Expired." } });
      }
      return jsonResponse(200, { ok: true });
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiClient.get<{ ok: boolean }>("/api/v1/learners/me");

    expect(result).toEqual({ ok: true });
    expect(refreshCallCount).toBe(1);
    expect(targetCallCount).toBe(2);
    expect(getAccessTokenSnapshot()?.accessToken).toBe("new-token");
  });

  it("single-flights concurrent 401s into exactly one refresh call", async () => {
    let refreshCallCount = 0;
    // Track per-path attempt counts so each of the two endpoints 401s exactly once,
    // then succeeds on retry - independent of call ordering between the two.
    const attempts = new Map<string, number>();

    const trackedFetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/auth/refresh")) {
        refreshCallCount += 1;
        // Simulate network latency so both callers are in-flight together.
        await new Promise((resolve) => setTimeout(resolve, 10));
        return jsonResponse(200, {
          authenticated: true,
          accessToken: "new-token",
          accessTokenExpiresAt: "2026-01-01T00:00:00Z",
        });
      }
      const count = (attempts.get(url) ?? 0) + 1;
      attempts.set(url, count);
      if (count === 1) {
        return jsonResponse(401, { error: { code: "UNAUTHENTICATED", message: "Expired." } });
      }
      return jsonResponse(200, { ok: true, url });
    });
    vi.stubGlobal("fetch", trackedFetch);

    const [resultA, resultB] = await Promise.all([
      apiClient.get<{ ok: boolean }>("/api/v1/a"),
      apiClient.get<{ ok: boolean }>("/api/v1/b"),
    ]);

    expect(resultA).toEqual(expect.objectContaining({ ok: true }));
    expect(resultB).toEqual(expect.objectContaining({ ok: true }));
    expect(refreshCallCount).toBe(1);
  });

  it("clears the session and does not loop when refresh itself fails", async () => {
    setAccessToken({ accessToken: "stale-token", accessTokenExpiresAt: "2020-01-01T00:00:00Z" });
    let targetCallCount = 0;
    let refreshCallCount = 0;

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/auth/refresh")) {
        refreshCallCount += 1;
        return jsonResponse(401, { authenticated: false });
      }
      targetCallCount += 1;
      return jsonResponse(401, { error: { code: "UNAUTHENTICATED", message: "Expired." } });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiClient.get("/api/v1/learners/me")).rejects.toMatchObject({ status: 401 });

    expect(refreshCallCount).toBe(1);
    // The original request is attempted exactly once - a failed refresh
    // must not trigger an infinite 401 -> refresh -> 401 loop.
    expect(targetCallCount).toBe(1);
    expect(getAccessTokenSnapshot()).toBeNull();
  });
});
