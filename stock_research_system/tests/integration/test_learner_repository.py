"""PostgreSQL integration tests: LearnerRepository."""

from __future__ import annotations

from uuid import uuid4

import pytest

from stock_research_core.domain.learning.enums import DifficultyLevel
from stock_research_core.domain.learning.models import LearnerProfile

pytestmark = pytest.mark.integration


async def test_learner_repository_round_trip(uow_factory) -> None:
    learner = LearnerProfile(
        display_name="Amit",
        preferred_language="en",
        financial_experience_level=DifficultyLevel.BEGINNER,
        daily_goal_minutes=15,
    )

    async with uow_factory() as uow:
        created = await uow.learners.create(learner)
        await uow.commit()

    assert created.learner_id == learner.learner_id
    assert created.preferred_language == "en"

    async with uow_factory() as uow:
        fetched = await uow.learners.get(learner.learner_id)
    assert fetched is not None
    assert fetched.display_name == "Amit"


async def test_learner_repository_update(uow_factory) -> None:
    learner = LearnerProfile(display_name="Amit")
    async with uow_factory() as uow:
        await uow.learners.create(learner)
        await uow.commit()

    updated = learner.model_copy(update={"display_name": "Amit Cohen", "daily_goal_minutes": 30})
    async with uow_factory() as uow:
        result = await uow.learners.update(updated)
        await uow.commit()

    assert result.display_name == "Amit Cohen"
    assert result.daily_goal_minutes == 30

    async with uow_factory() as uow:
        fetched = await uow.learners.get(learner.learner_id)
    assert fetched is not None
    assert fetched.display_name == "Amit Cohen"


async def test_learner_repository_set_active(uow_factory) -> None:
    learner = LearnerProfile(display_name="Amit")
    async with uow_factory() as uow:
        await uow.learners.create(learner)
        await uow.commit()

    async with uow_factory() as uow:
        result = await uow.learners.set_active(learner.learner_id, False)
        await uow.commit()

    assert result.active is False

    async with uow_factory() as uow:
        fetched = await uow.learners.get(learner.learner_id)
    assert fetched is not None
    assert fetched.active is False


async def test_learner_repository_get_returns_none_when_missing(uow_factory) -> None:
    async with uow_factory() as uow:
        result = await uow.learners.get(uuid4())
    assert result is None
