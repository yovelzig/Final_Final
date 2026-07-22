import type { components } from "@/types/generated-api";

type ScenarioFeedbackCode = components["schemas"]["ScenarioFeedbackCode"];
type ScenarioDecisionQuality = components["schemas"]["ScenarioDecisionQuality"];

export const FEEDBACK_CODE_LABELS: Record<ScenarioFeedbackCode, string> = {
  IDENTIFIED_RISK: "You identified a key risk",
  IGNORED_RISK: "You may have overlooked a risk",
  CONSIDERED_BENCHMARK: "You considered the benchmark",
  IGNORED_BENCHMARK: "You didn't compare against the benchmark",
  MATCHED_TIME_HORIZON: "Your decision matched the time horizon",
  MISMATCHED_TIME_HORIZON: "Your decision didn't match the time horizon",
  REQUESTED_MORE_INFORMATION: "You asked for more information before deciding",
  OVERCONFIDENT_DECISION: "Your confidence may have outpaced the available evidence",
  RECOGNIZED_UNCERTAINTY: "You recognized the uncertainty involved",
  CONCENTRATION_RISK: "This decision carries concentration risk",
  OUTCOME_BIAS_WARNING: "Remember: a good outcome doesn't always mean a good decision",
  GOOD_PROCESS_BAD_OUTCOME: "Good process, unlucky outcome",
  BAD_PROCESS_GOOD_OUTCOME: "Lucky outcome despite a weaker process",
  GOOD_PROCESS_GOOD_OUTCOME: "Good process and a good outcome",
  BAD_PROCESS_BAD_OUTCOME: "The process and outcome both suggest room to improve",
};

export const DECISION_QUALITY_LABELS: Record<ScenarioDecisionQuality, string> = {
  POOR: "Poor",
  DEVELOPING: "Developing",
  GOOD: "Good",
  STRONG: "Strong",
};
