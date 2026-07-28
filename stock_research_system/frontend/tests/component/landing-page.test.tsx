import { describe, expect, it } from "vitest";

import HomePage from "@/app/page";
import { he } from "@/lib/i18n/dictionaries/he";
import { renderWithProviders, screen } from "@/tests/test-utils";

describe("landing page: bilingual rendering", () => {
  it("renders the English hero, CTAs, and trust section by default", () => {
    renderWithProviders(<HomePage />, { locale: "en" });

    expect(screen.getByRole("heading", { level: 1, name: /Learn to invest with confidence/i })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Create your free account/i }).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Built for learning, not for advice" })).toBeInTheDocument();
  });

  it("renders the full Hebrew translation - hero, nav, and trust points - with no leftover English UI copy", () => {
    renderWithProviders(<HomePage />, { locale: "he" });

    expect(screen.getByRole("heading", { level: 1, name: he.landing.hero.title })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: he.landing.hero.primaryCta }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: he.landing.nav.login }).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: he.landing.trust.title })).toBeInTheDocument();
    for (const point of he.landing.trust.points) {
      expect(screen.getByText(point)).toBeInTheDocument();
    }

    // No stale English hero copy left behind after switching dictionaries.
    expect(screen.queryByText("Learn to invest with confidence, one grounded lesson at a time")).not.toBeInTheDocument();
  });

  it("does not fabricate customer counts, testimonials, or return figures", () => {
    renderWithProviders(<HomePage />, { locale: "en" });
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).not.toMatch(/\d[\d,]*\+?\s*(learners|users|students|customers)/i);
    expect(bodyText).not.toMatch(/\d+(\.\d+)?%\s*(return|gain|growth)/i);
  });
});
