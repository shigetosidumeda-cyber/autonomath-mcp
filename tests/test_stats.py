"""Tests for /v1/stats/* (P5-ι, brand 5-pillar transparent + anti-aggregator).

Coverage:
  1. /v1/stats/coverage returns COUNT(*) per dataset
  2. /v1/stats/coverage tolerates a missing table (returns 0, not 500)
  3. /v1/stats/freshness returns min/max/count + avg_interval_days per source
  4. /v1/stats/freshness handles a table with zero rows
  5. /v1/stats/usage returns 30 daily buckets with cumulative running total
  6. /v1/stats/usage zeroes a date with no events
  7. 5-minute in-memory cache: second call within TTL returns cached payload
  8. No auth required (no AnonIpLimitDep — same posture as meta_freshness)
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_stats_cache(seeded_db: Path):
    """Each test starts with a clean cache + clean usage_events table so
    TTL and event counts don't bleed across cases."""
    from jpintel_mcp.api.stats import _reset_stats_cache

    _reset_stats_cache()
    c = sqlite3.connect(seeded_db)
    try:
        source_snapshot = c.execute("SELECT unified_id, source_fetched_at FROM programs").fetchall()
        usage_columns = [row[1] for row in c.execute("PRAGMA table_info(usage_events)")]
        usage_snapshot = (
            usage_columns,
            c.execute("SELECT * FROM usage_events").fetchall(),
        )
        c.execute("DELETE FROM usage_events")
        c.commit()
    finally:
        c.close()
    try:
        yield
    finally:
        c = sqlite3.connect(seeded_db)
        try:
            c.execute("UPDATE programs SET source_fetched_at = NULL")
            c.executemany(
                "UPDATE programs SET source_fetched_at = ? WHERE unified_id = ?",
                [
                    (source_fetched_at, unified_id)
                    for unified_id, source_fetched_at in source_snapshot
                ],
            )
            columns, rows = usage_snapshot
            c.execute("DELETE FROM usage_events")
            if rows:
                col_sql = ",".join(columns)
                placeholders = ",".join("?" * len(columns))
                c.executemany(
                    f"INSERT INTO usage_events({col_sql}) VALUES ({placeholders})",
                    rows,
                )
            c.commit()
        finally:
            c.close()
        _reset_stats_cache()


def _live_count(seeded_db: Path, table: str) -> int:
    """Count rows in `table` on the shared session DB.

    The seeded_db fixture is session-scoped and other test modules insert
    additional rows (test_search_relevance, test_short_ascii_perf, etc.).
    Stats tests must read the live count instead of hard-coding 4 or they
    flake when ordering changes. Returns 0 if the table doesn't exist."""
    c = sqlite3.connect(seeded_db)
    try:
        try:
            row = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            return int(row[0]) if row else 0
        except sqlite3.OperationalError:
            return 0
    finally:
        c.close()


@pytest.fixture()
def _seed_usage_events(seeded_db: Path):
    """Seed `usage_events` rows across the past 30 days for /v1/stats/usage."""
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM usage_events")
        today = datetime.now(UTC)
        # 3 events 7 days ago, 5 events today, 1 event 14 days ago, 0 elsewhere.
        seed = [
            ((today - timedelta(days=7)).isoformat(), 3),
            (today.isoformat(), 5),
            ((today - timedelta(days=14)).isoformat(), 1),
        ]
        for ts, count in seed:
            for _ in range(count):
                c.execute(
                    "INSERT INTO usage_events(key_hash, endpoint, ts, status, metered) "
                    "VALUES (?,?,?,?,?)",
                    ("hash-test", "programs.search", ts, 200, 0),
                )
        c.commit()
    finally:
        c.close()


# ---------------------------------------------------------------------------
# /v1/stats/coverage
# ---------------------------------------------------------------------------


