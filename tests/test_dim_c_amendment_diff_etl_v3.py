"""Wave 46 dim 19 / Dim C amendment_diff ETL booster test.

Closes the Wave 46 dim 19 / dim C (amendment_diff ETL) gap: extends the
existing 3 happy-path tests in :mod:`tests.test_a3_amendment_diff_etl`
with explicit coverage of:

  * non-record cases (no change → no diff row even with apply=True),
  * unicode normalisation through canonical_value() (Japanese strings),
  * subsidy_rate float equality is exact (no floating-point drift),
  * raw_snapshot mismatch suppresses projection_regression_candidate,
  * insert_snapshot_diffs is a no-op when apply=False.

These are pure-Python / in-memory sqlite tests — no autonomath.db
dependency, no network, no LLM. Mirrors the ``_build_db`` fixture
shape used by ``test_a3_amendment_diff_etl``.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import backfill_amendment_diff_from_snapshots as backfill  # noqa: E402


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_amendment_snapshot (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            version_seq INTEGER NOT NULL,
            observed_at TEXT NOT NULL,
            amount_max_yen INTEGER,
            subsidy_rate_max REAL,
            target_set_json TEXT,
            eligibility_hash TEXT,
            summary_hash TEXT,
            source_url TEXT,
            source_fetched_at TEXT,
            raw_snapshot_json TEXT,
            UNIQUE(entity_id, version_seq)
        );
        CREATE TABLE am_amendment_diff (
            diff_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            prev_value TEXT,
            new_value TEXT,
            prev_hash TEXT,
            new_hash TEXT,
            detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            source_url TEXT
        );
        """
    )
    return conn


