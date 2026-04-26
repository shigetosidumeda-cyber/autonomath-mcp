"""Tests for the Tier 2 self-serve dashboard endpoints (api/dashboard.py).

Covers the four bearer-authenticated routes:
  - GET /v1/me/dashboard
  - GET /v1/me/usage_by_tool
  - GET /v1/me/billing_history
  - GET /v1/me/tool_recommendation

Auth model:
  Each endpoint requires `X-API-Key` (or `Authorization: Bearer …`).
  Anonymous calls return 401 (the dashboard.py module re-checks key_hash
  on top of require_key's permissive anon=tier:free fallback).
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from jpintel_mcp.api.deps import hash_api_key
from jpintel_mcp.billing.keys import issue_key

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_billing_cache():
    """Drop the in-process billing cache between tests so a stale entry from
    one test cannot mask a different invoice list in the next.
    """
    from jpintel_mcp.api.dashboard import _reset_billing_cache_state

    _reset_billing_cache_state()
    yield
    _reset_billing_cache_state()


@pytest.fixture()
def fresh_paid_key(seeded_db) -> str:
    """One-shot paid key per test (prevents quota / count bleed)."""
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    sub_id = f"sub_dash_{uuid.uuid4().hex[:8]}"
    raw = issue_key(
        c,
        customer_id=f"cus_dash_{uuid.uuid4().hex[:8]}",
        tier="paid",
        stripe_subscription_id=sub_id,
    )
    c.commit()
    c.close()
    return raw


def _seed_usage(
    db_path, key_hash: str, *, endpoint: str, count: int, days_ago: int = 0,
    metered: int = 1, status: int = 200,
) -> None:
    """Insert N usage_events rows for a given endpoint at days_ago."""
    base = datetime.now(UTC) - timedelta(days=days_ago, hours=1)
    rows = [
        (
            key_hash,
            endpoint,
            (base + timedelta(seconds=i)).isoformat(),
            status,
            metered,
        )
        for i in range(count)
    ]
    c = sqlite3.connect(db_path)
    try:
        c.executemany(
            "INSERT INTO usage_events(key_hash, endpoint, ts, status, metered) "
            "VALUES (?,?,?,?,?)",
            rows,
        )
        c.commit()
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Auth posture — anon is 401
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/v1/me/dashboard",
        "/v1/me/usage_by_tool",
        "/v1/me/billing_history",
        "/v1/me/tool_recommendation?intent=税制",
    ],
)
def test_anonymous_caller_is_401(client, path):
    r = client.get(path)
    assert r.status_code == 401, r.text


@pytest.mark.parametrize(
    "path",
    [
        "/v1/me/dashboard",
        "/v1/me/usage_by_tool",
        "/v1/me/billing_history",
        "/v1/me/tool_recommendation?intent=融資",
    ],
)
def test_revoked_key_is_401(client, fresh_paid_key, seeded_db, path):
    with sqlite3.connect(seeded_db) as c:
        c.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE key_hash = ?",
            (datetime.now(UTC).isoformat(), hash_api_key(fresh_paid_key)),
        )
        c.commit()
    r = client.get(path, headers={"X-API-Key": fresh_paid_key})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# /v1/me/dashboard — usage summary
# ---------------------------------------------------------------------------


def test_dashboard_empty_returns_zeros(client, fresh_paid_key):
    r = client.get(
        "/v1/me/dashboard", headers={"X-API-Key": fresh_paid_key}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["days"] == 30
    assert len(body["series"]) == 30
    assert body["last_30_calls"] == 0
    assert body["last_30_amount_yen"] == 0
    assert body["peak_day"] is None
    assert body["unit_price_yen"] == 3
    assert body["monthly_cap_yen"] is None
    assert body["cap_remaining_yen"] is None


def test_dashboard_aggregates_call_counts(
    client, fresh_paid_key, seeded_db
):
    kh = hash_api_key(fresh_paid_key)
    _seed_usage(seeded_db, kh, endpoint="programs.search", count=12, days_ago=0)
    _seed_usage(seeded_db, kh, endpoint="laws.search", count=4, days_ago=2)

    r = client.get(
        "/v1/me/dashboard?days=30", headers={"X-API-Key": fresh_paid_key}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["last_30_calls"] == 16
    assert body["last_30_amount_yen"] == 16 * 3
    assert body["today_calls"] == 12
    # peak_day should point at today
    assert body["peak_day"] is not None
    assert body["peak_day"]["calls"] == 12


def test_dashboard_clamps_days_param(client, fresh_paid_key):
    # ge=1, le=90 — values out of range should be 422.
    r = client.get(
        "/v1/me/dashboard?days=0", headers={"X-API-Key": fresh_paid_key}
    )
    assert r.status_code == 422
    r = client.get(
        "/v1/me/dashboard?days=400", headers={"X-API-Key": fresh_paid_key}
    )
    assert r.status_code == 422


def test_dashboard_reports_cap_state(client, fresh_paid_key, seeded_db):
    kh = hash_api_key(fresh_paid_key)
    # Set a cap directly + seed metered+success usage in this UTC month
    with sqlite3.connect(seeded_db) as c:
        c.execute(
            "UPDATE api_keys SET monthly_cap_yen = ? WHERE key_hash = ?",
            (1000, kh),
        )
        c.commit()
    _seed_usage(
        seeded_db, kh, endpoint="programs.search", count=50,
        metered=1, status=200,
    )
    r = client.get(
        "/v1/me/dashboard", headers={"X-API-Key": fresh_paid_key}
    )
    body = r.json()
    assert body["monthly_cap_yen"] == 1000
    assert body["month_to_date_calls"] >= 50
    # 50 * ¥3 = ¥150 spent -> ¥850 remaining (or ≤ that)
    assert body["cap_remaining_yen"] is not None
    assert body["cap_remaining_yen"] <= 850


# ---------------------------------------------------------------------------
# /v1/me/usage_by_tool — top N tools
# ---------------------------------------------------------------------------


def test_usage_by_tool_orders_by_count_desc(
    client, fresh_paid_key, seeded_db
):
    kh = hash_api_key(fresh_paid_key)
    _seed_usage(seeded_db, kh, endpoint="programs.search", count=20)
    _seed_usage(seeded_db, kh, endpoint="laws.search", count=7)
    _seed_usage(seeded_db, kh, endpoint="enforcement.search", count=15)

    r = client.get(
        "/v1/me/usage_by_tool?days=30",
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_calls"] == 42
    assert body["total_amount_yen"] == 42 * 3
    names = [row["endpoint"] for row in body["top"]]
    # programs (20) > enforcement (15) > laws (7)
    assert names[:3] == ["programs.search", "enforcement.search", "laws.search"]
    # amount_yen reflects metered+success only
    p = next(row for row in body["top"] if row["endpoint"] == "programs.search")
    assert p["amount_yen"] == 20 * 3


def test_usage_by_tool_excludes_other_keys(
    client, fresh_paid_key, seeded_db
):
    """Telemetry isolation: another key's usage MUST NOT leak into the response."""
    kh = hash_api_key(fresh_paid_key)
    _seed_usage(seeded_db, kh, endpoint="programs.search", count=3)

    # Seed a *different* key's usage that should not appear
    other = sqlite3.connect(seeded_db)
    try:
        other_raw = issue_key(other, customer_id=f"cus_other_{uuid.uuid4().hex[:6]}", tier="paid")
        other.commit()
    finally:
        other.close()
    other_kh = hash_api_key(other_raw)
    _seed_usage(seeded_db, other_kh, endpoint="programs.search", count=999)

    r = client.get(
        "/v1/me/usage_by_tool", headers={"X-API-Key": fresh_paid_key}
    )
    body = r.json()
    assert body["total_calls"] == 3  # only this key's 3 rows


