import type { ReactElement, ReactNode } from "react";
import { vi } from "vitest";

import type { Locale } from "@/lib/i18n/config";
import { AuthContext, type AuthContextValue } from "@/providers/AuthProvider";
import { LocaleProvider } from "@/providers/LocaleProvider";
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

export function renderWithAuthContext(
  ui: ReactElement,
  overrides?: Partial<AuthContextValue>,
  options?: { locale?: Locale }
) {
  const value = buildAuthContextValue(overrides);
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <LocaleProvider initialLocale={options?.locale ?? "en"}>
        <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
      </LocaleProvider>
    );
  }
  return { authValue: value, ...render(ui, { wrapper: Wrapper }) };
}
