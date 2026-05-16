"""Integration tests for Dim N anonymized-query storage (Wave 47).

Closes the Wave 46 dim N storage gap: persists the per-call audit trail
and materialized aggregate-outcome view that back PR #139's REST surface
``src/jpintel_mcp/api/anonymized_query.py`` (``POST /v1/network/
anonymized_outcomes``).

Three case bundles:
  1. Migration 274 applies cleanly + idempotent + rollback.
  2. Aggregator ETL drops sub-k=5 cohorts at materialization time and
     leaves only cohorts >= 5 in ``am_aggregated_outcome_view``.
  3. PR #139 REST integration: aggregate_cohort / redact_response paths
     enforce k=5 floor + PII strip parity with the SQL substrate.

Hard constraints exercised
--------------------------
  * No LLM SDK import (Dim N is fully deterministic).
  * Migration table names match the PR #139 disclaimer
    (am_anonymized_query_log / am_aggregated_outcome_view).
  * k=5 anonymity floor is enforced TWICE: at the CHECK constraint level
    AND at the aggregator HAVING clause. A sub-5 cohort must not appear
    in the view even if a bug bypasses one layer.
  * PII strip: the response whitelist of the REST surface drops every
    field not in ``_RESPONSE_WHITELIST`` — verified end-to-end.
  * Brand: only jpcite (and historical autonomath db filename) in
    comments + identifiers. No legacy ``税務会計AI`` / ``zeimu-kaikei.ai``.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sqlite3
import subprocess
import sys
import typing

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_274 = REPO_ROOT / "scripts" / "migrations" / "274_anonymized_query.sql"
MIG_274_RB = REPO_ROOT / "scripts" / "migrations" / "274_anonymized_query_rollback.sql"
ETL_AGGREGATE = REPO_ROOT / "scripts" / "etl" / "aggregate_anonymized_outcomes.py"
SRC_REST = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "anonymized_query.py"
MANIFEST_JPCITE = REPO_ROOT / "scripts" / "migrations" / "jpcite_boot_manifest.txt"
MANIFEST_AM = REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_rest_module() -> typing.Any:
    """Load anonymized_query.py by file path (avoids package init)."""
    spec = importlib.util.spec_from_file_location("_anon_query_test_w47_mod", SRC_REST)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_anon_query_test_w47_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def _apply_migration(db_path: pathlib.Path, sql_path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        sql = sql_path.read_text(encoding="utf-8")
        conn.executescript(sql)
    finally:
        conn.close()


def _fresh_db_with_migration(tmp_path: pathlib.Path) -> pathlib.Path:
    db = tmp_path / "anon_query_test.db"
    _apply_migration(db, MIG_274)
    return db


def _seed_corpus_with_one_eligible_cohort(db: pathlib.Path) -> None:
    """Seed minimal am_entities: 6 rows in F/13101/sme + 3 rows in G/27100/large."""
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS am_entities ("
            "entity_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "record_kind TEXT, "
            "industry_jsic_major TEXT, "
            "region_code TEXT, "
            "size_bucket TEXT)"
        )
        # k=6 (above floor) cohort
        for _ in range(6):
            conn.execute(
                "INSERT INTO am_entities "
                "(record_kind, industry_jsic_major, region_code, size_bucket) "
                "VALUES (?,?,?,?)",
                ("corporate_entity", "F", "13101", "sme"),
            )
        # k=3 (below floor) cohort — must be dropped by aggregator
        for _ in range(3):
            conn.execute(
                "INSERT INTO am_entities "
                "(record_kind, industry_jsic_major, region_code, size_bucket) "
                "VALUES (?,?,?,?)",
                ("corporate_entity", "G", "27100", "large"),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Case 1 — Migration apply + idempotent + rollback + k=5 CHECK
# ---------------------------------------------------------------------------


def test_migration_274_creates_tables(tmp_path: pathlib.Path) -> None:
    """Migration 274 creates audit log + aggregate view + helper view."""
    db = _fresh_db_with_migration(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "am_anonymized_query_log" in names
    assert "am_aggregated_outcome_view" in names
    assert "v_anon_cohort_outcomes_latest" in names


def test_migration_274_idempotent(tmp_path: pathlib.Path) -> None:
    """Re-applying migration 274 is a no-op."""
    db = _fresh_db_with_migration(tmp_path)
    _apply_migration(db, MIG_274)  # must not raise
    conn = sqlite3.connect(str(db))
    try:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='am_anonymized_query_log'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert cnt == 1


def test_migration_274_rollback_drops(tmp_path: pathlib.Path) -> None:
    """Rollback drops every storage object."""
    db = _fresh_db_with_migration(tmp_path)
    _apply_migration(db, MIG_274_RB)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "am_anonymized_query_log" not in names
    assert "am_aggregated_outcome_view" not in names
    assert "v_anon_cohort_outcomes_latest" not in names


def test_aggregate_view_k_lt_5_rejected_by_check(
    tmp_path: pathlib.Path,
) -> None:
    """CHECK(count>=5) blocks any direct INSERT below the floor."""
    db = _fresh_db_with_migration(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        for bad_k in (0, 1, 2, 3, 4):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO am_aggregated_outcome_view "
                    "(entity_cluster_id, outcome_type, count, k_value) "
                    "VALUES (?,?,?,?)",
                    (f"industry=F|k={bad_k}", "adoption", bad_k, bad_k),
                )
        # k=5 is the floor — must succeed.
        conn.execute(
            "INSERT INTO am_aggregated_outcome_view "
            "(entity_cluster_id, outcome_type, count, k_value) "
            "VALUES (?,?,?,?)",
            ("industry=F|k=5", "adoption", 5, 5),
        )
        n = conn.execute("SELECT COUNT(*) FROM am_aggregated_outcome_view").fetchone()[0]
    finally:
        conn.close()
    assert n == 1


# ---------------------------------------------------------------------------
# Case 2 — Aggregator ETL drops sub-k cohorts
# ---------------------------------------------------------------------------


def test_aggregator_dry_run(tmp_path: pathlib.Path) -> None:
    """Dry-run reports the eligible cohort count but writes no rows."""
    db = _fresh_db_with_migration(tmp_path)
    _seed_corpus_with_one_eligible_cohort(db)
    result = subprocess.run(
        [
            sys.executable,
            str(ETL_AGGREGATE),
            "--db",
            str(db),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stderr={result.stderr}"
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["dim"] == "N"
    # 1 eligible cohort × 4 outcome types
    assert payload["aggregate_stats"]["inserted"] == 4
    assert payload["aggregate_stats"]["rebuilt"] is False
    # No rows were written.
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_aggregated_outcome_view").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_aggregator_writes_only_eligible_cohorts(
    tmp_path: pathlib.Path,
) -> None:
    """Eligible cohort (k=6) lands; sub-k (k=3) is dropped entirely."""
    db = _fresh_db_with_migration(tmp_path)
    _seed_corpus_with_one_eligible_cohort(db)
    result = subprocess.run(
        [sys.executable, str(ETL_AGGREGATE), "--db", str(db)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stderr={result.stderr}"
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT entity_cluster_id, outcome_type, k_value "
            "FROM am_aggregated_outcome_view "
            "ORDER BY entity_cluster_id, outcome_type"
        ).fetchall()
    finally:
        conn.close()
    # 1 cohort × 4 outcome_types
    assert len(rows) == 4
    cluster_ids = {r[0] for r in rows}
    assert cluster_ids == {"industry=F|region=13101|size=sme"}
    # k_value invariant: every row >= 5
    assert all(r[2] >= 5 for r in rows)
    # The sub-floor cohort (G/27100/large, k=3) MUST NOT appear.
    assert not any("industry=G" in r[0] for r in rows)


def test_aggregator_idempotent_rebuild(tmp_path: pathlib.Path) -> None:
    """A second run yields the same row set (single-snapshot semantics)."""
    db = _fresh_db_with_migration(tmp_path)
    _seed_corpus_with_one_eligible_cohort(db)
    for _ in range(2):
        res = subprocess.run(
            [sys.executable, str(ETL_AGGREGATE), "--db", str(db)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, f"stderr={res.stderr}"
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_aggregated_outcome_view").fetchone()[0]
    finally:
        conn.close()
    assert n == 4


def test_aggregator_empty_corpus(tmp_path: pathlib.Path) -> None:
    """Missing am_entities table is tolerated (zero cohorts)."""
    db = _fresh_db_with_migration(tmp_path)
    # NO am_entities created.
    res = subprocess.run(
        [sys.executable, str(ETL_AGGREGATE), "--db", str(db)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    payload = json.loads(res.stdout.strip().splitlines()[-1])
    assert payload["aggregate_stats"]["inserted"] == 0
    assert payload["aggregate_stats"]["rebuilt"] is True


# ---------------------------------------------------------------------------
# Case 3 — PR #139 REST integration: k=5 floor + PII strip
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rest_module() -> typing.Any:
    return _import_rest_module()


def test_rest_k_anonymity_floor_constant(rest_module: typing.Any) -> None:
    """PR #139 REST surface pins k_min == 5 to match migration 274 CHECK."""
    assert rest_module.K_ANONYMITY_MIN == 5


