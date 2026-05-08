from __future__ import annotations

import importlib.util
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _load_ops_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "ops_quick_stats.py"
    spec = importlib.util.spec_from_file_location("_ops_quick_stats_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE api_keys(
            key_hash TEXT PRIMARY KEY,
            revoked_at TEXT,
            monthly_cap_yen INTEGER
        );
        CREATE TABLE usage_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_hash TEXT,
            endpoint TEXT,
            ts TEXT,
            status INTEGER,
            metered INTEGER,
            quantity INTEGER,
            stripe_synced_at TEXT,
            client_tag TEXT
        );
        CREATE TABLE analytics_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            method TEXT,
            path TEXT,
            status INTEGER,
            key_hash TEXT
        );
        """
    )
    return conn


def test_ops_quick_stats_mrr_and_cap_use_quantity() -> None:
    ops = _load_ops_module()
    conn = _conn()
    now = datetime.now(UTC).isoformat()
    try:
        conn.execute(
            "INSERT INTO api_keys(key_hash, revoked_at, monthly_cap_yen) VALUES (?,?,?)",
            ("kh1", None, 12),
        )
        conn.executemany(
            "INSERT INTO usage_events(key_hash, endpoint, ts, status, metered, quantity) "
            "VALUES (?,?,?,?,?,?)",
            [
                ("kh1", "batch.ok", now, 200, 1, 5),
                ("kh1", "batch.failed", now, 500, 1, 99),
                ("kh1", "free", now, 200, 0, 50),
            ],
        )
        conn.commit()

        assert ops.mrr_for_window(conn, "2000-01-01T00:00:00+00:00") == 5 * 3
        assert ops.cap_usage(conn) == (1, 1)
    finally:
        conn.close()


def test_ops_quick_stats_unsynced_units_sum_quantity() -> None:
    ops = _load_ops_module()
    conn = _conn()
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    try:
        conn.execute(
            "INSERT INTO api_keys(key_hash, revoked_at, monthly_cap_yen) VALUES (?,?,?)",
            ("kh1", None, None),
        )
        conn.executemany(
            "INSERT INTO usage_events(key_hash, endpoint, ts, status, metered, quantity, stripe_synced_at) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                ("kh1", "batch", old, 200, 1, 7, None),
                ("kh1", "single", old, 200, 1, 1, None),
                ("kh1", "synced", old, 200, 1, 10, old),
            ],
        )
        conn.commit()

        assert ops.unsynced_metered_events(conn) == 2
        assert ops.unsynced_metered_units(conn) == 8
        assert ops.classify({"unsynced_metered_units": 8})["unsynced_metered_events"] == "warn"
    finally:
        conn.close()


def test_ops_quick_stats_demand_shape_metrics_use_quantity_and_tags() -> None:
    ops = _load_ops_module()
    conn = _conn()
    now = datetime.now(UTC).isoformat()
    try:
        conn.executemany(
            "INSERT INTO usage_events("
            "key_hash, endpoint, ts, status, metered, quantity, client_tag"
            ") VALUES (?,?,?,?,?,?,?)",
            [
                ("kh1", "workflow", now, 200, 1, 70, "client-a"),
                ("kh1", "workflow", now, 200, 1, 10, "client-b"),
                ("kh2", "single", now, 200, 1, 20, None),
                ("kh2", "failed", now, 500, 1, 900, "client-c"),
                ("kh3", "free", now, 200, 0, 30, "client-d"),
            ],
        )
        conn.executemany(
            "INSERT INTO analytics_events(ts, method, path, status, key_hash) VALUES (?,?,?,?,?)",
            [
                (now, "POST", "/v1/cost/preview", 200, "kh1"),
                (now, "POST", "/v1/cost/preview", 200, "kh4"),
                (now, "POST", "/v1/cost/preview", 500, "kh2"),
            ],
        )
        conn.commit()

        tagged_units, total_units, tag_pairs, pct = ops.client_tag_demand_30d(conn)
        assert tagged_units == 80
        assert total_units == 100
        assert tag_pairs == 2
        assert pct == 80.0
        assert ops.billable_units_since(conn, "2000-01-01T00:00:00+00:00") == 100
        assert ops.billable_keys_since(conn, "2000-01-01T00:00:00+00:00") == 2
        assert ops.top_key_share_30d_pct(conn) == 80.0
        assert ops.cost_preview_requests_7d(conn) == 2
        assert ops.cost_preview_to_billable_7d_pct(conn) == 50.0
        assert (
            ops.classify({"top_key_30d_billable_units_share_pct": 80.0})[
                "top_key_30d_billable_units_share_pct"
            ]
            == "warn"
        )
    finally:
        conn.close()
