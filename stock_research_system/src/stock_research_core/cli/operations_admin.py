"""Administrative CLI for Phase 11 background jobs and n8n integration clients.

Create an n8n integration client (PowerShell) - prints the raw API key
exactly once; it is never stored or printed again:

    python -m stock_research_core.cli.operations_admin `
      --create-integration-client `
      --name "FinQuest n8n" `
      --allow-job TRACKED_MARKET_REFRESH `
      --allow-job PORTFOLIO_BATCH_VALUATION `
      --allow-job CURRICULUM_KNOWLEDGE_REFRESH `
      --allow-job RETRIEVAL_EVALUATION

List / revoke:

    python -m stock_research_core.cli.operations_admin --list-integration-clients
    python -m stock_research_core.cli.operations_admin --revoke-integration-client <UUID>

Create a job from a parameters file (JSON object only - never an
arbitrary Python expression):

    python -m stock_research_core.cli.operations_admin `
      --create-job TRACKED_MARKET_REFRESH `
      --parameters-file ".\\job-parameters.json" `
      --idempotency-key "manual-refresh-2026-07-20"

Job status / requeue:

    python -m stock_research_core.cli.operations_admin --job-status <UUID>
    python -m stock_research_core.cli.operations_admin --requeue-job <UUID>

This module is a composition root: it is the one place outside the
infrastructure layer allowed to import concrete adapters directly. It
never logs a raw integration API key.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from uuid import UUID

from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.domain.ai_tutor.enums import KnowledgeApprovalStatus  # noqa: F401 - re-exported for parameters-file authors
from stock_research_core.domain.models import utc_now
from stock_research_core.domain.operations.enums import (
    BackgroundJobPriority,
    BackgroundJobType,
    IntegrationClientStatus,
    JobTriggerSource,
)
from stock_research_core.domain.operations.models import IntegrationClient
from stock_research_core.infrastructure.ai_tutor.config import EmbeddingSettings
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import (
    DeterministicFakeEmbeddingAdapter,
)
from stock_research_core.infrastructure.ai_tutor.production_safety import (
    assert_embedding_provider_production_safe,
)
from stock_research_core.infrastructure.ai_tutor.sentence_transformer_embeddings import (
    SentenceTransformerEmbeddingAdapter,
)
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import create_database_engine, create_session_factory
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from stock_research_core.infrastructure.operations.celery_app import celery_app
from stock_research_core.infrastructure.operations.celery_queue import CeleryJobQueue
from stock_research_core.infrastructure.operations.config import OperationsSettings
from stock_research_core.infrastructure.operations.integration_auth import (
    generate_key_id,
    generate_raw_api_key,
    hash_api_key,
)
from stock_research_core.infrastructure.operations.redis_lock import RedisDistributedLock, build_redis_client
from stock_research_core.infrastructure.operations.registry_factory import build_operations_registry


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stock_research_core.cli.operations_admin",
        description="Administer FinQuest background jobs and n8n integration clients.",
    )
    parser.add_argument("--create-integration-client", action="store_true")
    parser.add_argument("--list-integration-clients", action="store_true")
    parser.add_argument("--revoke-integration-client", default=None, metavar="UUID")
    parser.add_argument("--create-job", default=None, metavar="JOB_TYPE", choices=[t.value for t in BackgroundJobType])
    parser.add_argument("--job-status", default=None, metavar="UUID")
    parser.add_argument("--requeue-job", default=None, metavar="UUID")

    parser.add_argument("--name", default=None, help="Integration client name (for --create-integration-client)")
    parser.add_argument(
        "--allow-job", action="append", default=[], metavar="JOB_TYPE", choices=[t.value for t in BackgroundJobType],
        help="Repeatable: a job type this integration client may trigger",
    )
    parser.add_argument("--parameters-file", default=None, metavar="PATH", help="A JSON object of job parameters")
    parser.add_argument("--idempotency-key", default=None)
    parser.add_argument(
        "--priority", default=BackgroundJobPriority.NORMAL.value, choices=[p.value for p in BackgroundJobPriority]
    )
    return parser


async def _create_integration_client(uow_factory, *, name: str, allowed_job_types: list[str]) -> None:
    key_id = generate_key_id()
    raw_key = generate_raw_api_key()
    client = IntegrationClient(
        name=name, key_id=key_id, api_key_hash=hash_api_key(raw_key),
        status=IntegrationClientStatus.ACTIVE, allowed_job_types=[BackgroundJobType(t) for t in allowed_job_types],
    )
    async with uow_factory() as uow:
        created = await uow.integration_clients.create(client)
        await uow.commit()
    print(f"Created integration client: {created.integration_id} <{created.name}>")
    print(f"  key_id:  {created.key_id}")
    print(f"  api_key: {raw_key}")
    print("\nThis is the ONLY time the raw API key is shown. Store it securely (e.g. an n8n credential) now.")


async def _list_integration_clients(uow_factory) -> None:
    async with uow_factory() as uow:
        clients = await uow.integration_clients.list_clients()
    print(f"{'integration_id':38} {'name':30} {'key_id':18} {'status':10} allowed_job_types")
    for client in clients:
        allowed = ",".join(job_type.value for job_type in client.allowed_job_types)
        print(f"{str(client.integration_id):38} {client.name:30} {client.key_id:18} {client.status.value:10} {allowed}")
    print(f"\n{len(clients)} client(s)")


async def _revoke_integration_client(uow_factory, *, integration_id: str) -> None:
    async with uow_factory() as uow:
        updated = await uow.integration_clients.set_status(UUID(integration_id), status=IntegrationClientStatus.REVOKED)
        await uow.commit()
    print(f"Revoked integration client: {updated.integration_id} <{updated.name}>")


async def _create_job(
    service: BackgroundJobService, *, job_type: str, parameters_file: str | None, idempotency_key: str | None,
    priority: str,
) -> None:
    if not idempotency_key:
        raise StockResearchError("--create-job requires --idempotency-key")
    raw_parameters: dict = {}
    if parameters_file:
        with open(parameters_file, "r", encoding="utf-8") as handle:
            raw_parameters = json.load(handle)
        if not isinstance(raw_parameters, dict):
            raise StockResearchError("--parameters-file must contain a single JSON object.")

    result = await service.create_job(
        job_type=BackgroundJobType(job_type), raw_parameters=raw_parameters, idempotency_key=idempotency_key,
        trigger_source=JobTriggerSource.ADMIN_CLI, priority=BackgroundJobPriority(priority),
        correlation_id="cli-create-job",
    )
    print(f"{'Created' if result.created else 'Existing (idempotent)'} job: {result.job.job_id} status={result.job.status.value}")


async def _job_status(service: BackgroundJobService, *, job_id: str) -> None:
    job = await service.get_job(UUID(job_id))
    attempts = await service.list_attempts(job.job_id)
    events = await service.list_events(job.job_id)
    print(f"job_id:        {job.job_id}")
    print(f"job_type:      {job.job_type.value}")
    print(f"status:        {job.status.value}")
    print(f"progress:      {job.progress_current}/{job.progress_total if job.progress_total is not None else '?'}")
    print(f"attempt_count: {job.attempt_count}/{job.maximum_attempts}")
    print(f"result:        {json.dumps(job.result_summary) if job.result_summary else '-'}")
    print(f"\nAttempts ({len(attempts)}):")
    for attempt in attempts:
        print(f"  #{attempt.attempt_number} {attempt.status.value} worker={attempt.worker_name} error={attempt.error_code}")
    print(f"\nEvents ({len(events)}):")
    for event in events:
        print(f"  {event.created_at.isoformat()} {event.event_type.value}: {event.message}")


async def _requeue_job(service: BackgroundJobService, *, job_id: str) -> None:
    job = await service.requeue_job(UUID(job_id))
    print(f"Requeued job: {job.job_id} status={job.status.value}")


async def _run(args: argparse.Namespace) -> int:
    database_settings = DatabaseSettings()
    embedding_settings = EmbeddingSettings()
    operations_settings = OperationsSettings()
    assert_embedding_provider_production_safe(
        embedding_settings=embedding_settings, operations_settings=operations_settings
    )

    engine = create_database_engine(database_settings)
    session_factory = create_session_factory(engine)
    uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)  # noqa: E731

    redis_client = build_redis_client(operations_settings.redis_url)
    embedding_provider = (
        DeterministicFakeEmbeddingAdapter(dimension=embedding_settings.embedding_dimension)
        if embedding_settings.embedding_provider == "deterministic_fake"
        else SentenceTransformerEmbeddingAdapter(
            model_name=embedding_settings.embedding_model_name, dimension=embedding_settings.embedding_dimension,
            batch_size=embedding_settings.embedding_batch_size,
        )
    )
    registry = build_operations_registry(
        unit_of_work_factory=uow_factory, embedding_provider=embedding_provider, chunker=HeadingAwareWordChunker()
    )
    service = BackgroundJobService(
        unit_of_work_factory=uow_factory, job_registry=registry, job_queue=CeleryJobQueue(celery_app),
        lock_port=RedisDistributedLock(redis_client),
    )

    try:
        if args.create_integration_client:
            if not args.name or not args.allow_job:
                print("error: --create-integration-client requires --name and at least one --allow-job", file=sys.stderr)
                return 2
            await _create_integration_client(uow_factory, name=args.name, allowed_job_types=args.allow_job)
            return 0

        if args.list_integration_clients:
            await _list_integration_clients(uow_factory)
            return 0

        if args.revoke_integration_client:
            await _revoke_integration_client(uow_factory, integration_id=args.revoke_integration_client)
            return 0

        if args.create_job:
            await _create_job(
                service, job_type=args.create_job, parameters_file=args.parameters_file,
                idempotency_key=args.idempotency_key, priority=args.priority,
            )
            return 0

        if args.job_status:
            await _job_status(service, job_id=args.job_status)
            return 0

        if args.requeue_job:
            await _requeue_job(service, job_id=args.requeue_job)
            return 0

        print(
            "error: specify one of --create-integration-client, --list-integration-clients, "
            "--revoke-integration-client, --create-job, --job-status, or --requeue-job",
            file=sys.stderr,
        )
        return 2
    except StockResearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        await redis_client.aclose()
        await engine.dispose()


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
