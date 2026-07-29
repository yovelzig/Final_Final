import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import DashboardPage from "@/app/(protected)/dashboard/page";
import { en } from "@/lib/i18n/dictionaries/en";
import { he } from "@/lib/i18n/dictionaries/he";
import { server } from "@/tests/mocks/server";
import { renderWithProviders, screen } from "@/tests/test-utils";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

/** The production defect: rows read "Skill 0dfce538" because the UI
 * printed `skill_id.slice(0, 8)`. Nothing a learner can read may look
 * like this again. */
const UUID_FRAGMENT_PATTERN = /Skill\s+[0-9a-f]{6,}/i;

const MASTERY_ITEMS = [
  {
    skill_id: "0dfce538-5f45-4d0e-8b6c-1f0e2a3b4c5d",
    skill_name: "Compound Interest",
    skill_code: "COMPOUND_INTEREST",
    mastery_score: 0.87,
    mastery_level: "PROFICIENT",
    correct_attempts: 7,
    total_attempts: 8,
    last_practiced_at: null,
    next_review_at: null,
  },
  {
    skill_id: "c6341461-0a1b-4c2d-9e3f-4a5b6c7d8e9f",
    skill_name: "Diversification",
    skill_code: "DIVERSIFICATION",
    mastery_score: 0.49,
    mastery_level: "DEVELOPING",
    correct_attempts: 2,
    total_attempts: 5,
    last_practiced_at: null,
    next_review_at: null,
  },
];

function mockDashboard({ mastery = MASTERY_ITEMS }: { mastery?: unknown[] } = {}) {
  server.use(
    http.get("*/api/v1/learners/me/dashboard", () =>
      HttpResponse.json({
        active_path_id: null,
        active_misconceptions: [],
        completed_lessons: 0,
        current_lesson_id: null,
        current_streak_days: 0,
        learner: {
          learner_id: "l1", display_name: "Ada", daily_goal_minutes: 10,
          preferred_language: "en", financial_experience_level: "BEGINNER",
        },
        skill_mastery: mastery,
        total_lessons: 0,
        total_xp: 0,
      })
    ),
    http.get("*/api/v1/learners/me/mastery", () =>
      HttpResponse.json({
        items: mastery,
        pagination: { limit: 50, offset: 0, returned: mastery.length, total: mastery.length },
      })
    ),
    http.get("*/api/v1/portfolios", () => HttpResponse.json([]))
  );
}

describe("Dashboard: Financial Skills Progress card", () => {
  it("titles the card 'Financial Skills Progress' and describes what it shows", async () => {
    mockDashboard();
    renderWithProviders(<DashboardPage />);

    expect(await screen.findByText("Financial Skills Progress")).toBeInTheDocument();
    expect(screen.getByText(en.dashboard.financialSkills.description)).toBeInTheDocument();
  });

  it("titles the card in Hebrew when the locale is Hebrew", async () => {
    mockDashboard();
    renderWithProviders(<DashboardPage />, { locale: "he" });

    expect(await screen.findByText("התקדמות במיומנויות פיננסיות")).toBeInTheDocument();
    expect(screen.getByText(he.dashboard.financialSkills.description)).toBeInTheDocument();
  });

  it("shows real curriculum skill names and never a 'Skill <id fragment>' label", async () => {
    mockDashboard();
    const { container } = renderWithProviders(<DashboardPage />);

    expect(await screen.findByText("Compound Interest")).toBeInTheDocument();
    expect(screen.getByText("Diversification")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(UUID_FRAGMENT_PATTERN);
    expect(container.textContent).not.toContain("0dfce538");
    expect(container.textContent).not.toContain("c6341461");
  });

  it("shows Hebrew skill names, still with no identifier fragments", async () => {
    mockDashboard();
    const { container } = renderWithProviders(<DashboardPage />, { locale: "he" });

    expect(await screen.findByText(he.dashboard.financialSkills.skillNames.COMPOUND_INTEREST)).toBeInTheDocument();
    expect(screen.getByText(he.dashboard.financialSkills.skillNames.DIVERSIFICATION)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(UUID_FRAGMENT_PATTERN);
    expect(container.textContent).not.toContain("0dfce538");
  });

  it("renders one legacy row with missing skill metadata without breaking the rest of the dashboard", async () => {
    mockDashboard({
      mastery: [
        MASTERY_ITEMS[0],
        {
          ...MASTERY_ITEMS[1],
          skill_name: null,
          skill_code: null,
        },
      ],
    });
    const { container } = renderWithProviders(<DashboardPage />);

    expect(await screen.findByText("Compound Interest")).toBeInTheDocument();
    expect(screen.getByText(en.dashboard.financialSkills.fallbackSkillName)).toBeInTheDocument();
    expect(screen.getByText(en.dashboard.portfolio.title)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(UUID_FRAGMENT_PATTERN);
  });

  it("keeps the localized empty state when no skill has been assessed yet", async () => {
    mockDashboard({ mastery: [] });
    renderWithProviders(<DashboardPage />);

    expect(await screen.findByText(en.dashboard.financialSkills.emptyTitle)).toBeInTheDocument();
    expect(screen.getByText(en.dashboard.financialSkills.emptyDescription)).toBeInTheDocument();
  });

  it("shows a loading status while the skills request is in flight, then the resolved card", async () => {
    let releaseMastery = () => {};
    const masteryGate = new Promise<void>((resolve) => {
      releaseMastery = resolve;
    });
    server.use(
      http.get("*/api/v1/learners/me/dashboard", () =>
        HttpResponse.json({
          active_path_id: null, active_misconceptions: [], completed_lessons: 0, current_lesson_id: null,
          current_streak_days: 0,
          learner: {
            learner_id: "l1", display_name: "Ada", daily_goal_minutes: 10,
            preferred_language: "en", financial_experience_level: "BEGINNER",
          },
          skill_mastery: [], total_lessons: 0, total_xp: 0,
        })
      ),
      http.get("*/api/v1/learners/me/mastery", async () => {
        await masteryGate;
        return HttpResponse.json({ items: [], pagination: { limit: 50, offset: 0, returned: 0, total: 0 } });
      }),
      http.get("*/api/v1/portfolios", () => HttpResponse.json([]))
    );
    renderWithProviders(<DashboardPage />);

    expect(await screen.findByText("Financial Skills Progress")).toBeInTheDocument();
    expect(screen.getAllByRole("status", { name: en.common.loading }).length).toBeGreaterThan(0);

    releaseMastery();
    expect(await screen.findByText(en.dashboard.financialSkills.emptyTitle)).toBeInTheDocument();
  });

  it("shows a retryable error state when the skills request fails", async () => {
    server.use(
      http.get("*/api/v1/learners/me/dashboard", () =>
        HttpResponse.json({
          active_path_id: null, active_misconceptions: [], completed_lessons: 0, current_lesson_id: null,
          current_streak_days: 0,
          learner: {
            learner_id: "l1", display_name: "Ada", daily_goal_minutes: 10,
            preferred_language: "en", financial_experience_level: "BEGINNER",
          },
          skill_mastery: [], total_lessons: 0, total_xp: 0,
        })
      ),
      http.get("*/api/v1/learners/me/mastery", () =>
        HttpResponse.json(
          { error: { code: "INTERNAL_ERROR", message: "Try again later.", correlation_id: "corr-7" } },
          { status: 500 }
        )
      ),
      http.get("*/api/v1/portfolios", () => HttpResponse.json([]))
    );
    renderWithProviders(<DashboardPage />);

    expect(await screen.findByText("Financial Skills Progress")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: en.common.retry })).toBeInTheDocument();
  });
});
