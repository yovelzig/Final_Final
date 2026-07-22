"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import type { CoachStreamEvent } from "@/lib/api/coach-stream";

type ApprovalRequest = Extract<CoachStreamEvent, { type: "approval_required" }>;

/** A proposed, learner-approvable action - never auto-executed. Shows
 * only the safe fields the backend's `approval_interrupt` node ever
 * sends (title/description/reason/safe parameters); disables itself
 * permanently after a decision is made so a slow network can never
 * result in a double-submit. */
export function ApprovalCard({
  request,
  decision,
  isSubmitting,
  onApprove,
  onReject,
}: {
  request: ApprovalRequest;
  decision: "APPROVE" | "REJECT" | "EDIT" | null;
  isSubmitting: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  const [announcement, setAnnouncement] = useState("");
  const isDecided = decision !== null;

  const handleApprove = () => {
    setAnnouncement(`Approved: ${request.title}.`);
    onApprove();
  };
  const handleReject = () => {
    setAnnouncement(`Declined: ${request.title}.`);
    onReject();
  };

  return (
    <div className="flex flex-col gap-3 rounded-card border border-primary/30 bg-primary-light p-4" role="group" aria-label="Action approval">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-slate-900">{request.title}</p>
        {isDecided ? (
          <Badge tone={decision === "APPROVE" ? "success" : "neutral"}>
            {decision === "APPROVE" ? "Approved" : "Declined"}
          </Badge>
        ) : (
          <Badge tone="primary">Needs your approval</Badge>
        )}
      </div>
      <p className="text-sm text-slate-700">{request.description}</p>
      <p className="text-xs text-muted">{request.reason}</p>

      {!isDecided ? (
        <div className="flex gap-2">
          <Button size="sm" onClick={handleApprove} isLoading={isSubmitting} disabled={isSubmitting}>
            Approve
          </Button>
          <Button size="sm" variant="ghost" onClick={handleReject} isLoading={isSubmitting} disabled={isSubmitting}>
            Not now
          </Button>
        </div>
      ) : null}

      <span className="sr-only" role="status" aria-live="polite">
        {announcement}
      </span>
    </div>
  );
}
