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
        c.execute("DELETE FROM usage_events")
        c.commit()
    finally:
        c.close()
    yield
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
        "laws_jpintel",
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


def test_coverage_tolerates_missing_table(client, seeded_db: Path):
    """If a table isn't on this volume, the count returns 0 — never 500."""
    c = sqlite3.connect(seeded_db)
    try:
        # Drop one of the optional expansion tables to force the fallback path.
        c.execute("DROP TABLE IF EXISTS bids")
        c.commit()
    finally:
        c.close()
    # Bust the cache so the second call recomputes.
    from jpintel_mcp.api.stats import _reset_stats_cache

    _reset_stats_cache()
    try:
        r = client.get("/v1/stats/coverage")
        assert r.status_code == 200, r.text
        assert r.json()["bids"] == 0
    finally:
        # Recreate a minimal bids table so other tests still see it (the real
        # schema migration recreates it idempotently in prod, but tests share
        # one DB so we must restore it here).
        c = sqlite3.connect(seeded_db)
        try:
            c.execute(
                "CREATE TABLE IF NOT EXISTS bids ("
                "unified_id TEXT PRIMARY KEY, fetched_at TEXT, updated_at TEXT)"
            )
            c.commit()
        finally:
            c.close()
        _reset_stats_cache()


# ---------------------------------------------------------------------------
# /v1/stats/freshness
# ---------------------------------------------------------------------------


def test_freshness_returns_min_max_per_source(client, seeded_db: Path):
    # Add a source_fetched_at to programs so MIN/MAX are non-null.
    c = sqlite3.connect(seeded_db)
    try:
        # Neutralize stamps from prior session-scoped tests (test_meta_freshness leaks UNI-test-b-1).
        c.execute("UPDATE programs SET source_fetched_at = NULL WHERE unified_id LIKE 'UNI-test-%'")
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


def test_freshness_zero_rows_returns_nulls(client):
    r = client.get("/v1/stats/freshness")
    assert r.status_code == 200
    body = r.json()
    # case_studies / loan_programs have 0 rows on the test DB.
    cs = body["sources"]["case_studies"]
    assert cs["count"] == 0
    assert cs["min"] is None
    assert cs["max"] is None
    assert cs["avg_interval_days"] is None


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
        snap = c.execute(
            "SELECT * FROM programs WHERE unified_id = 'UNI-test-s-1'"
        ).fetchone()
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
