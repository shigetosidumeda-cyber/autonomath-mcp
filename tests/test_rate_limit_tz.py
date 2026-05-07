"""Integration test: anonymous rate-limit TZ correctness.

Verifies:
  (a) The 4th anonymous request to /v1/programs/search returns 429.
  (b) The X-RateLimit-Reset header (via Retry-After + resets_at in body) points
      to JST next-day 00:00, not UTC midnight or any other epoch.

Policy: anonymous quota is 3 req/day per IP, resets at JST 翌日 00:00.
See src/jpintel_mcp/api/anon_limit.py and CLAUDE.md "Common gotchas".
"""

from __future__ import annotations

import importlib
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

_JST = timezone(timedelta(hours=9))
_LIMIT = 3


@pytest.fixture(autouse=True)
def _clear_anon(seeded_db):
    """Wipe anon_rate_limit before and after this test module."""
    c = sqlite3.connect(seeded_db)
    c.execute("DELETE FROM anon_rate_limit")
    c.commit()
    c.close()
    yield
    c = sqlite3.connect(seeded_db)
    c.execute("DELETE FROM anon_rate_limit")
    c.commit()
    c.close()


def _anon_mod():
    mod = sys.modules.get("jpintel_mcp.api.anon_limit")
    if mod is None:
        mod = importlib.import_module("jpintel_mcp.api.anon_limit")
    return mod


def test_anon_4th_request_is_429_with_jst_reset(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    (a) Simulate 4 anonymous requests to /v1/programs/search.
        The 4th must return 429.
    (b) The Retry-After header must be positive.
    (c) The body's resets_at (== reset_at_jst) must parse to a datetime with
        UTC+09:00 offset and be the next JST calendar day
        at 00:00:00 JST — NOT UTC midnight (which would be +00:00).

    The per-IP-endpoint middleware (`api/middleware/per_ip_endpoint_limit.py`)
    enforces a separate 30 req/min cap on `/v1/programs/search` that would
    fire before a large anon cap exhausts. We reset
    that bucket on every iteration so the test exercises ONLY the anon
    daily limiter.
    """
    _anon_mod()
    from jpintel_mcp.api.middleware.per_ip_endpoint_limit import (
        _reset_per_ip_endpoint_buckets,
    )
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_day", _LIMIT)

    ip = "198.51.100.201"  # TEST-NET, not a real address
    start_jst = datetime.now(_JST)

    # First 3 must succeed.
    for i in range(_LIMIT):
        # Drop the per-endpoint per-IP bucket so the 30 req/min /v1/programs/search
        # cap doesn't trip; this test is about the daily anon
        # cap, not the burst limiter.
        _reset_per_ip_endpoint_buckets()
        r = client.get(
            "/v1/programs/search",
            headers={"x-forwarded-for": ip},
            params={"q": "補助金", "limit": 1},
        )
        assert r.status_code == 200, f"request #{i + 1} unexpectedly failed: {r.status_code}"
    # Final probe: ensure the burst bucket is fresh so the 4th is rejected
    # by the daily limiter, not the burst limiter.
    _reset_per_ip_endpoint_buckets()

    # 4th must be rejected.
    r4 = client.get(
        "/v1/programs/search",
        headers={"x-forwarded-for": ip},
        params={"q": "補助金", "limit": 1},
    )
    assert r4.status_code == 429, f"expected 429, got {r4.status_code}"

    # --- (b) Retry-After header ---
    retry_after = r4.headers.get("Retry-After")
    assert retry_after is not None, "Retry-After header must be present on 429"
    retry_seconds = int(retry_after)
    assert retry_seconds > 0, "Retry-After must be positive (seconds to JST day reset)"

    # --- (c) resets_at timezone check ---
    body = r4.json()
    # Body may have either "resets_at" or "reset_at_jst" (both are set in anon_limit.py)
    resets_at_str = body.get("reset_at_jst") or body.get("resets_at")
    assert resets_at_str is not None, "Response body must contain resets_at or reset_at_jst"

    # Parse the ISO-8601 string.
    try:
        resets_at = datetime.fromisoformat(resets_at_str)
    except ValueError as exc:
        pytest.fail(f"resets_at '{resets_at_str}' is not valid ISO-8601: {exc}")

    # Must have timezone info.
    assert resets_at.tzinfo is not None, "resets_at must be timezone-aware"

    # Must be UTC+09:00 (JST), not UTC+00:00.
    offset = resets_at.utcoffset()
    assert offset == timedelta(hours=9), (
        f"resets_at must carry JST (+09:00) offset, got {offset!r}. "
        "This confirms the reset is JST next-day midnight, not UTC midnight."
    )

    # Must be the next JST day.
    expected_date = (start_jst + timedelta(days=1)).date()
    assert resets_at.date() == expected_date, (
        f"resets_at date must be next JST day {expected_date}, got {resets_at.date()}"
    )

    # Must be at 00:00:00.
    assert (resets_at.hour, resets_at.minute, resets_at.second) == (
        0,
        0,
        0,
    ), f"resets_at time must be 00:00:00 JST, got {resets_at.time()}"

    # Must be in the future relative to now (JST).
    now_jst = datetime.now(_JST)
    assert resets_at > now_jst, "resets_at must be in the future"

    # Sanity: Retry-After seconds must roughly match resets_at delta (±60 s tolerance).
    expected_seconds = int((resets_at - now_jst).total_seconds())
    assert abs(retry_seconds - expected_seconds) <= 60, (
        f"Retry-After ({retry_seconds}s) must be close to resets_at delta "
        f"({expected_seconds}s); diff = {abs(retry_seconds - expected_seconds)}s"
    )
