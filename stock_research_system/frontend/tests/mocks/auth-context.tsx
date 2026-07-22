import type { ReactElement, ReactNode } from "react";
import { vi } from "vitest";

import { AuthContext, type AuthContextValue } from "@/providers/AuthProvider";
import { render } from "@/tests/test-utils";

/** A fully-stubbed `AuthContextValue` for testing components that call
 * `useAuth()` in isolation, without going through `AuthProvider`'s real
 * network-backed bootstrap/login/refresh flow. */
export function buildAuthContextValue(overrides?: Partial<AuthContextValue>): AuthContextValue {
  return {
    status: "unauthenticated",
    account: null,
    learner: null,
    accessToken: null,
    login: vi.fn().mockResolvedValue(undefined),
    register: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn().mockResolvedValue(undefined),
    logoutAll: vi.fn().mockResolvedValue(0),
    refreshIdentity: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

export function renderWithAuthContext(ui: ReactElement, overrides?: Partial<AuthContextValue>) {
  const value = buildAuthContextValue(overrides);
  function Wrapper({ children }: { children: ReactNode }) {
    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
  }
  return { authValue: value, ...render(ui, { wrapper: Wrapper }) };
}