def test_rest_redact_strips_unknown_fields(rest_module: typing.Any) -> None:
    """redact_response drops any field outside the whitelist."""
    filters = {"industry_jsic_major": "F", "region_code": "13101"}
    aggregates = {
        "cohort_size": 12,
        "mean_amount_yen": 5_000_000,
        "median_amount_yen": 3_000_000,
        "top_program_id_anon": "anon_abc123",
        # The following PII-ish fields should be dropped if a future
        # substrate query returns them by accident.
        "houjin_bangou": "1234567890123",
        "company_name": "Example KK",
        "address": "Tokyo",
    }
    out = rest_module.redact_response(filters, aggregates)
    # Whitelisted fields preserved
    assert out["cohort_size"] == 12
    assert out["industry_jsic_major"] == "F"
    assert out["region_code"] == "13101"
    # PII fields stripped
    assert "houjin_bangou" not in out
    assert "company_name" not in out
    assert "address" not in out


def test_rest_aggregate_cohort_deterministic(
    rest_module: typing.Any,
) -> None:
    """Same filter triple → same synthetic cohort_size (replay-able)."""
    f1 = {"industry_jsic_major": "F", "region_code": "13101"}
    a = rest_module.aggregate_cohort(f1)
    b = rest_module.aggregate_cohort(f1)
    assert a == b
    # Different filter → likely different cohort_size.
    c = rest_module.aggregate_cohort({"industry_jsic_major": "G"})
    assert c is not None


