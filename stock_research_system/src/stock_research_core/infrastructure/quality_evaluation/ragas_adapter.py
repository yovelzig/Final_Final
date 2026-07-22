"""`RagasEvaluationPort` implementation - the *only* infrastructure
module (besides `ragas_model_factory.py`) allowed to import `ragas`.

Uses the current (0.4.x) collections-based per-sample metric API
(`ragas.metrics.collections.*`, each with an `ascore(...)` coroutine) -
not the legacy `ragas.metrics.*`/`evaluate()` batch API, which 0.4.x
itself deprecates in favor of collections. `EvaluationDataset`/
`SingleTurnSample`/`MultiTurnSample` remain importable (see
`test_ragas_adapter.py`'s compatibility smoke test) for callers that
still want the batch shape, but this adapter's own per-sample scoring
does not require building one.

Metric name mapping (spec section 12) is fixed and explicit - a
metric-name typo must fail loudly, never silently resolve to a
different metric.
"""

from __future__ import annotations

import asyncio
from typing import Any

from stock_research_core.application.quality_evaluation.models import (
    RagasMultiTurnInput,
    RagasSampleResult,
    RagasSingleTurnInput,
)
from stock_research_core.infrastructure.quality_evaluation.config import QualityEvaluationSettings

#: spec section 12's fixed mapping - `metric.requires_reference` records
#: whether a sample without `reference`/`reference_contexts` must skip it.
_SINGLE_TURN_METRIC_BUILDERS: dict[str, str] = {
    "finquest_faithfulness": "Faithfulness",
    "finquest_response_relevancy": "AnswerRelevancy",
    "finquest_context_precision": "ContextPrecisionWithoutReference",
    "finquest_context_recall": "ContextRecall",
    "finquest_factual_correctness": "FactualCorrectness",
}
_REFERENCE_REQUIRED_METRICS = frozenset({"finquest_context_recall", "finquest_factual_correctness"})
_MULTI_TURN_METRIC_BUILDERS: dict[str, str] = {
    "finquest_agent_goal_accuracy": "AgentGoalAccuracyWithoutReference",
}


class SameModelEvaluationError(ValueError):
    """Raised when the evaluator model matches the tutor's own model and
    `RAGAS_ALLOW_SAME_MODEL_AS_TUTOR` was not explicitly set - spec
    section 4: "Reject same-model evaluation by default"."""


