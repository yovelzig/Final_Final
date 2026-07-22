"""Deterministic, versioned educational risk/diversification feedback.

Describes portfolio *characteristics* - never a stock recommendation,
never a buy/sell instruction, never a promise about future returns.
No machine learning, no LLM calls, no randomness.
"""

from __future__ import annotations

from typing import Protocol

from stock_research_core.domain.virtual_portfolio.enums import DecisionConfidence, PortfolioFeedbackCode, PortfolioRiskLevel
from stock_research_core.domain.virtual_portfolio.models import (
    PortfolioDecisionJournalEntry,
    PortfolioPerformanceSummary,
    PortfolioPositionValuation,
    PortfolioRiskAssessment,
    PortfolioValuationSnapshot,
    VirtualPortfolio,
)

FEEDBACK_VERSION = "portfolio-feedback-v1"

_HIGH_CONFIDENCE_LEVELS = frozenset({DecisionConfidence.HIGH, DecisionConfidence.VERY_HIGH})

# -- documented thresholds (spec gives exact numbers for most; where the
# spec only names the feedback code without a number, e.g. HIGH_VOLATILITY
# and LOW_TURNOVER, a reasonable deterministic threshold is chosen here
# and documented explicitly). ---------------------------------------------

_POSITION_VERY_HIGH = 0.50
_POSITION_HIGH = 0.35
_POSITION_MODERATE = 0.20

_SECTOR_VERY_HIGH = 0.70
_SECTOR_HIGH = 0.50
_SECTOR_MODERATE = 0.35

_MIN_DIVERSIFIED_POSITIONS = 3
_LOW_DIVERSIFICATION_SCORE = 0.35
_BROAD_DIVERSIFICATION_SCORE = 0.70

_HIGH_CASH_WEIGHT = 0.50

_LARGE_DRAWDOWN = -0.25
_HIGH_DRAWDOWN = -0.15

#: Not given a specific number in the spec - chosen as a reasonable,
#: documented threshold for an individual portfolio's annualized
#: volatility of returns.
_HIGH_VOLATILITY = 0.40

_HIGH_TURNOVER = 2.0
#: Not given a specific number in the spec - chosen as the low-turnover
#: counterpart to the high-turnover threshold above.
_LOW_TURNOVER = 0.50


class PortfolioFeedbackPolicyPort(Protocol):
    """Produces deterministic, educational risk feedback for one valuation."""

    policy_version: str

    def assess(
        self,
        *,
        portfolio: VirtualPortfolio,
        snapshot: PortfolioValuationSnapshot,
        positions: list[PortfolioPositionValuation],
        performance: PortfolioPerformanceSummary | None,
        recent_journal_entries: list[PortfolioDecisionJournalEntry],
        related_skill_ids: list,
    ) -> PortfolioRiskAssessment: ...


