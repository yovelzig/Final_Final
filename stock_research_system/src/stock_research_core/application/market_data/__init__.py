"""Market-data ingestion use cases: result models and the ingestion service."""

from stock_research_core.application.market_data.models import (
    DataQualityIssue,
    MarketDataIngestionResult,
    MarketDataQualityReport,
)
from stock_research_core.application.market_data.service import (
    MarketDataIngestionService,
    QualityAwareMarketDataPort,
)

__all__ = [
    "DataQualityIssue",
    "MarketDataIngestionResult",
    "MarketDataIngestionService",
    "MarketDataQualityReport",
    "QualityAwareMarketDataPort",
]
