"""Unit tests for `application.shared.text_safety.SharedTextSafetyValidator`."""

from __future__ import annotations

from stock_research_core.application.shared.text_safety import SharedTextSafetyValidator


def test_plain_text_is_unchanged() -> None:
    validator = SharedTextSafetyValidator()
    decision = validator.validate("Diversification spreads risk across assets.")
    assert decision.bounded_text == "Diversification spreads risk across assets."
    assert decision.issue_codes == []


def test_text_over_the_limit_is_truncated() -> None:
    validator = SharedTextSafetyValidator(max_characters=10)
    decision = validator.validate("x" * 100)
    assert decision.bounded_text == "x" * 10
    assert "TEXT_TRUNCATED" in decision.issue_codes


def test_script_tag_is_stripped() -> None:
    validator = SharedTextSafetyValidator()
    decision = validator.validate("Hello <script>alert('x')</script> world")
    assert "<script" not in decision.bounded_text.lower()
    assert "UNSAFE_MARKUP_STRIPPED" in decision.issue_codes


def test_javascript_uri_is_stripped() -> None:
    validator = SharedTextSafetyValidator()
    decision = validator.validate('Click <a href="javascript:alert(1)">here</a>')
    assert "javascript:" not in decision.bounded_text.lower()
    assert "UNSAFE_MARKUP_STRIPPED" in decision.issue_codes


def test_inline_event_handler_is_stripped() -> None:
    validator = SharedTextSafetyValidator()
    decision = validator.validate('<img src=x onerror="alert(1)">')
    assert "onerror" not in decision.bounded_text.lower()
    assert "UNSAFE_MARKUP_STRIPPED" in decision.issue_codes


def test_both_issues_can_apply_together() -> None:
    validator = SharedTextSafetyValidator(max_characters=20)
    decision = validator.validate("<script>bad()</script>" + ("y" * 50))
    assert "UNSAFE_MARKUP_STRIPPED" in decision.issue_codes
    assert "TEXT_TRUNCATED" in decision.issue_codes
    assert len(decision.bounded_text) <= 20