class RuleBasedPortfolioFeedbackPolicy:
    """portfolio-feedback-v1: deterministic educational risk/diversification feedback.

    Overall `risk_level` is the unweighted average of whichever
    component risk scores are available for this valuation (position
    concentration, sector concentration, `1 - diversification_score`,
    drawdown risk, volatility risk), then banded:
        >= 0.70  -> VERY_HIGH
        >= 0.50  -> HIGH
        >= 0.25  -> MODERATE
        otherwise -> LOW
    """

    policy_version = FEEDBACK_VERSION

    def assess(
        self,
        *,
        portfolio: VirtualPortfolio,
        snapshot: PortfolioValuationSnapshot,
        positions: list[PortfolioPositionValuation],
        performance: PortfolioPerformanceSummary | None,
        recent_journal_entries: list[PortfolioDecisionJournalEntry],
        related_skill_ids: list,
    ) -> PortfolioRiskAssessment:
        feedback: list[str] = []
        codes: list[PortfolioFeedbackCode] = []

        drawdown_risk_score = None
        volatility_risk_score = None
        turnover_risk_score = None

        self._assess_position_concentration(snapshot, feedback, codes)
        self._assess_sector_concentration(snapshot, feedback, codes)
        self._assess_diversification(snapshot, feedback, codes)
        self._assess_cash_allocation(snapshot, feedback, codes)

        if performance is not None:
            drawdown_risk_score = self._assess_drawdown(performance, feedback, codes)
            volatility_risk_score = self._assess_volatility(performance, feedback, codes)
            turnover_risk_score = self._assess_turnover(performance, feedback, codes)

        if portfolio.benchmark_security_id is None:
            feedback.append(
                "No benchmark is configured for this portfolio, so relative performance cannot be shown."
            )
            codes.append(PortfolioFeedbackCode.BENCHMARK_NOT_CONFIGURED)

        self._assess_journal_quality(recent_journal_entries, feedback, codes)

        risk_level = self._classify_risk_level(
            position_concentration_score=snapshot.largest_position_weight,
            sector_concentration_score=snapshot.largest_sector_weight,
            diversification_score=snapshot.diversification_score,
            drawdown_risk_score=drawdown_risk_score,
            volatility_risk_score=volatility_risk_score,
        )

        summary = (
            f"This portfolio holds {snapshot.position_count} position(s) with a "
            f"{risk_level.value.lower()} overall risk profile based on concentration, "
            "diversification, drawdown, and volatility."
        )

        return PortfolioRiskAssessment(
            portfolio_id=portfolio.portfolio_id,
            snapshot_id=snapshot.snapshot_id,
            risk_level=risk_level,
            feedback_codes=codes,
            position_concentration_score=snapshot.largest_position_weight,
            sector_concentration_score=snapshot.largest_sector_weight,
            diversification_score=snapshot.diversification_score,
            drawdown_risk_score=drawdown_risk_score,
            volatility_risk_score=volatility_risk_score,
            turnover_risk_score=turnover_risk_score,
            summary=summary,
            educational_feedback=feedback,
            related_skill_ids=list(related_skill_ids),
            policy_version=self.policy_version,
        )

    # -- individual rules ---------------------------------------------------------

    def _assess_position_concentration(
        self,
        snapshot: PortfolioValuationSnapshot,
        feedback: list[str],
        codes: list[PortfolioFeedbackCode],
    ) -> None:
        weight = snapshot.largest_position_weight
        percentage = weight * 100
        if weight >= _POSITION_VERY_HIGH:
            feedback.append(
                f"Your largest position represents {percentage:.0f}% of the portfolio - a very high "
                "concentration."
            )
            codes.append(PortfolioFeedbackCode.POSITION_CONCENTRATION)
        elif weight >= _POSITION_HIGH:
            feedback.append(
                f"Your largest position represents {percentage:.0f}% of the portfolio - a high "
                "concentration."
            )
            codes.append(PortfolioFeedbackCode.POSITION_CONCENTRATION)
        elif weight >= _POSITION_MODERATE:
            feedback.append(
                f"Your largest position represents {percentage:.0f}% of the portfolio - a moderate "
                "concentration."
            )
            codes.append(PortfolioFeedbackCode.POSITION_CONCENTRATION)

    def _assess_sector_concentration(
        self,
        snapshot: PortfolioValuationSnapshot,
        feedback: list[str],
        codes: list[PortfolioFeedbackCode],
    ) -> None:
        weight = snapshot.largest_sector_weight
        if weight is None:
            return
        percentage = weight * 100
        if weight >= _SECTOR_VERY_HIGH:
            feedback.append(f"Most of the portfolio ({percentage:.0f}%) is exposed to one sector.")
            codes.append(PortfolioFeedbackCode.SECTOR_CONCENTRATION)
        elif weight >= _SECTOR_HIGH:
            feedback.append(f"A large share of the portfolio ({percentage:.0f}%) is exposed to one sector.")
            codes.append(PortfolioFeedbackCode.SECTOR_CONCENTRATION)
        elif weight >= _SECTOR_MODERATE:
            feedback.append(
                f"A moderate share of the portfolio ({percentage:.0f}%) is exposed to one sector."
            )
            codes.append(PortfolioFeedbackCode.SECTOR_CONCENTRATION)

    def _assess_diversification(
        self,
        snapshot: PortfolioValuationSnapshot,
        feedback: list[str],
        codes: list[PortfolioFeedbackCode],
    ) -> None:
        if (
            snapshot.position_count < _MIN_DIVERSIFIED_POSITIONS
            or snapshot.diversification_score < _LOW_DIVERSIFICATION_SCORE
        ):
            feedback.append(
                f"This portfolio holds {snapshot.position_count} position(s), which limits "
                "diversification."
            )
            codes.append(PortfolioFeedbackCode.LIMITED_DIVERSIFICATION)
        elif snapshot.diversification_score >= _BROAD_DIVERSIFICATION_SCORE:
            feedback.append(
                f"This portfolio is broadly diversified across {snapshot.position_count} positions."
            )
            codes.append(PortfolioFeedbackCode.BROAD_DIVERSIFICATION)

    def _assess_cash_allocation(
        self,
        snapshot: PortfolioValuationSnapshot,
        feedback: list[str],
        codes: list[PortfolioFeedbackCode],
    ) -> None:
        if snapshot.cash_weight >= _HIGH_CASH_WEIGHT:
            percentage = snapshot.cash_weight * 100
            feedback.append(
                f"{percentage:.0f}% of the portfolio is held in cash. High cash allocation is not "
                "automatically good or bad - it changes your risk and return exposure."
            )
            codes.append(PortfolioFeedbackCode.HIGH_CASH_ALLOCATION)

    def _assess_drawdown(
        self,
        performance: PortfolioPerformanceSummary,
        feedback: list[str],
        codes: list[PortfolioFeedbackCode],
    ) -> float | None:
        drawdown = performance.maximum_drawdown
        if drawdown is None:
            return None
        percentage = abs(drawdown) * 100
        if drawdown <= _LARGE_DRAWDOWN:
            feedback.append(f"The portfolio experienced a {percentage:.0f}% historical drawdown.")
            codes.append(PortfolioFeedbackCode.LARGE_DRAWDOWN)
        elif drawdown <= _HIGH_DRAWDOWN:
            feedback.append(f"The portfolio experienced a {percentage:.0f}% historical drawdown.")
            codes.append(PortfolioFeedbackCode.LARGE_DRAWDOWN)
        return min(1.0, abs(drawdown))

    def _assess_volatility(
        self,
        performance: PortfolioPerformanceSummary,
        feedback: list[str],
        codes: list[PortfolioFeedbackCode],
    ) -> float | None:
        volatility = performance.annualized_volatility
        if volatility is None:
            return None
        if volatility >= _HIGH_VOLATILITY:
            feedback.append(
                f"The portfolio's annualized volatility ({volatility * 100:.0f}%) has been high."
            )
            codes.append(PortfolioFeedbackCode.HIGH_VOLATILITY)
        return min(1.0, volatility)

    def _assess_turnover(
        self,
        performance: PortfolioPerformanceSummary,
        feedback: list[str],
        codes: list[PortfolioFeedbackCode],
    ) -> float:
        turnover = performance.turnover_ratio
        if turnover >= _HIGH_TURNOVER:
            feedback.append("High turnover increased simulated transaction costs.")
            codes.append(PortfolioFeedbackCode.HIGH_TURNOVER)
        elif turnover < _LOW_TURNOVER:
            feedback.append("Turnover has been low, keeping simulated transaction costs down.")
            codes.append(PortfolioFeedbackCode.LOW_TURNOVER)
        return min(1.0, turnover / _HIGH_TURNOVER)

    def _assess_journal_quality(
        self,
        recent_journal_entries: list[PortfolioDecisionJournalEntry],
        feedback: list[str],
        codes: list[PortfolioFeedbackCode],
    ) -> None:
        if not recent_journal_entries:
            return

        missing_horizon = any(entry.expected_horizon_days is None for entry in recent_journal_entries)
        missing_risks = any(not entry.risk_tags for entry in recent_journal_entries)
        overconfident = any(
            entry.confidence in _HIGH_CONFIDENCE_LEVELS and not entry.risk_tags
            for entry in recent_journal_entries
        )

        if missing_horizon:
            feedback.append(
                "This decision was made without documenting an expected time horizon."
            )
            codes.append(PortfolioFeedbackCode.HORIZON_NOT_DOCUMENTED)
        if missing_risks:
            feedback.append("This decision was made without documenting any risks.")
            codes.append(PortfolioFeedbackCode.RISK_NOT_DOCUMENTED)
        if overconfident:
            feedback.append(
                "This decision was made with high confidence but without documenting major risks."
            )
            codes.append(PortfolioFeedbackCode.OVERCONFIDENT_DECISION)
        if not missing_horizon and not missing_risks and not overconfident:
            feedback.append(
                "Recent decisions documented a clear rationale, time horizon, and risks - good practice."
            )
            codes.append(PortfolioFeedbackCode.DECISION_RATIONALE_DOCUMENTED)

    def _classify_risk_level(
        self,
        *,
        position_concentration_score: float,
        sector_concentration_score: float | None,
        diversification_score: float,
        drawdown_risk_score: float | None,
        volatility_risk_score: float | None,
    ) -> PortfolioRiskLevel:
        components = [position_concentration_score, 1.0 - diversification_score]
        if sector_concentration_score is not None:
            components.append(sector_concentration_score)
        if drawdown_risk_score is not None:
            components.append(drawdown_risk_score)
        if volatility_risk_score is not None:
            components.append(volatility_risk_score)

        overall = sum(components) / len(components)
        if overall >= 0.70:
            return PortfolioRiskLevel.VERY_HIGH
        if overall >= 0.50:
            return PortfolioRiskLevel.HIGH
        if overall >= 0.25:
            return PortfolioRiskLevel.MODERATE
        return PortfolioRiskLevel.LOW
