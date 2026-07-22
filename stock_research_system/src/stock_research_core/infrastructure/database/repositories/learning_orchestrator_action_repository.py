"""SQLAlchemy repository for `LearningActionProposal` persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.learning_orchestrator.enums import LearningActionProposalStatus
from stock_research_core.domain.learning_orchestrator.models import LearningActionProposal
from stock_research_core.domain.operations.sanitization import find_sensitive_keys
from stock_research_core.infrastructure.database.mappers.learning_orchestrator_mappers import (
    learning_orchestrator_action_proposal_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.learning_orchestrator_action_proposal import (
    LearningOrchestratorActionProposalORM,
)


def _ensure_safe_json(data: dict[str, Any] | None, *, field_name: str) -> None:
    if data is None:
        return
    sensitive = find_sensitive_keys(data)
    if sensitive:
        raise PersistenceError(f"Refusing to persist {field_name} containing sensitive fields: {sensitive}")


class SqlAlchemyLearningOrchestratorActionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, proposal: LearningActionProposal) -> LearningActionProposal:
        row = LearningOrchestratorActionProposalORM(
            proposal_id=proposal.proposal_id, run_id=proposal.run_id, thread_id=proposal.thread_id,
            learner_id=proposal.learner_id, action_type=proposal.action_type.value, status=proposal.status.value,
            title=proposal.title, description=proposal.description, reason=proposal.reason,
            parameters=proposal.parameters, result_reference=proposal.result_reference,
            approval_decision=proposal.approval_decision.value if proposal.approval_decision else None,
            approval_payload=proposal.approval_payload, idempotency_key=proposal.idempotency_key,
            expires_at=proposal.expires_at,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise PersistenceError(
                f"Could not create action proposal: idempotency key '{proposal.idempotency_key}' already used on this run."
            ) from exc
        return learning_orchestrator_action_proposal_orm_to_domain(row)

    async def get_by_id(self, proposal_id: UUID) -> LearningActionProposal | None:
        row = await self._session.get(LearningOrchestratorActionProposalORM, proposal_id)
        return learning_orchestrator_action_proposal_orm_to_domain(row) if row is not None else None

    async def get_for_update(self, proposal_id: UUID) -> LearningActionProposal | None:
        statement = (
            select(LearningOrchestratorActionProposalORM)
            .where(LearningOrchestratorActionProposalORM.proposal_id == proposal_id)
            .with_for_update()
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return learning_orchestrator_action_proposal_orm_to_domain(row) if row is not None else None

    async def get_by_idempotency_key(self, *, run_id: UUID, idempotency_key: str) -> LearningActionProposal | None:
        statement = select(LearningOrchestratorActionProposalORM).where(
            LearningOrchestratorActionProposalORM.run_id == run_id,
            LearningOrchestratorActionProposalORM.idempotency_key == idempotency_key,
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return learning_orchestrator_action_proposal_orm_to_domain(row) if row is not None else None

    async def mark_waiting_for_approval(self, proposal_id: UUID) -> LearningActionProposal:
        row = await self._get_or_raise(proposal_id)
        row.status = LearningActionProposalStatus.WAITING_FOR_APPROVAL.value
        await self._session.flush()
        return learning_orchestrator_action_proposal_orm_to_domain(row)

    async def mark_approved(
        self, proposal_id: UUID, *, approved_at: datetime, approval_payload: dict[str, Any] | None
    ) -> LearningActionProposal:
        _ensure_safe_json(approval_payload, field_name="approval_payload")
        row = await self._get_or_raise(proposal_id)
        row.status = LearningActionProposalStatus.APPROVED.value
        row.approval_decision = "APPROVE"
        row.approved_at = approved_at
        row.approval_payload = approval_payload
        await self._session.flush()
        return learning_orchestrator_action_proposal_orm_to_domain(row)

    async def mark_rejected(self, proposal_id: UUID, *, rejected_at: datetime) -> LearningActionProposal:
        row = await self._get_or_raise(proposal_id)
        row.status = LearningActionProposalStatus.REJECTED.value
        row.approval_decision = "REJECT"
        row.rejected_at = rejected_at
        await self._session.flush()
        return learning_orchestrator_action_proposal_orm_to_domain(row)

    async def mark_edited(
        self, proposal_id: UUID, *, parameters: dict[str, Any], approval_payload: dict[str, Any] | None
    ) -> LearningActionProposal:
        _ensure_safe_json(parameters, field_name="parameters")
        _ensure_safe_json(approval_payload, field_name="approval_payload")
        row = await self._get_or_raise(proposal_id)
        row.status = LearningActionProposalStatus.EDITED.value
        row.approval_decision = "EDIT"
        row.parameters = parameters
        row.approval_payload = approval_payload
        await self._session.flush()
        return learning_orchestrator_action_proposal_orm_to_domain(row)

    async def mark_executing(self, proposal_id: UUID, *, executed_at: datetime) -> LearningActionProposal:
        row = await self._get_or_raise(proposal_id)
        row.status = LearningActionProposalStatus.EXECUTING.value
        row.executed_at = executed_at
        await self._session.flush()
        return learning_orchestrator_action_proposal_orm_to_domain(row)

    async def mark_succeeded(
        self, proposal_id: UUID, *, completed_at: datetime, result_reference: dict[str, Any]
    ) -> LearningActionProposal:
        _ensure_safe_json(result_reference, field_name="result_reference")
        row = await self._get_or_raise(proposal_id)
        row.status = LearningActionProposalStatus.SUCCEEDED.value
        row.completed_at = completed_at
        row.result_reference = result_reference
        await self._session.flush()
        return learning_orchestrator_action_proposal_orm_to_domain(row)

    async def mark_failed(self, proposal_id: UUID, *, completed_at: datetime) -> LearningActionProposal:
        row = await self._get_or_raise(proposal_id)
        row.status = LearningActionProposalStatus.FAILED.value
        row.completed_at = completed_at
        await self._session.flush()
        return learning_orchestrator_action_proposal_orm_to_domain(row)

    async def list_for_run(self, run_id: UUID) -> list[LearningActionProposal]:
        statement = (
            select(LearningOrchestratorActionProposalORM)
            .where(LearningOrchestratorActionProposalORM.run_id == run_id)
            .order_by(LearningOrchestratorActionProposalORM.proposed_at.asc())
        )
        result = await self._session.execute(statement)
        return [learning_orchestrator_action_proposal_orm_to_domain(row) for row in result.scalars().all()]

    async def _get_or_raise(self, proposal_id: UUID) -> LearningOrchestratorActionProposalORM:
        row = await self._session.get(LearningOrchestratorActionProposalORM, proposal_id)
        if row is None:
            raise PersistenceError(f"No action proposal found with id '{proposal_id}'.")
        return row
