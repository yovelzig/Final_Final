"""PostgreSQL integration tests: migration 0006's `vector` extension,
HNSW index, and lexical GIN index.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_KNOWLEDGE_TABLES = {
    "knowledge_sources", "knowledge_documents", "knowledge_document_skills", "knowledge_chunks",
    "knowledge_chunk_embeddings", "knowledge_ingestion_runs",
}
_TUTOR_TABLES = {
    "tutor_conversations", "tutor_messages", "tutor_answers", "tutor_answer_citations",
    "tutor_guardrail_decisions", "tutor_retrieval_runs", "tutor_retrieval_run_chunks",
    "tutor_knowledge_gaps", "tutor_knowledge_gap_skills",
}


async def test_all_ai_tutor_tables_exist(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        table_names = await connection.run_sync(lambda sync_conn: sa_inspect(sync_conn).get_table_names())
    assert (_KNOWLEDGE_TABLES | _TUTOR_TABLES) <= set(table_names)


async def test_vector_and_timescaledb_extensions_installed(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        result = await connection.execute(
            text("SELECT extname FROM pg_extension WHERE extname IN ('vector', 'timescaledb')")
        )
        installed = {row[0] for row in result.all()}
    assert installed == {"vector", "timescaledb"}


async def test_hnsw_index_exists_on_embedding_column(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE tablename = 'knowledge_chunk_embeddings' "
                "AND indexname = 'ix_knowledge_chunk_embeddings_hnsw_cosine'"
            )
        )
        row = result.scalar_one_or_none()
    assert row is not None
    assert "hnsw" in row.lower()
    assert "vector_cosine_ops" in row


async def test_lexical_gin_index_exists_on_chunks(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE tablename = 'knowledge_chunks' "
                "AND indexname = 'ix_knowledge_chunks_content_tsv'"
            )
        )
        row = result.scalar_one_or_none()
    assert row is not None
    assert "gin" in row.lower()


async def test_cosine_distance_query_executes(test_engine: AsyncEngine) -> None:
    """A raw pgvector `<=>` query runs without error against an empty table."""
    async with test_engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT chunk_id FROM knowledge_chunk_embeddings "
                "ORDER BY embedding <=> (SELECT ('[' || repeat('0,', 383) || '0]')::vector) LIMIT 1"
            )
        )
        assert result.all() == []


async def test_immutable_tsvector_function_exists(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT provolatile FROM pg_proc WHERE proname = 'knowledge_chunk_tsvector'"
            )
        )
        row = result.scalar_one_or_none()
    assert row in ("i", b"i")  # 'i' == IMMUTABLE
