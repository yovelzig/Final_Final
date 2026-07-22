"""ORM model for the `knowledge_ingestion_runs` table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class KnowledgeIngestionRunORM(Base):
    """Auditable record of one knowledge-ingestion run."""

    __tablename__ = "knowledge_ingestion_runs"
    __table_args__ = (
        Index("ix_knowledge_ingestion_runs_source_id", "source_id"),
        Index("ix_knowledge_ingestion_runs_started_at", "started_at"),
        Index("ix_knowledge_ingestion_runs_status", "status"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_sources.source_id", ondelete="RESTRICT"), nullable=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_documents.document_id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    documents_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunks_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embeddings_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    chunking_version: Mapped[str] = mapped_column(String(50), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(50), nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
