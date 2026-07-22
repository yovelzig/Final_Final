"""Persistence use cases: result models, repository ports, and the ingestion service."""

from stock_research_core.application.persistence.models import (
    IngestionRunRecord,
    IngestionRunStatus,
    PersistedMarketDataResult,
    PersistenceCounts,
)
from stock_research_core.application.persistence.service import (
    PersistedMarketDataIngestionService,
)

__all__ = [
    "IngestionRunRecord",
    "IngestionRunStatus",
    "PersistedMarketDataIngestionService",
    "PersistedMarketDataResult",
    "PersistenceCounts",
]
