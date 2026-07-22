"""Unit tests for `OpaqueRefreshTokenService`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stock_research_core.infrastructure.identity.opaque_refresh_token_service import OpaqueRefreshTokenService

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_generate_token_produces_high_entropy_url_safe_strings() -> None:
    service = OpaqueRefreshTokenService()
    tokens = {service.generate_token() for _ in range(50)}
    assert len(tokens) == 50  # never collides in practice
    for token in tokens:
        assert len(token) >= 32
        assert all(c.isalnum() or c in "-_" for c in token)


def test_hash_token_is_deterministic_and_looks_like_sha256_hex() -> None:
    service = OpaqueRefreshTokenService()
    raw = service.generate_token()
    hash_a = service.hash_token(raw)
    hash_b = service.hash_token(raw)
    assert hash_a == hash_b
    assert len(hash_a) == 64
    assert all(c in "0123456789abcdef" for c in hash_a)


def test_different_tokens_hash_differently() -> None:
    service = OpaqueRefreshTokenService()
    assert service.hash_token(service.generate_token()) != service.hash_token(service.generate_token())


def test_verify_token_accepts_matching_pair_and_rejects_mismatch() -> None:
    service = OpaqueRefreshTokenService()
    raw = service.generate_token()
    token_hash = service.hash_token(raw)

    assert service.verify_token(raw, token_hash) is True
    assert service.verify_token(service.generate_token(), token_hash) is False


def test_calculate_expiration_adds_configured_days() -> None:
    service = OpaqueRefreshTokenService(refresh_token_days=30)
    assert service.calculate_expiration(issued_at=NOW) == NOW + timedelta(days=30)


def test_calculate_expiration_respects_custom_window() -> None:
    service = OpaqueRefreshTokenService(refresh_token_days=7)
    assert service.calculate_expiration(issued_at=NOW) == NOW + timedelta(days=7)
