"""Deterministic, versioned decision-quality grading for historical
market scenarios.

No LLM, no machine learning: every rule here is explicit and testable.
The base decision-quality score always comes from the already-validated
`ScenarioOptionRubric.decision_quality_score` (see
`domain.market_scenarios.models.RUBRIC_COMPONENT_WEIGHTS`, the single
source of truth for the weighting formula - never recomputed or
duplicated here). `grade()` takes no `ScenarioOutcome` argument at all,
so it is structurally impossible for it to read the realized future
return.
"""

from __future__ import annotations

from typing import Protocol

from stock_research_core.application.exceptions import InvalidScenarioStateError
from stock_research_core.domain.learning.enums import ConfidenceLevel
from stock_research_core.domain.market_scenarios.enums import (
    ScenarioDecisionQuality,
    ScenarioExpectedDirection,
    ScenarioFeedbackCode,
    ScenarioOutcomeDirection,
)
from stock_research_core.domain.market_scenarios.models import (
    HistoricalMarketScenario,
    ScenarioOptionRubric,
    ScenarioOutcome,
    ScenarioSubmission,
)

GRADING_VERSION = "scenario-grading-v1"

_OVERCONFIDENT_THRESHOLD = 0.50
_OVERCONFIDENT_PENALTY = 0.10
_UNDERCONFIDENT_THRESHOLD = 0.80

_HIGH_CONFIDENCE_LEVELS = frozenset({ConfidenceLevel.HIGH, ConfidenceLevel.VERY_HIGH})
_LOW_CONFIDENCE_LEVELS = frozenset({ConfidenceLevel.LOW, ConfidenceLevel.VERY_LOW})

_POOR_MAX = 0.30
_DEVELOPING_MAX = 0.60
_GOOD_MAX = 0.85

_PROCESS_QUALITY_THRESHOLD = 0.60
_OUTCOME_ALIGNMENT_THRESHOLD = 0.5

_OUTCOME_BIAS_TEXT: dict[ScenarioFeedbackCode, str] = {
    ScenarioFeedbackCode.GOOD_PROCESS_GOOD_OUTCOME: (
        "You made a sound, risk-aware decision, and the market outcome aligned with it. "
        "Both your process and the result were good - keep using this kind of reasoning."
    ),
    ScenarioFeedbackCode.GOOD_PROCESS_BAD_OUTCOME: (
        "Your reasoning was sound, even though the market outcome did not align with it. "
        "A good decision can still have an unlucky result - do not let this outcome change "
        "how you evaluate the quality of your reasoning."
    ),
    ScenarioFeedbackCode.BAD_PROCESS_GOOD_OUTCOME: (
        "The market outcome happened to align with your decision, but the underlying reasoning "
        "had gaps. A lucky result does not make a decision process sound - review the "
        "improvement feedback above before relying on similar reasoning again."
    ),
    ScenarioFeedbackCode.BAD_PROCESS_BAD_OUTCOME: (
        "Both the reasoning behind this decision and the market outcome were weak. Focus on the "
        "improvement feedback above to strengthen your process for next time."
    ),
}

_OUTCOME_BIAS_WARNING_TEXT = (
    "Remember: decision quality and market outcome are different things - a good decision can "
    "still lose money, and a poor decision can still get lucky. Your mastery progress from this "
    "scenario is based on your decision quality, never on what the market happened to do."
)

_DIVERGING_BIAS_CODES = frozenset(
    {
        ScenarioFeedbackCode.GOOD_PROCESS_BAD_OUTCOME,
        ScenarioFeedbackCode.BAD_PROCESS_GOOD_OUTCOME,
    }
)


class ScenarioGradingPolicyPort(Protocol):
    """Grades scenario decisions, and separately explains realized
    outcomes once they are known. Distinct methods (rather than one
    `grade`) so the type signature itself proves decision quality
    cannot depend on the outcome: `grade` never receives one.
    """

    policy_version: str

    def grade(
        self,
        *,
        scenario: HistoricalMarketScenario,
        rubric: ScenarioOptionRubric,
        confidence_level: ConfidenceLevel | None,
        learner_rationale: str | None,
    ) -> tuple[float, ScenarioDecisionQuality, list[ScenarioFeedbackCode], str]: ...

    def calculate_outcome_alignment(
        self, *, rubric: ScenarioOptionRubric, outcome: ScenarioOutcome
    ) -> float: ...

    def build_reveal_feedback(
        self,
        *,
        submission: ScenarioSubmission,
        rubric: ScenarioOptionRubric,
        outcome: ScenarioOutcome,
    ) -> tuple[str, str, str]: ...


