"""Tests for the adoption -> program canonical join cron + migration 114.

Covers:
    * Backfill produces the expected exact / fuzzy_high / fuzzy_med / unmatched
      bucket counts on a hand-crafted 20-row corpus (5 programs, 8 exact, 4
      high-fuzzy, 3 med-fuzzy, 5 unmatched).
    * Idempotency: a 2nd run leaves `program_id` unchanged.
    * `top_unmatched_program_names` reports the 5 unmatched names in
      count order.
    * Tie-break: when the same name resolves to 2 programs (S vs B), the
      S-tier program wins.
    * Migration 114 is idempotent (re-applying via raw SQL is a no-op).
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

# Load the cron script as a module — it's not a package member.
_REPO = Path(__file__).resolve().parent.parent
_CRON_PATH = _REPO / "scripts" / "cron" / "adoption_program_join.py"
_spec = importlib.util.spec_from_file_location(
    "adoption_program_join",
    _CRON_PATH,
)
assert _spec is not None and _spec.loader is not None
_cron = importlib.util.module_from_spec(_spec)
sys.modules["adoption_program_join"] = _cron
_spec.loader.exec_module(_cron)


_MIG_114 = _REPO / "scripts" / "migrations" / "114_adoption_program_join.sql"


# ---------------------------------------------------------------------------
# Test fixture: 5-program × 20-adoption-row corpus.
#
# Programs (jpintel.db):
#   prog-1  IT導入補助金 (national, tier=B, amount_max=450万円)
#                   aliases: ["IT補助金", "デジタル化補助金"]
#   prog-2  事業再構築補助金 (national, tier=A, amount_max=8000万円)
#   prog-3  ものづくり補助金 (national, tier=S, amount_max=1250万円)
#   prog-4  ものづくり補助金 (東京都, tier=B, amount_max=200万円)
#                   — same name as prog-3 to exercise the S>B tie-break.
#   prog-5  小規模事業者持続化補助金 (national, tier=B, amount_max=200万円)
#
# 20 adoption rows split by expected match method (per the calibrated
# ratios documented above _ADOPTIONS):
#   Exact (8):     3 hit primary_name, 5 hit aliases.
#   Fuzzy_high (4): single-char drift, ratio in [0.92, 1.0).
#   Fuzzy_med (3):  multi-char drift, ratio in [0.80, 0.92).
#   Unmatched (5):  ratio < 0.80 against any program.
#
# Counts asserted by tests: scanned=20, exact=8, high=4, med=3, unmatched=5.
# Top unmatched entry must be "全く関係ない補助金A" (count 2).
# ---------------------------------------------------------------------------


_PROGRAMS = [
    (
        "prog-1",
        "IT導入補助金",
        json.dumps(["IT補助金", "デジタル化補助金"], ensure_ascii=False),
        None,
        "B",
        450.0,
    ),
    ("prog-2", "事業再構築補助金", json.dumps([], ensure_ascii=False), None, "A", 8000.0),
    ("prog-3", "ものづくり補助金", json.dumps([], ensure_ascii=False), None, "S", 1250.0),
    # Same primary_name, different prefecture + tier — exercises the S>B
    # tie-break in `_pick_best`.
    ("prog-4", "ものづくり補助金", json.dumps([], ensure_ascii=False), "東京都", "B", 200.0),
    ("prog-5", "小規模事業者持続化補助金", json.dumps([], ensure_ascii=False), None, "B", 200.0),
]


# Empirical SequenceMatcher.ratio() on NFKC+lower+strip-whitespace forms
# of these inputs (verified against difflib at calibration time):
#   "IT導入補助金1"          vs "IT導入補助金"          -> 0.9333  (high)
#   "事業再構築補助金A"        vs "事業再構築補助金"        -> 0.9412  (high)
#   "ものづくり補助金A"        vs "ものづくり補助金"        -> 0.9412  (high)
#   "小規模事業者持続化補助金1"  vs "小規模事業者持続化補助金"  -> 0.9600  (high)
#   "IT導入補助金 後期"       vs "IT導入補助金"          -> 0.8750  (med)
#   "IT導入補助金 前期"       vs "IT導入補助金"          -> 0.8750  (med)
#   "ものづくり補助金 第10次"  vs "ものづくり補助金"        -> 0.8000  (med, edge)
# Threshold table (see scripts/cron/adoption_program_join.py):
#   THRESHOLD_HIGH = 0.92, THRESHOLD_MED = 0.80
_ADOPTIONS = [
    # Exact primary_name (3)
    (1, "IT導入補助金", None, 5_000_000),
    (2, "事業再構築補助金", None, 30_000_000),
    (3, "小規模事業者持続化補助金", None, 1_000_000),
    # Exact alias (5) — all hit prog-1 via aliases.
    (4, "IT補助金", None, 5_000_000),
    (5, "IT補助金", None, 5_000_000),
    (6, "デジタル化補助金", None, 5_000_000),
    (7, "デジタル化補助金", None, 5_000_000),
    (8, "IT補助金", None, 5_000_000),
    # Fuzzy_high (4) — single-char trailing drift, ratios all >= 0.92.
    (9, "IT導入補助金1", None, 5_000_000),  # 0.9333
    (10, "事業再構築補助金A", None, 30_000_000),  # 0.9412
    (11, "ものづくり補助金A", None, 12_000_000),  # 0.9412 (S>B tie-break)
    (12, "小規模事業者持続化補助金1", None, 1_000_000),  # 0.9600
    # Fuzzy_med (3) — multi-char round/year suffix drift, 0.80 <= r < 0.92.
    (13, "IT導入補助金 後期", None, 5_000_000),  # 0.8750
    (14, "IT導入補助金 前期", None, 5_000_000),  # 0.8750
    (15, "ものづくり補助金 第10次", None, 12_000_000),  # 0.8000
    # Unmatched (5) — ratio < 0.80 against any program.
    (16, "全く関係ない補助金A", None, 1_000_000),
    (17, "全く関係ない補助金A", None, 1_000_000),
    (18, "全く関係ない補助金B", None, 1_000_000),
    (19, "別の架空制度", None, 1_000_000),
    (20, "まったく違う名前", None, 1_000_000),
]


def _seed_jpintel(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE programs (
                unified_id TEXT PRIMARY KEY,
                primary_name TEXT NOT NULL,
                aliases_json TEXT,
                prefecture TEXT,
                tier TEXT,
                amount_max_man_yen REAL,
                excluded INTEGER DEFAULT 0,
                authority_level TEXT,
                authority_name TEXT,
                municipality TEXT,
                program_kind TEXT,
                official_url TEXT,
                amount_min_man_yen REAL,
                subsidy_rate REAL,
                trust_level TEXT,
                coverage_score REAL,
                gap_to_tier_s_json TEXT,
                a_to_j_coverage_json TEXT,
                exclusion_reason TEXT,
                crop_categories_json TEXT,
                equipment_category TEXT,
                target_types_json TEXT,
                funding_purpose_json TEXT,
                amount_band TEXT,
                application_window_json TEXT,
                enriched_json TEXT,
                source_mentions_json TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.executemany(
            "INSERT INTO programs("
            "  unified_id, primary_name, aliases_json, prefecture, tier, "
            "  amount_max_man_yen"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            _PROGRAMS,
        )
        conn.commit()
    finally:
        conn.close()


def _seed_autonomath(db_path: Path) -> None:
    """Seed autonomath.db with jpi_adoption_records (post mig 114 schema) + am_alias."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE jpi_adoption_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                houjin_bangou TEXT NOT NULL DEFAULT '0',
                program_id_hint TEXT,
                program_name_raw TEXT,
                company_name_raw TEXT,
                round_label TEXT,
                round_number INTEGER,
                announced_at TEXT,
                prefecture TEXT,
                municipality TEXT,
                project_title TEXT,
                industry_raw TEXT,
                industry_jsic_medium TEXT,
                amount_granted_yen INTEGER,
                amount_project_total_yen INTEGER,
                source_url TEXT NOT NULL DEFAULT '',
                source_pdf_page TEXT,
                fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
                confidence REAL NOT NULL DEFAULT 0.85,
                program_id TEXT,
                program_id_match_method TEXT,
                program_id_match_score REAL
            );
            CREATE INDEX idx_jpi_adoption_records_program_id
                ON jpi_adoption_records(program_id, program_id_match_method);
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
        for row_id, name, prefecture, amount in _ADOPTIONS:
            conn.execute(
                "INSERT INTO jpi_adoption_records("
                "  id, houjin_bangou, program_name_raw, prefecture, "
                "  amount_granted_yen, source_url, fetched_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    row_id,
                    "0",
                    name,
                    prefecture,
                    amount,
                    "https://example.invalid/",
                    "2026-04-30T00:00:00Z",
                ),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def seeded_dbs(tmp_path: Path) -> tuple[Path, Path]:
    """Fresh jpintel.db + autonomath.db with the substrate the cron needs."""
    j = tmp_path / "jpintel.db"
    a = tmp_path / "autonomath.db"
    _seed_jpintel(j)
    _seed_autonomath(a)
    return j, a


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_match_bucket_counts(seeded_dbs):
    j, a = seeded_dbs
    out = _cron.run(jpintel_db=j, autonomath_db=a)
    assert out["rows_scanned"] == 20
    assert out["exact_matched"] == 8, f"expected 8 exact, got {out['exact_matched']}; out={out}"
    assert (
        out["fuzzy_high_matched"] == 4
    ), f"expected 4 fuzzy_high, got {out['fuzzy_high_matched']}; out={out}"
    assert (
        out["fuzzy_med_matched"] == 3
    ), f"expected 3 fuzzy_med, got {out['fuzzy_med_matched']}; out={out}"
    assert out["unmatched"] == 5, f"expected 5 unmatched, got {out['unmatched']}; out={out}"
    # elapsed_s should be present and non-negative.
    assert isinstance(out["elapsed_s"], float)
    assert out["elapsed_s"] >= 0.0


