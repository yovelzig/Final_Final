"""Unit tests for the Phase 13 RAGAS infrastructure adapter (spec
section 28.5). No network access anywhere: the compatibility smoke test
only imports/inspects the installed `ragas` package; every scoring test
below mocks `RagasEvaluationAdapter`'s per-metric instances directly, so
no real LLM/HTTP client is ever constructed.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from stock_research_core.application.quality_evaluation.models import RagasMultiTurnInput, RagasSingleTurnInput
from stock_research_core.infrastructure.quality_evaluation.config import QualityEvaluationSettings
from stock_research_core.infrastructure.quality_evaluation.ragas_adapter import (
    RagasEvaluationAdapter,
    SameModelEvaluationError,
)


class TestRagasCompatibilitySmokeTest:
    """Verifies the pinned RAGAS version actually exposes the API this
    adapter depends on - fails loudly at test time (not silently at
    first production use) if a future `ragas` upgrade renames/removes
    something."""

    def test_installed_version_is_exposed(self) -> None:
        import ragas

        assert ragas.__version__

    def test_dataset_schema_types_import(self) -> None:
        from ragas import EvaluationDataset, MultiTurnSample, SingleTurnSample  # noqa: F401

    def test_required_collections_metrics_import(self) -> None:
        from ragas.metrics.collections import (  # noqa: F401
            AgentGoalAccuracyWithoutReference,
            AnswerRelevancy,
            ContextPrecisionWithoutReference,
            ContextRecall,
            Faithfulness,
            FactualCorrectness,
        )

    def test_llm_factory_and_message_types_import(self) -> None:
        from ragas.llms import llm_factory  # noqa: F401
        from ragas.messages import AIMessage, HumanMessage  # noqa: F401

    def test_embeddings_base_imports(self) -> None:
        from ragas.embeddings.base import BaseRagasEmbedding  # noqa: F401


class _FakeMetric:
    def __init__(self, *, value: float | None = None, error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.call_count = 0

    async def ascore(self, **kwargs) -> SimpleNamespace:
        self.call_count += 1
        if self.error is not None:
            raise self.error
        return SimpleNamespace(value=self.value)


def _settings(**overrides) -> QualityEvaluationSettings:
    fields = dict(
        ragas_enabled=True, ragas_evaluator_model="judge-model", ragas_max_concurrency=2, ragas_timeout_seconds=5,
        ragas_max_retries=1, ragas_max_samples_per_run=10,
    )
    fields.update(overrides)
    return QualityEvaluationSettings(**fields)


def _adapter(settings: QualityEvaluationSettings | None = None) -> RagasEvaluationAdapter:
    return RagasEvaluationAdapter(llm=object(), embeddings=object(), settings=settings or _settings())


class TestSameModelRejection:
    def test_rejects_same_model_by_default(self) -> None:
        settings = _settings(ragas_evaluator_model="tutor-model")
        with pytest.raises(SameModelEvaluationError):
            RagasEvaluationAdapter(llm=object(), embeddings=object(), settings=settings, tutor_model_name="tutor-model")

    def test_allows_same_model_when_explicitly_enabled(self) -> None:
        settings = _settings(ragas_evaluator_model="tutor-model", ragas_allow_same_model_as_tutor=True)
        adapter = RagasEvaluationAdapter(
            llm=object(), embeddings=object(), settings=settings, tutor_model_name="tutor-model"
        )
        assert adapter.model_name == "tutor-model"

    def test_different_models_never_rejected(self) -> None:
        settings = _settings(ragas_evaluator_model="judge-model")
        RagasEvaluationAdapter(llm=object(), embeddings=object(), settings=settings, tutor_model_name="tutor-model")


class TestEvaluateSingleTurn:
    async def test_scores_a_sample_across_requested_metrics(self) -> None:
        adapter = _adapter()
        adapter._metric_instances["finquest_faithfulness"] = _FakeMetric(value=0.9)
        adapter._metric_instances["finquest_response_relevancy"] = _FakeMetric(value=0.8)

        sample = RagasSingleTurnInput(
            case_id=uuid4(), user_input="What is diversification?", response="It reduces risk.",
            retrieved_contexts=["Diversification reduces risk."],
        )
        results = await adapter.evaluate_single_turn(
            samples=[sample], metric_names=["finquest_faithfulness", "finquest_response_relevancy"],
        )
        assert len(results) == 1
        assert results[0].scores == {"finquest_faithfulness": 0.9, "finquest_response_relevancy": 0.8}
        assert results[0].skipped_metrics == {}

    async def test_skips_reference_dependent_metrics_without_a_reference(self) -> None:
        adapter = _adapter()
        sample = RagasSingleTurnInput(
            case_id=uuid4(), user_input="What is a bond?", response="A loan to an issuer.",
            retrieved_contexts=["A bond is a loan to an issuer."], reference=None,
        )
        results = await adapter.evaluate_single_turn(
            samples=[sample], metric_names=["finquest_context_recall", "finquest_factual_correctness"],
        )
        assert results[0].scores == {}
        assert "reference answer required" in results[0].skipped_metrics["finquest_context_recall"]
        assert "reference answer required" in results[0].skipped_metrics["finquest_factual_correctness"]

    async def test_unknown_metric_name_is_skipped_not_silently_substituted(self) -> None:
        adapter = _adapter()
        sample = RagasSingleTurnInput(case_id=uuid4(), user_input="q", response="r")
        results = await adapter.evaluate_single_turn(samples=[sample], metric_names=["finquest_made_up_metric"])
        assert results[0].scores == {}
        assert "Unknown metric" in results[0].skipped_metrics["finquest_made_up_metric"]

    async def test_one_metric_failure_does_not_sink_the_whole_sample(self) -> None:
        adapter = _adapter()
        adapter._metric_instances["finquest_faithfulness"] = _FakeMetric(error=RuntimeError("provider timeout"))
        adapter._metric_instances["finquest_response_relevancy"] = _FakeMetric(value=0.7)

        sample = RagasSingleTurnInput(case_id=uuid4(), user_input="q", response="r", retrieved_contexts=["x"])
        results = await adapter.evaluate_single_turn(
            samples=[sample], metric_names=["finquest_faithfulness", "finquest_response_relevancy"],
        )
        assert results[0].scores == {"finquest_response_relevancy": 0.7}
        assert "evaluation failed" in results[0].skipped_metrics["finquest_faithfulness"]

    async def test_retries_up_to_the_configured_bound_then_gives_up(self) -> None:
        settings = _settings(ragas_max_retries=2)
        adapter = _adapter(settings)
        failing_metric = _FakeMetric(error=RuntimeError("transient"))
        adapter._metric_instances["finquest_faithfulness"] = failing_metric

        sample = RagasSingleTurnInput(case_id=uuid4(), user_input="q", response="r", retrieved_contexts=["x"])
        results = await adapter.evaluate_single_turn(samples=[sample], metric_names=["finquest_faithfulness"])
        assert failing_metric.call_count == 3  # initial attempt + 2 retries
        assert "evaluation failed" in results[0].skipped_metrics["finquest_faithfulness"]

    async def test_bounded_sample_count_is_enforced(self) -> None:
        settings = _settings(ragas_max_samples_per_run=1)
        adapter = _adapter(settings)
        samples = [
            RagasSingleTurnInput(case_id=uuid4(), user_input="a", response="a"),
            RagasSingleTurnInput(case_id=uuid4(), user_input="b", response="b"),
        ]
        with pytest.raises(ValueError, match="Refusing to evaluate"):
            await adapter.evaluate_single_turn(samples=samples, metric_names=["finquest_faithfulness"])

    async def test_no_api_key_appears_in_any_result(self) -> None:
        settings = _settings(ragas_evaluator_api_key="super-secret-key")
        adapter = _adapter(settings)
        adapter._metric_instances["finquest_faithfulness"] = _FakeMetric(value=0.5)
        sample = RagasSingleTurnInput(case_id=uuid4(), user_input="q", response="r", retrieved_contexts=["x"])
        results = await adapter.evaluate_single_turn(samples=[sample], metric_names=["finquest_faithfulness"])
        assert "super-secret-key" not in str(results[0].model_dump())


class TestEvaluateMultiTurn:
    async def test_scores_a_conversation(self) -> None:
        adapter = _adapter()
        adapter._metric_instances["finquest_agent_goal_accuracy"] = _FakeMetric(value=1.0)
        sample = RagasMultiTurnInput(
            case_id=uuid4(), turns=[{"role": "human", "content": "start practice"}, {"role": "ai", "content": "ok"}]
        )
        results = await adapter.evaluate_multi_turn(samples=[sample], metric_names=["finquest_agent_goal_accuracy"])
        assert results[0].scores == {"finquest_agent_goal_accuracy": 1.0}

    async def test_unsupported_multi_turn_metric_is_skipped(self) -> None:
        adapter = _adapter()
        sample = RagasMultiTurnInput(case_id=uuid4(), turns=[{"role": "human", "content": "hi"}])
        results = await adapter.evaluate_multi_turn(samples=[sample], metric_names=["finquest_faithfulness"])
        assert "Unknown or unsupported" in results[0].skipped_metrics["finquest_faithfulness"]


class TestCacheKeyStability:
    def test_same_inputs_produce_the_same_key(self) -> None:
        from stock_research_core.infrastructure.quality_evaluation.evaluation_cache import build_cache_key

        key1 = build_cache_key(
            case_hash="a", response_hash="b", context_hash="c", metric_version="v1",
            evaluator_provider="openai_compatible", evaluator_model="judge-1",
        )
        key2 = build_cache_key(
            case_hash="a", response_hash="b", context_hash="c", metric_version="v1",
            evaluator_provider="openai_compatible", evaluator_model="judge-1",
        )
        assert key1 == key2

    def test_different_inputs_produce_different_keys(self) -> None:
        from stock_research_core.infrastructure.quality_evaluation.evaluation_cache import build_cache_key

        key1 = build_cache_key(
            case_hash="a", response_hash="b", context_hash="c", metric_version="v1",
            evaluator_provider="openai_compatible", evaluator_model="judge-1",
        )
        key2 = build_cache_key(
            case_hash="a", response_hash="b", context_hash="c", metric_version="v2",
            evaluator_provider="openai_compatible", evaluator_model="judge-1",
        )
        assert key1 != key2
