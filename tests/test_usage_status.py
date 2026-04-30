"""Tests for the Wave 17 P1 quota-probe surface (REST + MCP).

Covers two paths:

  * REST ``GET /v1/usage`` — anonymous + authenticated (paid) responses.
    The handler is intentionally unmounted from ``AnonIpLimitDep`` so a
    probe never burns the runway it's reporting on; both tests below
    assert that probing twice does NOT increment the anon counter.

  * MCP ``get_usage_status`` tool — anonymous (no key) + paid key. The
    MCP transport carries no client IP, so the anonymous response must
    be honest about that (``remaining=None`` plus a note pointing at
    the REST surface for the exact count).

Timezone notes (CLAUDE.md "Common gotchas"):
  * Anonymous quota resets at JST 月初 00:00 — these tests assert the
    response carries ``reset_timezone="JST"`` AND that the ``reset_at``
    ISO timestamp ends with the JST offset ``+09:00``.
  * Paid quota resets at UTC 月初 00:00 — assert ``reset_timezone="UTC"``
    and the ISO timestamp ends with ``+00:00``.
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# REST: GET /v1/usage
# ---------------------------------------------------------------------------


def test_rest_anonymous_usage_returns_50_limit_and_jst_reset(
    client: "TestClient",
) -> None:
    """No X-API-Key → tier=anonymous, limit=50, used=0, reset_at JST."""
    r = client.get("/v1/usage", headers={"x-forwarded-for": "203.0.113.50"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tier"] == "anonymous"
    assert body["limit"] == 50
    # No prior anon traffic from this IP this month → used=0, remaining=50.
    assert body["used"] == 0
    assert body["remaining"] == 50
    assert body["reset_timezone"] == "JST"
    # JST month-start ISO ends with +09:00 offset.
    assert body["reset_at"].endswith("+09:00"), body["reset_at"]
    # Upgrade landing surfaced for free-tier callers. The brand was renamed
    # autonomath.ai → zeimu-kaikei.ai → jpcite.com across rebrand passes;
    # all three apex variants are accepted so a future re-rebrand survives
    # without silently dropping the assertion.
    upgrade_url = body["upgrade_url"]
    assert (
        upgrade_url.startswith("https://jpcite.com/")
        or upgrade_url.startswith("https://zeimu-kaikei.ai/")
        or upgrade_url.startswith("https://autonomath.ai/")
    ), f"unexpected upgrade_url={upgrade_url!r}"


def test_rest_anonymous_usage_does_not_consume_quota(
    client: "TestClient", seeded_db: "Path"
) -> None:
    """The probe must be free — calling it never increments anon_rate_limit.

    Hits /v1/usage 3 times then verifies anon_rate_limit row count is 0.
    Otherwise the probe itself burns the runway it's meant to report on.
    """
    ip = "203.0.113.51"
    for _ in range(3):
        r = client.get("/v1/usage", headers={"x-forwarded-for": ip})
        assert r.status_code == 200

    # No row inserted (the probe didn't go through enforce_anon_ip_limit).
    c = sqlite3.connect(seeded_db)
    try:
        (n,) = c.execute("SELECT COUNT(*) FROM anon_rate_limit").fetchone()
    finally:
        c.close()
    assert n == 0, f"probe inserted {n} anon_rate_limit rows; expected 0"


def test_rest_anonymous_usage_reflects_existing_count(
    client: "TestClient", seeded_db: "Path"
) -> None:
    """If the IP+fingerprint hash already has N calls this month, the
    probe MUST report used=N / remaining=50-N.
    """
    # Burn 2 anon slots first via /meta (which IS anon-quota-gated).
    ip = "203.0.113.52"
    for _ in range(2):
        r = client.get("/meta", headers={"x-forwarded-for": ip})
        assert r.status_code == 200

    # Now probe — same IP, same fingerprint (TestClient defaults).
    r = client.get("/v1/usage", headers={"x-forwarded-for": ip})
    body = r.json()
    assert body["used"] == 2, body
    assert body["remaining"] == 50 - 2, body


def test_rest_paid_usage_returns_paid_tier_and_utc_reset(
    client: "TestClient", paid_key: str
) -> None:
    """X-API-Key (paid tier) → tier=paid, limit=null, reset_at UTC."""
    r = client.get("/v1/usage", headers={"X-API-Key": paid_key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tier"] == "paid"
    assert body["limit"] is None
    assert body["remaining"] is None
    # used starts at 0 for a freshly-issued key.
    assert body["used"] == 0
    assert body["reset_timezone"] == "UTC"
    assert body["reset_at"].endswith("+00:00"), body["reset_at"]
    # Paid tier no longer needs the upgrade landing.
    assert body["upgrade_url"] is None


# ---------------------------------------------------------------------------
# MCP tool: get_usage_status
# ---------------------------------------------------------------------------


def test_mcp_get_usage_status_anonymous_returns_ceiling_and_jst_note(
    client: "TestClient",
) -> None:
    """No api_key → ceiling + honest "MCP cannot resolve IP" note.

    `client` fixture is required so the app (and its modules) are loaded
    before we touch the MCP-side function.
    """
    from jpintel_mcp.mcp.server import get_usage_status

    res = get_usage_status()
    assert res["tier"] == "anonymous"
    assert res["limit"] == 50
    assert res["remaining"] is None  # unknown over MCP stdio
    assert res["reset_timezone"] == "JST"
    assert res["reset_at"].endswith("+09:00")
    assert "MCP" in res["note"] and "/v1/usage" in res["note"]


def test_mcp_get_usage_status_unknown_key_surfaces_error_envelope(
    client: "TestClient",
) -> None:
    """An unrecognised api_key returns a structured error envelope.

    Doesn't 500 — the tool always returns a dict the LLM can introspect.
    """
    from jpintel_mcp.mcp.server import get_usage_status

    res = get_usage_status(api_key="am_definitely_not_a_real_key")
    assert res["tier"] == "unknown"
    assert "error" in res
    assert res["error"]["code"] == "key_not_found"


def test_mcp_get_usage_status_paid_key_returns_paid_tier(
    client: "TestClient", paid_key: str
) -> None:
    """Paid api_key → tier=paid, used=0, UTC reset boundary."""
    from jpintel_mcp.mcp.server import get_usage_status

    res = get_usage_status(api_key=paid_key)
    assert res["tier"] == "paid"
    assert res["limit"] is None
    assert res["remaining"] is None
    assert res["used"] == 0
    assert res["reset_timezone"] == "UTC"
    assert res["reset_at"].endswith("+00:00")
