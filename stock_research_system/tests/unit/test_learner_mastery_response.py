"""The learner-facing mastery contract: a canonical skill name travels
with every mastery row, `financial_skills` stays its only source, and no
schema change was needed to get it there.
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from stock_research_core.api.schemas.learners import DashboardResponse, SkillMasteryResponse
from stock_research_core.application.learning.models import SkillMasterySummary
from stock_research_core.application.learning.ports import MasteryRepositoryPort
from stock_research_core.domain.learning.enums import MasteryLevel
from stock_research_core.domain.learning.models import SkillMastery
from stock_research_core.infrastructure.database.orm.skill_mastery import SkillMasteryORM

_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"

#: The Alembic head at the point this dashboard work started. The skill
#: name already lived on `financial_skills`, so nothing here needed a
#: schema change - a new head would mean one was added.
_EXPECTED_MIGRATION_HEAD = "0012_live_research_domain"


def _mastery(skill_id) -> SkillMastery:
    return SkillMastery(
        learner_id=uuid4(),
        skill_id=skill_id,
        mastery_score=0.87,
        mastery_level=MasteryLevel.PROFICIENT,
        correct_attempts=7,
        total_attempts=8,
        calculation_version="mastery-v1",
    )


def test_from_summary_returns_the_name_of_the_matching_skill() -> None:
    compound_interest_id = uuid4()
    summary = SkillMasterySummary(
        mastery=_mastery(compound_interest_id),
        skill_name="Compound Interest",
        skill_code="COMPOUND_INTEREST",
    )

    response = SkillMasteryResponse.from_summary(summary)

    assert response.skill_id == compound_interest_id
    assert response.skill_name == "Compound Interest"
    assert response.skill_code == "COMPOUND_INTEREST"
    assert response.mastery_score == 0.87
    assert response.mastery_level is MasteryLevel.PROFICIENT


def test_each_response_keeps_its_own_skill_name_when_several_are_mapped() -> None:
    stocks_id, bonds_id = uuid4(), uuid4()
    summaries = [
        SkillMasterySummary(mastery=_mastery(stocks_id), skill_name="Stocks", skill_code="STOCKS"),
        SkillMasterySummary(mastery=_mastery(bonds_id), skill_name="Bonds", skill_code="BONDS"),
    ]

    responses = [SkillMasteryResponse.from_summary(summary) for summary in summaries]

    assert {(r.skill_id, r.skill_name) for r in responses} == {
        (stocks_id, "Stocks"),
        (bonds_id, "Bonds"),
    }


def test_missing_curriculum_metadata_leaves_the_name_empty_rather_than_leaking_the_id() -> None:
    orphaned_id = uuid4()
    summary = SkillMasterySummary(mastery=_mastery(orphaned_id))

    response = SkillMasteryResponse.from_summary(summary)

    assert response.skill_name is None
    assert response.skill_code is None
    assert response.skill_id == orphaned_id
    serialized = response.model_dump(mode="json")
    assert serialized["skill_name"] is None
    assert str(orphaned_id) not in str(serialized["skill_name"])


def test_from_domain_never_invents_a_name() -> None:
    response = SkillMasteryResponse.from_domain(_mastery(uuid4()))

    assert response.skill_name is None
    assert response.skill_code is None


def test_response_exposes_only_the_skill_name_and_code_from_the_curriculum() -> None:
    exposed = set(SkillMasteryResponse.model_fields)

    assert {"skill_name", "skill_code"} <= exposed
    # Authoring metadata (descriptions, difficulty, activation state) stays
    # out of a learner-facing progress row.
    assert exposed.isdisjoint({"description", "skill_description", "difficulty", "active", "category"})


def test_dashboard_response_reuses_the_same_enriched_mastery_schema() -> None:
    assert DashboardResponse.model_fields["skill_mastery"].annotation == list[SkillMasteryResponse]


def test_mastery_row_never_stores_its_own_copy_of_the_display_name() -> None:
    """`Skill` owns the name; duplicating it onto `skill_mastery` would be
    a second source of truth (and the migration this change avoided)."""
    columns = set(SkillMasteryORM.__table__.columns.keys())

    assert columns.isdisjoint({"skill_name", "name", "skill_code", "code", "title", "label"})


def test_mastery_port_offers_a_bulk_enriched_lookup() -> None:
    assert hasattr(MasteryRepositoryPort, "list_for_learner_with_skill")


def test_no_database_migration_was_added() -> None:
    revisions: set[str] = set()
    down_revisions: set[str] = set()
    for migration in _MIGRATIONS_DIR.glob("*.py"):
        source = migration.read_text(encoding="utf-8")
        revision = re.search(r"^revision(?::\s*str)?\s*=\s*[\"']([^\"']+)[\"']", source, re.MULTILINE)
        down_revision = re.search(
            r"^down_revision(?::\s*[^=]+)?\s*=\s*[\"']([^\"']+)[\"']", source, re.MULTILINE
        )
        if revision:
            revisions.add(revision.group(1))
        if down_revision:
            down_revisions.add(down_revision.group(1))

    assert revisions - down_revisions == {_EXPECTED_MIGRATION_HEAD}
