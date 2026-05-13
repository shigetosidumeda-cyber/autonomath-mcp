"""IPv6 /64 canonical text-form contract between edge and origin.

R2 P2 hardening (2026-05-13): the Cloudflare Pages edge limiter at
``functions/anon_rate_limit_edge.ts`` used to bucket IPv6 by
``ip.split(":").slice(0, 4).join(":")``. That string-only normalisation
diverges from Python's ``str(IPv6Network((addr, 64), strict=False).network_address)``
output for any non-canonical input — ``::1`` stayed as ``::1`` instead of
collapsing to ``::``, ``2001:db8::1`` stayed as ``2001:db8::1`` instead of
``2001:db8::``. A caller whose address rendered differently in each layer
ended up in two separate buckets — edge would grant 3 free requests while
origin counted them against a different bucket, or vice versa.

This module pins the canonical fixture vector and confirms the Python
helper ``canonical_ipv6_64`` agrees with ``str(IPv6Network((addr, 64)).network_address)``.
The TS mirror is enforced in ``tests/test_anon_ipv6_canonical_edge.py``
(node import of the Pages function).
"""

from __future__ import annotations

import ipaddress

import pytest

from jpintel_mcp.api.anon_limit import (
    _normalize_ip_to_prefix,
    canonical_ipv6_64,
    hash_ip,
)

# The single source of truth for the edge ↔ origin contract.
# Format: (raw IPv6 input, expected canonical /64 text).
# Generated from `str(IPv6Network((addr, 64), strict=False).network_address)`.
CANONICAL_VECTORS: list[tuple[str, str]] = [
    ("::", "::"),
    ("::1", "::"),
    ("2001:db8::", "2001:db8::"),
    ("2001:db8::1", "2001:db8::"),
    ("2001:db8:0:1::1", "2001:db8:0:1::"),
    ("2001:db8:0:1::ffff", "2001:db8:0:1::"),
    ("2001:db8:1234:5678:abcd:ef01:2345:6789", "2001:db8:1234:5678::"),
    ("fe80::1", "fe80::"),
    ("2001:0db8:0000:0000:0000:0000:0000:0001", "2001:db8::"),
    ("2001:0:0:1::5", "2001:0:0:1::"),
    ("2001:db8:1::1", "2001:db8:1::"),
]


@pytest.mark.parametrize("raw,expected", CANONICAL_VECTORS)
def test_canonical_ipv6_64_matches_python_network_address(
    raw: str, expected: str
) -> None:
    """`canonical_ipv6_64` returns the same string as Python's stdlib."""
    addr = ipaddress.IPv6Address(raw)
    py_canonical = str(
        ipaddress.IPv6Network((addr, 64), strict=False).network_address
    )
    assert py_canonical == expected, (
        f"Fixture drift: stdlib produced {py_canonical!r} but the test "
        f"vector says {expected!r}. Update CANONICAL_VECTORS."
    )
    assert canonical_ipv6_64(raw) == expected


def test_canonical_ipv6_64_rejects_ipv4() -> None:
    assert canonical_ipv6_64("203.0.113.5") is None


def test_canonical_ipv6_64_rejects_garbage() -> None:
    for bad in ("", "not-an-ip", "::g", "1:2:3", "1:2:3:4:5:6:7:8:9"):
        assert canonical_ipv6_64(bad) is None, bad


def test_normalize_ip_to_prefix_uses_canonical_form() -> None:
    """`_normalize_ip_to_prefix` returns the canonical /64 text for v6 inputs."""
    for raw, expected in CANONICAL_VECTORS:
        assert _normalize_ip_to_prefix(raw) == expected


def test_short_form_and_expanded_form_hash_identically() -> None:
    """`hash_ip` agrees across short, expanded, and same-/64 inputs."""
    short = hash_ip("2001:db8::1")
    expanded = hash_ip("2001:0db8:0000:0000:0000:0000:0000:0001")
    same_64 = hash_ip("2001:db8::cafe:beef")
    assert short == expanded == same_64

    # Loopback and `::` collapse to the same /64.
    assert hash_ip("::1") == hash_ip("::")

    # Different /64 must NOT collide.
    other = hash_ip("2001:db8:1::1")
    assert other != short


def test_edge_origin_contract_anchor_documented() -> None:
    """The Python source must reference the edge contract anchor explicitly.

    Static guard: the comment that ties the helper to the TS twin keeps
    a future contributor from "simplifying" one side without the other.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src/jpintel_mcp/api/anon_limit.py"
    text = src.read_text(encoding="utf-8")
    assert "canonicalIpv6Slash64" in text, (
        "anon_limit.py must reference the edge twin canonicalIpv6Slash64"
    )
    assert "functions/anon_rate_limit_edge.ts" in text, (
        "anon_limit.py must reference the edge file by path"
    )
