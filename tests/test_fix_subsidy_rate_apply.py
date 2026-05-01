"""Tests for the D5 follow-up: dual-write subsidy_rate + subsidy_rate_text.

Companion to ``tests/test_d5_subsidy_rate_text_fix.py``. The original test
file pre-dates migration 121 and exercises the numeric-only apply path.
This file exercises the dual-write path (where ``subsidy_rate_text`` is
populated alongside the parsed numeric) and the backfill-from-CSV recovery
path used to repair DBs that were cleaned before migration 121 landed.
"""

from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

import pytest  # noqa: I001  -- sys.path injection below requires sentinel import order.

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import fix_subsidy_rate_text_values as fix  # noqa: E402, I001


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _build_db_with_text_column() -> sqlite3.Connection:
    """Build an in-memory programs table including subsidy_rate_text.

    Mirrors the post-migration-121 state of jpintel.db.programs.
    """

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            authority_level TEXT,
            authority_name TEXT,
            prefecture TEXT,
            municipality TEXT,
            source_url TEXT,
            official_url TEXT,
            subsidy_rate REAL,
            subsidy_rate_text TEXT
        );
        """
    )
    return conn


def _build_db_without_text_column() -> sqlite3.Connection:
    """Build an in-memory programs table missing subsidy_rate_text.

    Mirrors the pre-migration-121 state. Used to verify the apply path
    falls back to numeric-only updates and the backfill path raises.
    """

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            authority_level TEXT,
            authority_name TEXT,
            prefecture TEXT,
            municipality TEXT,
            source_url TEXT,
            official_url TEXT,
            subsidy_rate REAL
        );
        """
    )
    return conn


def _target() -> fix.DbTarget:
    return fix.DbTarget("temp", Path("temp.db"), "programs")


# Ten-row fixture mirroring the production D5 footprint.
_TEN_ROW_FIXTURE: tuple[tuple[str, str, str], ...] = (
    ("UNI-130ae87809", "PREF-11-230_埼玉_法人化支援事業費補助金", "定額"),
    ("UNI-3ee089e35d", "MUN-112170-101_鴻巣市_肥料価格高騰対策支援金給付事業", "30%"),
    (
        "UNI-5f4f563b08",
        "PREF-11-280_埼玉_新技術新製品開発支援補助金",
        "2/3 (中堅・中小) / 3/4 (小規模)",
    ),
    ("UNI-60e2d6566d", "PREF-11-270_埼玉_県産農産物販売促進特別対策事業", "10/10"),
    (
        "UNI-6953037edd",
        "PREF-11-290_埼玉_スマート農業導入コスト低減支援事業",
        "2/3",
    ),
    (
        "UNI-8c205b438f",
        "MUN-112170-100_鴻巣市_直売農産物生産拡大体制整備支援補助金",
        "1/2",
    ),
    (
        "UNI-a42ee491ef",
        "PREF-11-260_埼玉_高温対策等園芸産地育成緊急支援事業",
        "1/2",
    ),
    (
        "UNI-b590d97884",
        "MUN-112170-102_鴻巣市_経営継承発展等支援事業_市負担分",
        "定額",
    ),
    (
        "UNI-cefc2ef1f1",
        "PREF-11-310_埼玉_施設園芸セーフティネット構築事業",
        "価格連動(発動基準価格超過分 x 70% or 100%)",
    ),
    (
        "UNI-ddc2e3e689",
        "PREF-11-300_埼玉_スマート農業農業支援サービス事業加速化総合対策事業",
        "1/2 or 定額",
    ),
)


def _seed_ten(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO programs(unified_id, primary_name, subsidy_rate) "
        "VALUES (?, ?, ?)",
        _TEN_ROW_FIXTURE,
    )


# ---------------------------------------------------------------------------
# dual-write apply (post-migration-121)
# ---------------------------------------------------------------------------


def test_apply_dual_writes_numeric_and_text_columns() -> None:
    """Apply on a ten-row fixture writes both columns in lock-step."""

    conn = _build_db_with_text_column()
    _seed_ten(conn)

    fixes = fix.collect_subsidy_rate_fixes(conn, _target())
    assert len(fixes) == 10

    updated = fix.apply_subsidy_rate_fixes(conn, fixes)
    assert updated == 10

    rows = conn.execute(
        "SELECT unified_id, subsidy_rate, subsidy_rate_text, "
        "       typeof(subsidy_rate) AS rate_type "
        "  FROM programs ORDER BY unified_id"
    ).fetchall()
    by_id = {row["unified_id"]: row for row in rows}

    expected = {
        "UNI-130ae87809": (None, "定額", "null"),
        "UNI-3ee089e35d": (0.3, "30%", "real"),
        "UNI-5f4f563b08": (0.75, "2/3 (中堅・中小) / 3/4 (小規模)", "real"),
        "UNI-60e2d6566d": (1.0, "10/10", "real"),
        "UNI-6953037edd": (0.666667, "2/3", "real"),
        "UNI-8c205b438f": (0.5, "1/2", "real"),
        "UNI-a42ee491ef": (0.5, "1/2", "real"),
        "UNI-b590d97884": (None, "定額", "null"),
        "UNI-cefc2ef1f1": (1.0, "価格連動(発動基準価格超過分 x 70% or 100%)", "real"),
        "UNI-ddc2e3e689": (0.5, "1/2 or 定額", "real"),
    }
    for unified_id, (num, text, rate_type) in expected.items():
        row = by_id[unified_id]
        assert row["subsidy_rate"] == num, unified_id
        assert row["subsidy_rate_text"] == text, unified_id
        assert row["rate_type"] == rate_type, unified_id


