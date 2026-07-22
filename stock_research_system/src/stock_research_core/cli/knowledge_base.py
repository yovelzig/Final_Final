"""CLI for the FinQuest grounded-AI-tutor knowledge base.

Check status:

    python -m stock_research_core.cli.knowledge_base --status

Seed curriculum knowledge:

    python -m stock_research_core.cli.knowledge_base --seed-curriculum

Ingest a local file:

    python -m stock_research_core.cli.knowledge_base `
      --ingest-file "C:\\path\\to\\financial_education.pdf" `
      --source-title "Approved Financial Education Material" --approval APPROVED

Search:

    python -m stock_research_core.cli.knowledge_base `
      --search "Why does diversification reduce concentration risk?" --top-k 5

This module is a composition root: it is the one place outside the
infrastructure layer allowed to import concrete adapters directly.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.application.ai_tutor.knowledge_ingestion import KnowledgeIngestionService
from stock_research_core.application.ai_tutor.models import TutorContext
from stock_research_core.application.ai_tutor.ports import EmbeddingPort
from stock_research_core.application.ai_tutor.retrieval import DEFAULT_TOP_K, HybridKnowledgeRetriever
from stock_research_core.application.exceptions import StockResearchError, UnsupportedDocumentError
from stock_research_core.domain.ai_tutor.enums import KnowledgeApprovalStatus, TutorContextType
from stock_research_core.infrastructure.ai_tutor.config import EmbeddingSettings
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import (
    DeterministicFakeEmbeddingAdapter,
)
from stock_research_core.infrastructure.ai_tutor.sentence_transformer_embeddings import (
    SentenceTransformerEmbeddingAdapter,
)
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import create_database_engine, create_session_factory
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


def _build_embedding_provider(settings: EmbeddingSettings) -> EmbeddingPort:
    if settings.embedding_provider == "deterministic_fake":
        # Dev/test-only: see infrastructure.ai_tutor.deterministic_fake_embeddings.
        return DeterministicFakeEmbeddingAdapter(dimension=settings.embedding_dimension)
    return SentenceTransformerEmbeddingAdapter(
        model_name=settings.embedding_model_name,
        dimension=settings.embedding_dimension,
        batch_size=settings.embedding_batch_size,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stock_research_core.cli.knowledge_base",
        description="Manage the FinQuest grounded-AI-tutor knowledge base.",
    )
    parser.add_argument("--status", action="store_true", help="Print knowledge-base status")
    parser.add_argument("--seed-curriculum", action="store_true", help="Ingest the published curriculum")
    parser.add_argument("--ingest-file", metavar="PATH", default=None, help="Ingest a local .md/.txt/.pdf/.docx file")
    parser.add_argument("--source-title", default=None, help="Source title for --ingest-file")
    parser.add_argument(
        "--approval", default="DRAFT", choices=[status.value for status in KnowledgeApprovalStatus],
        help="Approval status for --ingest-file (default DRAFT - not automatically retrievable)",
    )
    parser.add_argument("--search", metavar="QUERY", default=None, help="Run a hybrid search query")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Number of results for --search")
    return parser


async def _print_status(uow_factory, engine, embedding_settings: EmbeddingSettings) -> None:
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector', 'timescaledb')")
        )
        extensions = {row[0]: row[1] for row in result.all()}

    print("Knowledge base status:")
    print(f"  vector extension:      {extensions.get('vector', 'NOT INSTALLED')}")
    print(f"  timescaledb extension: {extensions.get('timescaledb', 'NOT INSTALLED')}")
    print(f"  embedding provider:    {embedding_settings.embedding_provider}")
    print(f"  embedding model:       {embedding_settings.embedding_model_name}")
    print(f"  embedding dimension:   {embedding_settings.embedding_dimension}")

    async with uow_factory() as uow:
        print(f"  sources:               {await uow.knowledge.count_sources()}")
        print(f"  approved documents:    {await uow.knowledge.count_approved_documents()}")
        print(f"  chunks:                {await uow.knowledge.count_chunks()}")
        print(f"  embeddings:            {await uow.knowledge.count_embeddings()}")
        print(f"  unresolved gaps:       {len(await uow.tutor_knowledge_gaps.list_unresolved_gaps())}")
        print("  latest ingestion runs:")
        for run in await uow.knowledge.list_recent_ingestion_runs(limit=5):
            print(
                f"    - {run.started_at.date()} status={run.status.value} "
                f"documents={run.documents_processed} chunks={run.chunks_created} "
                f"embeddings={run.embeddings_created}"
            )


async def _seed_curriculum(ingestion_service: KnowledgeIngestionService) -> None:
    summary = await ingestion_service.ingest_curriculum()
    print("Curriculum ingestion complete:")
    print(f"  Run status:             {summary.run.status.value}")
    print(f"  Sources created:        {summary.sources_created}")
    print(f"  Sources updated:        {summary.sources_updated}")
    print(f"  Documents created:      {summary.documents_created}")
    print(f"  Documents archived:     {summary.documents_archived}")
    print(f"  Documents unchanged:    {summary.documents_skipped_unchanged}")
    print(f"  Chunks created:         {summary.chunks_created}")
    print(f"  Embeddings created:     {summary.embeddings_created}")


async def _ingest_file(
    ingestion_service: KnowledgeIngestionService, file_path: Path, source_title: str, approval: str
) -> None:
    summary = await ingestion_service.ingest_local_document(
        file_path=file_path,
        source_title=source_title,
        approval_status=KnowledgeApprovalStatus(approval),
        skill_ids=[],
        available_at=datetime.now(timezone.utc),
    )
    print(f"Ingested '{file_path.name}':")
    print(f"  Documents created:      {summary.documents_created}")
    print(f"  Documents unchanged:    {summary.documents_skipped_unchanged}")
    print(f"  Chunks created:         {summary.chunks_created}")
    print(f"  Embeddings created:     {summary.embeddings_created}")
    if approval == KnowledgeApprovalStatus.DRAFT.value:
        print("  Note: ingested as DRAFT - not retrievable until explicitly approved.")


async def _search(retriever: HybridKnowledgeRetriever, query: str, top_k: int) -> None:
    from uuid import uuid4

    context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=uuid4())
    _run, candidates = await retriever.retrieve(query=query, context=context, top_k=top_k)
    if not candidates:
        print("No results.")
        return
    print(f"Top {len(candidates)} results for: {query!r}\n")
    for rank, candidate in enumerate(candidates, start=1):
        heading = " > ".join(candidate.chunk.heading_path) or "(no heading)"
        excerpt = candidate.chunk.content[:160].replace("\n", " ")
        print(f"[{rank}] score={candidate.combined_score:.4f} source={candidate.source.title!r}")
        print(f"    document={candidate.document.title!r} heading={heading!r}")
        print(f"    available_at={candidate.document.available_at.date()} excerpt={excerpt!r}\n")


async def _run(args: argparse.Namespace) -> int:
    settings = DatabaseSettings()
    embedding_settings = EmbeddingSettings()
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)  # noqa: E731
        embedding_provider = _build_embedding_provider(embedding_settings)
        chunker = HeadingAwareWordChunker()
        ingestion_service = KnowledgeIngestionService(
            unit_of_work_factory=uow_factory, chunker=chunker, embedding_provider=embedding_provider
        )
        retriever = HybridKnowledgeRetriever(unit_of_work_factory=uow_factory, embedding_provider=embedding_provider)

        if args.status:
            await _print_status(uow_factory, engine, embedding_settings)

        if args.seed_curriculum:
            await _seed_curriculum(ingestion_service)

        if args.ingest_file:
            if not args.source_title:
                print("error: --ingest-file requires --source-title", file=sys.stderr)
                return 2
            await _ingest_file(ingestion_service, Path(args.ingest_file), args.source_title, args.approval)

        if args.search:
            await _search(retriever, args.search, args.top_k)

        if not any((args.status, args.seed_curriculum, args.ingest_file, args.search)):
            print("error: specify --status, --seed-curriculum, --ingest-file, or --search", file=sys.stderr)
            return 2

        return 0
    except UnsupportedDocumentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
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
