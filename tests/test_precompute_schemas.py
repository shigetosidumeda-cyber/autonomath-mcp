"""Schema + dry-run tests for the 32 pre-compute (pc_*) tables.

Covers both waves:

  * C3 (migration 044): 14 tables added 2026-04-25.
  * D8 (migration 045): 18 tables added 2026-04-25.

Verifies:

  * Each pc_* table exists in the migrated DB.
  * Each table has the columns the cron expects (so a real INSERT will not
    fail with "no such column").
  * Each table has at least one named index from its migration block (this
    is the structural assertion behind the L3 read posture: lookups by the
    leading dimension must hit an index, not a scan).
  * The cron's PC_TABLES tuple matches the union of both waves.
  * Dry-run iterates over all 32 tables exactly once.
  * No LLM SDK leaks into the cron (memory: feedback_autonomath_no_api_use).
"""

from __future__ import annotations

import importlib
import logging
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
MIGRATIONS_DIR = SCRIPTS_DIR / "migrations"


# Wave C3 (migration 044) — 14 tables, expected column set per table.
PC_TABLES_C3: dict[str, set[str]] = {
    "pc_top_subsidies_by_industry": {
        "industry_jsic",
        "rank",
        "program_id",
        "relevance_score",
        "cached_payload",
        "refreshed_at",
    },
    "pc_top_subsidies_by_prefecture": {
        "prefecture_code",
        "rank",
        "program_id",
        "relevance_score",
        "cached_payload",
        "refreshed_at",
    },
    "pc_law_to_program_index": {
        "law_id",
        "program_id",
        "citation_kind",
        "refreshed_at",
    },
    "pc_program_to_amendments": {
        "program_id",
        "amendment_id",
        "severity",
        "observed_at",
        "summary",
        "refreshed_at",
    },
    "pc_acceptance_stats_by_program": {
        "program_id",
        "fiscal_year",
        "round_label",
        "applied_count",
        "accepted_count",
        "acceptance_rate",
        "refreshed_at",
    },
    "pc_combo_pairs": {
        "program_a",
        "program_b",
        "compat_kind",
        "rationale",
        "refreshed_at",
    },
    "pc_seasonal_calendar": {
        "month_of_year",
        "program_id",
        "deadline_date",
        "deadline_kind",
        "refreshed_at",
    },
    "pc_industry_jsic_aliases": {
        "alias_text",
        "industry_jsic",
        "confidence",
        "source",
        "refreshed_at",
    },
    "pc_authority_to_programs": {
        "authority_id",
        "program_id",
        "role",
        "refreshed_at",
    },
    "pc_law_amendments_recent": {
        "amendment_id",
        "law_id",
        "severity",
        "effective_date",
        "observed_at",
        "summary",
        "refreshed_at",
    },
    "pc_enforcement_by_industry": {
        "industry_jsic",
        "enforcement_id",
        "severity",
        "observed_at",
        "headline",
        "refreshed_at",
    },
    "pc_loan_by_collateral_type": {
        "collateral_type",
        "rank",
        "loan_program_id",
        "cap_amount_yen",
        "refreshed_at",
    },
    "pc_certification_by_subject": {
        "subject_code",
        "rank",
        "certification_id",
        "refreshed_at",
    },
    "pc_starter_packs_per_audience": {
        "audience",
        "rank",
        "program_id",
        "note",
        "refreshed_at",
    },
}

