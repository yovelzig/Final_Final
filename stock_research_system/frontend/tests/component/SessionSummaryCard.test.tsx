import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SessionSummaryCard } from "@/components/adaptive/SessionSummaryCard";
import { render, screen } from "@/tests/test-utils";
import type { SessionSummaryResponse } from "@/types/api-schemas";

const SUMMARY: SessionSummaryResponse = {
  activities: [],
  mastery_changes: { "skill-1": 0.1, "skill-2": -0.05 },
  reviews_scheduled: [],
  session: {
    completed_at: "2026-01-01T00:10:00Z",
    completed_item_count: 4,
    correct_item_count: 3,
    goal_minutes: 10,
    last_activity_at: "2026-01-01T00:10:00Z",
    maximum_score: 4,
    recommended_item_count: 4,
    session_id: "session-1",
    session_type: "DAILY_PRACTICE",
    started_at: "2026-01-01T00:00:00Z",
    status: "COMPLETED",
    total_score: 3,
  },
};

describe("SessionSummaryCard", () => {
  it("displays only backend-provided session totals", () => {
    render(<SessionSummaryCard summary={SUMMARY} onStartNewSession={vi.fn()} isStartingNewSession={false} />);

    expect(screen.getByText("4")).toBeInTheDocument(); // completed
    expect(screen.getByText("3")).toBeInTheDocument(); // correct
    expect(screen.getByText("3/4")).toBeInTheDocument(); // score
    expect(screen.getByText("2")).toBeInTheDocument(); // skills updated
  });

  it("invokes onStartNewSession when the learner starts another session", async () => {
    const user = userEvent.setup();
    const onStartNewSession = vi.fn();
    render(<SessionSummaryCard summary={SUMMARY} onStartNewSession={onStartNewSession} isStartingNewSession={false} />);

    await user.click(screen.getByRole("button", { name: "Start another session" }));
    expect(onStartNewSession).toHaveBeenCalledTimes(1);
  });
});