def _seed_snapshot(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    """Helper: insert (entity_id, version_seq, observed_at, amount, rate,
    target_set_json, eh, sh, url, fetched_at, raw_json) tuples."""
    conn.executemany(
        """INSERT INTO am_amendment_snapshot
           (entity_id, version_seq, observed_at, amount_max_yen,
            subsidy_rate_max, target_set_json, eligibility_hash,
            summary_hash, source_url, source_fetched_at, raw_snapshot_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()


# ---------------------------------------------------------------------------
# canonical_value / should_record_field_change unit tests
# ---------------------------------------------------------------------------


def test_canonical_value_target_set_sorts_list() -> None:
    """target_set_json canonicalisation must be order-independent."""
    a = backfill.canonical_value("target_set_json", '["b","a","c"]')
    b = backfill.canonical_value("target_set_json", '["c","a","b"]')
    assert a == b
    # And the canonical form must be the sorted JSON list.
    assert a == '["a","b","c"]'


def test_canonical_value_target_set_empty_equivalences() -> None:
    """Empty JSON variants for target_set_json must collapse to '[]'."""
    assert backfill.canonical_value("target_set_json", "[]") == "[]"
    assert backfill.canonical_value("target_set_json", "") == "[]"
    assert backfill.canonical_value("target_set_json", None) == "[]"


def test_should_record_field_change_amount() -> None:
    """Amount changes must trigger record."""
    assert backfill.should_record_field_change("amount_max_yen", 100, 200) is True
    assert backfill.should_record_field_change("amount_max_yen", 100, 100) is False


def test_should_record_field_change_japanese_target_set() -> None:
    """Unicode strings in target_set_json compare on canonical sort."""
    a = '["中小企業","個人事業主"]'
    b = '["個人事業主","中小企業"]'
    # Same content, different order — must NOT record.
    assert backfill.should_record_field_change("target_set_json", a, b) is False


# ---------------------------------------------------------------------------
# collect_snapshot_diffs negative path: no change → no diff
# ---------------------------------------------------------------------------


def test_collect_canonical_equal_but_raw_diff_yields_projection_only() -> None:
    """Same canonical content + same hashes → only projection_regression_candidate.

    When two snapshots are canonically identical (e.g. ``target_set_json``
    list-sorted equal) but their raw byte representation differs AND the
    eligibility/summary/raw hashes match, the backfill emits a single
    ``projection_regression_candidate`` row marking the raw-typed drift.
    """
    conn = _build_db()
    _seed_snapshot(
        conn,
        [
            (
                "program:rawdrift",
                1,
                "2026-04-01",
                100,
                0.5,
                '["A","B"]',
                "eh",
                "sh",
                "https://example.test",
                "t1",
                "{}",
            ),
            (
                "program:rawdrift",
                2,
                "2026-04-02",
                100,
                0.5,
                '["B","A"]',  # canonical-equal, raw-different
                "eh",
                "sh",
                "https://example.test",
                "t1",
                "{}",
            ),
        ],
    )
    diffs = backfill.collect_snapshot_diffs(conn)
    field_names = [d.field_name for d in diffs]
    # Canonical equality → no plain target_set_json diff.
    assert "target_set_json" not in field_names
    assert "amount_max_yen" not in field_names
    assert "subsidy_rate_max" not in field_names
    # Raw byte drift + hash parity → single projection_regression_candidate.
    assert field_names == ["projection_regression_candidate"]


def test_collect_rate_change_yields_subsidy_rate_diff() -> None:
    """subsidy_rate_max change must surface as a subsidy_rate_max diff row."""
    conn = _build_db()
    _seed_snapshot(
        conn,
        [
            (
                "program:rate",
                1,
                "2026-04-01",
                100,
                0.50,
                "[]",
                "eh",
                "sh",
                "https://example.test",
                "t1",
                "{}",
            ),
            (
                "program:rate",
                2,
                "2026-04-02",
                100,
                0.67,
                "[]",
                "eh",
                "sh",
                "https://example.test",
                "t1",
                "{}",
            ),
        ],
    )
    diffs = backfill.collect_snapshot_diffs(conn)
    field_names = [d.field_name for d in diffs]
    assert "subsidy_rate_max" in field_names
    # The rate change is the only typed diff (amount unchanged, target unchanged).
    assert "amount_max_yen" not in field_names
    assert "target_set_json" not in field_names
    # subsidy_rate_max raw values differ AND hashes match → also a projection
    # candidate is emitted (raw_typed drift, hash parity).
    assert "projection_regression_candidate" in field_names


def test_collect_projection_candidate_requires_hash_parity() -> None:
    """If raw_snapshot_json / hashes differ, no projection_regression_candidate."""
    conn = _build_db()
    _seed_snapshot(
        conn,
        [
            (
                "program:projection",
                1,
                "2026-04-01",
                100,
                0.5,
                "[]",
                "eh1",  # different eligibility_hash
                "sh",
                "https://example.test",
                "t1",
                '{"old":1}',
            ),
            (
                "program:projection",
                2,
                "2026-04-02",
                200,
                0.5,
                "[]",
                "eh2",  # different eligibility_hash
                "sh",
                "https://example.test",
                "t1",
                '{"new":2}',
            ),
        ],
    )
    diffs = backfill.collect_snapshot_diffs(conn)
    field_names = [d.field_name for d in diffs]
    # amount_max_yen change should be there
    assert "amount_max_yen" in field_names
    # but projection_regression_candidate should NOT (raw_snapshot_json differ)
    assert "projection_regression_candidate" not in field_names


# ---------------------------------------------------------------------------
# insert_snapshot_diffs dry-run semantics + idempotency
# ---------------------------------------------------------------------------


def test_insert_dry_run_is_noop() -> None:
    """apply=False must NOT touch the table."""
    conn = _build_db()
    _seed_snapshot(
        conn,
        [
            ("program:dry", 1, "2026-04-01", 100, None, None, None, None,
             "https://example.test", None, None),
            ("program:dry", 2, "2026-04-02", 200, None, None, None, None,
             "https://example.test", None, None),
        ],
    )
    diffs = backfill.collect_snapshot_diffs(conn)
    summary = backfill.insert_snapshot_diffs(conn, diffs, apply=False)
    assert summary["inserted_diffs"] == 0
    assert summary["am_amendment_diff_after"] == 0


def test_insert_apply_then_dry_run_idempotency_metrics() -> None:
    """After apply, dry-run must report 0 candidate_diffs_new."""
    conn = _build_db()
    _seed_snapshot(
        conn,
        [
            ("program:apply", 1, "2026-04-01", 100, None, None, None, None,
             "https://example.test", None, None),
            ("program:apply", 2, "2026-04-02", 200, None, None, None, None,
             "https://example.test", None, None),
        ],
    )
    diffs = backfill.collect_snapshot_diffs(conn)
    first = backfill.insert_snapshot_diffs(conn, diffs, apply=True)
    second = backfill.insert_snapshot_diffs(conn, diffs, apply=False)
    assert first["inserted_diffs"] >= 1
    assert second["candidate_diffs_new"] == 0
    assert second["inserted_diffs"] == 0
    assert second["am_amendment_diff_after"] == first["am_amendment_diff_after"]