def test_apply_falls_back_when_text_column_missing() -> None:
    """Without migration 121, apply still cleans subsidy_rate (no error)."""

    conn = _build_db_without_text_column()
    conn.execute(
        "INSERT INTO programs(unified_id, primary_name, subsidy_rate) "
        "VALUES ('UNI-X', 'Pre-121', '2/3')"
    )

    fixes = fix.collect_subsidy_rate_fixes(conn, _target())
    updated = fix.apply_subsidy_rate_fixes(conn, fixes)
    assert updated == 1
    row = conn.execute(
        "SELECT subsidy_rate, typeof(subsidy_rate) AS rate_type "
        "FROM programs WHERE unified_id = 'UNI-X'"
    ).fetchone()
    assert abs(row["subsidy_rate"] - 0.666667) < 1e-6
    assert row["rate_type"] == "real"


def test_apply_refuses_to_exceed_max_updates() -> None:
    """The over-application guard rejects bulk UPDATEs on a regex bug."""

    conn = _build_db_with_text_column()
    _seed_ten(conn)
    fixes = fix.collect_subsidy_rate_fixes(conn, _target())
    assert len(fixes) == 10
    with pytest.raises(RuntimeError, match="exceeds max_updates"):
        fix.apply_subsidy_rate_fixes(conn, fixes, max_updates=5)


def test_apply_round_trip_csv_and_db_match(tmp_path: Path) -> None:
    """Apply produces a CSV whose rows round-trip back to the live DB."""

    conn = _build_db_with_text_column()
    _seed_ten(conn)

    fixes = fix.collect_subsidy_rate_fixes(conn, _target())
    updated = fix.apply_subsidy_rate_fixes(conn, fixes)
    csv_path = tmp_path / "subsidy_rate_apply_2026-05-01.csv"
    fix._write_review_csv(csv_path, fixes)
    assert updated == 10

    with csv_path.open(encoding="utf-8", newline="") as f:
        csv_rows = list(csv.DictReader(f))
    assert len(csv_rows) == 10

    for csv_row in csv_rows:
        live = conn.execute(
            "SELECT subsidy_rate, subsidy_rate_text FROM programs "
            "WHERE unified_id = ?",
            (csv_row["unified_id"],),
        ).fetchone()
        assert live["subsidy_rate_text"] == csv_row["original_subsidy_rate_text"]
        if csv_row["parsed_subsidy_rate"]:
            assert (
                abs(float(live["subsidy_rate"]) - float(csv_row["parsed_subsidy_rate"]))
                < 1e-6
            )
        else:
            assert live["subsidy_rate"] is None


# ---------------------------------------------------------------------------
# backfill-from-CSV recovery path
# ---------------------------------------------------------------------------


