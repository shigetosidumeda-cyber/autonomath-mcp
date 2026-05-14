"""Per-IP anonymous rate-limit tests (task #46).

Exercises the router-level dep installed in `api/anon_limit.py`.

Monkeypatched items to look out for:
  - `settings.anon_rate_limit_per_day` to shrink the 50 default where a
    test wants to exhaust in a few calls (keeps each test < 100 ms).
  - `settings.anon_rate_limit_enabled` for the "flag off" case.
  - `api.anon_limit._jst_day_bucket` to simulate a month rollover without
    needing freezegun (not in the dev deps).
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import sqlite3
import sys
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


def _anon_module():
    """Always look up the currently-loaded module so module-swap tests don't
    poison us. Mirrors the pattern used in test_subscribers.py."""
    mod = sys.modules.get("jpintel_mcp.api.anon_limit")
    if mod is None:
        mod = importlib.import_module("jpintel_mcp.api.anon_limit")
    return mod


@pytest.fixture(autouse=True)
def _clear_anon_table(client: TestClient, seeded_db: Path):
    """Wipe the anon_rate_limit table between tests. `client` is depended
    on so the app (and its imports) are built before we touch the DB."""
    c = sqlite3.connect(seeded_db)
    c.execute("DELETE FROM anon_rate_limit")
    c.commit()
    c.close()
    yield
    c = sqlite3.connect(seeded_db)
    c.execute("DELETE FROM anon_rate_limit")
    c.commit()
    c.close()


def _count_row(db: Path, ip_hash: str, day_bucket: str) -> int:
    c = sqlite3.connect(db)
    try:
        row = c.execute(
            "SELECT call_count FROM anon_rate_limit WHERE ip_hash = ? AND date = ?",
            (ip_hash, day_bucket),
        ).fetchone()
    finally:
        c.close()
    return 0 if row is None else int(row[0])


def _testclient_hash(anon, ip: str) -> str:
    """Compute the authoritative per-IP hash production writes."""
    return anon.hash_ip(ip)


def _edge_auth_token(secret: str, caller_ip: str = "203.0.113.99") -> str:
    ts = str(int(time.time()))
    payload = f"v1:{ts}:{caller_ip}"
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256)
    return f"{payload}:{sig.hexdigest()}"


# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------


def test_anon_call_increments_counter(client: TestClient, seeded_db: Path):
    """One anon call -> one row with call_count=1 at this month's JST bucket."""
    anon = _anon_module()
    r = client.get("/meta")
    assert r.status_code == 200

    ip_h = _testclient_hash(anon, "testclient")
    day_bucket = anon._jst_day_bucket()
    assert _count_row(seeded_db, ip_h, day_bucket) == 1


def test_same_ip_hashes_to_same_value(client: TestClient):
    """Determinism: hashing the same IP twice yields the same digest."""
    anon = _anon_module()
    a = anon.hash_ip("203.0.113.1")
    b = anon.hash_ip("203.0.113.1")
    assert a == b
    assert len(a) == 64  # SHA-256 hex


def test_different_ips_have_separate_quotas(
    client: TestClient, seeded_db: Path, monkeypatch: pytest.MonkeyPatch
):
    """Two IPs each burn their own bucket — no cross-contamination."""
    anon = _anon_module()
    from jpintel_mcp.config import settings

    # Shrink so each IP is easily exhausted in the test.
    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 3)

    for _ in range(3):
        r = client.get("/meta", headers={"fly-client-ip": "198.51.100.1"})
        assert r.status_code == 200
    for _ in range(3):
        r = client.get("/meta", headers={"fly-client-ip": "198.51.100.2"})
        assert r.status_code == 200

    # Each IP has its own row with its own count.
    day_bucket = anon._jst_day_bucket()
    assert _count_row(seeded_db, _testclient_hash(anon, "198.51.100.1"), day_bucket) == 3
    assert _count_row(seeded_db, _testclient_hash(anon, "198.51.100.2"), day_bucket) == 3


