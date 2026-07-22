"""ORM model for the `knowledge_chunks` table.

`content_tsv` (the GIN-indexed full-text expression `knowledge_chunk_tsvector
(heading_path, content)`) is intentionally not mapped here - it is a
database-side index expression, not a stored column, and repository
queries reference it via raw SQL (see `knowledge_repository.py`).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class KnowledgeChunkORM(Base):
    """One deterministically-produced, retrievable slice of a `KnowledgeDocument`."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "chunk_index", "chunking_version", name="uq_knowledge_chunks_document_index_version"
        ),
        Index("ix_knowledge_chunks_document_id", "document_id"),
        Index("ix_knowledge_chunks_available_at", "available_at"),
    )

    chunk_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_documents.document_id", ondelete="CASCADE"), nullable=False
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_token_count: Mapped[int] = mapped_column(Integer, nullable=False)

    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    chunking_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
