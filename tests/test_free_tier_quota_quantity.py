from __future__ import annotations

import sqlite3

import pytest
from fastapi import HTTPException

from jpintel_mcp.api import deps
from jpintel_mcp.config import settings


def _conn_with_usage(rows: list[tuple[str, int | None]]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE usage_events (
            key_hash TEXT NOT NULL,
            ts TEXT NOT NULL,
            quantity INTEGER
        )
        """
    )
    for key_hash, quantity in rows:
        conn.execute(
            "INSERT INTO usage_events(key_hash, ts, quantity) VALUES (?, ?, ?)",
            (key_hash, deps._day_bucket() + "T00:00:00+00:00", quantity),
        )
    conn.commit()
    return conn


def test_free_tier_daily_quota_counts_billable_units(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_free_per_day", 3)
    conn = _conn_with_usage([("kh_free", 2), ("kh_free", 1)])
    ctx = deps.ApiContext(key_hash="kh_free", tier="free", customer_id="cus_free")

    with pytest.raises(HTTPException) as exc:
        deps._enforce_quota(conn, ctx)

    assert exc.value.status_code == 429


def test_free_tier_daily_quota_treats_null_quantity_as_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rate_limit_free_per_day", 2)
    conn = _conn_with_usage([("kh_free", None), ("kh_free", 1)])
    ctx = deps.ApiContext(key_hash="kh_free", tier="free", customer_id="cus_free")

    with pytest.raises(HTTPException) as exc:
        deps._enforce_quota(conn, ctx)

    assert exc.value.status_code == 429


def test_free_tier_daily_quota_allows_when_units_below_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rate_limit_free_per_day", 3)
    conn = _conn_with_usage([("kh_free", 2)])
    ctx = deps.ApiContext(key_hash="kh_free", tier="free", customer_id="cus_free")

    deps._enforce_quota(conn, ctx)
