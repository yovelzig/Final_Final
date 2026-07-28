"""Unit tests for the deterministic Hebrew/English detection heuristic
(Phase G2E2A).

Pure function, no fakes/mocks needed - `detect_language` never performs
I/O and never consults anything but the raw text it is given.
"""

from __future__ import annotations

from stock_research_core.application.language.detection import detect_language
from stock_research_core.application.language.enums import DetectedLanguage


def test_pure_english_question_detected_as_english() -> None:
    assert detect_language("What is diversification?") == DetectedLanguage.EN


def test_pure_hebrew_question_detected_as_hebrew() -> None:
    assert detect_language("מה זה פיזור סיכונים בתיק השקעות?") == DetectedLanguage.HE


def test_mixed_text_with_hebrew_majority_detected_as_hebrew() -> None:
    # Ticker + year embedded in an otherwise-Hebrew question.
    assert detect_language("מה ההבדל בין ETF לבין S&P 500 ב-2024?") == DetectedLanguage.HE


def test_mixed_text_with_english_majority_detected_as_english() -> None:
    assert detect_language("What is the difference between an ETF and a תיק?") == DetectedLanguage.EN


def test_ticker_only_defaults_to_english() -> None:
    assert detect_language("NVDA") == DetectedLanguage.EN


def test_digits_and_punctuation_only_default_to_english() -> None:
    assert detect_language("2024, 12345!") == DetectedLanguage.EN


def test_empty_string_defaults_to_english() -> None:
    assert detect_language("") == DetectedLanguage.EN


def test_whitespace_only_defaults_to_english() -> None:
    assert detect_language("   \t\n  ") == DetectedLanguage.EN


def test_hebrew_scenario_question_detected_as_hebrew() -> None:
    assert detect_language("האם כדאי לי לקנות עכשיו את המניה הזו?") == DetectedLanguage.HE


def test_detection_is_a_pure_function_of_text_only() -> None:
    """No parameter exists through which a learner profile, account
    identifier, or security/ticker field could influence detection -
    this test documents that guarantee at the call-signature level by
    calling with only positional text, twice, and confirming determinism
    (same input always produces the same output)."""
    text = "מה זה תיק השקעות מפוזר?"
    assert detect_language(text) == detect_language(text) == DetectedLanguage.HE


def test_long_input_is_bounded_and_does_not_raise() -> None:
    long_hebrew = "פיזור סיכונים " * 500
    assert detect_language(long_hebrew) == DetectedLanguage.HE
