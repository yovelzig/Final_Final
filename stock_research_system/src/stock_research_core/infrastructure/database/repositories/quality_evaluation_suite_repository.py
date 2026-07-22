"""SQLAlchemy repository for `QualityEvaluationSuite`/`QualityEvaluationCase`
persistence (Phase 13) - the two are grouped in one repository because a
case never exists independent of its suite (spec application-layer port
grouping, section 9)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.quality_evaluation.enums import QualityEvaluationCaseStatus
from stock_research_core.domain.quality_evaluation.models import QualityEvaluationCase, QualityEvaluationSuite
from stock_research_core.infrastructure.database.mappers.quality_evaluation_mappers import (
    quality_evaluation_case_orm_to_domain,
    quality_evaluation_suite_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.quality_evaluation_case import (
    QualityEvaluationCaseORM,
    QualityEvaluationCaseReferenceChunkORM,
    QualityEvaluationCaseReferenceDocumentORM,
    QualityEvaluationCaseSkillORM,
)
from stock_research_core.infrastructure.database.orm.quality_evaluation_suite import QualityEvaluationSuiteORM


class SqlAlchemyQualityEvaluationSuiteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- suites -----------------------------------------------

    async def create_suite(self, suite: QualityEvaluationSuite) -> QualityEvaluationSuite:
        row = QualityEvaluationSuiteORM(
            suite_id=suite.suite_id, code=suite.code, name=suite.name, description=suite.description,
            suite_type=suite.suite_type.value, status=suite.status.value, version=suite.version,
            language=suite.language, case_count=suite.case_count, dataset_hash=suite.dataset_hash,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise PersistenceError(f"Suite code '{suite.code}' version '{suite.version}' already exists.") from exc
        return quality_evaluation_suite_orm_to_domain(row)

    async def get_suite_by_id(self, suite_id: UUID) -> QualityEvaluationSuite | None:
        row = await self._session.get(QualityEvaluationSuiteORM, suite_id)
        return quality_evaluation_suite_orm_to_domain(row) if row is not None else None

    async def get_suite_by_code_and_version(self, *, code: str, version: str) -> QualityEvaluationSuite | None:
        statement = select(QualityEvaluationSuiteORM).where(
            QualityEvaluationSuiteORM.code == code, QualityEvaluationSuiteORM.version == version
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return quality_evaluation_suite_orm_to_domain(row) if row is not None else None

    async def list_suites(self, *, limit: int = 50, offset: int = 0) -> list[QualityEvaluationSuite]:
        statement = (
            select(QualityEvaluationSuiteORM).order_by(QualityEvaluationSuiteORM.created_at.desc())
            .limit(limit).offset(offset)
        )
        result = await self._session.execute(statement)
        return [quality_evaluation_suite_orm_to_domain(row) for row in result.scalars().all()]

    async def update_suite_status(
        self, suite_id: UUID, *, status: QualityEvaluationCaseStatus, case_count: int | None = None,
    ) -> QualityEvaluationSuite:
        row = await self._session.get(QualityEvaluationSuiteORM, suite_id)
        if row is None:
            raise PersistenceError(f"Suite '{suite_id}' not found.")
        row.status = status.value
        if case_count is not None:
            row.case_count = case_count
        await self._session.flush()
        await self._session.refresh(row)
        return quality_evaluation_suite_orm_to_domain(row)

    # -- cases -----------------------------------------------

    async def create_case(self, case: QualityEvaluationCase) -> QualityEvaluationCase:
        row = QualityEvaluationCaseORM(
            case_id=case.case_id, suite_id=case.suite_id, external_case_id=case.external_case_id,
            status=case.status.value, context_type=case.context_type.value, user_input=case.user_input,
            reference_answer=case.reference_answer, reference_contexts=list(case.reference_contexts),
            expected_guardrail_category=case.expected_guardrail_category.value if case.expected_guardrail_category else None,
            expected_refusal=case.expected_refusal, expected_fallback=case.expected_fallback,
            expected_intent=case.expected_intent.value if case.expected_intent else None,
            expected_route=case.expected_route.value if case.expected_route else None,
            expected_action_type=case.expected_action_type.value if case.expected_action_type else None,
            expected_interrupt=case.expected_interrupt, forbidden_phrases=list(case.forbidden_phrases),
            required_concepts=list(case.required_concepts), case_metadata=dict(case.metadata),
            case_version=case.case_version,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise PersistenceError(
                f"Case '{case.external_case_id}' version '{case.case_version}' already exists in this suite."
            ) from exc
        await self._replace_case_references(
            case.case_id, document_ids=case.reference_document_ids, chunk_ids=case.reference_chunk_ids,
            skill_ids=case.expected_skill_ids,
        )
        await self._session.flush()
        return await self.get_case_by_id(case.case_id)  # type: ignore[return-value]

    async def _replace_case_references(
        self, case_id: UUID, *, document_ids: list[UUID], chunk_ids: list[UUID], skill_ids: list[UUID],
    ) -> None:
        for document_id in document_ids:
            self._session.add(QualityEvaluationCaseReferenceDocumentORM(case_id=case_id, document_id=document_id))
        for chunk_id in chunk_ids:
            self._session.add(QualityEvaluationCaseReferenceChunkORM(case_id=case_id, chunk_id=chunk_id))
        for skill_id in skill_ids:
            self._session.add(QualityEvaluationCaseSkillORM(case_id=case_id, skill_id=skill_id))

    async def get_case_by_id(self, case_id: UUID) -> QualityEvaluationCase | None:
        row = await self._session.get(QualityEvaluationCaseORM, case_id)
        if row is None:
            return None
        return quality_evaluation_case_orm_to_domain(
            row,
            reference_document_ids=await self._reference_document_ids(case_id),
            reference_chunk_ids=await self._reference_chunk_ids(case_id),
            expected_skill_ids=await self._expected_skill_ids(case_id),
        )

    async def list_cases_for_suite(
        self, suite_id: UUID, *, status: QualityEvaluationCaseStatus | None = None,
    ) -> list[QualityEvaluationCase]:
        statement = select(QualityEvaluationCaseORM).where(QualityEvaluationCaseORM.suite_id == suite_id)
        if status is not None:
            statement = statement.where(QualityEvaluationCaseORM.status == status.value)
        statement = statement.order_by(QualityEvaluationCaseORM.external_case_id)
        result = await self._session.execute(statement)
        cases: list[QualityEvaluationCase] = []
        for row in result.scalars().all():
            cases.append(
                quality_evaluation_case_orm_to_domain(
                    row,
                    reference_document_ids=await self._reference_document_ids(row.case_id),
                    reference_chunk_ids=await self._reference_chunk_ids(row.case_id),
                    expected_skill_ids=await self._expected_skill_ids(row.case_id),
                )
            )
        return cases

    async def update_case_status(self, case_id: UUID, *, status: QualityEvaluationCaseStatus) -> QualityEvaluationCase:
        row = await self._session.get(QualityEvaluationCaseORM, case_id)
        if row is None:
            raise PersistenceError(f"Case '{case_id}' not found.")
        row.status = status.value
        await self._session.flush()
        await self._session.refresh(row)
        return await self.get_case_by_id(case_id)  # type: ignore[return-value]

    async def _reference_document_ids(self, case_id: UUID) -> list[UUID]:
        statement = select(QualityEvaluationCaseReferenceDocumentORM.document_id).where(
            QualityEvaluationCaseReferenceDocumentORM.case_id == case_id
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def _reference_chunk_ids(self, case_id: UUID) -> list[UUID]:
        statement = select(QualityEvaluationCaseReferenceChunkORM.chunk_id).where(
            QualityEvaluationCaseReferenceChunkORM.case_id == case_id
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def _expected_skill_ids(self, case_id: UUID) -> list[UUID]:
        statement = select(QualityEvaluationCaseSkillORM.skill_id).where(
            QualityEvaluationCaseSkillORM.case_id == case_id
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())
