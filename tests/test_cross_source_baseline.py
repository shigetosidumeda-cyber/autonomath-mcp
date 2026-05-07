"""Tests for the baseline-gating mode in `scripts/cron/cross_source_check.py`.

The Trust 8-pack agent flagged a P0 risk: the very first wet run of
the cross_source_check cron after migration 101 went live would emit
~4.88M `correction_log` rows. Every fact whose stored
`confirming_source_count` was the column DEFAULT (1) and whose live
distinct-source count came in at 0 / 1 would look like a regression
(`prev > live`) — but none of those are real regressions, just the
initial-population shape of the new column.

Migration 107 adds `cross_source_baseline_state` (single-row state
table). The cron consults it on every run; on `baseline_completed = 0`
it suppresses ALL correction_log writes for that pass and flips the
flag at the end. Subsequent runs use normal regression detection.

These tests pin three contracts:

  1. First wet pass on a fresh DB (mock 1000-row shape): refreshes
     `confirming_source_count` but writes ZERO `correction_log` rows
     and marks `cross_source_baseline_state.baseline_completed = 1`
     with a non-NULL `baseline_run_at`.

  2. Second pass with one real regression (prev=2, live=1): writes
     exactly one `correction_log` row tagged `cross_source_conflict`.

  3. Manual `--baseline` flag is honoured regardless of state — i.e.
     even when `baseline_completed` is already 1, the run still
     suppresses correction_log writes (operator re-baseline path).

The 1000-row default is the test-friendly stand-in for the prod
4.88M shape — proves the suppression is row-count-independent.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER_PATH = REPO_ROOT / "scripts" / "cron" / "cross_source_check.py"
MIGRATION_101 = REPO_ROOT / "scripts" / "migrations" / "101_trust_infrastructure.sql"
MIGRATION_107 = REPO_ROOT / "scripts" / "migrations" / "107_cross_source_baseline_state.sql"


def _load_driver():
    spec = importlib.util.spec_from_file_location(
        "cross_source_check",
        DRIVER_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_minimal_schema(conn: sqlite3.Connection) -> None:
    """Create the minimal slice of mig 101 + 107 the cron touches.

    We do not run the full SQL migrations because the seeded fixture
    runs against jpintel.db's schema; instead we recreate just the
    tables + columns + state row the cross_source_check cron reads
    and writes.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS am_entity_facts (
            fact_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id   TEXT,
            field_name  TEXT,
            value       TEXT,
            source_id   TEXT,
            confirming_source_count INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS correction_log (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_at         TEXT NOT NULL,
            dataset             TEXT NOT NULL,
            entity_id           TEXT NOT NULL,
            field_name          TEXT,
            prev_value_hash     TEXT,
            new_value_hash      TEXT,
            root_cause          TEXT NOT NULL,
            source_url          TEXT,
            reproducer_sql      TEXT,
            correction_post_url TEXT,
            rss_appended_at     TEXT
        );

        CREATE TABLE IF NOT EXISTS cross_source_baseline_state (
            id                  INTEGER PRIMARY KEY CHECK (id = 1),
            baseline_run_at     TIMESTAMP,
            baseline_completed  BOOLEAN DEFAULT 0
        );
        INSERT OR IGNORE INTO cross_source_baseline_state (id, baseline_completed)
        VALUES (1, 0);
        """
    )


def _seed_4_88m_shape(conn: sqlite3.Connection, *, n_rows: int = 1000) -> None:
    """Seed the 4.88M-shape false-positive scenario at test scale.

    Every fact has prev=1 (column DEFAULT) but live=0 (no distinct
    source — we use NULL source_id rows to drive distinct count to 0)
    or live=1 (single source). Either way `prev > live` would be true
    on a fraction of rows under the OLD cron logic, generating
    4.88M-shape correction_log writes.

    We mix two row patterns so the cron sees both `live=0` (2/3) and
    `live=1` (1/3). Both shapes are false positives during the first
    pass and MUST be suppressed in baseline mode.
    """
    rows = []
    for i in range(n_rows):
        if i % 3 == 0:
            # live=1: one distinct non-NULL source.
            rows.append((f"E-{i}", "amount_max_yen", "100", f"S-{i}"))
        else:
            # live=0: only NULL source_ids → COUNT(DISTINCT source_id) = 0.
            # This is the worst-case false-positive from a recent migration
            # that left the `confirming_source_count` DEFAULT (1) but did
            # not backfill source_id.
            rows.append((f"E-{i}", "amount_max_yen", "100", None))
    conn.executemany(
        "INSERT INTO am_entity_facts (entity_id, field_name, value, source_id) VALUES (?,?,?,?)",
        rows,
    )
    conn.commit()


def _seed_one_real_regression(conn: sqlite3.Connection) -> None:
    """Seed exactly one entity whose live count truly fell below prev.

    The fact has `confirming_source_count = 2` already stored (a prior
    run saw 2 distinct sources) but only ONE distinct source remains
    in the live data. This is a genuine `cross_source_conflict` —
    one source disappeared.
    """
    conn.execute(
        "INSERT INTO am_entity_facts "
        "(entity_id, field_name, value, source_id, confirming_source_count) "
        "VALUES (?,?,?,?,?)",
        ("E-regression", "amount_max_yen", "500", "S-survivor", 2),
    )
    conn.commit()


@pytest.fixture()
def fresh_db(tmp_path: Path) -> Path:
    db = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db)
    _seed_minimal_schema(conn)
    conn.close()
    return db


def test_first_wet_pass_emits_zero_correction_logs_and_flips_flag(
    fresh_db: Path,
) -> None:
    """First wet pass on the 4.88M-shape mock (n=1000) → 0 correction_log rows.

    This is the central P0 guard. Without baseline gating, this test
    would assert correction_log row count > 0. With baseline gating,
    it MUST be exactly 0 even though the cron also detected and
    counted the false-positive regressions.
    """
    conn = sqlite3.connect(fresh_db)
    _seed_4_88m_shape(conn, n_rows=1000)
    conn.close()

    drv = _load_driver()
    out = drv._run(fresh_db)

    # Sanity: cron actually iterated over the seeded rows.
    assert out["checked"] == 1000, out

    # Auto-baseline kicked in (state was baseline_completed=0).
    assert out["baseline_mode"] == 1, out
    assert out["baseline_marked_complete"] == 1, out

    # Live counts updated even in baseline mode (column DEFAULT=1, live=0/1).
    # Approximately 2/3 of rows had live=0, 1/3 had live=1; updates fire on
    # any (prev != live) — so the live=0 cohort updates and the live=1 cohort
    # does NOT (already matches DEFAULT 1).
    assert out["updated"] >= 600, out  # ~667 expected; loose lower bound.

    # The cron observed regressions (live=0 < prev=1) but suppressed them.
    assert out["regressions"] >= 600, out
    assert out["logged"] == 0, out

    # No correction_log rows landed.
    conn = sqlite3.connect(fresh_db)
    cnt = conn.execute("SELECT COUNT(*) FROM correction_log").fetchone()[0]
    assert cnt == 0, f"baseline mode must suppress all correction_log writes; got {cnt}"

    # State flipped to completed.
    row = conn.execute(
        "SELECT baseline_completed, baseline_run_at FROM cross_source_baseline_state WHERE id = 1"
    ).fetchone()
    assert row is not None
    assert int(row[0]) == 1, "baseline_completed must be 1 after first run"
    assert row[1] is not None, "baseline_run_at must be a non-NULL timestamp"
    conn.close()


def test_second_pass_with_real_regression_emits_one_correction_log(
    fresh_db: Path,
) -> None:
    """Second pass (post-baseline) with one real prev=2 → live=1 regression.

    After the baseline pass marks the flag complete, the next run
    behaves normally: regressions write `correction_log` rows with
    `root_cause = 'cross_source_conflict'`.
    """
    drv = _load_driver()

    # Step 1: run once on an EMPTY am_entity_facts to flip the baseline
    # flag with no data — this isolates the test from the baseline-pass
    # row-count behaviour and lets us focus on the regression path.
    out_baseline = drv._run(fresh_db)
    assert out_baseline["baseline_mode"] == 1
    assert out_baseline["baseline_marked_complete"] == 1
    assert out_baseline["logged"] == 0

    # Step 2: seed exactly one real regression (prev=2, live=1).
    conn = sqlite3.connect(fresh_db)
    _seed_one_real_regression(conn)
    conn.close()

    # Step 3: run again. Baseline flag is now 1 → normal regression
    # detection → exactly one correction_log row.
    out = drv._run(fresh_db)
    assert (
        out["baseline_mode"] == 0
    ), "second run must NOT be in baseline mode; state already complete"
    assert out["regressions"] == 1, out
    assert out["logged"] == 1, out

    conn = sqlite3.connect(fresh_db)
    rows = conn.execute(
        "SELECT entity_id, field_name, prev_value_hash, new_value_hash, "
        "       root_cause, dataset "
        "FROM correction_log"
    ).fetchall()
    assert len(rows) == 1, f"expected exactly 1 correction_log row, got {len(rows)}"
    eid, field, prev_h, new_h, cause, dataset = rows[0]
    assert eid == "E-regression"
    assert field == "amount_max_yen"
    assert prev_h == "sources:2"
    assert new_h == "sources:1"
    assert cause == "cross_source_conflict"
    assert dataset == "am_entity_facts"
    conn.close()


def test_manual_baseline_flag_works_regardless_of_state(fresh_db: Path) -> None:
    """`--baseline` (i.e. _run(..., baseline=True)) suppresses correction_log
    writes EVEN when `cross_source_baseline_state.baseline_completed` is 1.

    This is the operator re-baseline path: after a known data migration
    that legitimately changes source counts en masse, the operator
    re-runs with `--baseline` to absorb the shift without spamming RSS.
    """
    drv = _load_driver()

    # Pre-flip the state so the cron would NORMALLY run in non-baseline
    # mode. Without the explicit flag, a real regression would emit a
    # correction_log row.
    conn = sqlite3.connect(fresh_db)
    conn.execute(
        "UPDATE cross_source_baseline_state SET baseline_completed = 1, "
        "baseline_run_at = '2026-04-29T00:00:00+00:00' WHERE id = 1"
    )
    conn.commit()
    _seed_one_real_regression(conn)
    conn.close()

    # Confirm: WITHOUT the flag, this run WOULD emit one correction_log.
    # We check this by running with baseline=True and verifying ZERO rows.
    out = drv._run(fresh_db, baseline=True)
    assert out["baseline_mode"] == 1, out
    assert out["regressions"] == 1, "regression was detected and counted"
    assert out["logged"] == 0, "but `--baseline` suppressed the correction_log write"

    conn = sqlite3.connect(fresh_db)
    cnt = conn.execute("SELECT COUNT(*) FROM correction_log").fetchone()[0]
    assert cnt == 0, f"manual --baseline must suppress writes; got {cnt}"
    conn.close()


# --- additional defence-in-depth tests --------------------------------------


def test_migration_107_first_line_marks_target_db_autonomath() -> None:
    """entrypoint.sh §4 only auto-applies migrations whose FIRST LINE is
    `-- target_db: autonomath`. If migration 107 ever loses that marker
    (e.g. somebody re-flows the comment block), entrypoint.sh would
    silently skip it and the cron would emit the 4.88M false-positives
    again — silently and at production scale."""
    assert MIGRATION_107.is_file(), "migration 107 missing"
    first_line = MIGRATION_107.read_text(encoding="utf-8").splitlines()[0]
    assert (
        first_line.strip() == "-- target_db: autonomath"
    ), f"migration 107 first line must be '-- target_db: autonomath', got: {first_line!r}"


def test_migration_107_is_idempotent_via_create_if_not_exists() -> None:
    """Re-applying mig 107 on every Fly boot must be safe."""
    sql = MIGRATION_107.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS cross_source_baseline_state" in sql
    assert "INSERT OR IGNORE INTO cross_source_baseline_state" in sql
