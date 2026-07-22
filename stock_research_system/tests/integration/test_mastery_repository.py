"""PostgreSQL integration tests: MasteryRepository and MisconceptionRepository."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

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
