import type { components } from "@/types/generated-api";

type TutorContextType = components["schemas"]["TutorContextType"];

export const TUTOR_CONTEXT_LABELS: Record<TutorContextType, string> = {
  GENERAL_EDUCATION: "General question",
  LESSON_HELP: "Lesson help",
  EXERCISE_HELP: "Exercise help",
  SCENARIO_BEFORE_DECISION: "Scenario help (before deciding)",
  SCENARIO_AFTER_REVEAL: "Scenario review (after reveal)",
  PORTFOLIO_EXPLANATION: "Portfolio explanation",
};