class RagasEvaluationAdapter:
    def __init__(
        self, *, llm: Any, embeddings: Any, settings: QualityEvaluationSettings, tutor_model_name: str | None = None,
    ) -> None:
        if (
            tutor_model_name
            and settings.ragas_evaluator_model
            and tutor_model_name == settings.ragas_evaluator_model
            and not settings.ragas_allow_same_model_as_tutor
        ):
            raise SameModelEvaluationError(
                f"RAGAS_EVALUATOR_MODEL ({settings.ragas_evaluator_model!r}) matches the tutor's own model - "
                "set RAGAS_ALLOW_SAME_MODEL_AS_TUTOR=true to explicitly allow the tutor to grade itself."
            )
        self._llm = llm
        self._embeddings = embeddings
        self._settings = settings
        self._model_name = settings.ragas_evaluator_model
        self._semaphore = asyncio.Semaphore(max(1, settings.ragas_max_concurrency))
        self._metric_instances: dict[str, Any] = {}

    @property
    def ragas_version(self) -> str:
        import ragas

        return ragas.__version__

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def default_metric_names(self) -> list[str]:
        return list(_SINGLE_TURN_METRIC_BUILDERS)

    def _single_turn_metric(self, finquest_name: str) -> Any:
        if finquest_name not in _SINGLE_TURN_METRIC_BUILDERS:
            raise ValueError(f"Unknown single-turn RAGAS metric name {finquest_name!r}")
        if finquest_name not in self._metric_instances:
            from ragas.metrics import collections

            class_name = _SINGLE_TURN_METRIC_BUILDERS[finquest_name]
            metric_cls = getattr(collections, class_name)
            if class_name == "AnswerRelevancy":
                self._metric_instances[finquest_name] = metric_cls(llm=self._llm, embeddings=self._embeddings)
            else:
                self._metric_instances[finquest_name] = metric_cls(llm=self._llm)
        return self._metric_instances[finquest_name]

    def _multi_turn_metric(self, finquest_name: str) -> Any:
        if finquest_name not in _MULTI_TURN_METRIC_BUILDERS:
            raise ValueError(f"Unknown multi-turn RAGAS metric name {finquest_name!r}")
        if finquest_name not in self._metric_instances:
            from ragas.metrics import collections

            class_name = _MULTI_TURN_METRIC_BUILDERS[finquest_name]
            self._metric_instances[finquest_name] = getattr(collections, class_name)(llm=self._llm)
        return self._metric_instances[finquest_name]

    async def _score_with_retry(self, coro_factory) -> float:
        last_exc: Exception | None = None
        for attempt in range(self._settings.ragas_max_retries + 1):
            try:
                async with self._semaphore:
                    result = await asyncio.wait_for(coro_factory(), timeout=self._settings.ragas_timeout_seconds)
                return float(result.value)
            except Exception as exc:  # noqa: BLE001 - classified by the caller into a per-metric skip
                last_exc = exc
        raise last_exc  # type: ignore[misc]

    async def evaluate_single_turn(
        self, *, samples: list[RagasSingleTurnInput], metric_names: list[str],
    ) -> list[RagasSampleResult]:
        if len(samples) > self._settings.ragas_max_samples_per_run:
            raise ValueError(
                f"Refusing to evaluate {len(samples)} samples in one call "
                f"(bounded at {self._settings.ragas_max_samples_per_run})."
            )
        results: list[RagasSampleResult] = []
        for sample in samples:
            scores: dict[str, float] = {}
            skipped: dict[str, str] = {}
            for metric_name in metric_names:
                if metric_name not in _SINGLE_TURN_METRIC_BUILDERS:
                    skipped[metric_name] = f"Unknown metric {metric_name!r}"
                    continue
                if metric_name in _REFERENCE_REQUIRED_METRICS and not sample.reference:
                    skipped[metric_name] = "reference answer required but not provided for this case"
                    continue
                metric = self._single_turn_metric(metric_name)
                try:
                    if metric_name == "finquest_faithfulness":
                        score = await self._score_with_retry(
                            lambda m=metric, s=sample: m.ascore(
                                user_input=s.user_input, response=s.response, retrieved_contexts=s.retrieved_contexts
                            )
                        )
                    elif metric_name == "finquest_response_relevancy":
                        score = await self._score_with_retry(
                            lambda m=metric, s=sample: m.ascore(user_input=s.user_input, response=s.response)
                        )
                    elif metric_name == "finquest_context_precision":
                        score = await self._score_with_retry(
                            lambda m=metric, s=sample: m.ascore(
                                user_input=s.user_input, response=s.response, retrieved_contexts=s.retrieved_contexts
                            )
                        )
                    elif metric_name == "finquest_context_recall":
                        score = await self._score_with_retry(
                            lambda m=metric, s=sample: m.ascore(
                                user_input=s.user_input, retrieved_contexts=s.retrieved_contexts, reference=s.reference
                            )
                        )
                    elif metric_name == "finquest_factual_correctness":
                        score = await self._score_with_retry(
                            lambda m=metric, s=sample: m.ascore(response=s.response, reference=s.reference)
                        )
                    else:  # pragma: no cover - guarded by the membership check above
                        continue
                    scores[metric_name] = score
                except Exception as exc:  # noqa: BLE001 - one metric's failure must not sink the whole sample
                    skipped[metric_name] = f"evaluation failed: {type(exc).__name__}"
            results.append(RagasSampleResult(case_id=sample.case_id, scores=scores, skipped_metrics=skipped))
        return results

    async def evaluate_multi_turn(
        self, *, samples: list[RagasMultiTurnInput], metric_names: list[str],
    ) -> list[RagasSampleResult]:
        from ragas.messages import AIMessage, HumanMessage

        results: list[RagasSampleResult] = []
        for sample in samples:
            scores: dict[str, float] = {}
            skipped: dict[str, str] = {}
            messages = [
                HumanMessage(content=turn["content"]) if turn.get("role") == "human" else AIMessage(content=turn["content"])
                for turn in sample.turns
            ]
            for metric_name in metric_names:
                if metric_name not in _MULTI_TURN_METRIC_BUILDERS:
                    skipped[metric_name] = f"Unknown or unsupported multi-turn metric {metric_name!r}"
                    continue
                metric = self._multi_turn_metric(metric_name)
                try:
                    score = await self._score_with_retry(lambda m=metric, msgs=messages: m.ascore(user_input=msgs))
                    scores[metric_name] = score
                except Exception as exc:  # noqa: BLE001
                    skipped[metric_name] = f"evaluation failed: {type(exc).__name__}"
            results.append(RagasSampleResult(case_id=sample.case_id, scores=scores, skipped_metrics=skipped))
        return results
