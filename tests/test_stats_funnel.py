from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


ADMIN_KEY = "test-admin-secret-xyz"


@pytest.fixture()
def admin_enabled(monkeypatch: pytest.MonkeyPatch) -> str:
    from jpintel_mcp.api import admin as admin_mod
    from jpintel_mcp.config import settings

    for settings_obj in (settings, admin_mod.settings):
        monkeypatch.setattr(settings_obj, "admin_api_key", ADMIN_KEY, raising=False)
    return ADMIN_KEY


@pytest.fixture()
def stats_funnel_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from jpintel_mcp.config import settings
    from jpintel_mcp.db.session import init_db

    db_path = tmp_path / "stats_funnel.db"
    init_db(db_path)
    monkeypatch.setenv("JPINTEL_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_DB_PATH", str(db_path))
    monkeypatch.setattr(settings, "db_path", db_path, raising=False)
    return db_path


@pytest.fixture()
def stats_funnel_client(stats_funnel_db: Path, admin_enabled: str):
    from fastapi.testclient import TestClient

    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


def test_stats_funnel_uses_billable_quantity_not_request_count(
    stats_funnel_client,
    stats_funnel_db: Path,
) -> None:
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    today_s = today.isoformat()
    yesterday_s = yesterday.isoformat()

    conn = sqlite3.connect(stats_funnel_db)
    try:
        conn.execute("DELETE FROM usage_events")
        conn.execute("DELETE FROM api_keys")
        conn.execute("DELETE FROM anon_rate_limit")
        conn.executemany(
            "INSERT INTO api_keys(key_hash, customer_id, tier, stripe_subscription_id, created_at) "
            "VALUES (?,?,?,?,?)",
            [
                ("key_a", "cus_a", "paid", "sub_a", f"{today_s}T01:00:00+00:00"),
                ("key_b", "cus_b", "paid", "sub_b", f"{yesterday_s}T01:00:00+00:00"),
            ],
        )
        conn.executemany(
            "INSERT INTO anon_rate_limit(ip_hash, date, call_count, first_seen, last_seen) "
            "VALUES (?,?,?,?,?)",
            [
                ("ip_today", today_s, 1, f"{today_s}T00:00:00+00:00", f"{today_s}T00:00:00+00:00"),
                (
                    "ip_yesterday",
                    yesterday_s,
                    1,
                    f"{yesterday_s}T00:00:00+00:00",
                    f"{yesterday_s}T00:00:00+00:00",
                ),
            ],
        )
        conn.executemany(
            "INSERT INTO usage_events("
            "key_hash, endpoint, ts, status, metered, quantity, stripe_synced_at"
            ") VALUES (?,?,?,?,?,?,?)",
            [
                ("key_a", "/v1/bulk", f"{today_s}T02:00:00+00:00", 200, 1, 50, None),
                # Failed metered rows count as requests, not billable units.
                ("key_a", "/v1/bulk", f"{today_s}T03:00:00+00:00", 500, 1, 99, None),
                # Non-metered rows count as requests, not revenue.
                ("key_b", "/v1/usage", f"{today_s}T04:00:00+00:00", 200, 0, 7, None),
                (
                    "key_b",
                    "/v1/bulk",
                    f"{yesterday_s}T02:00:00+00:00",
                    200,
                    1,
                    3,
                    f"{yesterday_s}T02:01:00+00:00",
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    response = stats_funnel_client.get(
        "/v1/stats/funnel",
        params={"days": 2},
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    rows = {row["date"]: row for row in body["rows"]}

    assert rows[today_s]["requests"] == 3
    assert rows[today_s]["keys_with_requests"] == 2
    assert rows[today_s]["metered_requests"] == 1
    assert rows[today_s]["billable_units"] == 50
    assert rows[today_s]["revenue_jpy_ex_tax"] == 150
    assert rows[today_s]["revenue_jpy_inc_tax_estimate"] == 165.0
    assert rows[today_s]["stripe_unsynced_units"] == 50
    assert rows[today_s]["first_metered_request"] == 1
    assert rows[today_s]["daily_goal_billable_units"] == 100_000
    assert rows[today_s]["daily_goal_progress_pct"] == 0.05

    assert rows[yesterday_s]["billable_units"] == 3
    assert rows[yesterday_s]["stripe_unsynced_units"] == 0
    assert rows[yesterday_s]["first_metered_request"] == 1

    assert body["totals"]["requests"] == 4
    assert body["totals"]["keys_with_requests"] == 2
    assert body["totals"]["metered_requests"] == 2
    assert body["totals"]["billable_units"] == 53
    assert body["totals"]["keys_with_billable_units"] == 2
    assert body["totals"]["revenue_jpy_ex_tax"] == 159
    assert body["totals"]["revenue_jpy_inc_tax_estimate"] == 174.9
    assert body["totals"]["stripe_unsynced_units"] == 50
    assert body["totals"]["average_daily_billable_units"] == 26.5