class RuleBasedScenarioGradingPolicy:
    """scenario-grading-v1: deterministic decision-quality grading plus
    post-reveal outcome-vs-process feedback.

    Confidence adjustment (applied on top of the rubric's base score,
    documented per spec section 9):
      - VERY_HIGH/HIGH confidence on a rubric scoring below 0.50:
        subtract 0.10, add OVERCONFIDENT_DECISION.
      - VERY_LOW/LOW confidence on a rubric scoring at least 0.80: no
        penalty, but RECOGNIZED_UNCERTAINTY feedback is added noting the
        decision was actually strong.
      - Otherwise: no adjustment.
    Result is clamped to [0, 1] and classified: POOR < 0.30, DEVELOPING
    < 0.60, GOOD < 0.85, STRONG >= 0.85.

    `learner_rationale` is stored by the caller but never inspected here
    to change the score - matching spec section 9's explicit "do not
    increase the score solely through keyword presence".
    """

    policy_version = GRADING_VERSION

    def grade(
        self,
        *,
        scenario: HistoricalMarketScenario,
        rubric: ScenarioOptionRubric,
        confidence_level: ConfidenceLevel | None,
        learner_rationale: str | None,
    ) -> tuple[float, ScenarioDecisionQuality, list[ScenarioFeedbackCode], str]:
        score = rubric.decision_quality_score
        feedback_codes = list(rubric.feedback_codes)
        adjustment_note: str | None = None

        if (
            confidence_level in _HIGH_CONFIDENCE_LEVELS
            and rubric.decision_quality_score < _OVERCONFIDENT_THRESHOLD
        ):
            score = score - _OVERCONFIDENT_PENALTY
            if ScenarioFeedbackCode.OVERCONFIDENT_DECISION not in feedback_codes:
                feedback_codes.append(ScenarioFeedbackCode.OVERCONFIDENT_DECISION)
            adjustment_note = (
                "Your confidence was high, but the reasoning behind this option was weak - try "
                "to calibrate confidence to the strength of your reasoning, not to how the "
                "market later moved."
            )
        elif (
            confidence_level in _LOW_CONFIDENCE_LEVELS
            and rubric.decision_quality_score >= _UNDERCONFIDENT_THRESHOLD
        ):
            if ScenarioFeedbackCode.RECOGNIZED_UNCERTAINTY not in feedback_codes:
                feedback_codes.append(ScenarioFeedbackCode.RECOGNIZED_UNCERTAINTY)
            adjustment_note = (
                "This was actually a strong, well-reasoned decision - low confidence did not "
                "reduce your score, but it is worth noticing when your reasoning is this solid."
            )

        score = max(0.0, min(1.0, score))
        decision_quality = self._classify(score)

        feedback_parts = [rubric.positive_feedback, rubric.improvement_feedback]
        if adjustment_note is not None:
            feedback_parts.append(adjustment_note)
        feedback_text = " ".join(feedback_parts)

        return score, decision_quality, feedback_codes, feedback_text

    def _classify(self, score: float) -> ScenarioDecisionQuality:
        if score < _POOR_MAX:
            return ScenarioDecisionQuality.POOR
        if score < _DEVELOPING_MAX:
            return ScenarioDecisionQuality.DEVELOPING
        if score < _GOOD_MAX:
            return ScenarioDecisionQuality.GOOD
        return ScenarioDecisionQuality.STRONG

    def calculate_outcome_alignment(
        self, *, rubric: ScenarioOptionRubric, outcome: ScenarioOutcome
    ) -> float:
        """Display-only score - never used to update mastery.

        1.0 for directional alignment (expected POSITIVE/NEGATIVE
        matching the realized direction), 0.5 for a NEUTRAL/
        INFORMATION_REQUIRED decision or a directional decision facing a
        FLAT/highly-uncertain realized outcome, 0.0 for a directional
        mismatch.
        """
        if rubric.expected_direction in (
            ScenarioExpectedDirection.NEUTRAL,
            ScenarioExpectedDirection.INFORMATION_REQUIRED,
        ):
            return 0.5

        expected_outcome = (
            ScenarioOutcomeDirection.POSITIVE
            if rubric.expected_direction == ScenarioExpectedDirection.POSITIVE
            else ScenarioOutcomeDirection.NEGATIVE
        )
        if outcome.outcome_direction == expected_outcome:
            return 1.0
        if outcome.outcome_direction == ScenarioOutcomeDirection.FLAT:
            return 0.5
        return 0.0

    def build_reveal_feedback(
        self,
        *,
        submission: ScenarioSubmission,
        rubric: ScenarioOptionRubric,
        outcome: ScenarioOutcome,
    ) -> tuple[str, str, str]:
        if submission.decision_quality_score is None or submission.outcome_alignment_score is None:
            raise InvalidScenarioStateError(
                "build_reveal_feedback requires a graded submission with an "
                "outcome_alignment_score already computed."
            )

        good_process = submission.decision_quality_score >= _PROCESS_QUALITY_THRESHOLD
        good_outcome = submission.outcome_alignment_score >= _OUTCOME_ALIGNMENT_THRESHOLD

        if good_process and good_outcome:
            bias_code = ScenarioFeedbackCode.GOOD_PROCESS_GOOD_OUTCOME
        elif good_process and not good_outcome:
            bias_code = ScenarioFeedbackCode.GOOD_PROCESS_BAD_OUTCOME
        elif not good_process and good_outcome:
            bias_code = ScenarioFeedbackCode.BAD_PROCESS_GOOD_OUTCOME
        else:
            bias_code = ScenarioFeedbackCode.BAD_PROCESS_BAD_OUTCOME

        decision_feedback = submission.feedback_text or ""
        outcome_feedback = outcome.outcome_summary

        summary_parts = [_OUTCOME_BIAS_TEXT[bias_code]]
        if bias_code in _DIVERGING_BIAS_CODES:
            summary_parts.append(_OUTCOME_BIAS_WARNING_TEXT)
        combined_learning_summary = " ".join(summary_parts)

        return decision_feedback, outcome_feedback, combined_learning_summary
