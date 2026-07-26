"""ORM model for the `claim_evidence_links` table (Phase G1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class ClaimEvidenceLinkORM(Base):
    """The sole persisted record of a claim<->evidence relationship.
    Maps to the domain `ClaimEvidenceLink`. One row per `(claim_id,
    evidence_id)` pair."""

    __tablename__ = "claim_evidence_links"
    __table_args__ = (
        UniqueConstraint(
            "claim_id", "evidence_id",
            name="uq_claim_evidence_links_claim_evidence",
        ),
        Index("ix_claim_evidence_links_claim_id", "claim_id"),
        Index("ix_claim_evidence_links_evidence_id", "evidence_id"),
    )

    link_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("research_claims.claim_id", ondelete="CASCADE"), nullable=False
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("evidence_items.evidence_id", ondelete="CASCADE"), nullable=False
    )
    stance: Mapped[str] = mapped_column(String(24), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
