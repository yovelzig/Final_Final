"""SQLAlchemy 2.x declarative base shared by all ORM models."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base class for all Phase 3 ORM models."""
