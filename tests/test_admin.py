"""Tests for internal admin endpoints (/v1/admin/*).

Coverage:
  1. 503 when ADMIN_API_KEY unset (safer default)
  2. 401 when header missing while key is configured
  3. 401 when header value wrong
  4. 200 happy path — /v1/admin/funnel
  5. 200 happy path — /v1/admin/cohort
  6. 200 happy path — /v1/admin/top-errors
  7. empty-table graceful degradation for funnel_daily + cohort_retention
  8. OpenAPI export does NOT surface /v1/admin/*
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

ADMIN_KEY = "test-admin-secret-xyz"


@pytest.fixture()
def admin_enabled(monkeypatch):
    """Flip settings.admin_api_key on for the duration of a test."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "admin_api_key", ADMIN_KEY, raising=False)
    yield ADMIN_KEY


@pytest.fixture()
def seed_funnel_tables(seeded_db: Path):
    """Create + populate funnel_daily and cohort_retention for happy-path tests.

    These tables are created by a future migration (see conversion_funnel.md §8).
    For tests we create them directly so the 200 happy paths exercise real SQL.
    """
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS funnel_daily (
                   date TEXT PRIMARY KEY,
                   visits INTEGER DEFAULT 0,
                   ctas INTEGER DEFAULT 0,
                   checkouts_started INTEGER DEFAULT 0,
                   checkouts_paid INTEGER DEFAULT 0,
                   keys_issued INTEGER DEFAULT 0,
                   first_api_calls INTEGER DEFAULT 0,
                   d7_retained INTEGER DEFAULT 0,
                   d30_retained INTEGER DEFAULT 0
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS cohort_retention (
                   cohort_month TEXT PRIMARY KEY,
                   active_d7 INTEGER DEFAULT 0,
                   active_d14 INTEGER DEFAULT 0,
                   active_d21 INTEGER DEFAULT 0,
                   active_d28 INTEGER DEFAULT 0,
                   churn_count INTEGER DEFAULT 0,
                   churn_reason_breakdown_json TEXT
               )"""
        )
        conn.execute("DELETE FROM funnel_daily")
        conn.execute("DELETE FROM cohort_retention")
        conn.executemany(
            """INSERT INTO funnel_daily(
                   date, visits, ctas, checkouts_started, checkouts_paid,
                   keys_issued, first_api_calls, d7_retained, d30_retained
               ) VALUES (?,?,?,?,?,?,?,?,?)""",
            [
                ("2026-05-06", 500, 60, 24, 7, 7, 5, 0, 0),
                ("2026-05-07", 610, 71, 28, 9, 9, 7, 0, 0),
                ("2026-05-08", 480, 55, 20, 6, 6, 4, 3, 0),
            ],
        )
        conn.execute(
            """INSERT INTO cohort_retention(
                   cohort_month, active_d7, active_d14, active_d21, active_d28,
                   churn_count, churn_reason_breakdown_json
               ) VALUES (?,?,?,?,?,?,?)""",
            (
                "2026-05",
                42,
                38,
                33,
                28,
                4,
                '{"price":2,"no_use_case":1,"bug":1}',
            ),
        )
        conn.commit()
        yield
    finally:
        # leave tables in place; no harm to other tests (they are namespaced)
        conn.close()


@pytest.fixture()
def drop_funnel_tables(seeded_db: Path):
    """Ensure the rollup tables are absent to exercise missing-table path."""
    conn = sqlite3.connect(seeded_db)
    try:
        conn.execute("DROP TABLE IF EXISTS funnel_daily")
        conn.execute("DROP TABLE IF EXISTS cohort_retention")
        conn.commit()
        yield
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


def test_admin_funnel_503_when_admin_key_disabled(client, monkeypatch):
    """Empty settings.admin_api_key → 503 regardless of any client header."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "admin_api_key", "", raising=False)
    r = client.get(
        "/v1/admin/funnel",
        params={"start": "2026-05-06", "end": "2026-05-20"},
        headers={"X-API-Key": "anything"},
    )
    assert r.status_code == 503
    assert "disabled" in r.json()["detail"].lower()


def test_admin_cohort_401_without_key(client, admin_enabled):
    """Configured admin key + missing X-API-Key header → 401."""
    r = client.get("/v1/admin/cohort", params={"cohort_month": "2026-05"})
    assert r.status_code == 401


def test_admin_top_errors_401_with_wrong_key(client, admin_enabled):
    r = client.get(
        "/v1/admin/top-errors",
        headers={"X-API-Key": "not-the-admin-key"},
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Happy paths (tables populated)
# ---------------------------------------------------------------------------


def test_admin_funnel_happy_path(client, admin_enabled, seed_funnel_tables):
    r = client.get(
        "/v1/admin/funnel",
        params={"start": "2026-05-06", "end": "2026-05-08"},
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["start"] == "2026-05-06"
    assert body["end"] == "2026-05-08"
    assert body["note"] is None
    rows = body["rows"]
    assert len(rows) == 3
    assert rows[0]["date"] == "2026-05-06"
    assert rows[0]["visits"] == 500
    assert rows[0]["checkouts_paid"] == 7
    assert rows[2]["d7_retained"] == 3


def test_admin_cohort_happy_path(client, admin_enabled, seed_funnel_tables):
    r = client.get(
        "/v1/admin/cohort",
        params={"cohort_month": "2026-05"},
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cohort_month"] == "2026-05"
    assert body["active_d7"] == 42
    assert body["active_d28"] == 28
    assert body["churn_count"] == 4
    assert body["churn_reason_breakdown"] == {
        "price": 2,
        "no_use_case": 1,
        "bug": 1,
    }


def test_admin_top_errors_happy_path(client, admin_enabled, seeded_db: Path):
    """Seed usage_events with a mix of 2xx and 4xx/5xx, verify ranking."""
    # issue a key so we satisfy the NOT NULL key_hash foreign key on usage_events
    from jpintel_mcp.billing.keys import issue_key

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        raw = issue_key(c, customer_id="cus_admin_test", tier="free", stripe_subscription_id=None)
        c.commit()
    finally:
        c.close()
    from jpintel_mcp.api.deps import hash_api_key

    kh = hash_api_key(raw)

    now = datetime.now(UTC)
    recent = now - timedelta(minutes=30)

    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM usage_events WHERE key_hash = ?", (kh,))
        events = [
            (kh, "programs.search", recent.isoformat(), 200, 0),
            (kh, "programs.search", recent.isoformat(), 400, 0),
            (kh, "programs.search", recent.isoformat(), 400, 0),
            (kh, "programs.search", recent.isoformat(), 400, 0),
            (kh, "programs.get", recent.isoformat(), 404, 0),
            (kh, "programs.get", recent.isoformat(), 500, 0),
            (kh, "programs.get", recent.isoformat(), 500, 0),
        ]
        c.executemany(
            "INSERT INTO usage_events(key_hash, endpoint, ts, status, metered) VALUES (?,?,?,?,?)",
            events,
        )
        c.commit()
    finally:
        c.close()

    r = client.get(
        "/v1/admin/top-errors",
        params={"hours": 24, "limit": 10},
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hours"] == 24
    assert body["limit"] == 10
    errors = body["errors"]
    # Top row should be programs.search / 400 with count 3
    assert errors[0]["endpoint"] == "programs.search"
    assert errors[0]["status_code"] == 400
    assert errors[0]["error_class"] == "4xx"
    assert errors[0]["count"] == 3
    # 500s present, classed as 5xx
    fives = [e for e in errors if e["status_code"] == 500]
    assert fives and fives[0]["error_class"] == "5xx"
    # 200 rows must NOT appear
    assert all(e["status_code"] >= 400 for e in errors)


def test_admin_analytics_split_happy_path(client, admin_enabled, seeded_db: Path):
    """Seed bot + human rows and verify conversion denominators exclude bots."""
    now = datetime.now(UTC).isoformat()

    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM analytics_events")
        c.execute("DELETE FROM funnel_events WHERE session_id LIKE 'split-%'")
        c.executemany(
            """INSERT INTO analytics_events(
                   ts, method, path, status, latency_ms, key_hash, anon_ip_hash,
                   client_tag, is_anonymous, user_agent_class, is_bot
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    now,
                    "GET",
                    "/_test/playground.html",
                    200,
                    12,
                    None,
                    "anon-a",
                    None,
                    1,
                    "browser:chrome",
                    0,
                ),
                (
                    now,
                    "GET",
                    "/_test/pricing.html",
                    200,
                    10,
                    None,
                    "anon-b",
                    None,
                    1,
                    "browser:chrome",
                    0,
                ),
                (
                    now,
                    "POST",
                    "/_test/v1/programs/search",
                    200,
                    45,
                    "key-hash-1",
                    None,
                    "claude",
                    0,
                    "claude-code",
                    0,
                ),
                (
                    now,
                    "GET",
                    "/_test/robots",
                    200,
                    8,
                    None,
                    "anon-bot",
                    None,
                    1,
                    "bot:googlebot",
                    1,
                ),
                (
                    now,
                    "POST",
                    "/v1/funnel/event",
                    202,
                    9,
                    None,
                    "anon-funnel",
                    None,
                    1,
                    "browser:funnel-beacon",
                    0,
                ),
            ],
        )
        c.executemany(
            """INSERT INTO funnel_events(
                   ts, event_name, page, properties_json, anon_ip_hash,
                   session_id, key_hash, user_agent_class, is_bot,
                   is_anonymous, referer_host
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    now,
                    "pricing_view",
                    "/pricing.html",
                    None,
                    "anon-a",
                    "split-1",
                    None,
                    "browser:chrome",
                    0,
                    1,
                    "chatgpt.com",
                ),
                (
                    now,
                    "pricing_view",
                    "/pricing.html",
                    None,
                    "anon-b",
                    "split-2",
                    None,
                    "browser:chrome",
                    0,
                    1,
                    "claude.ai",
                ),
                (
                    now,
                    "cta_click",
                    "/pricing.html",
                    None,
                    "anon-bot",
                    "split-bot",
                    None,
                    "bot:googlebot",
                    1,
                    1,
                    "google.com",
                ),
            ],
        )
        c.commit()
    finally:
        c.close()

    r = client.get(
        "/v1/admin/analytics_split",
        params={"hours": 24},
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bot_requests"] == 1
    assert body["human_requests"] == 3
    assert body["paid_conversion_denominator_human_request"] == body[
        "human_requests"
    ]

    by_ua = {row["user_agent_class"]: row for row in body["by_ua_class"]}
    assert by_ua["browser:chrome"]["request_count"] >= 2
    assert by_ua["browser:chrome"]["is_bot"] is False
    assert by_ua["bot:googlebot"]["is_bot"] is True
    assert "browser:funnel-beacon" not in by_ua

    funnel = {row["event_name"]: row for row in body["funnel_events"]}
    assert funnel["pricing_view"]["human_count"] >= 2
    assert funnel["pricing_view"]["distinct_sessions"] >= 2
    assert funnel["cta_click"]["bot_count"] >= 1


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


def test_admin_funnel_empty_when_table_missing(
    client, admin_enabled, drop_funnel_tables
):
    r = client.get(
        "/v1/admin/funnel",
        params={"start": "2026-05-06", "end": "2026-05-20"},
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows"] == []
    assert body["note"] is not None
    assert "funnel_daily" in body["note"]


def test_admin_cohort_zero_when_table_missing(
    client, admin_enabled, drop_funnel_tables
):
    r = client.get(
        "/v1/admin/cohort",
        params={"cohort_month": "2026-05"},
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active_d7"] == 0
    assert body["churn_count"] == 0
    assert body["churn_reason_breakdown"] == {}
    # Cohort note must explain the zero-rows surface (table missing).
    assert isinstance(body["note"], str) and len(body["note"]) > 0


# ---------------------------------------------------------------------------
# OpenAPI hygiene — admin must not leak into the public contract
# ---------------------------------------------------------------------------


def test_admin_paths_absent_from_openapi(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = set(r.json()["paths"].keys())
    for p in paths:
        assert not p.startswith("/v1/admin/"), (
            f"admin path {p!r} must not appear in /openapi.json"
        )
