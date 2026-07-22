"""PostgreSQL integration tests: `PortfolioRiskRepository`."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.enums import DifficultyLevel, FinancialSkillCategory
from stock_research_core.domain.learning.models import LearnerProfile, Skill
from stock_research_core.domain.models import Security
from stock_research_core.domain.virtual_portfolio.enums import PortfolioFeedbackCode, PortfolioRiskLevel
from stock_research_core.domain.virtual_portfolio.models import PortfolioRiskAssessment, VirtualPortfolio

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _seed_portfolio(uow_factory):
    learner = LearnerProfile(display_name="Learner")
    async with uow_factory() as uow:
        stored_learner = await uow.learners.create(learner)
        portfolio = VirtualPortfolio(
            learner_id=stored_learner.learner_id, name="P", initial_cash=10_000.0, cash_balance=10_000.0,
            simulation_start_at=NOW, current_simulation_at=NOW, portfolio_version="virtual-portfolio-v1",
        )
        stored_portfolio = await uow.virtual_portfolios.create(portfolio)
        await uow.commit()
    return stored_portfolio


def _assessment(portfolio_id, snapshot_id, related_skill_ids, **overrides) -> PortfolioRiskAssessment:
    defaults: dict = dict(
        portfolio_id=portfolio_id, snapshot_id=snapshot_id, risk_level=PortfolioRiskLevel.MODERATE,
        feedback_codes=[PortfolioFeedbackCode.POSITION_CONCENTRATION],
        position_concentration_score=0.4, diversification_score=0.6, summary="A summary.",
        educational_feedback=["Feedback line."], related_skill_ids=related_skill_ids,
        policy_version="portfolio-feedback-v1",
    )
    defaults.update(overrides)
    return PortfolioRiskAssessment(**defaults)


async def test_upsert_is_idempotent_for_same_snapshot_and_version(uow_factory) -> None:
    portfolio = await _seed_portfolio(uow_factory)
    snapshot_id = uuid4()
    assessment = _assessment(portfolio.portfolio_id, snapshot_id, [])

    async with uow_factory() as uow:
        first = await uow.portfolio_risk.upsert(assessment)
        await uow.commit()

    updated = assessment.model_copy(update={"risk_level": PortfolioRiskLevel.HIGH})
    async with uow_factory() as uow:
        second = await uow.portfolio_risk.upsert(updated)
        await uow.commit()

    assert first.assessment_id == second.assessment_id
    assert second.risk_level == PortfolioRiskLevel.HIGH


async def test_upsert_replaces_feedback_codes_and_skills(uow_factory) -> None:
    portfolio = await _seed_portfolio(uow_factory)
    skill = Skill(
        code=f"SKILL_{uuid4().hex[:8].upper()}", name="Diversification", description="desc",
        category=FinancialSkillCategory.DIVERSIFICATION, difficulty=DifficultyLevel.BEGINNER,
    )
    async with uow_factory() as uow:
        stored_skill = await uow.curriculum.upsert_skill(skill)
        await uow.commit()

    snapshot_id = uuid4()
    assessment = _assessment(
        portfolio.portfolio_id, snapshot_id, [stored_skill.skill_id],
        feedback_codes=[PortfolioFeedbackCode.POSITION_CONCENTRATION, PortfolioFeedbackCode.HIGH_CASH_ALLOCATION],
    )
    async with uow_factory() as uow:
        await uow.portfolio_risk.upsert(assessment)
        await uow.commit()

    updated = assessment.model_copy(update={"feedback_codes": [PortfolioFeedbackCode.BROAD_DIVERSIFICATION]})
    async with uow_factory() as uow:
        result = await uow.portfolio_risk.upsert(updated)
        await uow.commit()

    assert result.feedback_codes == [PortfolioFeedbackCode.BROAD_DIVERSIFICATION]
    assert result.related_skill_ids == [stored_skill.skill_id]


async def test_get_by_snapshot_and_policy_version(uow_factory) -> None:
    portfolio = await _seed_portfolio(uow_factory)
    snapshot_id = uuid4()
    assessment = _assessment(portfolio.portfolio_id, snapshot_id, [])
    async with uow_factory() as uow:
        await uow.portfolio_risk.upsert(assessment)
        await uow.commit()

    async with uow_factory() as uow:
        found = await uow.portfolio_risk.get_by_snapshot(snapshot_id, "portfolio-feedback-v1")
        missing = await uow.portfolio_risk.get_by_snapshot(snapshot_id, "some-other-version")

    assert found is not None
    assert missing is None


async def test_get_latest_returns_most_recently_calculated(uow_factory) -> None:
    portfolio = await _seed_portfolio(uow_factory)
    first = _assessment(portfolio.portfolio_id, uuid4(), [], calculated_at=NOW)
    from datetime import timedelta

    second = _assessment(portfolio.portfolio_id, uuid4(), [], calculated_at=NOW + timedelta(days=1))

    async with uow_factory() as uow:
        await uow.portfolio_risk.upsert(first)
        await uow.portfolio_risk.upsert(second)
        await uow.commit()

    async with uow_factory() as uow:
        latest = await uow.portfolio_risk.get_latest(portfolio.portfolio_id)

    assert latest is not None
    assert latest.assessment_id == second.assessment_id
