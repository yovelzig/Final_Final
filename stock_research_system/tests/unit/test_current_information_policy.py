"""Unit tests for `application.learning_orchestrator.current_information_policy` -
the spec G2D2 section 10 deterministic decision table. Pure function, no I/O."""

from __future__ import annotations

import pytest

from stock_research_core.application.learning_orchestrator.current_information_policy import (
    InformationNeed,
    classify_information_need,
)
from stock_research_core.domain.live_research.enums import ResearchScope


@pytest.mark.parametrize(
    "question,expected_need,expected_scope",
    [
        # -- static (spec's own examples) -----------------------------------------------
        ("What is diversification?", InformationNeed.STATIC, None),
        ("What is a 10-K?", InformationNeed.STATIC, None),
        ("How does compound interest work?", InformationNeed.STATIC, None),
        ("What is the current ratio?", InformationNeed.STATIC, None),  # stable term, not live-info
        ("What is the current yield on a bond?", InformationNeed.STATIC, None),
        # -- current information (spec's own examples) -----------------------------------------------
        ("What happened to Nvidia this week?", InformationNeed.CURRENT_INFORMATION, ResearchScope.NEWS_SCAN),
        (
            "What did Nvidia report in its latest filing?",
            InformationNeed.CURRENT_INFORMATION, ResearchScope.FINANCIAL_FILING_REVIEW,
        ),
        (
            "What is the current CEO situation at Apple?",
            InformationNeed.CURRENT_INFORMATION, ResearchScope.COMPANY_OVERVIEW,
        ),
        ("What's the latest analyst sentiment on Tesla?", InformationNeed.CURRENT_INFORMATION, ResearchScope.ANALYST_SENTIMENT),
        ("What happened in the market today?", InformationNeed.CURRENT_INFORMATION, ResearchScope.NEWS_SCAN),
        ("Any recent news on Microsoft?", InformationNeed.CURRENT_INFORMATION, ResearchScope.NEWS_SCAN),
        # -- Hebrew -----------------------------------------------
        ("מה זה גיוון תיק השקעות?", InformationNeed.STATIC, None),
        ("מה קרה למניית NVDA השבוע?", InformationNeed.CURRENT_INFORMATION, ResearchScope.NEWS_SCAN),
        ("מה קרה היום בשוק?", InformationNeed.CURRENT_INFORMATION, ResearchScope.NEWS_SCAN),
        ("מה קרה אתמול לאפל?", InformationNeed.CURRENT_INFORMATION, ResearchScope.NEWS_SCAN),
    ],
)
def test_classify_information_need(
    question: str, expected_need: InformationNeed, expected_scope: ResearchScope | None
) -> None:
    decision = classify_information_need(question)
    assert decision.need == expected_need
    assert decision.scope == expected_scope


def test_market_data_snapshot_is_never_a_possible_output() -> None:
    """No pattern table may ever resolve to MARKET_DATA_SNAPSHOT - spec
    section 10 explicitly excludes it (no provider port exists for it)."""
    probes = [
        "What is the current stock price of AAPL?", "What's the latest quote for TSLA?",
        "What happened to the market today?", "current analyst rating for NVDA",
    ]
    for question in probes:
        decision = classify_information_need(question)
        assert decision.scope != ResearchScope.MARKET_DATA_SNAPSHOT


def test_filing_review_takes_precedence_over_generic_recency_keywords() -> None:
    """A question matching both a specific filing-review phrase and a
    generic recency word ("latest") must resolve to the more specific
    scope, not NEWS_SCAN."""
    decision = classify_information_need("What did the latest filing say about revenue?")
    assert decision.scope == ResearchScope.FINANCIAL_FILING_REVIEW
