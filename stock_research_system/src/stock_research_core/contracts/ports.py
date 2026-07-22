"""Abstract service contracts ("ports") for the stock research system.

These `Protocol` definitions describe what each component does, not how it
does it. No implementations live here. All methods that may later reach an
external system (network, database, file system, message queue, etc.) are
asynchronous so that future implementations can be built without changing
the contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from stock_research_core.domain.models import (
    AlertCandidate,
    CriticalPoint,
    EventMarketOutcome,
    EvidenceItem,
    ExtractedEvent,
    HorizonPrediction,
    MarketBar,
    Security,
    SourceDocument,
)


class SecurityResolverPort(Protocol):
    """Resolves a ticker and/or company name to a canonical Security."""

    async def resolve(
        self,
        ticker: str | None,
        company_name: str | None,
    ) -> Security: ...


class DocumentIngestionPort(Protocol):
    """Fetches source documents for a security."""

    async def fetch_historical(
        self,
        security: Security,
        start_at: datetime,
        end_at: datetime,
    ) -> list[SourceDocument]: ...

    async def fetch_incremental(
        self,
        security: Security,
        since: datetime,
    ) -> list[SourceDocument]: ...


class MarketDataPort(Protocol):
    """Fetches market price bars for a security."""

    async def fetch_bars(
        self,
        security: Security,
        start_at: datetime,
        end_at: datetime,
        interval: str = "1d",
    ) -> list[MarketBar]: ...


class EventExtractorPort(Protocol):
    """Extracts structured financial events from a source document."""

    async def extract(
        self,
        document: SourceDocument,
    ) -> list[ExtractedEvent]: ...


class MarketAnalyzerPort(Protocol):
    """Analyzes market bars for critical points and event impact."""

    async def detect_critical_points(
        self,
        security: Security,
        bars: list[MarketBar],
    ) -> list[CriticalPoint]: ...

    async def measure_event_impact(
        self,
        event: ExtractedEvent,
        bars: list[MarketBar],
        benchmark_bars: list[MarketBar],
        horizons_days: list[int],
    ) -> list[EventMarketOutcome]: ...


class PredictionPort(Protocol):
    """Produces horizon predictions for a security as of a point in time."""

    async def predict(
        self,
        security: Security,
        as_of: datetime,
        horizons_days: list[int],
    ) -> list[HorizonPrediction]: ...


class KnowledgeStorePort(Protocol):
    """Indexes and retrieves evidence supporting analysis claims."""

    async def index_documents(
        self,
        documents: list[SourceDocument],
        events: list[ExtractedEvent],
    ) -> None: ...

    async def retrieve_evidence(
        self,
        security: Security,
        query: str,
        limit: int = 10,
    ) -> list[EvidenceItem]: ...


class StructuredStorePort(Protocol):
    """Persists structured domain objects."""

    async def save_security(
        self,
        security: Security,
    ) -> None: ...

    async def save_documents(
        self,
        documents: list[SourceDocument],
    ) -> None: ...

    async def save_events(
        self,
        events: list[ExtractedEvent],
    ) -> None: ...

    async def save_market_bars(
        self,
        bars: list[MarketBar],
    ) -> None: ...

    async def save_critical_points(
        self,
        points: list[CriticalPoint],
    ) -> None: ...

    async def save_event_outcomes(
        self,
        outcomes: list[EventMarketOutcome],
    ) -> None: ...

    async def save_predictions(
        self,
        predictions: list[HorizonPrediction],
    ) -> None: ...


class AlertingPort(Protocol):
    """Evaluates prediction changes and notifies about resulting alerts."""

    async def evaluate(
        self,
        security_id: UUID,
        current_predictions: list[HorizonPrediction],
        previous_predictions: list[HorizonPrediction],
        new_events: list[ExtractedEvent],
    ) -> list[AlertCandidate]: ...

    async def notify(
        self,
        alerts: list[AlertCandidate],
    ) -> None: ...
