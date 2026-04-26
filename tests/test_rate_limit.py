"""Per-key / per-IP token-bucket throttle tests (D9, 2026-04-25).

Covers the middleware in `api/middleware/rate_limit.py` — NOT the monthly
50 req/月 anon quota (that lives in `tests/test_anon_rate_limit.py`).

Each test resets the bucket store via `_reset_rate_limit_buckets()` and
clears the `anon_rate_limit` table via the autouse fixture in
`tests/conftest.py` so the burst throttle and the monthly quota don't
contaminate each other.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


# --- helpers ----------------------------------------------------------------


def _reset_buckets() -> None:
    """Drop every token bucket so each test starts at full burst credit."""
    from jpintel_mcp.api.middleware.rate_limit import _reset_rate_limit_buckets

    _reset_rate_limit_buckets()


@pytest.fixture(autouse=True)
def _enable_throttle_for_this_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-enable the throttle (conftest disables it for the rest of the
    suite via ``RATE_LIMIT_BURST_DISABLED=1``) and reset bucket state on
    every test in this module."""
    monkeypatch.delenv("RATE_LIMIT_BURST_DISABLED", raising=False)
    _reset_buckets()
    yield
    _reset_buckets()


# --- anonymous IP throttle --------------------------------------------------


def test_anon_burst_under_limit_passes(client: TestClient) -> None:
    """5 quick anon requests stay under burst=5 → all 200."""
    for _ in range(5):
        r = client.get("/v1/meta")
        assert r.status_code == 200, r.text


def test_anon_burst_over_limit_returns_429(client: TestClient) -> None:
    """The 6th request inside one second exhausts the anon burst (5) and
    must return 429 with a Retry-After header."""
    for _ in range(5):
        r = client.get("/v1/meta")
        assert r.status_code == 200

    r = client.get("/v1/meta")
    assert r.status_code == 429, r.text
    body = r.json()
    assert body["error"]["code"] == "rate_limited"
    assert body["error"]["bucket"] == "anon-ip"
    assert body["error"]["retry_after"] >= 1
    # RFC 7231: Retry-After integer seconds.
    assert "Retry-After" in r.headers
    assert int(r.headers["Retry-After"]) >= 1