def test_coverage_returns_per_dataset_counts(client, seeded_db: Path):
    r = client.get("/v1/stats/coverage")
    assert r.status_code == 200, r.text
    body = r.json()
    # All required keys present (some may be 0 on the test DB).
    expected = {
        "programs",
        "case_studies",
        "loan_programs",
        "enforcement_cases",
        "exclusion_rules",
        "laws",
        "tax_rulesets",
        "court_decisions",
        "bids",
        "invoice_registrants",
        "generated_at",
    }
    assert expected.issubset(body.keys())
    # The seeded_db fixture is session-scoped and other test modules
    # (search_relevance, short_ascii_perf, prescreen, ...) insert extra
    # rows that aren't cleaned up. Compare to the live count so order
    # of test execution doesn't matter.
    assert body["programs"] == _live_count(seeded_db, "programs")
    assert body["exclusion_rules"] == _live_count(seeded_db, "exclusion_rules")
    assert body["programs"] >= 4  # at minimum the conftest-seeded 4 rows
    assert body["exclusion_rules"] >= 2
    # generated_at is ISO 8601 with Z suffix
    assert body["generated_at"].endswith("Z")


def test_coverage_tolerates_missing_table(client, monkeypatch: pytest.MonkeyPatch):
    """If a table isn't on this volume, the count returns 0 — never 500."""
    from jpintel_mcp.api import stats

    monkeypatch.setattr(
        stats,
        "_COVERAGE_TABLES",
        [
            ("__stats_missing_bids__", key) if key == "bids" else (table, key)
            for table, key in stats._COVERAGE_TABLES
        ],
    )
    stats._reset_stats_cache()

    r = client.get("/v1/stats/coverage")
    assert r.status_code == 200, r.text
    assert r.json()["bids"] == 0


# ---------------------------------------------------------------------------
# /v1/stats/freshness
# ---------------------------------------------------------------------------


def test_freshness_returns_min_max_per_source(client, seeded_db: Path):
    # Add a source_fetched_at to programs so MIN/MAX are non-null.
    # The seeded_db fixture is session-scoped and OTHER tests in the suite
    # (test_meta_freshness, test_search_relevance, etc.) insert programs
    # with source_fetched_at. Wipe ALL stamps first so this test owns the
    # exact two rows that drive MIN/MAX/avg_interval. Otherwise the count,
    # min, max, and avg_interval can drift unpredictably as the suite grows.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("UPDATE programs SET source_fetched_at = NULL")
        c.execute(
            "UPDATE programs SET source_fetched_at = ? WHERE unified_id = ?",
            ("2026-04-20T10:00:00+00:00", "UNI-test-s-1"),
        )
        c.execute(
            "UPDATE programs SET source_fetched_at = ? WHERE unified_id = ?",
            ("2026-04-25T10:00:00+00:00", "UNI-test-a-1"),
        )
        c.commit()
    finally:
        c.close()

    # Bust any cached freshness response from a prior test.
    try:
        from jpintel_mcp.api.stats import _reset_stats_cache

        _reset_stats_cache()
    except Exception:
        pass

    r = client.get("/v1/stats/freshness")
    assert r.status_code == 200, r.text
    body = r.json()
    sources = body["sources"]
    assert "programs" in sources
    prog = sources["programs"]
    assert prog["count"] == 2
    assert prog["min"].startswith("2026-04-20")
    assert prog["max"].startswith("2026-04-25")
    # 5-day span / 1 interval = 5.0 days
    assert prog["avg_interval_days"] == 5.0


