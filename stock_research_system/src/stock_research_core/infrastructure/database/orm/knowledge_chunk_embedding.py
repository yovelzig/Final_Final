"""ORM model for the `knowledge_chunk_embeddings` table.

The `embedding` vector column is deliberately never read into a domain
object - repositories only ever read `KnowledgeChunkEmbedding` lineage
fields (model, version, dimension) out of this row for anything that
crosses the infrastructure boundary. Raw vector values are only used
inside `knowledge_repository.py`'s pgvector similarity queries.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base

EMBEDDING_DIMENSION = 384


class KnowledgeChunkEmbeddingORM(Base):
    """Lineage and vector for one chunk's stored embedding."""

    __tablename__ = "knowledge_chunk_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "chunk_id", "embedding_model", "embedding_version",
            name="uq_knowledge_chunk_embeddings_chunk_model_version",
        ),
        Index("ix_knowledge_chunk_embeddings_chunk_id", "chunk_id"),
    )

    embedding_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_chunks.chunk_id", ondelete="CASCADE"), nullable=False
    )

    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(50), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
