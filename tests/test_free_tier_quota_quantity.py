from __future__ import annotations

import sqlite3

import pytest
from fastapi import BackgroundTasks, HTTPException

from jpintel_mcp.api import deps


def _conn_with_usage(rows: list[tuple[str, int | None]]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE api_keys (
            id INTEGER PRIMARY KEY,
            key_hash TEXT NOT NULL,
            parent_key_id INTEGER,
            last_used_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_hash TEXT NOT NULL,
            endpoint TEXT,
            ts TEXT NOT NULL,
            status INTEGER,
            metered INTEGER,
            params_digest TEXT,
            latency_ms INTEGER,
            result_count INTEGER,
            client_tag TEXT,
            billing_idempotency_key TEXT UNIQUE,
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


def _usage_units(conn: sqlite3.Connection, key_hash: str) -> int:
    (n,) = conn.execute(
        "SELECT COALESCE(SUM(COALESCE(quantity, 1)), 0) FROM usage_events WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    return int(n or 0)


def test_free_tier_daily_quota_counts_billable_units(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps.settings, "rate_limit_free_per_day", 3)
    conn = _conn_with_usage([("kh_free", 2), ("kh_free", 1)])
    ctx = deps.ApiContext(key_hash="kh_free", tier="free", customer_id="cus_free")

    with pytest.raises(HTTPException) as exc:
        deps._enforce_quota(conn, ctx)

    assert exc.value.status_code == 429


def test_free_tier_daily_quota_treats_null_quantity_as_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps.settings, "rate_limit_free_per_day", 2)
    conn = _conn_with_usage([("kh_free", None), ("kh_free", 1)])
    ctx = deps.ApiContext(key_hash="kh_free", tier="free", customer_id="cus_free")

    with pytest.raises(HTTPException) as exc:
        deps._enforce_quota(conn, ctx)

    assert exc.value.status_code == 429


def test_free_tier_daily_quota_allows_when_units_below_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps.settings, "rate_limit_free_per_day", 3)
    conn = _conn_with_usage([("kh_free", 2)])
    ctx = deps.ApiContext(key_hash="kh_free", tier="free", customer_id="cus_free")

    deps._enforce_quota(conn, ctx)


def test_free_tier_final_quota_counts_current_multi_unit_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps.settings, "rate_limit_free_per_day", 3)
    conn = _conn_with_usage([("kh_free", 2)])
    ctx = deps.ApiContext(key_hash="kh_free", tier="free", customer_id="cus_free")

    deps._enforce_quota(conn, ctx)
    with pytest.raises(HTTPException) as exc:
        deps.log_usage(
            conn,
            ctx,
            "clients.bulk_evaluate",
            quantity=2,
            background_tasks=BackgroundTasks(),
        )

    assert exc.value.status_code == 429
    assert _usage_units(conn, "kh_free") == 2


def test_free_tier_final_quota_inlines_allowed_multi_unit_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps.settings, "rate_limit_free_per_day", 3)
    conn = _conn_with_usage([("kh_free", 1)])
    ctx = deps.ApiContext(key_hash="kh_free", tier="free", customer_id="cus_free")

    deps.log_usage(
        conn,
        ctx,
        "clients.bulk_evaluate",
        quantity=2,
        background_tasks=BackgroundTasks(),
    )

    assert _usage_units(conn, "kh_free") == 3


def test_free_tier_final_quota_counts_parent_child_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps.settings, "rate_limit_free_per_day", 3)
    conn = _conn_with_usage([("kh_parent", 2)])
    conn.execute(
        "INSERT INTO api_keys(id, key_hash, parent_key_id) VALUES (?, ?, ?)",
        (1, "kh_parent", None),
    )
    conn.execute(
        "INSERT INTO api_keys(id, key_hash, parent_key_id) VALUES (?, ?, ?)",
        (2, "kh_child", 1),
    )
    conn.commit()
    ctx = deps.ApiContext(
        key_hash="kh_child",
        tier="free",
        customer_id="cus_free",
        key_id=2,
        parent_key_id=1,
    )

    deps._enforce_quota(conn, ctx)
    with pytest.raises(HTTPException) as exc:
        deps.log_usage(conn, ctx, "clients.bulk_evaluate", quantity=2)

    assert exc.value.status_code == 429
    assert _usage_units(conn, "kh_child") == 0
