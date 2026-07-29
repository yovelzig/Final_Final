import { describe, expect, it, vi } from "vitest";

import { CoachTurnView } from "@/components/coach/CoachTurnView";
import type { CoachTurn } from "@/hooks/useCoachStream";
import { renderWithQuery, screen } from "@/tests/test-utils";

let pollState: {
  status: "WAITING_FOR_RESEARCH" | "SUCCEEDED" | "FAILED";
  isPolling: boolean;
  timedOut: boolean;
  finalResponse: null | { answer_markdown: string; citations: unknown[] };
  errorKind: null | "failure";
};

vi.mock("@/hooks/useCoachRunPolling", () => ({
  useCoachRunPolling: () => pollState,
}));

const turn: CoachTurn = {
  id: "turn-1", runId: "run-1", userInput: "What happened?", stage: null,
  answerMarkdown: null, citations: [], approvalRequest: null, approvalDecision: null,
  navigationTarget: null, errorMessage: null, isComplete: false,
  researchStatus: "waiting", researchDeadlineAt: null,
};

describe("CoachTurnView polled terminal rendering", () => {
  it("renders waiting, safe polled success/citations, terminal failure, and Hebrew failure", () => {
    pollState = {
      status: "WAITING_FOR_RESEARCH", isPolling: true, timedOut: false,
      finalResponse: null, errorKind: null,
    };
    const view = renderWithQuery(
      <CoachTurnView turn={turn} isStreaming={false} onApprove={vi.fn()} onReject={vi.fn()} />
    );
    expect(screen.getByText("Still researching… this can take a minute.")).toBeInTheDocument();

    pollState = {
      status: "SUCCEEDED", isPolling: false, timedOut: false,
      finalResponse: {
        answer_markdown: "Polled answer",
        citations: [{
          citation_number: 1, document_title: "Quarterly report", source_title: "Issuer",
          evidence_id: "secret-id", provider_metadata: { token: "secret" },
        }],
      },
      errorKind: null,
    };
    view.rerender(<CoachTurnView turn={turn} isStreaming={false} onApprove={vi.fn()} onReject={vi.fn()} />);
    expect(screen.getByText("Polled answer")).toBeInTheDocument();
    expect(screen.getByText(/Quarterly report/)).toHaveTextContent("[1] Quarterly report — Issuer");
    expect(screen.queryByText("Still researching… this can take a minute.")).not.toBeInTheDocument();
    expect(view.container).not.toHaveTextContent("secret-id");
    expect(view.container).not.toHaveTextContent("provider_metadata");

    pollState = {
      status: "FAILED", isPolling: false, timedOut: false, finalResponse: null, errorKind: "failure",
    };
    view.rerender(<CoachTurnView turn={turn} isStreaming={false} onApprove={vi.fn()} onReject={vi.fn()} />);
    expect(screen.getByText("This request could not be completed. Please try again.")).toBeInTheDocument();
    expect(screen.queryByText("Still researching… this can take a minute.")).not.toBeInTheDocument();
    view.unmount();

    const hebrew = renderWithQuery(
      <CoachTurnView turn={turn} isStreaming={false} onApprove={vi.fn()} onReject={vi.fn()} />,
      { locale: "he" }
    );
    expect(screen.getByText("לא ניתן היה להשלים את הבקשה. נסו שוב.")).toBeInTheDocument();
    expect(hebrew.container.closest("[dir=rtl]") ?? document.documentElement).toBeTruthy();
  });
});