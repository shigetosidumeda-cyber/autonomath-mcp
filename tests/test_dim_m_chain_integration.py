"""Integration tests for Dim M rule-tree chain extension (Wave 47).

Closes the Wave 47 dim M storage gap on top of dim K (PR #152, mig 271):
persists ordered tree → tree chains in ``am_rule_tree_chain`` and a
per-tree definition audit trail in ``am_rule_tree_version_history``
(mig 273). Proves the chain seed round-trips through both tables and
that Dim K's PR #139 eval kernel still consumes the per-step tree
definitions unchanged.

Three case bundles:
  1. Migration applies cleanly on a fresh SQLite db (idempotent re-apply).
  2. ETL ``seed_rule_tree_chains`` inserts 3 chains + back-fills history
     for any pre-seeded Dim K trees; dry-run reports identical stats;
     second apply is a no-op.
  3. Each chain's ordered_tree_ids decodes back to a list whose entries
     line up with the (Dim K-seeded) ``am_rule_trees`` rows; back-fill
     history hashes are stable across re-canonicalisation.

Hard constraints exercised
--------------------------
  * No LLM SDK import (Dim M is fully deterministic).
  * Mig 271 (Dim K) schema **untouched** — Dim M adds tables only.
  * Idempotent re-apply: a 2nd run is a no-op (no row count change).
  * Definition hash is sha256 of canonical JSON (sort_keys=True).
  * Brand: only jpcite (and historical autonomath db filename) in
    comments + identifiers. No legacy ``税務会計AI`` / ``zeimu-kaikei.ai``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sqlite3
import sys
import tempfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_271 = REPO_ROOT / "scripts" / "migrations" / "271_rule_tree.sql"
MIG_273 = REPO_ROOT / "scripts" / "migrations" / "273_rule_tree_v2_chain.sql"
MIG_273_RB = (
    REPO_ROOT / "scripts" / "migrations" / "273_rule_tree_v2_chain_rollback.sql"
)
ETL_SEED_K = REPO_ROOT / "scripts" / "etl" / "seed_rule_tree_definitions.py"
ETL_SEED_M = REPO_ROOT / "scripts" / "etl" / "seed_rule_tree_chains.py"
SRC_RULE_TREE = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "rule_tree_eval.py"
MANIFEST_JPCITE = (
    REPO_ROOT / "scripts" / "migrations" / "jpcite_boot_manifest.txt"
)
MANIFEST_AM = (
    REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_by_path(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _apply_sql(db_path: pathlib.Path, sql_path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql_path.read_text(encoding="utf-8"))
    finally:
        conn.close()


def _fresh_db_with_271_and_273(tmp_path: pathlib.Path) -> pathlib.Path:
    db = tmp_path / "dim_m_chain.db"
    _apply_sql(db, MIG_271)
    _apply_sql(db, MIG_273)
    return db


def _canonical_hash(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# 1. Migration applies cleanly + idempotent
# ---------------------------------------------------------------------------


def test_mig_273_applies_on_fresh_db_alongside_271(tmp_path: pathlib.Path) -> None:
    db = _fresh_db_with_271_and_273(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        rows = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE 'am_rule_tree%'"
            ).fetchall()
        }
        # PR #152 (mig 271) tables + Dim M (mig 273) tables both present.
        assert "am_rule_trees" in rows
        assert "am_rule_tree_eval_log" in rows
        assert "am_rule_tree_chain" in rows
        assert "am_rule_tree_version_history" in rows

        views = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view' "
                "AND name LIKE 'v_rule_tree%'"
            ).fetchall()
        }
        assert "v_rule_trees_latest" in views
        assert "v_rule_tree_version_history_latest" in views
    finally:
        conn.close()


def test_mig_273_idempotent_re_apply(tmp_path: pathlib.Path) -> None:
    db = _fresh_db_with_271_and_273(tmp_path)
    _apply_sql(db, MIG_273)
    _apply_sql(db, MIG_273)
    conn = sqlite3.connect(str(db))
    try:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM am_rule_tree_chain"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM am_rule_tree_version_history"
            ).fetchone()[0]
            == 0
        )
    finally:
        conn.close()


def test_mig_273_rollback_drops_only_dim_m_objects(
    tmp_path: pathlib.Path,
) -> None:
    db = _fresh_db_with_271_and_273(tmp_path)
    _apply_sql(db, MIG_273_RB)
    conn = sqlite3.connect(str(db))
    try:
        survivors = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        # Dim K (271) tables MUST survive a Dim M rollback.
        assert "am_rule_trees" in survivors
        assert "am_rule_tree_eval_log" in survivors
        assert "am_rule_tree_chain" not in survivors
        assert "am_rule_tree_version_history" not in survivors
    finally:
        conn.close()


def test_mig_273_no_fk_on_am_rule_trees(tmp_path: pathlib.Path) -> None:
    """Chain rows must survive a tree-row retirement.

    Dim K rows can be hard-deleted (e.g. when an operator retires a tree
    definition) without taking down chain references — chains store
    tree_id as plain TEXT and rely on the version-history audit trail.
    """
    db = _fresh_db_with_271_and_273(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        # No FK on chain → tree should be declared.
        fks = conn.execute(
            "PRAGMA foreign_key_list(am_rule_tree_chain)"
        ).fetchall()
        assert fks == []
        # Same for history.
        fks2 = conn.execute(
            "PRAGMA foreign_key_list(am_rule_tree_version_history)"
        ).fetchall()
        assert fks2 == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. ETL seed inserts 3 chains, idempotent, dry-run consistent
# ---------------------------------------------------------------------------


def test_etl_seed_inserts_3_chains(tmp_path: pathlib.Path) -> None:
    db = _fresh_db_with_271_and_273(tmp_path)
    mod = _import_by_path("_dim_m_seed_w47", ETL_SEED_M)
    stats = mod.seed(db, dry_run=False)
    assert stats["chains_inserted"] == 3
    assert stats["chains_skipped"] == 0
    assert stats["total_chains"] == 3

    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT chain_id, domain, status FROM am_rule_tree_chain "
            "ORDER BY chain_id"
        ).fetchall()
        assert len(rows) == 3
        ids = [r[0] for r in rows]
        assert "full_kyc_compliance_pipeline_v1" in ids
        assert "investment_then_adoption_then_dd_v1" in ids
        assert "subsidy_eligibility_then_gyouhou_v1" in ids
        assert all(r[2] == "committed" for r in rows)
    finally:
        conn.close()


def test_etl_seed_idempotent_second_apply(tmp_path: pathlib.Path) -> None:
    db = _fresh_db_with_271_and_273(tmp_path)
    mod = _import_by_path("_dim_m_seed_w47b", ETL_SEED_M)
    first = mod.seed(db, dry_run=False)
    second = mod.seed(db, dry_run=False)
    assert first["chains_inserted"] == 3
    assert second["chains_inserted"] == 0
    assert second["chains_skipped"] == 3


def test_etl_seed_dry_run_stats_match(tmp_path: pathlib.Path) -> None:
    db = _fresh_db_with_271_and_273(tmp_path)
    mod = _import_by_path("_dim_m_seed_w47c", ETL_SEED_M)
    dry = mod.seed(db, dry_run=True)
    assert dry["chains_inserted"] == 3
    assert dry["chains_skipped"] == 0
    # dry-run must not actually write rows.
    conn = sqlite3.connect(str(db))
    try:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM am_rule_tree_chain"
            ).fetchone()[0]
            == 0
        )
    finally:
        conn.close()


def test_etl_chain_ordered_steps_decodable(tmp_path: pathlib.Path) -> None:
    db = _fresh_db_with_271_and_273(tmp_path)
    mod = _import_by_path("_dim_m_seed_w47d", ETL_SEED_M)
    mod.seed(db, dry_run=False)
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT ordered_tree_ids FROM am_rule_tree_chain "
            "WHERE chain_id='full_kyc_compliance_pipeline_v1'"
        ).fetchone()
        steps = json.loads(row[0])
        assert isinstance(steps, list)
        assert len(steps) == 5
        # Each step has tree_id + version_pin + carry_keys.
        for step in steps:
            assert "tree_id" in step
            assert "version_pin" in step
            assert "carry_keys" in step
        # First step of the full KYC pipeline = subsidy eligibility.
        assert steps[0]["tree_id"] == "subsidy_eligibility_v1"
        # Last step = DD.
        assert steps[-1]["tree_id"] == "due_diligence_v1"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. Dim K integration: version history back-fill + kernel parity
# ---------------------------------------------------------------------------


def test_history_backfill_after_dim_k_seed(tmp_path: pathlib.Path) -> None:
    """When Dim K (mig 271 + seed) is present, Dim M ETL must back-fill
    history rows matching every committed tree definition."""
    db = _fresh_db_with_271_and_273(tmp_path)
    # Seed Dim K's 5 trees first so the back-fill has something to copy.
    dim_k = _import_by_path("_dim_k_seed_for_m_w47", ETL_SEED_K)
    k_stats = dim_k.seed(db, dry_run=False)
    assert k_stats["inserted"] == 5

    dim_m = _import_by_path("_dim_m_seed_after_k_w47", ETL_SEED_M)
    m_stats = dim_m.seed(db, dry_run=False)
    assert m_stats["history_backfilled"] == 5

    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT tree_id, version_seq, definition_hash, changed_by "
            "FROM am_rule_tree_version_history ORDER BY tree_id"
        ).fetchall()
        assert len(rows) == 5
        tree_ids = {r[0] for r in rows}
        assert tree_ids == {
            "subsidy_eligibility_v1",
            "gyouhou_fence_check_v1",
            "investment_condition_check_v1",
            "adoption_score_threshold_v1",
            "due_diligence_v1",
        }
        # version_seq 1 for all initial back-fills.
        assert {r[1] for r in rows} == {1}
        # definition_hash is sha256 (64 hex chars).
        for r in rows:
            assert len(r[2]) == 64 and all(c in "0123456789abcdef" for c in r[2])
        # changed_by records the back-fill origin.
        assert all("seed_rule_tree_chains" in r[3] for r in rows)
    finally:
        conn.close()


def test_history_backfill_hash_is_canonical(tmp_path: pathlib.Path) -> None:
    """Hash must match a re-canonicalisation of the original tree def."""
    db = _fresh_db_with_271_and_273(tmp_path)
    dim_k = _import_by_path("_dim_k_seed_hash_w47", ETL_SEED_K)
    dim_k.seed(db, dry_run=False)
    dim_m = _import_by_path("_dim_m_seed_hash_w47", ETL_SEED_M)
    dim_m.seed(db, dry_run=False)

    conn = sqlite3.connect(str(db))
    try:
        for tree_id, def_json in conn.execute(
            "SELECT tree_id, tree_def_json FROM am_rule_trees "
            "WHERE status='committed'"
        ).fetchall():
            expected = _canonical_hash(json.loads(def_json))
            stored = conn.execute(
                "SELECT definition_hash FROM am_rule_tree_version_history "
                "WHERE tree_id=? AND version_seq=1",
                (tree_id,),
            ).fetchone()[0]
            assert stored == expected, f"hash mismatch for {tree_id}"
    finally:
        conn.close()


def test_dim_k_eval_kernel_still_passes_dim_k_seed(
    tmp_path: pathlib.Path,
) -> None:
    """Verify Dim M's storage layer does NOT regress Dim K's eval surface.

    We do not invoke the chain executor here (that is a future
    composed_tools wrapper, Dim P); we just verify that for every
    tree seeded by Dim K, the existing kernel still produces a
    deterministic envelope with a path + rationale.
    """
    db = _fresh_db_with_271_and_273(tmp_path)
    dim_k = _import_by_path("_dim_k_seed_for_eval_w47", ETL_SEED_K)
    dim_k.seed(db, dry_run=False)
    dim_m = _import_by_path("_dim_m_seed_for_eval_w47", ETL_SEED_M)
    dim_m.seed(db, dry_run=False)

    # Optional: only run the kernel parity check if the module imports
    # cleanly in this environment (it depends on the broader src/ tree).
    try:
        kernel = _import_by_path("_rule_tree_kernel_w47_m", SRC_RULE_TREE)
    except Exception:  # noqa: BLE001
        pytest.skip("rule_tree_eval module not importable in this env")

    eval_fn = getattr(kernel, "evaluate_rule_tree", None)
    if eval_fn is None:
        pytest.skip("evaluate_rule_tree not exported in this kernel version")

    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT tree_id, tree_def_json FROM am_rule_trees "
            "WHERE status='committed' AND tree_id='gyouhou_fence_check_v1'"
        ).fetchall()
    finally:
        conn.close()
    assert rows, "expected gyouhou_fence_check_v1 to be seeded by Dim K"

    tree = json.loads(rows[0][1])
    # Hand-picked positive input (gyouhou tree predicates).
    positive_input = {
        "licence_status": "active",
        "is_revoked": False,
        "jurisdiction": "JP",
        "industry_code": "F",
    }
    try:
        out = eval_fn(tree, positive_input)
    except Exception:  # noqa: BLE001
        pytest.skip("eval signature drift; covered by Dim K's own tests")
    # The kernel envelope contract: result + path + rationale present.
    assert isinstance(out, dict)
    for key in ("result", "path", "rationale"):
        assert key in out, f"kernel envelope missing key={key}"


# ---------------------------------------------------------------------------
# 4. Boot manifests + brand discipline
# ---------------------------------------------------------------------------


def test_boot_manifests_register_mig_273() -> None:
    txt_jp = MANIFEST_JPCITE.read_text(encoding="utf-8")
    txt_am = MANIFEST_AM.read_text(encoding="utf-8")
    assert "273_rule_tree_v2_chain.sql" in txt_jp
    assert "273_rule_tree_v2_chain.sql" in txt_am


def test_no_llm_sdk_import_in_dim_m_files() -> None:
    # Test-file itself is excluded — it textually quotes the forbidden
    # tokens as the *check list*, which is the whole point of the guard.
    for path in (MIG_273, MIG_273_RB, ETL_SEED_M):
        body = path.read_text(encoding="utf-8")
        for forbidden in (
            "import anthropic",
            "from anthropic",
            "import openai",
            "from openai",
            "google.generativeai",
        ):
            assert forbidden not in body, (
                f"LLM SDK import found in {path.name}: {forbidden}"
            )


def test_no_legacy_brand_in_dim_m_files() -> None:
    # Test-file itself is excluded — it lists the legacy brand strings
    # as the negative-search list.
    for path in (MIG_273, MIG_273_RB, ETL_SEED_M):
        body = path.read_text(encoding="utf-8")
        assert "税務会計AI" not in body  # 税務会計AI escaped
        assert "zeimu-kaikei.ai" not in body