def test_anon_429_does_not_burn_monthly_quota(client: TestClient) -> None:
    """A request rejected by the burst middleware must not increment the
    monthly anon counter — the router-dep runs INSIDE the handler, after
    the middleware has already short-circuited."""
    import hashlib
    import hmac
    import sqlite3

    from jpintel_mcp.api.anon_limit import _jst_month_bucket, _normalize_ip_to_prefix
    from jpintel_mcp.config import settings

    # Burn the burst.
    for _ in range(5):
        client.get("/v1/meta")
    rejected = client.get("/v1/meta")
    assert rejected.status_code == 429

    # P2.6.2: production hash composes IP + 4-axis fingerprint. TestClient
    # default fingerprint is "other|?|h1.1|?" (UA=testclient, no AL, HTTP/1.1,
    # no JA3). Mirror that to find the row.
    normalized = _normalize_ip_to_prefix("testclient")
    composed = f"{normalized}#other|?|h1.1|?"
    ip_h = hmac.new(
        settings.api_key_salt.encode("utf-8"),
        composed.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Inspect the monthly counter — the rejected request must NOT have
    # advanced it past 5 (the 5 successful calls).
    db_path = settings.db_path
    c = sqlite3.connect(db_path)
    try:
        row = c.execute(
            "SELECT call_count FROM anon_rate_limit WHERE ip_hash = ? AND date = ?",
            (ip_h, _jst_month_bucket()),
        ).fetchone()
    finally:
        c.close()
    # row[0] is exactly 5: only the 5 calls that returned 200 incremented it.
    assert row is not None
    assert int(row[0]) == 5


# --- paid-key throttle ------------------------------------------------------


def test_paid_key_higher_burst(client: TestClient, paid_key: str) -> None:
    """Paid keys get burst=20 — 10 quick requests must all succeed (where
    an anon caller would be at 429 by request 6)."""
    headers = {"X-API-Key": paid_key}
    for i in range(10):
        r = client.get("/v1/meta", headers=headers)
        assert r.status_code == 200, f"request {i} failed: {r.text}"


def test_paid_key_bucket_exhaustion_returns_429(client: TestClient, paid_key: str) -> None:
    """Drain the paid bucket directly via `_take_token`, then verify the
    next HTTP request returns 429 with bucket='paid'.

    Going through the HTTP path 21 times in a real loop never exhausts in
    a TestClient because /v1/meta is slow enough (DB query) for the
    10 req/sec refill to keep up; we deplete the bucket programmatically
    so the test stays deterministic."""
    import hashlib
    import hmac

    from jpintel_mcp.api.middleware.rate_limit import (
        _PAID_BURST,
        _PAID_RATE_PER_SEC,
        _take_token,
    )
    from jpintel_mcp.config import settings

    # Compute the same bucket key the middleware will derive for this key.
    key_hash16 = hmac.new(
        settings.api_key_salt.encode("utf-8"),
        paid_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    bucket_key = f"k:{key_hash16}"

    # Drain to exactly zero tokens. 20 takes from a fresh bucket → empty.
    for _ in range(int(_PAID_BURST)):
        allowed, _ = _take_token(bucket_key, _PAID_RATE_PER_SEC, _PAID_BURST)
        assert allowed

    # 21st take is denied with a positive retry_after.
    allowed, retry_after = _take_token(bucket_key, _PAID_RATE_PER_SEC, _PAID_BURST)
    assert not allowed
    assert retry_after >= 0.1  # ≥100ms at 10 req/sec

    # Now an HTTP call with the same X-API-Key must hit the same bucket
    # and get 429 + paid label.
    r = client.get("/v1/meta", headers={"X-API-Key": paid_key})
    assert r.status_code == 429, r.text
    body = r.json()
    assert body["error"]["bucket"] == "paid"
    assert "Retry-After" in r.headers


def test_paid_key_uses_separate_bucket_from_anon(
    client: TestClient, paid_key: str
) -> None:
    """The paid-key bucket is keyed on the key hash, NOT the IP — so an
    anon caller from the same IP that has burned its 5/sec is unaffected
    by paid-key activity (and vice versa)."""
    # First, burn the anon burst from the test client IP.
    for _ in range(5):
        r = client.get("/v1/meta")
        assert r.status_code == 200
    blocked = client.get("/v1/meta")
    assert blocked.status_code == 429

    # Same TestClient (same `testclient` IP) but now with X-API-Key — the
    # paid bucket is brand new, so this MUST succeed.
    r = client.get("/v1/meta", headers={"X-API-Key": paid_key})
    assert r.status_code == 200, r.text


# --- whitelist + auth-shaped headers ----------------------------------------


def test_healthz_is_whitelisted(client: TestClient) -> None:
    """/healthz must never throttle — Fly's liveness probe hits it every
    few seconds and a 429 there would break the deploy pipeline."""
    # Hammer it past the anon burst threshold; every call must be 200.
    # /healthz lives at the v1 router level; some apps mount it at
    # both / and /v1/ — hit /healthz directly because that's the path
    # in `_WHITELIST_PATHS`.
    for _ in range(50):
        r = client.get("/healthz")
        assert r.status_code == 200


def test_options_preflight_is_whitelisted(client: TestClient) -> None:
    """CORS preflight uses OPTIONS and must never be throttled — even when
    CORS rejects the origin (400) the rate-limiter must NOT have been the
    cause. The signal we care about: NO 429 across many quick OPTIONS hits
    where an anon GET would have been throttled by request 6."""
    for _ in range(20):
        r = client.options(
            "/v1/programs/UNI-test-s-1",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # 200/204 = CORS-approved preflight, 400 = origin not in allow list,
        # 405 = no OPTIONS handler. None should be 429: the throttle bypassed.
        assert r.status_code != 429, f"OPTIONS got throttled: {r.text}"


def test_authorization_bearer_treated_as_paid_bucket(
    client: TestClient, paid_key: str
) -> None:
    """`Authorization: Bearer …` is the second auth header form. It must
    route to the paid bucket (burst=20), not the anon bucket (burst=5)."""
    headers = {"Authorization": f"Bearer {paid_key}"}
    for i in range(10):
        r = client.get("/v1/meta", headers=headers)
        assert r.status_code == 200, f"request {i} failed: {r.text}"


# --- retry-after correctness ------------------------------------------------


def test_retry_after_is_integer_seconds(client: TestClient) -> None:
    """RFC 7231: Retry-After is either an HTTP-date or an integer number
    of seconds. Our implementation always emits the integer form."""
    for _ in range(5):
        client.get("/v1/meta")
    r = client.get("/v1/meta")
    assert r.status_code == 429
    ra = r.headers["Retry-After"]
    # Must parse as a positive integer.
    assert ra.isdigit() and int(ra) >= 1
