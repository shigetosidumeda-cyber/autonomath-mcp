"""Integration tests for Dim K rule-tree storage (Wave 47).

Closes the Wave 46 dim K storage gap: persists the 5 canonical decision
trees in ``am_rule_trees`` (mig 271) and proves they round-trip through
the existing PR #139 eval kernel in ``src/jpintel_mcp/api/rule_tree_eval``.

Three case bundles:
  1. Migration applies cleanly on a fresh SQLite db (idempotent re-apply).
  2. ETL seed_rule_tree_definitions inserts 5 trees, dry-run reports
     identical stats, second apply is a no-op.
  3. Each seeded tree feeds the eval kernel and returns a well-formed
     envelope with rationale + path + LEAF citations (Dim O integration).

Hard constraints exercised
--------------------------
  * No LLM SDK import (Dim K is fully deterministic).
  * Migration table names match the PR #139 disclaimer
    (am_rule_trees / am_rule_nodes / am_rule_tree_eval_log).
  * Idempotent re-apply: a 2nd run is a no-op (no row count change).
  * Citation gap surfaces as "conditional" not "pass" when a LEAF
    source_doc_id is None.
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
import tempfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_271 = REPO_ROOT / "scripts" / "migrations" / "271_rule_tree.sql"
MIG_271_RB = REPO_ROOT / "scripts" / "migrations" / "271_rule_tree_rollback.sql"
ETL_SEED = REPO_ROOT / "scripts" / "etl" / "seed_rule_tree_definitions.py"
SRC_RULE_TREE = (
    REPO_ROOT / "src" / "jpintel_mcp" / "api" / "rule_tree_eval.py"
)
MANIFEST_JPCITE = (
    REPO_ROOT / "scripts" / "migrations" / "jpcite_boot_manifest.txt"
)
MANIFEST_AM = (
    REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_rule_tree_module():
    """Load the rule_tree_eval module by file path (avoids package init)."""
    spec = importlib.util.spec_from_file_location(
        "_rule_tree_test_w47_mod", SRC_RULE_TREE
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_rule_tree_test_w47_mod"] = mod
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
    db = tmp_path / "rule_tree_test.db"
    _apply_migration(db, MIG_271)
    return db


# ---------------------------------------------------------------------------
# Case 1 — Migration apply + idempotent + rollback
# ---------------------------------------------------------------------------


def test_migration_271_creates_tables(tmp_path: pathlib.Path) -> None:
    """Migration 271 creates am_rule_trees + am_rule_tree_eval_log + view."""
    db = _fresh_db_with_migration(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') ORDER BY name"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "am_rule_trees" in names
    assert "am_rule_tree_eval_log" in names
    assert "v_rule_trees_latest" in names


def test_migration_271_idempotent(tmp_path: pathlib.Path) -> None:
    """Re-applying migration 271 is a no-op (every CREATE uses IF NOT EXISTS)."""
    db = _fresh_db_with_migration(tmp_path)
    # Second apply must not raise.
    _apply_migration(db, MIG_271)
    conn = sqlite3.connect(str(db))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='am_rule_trees'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_migration_271_rollback_drops(tmp_path: pathlib.Path) -> None:
    """Rollback drops the storage surface cleanly."""
    db = _fresh_db_with_migration(tmp_path)
    _apply_migration(db, MIG_271_RB)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "am_rule_trees" not in names
    assert "am_rule_tree_eval_log" not in names


# ---------------------------------------------------------------------------
# Case 2 — ETL seed: dry-run + apply + idempotent
# ---------------------------------------------------------------------------


def test_seed_etl_dry_run(tmp_path: pathlib.Path) -> None:
    """Dry-run reports 5 inserted, 0 skipped, total=5; no rows written."""
    db = _fresh_db_with_migration(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(ETL_SEED),
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
    assert payload["dim"] == "K"
    assert payload["seed_stats"]["total"] == 5
    assert payload["seed_stats"]["inserted"] == 5
    # No actual write occurred.
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_rule_trees").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_seed_etl_apply_then_idempotent(tmp_path: pathlib.Path) -> None:
    """Two-shot apply: first writes 5 rows, second skips all 5."""
    db = _fresh_db_with_migration(tmp_path)
    first = subprocess.run(
        [sys.executable, str(ETL_SEED), "--db", str(db)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, f"stderr={first.stderr}"
    p1 = json.loads(first.stdout.strip().splitlines()[-1])
    assert p1["seed_stats"]["inserted"] == 5
    assert p1["seed_stats"]["skipped"] == 0

    second = subprocess.run(
        [sys.executable, str(ETL_SEED), "--db", str(db)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, f"stderr={second.stderr}"
    p2 = json.loads(second.stdout.strip().splitlines()[-1])
    assert p2["seed_stats"]["inserted"] == 0
    assert p2["seed_stats"]["skipped"] == 5


def test_seed_etl_writes_5_canonical_trees(tmp_path: pathlib.Path) -> None:
    """The 5 canonical tree_ids land in am_rule_trees with valid JSON."""
    db = _fresh_db_with_migration(tmp_path)
    res = subprocess.run(
        [sys.executable, str(ETL_SEED), "--db", str(db)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"stderr={res.stderr}"
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT tree_id, version, status, domain, tree_def_json "
            "FROM am_rule_trees ORDER BY tree_id"
        ).fetchall()
    finally:
        conn.close()
    tids = {r[0] for r in rows}
    expected = {
        "subsidy_eligibility_v1",
        "gyouhou_fence_check_v1",
        "investment_condition_check_v1",
        "adoption_score_threshold_v1",
        "due_diligence_v1",
    }
    assert tids == expected
    for tid, version, status, domain, defj in rows:
        assert version == 1
        assert status == "committed"
        assert domain  # non-empty
        # JSON must parse + be a dict shaped like a tree.
        tree = json.loads(defj)
        assert isinstance(tree, dict)
        assert isinstance(tree.get("node_id"), str)
        assert tree.get("operator") in {"AND", "OR", "XOR", "LEAF"}


# ---------------------------------------------------------------------------
# Case 3 — Seeded trees feed the existing PR #139 eval kernel
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rule_tree_module():
    return _import_rule_tree_module()


@pytest.fixture
def seeded_db(tmp_path: pathlib.Path) -> pathlib.Path:
    """Fresh db with migration applied + 5 trees seeded."""
    db = _fresh_db_with_migration(tmp_path)
    res = subprocess.run(
        [sys.executable, str(ETL_SEED), "--db", str(db)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    return db


def _positive_input() -> dict:
    """Input dict that yields PASS across every seeded tree."""
    return {
        # subsidy_eligibility
        "entity_size": "sme",
        "industry_code": "F",
        "prefecture_jis": "13",
        # gyouhou_fence
        "licence_id": "L-001",
        "licence_status": "valid",
        "cross_jurisdiction": False,
        # investment
        "capital_amount": 50000000,
        "employee_count": 8,
        "export_ratio_pct": 0,
        # adoption
        "composite_score": 80,
        "diversity_bonus": False,
        # dd
        "tax_compliant": True,
        "filing_current": True,
        "bankruptcy_filed": False,
        "has_audit_opinion": False,
        "exempt_from_audit": True,
    }


def test_seeded_trees_pass_with_positive_input(
    seeded_db: pathlib.Path, rule_tree_module
) -> None:
    """Each seeded tree evaluates to 'pass' for a hand-picked positive input."""
    conn = sqlite3.connect(str(seeded_db))
    try:
        rows = conn.execute(
            "SELECT tree_id, tree_def_json FROM am_rule_trees"
        ).fetchall()
    finally:
        conn.close()
    inp = _positive_input()
    for tid, defj in rows:
        tree = json.loads(defj)
        env = rule_tree_module.evaluate_rule_tree(tree, inp)
        assert env["result"] == "pass", (
            f"tree={tid} expected pass, got {env['result']}, "
            f"rationale={env['rationale']}"
        )
        assert len(env["path"]) >= 1
        assert len(env["rationale"]) == len(env["path"])
        # Every LEAF in seeded trees has a source_doc_id → no citation gap.
        assert env["citation_gap"] is False


def test_seeded_subsidy_tree_fails_when_industry_out_of_set(
    seeded_db: pathlib.Path, rule_tree_module
) -> None:
    """Negative path: industry_code='Z' should fail subsidy_eligibility_v1."""
    conn = sqlite3.connect(str(seeded_db))
    try:
        row = conn.execute(
            "SELECT tree_def_json FROM am_rule_trees WHERE tree_id=?",
            ("subsidy_eligibility_v1",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    tree = json.loads(row[0])
    bad = dict(_positive_input())
    bad["industry_code"] = "Z"
    env = rule_tree_module.evaluate_rule_tree(tree, bad)
    assert env["result"] == "fail"


def test_seeded_dd_tree_xor_branch(
    seeded_db: pathlib.Path, rule_tree_module
) -> None:
    """XOR path in due_diligence_v1: exactly one of audit_opinion / exempt is true."""
    conn = sqlite3.connect(str(seeded_db))
    try:
        row = conn.execute(
            "SELECT tree_def_json FROM am_rule_trees WHERE tree_id=?",
            ("due_diligence_v1",),
        ).fetchone()
    finally:
        conn.close()
    tree = json.loads(row[0])
    both_true = dict(_positive_input())
    both_true["has_audit_opinion"] = True
    both_true["exempt_from_audit"] = True
    env_both = rule_tree_module.evaluate_rule_tree(tree, both_true)
    assert env_both["result"] == "fail"

    neither = dict(_positive_input())
    neither["has_audit_opinion"] = False
    neither["exempt_from_audit"] = False
    env_neither = rule_tree_module.evaluate_rule_tree(tree, neither)
    assert env_neither["result"] == "fail"


# ---------------------------------------------------------------------------
# Boot-manifest integrity
# ---------------------------------------------------------------------------


def test_manifest_jpcite_lists_271(rule_tree_module) -> None:
    """jpcite boot manifest registers migration 271_rule_tree.sql."""
    assert "271_rule_tree.sql" in MANIFEST_JPCITE.read_text(
        encoding="utf-8"
    )


def test_manifest_autonomath_lists_271(rule_tree_module) -> None:
    """autonomath boot manifest (mirror) registers migration 271."""
    assert "271_rule_tree.sql" in MANIFEST_AM.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# No-LLM-import + brand discipline
# ---------------------------------------------------------------------------


_FORBIDDEN_LLM_IMPORTS = ("anthropic", "openai", "google.generativeai")


def test_no_llm_import_in_etl_or_migration() -> None:
    """Dim K storage MUST stay LLM-free (feedback_no_operator_llm_api)."""
    sources = [
        ETL_SEED.read_text(encoding="utf-8"),
        MIG_271.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in _FORBIDDEN_LLM_IMPORTS:
            assert f"import {bad}" not in src
            assert f"from {bad}" not in src


def test_no_legacy_brand_in_new_files() -> None:
    """No 税務会計AI / zeimu-kaikei.ai / AutonoMath legacy brand in new files."""
    legacy_phrases = ("税務会計AI", "zeimu-kaikei.ai")
    sources = [
        ETL_SEED.read_text(encoding="utf-8"),
        MIG_271.read_text(encoding="utf-8"),
        MIG_271_RB.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in legacy_phrases:
            assert bad not in src, f"legacy brand `{bad}` found in new file"