# Wave D8 (migration 045) — 18 tables.
PC_TABLES_D8: dict[str, set[str]] = {
    "pc_amendment_recent_by_law": {
        "law_id",
        "amendment_id",
        "severity",
        "effective_date",
        "summary",
        "refreshed_at",
    },
    "pc_program_geographic_density": {
        "prefecture_code",
        "tier",
        "program_count",
        "refreshed_at",
    },
    "pc_authority_action_frequency": {
        "authority_id",
        "month_yyyymm",
        "action_count",
        "refreshed_at",
    },
    "pc_law_to_amendment_chain": {
        "law_id",
        "amendment_id",
        "parent_amendment_id",
        "position",
        "effective_date",
        "refreshed_at",
    },
    "pc_industry_jsic_to_program": {
        "industry_jsic",
        "rank",
        "program_id",
        "relevance_score",
        "refreshed_at",
    },
    "pc_amount_max_distribution": {
        "bucket",
        "program_count",
        "refreshed_at",
    },
    "pc_program_to_loan_combo": {
        "program_id",
        "loan_program_id",
        "compat_kind",
        "rationale",
        "refreshed_at",
    },
    "pc_program_to_certification_combo": {
        "program_id",
        "certification_id",
        "requirement_kind",
        "refreshed_at",
    },
    "pc_program_to_tax_combo": {
        "program_id",
        "tax_ruleset_id",
        "applicability",
        "refreshed_at",
    },
    "pc_acceptance_rate_by_authority": {
        "authority_id",
        "fiscal_year",
        "applied_count",
        "accepted_count",
        "acceptance_rate",
        "program_coverage",
        "refreshed_at",
    },
    "pc_application_close_calendar": {
        "month_of_year",
        "program_id",
        "close_date",
        "days_until",
        "refreshed_at",
    },
    "pc_amount_to_recipient_size": {
        "amount_bucket",
        "smb_size_class",
        "recipient_count",
        "refreshed_at",
    },
    "pc_law_text_to_program_count": {
        "law_id",
        "program_count",
        "last_cited_at",
        "refreshed_at",
    },
    "pc_court_decision_law_chain": {
        "court_id",
        "law_id",
        "decision_id",
        "relation_kind",
        "decided_at",
        "refreshed_at",
    },
    "pc_enforcement_industry_distribution": {
        "industry_jsic",
        "severity",
        "five_year_count",
        "refreshed_at",
    },
    "pc_loan_collateral_to_program": {
        "collateral_type",
        "program_id",
        "rank",
        "refreshed_at",
    },
    "pc_invoice_registrant_by_pref": {
        "prefecture_code",
        "registrant_count",
        "last_seen_at",
        "refreshed_at",
    },
    "pc_amendment_severity_distribution": {
        "severity",
        "month_yyyymm",
        "amendment_count",
        "refreshed_at",
    },
}

PC_TABLES_ALL: dict[str, set[str]] = {**PC_TABLES_C3, **PC_TABLES_D8}

# E1 / V4 wave (migration 048+) — tables that physically live in autonomath.db,
# not jpintel.db. We don't validate their schema here (the test fixture only
# applies jpintel-side migrations 043/044/045) but the cron must still iterate
# them, so they belong in the cron-level cardinality + dry-run + real-run
# assertions below. Keep this set aligned with cron's PC_TABLES_AM.
PC_TABLES_AM: set[str] = {
    "jpi_pc_program_health",
    # `am_amendment_diff` (migration 075) — append-only diff log refreshed
    # by `_refresh_am_amendment_diff` in the cron. The cron's PC_TABLES_AM
    # short-circuit guarantees the refresher never DELETEs, only inserts.
    "am_amendment_diff",
}

# Cron-level expected set: jpintel-shard tables + AM-shard tables. This is
# what `cron_module.PC_TABLES` should equal.
PC_TABLES_CRON: set[str] = set(PC_TABLES_ALL.keys()) | PC_TABLES_AM


