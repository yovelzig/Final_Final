"""The single, validated map from `BackgroundJobType` to everything the
operations engine needs to create, route, execute, and retry a job of
that type.

`BackgroundJobRegistry` fails fast at construction time (never at first
use) when any job type is missing a parameter model, a handler, a queue,
a task name, or a valid retry policy - see `_REQUIRED_JOB_TYPES`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from stock_research_core.application.operations.models import (
    CurriculumKnowledgeRefreshParameters,
    JobParameters,
    KnowledgeGapSummaryParameters,
    KnowledgeReembedParameters,
    LearningQualityAggregationParameters,
    LocalDocumentIngestionParameters,
    PortfolioBatchValuationParameters,
    PortfolioValuationParameters,
    QualityBaselineComparisonParameters,
    RagasQualityEvaluationParameters,
    RetrievalEvaluationParameters,
    SecurityMarketRefreshParameters,
    SystemMaintenanceParameters,
    TrackedMarketRefreshParameters,
)
from stock_research_core.application.operations.ports import JobHandlerPort
from stock_research_core.domain.operations.enums import BackgroundJobType, JobTriggerSource

# -- retry policy -----------------------------------------------


@dataclass(frozen=True)
class RetryDecision:
    retryable: bool
    error_code: str
    delay_seconds: int | None = None


class FixedScheduleRetryPolicy:
    """Retries only exceptions in `retryable_exceptions`, at the fixed
    per-attempt delay schedule in `delays_seconds` (the last entry repeats
    if `maximum_attempts` exceeds the schedule's length)."""

    def __init__(
        self,
        *,
        maximum_attempts: int,
        delays_seconds: tuple[int, ...],
        retryable_exceptions: tuple[type[Exception], ...],
    ) -> None:
        if maximum_attempts < 1:
            raise ValueError("maximum_attempts must be at least 1")
        self.maximum_attempts = maximum_attempts
        self.delays_seconds = delays_seconds
        self.retryable_exceptions = retryable_exceptions

    def classify(self, exception: Exception, *, attempt_number: int) -> RetryDecision:
        error_code = type(exception).__name__
        if not isinstance(exception, self.retryable_exceptions):
            return RetryDecision(retryable=False, error_code=error_code)
        if attempt_number >= self.maximum_attempts:
            return RetryDecision(retryable=False, error_code=error_code)
        if not self.delays_seconds:
            return RetryDecision(retryable=False, error_code=error_code)
        index = min(attempt_number - 1, len(self.delays_seconds) - 1)
        return RetryDecision(retryable=True, error_code=error_code, delay_seconds=self.delays_seconds[index])


class ExponentialBackoffRetryPolicy:
    """Capped exponential backoff with injectable (deterministic-by-default)
    jitter, for transient infrastructure failures (Redis, transient
    connection errors) rather than provider-specific failures."""

    def __init__(
        self,
        *,
        maximum_attempts: int,
        base_delay_seconds: int,
        cap_seconds: int,
        retryable_exceptions: tuple[type[Exception], ...],
        jitter: Callable[[int], int] | None = None,
    ) -> None:
        if maximum_attempts < 1:
            raise ValueError("maximum_attempts must be at least 1")
        self.maximum_attempts = maximum_attempts
        self.base_delay_seconds = base_delay_seconds
        self.cap_seconds = cap_seconds
        self.retryable_exceptions = retryable_exceptions
        # Identity by default: deterministic and injectable for tests. A
        # real jitter function is wired in by infrastructure composition
        # if randomized backoff is desired in production.
        self._jitter = jitter or (lambda value: value)

    def classify(self, exception: Exception, *, attempt_number: int) -> RetryDecision:
        error_code = type(exception).__name__
        if not isinstance(exception, self.retryable_exceptions):
            return RetryDecision(retryable=False, error_code=error_code)
        if attempt_number >= self.maximum_attempts:
            return RetryDecision(retryable=False, error_code=error_code)
        raw_delay = min(self.base_delay_seconds * (2 ** (attempt_number - 1)), self.cap_seconds)
        return RetryDecision(retryable=True, error_code=error_code, delay_seconds=self._jitter(raw_delay))


class NeverRetryPolicy:
    """Always non-retryable - for job types where a re-run should only ever
    be triggered by the next scheduled invocation, never an automatic retry."""

    maximum_attempts = 1

    def classify(self, exception: Exception, *, attempt_number: int) -> RetryDecision:
        return RetryDecision(retryable=False, error_code=type(exception).__name__)


# -- registry -----------------------------------------------


@dataclass(frozen=True)
class JobRegistryEntry:
    job_type: BackgroundJobType
    parameter_model: type[JobParameters]
    queue_name: str
    task_name: str
    handler: JobHandlerPort
    maximum_attempts: int
    retry_policy: object  # FixedScheduleRetryPolicy | ExponentialBackoffRetryPolicy | NeverRetryPolicy
    time_limit_seconds: int
    resource_key_builder: Callable[[JobParameters], str | None]
    allowed_trigger_sources: frozenset[JobTriggerSource]

    def parse_parameters(self, raw_parameters: dict) -> JobParameters:
        return self.parameter_model.model_validate(raw_parameters)


class BackgroundJobRegistry:
    """Fails fast at construction: every `BackgroundJobType` must resolve
    to exactly one, fully-specified `JobRegistryEntry`."""

    def __init__(self, entries: list[JobRegistryEntry]) -> None:
        by_type: dict[BackgroundJobType, JobRegistryEntry] = {}
        for entry in entries:
            if entry.job_type in by_type:
                raise ValueError(f"Job type {entry.job_type} is registered more than once.")
            if entry.handler is None:
                raise ValueError(f"Job type {entry.job_type} has no handler.")
            if not entry.queue_name:
                raise ValueError(f"Job type {entry.job_type} has an empty queue name.")
            if not entry.task_name:
                raise ValueError(f"Job type {entry.job_type} has an empty task name.")
            if entry.maximum_attempts < 1 or entry.maximum_attempts > 20:
                raise ValueError(f"Job type {entry.job_type} has an invalid maximum_attempts.")
            if entry.time_limit_seconds <= 0:
                raise ValueError(f"Job type {entry.job_type} has an invalid time_limit_seconds.")
            if not entry.allowed_trigger_sources:
                raise ValueError(f"Job type {entry.job_type} allows no trigger sources.")
            by_type[entry.job_type] = entry

        missing = [job_type for job_type in BackgroundJobType if job_type not in by_type]
        if missing:
            raise ValueError(f"Missing job registry entries for: {[m.value for m in missing]}")

        self._by_type = by_type

    def get(self, job_type: BackgroundJobType) -> JobRegistryEntry:
        try:
            return self._by_type[job_type]
        except KeyError as exc:
            raise ValueError(f"No registry entry for job type {job_type}.") from exc

    def all_queue_names(self) -> frozenset[str]:
        return frozenset(entry.queue_name for entry in self._by_type.values())


# -- default retry-policy construction -----------------------------------------------
#
# Concrete exception classes are imported lazily inside this function
# (rather than at module scope) to keep this module free of a hard
# dependency ordering surprise: the exceptions themselves live in
# `application.exceptions`, imported normally below - there is no cycle,
# this is simply grouped near its one call site for readability.

_ALL_TRIGGER_SOURCES = frozenset(JobTriggerSource)
_NO_N8N_OR_API = frozenset(
    {JobTriggerSource.ADMIN_CLI, JobTriggerSource.SYSTEM, JobTriggerSource.RETRY}
)


def build_default_retry_policies() -> dict[BackgroundJobType, object]:
    from stock_research_core.application.exceptions import (
        EmbeddingProviderError,
        ProviderRequestError,
        TransientInfrastructureError,
    )

    market_transient = FixedScheduleRetryPolicy(
        maximum_attempts=4,
        delays_seconds=(30, 120, 600),
        retryable_exceptions=(ProviderRequestError, TransientInfrastructureError),
    )
    infra_transient = ExponentialBackoffRetryPolicy(
        maximum_attempts=5,
        base_delay_seconds=5,
        cap_seconds=120,
        retryable_exceptions=(TransientInfrastructureError,),
    )
    embedding_transient = FixedScheduleRetryPolicy(
        maximum_attempts=3,
        delays_seconds=(30, 120),
        retryable_exceptions=(EmbeddingProviderError, TransientInfrastructureError),
    )
    return {
        BackgroundJobType.TRACKED_MARKET_REFRESH: market_transient,
        BackgroundJobType.SECURITY_MARKET_REFRESH: market_transient,
        BackgroundJobType.PORTFOLIO_VALUATION: infra_transient,
        BackgroundJobType.PORTFOLIO_BATCH_VALUATION: infra_transient,
        BackgroundJobType.CURRICULUM_KNOWLEDGE_REFRESH: embedding_transient,
        BackgroundJobType.LOCAL_DOCUMENT_INGESTION: embedding_transient,
        BackgroundJobType.KNOWLEDGE_REEMBED: embedding_transient,
        BackgroundJobType.RETRIEVAL_EVALUATION: infra_transient,
        BackgroundJobType.KNOWLEDGE_GAP_SUMMARY: infra_transient,
        BackgroundJobType.SYSTEM_MAINTENANCE: NeverRetryPolicy(),
        # Retries only transient evaluator-provider/infrastructure errors -
        # an invalid dataset or unapproved suite is never retryable.
        BackgroundJobType.RAGAS_QUALITY_EVALUATION: infra_transient,
        BackgroundJobType.LEARNING_QUALITY_AGGREGATION: infra_transient,
        BackgroundJobType.QUALITY_BASELINE_COMPARISON: infra_transient,
    }


#: `(queue_name, time_limit_seconds, maximum_attempts, allowed_trigger_sources)` per job type.
_JOB_TYPE_CONFIG: dict[BackgroundJobType, tuple[str, int, int, frozenset[JobTriggerSource]]] = {
    BackgroundJobType.TRACKED_MARKET_REFRESH: ("finquest.market", 1800, 4, _ALL_TRIGGER_SOURCES),
    BackgroundJobType.SECURITY_MARKET_REFRESH: ("finquest.market", 300, 4, _ALL_TRIGGER_SOURCES),
    BackgroundJobType.PORTFOLIO_VALUATION: ("finquest.portfolio", 120, 5, _ALL_TRIGGER_SOURCES),
    BackgroundJobType.PORTFOLIO_BATCH_VALUATION: ("finquest.portfolio", 900, 5, _ALL_TRIGGER_SOURCES),
    BackgroundJobType.CURRICULUM_KNOWLEDGE_REFRESH: ("finquest.knowledge", 1800, 3, _ALL_TRIGGER_SOURCES),
    BackgroundJobType.LOCAL_DOCUMENT_INGESTION: ("finquest.knowledge", 300, 3, _ALL_TRIGGER_SOURCES),
    BackgroundJobType.KNOWLEDGE_REEMBED: ("finquest.knowledge", 900, 3, _ALL_TRIGGER_SOURCES),
    BackgroundJobType.RETRIEVAL_EVALUATION: ("finquest.evaluation", 600, 5, _ALL_TRIGGER_SOURCES),
    BackgroundJobType.KNOWLEDGE_GAP_SUMMARY: ("finquest.knowledge", 120, 5, _ALL_TRIGGER_SOURCES),
    BackgroundJobType.SYSTEM_MAINTENANCE: ("finquest.default", 120, 1, _NO_N8N_OR_API),
    BackgroundJobType.RAGAS_QUALITY_EVALUATION: ("finquest.evaluation", 1800, 3, _ALL_TRIGGER_SOURCES),
    BackgroundJobType.LEARNING_QUALITY_AGGREGATION: ("finquest.evaluation", 900, 3, _ALL_TRIGGER_SOURCES),
    BackgroundJobType.QUALITY_BASELINE_COMPARISON: ("finquest.evaluation", 300, 3, _ALL_TRIGGER_SOURCES),
}

_JOB_TYPE_PARAMETER_MODEL: dict[BackgroundJobType, type[JobParameters]] = {
    BackgroundJobType.TRACKED_MARKET_REFRESH: TrackedMarketRefreshParameters,
    BackgroundJobType.SECURITY_MARKET_REFRESH: SecurityMarketRefreshParameters,
    BackgroundJobType.PORTFOLIO_VALUATION: PortfolioValuationParameters,
    BackgroundJobType.PORTFOLIO_BATCH_VALUATION: PortfolioBatchValuationParameters,
    BackgroundJobType.CURRICULUM_KNOWLEDGE_REFRESH: CurriculumKnowledgeRefreshParameters,
    BackgroundJobType.LOCAL_DOCUMENT_INGESTION: LocalDocumentIngestionParameters,
    BackgroundJobType.KNOWLEDGE_REEMBED: KnowledgeReembedParameters,
    BackgroundJobType.RETRIEVAL_EVALUATION: RetrievalEvaluationParameters,
    BackgroundJobType.KNOWLEDGE_GAP_SUMMARY: KnowledgeGapSummaryParameters,
    BackgroundJobType.SYSTEM_MAINTENANCE: SystemMaintenanceParameters,
    BackgroundJobType.RAGAS_QUALITY_EVALUATION: RagasQualityEvaluationParameters,
    BackgroundJobType.LEARNING_QUALITY_AGGREGATION: LearningQualityAggregationParameters,
    BackgroundJobType.QUALITY_BASELINE_COMPARISON: QualityBaselineComparisonParameters,
}


def _default_resource_key_builder(job_type: BackgroundJobType) -> Callable[[JobParameters], str | None]:
    from stock_research_core.application.operations.locking import (
        knowledge_curriculum_refresh_resource_key,
        knowledge_document_reembed_resource_key,
        market_security_resource_key,
        portfolio_valuation_resource_key,
        retrieval_evaluation_resource_key,
    )

    def _no_lock(_: JobParameters) -> str | None:
        return None

    if job_type == BackgroundJobType.SECURITY_MARKET_REFRESH:
        def _builder(parameters: JobParameters) -> str | None:
            assert isinstance(parameters, SecurityMarketRefreshParameters)
            # Locked per-ticker/source/interval; the security_id is not yet
            # known at parameter-validation time, so the ticker stands in
            # for it here - still a stable, conflict-preventing key.
            return market_security_resource_key(
                security_id=parameters.ticker, source_name=parameters.source_name, interval=parameters.interval
            )

        return _builder
    if job_type == BackgroundJobType.PORTFOLIO_VALUATION:
        def _builder(parameters: JobParameters) -> str | None:
            assert isinstance(parameters, PortfolioValuationParameters)
            return portfolio_valuation_resource_key(portfolio_id=parameters.portfolio_id, as_of=parameters.as_of)

        return _builder
    if job_type in (BackgroundJobType.CURRICULUM_KNOWLEDGE_REFRESH, BackgroundJobType.LOCAL_DOCUMENT_INGESTION):
        return lambda _parameters: knowledge_curriculum_refresh_resource_key()
    if job_type == BackgroundJobType.KNOWLEDGE_REEMBED:
        def _builder(parameters: JobParameters) -> str | None:
            assert isinstance(parameters, KnowledgeReembedParameters)
            if parameters.document_ids and len(parameters.document_ids) == 1:
                return knowledge_document_reembed_resource_key(document_id=parameters.document_ids[0])
            return knowledge_curriculum_refresh_resource_key()

        return _builder
    if job_type == BackgroundJobType.RETRIEVAL_EVALUATION:
        def _builder(parameters: JobParameters) -> str | None:
            assert isinstance(parameters, RetrievalEvaluationParameters)
            return retrieval_evaluation_resource_key(dataset=parameters.evaluation_dataset, top_k=parameters.top_k)

        return _builder
    return _no_lock


def build_default_registry(handlers: dict[BackgroundJobType, JobHandlerPort]) -> BackgroundJobRegistry:
    """Wire the fixed job-type configuration together with worker-supplied
    handler instances (constructed by a composition root, since handlers
    hold real adapters such as the market-data provider or embedding
    provider)."""
    retry_policies = build_default_retry_policies()
    entries: list[JobRegistryEntry] = []
    for job_type in BackgroundJobType:
        if job_type not in handlers:
            raise ValueError(f"No handler supplied for job type {job_type}.")
        queue_name, time_limit_seconds, maximum_attempts, allowed_trigger_sources = _JOB_TYPE_CONFIG[job_type]
        entries.append(
            JobRegistryEntry(
                job_type=job_type,
                parameter_model=_JOB_TYPE_PARAMETER_MODEL[job_type],
                queue_name=queue_name,
                task_name=f"finquest.{job_type.value.lower()}",
                handler=handlers[job_type],
                maximum_attempts=maximum_attempts,
                retry_policy=retry_policies[job_type],
                time_limit_seconds=time_limit_seconds,
                resource_key_builder=_default_resource_key_builder(job_type),
                allowed_trigger_sources=allowed_trigger_sources,
            )
        )
    return BackgroundJobRegistry(entries)
