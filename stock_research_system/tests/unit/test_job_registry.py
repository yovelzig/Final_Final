"""Unit tests for `BackgroundJobRegistry` and the default retry policies."""

from __future__ import annotations

import pytest

from stock_research_core.application.exceptions import (
    LiveResearchProviderAccessError,
    LiveResearchProviderRateLimitError,
    LiveResearchProviderResponseError,
    LiveResearchProviderTimeoutError,
    TransientInfrastructureError,
)
from stock_research_core.application.operations.job_registry import (
    _JOB_TYPE_CONFIG,
    BackgroundJobRegistry,
    ExponentialBackoffRetryPolicy,
    FixedScheduleRetryPolicy,
    JobRegistryEntry,
    NeverRetryPolicy,
    build_default_registry,
    build_default_retry_policies,
)
from stock_research_core.application.operations.locking import live_research_job_resource_key
from stock_research_core.application.operations.models import LiveResearchRunExecutionParameters, PortfolioValuationParameters
from stock_research_core.application.operations.ports import JobExecutionContext
from stock_research_core.domain.operations.enums import BackgroundJobType, JobTriggerSource


def _minimal_entry(job_type: BackgroundJobType, **overrides) -> JobRegistryEntry:
    fields = dict(
        job_type=job_type, parameter_model=PortfolioValuationParameters, queue_name="finquest.default",
        task_name=f"finquest.{job_type.value.lower()}", handler=object(), maximum_attempts=3,
        retry_policy=NeverRetryPolicy(), time_limit_seconds=60, resource_key_builder=lambda context, p: None,
        allowed_trigger_sources=frozenset(JobTriggerSource),
    )
    fields.update(overrides)
    return JobRegistryEntry(**fields)


def _all_entries(**overrides_by_type) -> list[JobRegistryEntry]:
    return [_minimal_entry(job_type, **overrides_by_type.get(job_type, {})) for job_type in BackgroundJobType]


class TestBackgroundJobRegistry:
    def test_fails_when_a_job_type_is_missing(self) -> None:
        entries = _all_entries()[:-1]
        with pytest.raises(ValueError, match="Missing job registry entries"):
            BackgroundJobRegistry(entries)

    def test_fails_when_a_job_type_is_registered_twice(self) -> None:
        entries = _all_entries()
        entries.append(_minimal_entry(BackgroundJobType.PORTFOLIO_VALUATION))
        with pytest.raises(ValueError, match="registered more than once"):
            BackgroundJobRegistry(entries)

    def test_fails_when_handler_is_none(self) -> None:
        entries = _all_entries()
        entries[0] = _minimal_entry(entries[0].job_type, handler=None)
        with pytest.raises(ValueError, match="no handler"):
            BackgroundJobRegistry(entries)

    def test_fails_when_queue_name_is_empty(self) -> None:
        entries = _all_entries()
        entries[0] = _minimal_entry(entries[0].job_type, queue_name="")
        with pytest.raises(ValueError, match="empty queue name"):
            BackgroundJobRegistry(entries)

    def test_fails_when_task_name_is_empty(self) -> None:
        entries = _all_entries()
        entries[0] = _minimal_entry(entries[0].job_type, task_name="")
        with pytest.raises(ValueError, match="empty task name"):
            BackgroundJobRegistry(entries)

    @pytest.mark.parametrize("maximum_attempts", [0, 21])
    def test_fails_on_invalid_maximum_attempts(self, maximum_attempts: int) -> None:
        entries = _all_entries()
        entries[0] = _minimal_entry(entries[0].job_type, maximum_attempts=maximum_attempts)
        with pytest.raises(ValueError, match="maximum_attempts"):
            BackgroundJobRegistry(entries)

    def test_fails_when_no_trigger_sources_allowed(self) -> None:
        entries = _all_entries()
        entries[0] = _minimal_entry(entries[0].job_type, allowed_trigger_sources=frozenset())
        with pytest.raises(ValueError, match="allows no trigger sources"):
            BackgroundJobRegistry(entries)

    def test_successful_construction_resolves_every_job_type(self) -> None:
        registry = BackgroundJobRegistry(_all_entries())
        for job_type in BackgroundJobType:
            entry = registry.get(job_type)
            assert entry.job_type == job_type

    def test_get_unknown_job_type_raises(self) -> None:
        registry = BackgroundJobRegistry(_all_entries())
        with pytest.raises(ValueError):
            registry.get("NOT_A_REAL_TYPE")  # type: ignore[arg-type]


