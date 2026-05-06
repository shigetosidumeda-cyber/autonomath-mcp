"""Tests for the weekly alias expansion cron + operator review CLI.

Covers:
    * `scripts.cron.alias_dict_expansion.run` proposes candidates from a
      tiny seeded `empty_search_log` and inserts them into
      `alias_candidates_queue` (mig 112).
    * Re-running the cron is idempotent (bumps existing rows, never
      double-inserts).
    * Approved / rejected rows are sticky across cron runs.
    * `jpintel_mcp.loops.alias_review` approves a row -> writes into
      `am_alias` and updates the queue.
    * Reject does NOT write to am_alias.
    * Re-approve is a noop (no double am_alias INSERT).
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# Load the cron script as a module — it's not a package member.
_REPO = Path(__file__).resolve().parent.parent
_CRON_PATH = _REPO / "scripts" / "cron" / "alias_dict_expansion.py"
_spec = importlib.util.spec_from_file_location(
    "alias_dict_expansion",
    _CRON_PATH,
)
assert _spec is not None and _spec.loader is not None
_cron = importlib.util.module_from_spec(_spec)
sys.modules["alias_dict_expansion"] = _cron
_spec.loader.exec_module(_cron)

from jpintel_mcp.loops import alias_review  # noqa: E402


def _seed_jpintel(db_path: Path, queries: list[tuple[str, int, str]]) -> None:
    """Seed a minimal jpintel.db with empty_search_log + programs + queue.

    `queries` is [(query, count, created_at_iso), ...] — count rows are
    inserted (one row per count) so the cron's GROUP BY ... HAVING clause
    sees the right count.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE empty_search_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                filters_json TEXT,
                ip_hash TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE programs (
                unified_id TEXT PRIMARY KEY,
                primary_name TEXT NOT NULL,
                excluded INTEGER DEFAULT 0,
                tier TEXT NOT NULL DEFAULT 'B'
            );
            CREATE TABLE alias_candidates_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_alias TEXT NOT NULL,
                canonical_term TEXT NOT NULL,
                match_score REAL NOT NULL,
                empty_query_count INTEGER NOT NULL,
                first_seen TIMESTAMP NOT NULL,
                last_seen TIMESTAMP NOT NULL,
                status TEXT DEFAULT 'pending'
                  CHECK(status IN ('pending','approved','rejected')),
                reviewed_at TIMESTAMP,
                reviewer TEXT,
                UNIQUE(candidate_alias, canonical_term)
            );
            """
        )
        for q, count, ts in queries:
            for _ in range(count):
                conn.execute(
                    "INSERT INTO empty_search_log("
                    "  query, endpoint, created_at"
                    ") VALUES (?, 'search_programs', ?)",
                    (q, ts),
                )
        conn.execute(
            "INSERT INTO programs(unified_id, primary_name, excluded, tier) "
            "VALUES ('program:base:abc', 'ものづくり補助金', 0, 'B')"
        )
        conn.commit()
    finally:
        conn.close()


def _seed_autonomath(db_path: Path) -> None:
    """Seed a minimal autonomath.db with am_alias + sample row."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE am_alias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_table TEXT NOT NULL,
                canonical_id TEXT NOT NULL,
                alias TEXT NOT NULL,
                alias_kind TEXT NOT NULL DEFAULT 'partial',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                language TEXT NOT NULL DEFAULT 'ja'
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def seeded_dbs(tmp_path: Path) -> tuple[Path, Path]:
    """Fresh jpintel.db + autonomath.db with the substrate the cron needs."""
    j = tmp_path / "jpintel.db"
    a = tmp_path / "autonomath.db"
    now = datetime.now(UTC)
    yesterday = (now - timedelta(days=1)).isoformat()
    queries = [
        # Strong signal: kanji + kana noise -> JSIC 'A' (農業) via substring.
        ("農業 のうぎょう", 5, yesterday),
        # Strong signal: '製造業' surface inside '"DX" 製造業'.
        ('"DX" 製造業', 3, yesterday),
        # Single-shot noise — falls below MIN_EMPTY_COUNT (2).
        ("**", 1, yesterday),
    ]
    _seed_jpintel(j, queries)
    _seed_autonomath(a)
    return j, a


