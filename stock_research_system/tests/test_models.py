"""Unit tests for stock_research_core domain models."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from stock_research_core.domain.enums import DocumentType, Exchange, PredictionLabel
from stock_research_core.domain.models import (
    AnalysisRequest,
    HorizonPrediction,
    MarketBar,
    Security,
    SourceDocument,
)

UTC_NOW = datetime.now(timezone.utc)


def _market_bar(**overrides: object) -> dict:
    defaults: dict = {
        "security_id": uuid4(),
        "timestamp": UTC_NOW,
        "open": 100.0,
        "high": 110.0,
        "low": 95.0,
        "close": 105.0,
        "adjusted_close": 105.0,
        "volume": 1_000,
        "source_name": "test-source",
    }
    defaults.update(overrides)
    return defaults


def _horizon_prediction(**overrides: object) -> dict:
    defaults: dict = {
        "security_id": uuid4(),
        "as_of": UTC_NOW,
        "horizon_days": 20,
        "label": PredictionLabel.OUTPERFORM,
        "probability_outperform": 0.60,
        "probability_neutral": 0.25,
        "probability_underperform": 0.15,
        "confidence_score": 0.8,
        "sample_size": 500,
        "model_name": "baseline",
        "model_version": "0.1.0",
        "feature_set_version": "0.1.0",
        "data_cutoff_at": UTC_NOW,
    }
    defaults.update(overrides)
    return defaults


def test_security_ticker_is_normalized_to_uppercase() -> None:
    security = Security(
        ticker="nvda",
        company_name="NVIDIA Corporation",
        exchange=Exchange.NASDAQ,
    )
    assert security.ticker == "NVDA"


def test_analysis_request_requires_ticker_or_company_name() -> None:
    with pytest.raises(ValidationError):
        AnalysisRequest(user_question="What is the outlook for this company?")


def test_analysis_request_normalizes_horizons() -> None:
    request = AnalysisRequest(
        ticker="AAPL",
        user_question="What is the outlook for this company?",
        requested_horizons_days=[60, 5, 20, 5],
    )
    assert request.requested_horizons_days == [5, 20, 60]


def test_market_bar_rejects_high_lower_than_close() -> None:
    with pytest.raises(ValidationError):
        MarketBar(**_market_bar(high=100.0, close=105.0))


def test_market_bar_rejects_low_greater_than_open_or_close() -> None:
    with pytest.raises(ValidationError):
        MarketBar(**_market_bar(low=101.0, open=100.0, close=105.0, high=110.0))


def test_horizon_prediction_accepts_valid_probabilities() -> None:
    prediction = HorizonPrediction(**_horizon_prediction())
    assert prediction.probability_outperform == 0.60
    assert prediction.probability_neutral == 0.25
    assert prediction.probability_underperform == 0.15


def test_horizon_prediction_rejects_probabilities_summing_above_one() -> None:
    with pytest.raises(ValidationError):
        HorizonPrediction(
            **_horizon_prediction(
                probability_outperform=0.70,
                probability_neutral=0.40,
                probability_underperform=0.15,
            )
        )


def test_horizon_prediction_allows_insufficient_evidence_without_probabilities() -> None:
    prediction = HorizonPrediction(
        **_horizon_prediction(
            label=PredictionLabel.INSUFFICIENT_EVIDENCE,
            probability_outperform=None,
            probability_neutral=None,
            probability_underperform=None,
        )
    )
    assert prediction.label == PredictionLabel.INSUFFICIENT_EVIDENCE
    assert prediction.probability_outperform is None


def test_source_document_rejects_source_quality_above_one() -> None:
    with pytest.raises(ValidationError):
        SourceDocument(
            security_id=uuid4(),
            document_type=DocumentType.NEWS,
            title="Example headline",
            source_name="Example Source",
            published_at=UTC_NOW,
            raw_text="Some article body text.",
            content_hash="0123456789abcdef",
            source_quality=1.5,
        )


def test_extra_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Security(
            ticker="MSFT",
            company_name="Microsoft Corporation",
            exchange=Exchange.NASDAQ,
            unknown_field="not allowed",
        )