def _seed_post_apply_state(conn: sqlite3.Connection) -> None:
    """Pre-load the DB into the state where REAL is clean but text is NULL.

    Mirrors the historical jpintel.db state immediately after the original
    D5 cleanup ran but before migration 121 added subsidy_rate_text.
    """

    rows = (
        ("UNI-130ae87809", "fixed-1", None, None),
        ("UNI-3ee089e35d", "30 percent", 0.3, None),
        ("UNI-5f4f563b08", "2/3 ranged", 0.75, None),
        ("UNI-60e2d6566d", "10/10", 1.0, None),
        ("UNI-6953037edd", "2/3", 0.666667, None),
        ("UNI-8c205b438f", "1/2", 0.5, None),
        ("UNI-a42ee491ef", "1/2", 0.5, None),
        ("UNI-b590d97884", "fixed-2", None, None),
        ("UNI-cefc2ef1f1", "price-linked", 1.0, None),
        ("UNI-ddc2e3e689", "1/2 or fixed", 0.5, None),
    )
    conn.executemany(
        "INSERT INTO programs(unified_id, primary_name, subsidy_rate, "
        "                     subsidy_rate_text) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )


def _write_review_csv_fixture(path: Path) -> None:
    """Synthesize a review CSV equivalent to the one from the original apply."""

    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "db_label": "temp",
            "db_path": "temp.db",
            "table_name": "programs",
            "unified_id": uid,
            "primary_name": name,
            "authority_level": "",
            "authority_name": "",
            "prefecture": "",
            "municipality": "",
            "source_url": "",
            "official_url": "",
            "original_subsidy_rate_text": text,
            "parsed_subsidy_rate": parsed,
            "action": action,
            "parse_reason": reason,
        }
        for uid, name, text, parsed, action, reason in (
            ("UNI-130ae87809", "fixed-1", "定額", "", "set_null_fixed_only", "x"),
            ("UNI-3ee089e35d", "30 percent", "30%", "0.3", "set_numeric_max", "x"),
            (
                "UNI-5f4f563b08",
                "2/3 ranged",
                "2/3 (中堅・中小) / 3/4 (小規模)",
                "0.75",
                "set_numeric_max",
                "x",
            ),
            ("UNI-60e2d6566d", "10/10", "10/10", "1.0", "set_numeric_max", "x"),
            ("UNI-6953037edd", "2/3", "2/3", "0.666667", "set_numeric_max", "x"),
            ("UNI-8c205b438f", "1/2", "1/2", "0.5", "set_numeric_max", "x"),
            ("UNI-a42ee491ef", "1/2", "1/2", "0.5", "set_numeric_max", "x"),
            ("UNI-b590d97884", "fixed-2", "定額", "", "set_null_fixed_only", "x"),
            (
                "UNI-cefc2ef1f1",
                "price-linked",
                "価格連動(発動基準価格超過分 x 70% or 100%)",
                "1.0",
                "set_numeric_max",
                "x",
            ),
            (
                "UNI-ddc2e3e689",
                "1/2 or fixed",
                "1/2 or 定額",
                "0.5",
                "set_numeric_max",
                "x",
            ),
        )
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fix.CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_backfill_dry_run_reports_pending_rows(tmp_path: Path) -> None:
    """Dry-run produces a record per pending row, no DB writes."""

    db_path = tmp_path / "fake.db"
    csv_path = tmp_path / "review.csv"
    _write_review_csv_fixture(csv_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            subsidy_rate REAL,
            subsidy_rate_text TEXT
        );
        """
    )
    _seed_post_apply_state(conn)
    conn.commit()
    conn.close()

    target = fix.DbTarget("temp", db_path, "programs")
    out = tmp_path / "backfill_dry.csv"
    result = fix.backfill_text_from_csv([target], csv_path, out, apply=False)

    assert result["mode"] == "backfill_dry_run"
    assert result["updated_rows"] == 0
    # Sample rows should reflect the 10 pending updates.
    sample_actions = {row["action"] for row in result["sample_rows"]}
    assert sample_actions == {"set_subsidy_rate_text"}


def test_backfill_apply_populates_and_is_idempotent(tmp_path: Path) -> None:
    """Apply once -> 10 updates; apply again -> 0 updates / 10 skips."""

    db_path = tmp_path / "real.db"
    csv_path = tmp_path / "review.csv"
    _write_review_csv_fixture(csv_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            subsidy_rate REAL,
            subsidy_rate_text TEXT
        );
        """
    )
    _seed_post_apply_state(conn)
    conn.commit()
    conn.close()

    target = fix.DbTarget("temp", db_path, "programs")
    out_first = tmp_path / "backfill_first.csv"

    first = fix.backfill_text_from_csv([target], csv_path, out_first, apply=True)
    assert first["mode"] == "backfill_apply"
    assert first["updated_rows"] == 10
    assert first["skipped_rows"] == 0

    out_second = tmp_path / "backfill_second.csv"
    second = fix.backfill_text_from_csv([target], csv_path, out_second, apply=True)
    assert second["updated_rows"] == 0
    assert second["skipped_rows"] == 10

    # CSV from the first run should record before/after deltas.
    with out_first.open(encoding="utf-8", newline="") as f:
        backfill_rows = list(csv.DictReader(f))
    assert len(backfill_rows) == 10
    assert all(row["action"] == "set_subsidy_rate_text" for row in backfill_rows)
    assert all(row["before_subsidy_rate_text"] == "" for row in backfill_rows)
    assert {row["after_subsidy_rate_text"] for row in backfill_rows} == {
        "定額",
        "30%",
        "2/3 (中堅・中小) / 3/4 (小規模)",
        "10/10",
        "2/3",
        "1/2",
        "価格連動(発動基準価格超過分 x 70% or 100%)",
        "1/2 or 定額",
    }

    # DB should now carry the original display text alongside the numeric.
    inspect = sqlite3.connect(str(db_path))
    inspect.row_factory = sqlite3.Row
    rows = inspect.execute(
        "SELECT unified_id, subsidy_rate, subsidy_rate_text "
        "  FROM programs ORDER BY unified_id"
    ).fetchall()
    by_id = {row["unified_id"]: row for row in rows}
    assert by_id["UNI-130ae87809"]["subsidy_rate_text"] == "定額"
    assert by_id["UNI-3ee089e35d"]["subsidy_rate_text"] == "30%"
    assert by_id["UNI-cefc2ef1f1"]["subsidy_rate_text"] == (
        "価格連動(発動基準価格超過分 x 70% or 100%)"
    )
    inspect.close()


