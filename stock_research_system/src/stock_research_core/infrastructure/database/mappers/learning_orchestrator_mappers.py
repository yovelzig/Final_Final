"""Maps ORM rows to Phase 12 learning-orchestrator domain models."""

from __future__ import annotations

from pydantic import ValidationError

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.domain.learning_orchestrator.models import (
    LearningActionProposal,
    LearningOrchestratorEvent,
    LearningOrchestratorRun,
    LearningOrchestratorThread,
)
from stock_research_core.infrastructure.database.orm.learning_orchestrator_action_proposal import (
    LearningOrchestratorActionProposalORM,
)
from stock_research_core.infrastructure.database.orm.learning_orchestrator_event import LearningOrchestratorEventORM
from stock_research_core.infrastructure.database.orm.learning_orchestrator_run import LearningOrchestratorRunORM
from stock_research_core.infrastructure.database.orm.learning_orchestrator_thread import (
    LearningOrchestratorThreadORM,
)


def learning_orchestrator_thread_orm_to_domain(row: LearningOrchestratorThreadORM) -> LearningOrchestratorThread:
    try:
        return LearningOrchestratorThread(
            thread_id=row.thread_id, learner_id=row.learner_id, status=row.status, title=row.title,
            current_context_type=row.current_context_type, linked_tutor_conversation_id=row.linked_tutor_conversation_id,
            graph_name=row.graph_name, graph_version=row.graph_version, created_at=row.created_at,
            updated_at=row.updated_at, closed_at=row.closed_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored learning-orchestrator-thread row '{row.thread_id}' could not be mapped."
        ) from exc


def learning_orchestrator_run_orm_to_domain(row: LearningOrchestratorRunORM) -> LearningOrchestratorRun:
    try:
        return LearningOrchestratorRun(
            run_id=row.run_id, thread_id=row.thread_id, learner_id=row.learner_id,
            input_message_id=row.input_message_id, output_tutor_answer_id=row.output_tutor_answer_id,
            status=row.status, intent=row.intent, route=row.route, idempotency_key=row.idempotency_key,
            correlation_id=row.correlation_id, step_count=row.step_count, maximum_steps=row.maximum_steps,
            started_at=row.started_at, waiting_at=row.waiting_at, completed_at=row.completed_at,
            cancelled_at=row.cancelled_at, failure_code=row.failure_code, failure_message=row.failure_message,
            graph_version=row.graph_version, created_at=row.created_at, updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(f"Stored learning-orchestrator-run row '{row.run_id}' could not be mapped.") from exc


def learning_orchestrator_event_orm_to_domain(row: LearningOrchestratorEventORM) -> LearningOrchestratorEvent:
    try:
        return LearningOrchestratorEvent(
            event_id=row.event_id, run_id=row.run_id, thread_id=row.thread_id, event_type=row.event_type,
            sequence_number=row.sequence_number, learner_message=row.learner_message,
            metadata=row.event_metadata or {}, created_at=row.created_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(f"Stored learning-orchestrator-event row '{row.event_id}' could not be mapped.") from exc


def learning_orchestrator_action_proposal_orm_to_domain(
    row: LearningOrchestratorActionProposalORM,
) -> LearningActionProposal:
    try:
        return LearningActionProposal(
            proposal_id=row.proposal_id, run_id=row.run_id, thread_id=row.thread_id, learner_id=row.learner_id,
            action_type=row.action_type, status=row.status, title=row.title, description=row.description,
            reason=row.reason, parameters=row.parameters or {}, result_reference=row.result_reference,
            approval_decision=row.approval_decision, approval_payload=row.approval_payload,
            idempotency_key=row.idempotency_key, proposed_at=row.proposed_at, approved_at=row.approved_at,
            rejected_at=row.rejected_at, executed_at=row.executed_at, completed_at=row.completed_at,
            expires_at=row.expires_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored learning-orchestrator-action-proposal row '{row.proposal_id}' could not be mapped."
        ) from exc
