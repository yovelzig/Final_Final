"""Unit tests for trusted-proxy-aware client identity resolution
(`infrastructure.identity.client_identity`)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stock_research_core.infrastructure.identity.client_identity import resolve_client_ip

_TRUSTED_CIDRS = ["172.28.0.0/24"]


def _request(peer_ip: str | None, headers: dict[str, str] | None = None):
    request = MagicMock()
    request.client.host = peer_ip if peer_ip is not None else None
    if peer_ip is None:
        request.client = None
    request.headers = headers or {}
    return request


class TestResolveClientIp:
    def test_forwarded_header_ignored_by_default(self) -> None:
        request = _request("203.0.113.5", {"x-forwarded-for": "9.9.9.9"})
        result = resolve_client_ip(request, trust_forwarded_headers=False, trusted_proxy_cidrs=_TRUSTED_CIDRS)
        assert result == "203.0.113.5"

    def test_untrusted_peer_cannot_spoof_forwarded_header(self) -> None:
        request = _request("203.0.113.5", {"x-forwarded-for": "9.9.9.9"})
        result = resolve_client_ip(request, trust_forwarded_headers=True, trusted_proxy_cidrs=_TRUSTED_CIDRS)
        assert result == "203.0.113.5"

    def test_trusted_proxy_single_hop_is_honored(self) -> None:
        request = _request("172.28.0.5", {"x-forwarded-for": "198.51.100.7"})
        result = resolve_client_ip(request, trust_forwarded_headers=True, trusted_proxy_cidrs=_TRUSTED_CIDRS)
        assert result == "198.51.100.7"

    def test_multiple_proxy_chain_resolves_to_first_untrusted_hop(self) -> None:
        request = _request("172.28.0.5", {"x-forwarded-for": "198.51.100.9, 172.28.0.5"})
        result = resolve_client_ip(request, trust_forwarded_headers=True, trusted_proxy_cidrs=_TRUSTED_CIDRS)
        assert result == "198.51.100.9"

    def test_chain_of_only_trusted_hops_falls_back_to_peer(self) -> None:
        request = _request("172.28.0.5", {"x-forwarded-for": "172.28.0.9, 172.28.0.5"})
        result = resolve_client_ip(request, trust_forwarded_headers=True, trusted_proxy_cidrs=_TRUSTED_CIDRS)
        assert result == "172.28.0.5"

    def test_malformed_header_entry_falls_back_safely(self) -> None:
        request = _request("172.28.0.5", {"x-forwarded-for": "not-an-ip"})
        result = resolve_client_ip(request, trust_forwarded_headers=True, trusted_proxy_cidrs=_TRUSTED_CIDRS)
        assert result == "172.28.0.5"

    def test_excessively_long_header_falls_back_safely(self) -> None:
        request = _request("172.28.0.5", {"x-forwarded-for": ",".join(["1.2.3.4"] * 500)})
        result = resolve_client_ip(request, trust_forwarded_headers=True, trusted_proxy_cidrs=_TRUSTED_CIDRS)
        assert result == "172.28.0.5"

    def test_excessive_hop_count_falls_back_safely(self) -> None:
        request = _request("172.28.0.5", {"x-forwarded-for": ", ".join(["9.9.9.9"] * 25)})
        result = resolve_client_ip(request, trust_forwarded_headers=True, trusted_proxy_cidrs=_TRUSTED_CIDRS)
        assert result == "172.28.0.5"

    def test_no_client_returns_unknown(self) -> None:
        request = _request(None)
        result = resolve_client_ip(request, trust_forwarded_headers=True, trusted_proxy_cidrs=_TRUSTED_CIDRS)
        assert result == "unknown"

    def test_empty_trusted_cidr_list_never_honors_forwarded_header(self) -> None:
        request = _request("172.28.0.5", {"x-forwarded-for": "198.51.100.7"})
        result = resolve_client_ip(request, trust_forwarded_headers=True, trusted_proxy_cidrs=[])
        assert result == "172.28.0.5"

    def test_distinct_forwarded_clients_produce_distinct_identities(self) -> None:
        request_a = _request("172.28.0.5", {"x-forwarded-for": "198.51.100.1"})
        request_b = _request("172.28.0.5", {"x-forwarded-for": "198.51.100.2"})
        result_a = resolve_client_ip(request_a, trust_forwarded_headers=True, trusted_proxy_cidrs=_TRUSTED_CIDRS)
        result_b = resolve_client_ip(request_b, trust_forwarded_headers=True, trusted_proxy_cidrs=_TRUSTED_CIDRS)
        assert result_a != result_b
