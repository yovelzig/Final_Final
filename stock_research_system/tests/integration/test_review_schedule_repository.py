"""PostgreSQL integration tests: ReviewScheduleRepository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from stock_research_core.domain.adaptive_learning.enums import ReviewScheduleStatus
from stock_research_core.domain.adaptive_learning.models import SkillReviewSchedule
from stock_research_core.domain.learning.enums import DifficultyLevel, FinancialSkillCategory
from stock_research_core.domain.learning.models import LearnerProfile, Skill

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _seed_learner_and_skill(uow_factory) -> tuple[LearnerProfile, Skill]:
    from uuid import uuid4

    learner = LearnerProfile(display_name="Learner")
    skill = Skill(
        code=f"MONEY_BASICS_{uuid4().hex[:8].upper()}",
        name="Money Basics",
        description="desc",
        category=FinancialSkillCategory.MONEY_BASICS,
        difficulty=DifficultyLevel.BEGINNER,
    )
    async with uow_factory() as uow:
        stored_learner = await uow.learners.create(learner)
        stored_skill = await uow.curriculum.upsert_skill(skill)
        await uow.commit()
    return stored_learner, stored_skill


async def test_review_schedule_upsert_is_idempotent(uow_factory) -> None:
    learner, skill = await _seed_learner_and_skill(uow_factory)
    schedule = SkillReviewSchedule(
        learner_id=learner.learner_id, skill_id=skill.skill_id,
        status=ReviewScheduleStatus.SCHEDULED, next_review_at=NOW + timedelta(days=1),
        review_interval_days=1, ease_factor=2.0, calculation_version="review-schedule-v1",
    )

    async with uow_factory() as uow:
        first = await uow.review_schedules.upsert(schedule)
        await uow.commit()

    updated = schedule.model_copy(update={"review_interval_days": 3, "ease_factor": 2.1})
    async with uow_factory() as uow:
        second = await uow.review_schedules.upsert(updated)
        await uow.commit()

    assert first.schedule_id == second.schedule_id
    assert second.review_interval_days == 3
    assert second.ease_factor == pytest.approx(2.1)

    async with uow_factory() as uow:
        all_for_learner = await uow.review_schedules.list_for_learner(learner.learner_id)
    assert len(all_for_learner) == 1


async def test_review_schedule_get_returns_none_when_missing(uow_factory) -> None:
    learner, skill = await _seed_learner_and_skill(uow_factory)
    async with uow_factory() as uow:
        result = await uow.review_schedules.get(learner.learner_id, skill.skill_id)
    assert result is None


async def test_review_schedule_list_due(uow_factory) -> None:
    learner, skill_due = await _seed_learner_and_skill(uow_factory)
    _learner2, skill_future = await _seed_learner_and_skill(uow_factory)

    due_schedule = SkillReviewSchedule(
        learner_id=learner.learner_id, skill_id=skill_due.skill_id,
        status=ReviewScheduleStatus.SCHEDULED, next_review_at=NOW - timedelta(days=1),
        review_interval_days=1, ease_factor=2.0, calculation_version="review-schedule-v1",
    )
    future_schedule = SkillReviewSchedule(
        learner_id=learner.learner_id, skill_id=skill_future.skill_id,
        status=ReviewScheduleStatus.SCHEDULED, next_review_at=NOW + timedelta(days=30),
        review_interval_days=30, ease_factor=2.0, calculation_version="review-schedule-v1",
    )

    async with uow_factory() as uow:
        await uow.review_schedules.upsert(due_schedule)
        await uow.review_schedules.upsert(future_schedule)
        await uow.commit()

    async with uow_factory() as uow:
        due = await uow.review_schedules.list_due(learner.learner_id, NOW)

    assert {s.skill_id for s in due} == {skill_due.skill_id}
