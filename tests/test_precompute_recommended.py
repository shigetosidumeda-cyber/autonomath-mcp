"""Tests for `scripts/cron/precompute_recommended_programs.py`.

Covers the "5 法人 × 10 program → 50 row INSERT" contract specified in
the W3-12 / W3-13 fix plan, plus:

  * --dry-run does NOT write to am_recommended_programs.
  * Real run inserts exactly 50 rows (5 × 10) when seeded as such.
  * Composite score ∈ [0, 1] for every row.
  * reason_json round-trips: contains all 5 signal keys + weights summing
    to 1.0.
  * No LLM SDK leaks into the cron script (memory:
    `feedback_autonomath_no_api_use`).
"""

from __future__ import annotations

import importlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
CRON_DIR = SCRIPTS_DIR / "cron"
SCRIPT_PATH = CRON_DIR / "precompute_recommended_programs.py"


# ---------------------------------------------------------------------------
# Hermetic AM DB fixture
# ---------------------------------------------------------------------------


def _build_test_am_db(path: Path, n_houjin: int = 5, n_programs: int = 10) -> None:
    """Build a minimal autonomath.db shape with 5 houjin × 10 programs.

    Table shapes mirror the production migrations (subset of columns the
    cron actually reads). Only what's necessary for end-to-end scoring.
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE houjin_master (
                houjin_bangou TEXT PRIMARY KEY,
                normalized_name TEXT NOT NULL,
                prefecture TEXT,
                close_date TEXT,
                total_adoptions INTEGER NOT NULL DEFAULT 0,
                total_received_yen INTEGER NOT NULL DEFAULT 0,
                jsic_major TEXT,
                jsic_middle TEXT
            );
            CREATE TABLE jpi_programs (
                unified_id TEXT PRIMARY KEY,
                primary_name TEXT NOT NULL,
                tier TEXT,
                prefecture TEXT,
                program_kind TEXT,
                amount_min_man_yen REAL,
                amount_max_man_yen REAL,
                excluded INTEGER NOT NULL DEFAULT 0,
                jsic_major TEXT,
                jsic_middle TEXT
            );
            CREATE TABLE adoption_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                houjin_bangou TEXT NOT NULL,
                program_id_hint TEXT,
                amount_granted_yen INTEGER
            );
            CREATE TABLE am_application_round (
                round_id INTEGER PRIMARY KEY AUTOINCREMENT,
                program_entity_id TEXT NOT NULL,
                round_label TEXT NOT NULL,
                application_close_date TEXT
            );
            CREATE TABLE entity_id_map (
                jpi_unified_id TEXT,
                am_canonical_id TEXT,
                match_method TEXT,
                confidence REAL
            );
            CREATE TABLE am_recommended_programs (
                houjin_bangou      TEXT NOT NULL,
                program_unified_id TEXT NOT NULL,
                rank               INTEGER NOT NULL CHECK (rank > 0),
                score              REAL NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
                reason_json        TEXT,
                computed_at        TEXT NOT NULL DEFAULT (datetime('now')),
                source_snapshot_id TEXT,
                PRIMARY KEY (houjin_bangou, program_unified_id)
            );
            """
        )
        # Seed 5 houjin in JSIC E (Manufacturing), Tokyo.
        for i in range(n_houjin):
            hb = f"{(1000000000000 + i):013d}"
            conn.execute(
                """INSERT INTO houjin_master
                   (houjin_bangou, normalized_name, prefecture, close_date,
                    total_adoptions, total_received_yen, jsic_major, jsic_middle)
                   VALUES (?, ?, '東京都', NULL, ?, ?, 'E', '24')""",
                (hb, f"テスト法人{i + 1}", 3, 30_000_000 - i),
            )
            # Each houjin has 3 prior adoptions of varying amounts.
            for j in range(3):
                conn.execute(
                    """INSERT INTO adoption_records
                       (houjin_bangou, program_id_hint, amount_granted_yen)
                       VALUES (?, ?, ?)""",
                    (hb, f"prog-{j:02d}", 5_000_000 + j * 1_000_000),
                )
        # Seed 10 tier S/A programs in JSIC E, Tokyo.
        for j in range(n_programs):
            uid = f"prog-{j:02d}"
            tier = "S" if j < 3 else "A"
            conn.execute(
                """INSERT INTO jpi_programs
                   (unified_id, primary_name, tier, prefecture, program_kind,
                    amount_min_man_yen, amount_max_man_yen, excluded,
                    jsic_major, jsic_middle)
                   VALUES (?, ?, ?, '東京都', 'subsidy', ?, ?, 0, 'E', '24')""",
                (uid, f"テスト制度{j + 1}", tier, 100.0 + j * 10, 1000.0 + j * 100),
            )
            # Map program to am_canonical_id and seed an open round (close
            # date in the far future) so application_window_open scores 1.0.
            conn.execute(
                """INSERT INTO entity_id_map
                   (jpi_unified_id, am_canonical_id, match_method, confidence)
                   VALUES (?, ?, 'exact_name', 1.0)""",
                (uid, f"program:test:{uid}"),
            )
            conn.execute(
                """INSERT INTO am_application_round
                   (program_entity_id, round_label, application_close_date)
                   VALUES (?, '令和7年度 第1次', date('now', '+90 days'))""",
                (f"program:test:{uid}",),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def am_db(tmp_path: Path) -> Path:
    p = tmp_path / "test_autonomath.db"
    _build_test_am_db(p, n_houjin=5, n_programs=10)
    return p


@pytest.fixture(scope="module")
def cron_module():
    src = REPO_ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    if str(CRON_DIR) not in sys.path:
        sys.path.insert(0, str(CRON_DIR))
    sys.modules.pop("precompute_recommended_programs", None)
    return importlib.import_module("precompute_recommended_programs")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dry_run_writes_no_rows(am_db: Path, cron_module):
    counters = cron_module.run(
        am_db_path=am_db,
        max_houjin=5,
        top_n=10,
        dry_run=True,
    )
    assert counters["houjin_processed"] == 5
    assert counters["rows_written"] == 50  # accounted but NOT persisted
    assert counters["skipped"] == 0
    conn = sqlite3.connect(str(am_db))
    try:
        (n,) = conn.execute("SELECT COUNT(*) FROM am_recommended_programs").fetchone()
    finally:
        conn.close()
    assert n == 0, "dry-run must not write to am_recommended_programs"


def test_real_run_inserts_50_rows(am_db: Path, cron_module):
    counters = cron_module.run(
        am_db_path=am_db,
        max_houjin=5,
        top_n=10,
        dry_run=False,
    )
    assert counters["houjin_processed"] == 5
    assert counters["rows_written"] == 50
    conn = sqlite3.connect(str(am_db))
    conn.row_factory = sqlite3.Row
    try:
        (n,) = conn.execute("SELECT COUNT(*) FROM am_recommended_programs").fetchone()
        assert n == 50, f"expected 50 rows (5 houjin × 10), got {n}"
        # Each houjin gets exactly 10 ranks 1..10 — strict.
        per_houjin = conn.execute(
            """SELECT houjin_bangou, COUNT(*) AS c
                 FROM am_recommended_programs GROUP BY houjin_bangou"""
        ).fetchall()
        assert len(per_houjin) == 5
        for r in per_houjin:
            assert r["c"] == 10
        ranks = conn.execute(
            """SELECT houjin_bangou, MIN(rank) AS mn, MAX(rank) AS mx
                 FROM am_recommended_programs GROUP BY houjin_bangou"""
        ).fetchall()
        for r in ranks:
            assert r["mn"] == 1 and r["mx"] == 10
    finally:
        conn.close()


def test_score_in_unit_interval_and_sorted_desc(am_db: Path, cron_module):
    cron_module.run(am_db_path=am_db, max_houjin=5, top_n=10, dry_run=False)
    conn = sqlite3.connect(str(am_db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT houjin_bangou, rank, score
                 FROM am_recommended_programs
                 ORDER BY houjin_bangou, rank"""
        ).fetchall()
    finally:
        conn.close()
    assert rows
    by_h: dict[str, list[tuple[int, float]]] = {}
    for r in rows:
        assert 0.0 <= float(r["score"]) <= 1.0
        by_h.setdefault(r["houjin_bangou"], []).append((int(r["rank"]), float(r["score"])))
    # Score must be non-increasing as rank grows for every houjin.
    for hb, items in by_h.items():
        items.sort()
        scores = [s for _r, s in items]
        assert scores == sorted(scores, reverse=True), (
            f"score not sorted DESC by rank for {hb}: {scores}"
        )


def test_reason_json_carries_all_signals_and_weights_sum_to_one(am_db: Path, cron_module):
    cron_module.run(am_db_path=am_db, max_houjin=5, top_n=10, dry_run=False)
    conn = sqlite3.connect(str(am_db))
    try:
        (raw,) = conn.execute("SELECT reason_json FROM am_recommended_programs LIMIT 1").fetchone()
    finally:
        conn.close()
    payload = json.loads(raw)
    expected_signals = {
        "jsic_match",
        "region_match",
        "amount_band_fit",
        "past_adoption_pattern",
        "application_window_open",
    }
    assert set(payload["signals"].keys()) == expected_signals
    assert set(payload["weights"].keys()) == expected_signals
    assert abs(sum(payload["weights"].values()) - 1.0) < 1e-9
    # All signal scores in unit interval.
    for v in payload["signals"].values():
        assert 0.0 <= float(v) <= 1.0


def test_idempotent_rerun_does_not_double_insert(am_db: Path, cron_module):
    """A second run with the same cohort must leave row count at 50, not 100."""
    cron_module.run(am_db_path=am_db, max_houjin=5, top_n=10, dry_run=False)
    cron_module.run(am_db_path=am_db, max_houjin=5, top_n=10, dry_run=False)
    conn = sqlite3.connect(str(am_db))
    try:
        (n,) = conn.execute("SELECT COUNT(*) FROM am_recommended_programs").fetchone()
    finally:
        conn.close()
    assert n == 50


def test_missing_table_degrades_cleanly(tmp_path: Path, cron_module):
    """Without migration wave24_126 applied, cron exits 0 with no rows."""
    p = tmp_path / "no_migration.db"
    conn = sqlite3.connect(str(p))
    conn.executescript("""
        CREATE TABLE houjin_master (
            houjin_bangou TEXT PRIMARY KEY,
            normalized_name TEXT NOT NULL,
            prefecture TEXT,
            close_date TEXT,
            total_adoptions INTEGER NOT NULL DEFAULT 0,
            total_received_yen INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE jpi_programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            tier TEXT,
            prefecture TEXT,
            program_kind TEXT,
            amount_min_man_yen REAL,
            amount_max_man_yen REAL,
            excluded INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()
    counters = cron_module.run(am_db_path=p, max_houjin=5, top_n=10, dry_run=False)
    assert counters == {"houjin_processed": 0, "rows_written": 0, "skipped": 0}


def test_no_llm_sdk_imports():
    """Hard guarantee per `feedback_autonomath_no_api_use` — the cron must
    import zero LLM provider SDKs. Belt-and-suspenders to the repo-wide
    test_no_llm_in_production guard.
    """
    src = SCRIPT_PATH.read_text(encoding="utf-8")
    forbidden = (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "google.generativeai",
        "claude_agent_sdk",
        "claude-agent-sdk",
    )
    for needle in forbidden:
        assert needle not in src, f"cron imports forbidden LLM SDK: {needle!r}"