def test_idempotent_second_run(seeded_dbs):
    """Running the cron twice in a row produces the same program_id state."""
    j, a = seeded_dbs
    _cron.run(jpintel_db=j, autonomath_db=a)
    # Snapshot every (id, program_id, method, score) tuple post-first-run.
    conn = sqlite3.connect(a)
    try:
        first = conn.execute(
            "SELECT id, program_id, program_id_match_method, "
            "       program_id_match_score "
            "  FROM jpi_adoption_records ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    out2 = _cron.run(jpintel_db=j, autonomath_db=a)
    # Default mode skips already-matched rows (program_id IS NOT NULL),
    # and the only-unknown rows re-evaluate to unknown again — so the
    # net change is zero new matches and the snapshot is unchanged.
    assert out2["exact_matched"] == 0
    assert out2["fuzzy_high_matched"] == 0
    assert out2["fuzzy_med_matched"] == 0
    # Unmatched rows ARE re-scanned (they have NULL program_id) but
    # produce no new matches.
    conn = sqlite3.connect(a)
    try:
        second = conn.execute(
            "SELECT id, program_id, program_id_match_method, "
            "       program_id_match_score "
            "  FROM jpi_adoption_records ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert first == second, (
        "Idempotency violation: rows changed between back-to-back runs.\n"
        f"first={first}\nsecond={second}"
    )


def test_top_unmatched_program_names(seeded_dbs):
    """`top_unmatched_program_names` lists names in count-DESC order.

    Our seed puts "全く関係ない補助金A" twice (rows 16 + 17) and 3 other
    names once. Most-common item must be that name with count=2; the
    other 3 unmatched names appear with count=1 each in the list. List
    length is 4 (4 distinct unmatched names; 5 unmatched rows).
    """
    j, a = seeded_dbs
    out = _cron.run(jpintel_db=j, autonomath_db=a)
    top = out["top_unmatched_program_names"]
    assert isinstance(top, list)
    # 4 distinct unmatched names (one of them appears twice).
    assert len(top) == 4
    # Most-common must be the duplicated name with count=2.
    assert top[0]["program_name_raw"] == "全く関係ない補助金A"
    assert top[0]["count"] == 2
    # Remaining entries are count=1 (order among them is stable per Counter).
    other_names = {item["program_name_raw"] for item in top[1:]}
    assert other_names == {
        "全く関係ない補助金B",
        "別の架空制度",
        "まったく違う名前",
    }


def test_tie_break_prefers_higher_tier(seeded_dbs):
    """Same primary_name in 2 programs (S vs B) -> match resolves to S.

    "ものづくり補助金A" is fuzzy_high (ratio=0.9412) against both prog-3
    (S, national) and prog-4 (B, 東京都). The adoption row carries
    prefecture=None, so the prefecture step rates them equal; the tier
    step picks S over B.
    """
    j, a = seeded_dbs
    _cron.run(jpintel_db=j, autonomath_db=a)
    conn = sqlite3.connect(a)
    try:
        row = conn.execute(
            "SELECT program_id, program_id_match_method "
            "  FROM jpi_adoption_records "
            " WHERE program_name_raw='ものづくり補助金A'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "prog-3", f"expected prog-3 (tier=S), got {row[0]} — tie-break broke"
    assert row[1] == "fuzzy_name_high"


def test_alias_hit_lands_as_exact(seeded_dbs):
    """Alias surface form hits (prog-1's aliases) record method='exact_alias'."""
    j, a = seeded_dbs
    _cron.run(jpintel_db=j, autonomath_db=a)
    conn = sqlite3.connect(a)
    try:
        rows = conn.execute(
            "SELECT program_name_raw, program_id, program_id_match_method "
            "  FROM jpi_adoption_records "
            " WHERE program_name_raw IN ('IT補助金', 'デジタル化補助金') "
            " ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) >= 2
    for raw_name, pid, method in rows:
        assert pid == "prog-1", f"alias '{raw_name}' didn't resolve to prog-1"
        assert method == "exact_alias"


def test_unmatched_rows_have_unknown_method(seeded_dbs):
    """Unmatched rows persist with method='unknown' and program_id=NULL."""
    j, a = seeded_dbs
    _cron.run(jpintel_db=j, autonomath_db=a)
    conn = sqlite3.connect(a)
    try:
        rows = conn.execute(
            "SELECT program_id, program_id_match_method, "
            "       program_id_match_score "
            "  FROM jpi_adoption_records "
            " WHERE program_name_raw IN ("
            "   '全く関係ない補助金A', '全く関係ない補助金B', "
            "   '別の架空制度', 'まったく違う名前'"
            " )"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 5
    for pid, method, score in rows:
        assert pid is None
        assert method == "unknown"
        assert score == 0.0


def test_migration_is_idempotent(tmp_path: Path):
    """Re-applying mig 114 yields stable schema state.

    Mig 114 uses bare `ALTER TABLE ADD COLUMN` (no IF NOT EXISTS — sqlite
    doesn't support that syntax for ALTER), so the second apply raises
    "duplicate column name". The migration runner (`scripts/migrate.py`,
    duplicate_column_skipping) and `entrypoint.sh` §4 self-heal loop
    both record the migration as applied on the first pass, so the
    second pass is never executed in prod. This test exercises the same
    duplicate-column tolerance: we apply via `executescript` (the same
    function migrate.py uses); the second apply raises but the column
    set must not drift.

    The `CREATE INDEX IF NOT EXISTS` IS portable, so the index stays
    stable on its own.
    """
    db = tmp_path / "autonomath.db"
    sql = _MIG_114.read_text(encoding="utf-8")
    conn = sqlite3.connect(db)
    try:
        # Emulate the on-disk schema fragment we're ALTERing.
        conn.executescript(
            """
            CREATE TABLE jpi_adoption_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                houjin_bangou TEXT NOT NULL DEFAULT '0',
                program_name_raw TEXT,
                source_url TEXT NOT NULL DEFAULT '',
                fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.commit()
        # First apply: must land cleanly.
        conn.executescript(sql)
        cols = {c[1] for c in conn.execute("PRAGMA table_info(jpi_adoption_records)")}
        assert "program_id" in cols
        assert "program_id_match_method" in cols
        assert "program_id_match_score" in cols
        idx_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "  AND name='idx_jpi_adoption_records_program_id'"
        ).fetchall()
        assert len(idx_rows) == 1

        # Second apply: ALTERs raise "duplicate column", but executescript
        # commits the statements before the failing one and leaves the
        # rest. We expect an OperationalError; downstream is the
        # caller's job (migrate.py records as applied). Schema must be
        # identical post-failure.
        with pytest.raises(sqlite3.OperationalError) as excinfo:
            conn.executescript(sql)
        assert "duplicate column" in str(excinfo.value).lower()
        cols2 = {c[1] for c in conn.execute("PRAGMA table_info(jpi_adoption_records)")}
        assert cols2 == cols, "column set drifted on re-apply"
    finally:
        conn.close()
