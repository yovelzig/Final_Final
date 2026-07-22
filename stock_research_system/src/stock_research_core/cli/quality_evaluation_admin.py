"""Administrative CLI for the Phase 13 quality-evaluation platform
(spec section 25).

Validate a curated JSONL dataset (structure/reference checks only, no
database access):

    python -m stock_research_core.cli.quality_evaluation_admin `
      --validate-suite ".\\evaluation\\suites\\finquest-rag-core-v1.jsonl"

Import a validated suite (stays DRAFT - never auto-approved):

    python -m stock_research_core.cli.quality_evaluation_admin `
      --import-suite ".\\evaluation\\suites\\finquest-rag-core-v1.jsonl" `
      --code FINQUEST_RAG_CORE_V1 --name "FinQuest RAG core" `
      --suite-type RAG_SINGLE_TURN --version v1

Approve a suite (ADMIN-only in spirit - run this only as an authorized
administrator):

    python -m stock_research_core.cli.quality_evaluation_admin --approve-suite <UUID>

Run an evaluation:

    python -m stock_research_core.cli.quality_evaluation_admin `
      --run-suite <UUID> --mode DETERMINISTIC

Check run status / compare against a baseline:

    python -m stock_research_core.cli.quality_evaluation_admin --run-status <UUID>
    python -m stock_research_core.cli.quality_evaluation_admin --compare-run <UUID> --baseline <UUID>

Never prints API keys or full case/answer content by default. Always
disposes the database engine (and, if RAGAS is enabled, no persistent
evaluator connection is held open beyond one CLI invocation).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID, uuid4

from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.application.quality_evaluation.datasets import DatasetValidationError, build_cases, compute_dataset_hash, parse_jsonl
from stock_research_core.application.quality_evaluation.models import EvaluationConfiguration
from stock_research_core.application.quality_evaluation.service import QualityEvaluationService
from stock_research_core.domain.quality_evaluation.enums import (
    QualityEvaluationCaseStatus,
    QualityEvaluationMode,
    QualityEvaluationSuiteType,
)
from stock_research_core.domain.quality_evaluation.models import QualityEvaluationSuite
from stock_research_core.infrastructure.ai_tutor.config import EmbeddingSettings
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import DeterministicFakeEmbeddingAdapter
from stock_research_core.infrastructure.ai_tutor.production_safety import assert_embedding_provider_production_safe
from stock_research_core.infrastructure.ai_tutor.sentence_transformer_embeddings import SentenceTransformerEmbeddingAdapter
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import create_database_engine, create_session_factory
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from stock_research_core.infrastructure.operations.config import OperationsSettings
from stock_research_core.infrastructure.operations.registry_factory import build_quality_evaluation_service
from stock_research_core.infrastructure.quality_evaluation.dataset_loader import load_cases_from_file


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stock_research_core.cli.quality_evaluation_admin",
        description="Administer the FinQuest Phase 13 quality-evaluation platform.",
    )
    parser.add_argument("--validate-suite", default=None, metavar="PATH")
    parser.add_argument("--import-suite", default=None, metavar="PATH")
    parser.add_argument("--approve-suite", default=None, metavar="UUID")
    parser.add_argument("--run-suite", default=None, metavar="UUID")
    parser.add_argument("--run-status", default=None, metavar="UUID")
    parser.add_argument("--compare-run", default=None, metavar="UUID")

    parser.add_argument("--code", default=None, help="Suite code (for --import-suite)")
    parser.add_argument("--name", default=None, help="Suite name (for --import-suite)")
    parser.add_argument(
        "--suite-type", default=None, choices=[t.value for t in QualityEvaluationSuiteType],
        help="Suite type (for --import-suite)",
    )
    parser.add_argument("--version", default=None, help="Suite version (for --import-suite)")
    parser.add_argument(
        "--mode", default=QualityEvaluationMode.DETERMINISTIC.value, choices=[m.value for m in QualityEvaluationMode],
        help="Evaluation mode (for --run-suite)",
    )
    parser.add_argument("--baseline", default=None, metavar="UUID", help="Baseline id (for --compare-run)")
    return parser


async def _validate_suite(path: str) -> None:
    raw_text = Path(path).read_text(encoding="utf-8")
    raw_lines = parse_jsonl(raw_text)
    cases = build_cases(raw_lines, suite_id=uuid4(), case_version="validation-only")
    dataset_hash = compute_dataset_hash(raw_lines)
    print(f"OK: {len(cases)} valid case(s). dataset_hash={dataset_hash}")


async def _import_suite(uow_factory, *, path: str, code: str, name: str, suite_type: str, version: str) -> None:
    async with uow_factory() as uow:
        existing = await uow.quality_evaluation_suites.get_suite_by_code_and_version(code=code, version=version)
        if existing is not None:
            print(f"error: suite '{code}' version '{version}' already exists ({existing.suite_id})", file=sys.stderr)
            return
        suite = await uow.quality_evaluation_suites.create_suite(
            QualityEvaluationSuite(
                code=code, name=name, suite_type=QualityEvaluationSuiteType(suite_type), version=version,
                case_count=0, dataset_hash="0" * 64,
            )
        )
        cases, dataset_hash = load_cases_from_file(Path(path), suite_id=suite.suite_id, case_version=version)
        for case in cases:
            await uow.quality_evaluation_suites.create_case(case)
        await uow.quality_evaluation_suites.update_suite_status(
            suite.suite_id, status=QualityEvaluationCaseStatus.DRAFT, case_count=len(cases),
        )
        await uow.commit()
    print(f"Imported suite {suite.suite_id} ({len(cases)} case(s), status=DRAFT). Approve it with --approve-suite before running.")


async def _approve_suite(service: QualityEvaluationService, *, suite_id: str) -> None:
    updated = await service.approve_suite(suite_id=UUID(suite_id))
    print(f"Approved suite {updated.suite_id} <{updated.code}> version {updated.version} ({updated.case_count} case(s)).")


async def _run_suite(service: QualityEvaluationService, default_configuration: EvaluationConfiguration, *, suite_id: str, mode: str) -> None:
    run = await service.create_run(
        suite_id=UUID(suite_id), mode=QualityEvaluationMode(mode), requested_by_account_id=None,
        idempotency_key=f"cli-{uuid4()}", configuration=default_configuration,
    )
    print(f"Created run {run.run_id} (mode={mode}). Executing...")
    summary = await service.execute_run(run_id=run.run_id)
    print(f"Run {summary.run_id}: status={summary.status.value} gate={summary.gate_decision.overall_status.value}")
    print(f"  cases: {summary.completed_case_count} completed, {summary.failed_case_count} failed, {summary.skipped_case_count} skipped")
    if summary.gate_decision.hard_gate_failures:
        print(f"  HARD GATE FAILURES: {', '.join(summary.gate_decision.hard_gate_failures)}")
    for name, score in sorted(summary.deterministic_metric_summary.items()):
        print(f"  {name}: {score:.3f}")


async def _run_status(uow_factory, *, run_id: str) -> None:
    async with uow_factory() as uow:
        run = await uow.quality_evaluation_runs.get_by_id(UUID(run_id))
    if run is None:
        print(f"error: run '{run_id}' not found", file=sys.stderr)
        return
    print(f"Run {run.run_id}: status={run.status.value} mode={run.mode.value}")
    print(f"  cases: {run.completed_case_count}/{run.case_count} completed, {run.failed_case_count} failed, {run.skipped_case_count} skipped")


async def _compare_run(service: QualityEvaluationService, *, run_id: str, baseline_id: str) -> None:
    report = await service.compare_with_baseline(run_id=UUID(run_id), baseline_id=UUID(baseline_id))
    print(f"Comparable: {report.comparable}. Overall: {report.overall_result.value}")
    for comparison in report.metric_comparisons:
        print(f"  {comparison.metric_name}: {comparison.result.value} (baseline={comparison.baseline_value}, candidate={comparison.candidate_value})")
    for note in report.notes:
        print(f"  note: {note}")


async def _run(args: argparse.Namespace) -> int:
    if args.validate_suite:
        try:
            await _validate_suite(args.validate_suite)
            return 0
        except DatasetValidationError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    database_settings = DatabaseSettings()
    embedding_settings = EmbeddingSettings()
    operations_settings = OperationsSettings()
    assert_embedding_provider_production_safe(embedding_settings=embedding_settings, operations_settings=operations_settings)

    engine = create_database_engine(database_settings)
    embedding_provider = (
        DeterministicFakeEmbeddingAdapter(dimension=embedding_settings.embedding_dimension)
        if embedding_settings.embedding_provider == "deterministic_fake"
        else SentenceTransformerEmbeddingAdapter(
            model_name=embedding_settings.embedding_model_name, dimension=embedding_settings.embedding_dimension,
            batch_size=embedding_settings.embedding_batch_size,
        )
    )
    try:
        session_factory = create_session_factory(engine)
        uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)  # noqa: E731
        composition = build_quality_evaluation_service(unit_of_work_factory=uow_factory, embedding_provider=embedding_provider)
        service = composition.service

        if args.import_suite:
            if not all([args.code, args.name, args.suite_type, args.version]):
                print("error: --import-suite requires --code, --name, --suite-type, and --version", file=sys.stderr)
                return 2
            await _import_suite(
                uow_factory, path=args.import_suite, code=args.code, name=args.name,
                suite_type=args.suite_type, version=args.version,
            )
            return 0

        if args.approve_suite:
            await _approve_suite(service, suite_id=args.approve_suite)
            return 0

        if args.run_suite:
            await _run_suite(service, composition.default_configuration, suite_id=args.run_suite, mode=args.mode)
            return 0

        if args.run_status:
            await _run_status(uow_factory, run_id=args.run_status)
            return 0

        if args.compare_run:
            if not args.baseline:
                print("error: --compare-run requires --baseline", file=sys.stderr)
                return 2
            await _compare_run(service, run_id=args.compare_run, baseline_id=args.baseline)
            return 0

        print(
            "error: specify one of --validate-suite, --import-suite, --approve-suite, "
            "--run-suite, --run-status, or --compare-run",
            file=sys.stderr,
        )
        return 2
    except StockResearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
