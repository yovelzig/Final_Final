"""ORM models for `portfolio_risk_assessments` and its two association
tables (feedback codes, related skills).

`snapshot_id` is a plain, indexed UUID column, not a foreign key - see
the module docstring in `portfolio_valuation_snapshot.py` for why.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ARRAY, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class PortfolioRiskAssessmentORM(Base):
    """Deterministic, educational risk/diversification feedback for one snapshot."""

    __tablename__ = "portfolio_risk_assessments"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "policy_version", name="uq_portfolio_risk_assessments_snapshot_version"
        ),
        Index("ix_portfolio_risk_assessments_portfolio_id", "portfolio_id"),
        Index("ix_portfolio_risk_assessments_risk_level", "risk_level"),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("virtual_portfolios.portfolio_id", ondelete="RESTRICT"),
        nullable=False,
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)

    position_concentration_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    sector_concentration_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    diversification_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    drawdown_risk_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    volatility_risk_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    turnover_risk_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)

    summary: Mapped[str] = mapped_column(Text, nullable=False)
    #: Free-text educational sentences - soft, auxiliary content, not a
    #: normalized relationship (unlike feedback codes and related
    #: skills below), so a plain array is appropriate here.
    educational_feedback: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PortfolioRiskFeedbackCodeORM(Base):
    """Association table: the feedback codes attached to a risk assessment."""

    __tablename__ = "portfolio_risk_assessment_feedback_codes"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("portfolio_risk_assessments.assessment_id", ondelete="CASCADE"),
        primary_key=True,
    )
    feedback_code: Mapped[str] = mapped_column(String(50), primary_key=True)


class PortfolioRiskSkillORM(Base):
    """Association table: financial skills a risk assessment relates to."""

    __tablename__ = "portfolio_risk_assessment_skills"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("portfolio_risk_assessments.assessment_id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("financial_skills.skill_id", ondelete="RESTRICT"), primary_key=True
    )
