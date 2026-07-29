import { describe, expect, it } from "vitest";

import { FinancialSkillsProgress } from "@/components/dashboard/FinancialSkillsProgress";
import { en } from "@/lib/i18n/dictionaries/en";
import { he } from "@/lib/i18n/dictionaries/he";
import { renderWithQuery, screen, within } from "@/tests/test-utils";
import type { SkillMasteryResponse } from "@/types/api-schemas";

/** A learner-visible label must never be, or contain, a database
 * identifier - this is the exact defect this card regressed on. */
const UUID_FRAGMENT_PATTERN = /Skill\s+[0-9a-f]{6,}/i;

function masteryRow(overrides: Partial<SkillMasteryResponse> = {}): SkillMasteryResponse {
  return {
    skill_id: "0dfce538-5f45-4d0e-8b6c-1f0e2a3b4c5d",
    skill_name: "Compound Interest",
    skill_code: "COMPOUND_INTEREST",
    mastery_score: 0.87,
    mastery_level: "PROFICIENT",
    correct_attempts: 7,
    total_attempts: 8,
    last_practiced_at: null,
    next_review_at: null,
    ...overrides,
  };
}

describe("FinancialSkillsProgress: canonical skill names", () => {
  it("labels each row with the canonical skill name from the API, never a skill_id fragment", () => {
    const { container } = renderWithQuery(
      <FinancialSkillsProgress
        items={[
          masteryRow(),
          masteryRow({
            skill_id: "c6341461-0a1b-4c2d-9e3f-4a5b6c7d8e9f",
            skill_name: "Diversification",
            skill_code: "DIVERSIFICATION",
            mastery_score: 0.49,
            mastery_level: "DEVELOPING",
          }),
        ]}
      />
    );

    expect(screen.getByText("Compound Interest")).toBeInTheDocument();
    expect(screen.getByText("Diversification")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(UUID_FRAGMENT_PATTERN);
    expect(container.textContent).not.toContain("0dfce538");
    expect(container.textContent).not.toContain("c6341461");
  });

  it("keeps the skill_id as a React key only, so the rows still render without repeating it", () => {
    const { container } = renderWithQuery(
      <FinancialSkillsProgress items={[masteryRow(), masteryRow({ skill_id: "8ae761e8-1111-2222-3333-444455556666", skill_name: "Stocks", skill_code: "STOCKS" })]} />
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(container.textContent).not.toContain("8ae761e8");
  });

  it("falls back to a localized financial-topic label - never a UUID - when skill metadata is missing", () => {
    const { container } = renderWithQuery(
      <FinancialSkillsProgress
        items={[masteryRow({ skill_name: null, skill_code: null, mastery_level: "NOVICE", mastery_score: 0.1 })]}
      />
    );

    expect(screen.getByText(en.dashboard.financialSkills.fallbackSkillName)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(UUID_FRAGMENT_PATTERN);
    expect(container.textContent).not.toContain("0dfce538");
  });

  it("prefers the backend's canonical English name for a skill code with no translation entry", () => {
    renderWithQuery(
      <FinancialSkillsProgress items={[masteryRow({ skill_name: "Sector Rotation", skill_code: "SECTOR_ROTATION" })]} />
    );

    expect(screen.getByText("Sector Rotation")).toBeInTheDocument();
  });

  it("keeps a long skill name fully readable instead of truncating it", () => {
    const longName = "Understanding Risk, Return and Diversification Across Global Asset Classes";
    renderWithQuery(<FinancialSkillsProgress items={[masteryRow({ skill_name: longName, skill_code: null })]} />);

    const label = screen.getByText(longName);
    expect(label).toBeInTheDocument();
    expect(label.className).toContain("break-words");
  });
});

describe("FinancialSkillsProgress: mastery levels and percentages", () => {
  it("renders the English mastery-level label for every level the backend can return", () => {
    renderWithQuery(
      <FinancialSkillsProgress
        items={[
          masteryRow({ skill_id: "a1", skill_code: "MONEY_BASICS", mastery_level: "NOT_ASSESSED", mastery_score: 0 }),
          masteryRow({ skill_id: "a2", skill_code: "INFLATION", mastery_level: "NOVICE", mastery_score: 0.2 }),
          masteryRow({ skill_id: "a3", skill_code: "STOCKS", mastery_level: "DEVELOPING", mastery_score: 0.49 }),
          masteryRow({ skill_id: "a4", skill_code: "BONDS", mastery_level: "PROFICIENT", mastery_score: 0.87 }),
          masteryRow({ skill_id: "a5", skill_code: "DIVERSIFICATION", mastery_level: "MASTERED", mastery_score: 1 }),
        ]}
      />
    );

    expect(screen.getByText("Not started")).toBeInTheDocument();
    expect(screen.getByText("Getting started")).toBeInTheDocument();
    expect(screen.getByText("Building confidence")).toBeInTheDocument();
    expect(screen.getByText("Strong understanding")).toBeInTheDocument();
    expect(screen.getByText("Mastered")).toBeInTheDocument();
  });

  it("renders the Hebrew mastery-level label for every level", () => {
    renderWithQuery(
      <FinancialSkillsProgress
        items={[
          masteryRow({ skill_id: "b1", skill_code: "MONEY_BASICS", mastery_level: "NOT_ASSESSED", mastery_score: 0 }),
          masteryRow({ skill_id: "b2", skill_code: "INFLATION", mastery_level: "NOVICE", mastery_score: 0.2 }),
          masteryRow({ skill_id: "b3", skill_code: "STOCKS", mastery_level: "DEVELOPING", mastery_score: 0.49 }),
          masteryRow({ skill_id: "b4", skill_code: "BONDS", mastery_level: "PROFICIENT", mastery_score: 0.87 }),
          masteryRow({ skill_id: "b5", skill_code: "DIVERSIFICATION", mastery_level: "MASTERED", mastery_score: 1 }),
        ]}
      />,
      { locale: "he" }
    );

    for (const label of Object.values(he.dashboard.financialSkills.levels)) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("rounds the 0-1 mastery score to a whole percentage at the boundaries", () => {
    renderWithQuery(
      <FinancialSkillsProgress
        items={[
          masteryRow({ skill_id: "c1", skill_code: "MONEY_BASICS", mastery_score: 0, mastery_level: "NOT_ASSESSED" }),
          masteryRow({ skill_id: "c2", skill_code: "INFLATION", mastery_score: 0.49, mastery_level: "DEVELOPING" }),
          masteryRow({ skill_id: "c3", skill_code: "STOCKS", mastery_score: 0.8749, mastery_level: "PROFICIENT" }),
          masteryRow({ skill_id: "c4", skill_code: "BONDS", mastery_score: 1, mastery_level: "MASTERED" }),
        ]}
      />
    );

    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(screen.getByText("49%")).toBeInTheDocument();
    expect(screen.getByText("87%")).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
  });
});

describe("FinancialSkillsProgress: accessibility", () => {
  it("exposes each row as a progressbar labelled by its skill name, with a 0-100 range", () => {
    renderWithQuery(
      <FinancialSkillsProgress
        items={[
          masteryRow({ skill_id: "d1", skill_name: "Stocks", skill_code: "STOCKS", mastery_score: 0.87 }),
          masteryRow({ skill_id: "d2", skill_name: "Bonds", skill_code: "BONDS", mastery_score: 0, mastery_level: "NOT_ASSESSED" }),
        ]}
      />
    );

    const stocks = screen.getByRole("progressbar", { name: "Stocks" });
    expect(stocks).toHaveAttribute("aria-valuenow", "87");
    expect(stocks).toHaveAttribute("aria-valuemin", "0");
    expect(stocks).toHaveAttribute("aria-valuemax", "100");

    const bonds = screen.getByRole("progressbar", { name: "Bonds" });
    expect(bonds).toHaveAttribute("aria-valuenow", "0");
  });

  it("uses a semantic list so a screen reader announces how many skills there are", () => {
    renderWithQuery(
      <FinancialSkillsProgress
        items={[masteryRow({ skill_id: "e1", skill_code: "STOCKS" }), masteryRow({ skill_id: "e2", skill_code: "BONDS" })]}
      />
    );

    const list = screen.getByRole("list");
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
  });

  it("states the mastery status in words, so colour is never the only cue", () => {
    renderWithQuery(<FinancialSkillsProgress items={[masteryRow({ mastery_level: "MASTERED", mastery_score: 1 })]} />);

    const row = screen.getByRole("listitem");
    expect(within(row).getByText("Mastered")).toBeInTheDocument();
  });

  it("does not repeat the percentage to a screen reader - the progressbar value carries it", () => {
    renderWithQuery(<FinancialSkillsProgress items={[masteryRow({ mastery_score: 0.87 })]} />);

    expect(screen.getByText("87%").closest("[aria-hidden='true']")).not.toBeNull();
  });
});

describe("FinancialSkillsProgress: Hebrew / RTL", () => {
  it("renders Hebrew skill names for the seeded curriculum codes", () => {
    renderWithQuery(
      <FinancialSkillsProgress
        items={[
          masteryRow({ skill_id: "f1", skill_name: "Compound Interest", skill_code: "COMPOUND_INTEREST" }),
          masteryRow({ skill_id: "f2", skill_name: "Stocks", skill_code: "STOCKS", mastery_level: "MASTERED", mastery_score: 1 }),
        ]}
      />,
      { locale: "he" }
    );

    expect(screen.getByText(he.dashboard.financialSkills.skillNames.COMPOUND_INTEREST)).toBeInTheDocument();
    expect(screen.getByText(he.dashboard.financialSkills.skillNames.STOCKS)).toBeInTheDocument();
    expect(screen.queryByText("Compound Interest")).not.toBeInTheDocument();
  });

  it("switches the document to right-to-left and isolates the percentage so it reads left-to-right", () => {
    renderWithQuery(<FinancialSkillsProgress items={[masteryRow({ mastery_score: 0.87 })]} />, { locale: "he" });

    expect(document.documentElement.dir).toBe("rtl");
    expect(screen.getByText("87%").closest("[dir='ltr']")).not.toBeNull();
  });

  it("never shows a skill whose Hebrew translation is missing as blank or hidden", () => {
    renderWithQuery(
      <FinancialSkillsProgress items={[masteryRow({ skill_name: "Sector Rotation", skill_code: "SECTOR_ROTATION" })]} />,
      { locale: "he" }
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("Sector Rotation")).toBeInTheDocument();
  });
});

describe("FinancialSkillsProgress: empty state", () => {
  it("shows the localized empty state in English", () => {
    renderWithQuery(<FinancialSkillsProgress items={[]} />);

    expect(screen.getByText(en.dashboard.financialSkills.emptyTitle)).toBeInTheDocument();
    expect(screen.getByText(en.dashboard.financialSkills.emptyDescription)).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("shows the localized empty state in Hebrew", () => {
    renderWithQuery(<FinancialSkillsProgress items={[]} />, { locale: "he" });

    expect(screen.getByText(he.dashboard.financialSkills.emptyTitle)).toBeInTheDocument();
    expect(screen.getByText(he.dashboard.financialSkills.emptyDescription)).toBeInTheDocument();
  });
});
