"""ORM model for the `research_claims` table (Phase G1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class ResearchClaimORM(Base):
    """A single normalized claim derived from a `ResearchRun`'s evidence.
    Maps to the domain `ResearchClaim`.

    Scalar claim data only - no evidence-ID columns exist or have ever
    existed here. The claim<->evidence relationship lives exclusively in
    `claim_evidence_links` (see `ClaimEvidenceLinkORM`).
    """

    __tablename__ = "research_claims"
    __table_args__ = (
        Index("ix_research_claims_run_id", "run_id"),
        Index("ix_research_claims_status", "status"),
    )

    claim_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("research_runs.run_id", ondelete="CASCADE"), nullable=False
    )

    claim_text: Mapped[str] = mapped_column(String(2000), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
