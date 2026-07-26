"""ORM model for the `evidence_items` table (Phase G1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class EvidenceItemORM(Base):
    """An immutable, provenance-carrying evidence record. Maps to the
    domain `EvidenceItem`. Never updated after insert - a re-fetch that
    changes any hashed field produces a new row."""

    __tablename__ = "evidence_items"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "content_hash",
            name="uq_evidence_items_run_content",
        ),
        Index("ix_evidence_items_run_id", "run_id"),
        Index("ix_evidence_items_source_type", "source_type"),
    )

    evidence_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    #: Evidence has no meaning outside the run that gathered it - CASCADE
    #: is appropriate here, unlike the RESTRICT used for domain data
    #: referenced from elsewhere (e.g. `securities`).
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("research_runs.run_id", ondelete="CASCADE"), nullable=False
    )

    source_type: Mapped[str] = mapped_column(String(48), nullable=False)
    classification: Mapped[str] = mapped_column(String(16), nullable=False)

    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    official_identifier: Mapped[str | None] = mapped_column(String(200), nullable=True)

    source_title: Mapped[str] = mapped_column(String(1000), nullable=False)
    publisher: Mapped[str] = mapped_column(String(250), nullable=False)

    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    raw_excerpt: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    normalized_text: Mapped[str | None] = mapped_column(String(5000), nullable=True)

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    structured_facts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
