"""stock_research_core: shared domain models and service contracts.

All future components of the AI stock research system must accept and
return the domain objects exported from this package instead of passing
unvalidated dictionaries around.
"""

from stock_research_core.domain.models import (
    AlertCandidate,
    AnalysisRequest,
    AnalysisResponse,
    CriticalPoint,
    DataFreshness,
    EventMarketOutcome,
    EvidenceItem,
    ExtractedEvent,
    HorizonPrediction,
    MarketBar,
    RiskAssessment,
    Security,
    SourceDocument,
    TrackedSecurity,
)

__all__ = [
    "AlertCandidate",
    "AnalysisRequest",
    "AnalysisResponse",
    "CriticalPoint",
    "DataFreshness",
    "EventMarketOutcome",
    "EvidenceItem",
    "ExtractedEvent",
    "HorizonPrediction",
    "MarketBar",
    "RiskAssessment",
    "Security",
    "SourceDocument",
    "TrackedSecurity",
]
