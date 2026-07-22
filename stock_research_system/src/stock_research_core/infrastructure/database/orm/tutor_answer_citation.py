"""ORM model for the `tutor_answer_citations` table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class TutorAnswerCitationORM(Base):
    """One citation on a `TutorAnswer`, pointing to an exact retrieved chunk."""

    __tablename__ = "tutor_answer_citations"
    __table_args__ = (
        UniqueConstraint("answer_id", "citation_number", name="uq_tutor_answer_citations_answer_number"),
        UniqueConstraint("answer_id", "chunk_id", name="uq_tutor_answer_citations_answer_chunk"),
        Index("ix_tutor_answer_citations_answer_id", "answer_id"),
    )

    citation_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    answer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tutor_answers.answer_id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_chunks.chunk_id", ondelete="RESTRICT"), nullable=False
    )

    citation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    quoted_excerpt: Mapped[str] = mapped_column(String(500), nullable=False)
    source_title: Mapped[str] = mapped_column(String(300), nullable=False)
    document_title: Mapped[str] = mapped_column(String(300), nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
