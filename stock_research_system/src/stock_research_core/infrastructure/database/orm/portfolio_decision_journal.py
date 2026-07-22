"""ORM models for `portfolio_decision_journal_entries` and its three
association tables (risk tags, information items, assumptions).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class PortfolioDecisionJournalEntryORM(Base):
    """A learner's documented rationale for a trade or a deliberate non-trade decision."""

    __tablename__ = "portfolio_decision_journal_entries"
    __table_args__ = (
        UniqueConstraint(
            "related_transaction_id", name="uq_portfolio_journal_related_transaction"
        ),
        Index("ix_portfolio_journal_portfolio_decision_at", "portfolio_id", "decision_at"),
        Index("ix_portfolio_journal_learner_decision_at", "learner_id", "decision_at"),
        Index("ix_portfolio_journal_action", "action"),
        Index("ix_portfolio_journal_confidence", "confidence"),
    )

    journal_entry_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("virtual_portfolios.portfolio_id", ondelete="RESTRICT"),
        nullable=False,
    )
    learner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"), nullable=False
    )
    security_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("securities.security_id", ondelete="RESTRICT"), nullable=True
    )
    related_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("portfolio_transactions.transaction_id", ondelete="RESTRICT"),
        nullable=True,
    )

    action: Mapped[str] = mapped_column(String(20), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    expected_horizon_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PortfolioJournalRiskTagORM(Base):
    """Association table: normalized risk tags documented for a journal entry."""

    __tablename__ = "portfolio_decision_journal_risk_tags"

    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("portfolio_decision_journal_entries.journal_entry_id", ondelete="CASCADE"),
        primary_key=True,
    )
    risk_tag: Mapped[str] = mapped_column(String(100), primary_key=True)


class PortfolioJournalInformationItemORM(Base):
    """Association table: normalized information items considered for a journal entry."""

    __tablename__ = "portfolio_decision_journal_information_items"

    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("portfolio_decision_journal_entries.journal_entry_id", ondelete="CASCADE"),
        primary_key=True,
    )
    information_item: Mapped[str] = mapped_column(String(500), primary_key=True)


class PortfolioJournalAssumptionORM(Base):
    """Association table: normalized assumptions documented for a journal entry."""

    __tablename__ = "portfolio_decision_journal_assumptions"

    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("portfolio_decision_journal_entries.journal_entry_id", ondelete="CASCADE"),
        primary_key=True,
    )
    assumption: Mapped[str] = mapped_column(String(500), primary_key=True)