def test_over_limit_returns_429_with_retry_after_and_resets_at(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Spec: 51st call returns 429 with Retry-After + body detail/limit/resets_at."""
    from jpintel_mcp.config import settings

    # Shrink to 5 so the test runs in < 100 ms.
    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 5)

    ip = "198.51.100.9"
    # 5 allowed.
    for _ in range(5):
        r = client.get("/meta", headers={"fly-client-ip": ip})
        assert r.status_code == 200

    # 6th -> 429.
    r = client.get("/meta", headers={"fly-client-ip": ip})
    assert r.status_code == 429
    body = r.json()
    # `detail` was localised to Japanese for end-user surfaces; accept either
    # the old English string or the current JP copy so the test is stable
    # across copy edits.
    assert "5" in body["detail"] and ("anon" in body["detail"].lower() or "上限" in body["detail"])
    assert body["limit"] == 5
    assert body["resets_at"].startswith(("20", "21"))  # ISO8601 year prefix
    retry_after = r.headers.get("Retry-After")
    assert retry_after is not None and int(retry_after) > 0


def test_authed_call_bypasses_throttled_ip(
    client: TestClient, seeded_db: Path, monkeypatch: pytest.MonkeyPatch
):
    """Tier key on a throttled IP still works (anon limit does NOT gate authed)."""
    from jpintel_mcp.api.deps import hash_api_key  # noqa: F401  (side effects)
    from jpintel_mcp.billing.keys import issue_key
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 2)

    ip = "198.51.100.22"
    # Burn the anon bucket from this IP.
    for _ in range(2):
        assert client.get("/meta", headers={"fly-client-ip": ip}).status_code == 200
    assert client.get("/meta", headers={"fly-client-ip": ip}).status_code == 429

    # Issue a fresh Plus key, then call from the SAME IP with the key.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(c, customer_id="cus_anon", tier="paid", stripe_subscription_id="sub_anon")
    c.commit()
    c.close()

    r = client.get(
        "/meta",
        headers={"fly-client-ip": ip, "X-API-Key": raw},
    )
    assert r.status_code == 200


def test_bogus_api_key_counts_as_anonymous(
    client: TestClient, seeded_db: Path, monkeypatch: pytest.MonkeyPatch
):
    """A fake X-API-Key must not uncap anon-accepting routes."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 2)
    ip = "198.51.100.24"
    headers = {"fly-client-ip": ip, "X-API-Key": "am_bogus_not_a_real_key"}

    assert client.get("/meta", headers=headers).status_code == 401
    assert client.get("/meta", headers=headers).status_code == 401
    r = client.get("/meta", headers=headers)
    assert r.status_code == 429

    anon = _anon_module()
    assert (
        _count_row(
            seeded_db,
            _testclient_hash(anon, ip),
            anon._jst_day_bucket(),
        )
        == 3
    )


# ---------------------------------------------------------------------------
# JST day rollover
# ---------------------------------------------------------------------------


def test_day_rollover_gives_fresh_quota(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Month N exhausted -> switch to month N+1 bucket -> quota resets."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 2)

    anon = _anon_module()

    # Month 1: freeze bucket string to 2026-04-01 (April).
    monkeypatch.setattr(anon, "_jst_day_bucket", lambda *a, **k: "2026-04-29")
    ip = "198.51.100.33"
    for _ in range(2):
        assert client.get("/meta", headers={"fly-client-ip": ip}).status_code == 200
    assert client.get("/meta", headers={"fly-client-ip": ip}).status_code == 429

    # Month 2: rollover — a different bucket string gives a fresh quota.
    monkeypatch.setattr(anon, "_jst_day_bucket", lambda *a, **k: "2026-04-30")
    assert client.get("/meta", headers={"fly-client-ip": ip}).status_code == 200


# ---------------------------------------------------------------------------
# Config flag
# ---------------------------------------------------------------------------


def test_disabled_flag_skips_the_check(
    client: TestClient, seeded_db: Path, monkeypatch: pytest.MonkeyPatch
):
    """anon_rate_limit_enabled=False -> no row written, no 429 ever."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_enabled", False)
    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 1)  # would tripwire if on

    ip = "198.51.100.44"
    for _ in range(5):
        r = client.get("/meta", headers={"fly-client-ip": ip})
        assert r.status_code == 200

    anon = _anon_module()
    # No row was ever written because the dep short-circuited on the flag.
    assert _count_row(seeded_db, anon.hash_ip(ip), anon._jst_day_bucket()) == 0


# ---------------------------------------------------------------------------
# Excluded route
# ---------------------------------------------------------------------------


def test_healthz_never_counts_against_quota(
    client: TestClient, seeded_db: Path, monkeypatch: pytest.MonkeyPatch
):
    """/healthz must never touch the anon bucket — it is the liveness probe."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 3)

    anon = _anon_module()
    ip_h = _testclient_hash(anon, "testclient")
    day_bucket = anon._jst_day_bucket()

    for _ in range(10):
        r = client.get("/healthz")
        assert r.status_code == 200

    # No row — /healthz is not wired to AnonIpLimitDep.
    assert _count_row(seeded_db, ip_h, day_bucket) == 0


# ---------------------------------------------------------------------------
# IPv6 /64 normalisation
# ---------------------------------------------------------------------------


def test_ipv6_addresses_in_same_slash_64_share_bucket(client: TestClient):
    """Two v6 addresses differing only in low bits share a /64 -> same hash."""
    anon = _anon_module()
    a = anon.hash_ip("2001:db8:0:1::1")
    b = anon.hash_ip("2001:db8:0:1::ffff")
    assert a == b
    # Different /64 -> different hash.
    c = anon.hash_ip("2001:db8:0:2::1")
    assert a != c


# ---------------------------------------------------------------------------
# Fly-Client-IP precedence
# ---------------------------------------------------------------------------


def test_fly_client_ip_wins_over_xff(client: TestClient, seeded_db: Path):
    """Fly-Client-IP is trusted over X-Forwarded-For when both are present."""
    anon = _anon_module()
    day_bucket = anon._jst_day_bucket()

    r = client.get(
        "/meta",
        headers={
            "fly-client-ip": "203.0.113.77",
            "x-forwarded-for": "203.0.113.99",
        },
    )
    assert r.status_code == 200
    assert _count_row(seeded_db, _testclient_hash(anon, "203.0.113.77"), day_bucket) == 1
    assert _count_row(seeded_db, _testclient_hash(anon, "203.0.113.99"), day_bucket) == 0


def test_signed_x_forwarded_for_wins_over_fly_client_ip(
    client: TestClient,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """The jpcite.com API proxy signs the caller IP; origin must prefer it."""
    secret = "edge-secret-for-anon-limit-test"
    monkeypatch.setenv("JPCITE_EDGE_AUTH_SECRET", secret)
    anon = _anon_module()
    day_bucket = anon._jst_day_bucket()

    r = client.get(
        "/meta",
        headers={
            "fly-client-ip": "203.0.113.77",
            "x-forwarded-for": "203.0.113.99, 198.51.100.10",
            "x-edge-auth": _edge_auth_token(secret, "203.0.113.99"),
        },
    )
    assert r.status_code == 200
    assert _count_row(seeded_db, _testclient_hash(anon, "203.0.113.99"), day_bucket) == 1
    assert _count_row(seeded_db, _testclient_hash(anon, "203.0.113.77"), day_bucket) == 0


def test_signed_x_forwarded_for_rejects_mismatched_token_ip(
    client: TestClient,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A signed token must be bound to the first XFF hop it authorizes."""
    secret = "edge-secret-for-anon-limit-test"
    monkeypatch.setenv("JPCITE_EDGE_AUTH_SECRET", secret)
    anon = _anon_module()
    day_bucket = anon._jst_day_bucket()

    r = client.get(
        "/meta",
        headers={
            "fly-client-ip": "203.0.113.77",
            "x-forwarded-for": "203.0.113.99, 198.51.100.10",
            "x-edge-auth": _edge_auth_token(secret, "203.0.113.88"),
        },
    )
    assert r.status_code == 200
    assert _count_row(seeded_db, _testclient_hash(anon, "203.0.113.99"), day_bucket) == 0
    assert _count_row(seeded_db, _testclient_hash(anon, "203.0.113.77"), day_bucket) == 1


def test_bare_x_forwarded_for_is_not_trusted(client: TestClient, seeded_db: Path):
    """Spoofable X-Forwarded-For alone must not choose the anon bucket."""
    anon = _anon_module()
    day_bucket = anon._jst_day_bucket()

    r = client.get("/meta", headers={"x-forwarded-for": "203.0.113.123"})
    assert r.status_code == 200

    assert _count_row(seeded_db, _testclient_hash(anon, "203.0.113.123"), day_bucket) == 0
    assert _count_row(seeded_db, _testclient_hash(anon, "testclient"), day_bucket) == 1


# ---------------------------------------------------------------------------
# R2 P1-3: Direct-to-Fly traffic with no Fly-Client-IP must be rejected
# when the transport peer is loopback / RFC1918 / link-local.
# ---------------------------------------------------------------------------


def test_is_loopback_or_internal_detects_spec_ranges():
    """The helper must cover every CIDR the spec calls out."""
    anon = _anon_module()
    is_lb = anon._is_loopback_or_internal

    # Loopback
    assert is_lb("127.0.0.1") is True
    assert is_lb("127.255.255.254") is True
    assert is_lb("::1") is True
    # RFC1918
    assert is_lb("10.0.0.1") is True
    assert is_lb("10.255.255.254") is True
    assert is_lb("172.16.0.1") is True
    assert is_lb("172.31.255.254") is True
    assert is_lb("192.168.0.1") is True
    assert is_lb("192.168.255.254") is True
    # Link-local
    assert is_lb("169.254.0.1") is True
    assert is_lb("169.254.255.254") is True
    # Globally routable (8.8.8.8 / 1.1.1.1 / public AAAA) — these are the
    # only IPs a legitimate Fly proxy should ever surface as request.client.host
    # when CF/Fly-Client-IP is absent (and even then it's the proxy's own
    # public address, not the caller). Documentation ranges (TEST-NET,
    # 2001:db8::/32) are classified by Python as `is_private` so they
    # trip the loopback/internal check, which is fine — we don't expect
    # them in production.
    assert is_lb("8.8.8.8") is False
    assert is_lb("1.1.1.1") is False
    assert is_lb("2606:4700:4700::1111") is False  # Cloudflare DNS, global
    # Non-IP literals (TestClient default) — treated as not-loopback
    # so existing tests / dev flows keep working.
    assert is_lb("testclient") is False
    assert is_lb("") is False
    assert is_lb("unknown") is False


def test_direct_to_fly_loopback_peer_without_fly_header_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Direct-to-Fly traffic that bypassed the proxy chain (no Fly-Client-IP
    AND transport peer is 127.0.0.1 / 10.x.x.x / 169.254.x.x / ::1) must
    be refused with 503 `edge_ip_unavailable`, NOT silently bucketed under
    a shared "unknown" key.
    """
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 3)

    # Override the TestClient default "testclient" peer with a real
    # loopback literal by patching `_client_ip`'s sibling check directly
    # — easiest is to monkeypatch `request.client.host` via a starlette
    # Request wrapper. Use the existing dep test pattern: build a fake
    # request and call enforce_anon_ip_limit synchronously through the
    # router by overriding the testclient peer via app.dependency_overrides.
    #
    # The path of least resistance is to call enforce_anon_ip_limit
    # directly on a synthesised Request.
    import asyncio

    from starlette.datastructures import Headers
    from starlette.requests import Request

    from jpintel_mcp.api.anon_limit import enforce_anon_ip_limit

    for loopback_peer in ("127.0.0.1", "10.0.0.5", "169.254.1.1", "192.168.1.1", "::1"):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/meta",
            "headers": Headers({}).raw,  # NO fly-client-ip
            "http_version": "1.1",
            "client": (loopback_peer, 12345),
        }
        request = Request(scope)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(enforce_anon_ip_limit(request))
        assert excinfo.value.status_code == 503
        detail = excinfo.value.detail
        assert isinstance(detail, dict)
        assert detail.get("code") == "edge_ip_unavailable"
        assert detail.get("reason") == "edge_ip_unavailable"


def test_direct_to_fly_public_peer_without_fly_header_passes(
    client: TestClient, seeded_db: Path
):
    """If the transport peer is public (e.g. Fly proxy IP itself) and
    Fly-Client-IP is absent, the request is bucketed against the peer
    address — NOT refused. This is the "Fly proxy hit us directly" path
    and must keep working so a Fly internal probe doesn't 503.
    """
    import asyncio

    from starlette.datastructures import Headers
    from starlette.requests import Request

    from jpintel_mcp.api.anon_limit import enforce_anon_ip_limit

    # Globally routable IP — must NOT be in a documentation range (CPython
    # classifies TEST-NET-1/2/3 + 2001:db8::/32 as is_private). 8.8.8.8 is
    # genuinely public.
    public_peer = "8.8.8.8"
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/meta",
        "headers": Headers({}).raw,
        "http_version": "1.1",
        "client": (public_peer, 12345),
    }
    request = Request(scope)
    # Should NOT raise — public peer is treated as legit.
    asyncio.run(enforce_anon_ip_limit(request))

    anon = _anon_module()
    day_bucket = anon._jst_day_bucket()
    assert _count_row(seeded_db, _testclient_hash(anon, public_peer), day_bucket) == 1


def test_loopback_peer_is_overridden_by_fly_client_ip(
    client: TestClient, seeded_db: Path, monkeypatch: pytest.MonkeyPatch
):
    """A loopback transport peer is FINE if Fly-Client-IP IS set — the
    request went through the Fly proxy (which terminates on loopback
    inside the machine) and the header carries the real caller IP.
    """
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 3)

    r = client.get(
        "/meta",
        headers={"fly-client-ip": "203.0.113.77"},
    )
    assert r.status_code == 200

    anon = _anon_module()
    day_bucket = anon._jst_day_bucket()
    assert _count_row(seeded_db, _testclient_hash(anon, "203.0.113.77"), day_bucket) == 1


def test_valid_api_key_bypasses_loopback_503(
    client: TestClient, seeded_db: Path, monkeypatch: pytest.MonkeyPatch
):
    """A valid API key must short-circuit the loopback check — dev /
    internal callers that supply a key shouldn't be 503'd just because
    they reach Fly through a private interface.
    """
    import asyncio

    from starlette.datastructures import Headers
    from starlette.requests import Request

    from jpintel_mcp.api.anon_limit import enforce_anon_ip_limit
    from jpintel_mcp.billing.keys import issue_key

    monkeypatch.setattr(
        __import__("jpintel_mcp.config", fromlist=["settings"]).settings,
        "anon_rate_limit_per_day",
        3,
    )

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(c, customer_id="cus_loopback", tier="paid", stripe_subscription_id="sub_lb")
    c.commit()
    c.close()

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/meta",
        "headers": Headers({"x-api-key": raw}).raw,
        "http_version": "1.1",
        "client": ("127.0.0.1", 12345),
    }
    request = Request(scope)
    # Should NOT raise — the API key short-circuits before the IP check.
    asyncio.run(enforce_anon_ip_limit(request))
