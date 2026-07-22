import type { components } from "@/types/generated-api";

type RecommendationType = components["schemas"]["RecommendationType"];
type RecommendationReason = components["schemas"]["RecommendationReason"];

/** Learner-friendly copy for backend-issued recommendation codes. The
 * backend decides WHAT to recommend and WHY (reason codes); this only
 * translates those codes into readable text - it never invents a
 * reason the backend didn't send. */
export const RECOMMENDATION_TYPE_LABELS: Record<RecommendationType, string> = {
  NEW_LESSON: "New lesson",
  PRACTICE_EXERCISE: "Practice",
  REVIEW_EXERCISE: "Review",
  MISCONCEPTION_REMEDIATION: "Clear up a misconception",
  PREREQUISITE_REVIEW: "Prerequisite review",
  DIAGNOSTIC_EXERCISE: "Diagnostic check",
  SESSION_COMPLETE: "Session complete",
  NO_ELIGIBLE_CONTENT: "Nothing to practice right now",
};

export const RECOMMENDATION_REASON_LABELS: Record<RecommendationReason, string> = {
  ACTIVE_MISCONCEPTION: "You have an active misconception here",
  OVERDUE_REVIEW: "This review is overdue",
  LOW_MASTERY: "Your mastery of this skill is still low",
  PREREQUISITE_GAP: "A prerequisite skill needs attention first",
  INCOMPLETE_LESSON: "This lesson isn't finished yet",
  RECENT_FAILURE: "You missed this recently",
  LOW_CONFIDENCE: "You reported low confidence here",
  DIAGNOSTIC_COVERAGE: "Needed for diagnostic coverage",
  NEW_CONTENT: "New content for you",
  DAILY_GOAL_REACHED: "You've reached your daily goal",
  NO_ELIGIBLE_EXERCISE: "No eligible exercise was found",
};
