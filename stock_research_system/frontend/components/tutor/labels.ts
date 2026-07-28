import type { Dictionary } from "@/lib/i18n/types";
import type { components } from "@/types/generated-api";

type TutorContextType = components["schemas"]["TutorContextType"];

/** Looks up the display label for a tutor conversation's context type
 * from the active dictionary - takes `t` explicitly (rather than
 * calling `useDictionary()` itself) so it stays a plain function
 * usable from anywhere a dictionary is already in scope. */
export function getTutorContextLabel(t: Dictionary, contextType: TutorContextType): string {
  const labels: Record<TutorContextType, string> = {
    GENERAL_EDUCATION: t.tutor.contextLabels.generalEducation,
    LESSON_HELP: t.tutor.contextLabels.lessonHelp,
    EXERCISE_HELP: t.tutor.contextLabels.exerciseHelp,
    SCENARIO_BEFORE_DECISION: t.tutor.contextLabels.scenarioBeforeDecision,
    SCENARIO_AFTER_REVEAL: t.tutor.contextLabels.scenarioAfterReveal,
    PORTFOLIO_EXPLANATION: t.tutor.contextLabels.portfolioExplanation,
  };
  return labels[contextType];
}
