"""Seed the FinQuest grounded-AI-tutor knowledge base from the already-stored
published curriculum (lessons and active exercise explanations).

Deterministic and idempotent: every document ID is derived via
`uuid.uuid5` from `(logical identity, content hash)`
(`KnowledgeIngestionService._content_derived_id`), so re-running this
script maps unchanged content to the same rows (a no-op) while changed
content creates a new document version and archives the previous one -
nothing is ever silently deleted. Requires
`scripts/seed_learning_curriculum.py` to have been run first (this
script only reads already-stored lessons/exercises, it never creates
curriculum itself).

Usage (PowerShell):

    python scripts/seed_learning_curriculum.py
    python scripts/seed_finquest_knowledge_base.py

By default this uses the deterministic, dev/test-only fake embedding
adapter (no model download, no `sentence-transformers` dependency
required) - pass `--real-embeddings` to use the configured local
sentence-transformer model instead (requires
`pip install -e ".[ai_tutor]"`).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.application.ai_tutor.knowledge_ingestion import KnowledgeIngestionService
from stock_research_core.application.ai_tutor.ports import EmbeddingPort
from stock_research_core.application.exceptions import StockResearchError
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


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/seed_finquest_knowledge_base.py",
        description="Ingest the published FinQuest curriculum into the grounded-AI-tutor knowledge base.",
    )
    parser.add_argument(
        "--real-embeddings", action="store_true",
        help="Use the configured local sentence-transformer model instead of the deterministic fake adapter "
        "(requires 'pip install -e \".[ai_tutor]\"').",
    )
    parser.add_argument("--no-lessons", dest="include_lessons", action="store_false", default=True)
    parser.add_argument("--no-exercise-explanations", dest="include_exercise_explanations", action="store_false", default=True)
    return parser


def _build_embedding_provider(*, use_real_embeddings: bool) -> EmbeddingPort:
    if not use_real_embeddings:
        return DeterministicFakeEmbeddingAdapter()
    settings = EmbeddingSettings()
    return SentenceTransformerEmbeddingAdapter(
        model_name=settings.embedding_model_name,
        dimension=settings.embedding_dimension,
        batch_size=settings.embedding_batch_size,
    )


async def _run(args: argparse.Namespace) -> int:
    settings = DatabaseSettings()
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)  # noqa: E731

        embedding_provider = _build_embedding_provider(use_real_embeddings=args.real_embeddings)
        ingestion_service = KnowledgeIngestionService(
            unit_of_work_factory=uow_factory,
            chunker=HeadingAwareWordChunker(),
            embedding_provider=embedding_provider,
        )

        print(f"Seeding FinQuest knowledge base (embedding provider: {embedding_provider.model_name})...")
        summary = await ingestion_service.ingest_curriculum(
            include_lessons=args.include_lessons,
            include_exercise_explanations=args.include_exercise_explanations,
        )

        print("Done.")
        print(f"  Run status:             {summary.run.status.value}")
        print(f"  Sources created:        {summary.sources_created}")
        print(f"  Sources updated:        {summary.sources_updated}")
        print(f"  Documents created:      {summary.documents_created}")
        print(f"  Documents archived:     {summary.documents_archived}")
        print(f"  Documents unchanged:    {summary.documents_skipped_unchanged}")
        print(f"  Chunks created:         {summary.chunks_created}")
        print(f"  Embeddings created:     {summary.embeddings_created}")
        return 0
    except StockResearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


def main() -> None:
    args = _build_arg_parser().parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
