import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CitationList } from "@/components/tutor/CitationList";
import { render, screen } from "@/tests/test-utils";

const CITATIONS = [
  {
    citation_number: 1,
    document_title: "Understanding Diversification",
    source_title: "FinQuest Curriculum",
    heading_path: ["Module 2", "Diversification"],
    excerpt: "Diversification spreads risk across many holdings.",
  },
];

describe("CitationList", () => {
  it("renders nothing when there are no citations", () => {
    const { container } = render(<CitationList citations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the citation number, document, and heading path collapsed by default", () => {
    render(<CitationList citations={CITATIONS} />);
    const toggle = screen.getByRole("button", { name: /Understanding Diversification/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/Diversification spreads risk/)).not.toBeInTheDocument();
  });

  it("expands to reveal the excerpt and source on click", async () => {
    const user = userEvent.setup();
    render(<CitationList citations={CITATIONS} />);

    await user.click(screen.getByRole("button", { name: /Understanding Diversification/ }));

    expect(screen.getByText(/Diversification spreads risk/)).toBeInTheDocument();
    expect(screen.getByText(/FinQuest Curriculum/)).toBeInTheDocument();
  });

  it("never renders a chunk id or vector-looking field", () => {
    render(<CitationList citations={CITATIONS} />);
    expect(screen.queryByText(/chunk/i)).not.toBeInTheDocument();
  });
});
