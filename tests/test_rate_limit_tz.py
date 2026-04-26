"""Integration test: anonymous rate-limit TZ correctness.

Verifies:
  (a) The 51st anonymous request to /v1/programs/search returns 429.
  (b) The X-RateLimit-Reset header (via Retry-After + resets_at in body) points
      to JST first-of-next-month 00:00, not UTC midnight or any other epoch.

Policy: anonymous quota is 50 req/month per IP, resets at JST 月初 00:00.
See src/jpintel_mcp/api/anon_limit.py and CLAUDE.md "Common gotchas".
"""
from __future__ import annotations

import importlib
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

_JST = timezone(timedelta(hours=9))
_LIMIT = 50


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


def test_anon_51st_request_is_429_with_jst_reset(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    (a) Simulate 51 anonymous requests to /v1/programs/search.
        The 51st must return 429.
    (b) The Retry-After header must be positive.
    (c) The body's resets_at (== reset_at_jst) must parse to a datetime with
        UTC+09:00 offset and be the first day of the next JST calendar month
        at 00:00:00 JST — NOT UTC midnight (which would be +00:00).
    """
    _anon_mod()
    from jpintel_mcp.config import settings

    # Use a tiny limit so the test exhausts quickly.
    monkeypatch.setattr(settings, "anon_rate_limit_per_month", _LIMIT)

    ip = "198.51.100.201"  # TEST-NET, not a real address

    # First 50 must succeed.
    for i in range(_LIMIT):
        r = client.get(
            "/v1/programs/search",
            headers={"x-forwarded-for": ip},
            params={"q": "補助金", "limit": 1},
        )
        assert r.status_code == 200, f"request #{i+1} unexpectedly failed: {r.status_code}"

    # 51st must be rejected.
    r51 = client.get(
        "/v1/programs/search",
        headers={"x-forwarded-for": ip},
        params={"q": "補助金", "limit": 1},
    )
    assert r51.status_code == 429, f"expected 429, got {r51.status_code}"

    # --- (b) Retry-After header ---
    retry_after = r51.headers.get("Retry-After")
    assert retry_after is not None, "Retry-After header must be present on 429"
    retry_seconds = int(retry_after)
    assert retry_seconds > 0, "Retry-After must be positive (seconds to JST month start)"

    # --- (c) resets_at timezone check ---
    body = r51.json()
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
        "This confirms the reset is JST first-of-month, not UTC midnight."
    )

    # Must be the first day of the month.
    assert resets_at.day == 1, (
        f"resets_at day must be 1 (first-of-month), got {resets_at.day}"
    )

    # Must be at 00:00:00.
    assert (resets_at.hour, resets_at.minute, resets_at.second) == (0, 0, 0), (
        f"resets_at time must be 00:00:00 JST, got {resets_at.time()}"
    )

    # Must be in the future relative to now (JST).
    now_jst = datetime.now(_JST)
    assert resets_at > now_jst, "resets_at must be in the future"

    # Sanity: Retry-After seconds must roughly match resets_at delta (±60 s tolerance).
    expected_seconds = int((resets_at - now_jst).total_seconds())
    assert abs(retry_seconds - expected_seconds) <= 60, (
        f"Retry-After ({retry_seconds}s) must be close to resets_at delta "
        f"({expected_seconds}s); diff = {abs(retry_seconds - expected_seconds)}s"
    )
