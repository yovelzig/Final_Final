"""`QualityEvaluationService`: the single application-layer entry point
for the Phase 13 quality-evaluation platform (spec section 17).

Owns suite/run lifecycle, idempotency-key deduplication, bounded-
concurrency case execution via `QualityEvaluationRunner`, deterministic-
metric computation, optional RAGAS scoring (never overriding a
deterministic hard-gate failure), incremental persistence, and baseline
comparison/approval. Never mutates real learner state - see
`EvaluationCaseExecutorPort`'s contract.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from typing import Any, Callable
from uuid import UUID, uuid4

from stock_research_core.application.exceptions import (
    QualityEvaluationBaselineNotFoundError,
    QualityEvaluationRunNotFoundError,
    QualityEvaluationSuiteNotApprovedError,
    QualityEvaluationSuiteNotFoundError,
)
from stock_research_core.application.operations.ports import MetricsPort, TracingPort
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.application.quality_evaluation import deterministic_metrics as det
from stock_research_core.application.quality_evaluation.deterministic_metrics import HARD_GATE_METRIC_NAMES
from stock_research_core.application.quality_evaluation.models import (
    DeterministicMetricResult,
    EvaluationConfiguration,
    EvaluationRegressionReport,
    EvaluationRunSummary,
    RagasMetricRequest,
    RagasSingleTurnInput,
)
from stock_research_core.application.quality_evaluation.ports import RagasEvaluationPort
from stock_research_core.application.quality_evaluation.regression import build_regression_report, compare_metric
from stock_research_core.application.quality_evaluation.reports import build_gate_decision, summarize_scores
from stock_research_core.application.quality_evaluation.runner import QualityEvaluationRunner
from stock_research_core.domain.models import utc_now
from stock_research_core.domain.quality_evaluation.enums import (
    EvaluationEvidenceIdentity,
    QualityEvaluationCaseStatus,
    QualityEvaluationMode,
    QualityEvaluationRunStatus,
    QualityGateStatus,
    QualityMetricType,
)
from stock_research_core.domain.quality_evaluation.models import (
    QualityEvaluationBaseline,
    QualityEvaluationRun,
    QualityEvaluationSampleResult,
    QualityMetricResult,
)

Clock = Callable[[], datetime]

DEFAULT_RETRIEVAL_K = 5


def _hash_configuration(configuration: EvaluationConfiguration) -> str:
    canonical = json.dumps(configuration.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class QualityEvaluationService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
        case_executor,
        ragas_evaluator: RagasEvaluationPort | None,
        learning_quality_calculator,
        evaluation_cache,
        metrics: MetricsPort,
        tracing: TracingPort,
        clock: Clock = utc_now,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._runner = QualityEvaluationRunner(executor=case_executor)
        self._ragas_evaluator = ragas_evaluator
        self._learning_quality_calculator = learning_quality_calculator
        self._evaluation_cache = evaluation_cache
        self._metrics = metrics
        self._tracing = tracing
        self._clock = clock

    # -- suites -----------------------------------------------

    async def approve_suite(self, *, suite_id: UUID):
        """ADMIN-only (enforced by the caller). Approving a suite
        cascades to every one of its still-`DRAFT` cases - the spec's
        review workflow is suite-level ("every case begins as DRAFT...
        ADMIN approval is required to mark a suite APPROVED"), and
        `execute_run` only ever selects cases whose own status is
        APPROVED, so a suite approval that left cases behind would
        silently produce zero-case runs."""
        async with self._unit_of_work_factory() as uow:
            suite = await uow.quality_evaluation_suites.get_suite_by_id(suite_id)
            if suite is None:
                raise QualityEvaluationSuiteNotFoundError(f"Suite '{suite_id}' not found.")
            draft_cases = await uow.quality_evaluation_suites.list_cases_for_suite(
                suite_id, status=QualityEvaluationCaseStatus.DRAFT
            )
            for case in draft_cases:
                await uow.quality_evaluation_suites.update_case_status(
                    case.case_id, status=QualityEvaluationCaseStatus.APPROVED
                )
            approved_case_count = len(
                await uow.quality_evaluation_suites.list_cases_for_suite(
                    suite_id, status=QualityEvaluationCaseStatus.APPROVED
                )
            )
            updated = await uow.quality_evaluation_suites.update_suite_status(
                suite_id, status=QualityEvaluationCaseStatus.APPROVED, case_count=approved_case_count,
            )
            await uow.commit()
        return updated

    # -- run lifecycle -----------------------------------------------

    async def create_run(
        self, *, suite_id: UUID, mode: QualityEvaluationMode, requested_by_account_id: UUID | None,
        idempotency_key: str, configuration: EvaluationConfiguration,
    ) -> QualityEvaluationRun:
        async with self._unit_of_work_factory() as uow:
            suite = await uow.quality_evaluation_suites.get_suite_by_id(suite_id)
            if suite is None:
                raise QualityEvaluationSuiteNotFoundError(f"Suite '{suite_id}' not found.")

            existing = await uow.quality_evaluation_runs.get_by_suite_and_idempotency_key(
                suite_id=suite_id, idempotency_key=idempotency_key
            )
            if existing is not None:
                return existing

            cases = await uow.quality_evaluation_suites.list_cases_for_suite(
                suite_id, status=QualityEvaluationCaseStatus.APPROVED
            )
            run = QualityEvaluationRun(
                run_id=uuid4(), suite_id=suite_id, mode=mode, requested_by_account_id=requested_by_account_id,
                system_version=configuration.system_version, git_commit=configuration.git_commit,
                retrieval_policy_version=configuration.retrieval_policy_version,
                embedding_model=configuration.embedding_model, embedding_version=configuration.embedding_version,
                tutor_policy_version=configuration.tutor_policy_version, prompt_version=configuration.prompt_version,
                guardrail_version=configuration.guardrail_version, graph_version=configuration.graph_version,
                evaluator_provider="openai_compatible" if mode != QualityEvaluationMode.DETERMINISTIC else None,
                evaluator_model=(
                    self._ragas_evaluator_model_name() if mode != QualityEvaluationMode.DETERMINISTIC else None
                ),
                ragas_version=(self._ragas_evaluator.ragas_version if self._ragas_evaluator and mode != QualityEvaluationMode.DETERMINISTIC else None),
                case_count=len(cases), dataset_hash=suite.dataset_hash, configuration_hash=_hash_configuration(configuration),
            )
            created = await uow.quality_evaluation_runs.create(run, idempotency_key=idempotency_key)
            await uow.commit()
        self._metrics.increment_counter(
            "finquest_quality_evaluation_runs_total", labels={"suite_type": suite.suite_type.value, "mode": mode.value, "status": "CREATED"}
        )
        return created

    async def execute_run(self, *, run_id: UUID) -> EvaluationRunSummary:
        async with self._unit_of_work_factory() as uow:
            run = await uow.quality_evaluation_runs.get_by_id(run_id)
            if run is None:
                raise QualityEvaluationRunNotFoundError(f"Run '{run_id}' not found.")
            suite = await uow.quality_evaluation_suites.get_suite_by_id(run.suite_id)
            if suite is None:
                raise QualityEvaluationSuiteNotFoundError(f"Suite '{run.suite_id}' not found.")
            if not suite.is_production_eligible:
                raise QualityEvaluationSuiteNotApprovedError(
                    f"Suite '{suite.code}' version '{suite.version}' is not APPROVED - approve it before running an evaluation."
                )
            cases = await uow.quality_evaluation_suites.list_cases_for_suite(
                run.suite_id, status=QualityEvaluationCaseStatus.APPROVED
            )
            await uow.quality_evaluation_runs.mark_running(run_id, started_at=self._clock())
            await uow.commit()

        self._metrics.set_gauge("finquest_quality_evaluation_cases_total", len(cases))
        completed = 0
        failed = 0
        skipped = 0
        all_deterministic_results: list[DeterministicMetricResult] = []
        ragas_single_turn_inputs: list[RagasSingleTurnInput] = []
        # Populated from the configured evaluator's metric list once RAGAS
        # is actually enabled (spec section 4: RAGAS_ENABLED=false by
        # default this phase) - `_run_ragas` is a safe no-op while empty.
        ragas_metric_names: list[str] = (
            list(self._ragas_evaluator.default_metric_names)
            if self._ragas_evaluator is not None and hasattr(self._ragas_evaluator, "default_metric_names")
            else []
        )

        semaphore = asyncio.Semaphore(4)

        async def _run_one(case):
            async with semaphore:
                return await self._execute_and_grade_case(run, case)

        async with self._tracing.start_span("quality_evaluation.execute_run", attributes={"suite_type": suite.suite_type.value}):
            results = await asyncio.gather(*[_run_one(case) for case in cases], return_exceptions=True)

        for case, outcome in zip(cases, results):
            if isinstance(outcome, Exception):
                failed += 1
                self._metrics.increment_counter(
                    "finquest_quality_evaluation_case_failures_total", labels={"suite_type": suite.suite_type.value}
                )
                continue
            sample, case_metrics = outcome
            completed += 1
            all_deterministic_results.extend(case_metrics)
            async with self._unit_of_work_factory() as uow:
                await uow.quality_evaluation_results.create_sample_result(sample)
                metric_rows = [
                    QualityMetricResult(
                        run_id=run.run_id, sample_result_id=sample.sample_result_id, metric_name=metric.metric_name,
                        metric_type=QualityMetricType.SAFETY_GATE if metric.is_hard_gate else QualityMetricType.DETERMINISTIC,
                        metric_version="v1", score=metric.score, passed=metric.passed, details=metric.details,
                    )
                    for metric in case_metrics
                ]
                await uow.quality_evaluation_results.bulk_create_metric_results(metric_rows)
                await uow.quality_evaluation_runs.update_progress(
                    run_id, completed_case_count=completed, failed_case_count=failed, skipped_case_count=skipped,
                )
                await uow.commit()

            if run.mode != QualityEvaluationMode.DETERMINISTIC and sample.generated_response:
                ragas_single_turn_inputs.append(
                    RagasSingleTurnInput(
                        case_id=case.case_id, user_input=case.user_input, response=sample.generated_response,
                        retrieved_contexts=[], reference=case.reference_answer,
                    )
                )

        ragas_metric_summary: dict[str, float] = {}
        skipped_ragas_metrics: dict[str, str] = {}
        if run.mode != QualityEvaluationMode.DETERMINISTIC and self._ragas_evaluator is not None and ragas_single_turn_inputs:
            ragas_metric_summary, skipped_ragas_metrics = await self._run_ragas(
                run=run, samples=ragas_single_turn_inputs, metric_names=ragas_metric_names,
            )

        deterministic_summary = summarize_scores(all_deterministic_results)
        gate_decision = build_gate_decision(all_deterministic_results)

        async with self._unit_of_work_factory() as uow:
            aggregate_rows = [
                QualityMetricResult(
                    run_id=run.run_id, sample_result_id=None, metric_name=name,
                    metric_type=QualityMetricType.SAFETY_GATE if name in HARD_GATE_METRIC_NAMES else QualityMetricType.DETERMINISTIC,
                    metric_version="v1", score=score,
                )
                for name, score in deterministic_summary.items()
            ]
            aggregate_rows.extend(
                QualityMetricResult(
                    run_id=run.run_id, sample_result_id=None, metric_name=name, metric_type=QualityMetricType.RAGAS,
                    metric_version="v1", score=score, evaluator_provider="openai_compatible",
                    evaluator_model=self._ragas_evaluator_model_name(),
                )
                for name, score in ragas_metric_summary.items()
            )
            if aggregate_rows:
                await uow.quality_evaluation_results.bulk_create_metric_results(aggregate_rows)

            completed_at = self._clock()
            if gate_decision.overall_status == QualityGateStatus.FAIL or (failed > 0 and completed == 0):
                final_run = await uow.quality_evaluation_runs.mark_failed(run_id, completed_at=completed_at)
                final_status = QualityEvaluationRunStatus.FAILED
            elif failed > 0 or skipped > 0:
                final_run = await uow.quality_evaluation_runs.mark_partially_succeeded(run_id, completed_at=completed_at)
                final_status = QualityEvaluationRunStatus.PARTIALLY_SUCCEEDED
            else:
                final_run = await uow.quality_evaluation_runs.mark_succeeded(run_id, completed_at=completed_at)
                final_status = QualityEvaluationRunStatus.SUCCEEDED
            await uow.commit()

        self._metrics.increment_counter(
            "finquest_quality_evaluation_runs_total",
            labels={"suite_type": suite.suite_type.value, "mode": run.mode.value, "status": final_status.value},
        )
        if gate_decision.hard_gate_failures:
            self._metrics.increment_counter(
                "finquest_quality_hard_gate_failures_total", labels={"suite_type": suite.suite_type.value}
            )

        return EvaluationRunSummary(
            run_id=run_id, status=final_status, mode=run.mode, case_count=len(cases), completed_case_count=completed,
            failed_case_count=failed, skipped_case_count=skipped, gate_decision=gate_decision,
            deterministic_metric_summary=deterministic_summary, ragas_metric_summary=ragas_metric_summary,
            skipped_ragas_metrics=skipped_ragas_metrics,
        )

    def _ragas_evaluator_model_name(self) -> str | None:
        return getattr(self._ragas_evaluator, "model_name", None)

    async def _run_ragas(
        self, *, run: QualityEvaluationRun, samples: list[RagasSingleTurnInput], metric_names: list[str],
    ) -> tuple[dict[str, float], dict[str, str]]:
        if not metric_names or self._ragas_evaluator is None:
            return {}, {}
        try:
            results = await self._ragas_evaluator.evaluate_single_turn(samples=samples, metric_names=metric_names)
        except Exception as exc:  # noqa: BLE001 - RAGAS failure must not corrupt deterministic results
            self._metrics.increment_counter("finquest_ragas_failures_total")
            return {}, {name: f"RAGAS evaluation failed: {type(exc).__name__}" for name in metric_names}

        by_metric: dict[str, list[float]] = {}
        skipped: dict[str, str] = {}
        for sample_result in results:
            for metric_name, score in sample_result.scores.items():
                by_metric.setdefault(metric_name, []).append(score)
            skipped.update(sample_result.skipped_metrics)
        summary = {name: sum(scores) / len(scores) for name, scores in by_metric.items() if scores}
        return summary, skipped

    async def _execute_and_grade_case(self, run: QualityEvaluationRun, case) -> tuple[QualityEvaluationSampleResult, list[DeterministicMetricResult]]:
        result = await self._runner.execute_case(case)
        metrics: list[DeterministicMetricResult] = []
        for identity in (EvaluationEvidenceIdentity.CHUNK, EvaluationEvidenceIdentity.DOCUMENT):
            metrics.append(det.hit_at_k(case, result, k=DEFAULT_RETRIEVAL_K, identity=identity))
            metrics.append(det.reciprocal_rank(case, result, identity=identity))
            metrics.append(det.precision_at_k(case, result, k=DEFAULT_RETRIEVAL_K, identity=identity))
            metrics.append(det.recall_at_k(case, result, k=DEFAULT_RETRIEVAL_K, identity=identity))
        metrics.append(det.required_concept_coverage(case, result))
        metrics.append(det.citation_validity(case, result))
        metrics.append(det.citation_ordering(result))
        metrics.append(det.guardrail_category_accuracy(case, result))
        metrics.append(det.refusal_accuracy(case, result))
        metrics.append(det.forbidden_phrase_absence(case, result, metric_name="scenario_future_leakage_prevention"))
        metrics.append(det.intent_accuracy(case, result))
        metrics.append(det.route_accuracy(case, result))
        metrics.append(det.action_proposal_accuracy(case, result))
        metrics.append(det.interrupt_compliance(case, result))
        metrics.append(det.unauthorized_action_prevention(result))
        metrics = [metric for metric in metrics if metric.score is not None or metric.passed is not None]

        status = QualityGateStatus.PASS
        if any(metric.is_hard_gate and metric.gate_status == QualityGateStatus.FAIL for metric in metrics):
            status = QualityGateStatus.FAIL
        elif any(metric.gate_status == QualityGateStatus.WARN for metric in metrics):
            status = QualityGateStatus.WARN

        sample = QualityEvaluationSampleResult(
            run_id=run.run_id, case_id=case.case_id, status=status, generated_response=result.generated_response,
            retrieved_context_ids=result.retrieved_context_ids, retrieved_document_ids=result.retrieved_document_ids,
            citation_chunk_ids=result.citation_chunk_ids, observed_guardrail_category=result.observed_guardrail_category,
            observed_intent=result.observed_intent, observed_route=result.observed_route,
            observed_action_type=result.observed_action_type, observed_interrupt=result.observed_interrupt,
            latency_ms=result.latency_ms, retrieval_latency_ms=result.retrieval_latency_ms,
            generation_latency_ms=result.generation_latency_ms, input_token_count=result.input_token_count,
            output_token_count=result.output_token_count, estimated_cost=result.estimated_cost,
            failure_code=result.failure_code, failure_message=result.failure_message,
        )
        return sample, metrics

    # -- baselines -----------------------------------------------

    async def approve_baseline(self, *, run_id: UUID, name: str, approved_by_account_id: UUID) -> QualityEvaluationBaseline:
        """ADMIN-only (enforced by the caller - e.g. the API's
        `require_admin` dependency). Never automatic."""
        async with self._unit_of_work_factory() as uow:
            run = await uow.quality_evaluation_runs.get_by_id(run_id)
            if run is None:
                raise QualityEvaluationRunNotFoundError(f"Run '{run_id}' not found.")
            metric_results = await uow.quality_evaluation_results.list_metric_results_for_run(run_id)
            metric_summary = {m.metric_name: m.score for m in metric_results if m.score is not None}
            safety_gate_summary = {
                m.metric_name: bool(m.passed) for m in metric_results
                if m.metric_type == QualityMetricType.SAFETY_GATE and m.passed is not None
            }
            now = self._clock()
            baseline = await uow.quality_evaluation_baselines.create(
                QualityEvaluationBaseline(
                    suite_id=run.suite_id, run_id=run_id, name=name, approved=True,
                    approved_by_account_id=approved_by_account_id, metric_summary=metric_summary,
                    safety_gate_summary=safety_gate_summary, approved_at=now,
                )
            )
            await uow.commit()
        return baseline

    async def compare_with_baseline(self, *, run_id: UUID, baseline_id: UUID) -> EvaluationRegressionReport:
        async with self._unit_of_work_factory() as uow:
            run = await uow.quality_evaluation_runs.get_by_id(run_id)
            if run is None:
                raise QualityEvaluationRunNotFoundError(f"Run '{run_id}' not found.")
            baseline = await uow.quality_evaluation_baselines.get_by_id(baseline_id)
            if baseline is None:
                raise QualityEvaluationBaselineNotFoundError(f"Baseline '{baseline_id}' not found.")
            baseline_run = await uow.quality_evaluation_runs.get_by_id(baseline.run_id)
            candidate_suite = await uow.quality_evaluation_suites.get_suite_by_id(run.suite_id)
            baseline_suite = await uow.quality_evaluation_suites.get_suite_by_id(baseline.suite_id)
            candidate_metrics = await uow.quality_evaluation_results.list_metric_results_for_run(run_id)

        candidate_by_name = {m.metric_name: m for m in candidate_metrics if m.sample_result_id is None}
        comparisons = []
        for metric_name, baseline_value in baseline.metric_summary.items():
            candidate_metric = candidate_by_name.get(metric_name)
            comparisons.append(
                compare_metric(
                    metric_name=metric_name, candidate_value=candidate_metric.score if candidate_metric else None,
                    baseline_value=baseline_value,
                )
            )
        for metric_name, baseline_passed in baseline.safety_gate_summary.items():
            candidate_metric = candidate_by_name.get(metric_name)
            comparisons.append(
                compare_metric(
                    metric_name=metric_name, candidate_value=None, baseline_value=None, is_hard_gate=True,
                    candidate_passed=candidate_metric.passed if candidate_metric else None,
                    baseline_passed=baseline_passed,
                )
            )

        return build_regression_report(
            run_id=run_id, baseline_id=baseline_id,
            candidate_suite_version=candidate_suite.version if candidate_suite else "unknown",
            baseline_suite_version=baseline_suite.version if baseline_suite else "unknown",
            candidate_evaluator_model=run.evaluator_model,
            baseline_evaluator_model=baseline_run.evaluator_model if baseline_run else None,
            comparisons=comparisons,
        )
