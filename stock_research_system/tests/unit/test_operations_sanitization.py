"""Unit tests for `domain.operations.sanitization` - the shared redaction
helpers used by both domain-model validation and structured logging."""

from __future__ import annotations

from stock_research_core.domain.operations.sanitization import (
    contains_credential_leak,
    contains_traceback,
    find_sensitive_keys,
    key_is_sensitive,
    redact,
)


class TestKeyIsSensitive:
    def test_recognizes_common_sensitive_key_names(self) -> None:
        for key in ("password", "Password", "api_key", "API-KEY", "refresh_token", "database_url", "Authorization"):
            assert key_is_sensitive(key)

    def test_does_not_flag_ordinary_keys(self) -> None:
        for key in ("task_id", "job_type", "ticker", "portfolio_id", "as_of"):
            assert not key_is_sensitive(key)


class TestFindSensitiveKeys:
    def test_finds_nested_sensitive_keys(self) -> None:
        found = find_sensitive_keys({"outer": {"inner": {"password": "x"}}})
        assert "outer.inner.password" in found

    def test_finds_sensitive_keys_inside_lists(self) -> None:
        found = find_sensitive_keys({"items": [{"api_key": "x"}, {"ok": "y"}]})
        assert "items[0].api_key" in found

    def test_returns_empty_for_clean_data(self) -> None:
        assert find_sensitive_keys({"job_type": "PORTFOLIO_VALUATION", "as_of": "2026-01-01"}) == []


class TestContainsTraceback:
    def test_detects_traceback_marker(self) -> None:
        assert contains_traceback("Traceback (most recent call last):\n  File x, line 1")

    def test_detects_traceback_nested_in_dict(self) -> None:
        assert contains_traceback({"error": "Traceback (most recent call last):\nfoo"})

    def test_ordinary_text_is_not_flagged(self) -> None:
        assert not contains_traceback("No virtual portfolio found with id 'abc'.")


class TestContainsCredentialLeak:
    def test_detects_jwt_shaped_string(self) -> None:
        jwt_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dQw4w9WgXcQ_abcdefghijklmno"
        assert contains_credential_leak(jwt_like)

    def test_detects_credential_bearing_url(self) -> None:
        assert contains_credential_leak("Connection failed: postgresql://user:secretpass@host:5432/db")

    def test_detects_raw_bearer_header(self) -> None:
        assert contains_credential_leak("Authorization: Bearer abc.def.ghi")

    def test_ordinary_sentence_mentioning_token_is_not_flagged(self) -> None:
        assert not contains_credential_leak("The refresh token was invalid or expired.")


class TestRedact:
    def test_redacts_sensitive_keys(self) -> None:
        result = redact({"password": "hunter2", "ok": "fine"})
        assert result["password"] == "***REDACTED***"
        assert result["ok"] == "fine"

    def test_redacts_nested_structures(self) -> None:
        result = redact({"nested": {"authorization": "Bearer xyz"}})
        assert result["nested"]["authorization"] == "***REDACTED***"

    def test_redacts_credential_shaped_strings_even_under_safe_keys(self) -> None:
        result = redact({"message": "Traceback (most recent call last):\nfoo"})
        assert result["message"] == "***REDACTED***"

    def test_does_not_mutate_input(self) -> None:
        original = {"password": "hunter2"}
        redact(original)
        assert original["password"] == "hunter2"

    def test_redacts_within_lists(self) -> None:
        result = redact([{"api_key": "secret"}, {"ok": "fine"}])
        assert result[0]["api_key"] == "***REDACTED***"
        assert result[1]["ok"] == "fine"
