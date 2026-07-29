"""Enumerations for the FinQuest background-jobs and n8n-integration engine
(Phase 11: production operations).

This module has no knowledge of any infrastructure (databases, queues,
HTTP frameworks, Celery, Redis, orchestration engines, etc.).
"""

from enum import StrEnum


class BackgroundJobType(StrEnum):
    TRACKED_MARKET_REFRESH = "TRACKED_MARKET_REFRESH"
    SECURITY_MARKET_REFRESH = "SECURITY_MARKET_REFRESH"
    PORTFOLIO_VALUATION = "PORTFOLIO_VALUATION"
    PORTFOLIO_BATCH_VALUATION = "PORTFOLIO_BATCH_VALUATION"
    CURRICULUM_KNOWLEDGE_REFRESH = "CURRICULUM_KNOWLEDGE_REFRESH"
    LOCAL_DOCUMENT_INGESTION = "LOCAL_DOCUMENT_INGESTION"
    KNOWLEDGE_REEMBED = "KNOWLEDGE_REEMBED"
    RETRIEVAL_EVALUATION = "RETRIEVAL_EVALUATION"
    KNOWLEDGE_GAP_SUMMARY = "KNOWLEDGE_GAP_SUMMARY"
    SYSTEM_MAINTENANCE = "SYSTEM_MAINTENANCE"
    RAGAS_QUALITY_EVALUATION = "RAGAS_QUALITY_EVALUATION"
    LEARNING_QUALITY_AGGREGATION = "LEARNING_QUALITY_AGGREGATION"
    QUALITY_BASELINE_COMPARISON = "QUALITY_BASELINE_COMPARISON"
    LIVE_RESEARCH_RUN_EXECUTION = "LIVE_RESEARCH_RUN_EXECUTION"
    #: Internal-only (spec G2D2 section 12): resumes a Coach run that was
    #: paused `WAITING_FOR_RESEARCH` once its linked `LIVE_RESEARCH_RUN_
    #: EXECUTION` job reaches a terminal status. Never triggerable by API,
    #: ADMIN_CLI, or N8N - only SYSTEM (see `job_registry.py`).
    COACH_RESEARCH_RESUME = "COACH_RESEARCH_RESUME"


class BackgroundJobStatus(StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


#: Statuses from which a job will never transition again.
TERMINAL_JOB_STATUSES: frozenset[BackgroundJobStatus] = frozenset(
    {
        BackgroundJobStatus.SUCCEEDED,
        BackgroundJobStatus.FAILED,
        BackgroundJobStatus.CANCELLED,
        BackgroundJobStatus.SKIPPED,
    }
)


class BackgroundJobPriority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class JobTriggerSource(StrEnum):
    API = "API"
    ADMIN_CLI = "ADMIN_CLI"
    N8N = "N8N"
    SYSTEM = "SYSTEM"
    RETRY = "RETRY"


class JobAttemptStatus(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    CANCELLED = "CANCELLED"


#: Attempt statuses that require a `completed_at` timestamp.
TERMINAL_ATTEMPT_STATUSES: frozenset[JobAttemptStatus] = frozenset(
    {
        JobAttemptStatus.SUCCEEDED,
        JobAttemptStatus.FAILED,
        JobAttemptStatus.RETRYABLE_FAILURE,
        JobAttemptStatus.CANCELLED,
    }
)


class JobEventType(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    STARTED = "STARTED"
    PROGRESS_UPDATED = "PROGRESS_UPDATED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"
    LOCK_NOT_ACQUIRED = "LOCK_NOT_ACQUIRED"


class IntegrationClientStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    REVOKED = "REVOKED"


class IntegrationRequestStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
