"""Enumerations for the FinQuest historical market scenario engine.

This module has no knowledge of any infrastructure (databases, queues,
HTTP frameworks, pandas/NumPy/SciPy, yfinance, ML/LLM/RAG libraries,
orchestration engines, etc.).
"""

from enum import StrEnum


class MarketScenarioType(StrEnum):
    MARKET_REPLAY = "MARKET_REPLAY"
    BENCHMARK_COMPARISON = "BENCHMARK_COMPARISON"
    RISK_ASSESSMENT = "RISK_ASSESSMENT"
    HORIZON_SELECTION = "HORIZON_SELECTION"
    INFORMATION_SUFFICIENCY = "INFORMATION_SUFFICIENCY"
    DRAWDOWN_ANALYSIS = "DRAWDOWN_ANALYSIS"
    VOLATILITY_ANALYSIS = "VOLATILITY_ANALYSIS"


class MarketScenarioStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"
    INVALID = "INVALID"


class ScenarioSecurityRole(StrEnum):
    FOCAL = "FOCAL"
    BENCHMARK = "BENCHMARK"


class ScenarioRevealStatus(StrEnum):
    HIDDEN = "HIDDEN"
    AVAILABLE = "AVAILABLE"
    REVEALED = "REVEALED"


class ScenarioSubmissionStatus(StrEnum):
    STARTED = "STARTED"
    SUBMITTED = "SUBMITTED"
    GRADED = "GRADED"
    REVEALED = "REVEALED"
    ABANDONED = "ABANDONED"


class ScenarioDecisionQuality(StrEnum):
    POOR = "POOR"
    DEVELOPING = "DEVELOPING"
    GOOD = "GOOD"
    STRONG = "STRONG"


class ScenarioGenerationRunStatus(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ScenarioFeedbackCode(StrEnum):
    IDENTIFIED_RISK = "IDENTIFIED_RISK"
    IGNORED_RISK = "IGNORED_RISK"
    CONSIDERED_BENCHMARK = "CONSIDERED_BENCHMARK"
    IGNORED_BENCHMARK = "IGNORED_BENCHMARK"
    MATCHED_TIME_HORIZON = "MATCHED_TIME_HORIZON"
    MISMATCHED_TIME_HORIZON = "MISMATCHED_TIME_HORIZON"
    REQUESTED_MORE_INFORMATION = "REQUESTED_MORE_INFORMATION"
    OVERCONFIDENT_DECISION = "OVERCONFIDENT_DECISION"
    RECOGNIZED_UNCERTAINTY = "RECOGNIZED_UNCERTAINTY"
    CONCENTRATION_RISK = "CONCENTRATION_RISK"
    OUTCOME_BIAS_WARNING = "OUTCOME_BIAS_WARNING"
    GOOD_PROCESS_BAD_OUTCOME = "GOOD_PROCESS_BAD_OUTCOME"
    BAD_PROCESS_GOOD_OUTCOME = "BAD_PROCESS_GOOD_OUTCOME"
    GOOD_PROCESS_GOOD_OUTCOME = "GOOD_PROCESS_GOOD_OUTCOME"
    BAD_PROCESS_BAD_OUTCOME = "BAD_PROCESS_BAD_OUTCOME"


class ScenarioOutcomeDirection(StrEnum):
    """The realized direction of a scenario's focal return, past the
    documented +-1% "flat" threshold (see
    `application.market_scenarios.calculator`)."""

    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    FLAT = "FLAT"


class ScenarioExpectedDirection(StrEnum):
    """The directional stance a rubric option represents, used only for
    post-reveal *outcome alignment* display (never for grading decision
    quality). Not part of the spec's literal `ScenarioOptionRubric`
    field list, but required by the outcome-alignment rule ("compare
    [the expected stance] with the realized outcome") - see the
    `ScenarioOptionRubric` docstring in `models.py`.
    """

    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    INFORMATION_REQUIRED = "INFORMATION_REQUIRED"