def test_cron_proposes_candidates_from_empty_log(seeded_dbs):
    j, a = seeded_dbs
    out = _cron.run(
        dry_run=False,
        days=7,
        min_count=2,
        jpintel_db=j,
        autonomath_db=a,
    )
    assert out["scanned_queries"] == 2  # '**' filtered out by min_count.
    assert out["candidates_proposed"] >= 2
    assert out["candidates_inserted"] >= 2
    assert out["candidates_bumped"] == 0
    # Confirm rows landed in queue.
    conn = sqlite3.connect(j)
    try:
        rows = conn.execute(
            "SELECT candidate_alias, canonical_term, status, "
            "       empty_query_count "
            "  FROM alias_candidates_queue ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    pairs = {(r[0], r[1]) for r in rows}
    assert ("農業 のうぎょう", "A") in pairs
    assert ('"DX" 製造業', "E") in pairs
    assert all(r[2] == "pending" for r in rows)
    # First-seen / last-seen counts must equal the seeded count.
    counts = {r[0]: r[3] for r in rows}
    assert counts["農業 のうぎょう"] == 5
    assert counts['"DX" 製造業'] == 3


def test_cron_is_idempotent(seeded_dbs):
    j, a = seeded_dbs
    _cron.run(dry_run=False, days=7, min_count=2, jpintel_db=j, autonomath_db=a)
    out2 = _cron.run(dry_run=False, days=7, min_count=2, jpintel_db=j, autonomath_db=a)
    assert out2["candidates_inserted"] == 0
    assert out2["candidates_bumped"] >= 2
    # Row count must not double.
    conn = sqlite3.connect(j)
    try:
        n = conn.execute("SELECT count(*) FROM alias_candidates_queue").fetchone()[0]
    finally:
        conn.close()
    assert n == out2["candidates_proposed"]


def test_cron_dry_run_does_not_write(seeded_dbs):
    j, a = seeded_dbs
    out = _cron.run(dry_run=True, days=7, min_count=2, jpintel_db=j, autonomath_db=a)
    assert out["candidates_proposed"] >= 2
    assert out["candidates_inserted"] == 0
    conn = sqlite3.connect(j)
    try:
        n = conn.execute("SELECT count(*) FROM alias_candidates_queue").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_review_list_returns_pending(seeded_dbs):
    j, a = seeded_dbs
    _cron.run(dry_run=False, days=7, min_count=2, jpintel_db=j, autonomath_db=a)
    rows = alias_review.list_pending(jpintel_db=j, limit=10)
    assert len(rows) >= 2
    assert all(r["status"] == "pending" for r in rows)


def test_review_approve_writes_am_alias_and_flips_queue(seeded_dbs):
    j, a = seeded_dbs
    _cron.run(dry_run=False, days=7, min_count=2, jpintel_db=j, autonomath_db=a)
    rows = alias_review.list_pending(jpintel_db=j, limit=10)
    target = next(r for r in rows if r["candidate_alias"] == "農業 のうぎょう")
    out = alias_review.approve(
        target["id"],
        reviewer="test",
        jpintel_db=j,
        autonomath_db=a,
    )
    assert out["op"] == "approved"
    assert out["entity_table"] == "am_industry_jsic"
    # am_alias must carry the new row.
    conn = sqlite3.connect(a)
    try:
        am_rows = conn.execute(
            "SELECT entity_table, canonical_id, alias, alias_kind   FROM am_alias"
        ).fetchall()
    finally:
        conn.close()
    assert ("am_industry_jsic", "A", "農業 のうぎょう", "partial") in am_rows
    # Queue row must be approved.
    conn = sqlite3.connect(j)
    try:
        status = conn.execute(
            "SELECT status, reviewer FROM alias_candidates_queue WHERE id=?",
            (target["id"],),
        ).fetchone()
    finally:
        conn.close()
    assert status[0] == "approved"
    assert status[1] == "test"


def test_review_approve_is_noop_on_already_approved(seeded_dbs):
    j, a = seeded_dbs
    _cron.run(dry_run=False, days=7, min_count=2, jpintel_db=j, autonomath_db=a)
    rows = alias_review.list_pending(jpintel_db=j, limit=10)
    target_id = rows[0]["id"]
    alias_review.approve(target_id, jpintel_db=j, autonomath_db=a)
    out2 = alias_review.approve(target_id, jpintel_db=j, autonomath_db=a)
    assert out2["op"] == "noop"
    # am_alias row count should not have doubled.
    conn = sqlite3.connect(a)
    try:
        n = conn.execute("SELECT count(*) FROM am_alias").fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_review_reject_does_not_touch_am_alias(seeded_dbs):
    j, a = seeded_dbs
    _cron.run(dry_run=False, days=7, min_count=2, jpintel_db=j, autonomath_db=a)
    rows = alias_review.list_pending(jpintel_db=j, limit=10)
    target_id = rows[0]["id"]
    out = alias_review.reject(target_id, reviewer="test", jpintel_db=j)
    assert out["op"] == "rejected"
    conn = sqlite3.connect(a)
    try:
        n = conn.execute("SELECT count(*) FROM am_alias").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_review_handles_missing_id(seeded_dbs):
    j, a = seeded_dbs
    out = alias_review.approve(99999, jpintel_db=j, autonomath_db=a)
    assert out["op"] == "not_found"
    out2 = alias_review.reject(99999, jpintel_db=j)
    assert out2["op"] == "not_found"


def test_cron_skips_already_known_aliases(tmp_path: Path):
    """A miss query whose (canonical, alias) is already in am_alias must
    not produce a queue row (operator review cost is the constraint)."""
    j = tmp_path / "jpintel.db"
    a = tmp_path / "autonomath.db"
    yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    _seed_jpintel(j, [("農業 のうぎょう", 5, yesterday)])
    _seed_autonomath(a)
    # Pre-populate am_alias with the EXACT pair the cron would propose.
    conn = sqlite3.connect(a)
    try:
        conn.execute(
            "INSERT INTO am_alias(entity_table, canonical_id, alias, "
            "                     alias_kind, language) "
            "VALUES ('am_industry_jsic', 'A', '農業 のうぎょう', 'partial', 'ja')"
        )
        conn.commit()
    finally:
        conn.close()
    out = _cron.run(dry_run=False, days=7, min_count=2, jpintel_db=j, autonomath_db=a)
    # The proposal targeting JSIC 'A' should be filtered.
    conn = sqlite3.connect(j)
    try:
        rows = conn.execute("SELECT canonical_term FROM alias_candidates_queue").fetchall()
    finally:
        conn.close()
    canonicals = {r[0] for r in rows}
    assert "A" not in canonicals
    assert out["candidates_proposed"] == 0


def test_normalize_query_pykakasi():
    """pykakasi is a hard dep — confirm hira / romaji forms emerge."""
    forms = _cron.normalize_query("製造業")
    assert forms["orig"] == "製造業"
    # pykakasi present in this env (per pyproject.toml).
    assert forms["hira"] == "せいぞうぎょう"
    assert "seizou" in forms["romaji"]
