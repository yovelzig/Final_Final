"use client";

import { Alert } from "@/components/ui/Alert";
import { useDictionary } from "@/providers/LocaleProvider";
import type { components } from "@/types/generated-api";

type TutorContextType = components["schemas"]["TutorContextType"];

/** Context-specific reminders of what the tutor will and won't do -
 * the backend's guardrails are the actual enforcement; this only sets
 * the learner's expectations up front. */
export function ContextSafetyBanner({ contextType }: { contextType: TutorContextType }) {
  const t = useDictionary();

  if (contextType === "SCENARIO_BEFORE_DECISION") {
    return (
      <Alert tone="warning" title={t.tutor.contextSafety.beforeDecisionTitle}>
        {t.tutor.contextSafety.beforeDecisionBody}
      </Alert>
    );
  }
  if (contextType === "PORTFOLIO_EXPLANATION") {
    return (
      <Alert tone="info" title={t.tutor.contextSafety.portfolioTitle}>
        {t.tutor.contextSafety.portfolioBody}
      </Alert>
    );
  }
  return null;
}
