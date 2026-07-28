"""PostgreSQL integration tests: MasteryRepository and MisconceptionRepository."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from stock_research_core.domain.learning.enums import (
    DifficultyLevel,
    FinancialSkillCategory,
    MasteryLevel,
    MisconceptionStatus,
)
from stock_research_core.domain.learning.models import LearnerProfile, Misconception, Skill, SkillMastery

pytestmark = pytest.mark.integration


async def _seed_learner_and_skill(uow_factory):
    learner = LearnerProfile(display_name="Amit")
    skill = Skill(
        code="RISK_AND_RETURN",
        name="Risk and Return",
        description="desc",
        category=FinancialSkillCategory.RISK_AND_RETURN,
        difficulty=DifficultyLevel.BEGINNER,
    )
    async with uow_factory() as uow:
        await uow.learners.create(learner)
        await uow.curriculum.upsert_skill(skill)
        await uow.commit()
    return learner, skill


async def test_mastery_upsert_is_idempotent(uow_factory) -> None:
    learner, skill = await _seed_learner_and_skill(uow_factory)
    mastery = SkillMastery(
        learner_id=learner.learner_id,
        skill_id=skill.skill_id,
        mastery_score=0.5,
        mastery_level=MasteryLevel.DEVELOPING,
        correct_attempts=1,
        total_attempts=2,
        calculation_version="mastery-v1",
    )

    async with uow_factory() as uow:
        first = await uow.mastery.upsert(mastery)
        await uow.commit()

    updated = mastery.model_copy(update={"mastery_score": 0.6, "total_attempts": 3})
    async with uow_factory() as uow:
        second = await uow.mastery.upsert(updated)
        await uow.commit()

    assert first.mastery_id == second.mastery_id
    assert second.mastery_score == pytest.approx(0.6)

    async with uow_factory() as uow:
        all_for_learner = await uow.mastery.list_for_learner(learner.learner_id)
    assert len(all_for_learner) == 1


async def _seed_learner_and_skills(uow_factory, names: list[tuple[str, str]]):
    learner = LearnerProfile(display_name="Noa")
    skills = [
        Skill(
            code=code,
            name=name,
            description=f"Canonical curriculum entry for {name}.",
            category=FinancialSkillCategory.RISK_AND_RETURN,
            difficulty=DifficultyLevel.BEGINNER,
        )
        for code, name in names
    ]
    async with uow_factory() as uow:
        await uow.learners.create(learner)
        for skill in skills:
            await uow.curriculum.upsert_skill(skill)
        await uow.commit()
    return learner, skills


async def _record_mastery(uow_factory, learner, skills) -> None:
    async with uow_factory() as uow:
        for index, skill in enumerate(skills):
            await uow.mastery.upsert(
                SkillMastery(
                    learner_id=learner.learner_id,
                    skill_id=skill.skill_id,
                    mastery_score=0.5,
                    mastery_level=MasteryLevel.DEVELOPING,
                    correct_attempts=index,
                    total_attempts=index + 1,
                    calculation_version="mastery-v1",
                )
            )
        await uow.commit()


async def test_enriched_mastery_list_carries_each_skills_canonical_name(uow_factory) -> None:
    learner, skills = await _seed_learner_and_skills(
        uow_factory, [("STOCKS", "Stocks"), ("BONDS", "Bonds"), ("DIVERSIFICATION", "Diversification")]
    )
    await _record_mastery(uow_factory, learner, skills)

    async with uow_factory() as uow:
        summaries = await uow.mastery.list_for_learner_with_skill(learner.learner_id)

    names_by_skill_id = {skill.skill_id: skill.name for skill in skills}
    assert len(summaries) == 3
    for summary in summaries:
        assert summary.skill_name == names_by_skill_id[summary.mastery.skill_id]
    assert [summary.skill_code for summary in summaries] == ["BONDS", "DIVERSIFICATION", "STOCKS"]


async def test_enriched_mastery_list_scopes_to_one_learner(uow_factory) -> None:
    learner, skills = await _seed_learner_and_skills(uow_factory, [("STOCKS", "Stocks")])
    other_learner = LearnerProfile(display_name="Other")
    async with uow_factory() as uow:
        await uow.learners.create(other_learner)
        await uow.commit()
    await _record_mastery(uow_factory, learner, skills)

    async with uow_factory() as uow:
        summaries = await uow.mastery.list_for_learner_with_skill(other_learner.learner_id)

    assert summaries == []


async def test_enriched_mastery_list_stays_one_query_as_skills_grow(uow_factory, test_engine) -> None:
    """Resolving names must never become a per-row `get_skill` lookup."""
    learner, skills = await _seed_learner_and_skills(
        uow_factory,
        [
            ("STOCKS", "Stocks"),
            ("BONDS", "Bonds"),
            ("DIVERSIFICATION", "Diversification"),
            ("INFLATION", "Inflation"),
            ("MONEY_BASICS", "Money Basics"),
        ],
    )
    await _record_mastery(uow_factory, learner, skills)

    executed: list[str] = []

    def _record_statement(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        executed.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", _record_statement)
    try:
        async with uow_factory() as uow:
            summaries = await uow.mastery.list_for_learner_with_skill(learner.learner_id)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _record_statement)

    assert len(summaries) == 5
    assert all(summary.skill_name for summary in summaries)
    assert len([statement for statement in executed if "financial_skills" in statement]) == 1
    assert len([statement for statement in executed if "FROM skill_mastery" in statement]) == 1


async def test_mastery_get_returns_none_when_missing(uow_factory) -> None:
    learner, skill = await _seed_learner_and_skill(uow_factory)
    async with uow_factory() as uow:
        result = await uow.mastery.get(learner.learner_id, skill.skill_id)
    assert result is None


async def test_misconception_repository_upsert_and_list_active(uow_factory) -> None:
    learner, skill = await _seed_learner_and_skill(uow_factory)
    now = datetime.now(timezone.utc)
    misconception = Misconception(
        learner_id=learner.learner_id,
        skill_id=skill.skill_id,
        code="GUARANTEED_RETURN_MYTH",
        description="Believes diversification guarantees profit.",
        status=MisconceptionStatus.ACTIVE,
        confidence_score=0.8,
        first_detected_at=now,
        last_detected_at=now,
        detector_version="misconception-v1",
    )

    async with uow_factory() as uow:
        await uow.misconceptions.upsert(misconception)
        await uow.commit()

    async with uow_factory() as uow:
        active = await uow.misconceptions.list_active(learner.learner_id)
    assert len(active) == 1
    assert active[0].code == "GUARANTEED_RETURN_MYTH"


async def test_misconception_repository_resolve(uow_factory) -> None:
    learner, skill = await _seed_learner_and_skill(uow_factory)
    now = datetime.now(timezone.utc)
    misconception = Misconception(
        learner_id=learner.learner_id,
        skill_id=skill.skill_id,
        code="GUARANTEED_RETURN_MYTH",
        description="Believes diversification guarantees profit.",
        status=MisconceptionStatus.ACTIVE,
        confidence_score=0.8,
        first_detected_at=now,
        last_detected_at=now,
        detector_version="misconception-v1",
    )
    async with uow_factory() as uow:
        await uow.misconceptions.upsert(misconception)
        await uow.commit()

    resolved_at = datetime.now(timezone.utc)
    async with uow_factory() as uow:
        resolved = await uow.misconceptions.resolve(misconception.misconception_id, resolved_at)
        await uow.commit()

    assert resolved.status == MisconceptionStatus.RESOLVED
    assert resolved.resolved_at == resolved_at

    async with uow_factory() as uow:
        active = await uow.misconceptions.list_active(learner.learner_id)
    assert active == []
