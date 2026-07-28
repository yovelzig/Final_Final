"""`SqlAlchemyMasteryRepository.list_for_learner_with_skill` resolves every
skill in one statement and degrades safely when a mastery row's skill is
gone. Driven through a stub session so the query-count and logging
behaviour is asserted without a database (the PostgreSQL-backed
counterpart lives in `tests/integration/test_mastery_repository.py`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import structlog

from stock_research_core.infrastructure.database.orm.skill_mastery import SkillMasteryORM
from stock_research_core.infrastructure.database.repositories.mastery_repository import (
    SqlAlchemyMasteryRepository,
)


def _mastery_row(skill_id: UUID, learner_id: UUID) -> SkillMasteryORM:
    return SkillMasteryORM(
        mastery_id=uuid4(),
        learner_id=learner_id,
        skill_id=skill_id,
        mastery_score=Decimal("0.8700"),
        mastery_level="PROFICIENT",
        correct_attempts=7,
        total_attempts=8,
        consecutive_correct=3,
        last_practiced_at=None,
        next_review_at=None,
        calculation_version="mastery-v1",
        # `server_default` only fills this on a real INSERT, and the ORM ->
        # domain mapper requires it.
        updated_at=datetime.now(timezone.utc),
    )


class _StubResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _StubSession:
    """Records every `execute` call so an N+1 pattern is impossible to hide."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.executed_statements: list[Any] = []

    async def execute(self, statement: Any) -> _StubResult:
        self.executed_statements.append(statement)
        return _StubResult(self._rows)


async def test_resolves_many_skills_in_a_single_statement() -> None:
    learner_id = uuid4()
    names = ["Bonds", "Compound Interest", "Diversification", "Money Basics", "Stocks"]
    rows = [(_mastery_row(uuid4(), learner_id), name, name.upper().replace(" ", "_")) for name in names]
    session = _StubSession(rows)

    summaries = await SqlAlchemyMasteryRepository(session).list_for_learner_with_skill(learner_id)

    assert len(summaries) == len(names)
    assert len(session.executed_statements) == 1


async def test_pairs_each_mastery_row_with_its_own_skill_name() -> None:
    learner_id = uuid4()
    stocks_id, bonds_id = uuid4(), uuid4()
    session = _StubSession(
        [
            (_mastery_row(bonds_id, learner_id), "Bonds", "BONDS"),
            (_mastery_row(stocks_id, learner_id), "Stocks", "STOCKS"),
        ]
    )

    summaries = await SqlAlchemyMasteryRepository(session).list_for_learner_with_skill(learner_id)

    assert [(s.mastery.skill_id, s.skill_name, s.skill_code) for s in summaries] == [
        (bonds_id, "Bonds", "BONDS"),
        (stocks_id, "Stocks", "STOCKS"),
    ]


async def test_a_mastery_row_without_curriculum_metadata_still_comes_back() -> None:
    learner_id = uuid4()
    orphaned_id = uuid4()
    session = _StubSession(
        [
            (_mastery_row(uuid4(), learner_id), "Stocks", "STOCKS"),
            (_mastery_row(orphaned_id, learner_id), None, None),
        ]
    )

    with structlog.testing.capture_logs() as logs:
        summaries = await SqlAlchemyMasteryRepository(session).list_for_learner_with_skill(learner_id)

    assert len(summaries) == 2
    orphaned = next(s for s in summaries if s.mastery.skill_id == orphaned_id)
    assert orphaned.skill_name is None
    assert orphaned.skill_code is None
    assert summaries[0].skill_name == "Stocks"

    warnings = [entry for entry in logs if entry["log_level"] == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["event"] == "skill_mastery_skill_metadata_missing"
    assert warnings[0]["missing_count"] == 1
    assert str(learner_id) not in str(warnings[0])


async def test_missing_metadata_warning_stays_bounded_for_many_orphaned_rows() -> None:
    learner_id = uuid4()
    session = _StubSession([(_mastery_row(uuid4(), learner_id), None, None) for _ in range(40)])

    with structlog.testing.capture_logs() as logs:
        summaries = await SqlAlchemyMasteryRepository(session).list_for_learner_with_skill(learner_id)

    assert len(summaries) == 40
    warnings = [entry for entry in logs if entry["log_level"] == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["missing_count"] == 40
    assert len(warnings[0]["sample_skill_ids"]) == 5


async def test_no_warning_when_every_skill_resolves() -> None:
    learner_id = uuid4()
    session = _StubSession([(_mastery_row(uuid4(), learner_id), "Stocks", "STOCKS")])

    with structlog.testing.capture_logs() as logs:
        await SqlAlchemyMasteryRepository(session).list_for_learner_with_skill(learner_id)

    assert [entry for entry in logs if entry["log_level"] == "warning"] == []
