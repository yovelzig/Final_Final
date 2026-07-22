"""Unit tests for `RuleBasedPortfolioFeedbackPolicy` (portfolio-feedback-v1)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from stock_research_core.application.virtual_portfolio.feedback import RuleBasedPortfolioFeedbackPolicy
from stock_research_core.domain.virtual_portfolio.enums import (
    DecisionConfidence,
    PortfolioDecisionAction,
    PortfolioFeedbackCode,
    PortfolioRiskLevel,
)
from stock_research_core.domain.virtual_portfolio.models import (
    PortfolioDecisionJournalEntry,
    PortfolioValuationSnapshot,
    VirtualPortfolio,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
POLICY = RuleBasedPortfolioFeedbackPolicy()


def _portfolio(**overrides: object) -> VirtualPortfolio:
    defaults: dict = dict(
        learner_id=uuid4(), name="P", initial_cash=10_000.0, cash_balance=5_000.0,
        simulation_start_at=NOW, current_simulation_at=NOW, portfolio_version="virtual-portfolio-v1",
    )
    defaults.update(overrides)
    return VirtualPortfolio(**defaults)


def _snapshot(**overrides: object) -> PortfolioValuationSnapshot:
    defaults: dict = dict(
        portfolio_id=uuid4(), as_of=NOW, data_cutoff_at=NOW, cash_balance=5000.0, holdings_value=5000.0,
        total_value=10000.0, total_cost_basis=4500.0, realized_pnl=0.0, unrealized_pnl=500.0,
        net_profit=500.0, total_return=0.0, largest_position_weight=0.10, cash_weight=0.5,
        position_count=5, portfolio_hhi=0.10, diversification_score=0.8,
        valuation_version="portfolio-valuation-v1",
    )
    defaults.update(overrides)
    return PortfolioValuationSnapshot(**defaults)


def test_policy_version_is_stable() -> None:
    assert POLICY.policy_version == "portfolio-feedback-v1"


def test_very_high_position_concentration_is_flagged() -> None:
    snapshot = _snapshot(largest_position_weight=0.60)
    assessment = POLICY.assess(
        portfolio=_portfolio(), snapshot=snapshot, positions=[], performance=None,
        recent_journal_entries=[], related_skill_ids=[],
    )
    assert PortfolioFeedbackCode.POSITION_CONCENTRATION in assessment.feedback_codes


def test_high_sector_concentration_is_flagged() -> None:
    snapshot = _snapshot(largest_sector_weight=0.75)
    assessment = POLICY.assess(
        portfolio=_portfolio(), snapshot=snapshot, positions=[], performance=None,
        recent_journal_entries=[], related_skill_ids=[],
    )
    assert PortfolioFeedbackCode.SECTOR_CONCENTRATION in assessment.feedback_codes


def test_limited_diversification_flagged_for_few_positions() -> None:
    snapshot = _snapshot(position_count=1, diversification_score=0.9)
    assessment = POLICY.assess(
        portfolio=_portfolio(), snapshot=snapshot, positions=[], performance=None,
        recent_journal_entries=[], related_skill_ids=[],
    )
    assert PortfolioFeedbackCode.LIMITED_DIVERSIFICATION in assessment.feedback_codes


def test_broad_diversification_flagged() -> None:
    snapshot = _snapshot(position_count=10, diversification_score=0.85)
    assessment = POLICY.assess(
        portfolio=_portfolio(), snapshot=snapshot, positions=[], performance=None,
        recent_journal_entries=[], related_skill_ids=[],
    )
    assert PortfolioFeedbackCode.BROAD_DIVERSIFICATION in assessment.feedback_codes


def test_high_cash_allocation_is_explained_neutrally() -> None:
    snapshot = _snapshot(cash_weight=0.75)
    assessment = POLICY.assess(
        portfolio=_portfolio(), snapshot=snapshot, positions=[], performance=None,
        recent_journal_entries=[], related_skill_ids=[],
    )
    assert PortfolioFeedbackCode.HIGH_CASH_ALLOCATION in assessment.feedback_codes
    feedback_text = " ".join(assessment.educational_feedback)
    assert "not automatically good or bad" in feedback_text


def test_missing_benchmark_is_flagged() -> None:
    assessment = POLICY.assess(
        portfolio=_portfolio(benchmark_security_id=None), snapshot=_snapshot(), positions=[],
        performance=None, recent_journal_entries=[], related_skill_ids=[],
    )
    assert PortfolioFeedbackCode.BENCHMARK_NOT_CONFIGURED in assessment.feedback_codes


def test_missing_horizon_and_risks_are_flagged() -> None:
    entry = PortfolioDecisionJournalEntry(
        portfolio_id=uuid4(), learner_id=uuid4(), action=PortfolioDecisionAction.HOLD, decision_at=NOW,
        rationale="A reasonably long rationale for this decision.", confidence=DecisionConfidence.MEDIUM,
    )
    assessment = POLICY.assess(
        portfolio=_portfolio(), snapshot=_snapshot(), positions=[], performance=None,
        recent_journal_entries=[entry], related_skill_ids=[],
    )
    assert PortfolioFeedbackCode.HORIZON_NOT_DOCUMENTED in assessment.feedback_codes
    assert PortfolioFeedbackCode.RISK_NOT_DOCUMENTED in assessment.feedback_codes


def test_overconfident_decision_without_documented_risks_is_flagged() -> None:
    entry = PortfolioDecisionJournalEntry(
        portfolio_id=uuid4(), learner_id=uuid4(), action=PortfolioDecisionAction.BUY, decision_at=NOW,
        rationale="A reasonably long rationale for this decision.", confidence=DecisionConfidence.HIGH,
        expected_horizon_days=30, risk_tags=[],
    )
    assessment = POLICY.assess(
        portfolio=_portfolio(), snapshot=_snapshot(), positions=[], performance=None,
        recent_journal_entries=[entry], related_skill_ids=[],
    )
    assert PortfolioFeedbackCode.OVERCONFIDENT_DECISION in assessment.feedback_codes


def test_well_documented_decision_is_praised() -> None:
    entry = PortfolioDecisionJournalEntry(
        portfolio_id=uuid4(), learner_id=uuid4(), action=PortfolioDecisionAction.BUY, decision_at=NOW,
        rationale="A reasonably long, well thought out rationale for this decision.",
        confidence=DecisionConfidence.MEDIUM, expected_horizon_days=365, risk_tags=["concentration"],
    )
    assessment = POLICY.assess(
        portfolio=_portfolio(), snapshot=_snapshot(), positions=[], performance=None,
        recent_journal_entries=[entry], related_skill_ids=[],
    )
    assert PortfolioFeedbackCode.DECISION_RATIONALE_DOCUMENTED in assessment.feedback_codes
    assert PortfolioFeedbackCode.OVERCONFIDENT_DECISION not in assessment.feedback_codes


def test_large_drawdown_is_flagged() -> None:
    from stock_research_core.domain.virtual_portfolio.models import PortfolioPerformanceSummary

    performance = PortfolioPerformanceSummary(
        portfolio_id=uuid4(), start_at=NOW, end_at=NOW.replace(year=2027), start_value=10000, end_value=8000,
        total_return=-0.2, maximum_drawdown=-0.30, turnover_ratio=0.5, average_cash_weight=0.5,
        average_position_count=3, calculation_version="portfolio-performance-v1",
    )
    assessment = POLICY.assess(
        portfolio=_portfolio(), snapshot=_snapshot(), positions=[], performance=performance,
        recent_journal_entries=[], related_skill_ids=[],
    )
    assert PortfolioFeedbackCode.LARGE_DRAWDOWN in assessment.feedback_codes


def test_high_turnover_is_flagged() -> None:
    from stock_research_core.domain.virtual_portfolio.models import PortfolioPerformanceSummary

    performance = PortfolioPerformanceSummary(
        portfolio_id=uuid4(), start_at=NOW, end_at=NOW.replace(year=2027), start_value=10000, end_value=10500,
        total_return=0.05, turnover_ratio=2.5, average_cash_weight=0.5, average_position_count=3,
        calculation_version="portfolio-performance-v1",
    )
    assessment = POLICY.assess(
        portfolio=_portfolio(), snapshot=_snapshot(), positions=[], performance=performance,
        recent_journal_entries=[], related_skill_ids=[],
    )
    assert PortfolioFeedbackCode.HIGH_TURNOVER in assessment.feedback_codes
    feedback_text = " ".join(assessment.educational_feedback)
    assert "simulated transaction costs" in feedback_text


def test_feedback_is_english() -> None:
    assessment = POLICY.assess(
        portfolio=_portfolio(benchmark_security_id=None), snapshot=_snapshot(largest_position_weight=0.6),
        positions=[], performance=None, recent_journal_entries=[], related_skill_ids=[],
    )
    for line in assessment.educational_feedback:
        assert all(ord(char) < 128 for char in line)


def test_risk_level_classification_is_deterministic() -> None:
    snapshot = _snapshot(largest_position_weight=0.6, diversification_score=0.1)
    kwargs = dict(
        portfolio=_portfolio(), snapshot=snapshot, positions=[], performance=None,
        recent_journal_entries=[], related_skill_ids=[],
    )
    first = POLICY.assess(**kwargs)
    second = POLICY.assess(**kwargs)
    assert first.risk_level == second.risk_level
    assert first.risk_level in (PortfolioRiskLevel.HIGH, PortfolioRiskLevel.VERY_HIGH)


def test_feedback_never_mentions_a_specific_trade_instruction() -> None:
    """Feedback describes portfolio characteristics, never a buy/sell instruction."""
    assessment = POLICY.assess(
        portfolio=_portfolio(), snapshot=_snapshot(largest_position_weight=0.6), positions=[],
        performance=None, recent_journal_entries=[], related_skill_ids=[],
    )
    forbidden_phrases = ["buy ", "sell ", "will rise", "will fall", "guarantee"]
    combined = " ".join(assessment.educational_feedback).lower()
    for phrase in forbidden_phrases:
        assert phrase not in combined