def test_backfill_skips_drifted_rows(tmp_path: Path) -> None:
    """Rows whose live numeric drifted post-cleanup are skipped, not corrupted."""

    db_path = tmp_path / "drift.db"
    csv_path = tmp_path / "review.csv"
    _write_review_csv_fixture(csv_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            subsidy_rate REAL,
            subsidy_rate_text TEXT
        );
        """
    )
    _seed_post_apply_state(conn)
    # Drift: simulate a subsequent re-import that changed UNI-3ee089e35d.
    conn.execute(
        "UPDATE programs SET subsidy_rate = 0.42 WHERE unified_id = 'UNI-3ee089e35d'"
    )
    conn.commit()
    conn.close()

    target = fix.DbTarget("temp", db_path, "programs")
    out = tmp_path / "backfill_drift.csv"
    result = fix.backfill_text_from_csv([target], csv_path, out, apply=True)

    # 9 safe rows updated, 1 drifted row skipped.
    assert result["updated_rows"] == 9
    assert result["skipped_rows"] == 1

    inspect = sqlite3.connect(str(db_path))
    inspect.row_factory = sqlite3.Row
    drifted = inspect.execute(
        "SELECT subsidy_rate, subsidy_rate_text FROM programs "
        "WHERE unified_id = 'UNI-3ee089e35d'"
    ).fetchone()
    inspect.close()
    # Drifted row must NOT have been overwritten.
    assert drifted["subsidy_rate"] == 0.42
    assert drifted["subsidy_rate_text"] is None


def test_backfill_refuses_when_csv_exceeds_max_updates(tmp_path: Path) -> None:
    """An oversized CSV (e.g. 25 rows) is rejected before any DB write."""

    db_path = tmp_path / "huge.db"
    csv_path = tmp_path / "huge_review.csv"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            subsidy_rate REAL,
            subsidy_rate_text TEXT
        );
        """
    )
    conn.commit()
    conn.close()

    rows = [
        {
            "db_label": "temp",
            "db_path": "temp.db",
            "table_name": "programs",
            "unified_id": f"UNI-bulk-{i:03d}",
            "primary_name": f"row {i}",
            "authority_level": "",
            "authority_name": "",
            "prefecture": "",
            "municipality": "",
            "source_url": "",
            "official_url": "",
            "original_subsidy_rate_text": "1/2",
            "parsed_subsidy_rate": "0.5",
            "action": "set_numeric_max",
            "parse_reason": "x",
        }
        for i in range(25)
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fix.CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    target = fix.DbTarget("temp", db_path, "programs")
    out = tmp_path / "backfill_huge.csv"
    with pytest.raises(RuntimeError, match="exceeds max_updates"):
        fix.backfill_text_from_csv([target], csv_path, out, apply=True)


# ---------------------------------------------------------------------------
# audit summary
# ---------------------------------------------------------------------------


def test_audit_reports_zero_when_clean(tmp_path: Path) -> None:
    """Audit on a clean DB returns zero text rows + column-present True."""

    db_path = tmp_path / "clean.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            subsidy_rate REAL,
            subsidy_rate_text TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO programs(unified_id, primary_name, subsidy_rate) "
        "VALUES ('UNI-clean', 'real-only', 0.5)"
    )
    conn.commit()
    conn.close()

    target = fix.DbTarget("temp", db_path, "programs")
    result = fix.audit_subsidy_rate_text([target])
    assert result["mode"] == "audit"
    assert result["text_rows"] == {"temp": 0}
    assert result["subsidy_rate_text_column_present"] == {"temp": True}


def test_audit_reports_contamination_count(tmp_path: Path) -> None:
    """Audit on a contaminated DB returns the precise count."""

    db_path = tmp_path / "dirty.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            authority_level TEXT,
            authority_name TEXT,
            prefecture TEXT,
            municipality TEXT,
            source_url TEXT,
            official_url TEXT,
            subsidy_rate REAL
        );
        """
    )
    _seed_ten(conn)
    conn.commit()
    conn.close()

    target = fix.DbTarget("temp", db_path, "programs")
    result = fix.audit_subsidy_rate_text([target])
    assert result["text_rows"] == {"temp": 10}
    assert result["subsidy_rate_text_column_present"] == {"temp": False}
