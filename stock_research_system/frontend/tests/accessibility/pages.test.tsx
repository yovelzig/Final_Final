import { axe } from "jest-axe";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import LoginPage from "@/app/(auth)/login/page";
import RegisterPage from "@/app/(auth)/register/page";
import DashboardPage from "@/app/(protected)/dashboard/page";
import LearnPage from "@/app/(protected)/learn/page";
import PortfoliosPage from "@/app/(protected)/portfolios/page";
import PracticePage from "@/app/(protected)/practice/page";
import ScenariosCatalogPage from "@/app/(protected)/scenarios/page";
import SettingsPage from "@/app/(protected)/settings/page";
import TutorPage from "@/app/(protected)/tutor/page";
import { server } from "@/tests/mocks/server";
import { renderWithProviders, waitFor } from "@/tests/test-utils";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

/**
 * Every non-dynamic (parameter-less) route gets an axe pass here - the
 * `[id]`-suffixed detail pages need real fixture data and are instead
 * covered end-to-end by the Playwright journeys, which exercise the
 * same rendered markup against the real backend.
 */

async function expectNoViolations(container: Element) {
  const results = await axe(container, {
    rules: {
      // Recharts' SVGs render at 0x0 in jsdom (no real layout engine),
      // which axe's color-contrast heuristics can misfire on - the
      // scenario/reveal pages aren't in this route-level sweep anyway.
      "color-contrast": { enabled: false },
    },
  });
  expect(results).toHaveNoViolations();
}

describe("accessibility: static routes", () => {
  it("/login has no serious or critical violations", async () => {
    const { container } = renderWithProviders(<LoginPage />);
    await expectNoViolations(container);
  });

  it("/register has no serious or critical violations", async () => {
    const { container } = renderWithProviders(<RegisterPage />);
    await expectNoViolations(container);
  });

  it("/dashboard has no serious or critical violations", async () => {
    server.use(
      http.get("*/api/v1/learners/me/dashboard", () =>
        HttpResponse.json({
          active_path_id: null, active_misconceptions: [], completed_lessons: 0, current_lesson_id: null,
          current_streak_days: 0,
          learner: { learner_id: "l1", display_name: "Ada", daily_goal_minutes: 10, preferred_language: "en", financial_experience_level: "BEGINNER" },
          skill_mastery: [], total_lessons: 0, total_xp: 0,
        })
      ),
      http.get("*/api/v1/learners/me/mastery", () =>
        HttpResponse.json({ items: [], pagination: { limit: 50, offset: 0, returned: 0, total: 0 } })
      )
    );
    const { container, findByText } = renderWithProviders(<DashboardPage />);
    await findByText(/haven't started/i);
    await expectNoViolations(container);
  });

  it("/learn has no serious or critical violations", async () => {
    server.use(http.get("*/api/v1/learning-paths", () => HttpResponse.json([])));
    const { container, findByText } = renderWithProviders(<LearnPage />);
    await findByText("No learning paths are available yet");
    await expectNoViolations(container);
  });

  it("/practice (idle state) has no serious or critical violations", async () => {
    const { container } = renderWithProviders(<PracticePage />);
    await expectNoViolations(container);
  });

  it("/scenarios has no serious or critical violations", async () => {
    server.use(http.get("*/api/v1/scenarios", () => HttpResponse.json([])));
    const { container, findByText } = renderWithProviders(<ScenariosCatalogPage />);
    await findByText("No scenarios available yet");
    await expectNoViolations(container);
  });

  it("/portfolios has no serious or critical violations", async () => {
    server.use(http.get("*/api/v1/portfolios", () => HttpResponse.json([])));
    const { container, findByText } = renderWithProviders(<PortfoliosPage />);
    await findByText("No portfolios yet");
    await expectNoViolations(container);
  });

  it("/tutor has no serious or critical violations", async () => {
    server.use(http.get("*/api/v1/tutor/conversations", () => HttpResponse.json([])));
    const { container, findByText } = renderWithProviders(<TutorPage />);
    await findByText("No conversations yet");
    await expectNoViolations(container);
  });

  it("/settings has no serious or critical violations", async () => {
    const { container } = renderWithProviders(<SettingsPage />);
    await waitFor(() => expect(document.querySelector("form")).toBeInTheDocument());
    await expectNoViolations(container);
  });
});
