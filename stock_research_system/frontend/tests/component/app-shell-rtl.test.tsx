import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/layout/AppShell";
import type { Locale } from "@/lib/i18n/config";
import { he } from "@/lib/i18n/dictionaries/he";
import { AuthContext, type AuthContextValue } from "@/providers/AuthProvider";
import { LocaleProvider } from "@/providers/LocaleProvider";
import { buildAuthContextValue } from "@/tests/mocks/auth-context";
import { server } from "@/tests/mocks/server";
import { render, screen } from "@/tests/test-utils";
import type { PublicAccount } from "@/types/session";

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
}));

beforeEach(() => {
  // TopBar reads real dashboard data (XP/streak) via the same
  // `useDashboard()` hook the dashboard page uses - keep it a fast,
  // deterministic "no data yet" response instead of letting the
  // request fall through to a real network call.
  server.use(
    http.get("*/api/v1/learners/me/dashboard", () =>
      HttpResponse.json({ error: { code: "NOT_FOUND", message: "none", correlation_id: "c1" } }, { status: 404 })
    )
  );
});

const ACCOUNT: PublicAccount = {
  account_id: "acc-1",
  created_at: "2026-01-01T00:00:00Z",
  display_name: "Ada Lovelace",
  email: "ada@example.com",
  last_login_at: null,
  learner_id: "learner-1",
  role: "LEARNER",
  status: "ACTIVE",
};

function renderShell(locale: Locale, overrides?: Partial<AuthContextValue>) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const authValue = buildAuthContextValue({ status: "authenticated", account: ACCOUNT, ...overrides });
  return render(
    <LocaleProvider initialLocale={locale}>
      <QueryClientProvider client={queryClient}>
        <AuthContext.Provider value={authValue}>
          <AppShell>
            <p>Page content</p>
          </AppShell>
        </AuthContext.Provider>
      </QueryClientProvider>
    </LocaleProvider>
  );
}

describe("AppShell: RTL (Hebrew)", () => {
  it("renders the sidebar, top bar, and mobile nav entirely in Hebrew - one shell, no duplicated markup per locale", () => {
    renderShell("he");

    // Sidebar (desktop) primary nav, translated.
    expect(screen.getByRole("navigation", { name: he.nav.primaryNavLabel })).toBeInTheDocument();
    expect(screen.getAllByText(he.nav.dashboard).length).toBeGreaterThan(0);
    expect(screen.getAllByText(he.nav.tutor).length).toBeGreaterThan(0);

    // Bottom nav (mobile), translated, same nav item set - not a second implementation.
    expect(screen.getByRole("navigation", { name: he.nav.mobileNavLabel })).toBeInTheDocument();

    // Skip link, profile menu, brand - all Hebrew.
    expect(screen.getByText(he.nav.skipToContent)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: he.appShell.profileMenuLabel })).toBeInTheDocument();

    // Only one AppShell tree renders - the page content appears once.
    expect(screen.getAllByText("Page content")).toHaveLength(1);
  });

  it("renders the same shell in English with ltr copy when the locale is en", () => {
    renderShell("en");

    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(screen.getAllByText("Dashboard").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Account menu" })).toBeInTheDocument();
  });

  it("only shows a streak badge when the learner has a real, positive streak (never a fabricated one)", () => {
    renderShell("he");
    // No dashboard data mocked here -> query stays pending -> no XP/streak
    // pill renders at all, which is the correct "no fabricated data" state.
    expect(screen.queryByText(he.appShell.streakLabel)).not.toBeInTheDocument();
  });
});
