"""Trusted-proxy-aware client identity resolution (Phase 11 stabilization ss3.2).

FastAPI runs behind the Next.js Route Handler proxy, so `request.client.host`
is frequently the proxy's own container IP, not the browser's. Blindly
trusting `X-Forwarded-For` would let any caller spoof their rate-limit and
audit identity, so forwarded headers are honored *only* when both:

1. `TRUST_FORWARDED_HEADERS=true`, and
2. the immediate TCP peer (`request.client.host`) is itself inside a
   configured `TRUSTED_PROXY_CIDRS` network.

Even then, only the boundary of the trusted-proxy chain is trusted - the
first (nearest-to-client) hop that is *not* itself a trusted proxy - never
an arbitrary client-supplied leftmost entry.
"""

from __future__ import annotations

import ipaddress
from typing import Sequence

from starlette.requests import Request

_MAX_FORWARDED_HEADER_LENGTH = 1000
_MAX_FORWARDED_HOPS = 20
_UNKNOWN = "unknown"


def parse_trusted_cidrs(cidrs: Sequence[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for cidr in cidrs:
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue
    return networks


def _is_trusted_proxy(ip_str: str, networks: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network]) -> bool:
    try:
        address = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(address in network for network in networks)


def resolve_client_ip(
    request: Request, *, trust_forwarded_headers: bool, trusted_proxy_cidrs: Sequence[str]
) -> str:
    """The client IP to use for rate limiting and authentication auditing.

    Never raises - any malformed input falls back to the immediate TCP
    peer address (or `"unknown"` if even that is unavailable), which is
    always the safe, non-spoofable choice.
    """
    peer_ip = request.client.host if request.client else _UNKNOWN

    if not trust_forwarded_headers or peer_ip == _UNKNOWN:
        return peer_ip

    networks = parse_trusted_cidrs(trusted_proxy_cidrs)
    if not networks or not _is_trusted_proxy(peer_ip, networks):
        return peer_ip

    raw_header = request.headers.get("x-forwarded-for")
    if not raw_header or len(raw_header) > _MAX_FORWARDED_HEADER_LENGTH:
        return peer_ip

    hops = [hop.strip() for hop in raw_header.split(",")]
    if not hops or len(hops) > _MAX_FORWARDED_HOPS:
        return peer_ip

    # Walk from the nearest hop (rightmost) back toward the original
    # client (leftmost). Each hop that is itself a trusted proxy is
    # skipped; the first hop that is not is the resolved client - never
    # trust anything past an untrusted hop, and never fall through to a
    # client-controlled leftmost value directly.
    for hop in reversed(hops):
        if not hop:
            return peer_ip
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            return peer_ip
        if not _is_trusted_proxy(hop, networks):
            return hop

    return peer_ip
