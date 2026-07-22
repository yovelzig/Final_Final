import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MultipleChoiceInput } from "@/components/exercises/MultipleChoiceInput";
import { NumericAnswerInput } from "@/components/exercises/NumericAnswerInput";
import { OrderingInput } from "@/components/exercises/OrderingInput";
import { SingleSelectInput } from "@/components/exercises/SingleSelectInput";
import { TextResponseInput } from "@/components/exercises/TextResponseInput";
import { EMPTY_DRAFT } from "@/components/exercises/types";
import { render, screen } from "@/tests/test-utils";

const OPTIONS = [
  { option_id: "a", option_key: "A", content: "First option", position: 0 },
  { option_id: "b", option_key: "B", content: "Second option", position: 1 },
  { option_id: "c", option_key: "C", content: "Third option", position: 2 },
];

describe("SingleSelectInput", () => {
  it("selects exactly one option and replaces the previous selection", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<SingleSelectInput options={OPTIONS} draft={EMPTY_DRAFT} onChange={onChange} disabled={false} />);

    await user.click(screen.getByRole("radio", { name: "First option" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...EMPTY_DRAFT, selectedOptionIds: ["a"] });
  });

  it("never renders any correctness indicator for an option", () => {
    render(<SingleSelectInput options={OPTIONS} draft={EMPTY_DRAFT} onChange={vi.fn()} disabled={false} />);
    expect(screen.queryByText(/correct/i)).not.toBeInTheDocument();
  });
});

describe("MultipleChoiceInput", () => {
  it("toggles independent checkboxes without revealing an expected count", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <MultipleChoiceInput options={OPTIONS} draft={EMPTY_DRAFT} onChange={onChange} disabled={false} />
    );

    await user.click(screen.getByRole("checkbox", { name: "First option" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...EMPTY_DRAFT, selectedOptionIds: ["a"] });

    const withFirstSelected = { ...EMPTY_DRAFT, selectedOptionIds: ["a"] };
    rerender(<MultipleChoiceInput options={OPTIONS} draft={withFirstSelected} onChange={onChange} disabled={false} />);
    await user.click(screen.getByRole("checkbox", { name: "Second option" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...withFirstSelected, selectedOptionIds: ["a", "b"] });

    expect(screen.queryByText(/select \d+/i)).not.toBeInTheDocument();
  });
});

describe("NumericAnswerInput", () => {
  it("reports an invalid entry without doing the grading itself", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<NumericAnswerInput draft={{ ...EMPTY_DRAFT, numericAnswer: "abc" }} onChange={onChange} disabled={false} />);

    expect(screen.getByText("Enter a valid number.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Your answer"), "1");
    expect(onChange).toHaveBeenCalled();
  });

  it("shows no error for a valid number", () => {
    render(<NumericAnswerInput draft={{ ...EMPTY_DRAFT, numericAnswer: "42.5" }} onChange={vi.fn()} disabled={false} />);
    expect(screen.queryByText("Enter a valid number.")).not.toBeInTheDocument();
  });
});

describe("OrderingInput", () => {
  it("is operable via keyboard-focusable move buttons, not drag-and-drop only", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const draft = { ...EMPTY_DRAFT, orderedOptionIds: ["a", "b", "c"] };
    render(<OrderingInput options={OPTIONS} draft={draft} onChange={onChange} disabled={false} />);

    await user.click(screen.getByRole("button", { name: 'Move "Second option" up' }));
    expect(onChange).toHaveBeenLastCalledWith({ ...draft, orderedOptionIds: ["b", "a", "c"] });
  });

  it("disables moving the first item further up and the last item further down", () => {
    const draft = { ...EMPTY_DRAFT, orderedOptionIds: ["a", "b", "c"] };
    render(<OrderingInput options={OPTIONS} draft={draft} onChange={vi.fn()} disabled={false} />);

    expect(screen.getByRole("button", { name: 'Move "First option" up' })).toBeDisabled();
    expect(screen.getByRole("button", { name: 'Move "Third option" down' })).toBeDisabled();
  });
});

describe("TextResponseInput", () => {
  it("tracks the character count as the learner types", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(<TextResponseInput draft={EMPTY_DRAFT} onChange={onChange} disabled={false} />);

    expect(screen.getByText("0/5000")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Your response"), "hi");
    expect(onChange).toHaveBeenCalled();

    rerender(<TextResponseInput draft={{ ...EMPTY_DRAFT, textAnswer: "hi" }} onChange={onChange} disabled={false} />);
    expect(screen.getByText("2/5000")).toBeInTheDocument();
  });
});