def test_rest_audit_log_records_decision(
    rest_module: typing.Any,
) -> None:
    """Each REST call appends one audit row carrying redact_policy_version."""
    before = len(rest_module.get_audit_log_snapshot())
    filters = {"industry_jsic_major": "A"}
    aggregates = rest_module.aggregate_cohort(filters)
    assert aggregates is not None
    rest_module._audit_log_call(filters, aggregates["cohort_size"], "served")
    after = rest_module.get_audit_log_snapshot()
    assert len(after) == before + 1
    last = after[-1]
    assert last["redact_policy_version"] == rest_module.REDACT_POLICY_VERSION
    assert "filter_hash" in last
    assert last["decision"] == "served"


def test_rest_whitelist_matches_substrate_columns(
    rest_module: typing.Any,
) -> None:
    """The REST whitelist surface intersects the SQL aggregate view columns."""
    whitelist = rest_module._RESPONSE_WHITELIST
    # Cohort-defining fields surface, per feedback_anonymized_query_pii_redact.
    assert "cohort_size" in whitelist
    assert "industry_jsic_major" in whitelist
    assert "region_code" in whitelist
    assert "size_bucket" in whitelist
    # Envelope fields surface.
    assert "_disclaimer" in whitelist
    assert "_billing_unit" in whitelist
    assert "_redact_policy_version" in whitelist
    # PII fields do NOT surface.
    assert "houjin_bangou" not in whitelist
    assert "company_name" not in whitelist


# ---------------------------------------------------------------------------
# Boot-manifest integrity
# ---------------------------------------------------------------------------


def test_manifest_jpcite_lists_274() -> None:
    """jpcite boot manifest registers migration 274_anonymized_query.sql."""
    assert "274_anonymized_query.sql" in MANIFEST_JPCITE.read_text(encoding="utf-8")


def test_manifest_autonomath_lists_274() -> None:
    """autonomath boot manifest registers migration 274_anonymized_query.sql."""
    assert "274_anonymized_query.sql" in MANIFEST_AM.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# No-LLM-import + brand discipline
# ---------------------------------------------------------------------------


_FORBIDDEN_LLM_IMPORTS = ("anthropic", "openai", "google.generativeai")


def test_no_llm_import_in_etl_or_migration() -> None:
    """Dim N storage MUST stay LLM-free (feedback_no_operator_llm_api)."""
    sources = [
        ETL_AGGREGATE.read_text(encoding="utf-8"),
        MIG_274.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in _FORBIDDEN_LLM_IMPORTS:
            assert f"import {bad}" not in src
            assert f"from {bad}" not in src


def test_no_legacy_brand_in_new_files() -> None:
    """No 税務会計AI / zeimu-kaikei.ai legacy brand in new files."""
    legacy_phrases = ("税務会計AI", "zeimu-kaikei.ai")
    sources = [
        ETL_AGGREGATE.read_text(encoding="utf-8"),
        MIG_274.read_text(encoding="utf-8"),
        MIG_274_RB.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in legacy_phrases:
            assert bad not in src, f"legacy brand `{bad}` found in new file"
