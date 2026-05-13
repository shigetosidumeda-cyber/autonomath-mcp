"""Regression tests for meta_analysis_daily SQLite safety."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CRON_FILE = REPO_ROOT / "scripts" / "cron" / "meta_analysis_daily.py"


def _load_cron_module():
    spec = importlib.util.spec_from_file_location("meta_analysis_daily_test", CRON_FILE)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_open_autonomath_ro_uses_file_uri_and_query_only(tmp_path: Path) -> None:
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE am_data_quality_snapshot (snapshot_at TEXT)")
        conn.commit()
    finally:
        conn.close()

    cron = _load_cron_module()
    uri = cron._sqlite_readonly_uri(db_path)
    assert uri.startswith("file:")
    assert uri.endswith("?mode=ro")

    ro = cron._open_autonomath_ro(db_path)
    try:
        assert ro.execute("PRAGMA query_only").fetchone()[0] == 1
        try:
            ro.execute("INSERT INTO am_data_quality_snapshot VALUES ('2026-05-13')")
            raise AssertionError("query_only connection should reject writes")
        except sqlite3.DatabaseError as exc:
            assert "readonly" in str(exc).lower() or "query only" in str(exc).lower()
    finally:
        ro.close()


def test_bounded_row_count_uses_sqlite_stat1_estimate_without_full_count() -> None:
    cron = _load_cron_module()
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE big_table (id INTEGER PRIMARY KEY, computed_at TEXT)")
        conn.executemany(
            "INSERT INTO big_table (computed_at) VALUES (?)",
            [(f"2026-05-13T00:00:0{i}Z",) for i in range(4)],
        )
        conn.execute("CREATE INDEX idx_big_table_computed_at ON big_table(computed_at)")
        conn.execute("ANALYZE")

        seen_sql: list[str] = []
        conn.set_trace_callback(seen_sql.append)
        row_count, row_count_kind = cron._bounded_row_count(conn, "big_table", limit=1)

        assert row_count == 4
        assert row_count_kind == "estimated"
        assert not any("COUNT(*) FROM big_table" in sql for sql in seen_sql)
    finally:
        conn.close()


def test_bounded_row_count_returns_lower_bound_without_stats() -> None:
    cron = _load_cron_module()
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE big_table (id INTEGER PRIMARY KEY)")
        conn.executemany("INSERT INTO big_table DEFAULT VALUES", [() for _ in range(4)])

        row_count, row_count_kind = cron._bounded_row_count(conn, "big_table", limit=1)

        assert row_count == 2
        assert row_count_kind == "lower_bound"
    finally:
        conn.close()


def test_latest_ts_skips_unindexed_timestamp_scan() -> None:
    cron = _load_cron_module()
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE events (computed_at TEXT)")
        conn.executemany(
            "INSERT INTO events VALUES (?)",
            [("2026-05-12T00:00:00Z",), ("2026-05-13T00:00:00Z",)],
        )

        last_ts, last_ts_kind = cron._latest_ts_indexed(conn, "events", "computed_at")

        assert last_ts is None
        assert last_ts_kind == "unindexed"
    finally:
        conn.close()


def test_latest_ts_uses_existing_timestamp_index() -> None:
    cron = _load_cron_module()
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE events (computed_at TEXT)")
        conn.executemany(
            "INSERT INTO events VALUES (?)",
            [("2026-05-12T00:00:00Z",), ("2026-05-13T00:00:00Z",)],
        )
        conn.execute("CREATE INDEX idx_events_computed_at ON events(computed_at)")

        last_ts, last_ts_kind = cron._latest_ts_indexed(conn, "events", "computed_at")

        assert last_ts == "2026-05-13T00:00:00Z"
        assert last_ts_kind == "indexed"
    finally:
        conn.close()
