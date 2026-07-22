"""Maps ORM rows to Phase 11 operations domain models."""

from __future__ import annotations

from pydantic import ValidationError

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.domain.operations.enums import BackgroundJobType
from stock_research_core.domain.operations.models import (
    BackgroundJob,
    BackgroundJobAttempt,
    BackgroundJobEvent,
    IntegrationClient,
    IntegrationRequest,
)
from stock_research_core.infrastructure.database.orm.background_job import BackgroundJobORM
from stock_research_core.infrastructure.database.orm.background_job_attempt import BackgroundJobAttemptORM
from stock_research_core.infrastructure.database.orm.background_job_event import BackgroundJobEventORM
from stock_research_core.infrastructure.database.orm.integration_client import IntegrationClientORM
from stock_research_core.infrastructure.database.orm.integration_request import IntegrationRequestORM


def background_job_orm_to_domain(row: BackgroundJobORM) -> BackgroundJob:
    try:
        return BackgroundJob(
            job_id=row.job_id,
            job_type=row.job_type,
            status=row.status,
            priority=row.priority,
            trigger_source=row.trigger_source,
            requested_by_account_id=row.requested_by_account_id,
            requested_by_integration_id=row.requested_by_integration_id,
            idempotency_key=row.idempotency_key,
            resource_key=row.resource_key,
            parameters=row.parameters or {},
            result_summary=row.result_summary,
            progress_current=row.progress_current,
            progress_total=row.progress_total,
            progress_message=row.progress_message,
            attempt_count=row.attempt_count,
            maximum_attempts=row.maximum_attempts,
            queue_name=row.queue_name,
            task_name=row.task_name,
            task_id=row.task_id,
            available_at=row.available_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            cancelled_at=row.cancelled_at,
            job_version=row.job_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(f"Stored background-job row '{row.job_id}' could not be mapped to a domain BackgroundJob.") from exc


def background_job_attempt_orm_to_domain(row: BackgroundJobAttemptORM) -> BackgroundJobAttempt:
    try:
        return BackgroundJobAttempt(
            attempt_id=row.attempt_id,
            job_id=row.job_id,
            attempt_number=row.attempt_number,
            status=row.status,
            worker_name=row.worker_name,
            celery_task_id=row.celery_task_id,
            started_at=row.started_at,
            completed_at=row.completed_at,
            error_type=row.error_type,
            error_code=row.error_code,
            error_message=row.error_message,
            retry_delay_seconds=row.retry_delay_seconds,
            created_at=row.created_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(f"Stored background-job-attempt row '{row.attempt_id}' could not be mapped.") from exc


def background_job_event_orm_to_domain(row: BackgroundJobEventORM) -> BackgroundJobEvent:
    try:
        return BackgroundJobEvent(
            event_id=row.event_id,
            job_id=row.job_id,
            attempt_id=row.attempt_id,
            event_type=row.event_type,
            message=row.message,
            metadata=row.event_metadata or {},
            correlation_id=row.correlation_id,
            created_at=row.created_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(f"Stored background-job-event row '{row.event_id}' could not be mapped.") from exc


def integration_client_orm_to_domain(row: IntegrationClientORM, allowed_job_types: list[str]) -> IntegrationClient:
    try:
        return IntegrationClient(
            integration_id=row.integration_id,
            name=row.name,
            key_id=row.key_id,
            api_key_hash=row.api_key_hash,
            status=row.status,
            allowed_job_types=[BackgroundJobType(value) for value in allowed_job_types],
            created_at=row.created_at,
            updated_at=row.updated_at,
            last_used_at=row.last_used_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(f"Stored integration-client row '{row.integration_id}' could not be mapped.") from exc


def integration_request_orm_to_domain(row: IntegrationRequestORM) -> IntegrationRequest:
    try:
        return IntegrationRequest(
            request_id=row.request_id,
            integration_id=row.integration_id,
            external_request_id=row.external_request_id,
            idempotency_key=row.idempotency_key,
            job_id=row.job_id,
            status=row.status,
            request_hash=row.request_hash,
            correlation_id=row.correlation_id,
            received_at=row.received_at,
            completed_at=row.completed_at,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(f"Stored integration-request row '{row.request_id}' could not be mapped.") from exc
