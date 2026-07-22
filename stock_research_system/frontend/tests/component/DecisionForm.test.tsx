import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DecisionForm } from "@/components/scenarios/DecisionForm";
import { render, screen } from "@/tests/test-utils";

const OPTIONS = [
  { option_id: "buy", option_key: "A", content: "Buy more", position: 0 },
  { option_id: "hold", option_key: "B", content: "Hold", position: 1 },
];

describe("DecisionForm", () => {
  it("disables submission until an option is selected", () => {
    render(<DecisionForm options={OPTIONS} onSubmit={vi.fn()} isSubmitting={false} />);
    expect(screen.getByRole("button", { name: "Submit decision" })).toBeDisabled();
  });

  it("submits the selected option, confidence, and rationale", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<DecisionForm options={OPTIONS} onSubmit={onSubmit} isSubmitting={false} />);

    await user.click(screen.getByRole("radio", { name: "Hold" }));
    await user.selectOptions(screen.getByLabelText(/How confident/), "HIGH");
    await user.type(screen.getByLabelText(/Why did you make this decision/), "Staying the course.");
    await user.click(screen.getByRole("button", { name: "Submit decision" }));

    expect(onSubmit).toHaveBeenCalledWith({
      selectedOptionId: "hold",
      confidenceLevel: "HIGH",
      rationale: "Staying the course.",
    });
  });

  it("never renders a correct-option indicator before submission", () => {
    render(<DecisionForm options={OPTIONS} onSubmit={vi.fn()} isSubmitting={false} />);
    expect(screen.queryByText(/correct/i)).not.toBeInTheDocument();
  });
});