class TestBuildDefaultRegistry:
    def test_fails_when_a_handler_is_missing(self) -> None:
        handlers = {job_type: object() for job_type in list(BackgroundJobType)[:-1]}
        with pytest.raises(ValueError, match="No handler supplied"):
            build_default_registry(handlers)

    def test_succeeds_with_every_handler_supplied(self) -> None:
        handlers = {job_type: object() for job_type in BackgroundJobType}
        registry = build_default_registry(handlers)
        assert registry.all_queue_names() == {
            "finquest.default", "finquest.market", "finquest.portfolio", "finquest.knowledge", "finquest.evaluation",
            "finquest.research", "finquest.coach",
        }
        entry = registry.get(BackgroundJobType.SYSTEM_MAINTENANCE)
        assert JobTriggerSource.API not in entry.allowed_trigger_sources
        assert JobTriggerSource.N8N not in entry.allowed_trigger_sources
        assert JobTriggerSource.ADMIN_CLI in entry.allowed_trigger_sources


class TestEmbeddingDependentJobRouting:
    """Regression guard for the Phase A2 base/ai image split: `finquest-worker-default`,
    `finquest-worker-market`, and `finquest-worker-portfolio` build on the `base` image
    (no `sentence-transformers`), so no job type that calls an embedding provider may ever
    be routed to `finquest.default`, `finquest.market`, or `finquest.portfolio`.

    This test locks the currently audited embedding-dependent job types to the
    knowledge/evaluation queues. Any future job that introduces an embedding dependency
    must update this audited set and its routing-contract test as part of the same change.
    """

    _EMBEDDING_DEPENDENT_JOB_TYPES = frozenset({
        BackgroundJobType.CURRICULUM_KNOWLEDGE_REFRESH,
        BackgroundJobType.LOCAL_DOCUMENT_INGESTION,
        BackgroundJobType.KNOWLEDGE_REEMBED,
        BackgroundJobType.RETRIEVAL_EVALUATION,
        BackgroundJobType.RAGAS_QUALITY_EVALUATION,
        BackgroundJobType.QUALITY_BASELINE_COMPARISON,
    })
    _BASE_IMAGE_QUEUES = frozenset({"finquest.default", "finquest.market", "finquest.portfolio"})
    _AI_IMAGE_QUEUES = frozenset({"finquest.knowledge", "finquest.evaluation"})

    def test_embedding_dependent_job_types_are_routed_only_to_knowledge_or_evaluation(self) -> None:
        for job_type in self._EMBEDDING_DEPENDENT_JOB_TYPES:
            queue_name = _JOB_TYPE_CONFIG[job_type][0]
            assert queue_name in self._AI_IMAGE_QUEUES, (
                f"{job_type} touches embeddings but is routed to {queue_name!r}, "
                f"not one of {sorted(self._AI_IMAGE_QUEUES)}"
            )

    def test_base_image_queues_never_carry_an_embedding_dependent_job(self) -> None:
        for job_type, (queue_name, *_rest) in _JOB_TYPE_CONFIG.items():
            if queue_name in self._BASE_IMAGE_QUEUES:
                assert job_type not in self._EMBEDDING_DEPENDENT_JOB_TYPES, (
                    f"{job_type} is routed to base-image queue {queue_name!r} but is in the "
                    "audited embedding-dependent set"
                )


class TestFixedScheduleRetryPolicy:
    def test_non_retryable_exception_type_is_never_retried(self) -> None:
        policy = FixedScheduleRetryPolicy(maximum_attempts=4, delays_seconds=(30,), retryable_exceptions=(TimeoutError,))
        decision = policy.classify(ValueError("bad"), attempt_number=1)
        assert not decision.retryable

    def test_retryable_exception_retries_until_maximum_attempts(self) -> None:
        policy = FixedScheduleRetryPolicy(
            maximum_attempts=3, delays_seconds=(30, 120), retryable_exceptions=(TimeoutError,)
        )
        first = policy.classify(TimeoutError(), attempt_number=1)
        second = policy.classify(TimeoutError(), attempt_number=2)
        third = policy.classify(TimeoutError(), attempt_number=3)
        assert first.retryable and first.delay_seconds == 30
        assert second.retryable and second.delay_seconds == 120
        assert not third.retryable  # exhausted maximum_attempts

    def test_last_delay_repeats_beyond_schedule_length(self) -> None:
        policy = FixedScheduleRetryPolicy(maximum_attempts=5, delays_seconds=(30,), retryable_exceptions=(TimeoutError,))
        decision = policy.classify(TimeoutError(), attempt_number=4)
        assert decision.retryable and decision.delay_seconds == 30


