import { axe } from "jest-axe";
import { describe, expect, it } from "vitest";

import { FinancialSkillsProgress } from "@/components/dashboard/FinancialSkillsProgress";
import { renderWithQuery, screen } from "@/tests/test-utils";
import type { SkillMasteryResponse } from "@/types/api-schemas";

/**
 * The route-level sweep in `pages.test.tsx` covers the dashboard with an
 * empty skills card; this file covers the populated card, including the
 * per-row progressbar semantics, in both reading directions.
 */

const ITEMS: SkillMasteryResponse[] = [
  {
    skill_id: "0dfce538-5f45-4d0e-8b6c-1f0e2a3b4c5d",
    skill_name: "Money Basics", skill_code: "MONEY_BASICS",
    mastery_score: 0, mastery_level: "NOT_ASSESSED",
    correct_attempts: 0, total_attempts: 0, last_practiced_at: null, next_review_at: null,
  },
  {
    skill_id: "c6341461-0a1b-4c2d-9e3f-4a5b6c7d8e9f",
    skill_name: "Compound Interest", skill_code: "COMPOUND_INTEREST",
    mastery_score: 0.49, mastery_level: "DEVELOPING",
    correct_attempts: 2, total_attempts: 5, last_practiced_at: null, next_review_at: null,
  },
  {
    skill_id: "8ae761e8-1111-2222-3333-444455556666",
    skill_name: "Risk and Return", skill_code: "RISK_AND_RETURN",
    mastery_score: 0.87, mastery_level: "PROFICIENT",
    correct_attempts: 7, total_attempts: 8, last_practiced_at: null, next_review_at: null,
  },
  {
    skill_id: "06456a7a-9999-8888-7777-666655554444",
    skill_name: "Diversification", skill_code: "DIVERSIFICATION",
    mastery_score: 1, mastery_level: "MASTERED",
    correct_attempts: 9, total_attempts: 9, last_practiced_at: null, next_review_at: null,
  },
];

describe("accessibility: Financial Skills Progress", () => {
  it("has no violations in English", async () => {
    const { container } = renderWithQuery(<FinancialSkillsProgress items={ITEMS} />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it("has no violations in Hebrew (RTL)", async () => {
    const { container } = renderWithQuery(<FinancialSkillsProgress items={ITEMS} />, { locale: "he" });
    expect(await axe(container)).toHaveNoViolations();
  });

  it("gives every row a progressbar whose accessible name is the skill name", async () => {
    renderWithQuery(<FinancialSkillsProgress items={ITEMS} />);

    const bars = screen.getAllByRole("progressbar");
    expect(bars).toHaveLength(ITEMS.length);
    expect(bars.map((bar) => bar.getAttribute("aria-valuenow"))).toEqual(["0", "49", "87", "100"]);
    for (const item of ITEMS) {
      expect(screen.getByRole("progressbar", { name: item.skill_name as string })).toBeInTheDocument();
    }
  });
});
