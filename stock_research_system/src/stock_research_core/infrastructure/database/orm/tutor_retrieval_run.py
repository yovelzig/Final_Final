"""ORM models for `tutor_retrieval_runs` and its returned-chunks association table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class TutorRetrievalRunORM(Base):
    """An audit record of one retrieval query issued on behalf of the tutor."""

    __tablename__ = "tutor_retrieval_runs"
    __table_args__ = (
        Index("ix_tutor_retrieval_runs_conversation_created", "conversation_id", "created_at"),
    )

    retrieval_run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tutor_conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)

    method: Mapped[str] = mapped_column(String(20), nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    knowledge_cutoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    retrieval_policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(50), nullable=False)

    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TutorRetrievalRunChunkORM(Base):
    """Association: the ordered, scored chunks returned by one retrieval run."""

    __tablename__ = "tutor_retrieval_run_chunks"
    __table_args__ = (Index("ix_tutor_retrieval_run_chunks_chunk_id", "chunk_id"),)

    retrieval_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tutor_retrieval_runs.retrieval_run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_chunks.chunk_id", ondelete="RESTRICT"), nullable=False
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