@pytest.fixture(scope="module")
def migrated_db() -> Path:
    """Apply migrations 043 (l4 cache) + 044 + 045 to a fresh temp DB."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="pc-schema-test-"))
    db_path = tmp_dir / "jpintel.db"
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        for mig in ("043_l4_cache.sql", "044_precompute_tables.sql", "045_precompute_more.sql"):
            sql = (MIGRATIONS_DIR / mig).read_text(encoding="utf-8")
            conn.executescript(sql)
    finally:
        conn.close()
    return db_path


def test_total_pc_table_count_is_32():
    """Schema-level invariant — one number to remember when reading the
    plan: 14 (C3) + 18 (D8) = 32. The cron iterates over exactly this set.
    """
    assert len(PC_TABLES_ALL) == 32
    assert len(PC_TABLES_C3) == 14
    assert len(PC_TABLES_D8) == 18
    # No accidental name collision between waves.
    assert set(PC_TABLES_C3.keys()).isdisjoint(set(PC_TABLES_D8.keys()))


@pytest.mark.parametrize("table", sorted(PC_TABLES_ALL.keys()))
def test_pc_table_exists(migrated_db: Path, table: str):
    conn = sqlite3.connect(str(migrated_db))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"{table} missing after migrations"


@pytest.mark.parametrize("table,expected_cols", sorted(PC_TABLES_ALL.items()))
def test_pc_table_columns(migrated_db: Path, table: str, expected_cols: set[str]):
    conn = sqlite3.connect(str(migrated_db))
    try:
        cols = {
            r[1]  # name
            for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
    finally:
        conn.close()
    missing = expected_cols - cols
    assert not missing, f"{table} missing columns: {missing}"


@pytest.mark.parametrize("table", sorted(PC_TABLES_ALL.keys()))
def test_pc_table_has_index(migrated_db: Path, table: str):
    """Every pc_* table should be backed by either a PRIMARY KEY or at
    least one named secondary index. Without it, the L3 read posture
    collapses into a full-table scan on miss.
    """
    conn = sqlite3.connect(str(migrated_db))
    try:
        idx_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
            (table,),
        ).fetchall()
        # PK-backed indexes are auto-named (sqlite_autoindex_*); explicit
        # indexes have human names. Either form satisfies the contract.
        assert idx_rows, f"{table} has no index at all"
    finally:
        conn.close()


@pytest.fixture(scope="module")
def cron_module(migrated_db: Path):
    """Import the cron with PYTHONPATH set up so its `from jpintel_mcp...`
    imports resolve. Force settings.db_path to the migrated test DB so the
    dry-run reads from our schema rather than the repo's data/jpintel.db.
    """
    src = REPO_ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    cron_dir = SCRIPTS_DIR / "cron"
    if str(cron_dir) not in sys.path:
        sys.path.insert(0, str(cron_dir))
    # Drop any cached copy so re-runs see live edits to the file.
    sys.modules.pop("precompute_refresh", None)
    mod = importlib.import_module("precompute_refresh")
    return mod


def test_cron_pc_tables_matches_migrations(cron_module):
    """The PC_TABLES tuple in the cron must be the exact union of the two
    migration waves PLUS the AM-resident E1/V4 tables. Drift here would
    leave a table un-refreshed nightly.
    """
    expected = PC_TABLES_CRON
    got = set(cron_module.PC_TABLES)
    assert got == expected, f"cron drift: missing={expected - got}, extra={got - expected}"
    # 32 jpintel-shard + 1 am-shard (jpi_pc_program_health) = 33.
    assert len(cron_module.PC_TABLES) == 32 + len(PC_TABLES_AM)
    # The C3 / D8 split helpers should match the migration boundaries.
    assert set(cron_module.PC_TABLES_C3) == set(PC_TABLES_C3.keys())
    assert set(cron_module.PC_TABLES_D8) == set(PC_TABLES_D8.keys())
    # The AM-shard split helper should match the cron-side constant.
    assert set(cron_module.PC_TABLES_AM) == PC_TABLES_AM


def test_cron_refreshers_cover_all_32(cron_module):
    """Every entry in PC_TABLES has a corresponding callable in REFRESHERS."""
    for name in cron_module.PC_TABLES:
        assert name in cron_module.REFRESHERS, f"no refresher registered for {name}"
        assert callable(cron_module.REFRESHERS[name])


def test_cron_dry_run_iterates_all_32(
    migrated_db: Path, cron_module, caplog: pytest.LogCaptureFixture
):
    """End-to-end dry-run: every pc_* table appears in the dry-run log line
    `pc_dry_run table=<name> current_rows=<n>`. Empty tables are fine; the
    point is the cron *visited* every table.
    """
    caplog.set_level(logging.INFO, logger="autonomath.cron.precompute_refresh")
    counters = cron_module.run(
        db_path=migrated_db,
        am_db_path=Path("/nonexistent-am-db-for-tests.db"),
        only=None,
        dry_run=True,
    )
    # Dry-run returns 0 for every table (it does not delete or insert).
    assert set(counters.keys()) == set(cron_module.PC_TABLES)
    assert all(v == 0 for v in counters.values())

    # Each table should have produced a dry-run log line.
    msgs = [rec.getMessage() for rec in caplog.records]
    for name in cron_module.PC_TABLES:
        assert any(f"table={name}" in m for m in msgs), f"no dry-run log line for {name}"


def test_cron_real_run_keeps_tables_empty_pre_launch(migrated_db: Path, cron_module):
    """Pre-launch contract: refreshers are stubs returning 0. After a non-
    dry run every pc_* table is still empty (DELETE then INSERT-zero).
    """
    counters = cron_module.run(
        db_path=migrated_db,
        am_db_path=Path("/nonexistent-am-db-for-tests.db"),
        only=None,
        dry_run=False,
    )
    # Strip the side-channel l4_swept counter when present.
    table_counters = {k: v for k, v in counters.items() if not k.startswith("__")}
    assert set(table_counters.keys()) == set(cron_module.PC_TABLES)
    assert all(v == 0 for v in table_counters.values())

    # And the jpintel-shard tables remain empty on disk. The AM-shard tables
    # live in autonomath.db (which the test fixture deliberately points at a
    # nonexistent path), so we don't probe them on `migrated_db`.
    conn = sqlite3.connect(str(migrated_db))
    try:
        for name in cron_module.PC_TABLES:
            if name in cron_module.PC_TABLES_AM:
                continue
            (n,) = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()  # noqa: S608
            assert n == 0, f"{name} non-empty after stub refresh: {n} rows"
    finally:
        conn.close()


def test_cron_no_llm_sdk_imports():
    """Hard guarantee per memory `feedback_autonomath_no_api_use`: the
    nightly cron must not import any LLM provider SDK.
    """
    src = (SCRIPTS_DIR / "cron" / "precompute_refresh.py").read_text(encoding="utf-8")
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
