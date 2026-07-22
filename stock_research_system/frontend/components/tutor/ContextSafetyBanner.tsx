import { Alert } from "@/components/ui/Alert";
import type { components } from "@/types/generated-api";

type TutorContextType = components["schemas"]["TutorContextType"];

/** Context-specific reminders of what the tutor will and won't do -
 * the backend's guardrails are the actual enforcement; this only sets
 * the learner's expectations up front. */
export function ContextSafetyBanner({ contextType }: { contextType: TutorContextType }) {
  if (contextType === "SCENARIO_BEFORE_DECISION") {
    return (
      <Alert tone="warning" title="Before you decide">
        The tutor will help you think through this scenario, but it will never tell you what actually
        happened or which option is &ldquo;correct&rdquo; - that stays hidden until you reveal the outcome.
      </Alert>
    );
  }
  if (contextType === "PORTFOLIO_EXPLANATION") {
    return (
      <Alert tone="info" title="Educational only">
        The tutor can explain what&apos;s in your virtual portfolio and general investing concepts. It
        won&apos;t tell you what to buy or sell, or give personalized investment advice.
      </Alert>
    );
  }
  return null;
}