class TestExponentialBackoffRetryPolicy:
    def test_delay_doubles_and_is_capped(self) -> None:
        policy = ExponentialBackoffRetryPolicy(
            maximum_attempts=6, base_delay_seconds=5, cap_seconds=40, retryable_exceptions=(TimeoutError,),
        )
        delays = [policy.classify(TimeoutError(), attempt_number=n).delay_seconds for n in range(1, 6)]
        assert delays == [5, 10, 20, 40, 40]

    def test_jitter_is_injectable_and_deterministic(self) -> None:
        policy = ExponentialBackoffRetryPolicy(
            maximum_attempts=3, base_delay_seconds=10, cap_seconds=100,
            retryable_exceptions=(TimeoutError,), jitter=lambda raw: raw + 1,
        )
        decision = policy.classify(TimeoutError(), attempt_number=1)
        assert decision.delay_seconds == 11


class TestNeverRetryPolicy:
    def test_always_non_retryable(self) -> None:
        policy = NeverRetryPolicy()
        decision = policy.classify(RuntimeError("boom"), attempt_number=1)
        assert not decision.retryable


class TestLiveResearchRunExecutionRegistration:
    """Phase G2B: `LIVE_RESEARCH_RUN_EXECUTION` registration and its
    retry policy, using the real `build_default_registry` wiring."""

    def test_registered_on_a_dedicated_queue_with_the_approved_limits(self) -> None:
        handlers = {job_type: object() for job_type in BackgroundJobType}
        registry = build_default_registry(handlers)
        entry = registry.get(BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION)
        assert entry.queue_name == "finquest.research"
        assert entry.time_limit_seconds == 180
        assert entry.maximum_attempts == 4

    def test_g2c_allows_n8n_but_still_excludes_api(self) -> None:
        """Phase G2C: N8N becomes an allowed trigger source for
        LIVE_RESEARCH_RUN_EXECUTION; the admin-facing API trigger source
        remains deliberately excluded (see docs/migration-status.md)."""
        handlers = {job_type: object() for job_type in BackgroundJobType}
        registry = build_default_registry(handlers)
        entry = registry.get(BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION)
        assert JobTriggerSource.N8N in entry.allowed_trigger_sources
        assert JobTriggerSource.API not in entry.allowed_trigger_sources
        assert JobTriggerSource.ADMIN_CLI in entry.allowed_trigger_sources
        assert JobTriggerSource.SYSTEM in entry.allowed_trigger_sources
        assert JobTriggerSource.RETRY in entry.allowed_trigger_sources

    def test_resource_key_builder_delegates_to_live_research_job_resource_key(self) -> None:
        handlers = {job_type: object() for job_type in BackgroundJobType}
        registry = build_default_registry(handlers)
        entry = registry.get(BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION)
        context = JobExecutionContext(
            job_id=__import__("uuid").uuid4(), job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
            trigger_source=JobTriggerSource.ADMIN_CLI, requested_by_account_id=None,
            requested_by_integration_id=None, idempotency_key="k1", correlation_id=None, attempt_number=0,
        )
        parameters = LiveResearchRunExecutionParameters(original_question="what is a bond?", scope="GENERAL_QUESTION")
        assert entry.resource_key_builder(context, parameters) == live_research_job_resource_key(context)

    def test_retry_policy_retries_only_the_documented_exceptions(self) -> None:
        policies = build_default_retry_policies()
        policy = policies[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]
        for exc in (LiveResearchProviderTimeoutError("x"), LiveResearchProviderRateLimitError("x"), TransientInfrastructureError("x")):
            assert policy.classify(exc, attempt_number=1).retryable, type(exc)
        for exc in (LiveResearchProviderAccessError("x"), LiveResearchProviderResponseError("x"), ValueError("unlisted")):
            assert not policy.classify(exc, attempt_number=1).retryable, type(exc)

    def test_retry_schedule_matches_the_approved_delays(self) -> None:
        policies = build_default_retry_policies()
        policy = policies[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]
        delays = [
            policy.classify(LiveResearchProviderTimeoutError("x"), attempt_number=n).delay_seconds
            for n in range(1, 4)
        ]
        assert delays == [30, 120, 600]
        assert not policy.classify(LiveResearchProviderTimeoutError("x"), attempt_number=4).retryable

    def test_existing_job_types_retain_their_own_retry_policy_and_config(self) -> None:
        """Regression guard: adding LIVE_RESEARCH_RUN_EXECUTION must not
        change any of the 13 pre-existing job types' queue/time-limit/
        retry behavior."""
        policies = build_default_retry_policies()
        assert _JOB_TYPE_CONFIG[BackgroundJobType.SECURITY_MARKET_REFRESH] == (
            "finquest.market", 300, 4, frozenset(JobTriggerSource)
        )
        assert _JOB_TYPE_CONFIG[BackgroundJobType.SYSTEM_MAINTENANCE][0] == "finquest.default"
        assert isinstance(policies[BackgroundJobType.SYSTEM_MAINTENANCE], NeverRetryPolicy)
