"""`/api/v1/learners/me/mastery` and `/dashboard` over HTTP: every row a
learner reads carries the canonical `financial_skills` name, and only
their own rows.
"""

from __future__ import annotations

import uuid

import pytest

from stock_research_core.domain.learning.enums import (
    DifficultyLevel,
    FinancialSkillCategory,
    MasteryLevel,
)
from stock_research_core.domain.learning.models import Skill, SkillMastery
from tests.integration.conftest import register_account

pytestmark = pytest.mark.integration

_SEEDED_SKILLS = [
    ("COMPOUND_INTEREST", "Compound Interest", FinancialSkillCategory.COMPOUND_INTEREST),
    ("DIVERSIFICATION", "Diversification", FinancialSkillCategory.DIVERSIFICATION),
    ("STOCKS", "Stocks", FinancialSkillCategory.STOCKS),
]


def _email() -> str:
    return f"skills-{uuid.uuid4().hex[:10]}@example.com"


async def _seed_skills(uow_factory) -> dict[str, Skill]:
    skills = {
        code: Skill(
            code=code,
            name=name,
            description=f"Canonical curriculum entry for {name}.",
            category=category,
            difficulty=DifficultyLevel.BEGINNER,
        )
        for code, name, category in _SEEDED_SKILLS
    }
    async with uow_factory() as uow:
        for skill in skills.values():
            await uow.curriculum.upsert_skill(skill)
        await uow.commit()
    return skills


async def _record_mastery(uow_factory, *, learner_id: uuid.UUID, skill: Skill, score: float) -> None:
    async with uow_factory() as uow:
        await uow.mastery.upsert(
            SkillMastery(
                learner_id=learner_id,
                skill_id=skill.skill_id,
                mastery_score=score,
                mastery_level=MasteryLevel.PROFICIENT,
                correct_attempts=7,
                total_attempts=8,
                calculation_version="mastery-v1",
            )
        )
        await uow.commit()


async def test_mastery_list_returns_the_canonical_name_of_each_skill(api_client, uow_factory) -> None:
    account = await register_account(api_client, email=_email())
    learner_id = uuid.UUID(account["learner"]["learner_id"])
    headers = {"Authorization": f"Bearer {account['tokens']['access_token']}"}
    skills = await _seed_skills(uow_factory)
    for skill in skills.values():
        await _record_mastery(uow_factory, learner_id=learner_id, skill=skill, score=0.87)

    response = await api_client.get("/api/v1/learners/me/mastery", headers=headers)

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == len(skills)
    by_skill_id = {item["skill_id"]: item for item in items}
    for skill in skills.values():
        item = by_skill_id[str(skill.skill_id)]
        assert item["skill_name"] == skill.name
        assert item["skill_code"] == skill.code
    # Alphabetical by canonical name, so paging over the list is stable.
    assert [item["skill_name"] for item in items] == ["Compound Interest", "Diversification", "Stocks"]


async def test_mastery_response_never_needs_a_client_side_skill_lookup(api_client, uow_factory) -> None:
    account = await register_account(api_client, email=_email())
    learner_id = uuid.UUID(account["learner"]["learner_id"])
    headers = {"Authorization": f"Bearer {account['tokens']['access_token']}"}
    skills = await _seed_skills(uow_factory)
    await _record_mastery(uow_factory, learner_id=learner_id, skill=skills["STOCKS"], score=0.49)

    item = (await api_client.get("/api/v1/learners/me/mastery", headers=headers)).json()["items"][0]

    assert set(item) >= {"skill_id", "skill_name", "skill_code", "mastery_score", "mastery_level"}
    # No curriculum authoring metadata rides along.
    assert "description" not in item
    assert "difficulty" not in item


async def test_dashboard_skill_mastery_is_enriched_the_same_way(api_client, uow_factory) -> None:
    account = await register_account(api_client, email=_email())
    learner_id = uuid.UUID(account["learner"]["learner_id"])
    headers = {"Authorization": f"Bearer {account['tokens']['access_token']}"}
    skills = await _seed_skills(uow_factory)
    await _record_mastery(uow_factory, learner_id=learner_id, skill=skills["DIVERSIFICATION"], score=1.0)

    body = (await api_client.get("/api/v1/learners/me/dashboard", headers=headers)).json()

    assert [row["skill_name"] for row in body["skill_mastery"]] == ["Diversification"]
    assert body["skill_mastery"][0]["skill_id"] == str(skills["DIVERSIFICATION"].skill_id)


async def test_a_learner_only_ever_sees_their_own_mastery(api_client, uow_factory) -> None:
    skills = await _seed_skills(uow_factory)
    owner = await register_account(api_client, email=_email())
    other = await register_account(api_client, email=_email())
    await _record_mastery(
        uow_factory,
        learner_id=uuid.UUID(owner["learner"]["learner_id"]),
        skill=skills["STOCKS"],
        score=0.87,
    )

    owner_items = (
        await api_client.get(
            "/api/v1/learners/me/mastery",
            headers={"Authorization": f"Bearer {owner['tokens']['access_token']}"},
        )
    ).json()["items"]
    other_items = (
        await api_client.get(
            "/api/v1/learners/me/mastery",
            headers={"Authorization": f"Bearer {other['tokens']['access_token']}"},
        )
    ).json()["items"]

    assert [item["skill_name"] for item in owner_items] == ["Stocks"]
    assert other_items == []


async def test_enriched_mastery_still_requires_authentication(api_client) -> None:
    for path in ("/api/v1/learners/me/mastery", "/api/v1/learners/me/dashboard"):
        assert (await api_client.get(path)).status_code == 401, path
