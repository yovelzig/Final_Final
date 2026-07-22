import { describe, expect, it, vi } from "vitest";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { FinQuestApiError } from "@/lib/api/client";
import { render, screen } from "@/tests/test-utils";

describe("ErrorState", () => {
  it("shows a friendly message and correlation-id reference for a backend error, never a stack trace", () => {
    const error = new FinQuestApiError({
      status: 500, code: "INTERNAL_ERROR", message: "Something broke.", correlationId: "corr-42",
    });
    render(<ErrorState error={error} />);

    expect(screen.getByText("Something broke.")).toBeInTheDocument();
    expect(screen.getByText(/Reference: corr-42/)).toBeInTheDocument();
    expect(screen.queryByText(/at\s+\S+\s+\(/)).not.toBeInTheDocument(); // no stack-trace-looking text
  });

  it("shows a specific message for an authentication error", () => {
    const error = new FinQuestApiError({ status: 401, code: "UNAUTHENTICATED", message: "raw" });
    render(<ErrorState error={error} />);
    expect(screen.getByText("Your session has expired. Please sign in again.")).toBeInTheDocument();
  });

  it("renders a retry button only when onRetry is provided, and calls it on click", async () => {
    const onRetry = vi.fn();
    const error = new FinQuestApiError({ status: 500, code: "X", message: "m" });
    const { rerender } = render(<ErrorState error={error} onRetry={onRetry} />);
    screen.getByRole("button", { name: "Try again" }).click();
    expect(onRetry).toHaveBeenCalledTimes(1);

    rerender(<ErrorState error={error} />);
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("uses role=alert so assistive technology announces the error", () => {
    render(<ErrorState error={new Error("boom")} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});

describe("EmptyState", () => {
  it("renders a title, optional description, and optional action", () => {
    render(<EmptyState title="Nothing here" description="Try something else" action={<button>Go</button>} />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.getByText("Try something else")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Go" })).toBeInTheDocument();
  });
});

describe("Alert", () => {
  it("defaults to role=status for non-alarming information", () => {
    render(<Alert tone="info">Heads up</Alert>);
    expect(screen.getByRole("status")).toHaveTextContent("Heads up");
  });
});

describe("Badge", () => {
  it("always pairs a status with a visible text label, never color alone", () => {
    render(<Badge tone="success">Correct</Badge>);
    expect(screen.getByText("Correct")).toBeInTheDocument();
  });
});

describe("ProgressBar", () => {
  it("exposes progressbar semantics with correct aria bounds", () => {
    render(<ProgressBar value={3} max={10} label="Progress" />);
    const bar = screen.getByRole("progressbar", { name: "Progress" });
    expect(bar).toHaveAttribute("aria-valuenow", "3");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "10");
  });

  it("clamps an out-of-range value into [0, max]", () => {
    render(<ProgressBar value={999} max={10} label="Progress" />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "10");
  });
});