# ---------------------------------------------------------------------------
# /v1/me/billing_history — Stripe-less env returns empty list
# ---------------------------------------------------------------------------


def test_billing_history_empty_when_stripe_unconfigured(
    client, fresh_paid_key
):
    """Local/test runs have no STRIPE_SECRET_KEY; expect empty list, not 500."""
    r = client.get(
        "/v1/me/billing_history", headers={"X-API-Key": fresh_paid_key}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["invoices"] == []
    assert body["customer_id"] is not None  # cus_dash_…


def test_billing_history_no_customer_id_returns_empty(
    client, fresh_paid_key, seeded_db
):
    """A key with NULL customer_id (e.g. legacy bootstrap) returns
    `customer_id=None` + empty list rather than 500."""
    kh = hash_api_key(fresh_paid_key)
    with sqlite3.connect(seeded_db) as c:
        c.execute(
            "UPDATE api_keys SET customer_id = NULL WHERE key_hash = ?",
            (kh,),
        )
        c.commit()
    r = client.get(
        "/v1/me/billing_history", headers={"X-API-Key": fresh_paid_key}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["customer_id"] is None
    assert body["invoices"] == []


# ---------------------------------------------------------------------------
# /v1/me/tool_recommendation — keyword scoring
# ---------------------------------------------------------------------------


def test_recommendation_tax_query_returns_tax_tool(client, fresh_paid_key):
    r = client.get(
        "/v1/me/tool_recommendation?intent=税額控除に関する条文",
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code == 200
    body = r.json()
    names = [t["name"] for t in body["tools"]]
    assert "am.tax_incentives.search" in names
    # 法令 keyword should also fire
    assert "laws.search" in names
    assert body["fallback_used"] is False


def test_recommendation_subsidy_keyword(client, fresh_paid_key):
    r = client.get(
        "/v1/me/tool_recommendation?intent=設備投資の補助金",
        headers={"X-API-Key": fresh_paid_key},
    )
    body = r.json()
    names = [t["name"] for t in body["tools"]]
    assert "programs.search" in names


def test_recommendation_unknown_query_falls_back(client, fresh_paid_key):
    r = client.get(
        "/v1/me/tool_recommendation?intent=quantum%20foo%20bar",
        headers={"X-API-Key": fresh_paid_key},
    )
    body = r.json()
    assert body["fallback_used"] is True
    assert len(body["tools"]) >= 1
    # Fallback must include programs.search (top default)
    names = [t["name"] for t in body["tools"]]
    assert "programs.search" in names
    # Confidence is the deterministic fallback constant
    for t in body["tools"]:
        assert t["confidence"] == pytest.approx(0.2)


def test_recommendation_limit_clamp(client, fresh_paid_key):
    r = client.get(
        "/v1/me/tool_recommendation?intent=税&limit=2",
        headers={"X-API-Key": fresh_paid_key},
    )
    body = r.json()
    assert len(body["tools"]) <= 2


def test_recommendation_returns_endpoint_path(client, fresh_paid_key):
    """Each recommendation must have a callable REST path so the SDK doesn't
    have to second-guess the URL."""
    r = client.get(
        "/v1/me/tool_recommendation?intent=入札",
        headers={"X-API-Key": fresh_paid_key},
    )
    body = r.json()
    assert body["tools"], body
    bid = next((t for t in body["tools"] if t["name"] == "bids.search"), None)
    assert bid is not None
    assert bid["endpoint"].startswith("/v1/")
    assert bid["why"]
