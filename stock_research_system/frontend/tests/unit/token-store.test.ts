import { afterEach, describe, expect, it, vi } from "vitest";

import { getAccessTokenSnapshot, setAccessToken, subscribeToAccessToken } from "@/lib/auth/token-store";

afterEach(() => {
  setAccessToken(null);
});

describe("token-store", () => {
  it("starts with no token", () => {
    expect(getAccessTokenSnapshot()).toBeNull();
  });

  it("returns the token that was set", () => {
    setAccessToken({ accessToken: "abc.def.ghi", accessTokenExpiresAt: "2026-01-01T00:00:00Z" });
    expect(getAccessTokenSnapshot()).toEqual({ accessToken: "abc.def.ghi", accessTokenExpiresAt: "2026-01-01T00:00:00Z" });
  });

  it("clears the token when set to null", () => {
    setAccessToken({ accessToken: "abc", accessTokenExpiresAt: "2026-01-01T00:00:00Z" });
    setAccessToken(null);
    expect(getAccessTokenSnapshot()).toBeNull();
  });

  it("notifies subscribers on every change", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToAccessToken(listener);

    setAccessToken({ accessToken: "abc", accessTokenExpiresAt: "2026-01-01T00:00:00Z" });
    expect(listener).toHaveBeenCalledTimes(1);

    setAccessToken(null);
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
    setAccessToken({ accessToken: "xyz", accessTokenExpiresAt: "2026-01-01T00:00:00Z" });
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("never persists the token to localStorage or sessionStorage", () => {
    setAccessToken({ accessToken: "super-secret-token", accessTokenExpiresAt: "2026-01-01T00:00:00Z" });

    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i);
      expect(key ? window.localStorage.getItem(key) : null).not.toContain("super-secret-token");
    }
    for (let i = 0; i < window.sessionStorage.length; i += 1) {
      const key = window.sessionStorage.key(i);
      expect(key ? window.sessionStorage.getItem(key) : null).not.toContain("super-secret-token");
    }
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });
});