def test_freshness_zero_rows_returns_nulls(
    client,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # Point the two freshness entries at empty scratch tables so the
    # zero-row branch is tested without deleting shared seeded rows.
    empty_case_studies = "__stats_empty_case_studies"
    empty_loan_programs = "__stats_empty_loan_programs"
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(f"CREATE TABLE IF NOT EXISTS {empty_case_studies} (fetched_at TEXT)")
        c.execute(f"CREATE TABLE IF NOT EXISTS {empty_loan_programs} (fetched_at TEXT)")
        c.execute(f"DELETE FROM {empty_case_studies}")
        c.execute(f"DELETE FROM {empty_loan_programs}")
        c.commit()
    finally:
        c.close()

    from jpintel_mcp.api import stats

    monkeypatch.setattr(
        stats,
        "_FRESHNESS_SOURCES",
        [
            (empty_case_studies, column, key)
            if key == "case_studies"
            else (empty_loan_programs, column, key)
            if key == "loan_programs"
            else (table, column, key)
            for table, column, key in stats._FRESHNESS_SOURCES
        ],
    )
    stats._reset_stats_cache()

    try:
        r = client.get("/v1/stats/freshness")
        assert r.status_code == 200
        body = r.json()
        cs = body["sources"]["case_studies"]
        assert cs["count"] == 0
        assert cs["min"] is None
        assert cs["max"] is None
        assert cs["avg_interval_days"] is None
    finally:
        c = sqlite3.connect(seeded_db)
        try:
            c.execute(f"DROP TABLE IF EXISTS {empty_case_studies}")
            c.execute(f"DROP TABLE IF EXISTS {empty_loan_programs}")
            c.commit()
        finally:
            c.close()
        stats._reset_stats_cache()


# ---------------------------------------------------------------------------
# /v1/stats/usage
# ---------------------------------------------------------------------------


def test_usage_returns_30_day_window_with_cumulative(client, _seed_usage_events):
    r = client.get("/v1/stats/usage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["window_days"] == 30
    assert len(body["daily"]) == 30
    # Cumulative is monotonically non-decreasing
    last = -1
    for entry in body["daily"]:
        assert entry["cumulative"] >= last
        last = entry["cumulative"]
    # Total = sum of 3 + 5 + 1 = 9 events
    assert body["total"] == 9


def test_usage_zero_events_returns_zero_buckets(client):
    """No usage_events rows → 30 buckets of count=0, total=0."""
    r = client.get("/v1/stats/usage")
    assert r.status_code == 200
    body = r.json()
    assert len(body["daily"]) == 30
    assert all(d["count"] == 0 for d in body["daily"])
    assert body["total"] == 0


# ---------------------------------------------------------------------------
# 5-minute cache
# ---------------------------------------------------------------------------


def test_coverage_is_cached_for_five_minutes(client, seeded_db: Path):
    """Within TTL, coverage should not re-read the DB after a change."""
    r1 = client.get("/v1/stats/coverage")
    initial_programs = r1.json()["programs"]
    # Live count rather than == 4 (other test modules add rows to the
    # session DB before this test runs).
    live = _live_count(seeded_db, "programs")
    assert initial_programs == live
    # Mutate the DB after the cache was warmed. Use a row guaranteed to
    # exist (seeded by conftest) and also restore at the end.
    c = sqlite3.connect(seeded_db)
    try:
        # Snapshot the row before deleting so we can restore it.
        snap = c.execute("SELECT * FROM programs WHERE unified_id = 'UNI-test-s-1'").fetchone()
        assert snap is not None, "seeded UNI-test-s-1 missing from DB"
        col_names = [d[0] for d in c.execute("SELECT * FROM programs LIMIT 0").description]
        c.execute("DELETE FROM programs WHERE unified_id = 'UNI-test-s-1'")
        c.commit()
    finally:
        c.close()
    try:
        # Second call within TTL -> still the original count (cache hit).
        r2 = client.get("/v1/stats/coverage")
        assert r2.json()["programs"] == initial_programs
        # After cache reset, see the live count (initial - 1).
        from jpintel_mcp.api.stats import _reset_stats_cache

        _reset_stats_cache()
        r3 = client.get("/v1/stats/coverage")
        assert r3.json()["programs"] == initial_programs - 1
    finally:
        # Restore the deleted row so other tests sharing the session DB
        # don't observe it missing.
        c = sqlite3.connect(seeded_db)
        try:
            placeholders = ",".join("?" * len(col_names))
            c.execute(
                f"INSERT OR REPLACE INTO programs({','.join(col_names)}) VALUES ({placeholders})",
                tuple(snap),
            )
            c.commit()
        finally:
            c.close()
        from jpintel_mcp.api.stats import _reset_stats_cache

        _reset_stats_cache()


# ---------------------------------------------------------------------------
# Auth posture (no AnonIpLimitDep)
# ---------------------------------------------------------------------------


def test_stats_no_auth_required(client):
    """Stats endpoints are public (transparency posture). No 401."""
    for path in ("/v1/stats/coverage", "/v1/stats/freshness", "/v1/stats/usage"):
        r = client.get(path)
        assert r.status_code == 200, (path, r.text)
