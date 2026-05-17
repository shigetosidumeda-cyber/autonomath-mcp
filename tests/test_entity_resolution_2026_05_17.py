"""Unit + smoke tests for CC3 cross-corpus entity resolution.

Covers:
  * Phase 1 — entity canonical-id assignment (soft-merge by houjin_bangou).
  * Phase 2 — am_compat_matrix heuristic -> sourced upgrade rules.
  * 4-way join view (v_corp_program_judgment_law) shape + non-emptiness.
  * Migration wave24_208 idempotency markers (column / view / indexes exist).

These tests run against the live autonomath.db at the repo root (read-only).
They are SKIPPED if the DB is missing or if the migration has not been
applied yet (CI sandboxes without the 16GB DB).
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
ETL_PATH = (
    REPO_ROOT
    / "scripts"
    / "etl"
    / "cc3_entity_canonical_assignment_2026_05_17.py"
)

if not AUTONOMATH_DB.exists():
    pytest.skip(
        f"autonomath.db not present at {AUTONOMATH_DB}",
        allow_module_level=True,
    )


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _has_index(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({table})"))


@pytest.fixture(scope="module")
def db() -> Iterator[sqlite3.Connection]:
    uri = f"file:{AUTONOMATH_DB}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=60.0)
    conn.execute("PRAGMA busy_timeout = 60000")
    if not _has_column(conn, "am_entities", "entity_id_canonical"):
        pytest.skip("migration wave24_208 not applied (column missing)")
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1..5  migration shape
# ---------------------------------------------------------------------------


def test_entity_id_canonical_column_exists(db: sqlite3.Connection) -> None:
    assert _has_column(db, "am_entities", "entity_id_canonical")


def test_v_corp_program_judgment_law_exists(db: sqlite3.Connection) -> None:
    assert _has_table(db, "v_corp_program_judgment_law")


def test_canonical_axis_indexes_exist(db: sqlite3.Connection) -> None:
    assert _has_index(db, "idx_am_entities_canonical_axis")
    assert _has_index(db, "idx_am_entities_kind_canonical")


def test_cross_corpus_supporting_indexes_exist(db: sqlite3.Connection) -> None:
    for name in (
        "idx_am_entity_facts_houjin_bangou",
        "idx_am_relation_type_source",
        "idx_am_relation_type_target",
        "idx_am_law_article_law_canonical",
        "idx_am_compat_matrix_inferred",
    ):
        assert _has_index(db, name), f"missing index: {name}"


def test_migration_recorded_in_schema_migrations(db: sqlite3.Connection) -> None:
    row = db.execute(
        "SELECT id FROM schema_migrations WHERE id='wave24_208_am_entity_canonical_id.sql'"
    ).fetchone()
    assert row is not None


# ---------------------------------------------------------------------------
# 6..10  Phase 1 — canonical-id assignment
# ---------------------------------------------------------------------------


def test_canonical_column_fully_populated(db: sqlite3.Connection) -> None:
    """After Phase 1, no entity_id_canonical should be NULL."""
    total = db.execute("SELECT COUNT(*) FROM am_entities").fetchone()[0]
    filled = db.execute(
        "SELECT COUNT(*) FROM am_entities WHERE entity_id_canonical IS NOT NULL"
    ).fetchone()[0]
    # tolerate <0.1% NULL if a concurrent ingest landed mid-run
    assert filled / total >= 0.999, (
        f"entity_id_canonical fill {filled}/{total} below 0.999"
    )


def test_canonical_anchor_membership_consistent(db: sqlite3.Connection) -> None:
    """Every entity_id_canonical value must itself be a canonical_id in am_entities."""
    row = db.execute(
        """
        SELECT COUNT(*) FROM am_entities e
        WHERE e.entity_id_canonical IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM am_entities f
              WHERE f.canonical_id = e.entity_id_canonical
          )
        """
    ).fetchone()
    assert row[0] == 0, f"{row[0]} entities point at a non-existent canonical anchor"


def test_canonical_anchor_is_self_or_lower(db: sqlite3.Connection) -> None:
    """Anchor is the ASCII-min member of its group; entity_id_canonical <= canonical_id always."""
    bad = db.execute(
        """
        SELECT COUNT(*) FROM am_entities
        WHERE entity_id_canonical IS NOT NULL
          AND entity_id_canonical > canonical_id
        """
    ).fetchone()[0]
    assert bad == 0


def test_cross_corpus_canonical_clustering_nontrivial(db: sqlite3.Connection) -> None:
    """At least one anchor must serve >1 member (proves cross-corpus merging happened)."""
    row = db.execute(
        """
        SELECT entity_id_canonical, COUNT(*) c FROM am_entities
        WHERE entity_id_canonical IS NOT NULL
        GROUP BY entity_id_canonical
        HAVING c > 1
        ORDER BY c DESC LIMIT 1
        """
    ).fetchone()
    assert row is not None and row[1] >= 2


def test_canonical_group_count_matches_cross_corpus_houjin_bangou(
    db: sqlite3.Connection,
) -> None:
    """The number of multi-member canonical groups must be >= 1000.

    The CC3 spec sized at ~166K duplicate groups across corporate_entity +
    adoption + case_study. We accept anything >= 1000 as evidence the ETL
    actually walked the cross-corpus axis.
    """
    n_groups = db.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT entity_id_canonical FROM am_entities
            WHERE entity_id_canonical IS NOT NULL
            GROUP BY entity_id_canonical
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    assert n_groups >= 1_000, f"only {n_groups} multi-member canonical groups"


# ---------------------------------------------------------------------------
# 11..13  Phase 2 — compat-matrix upgrade
# ---------------------------------------------------------------------------


def test_compat_matrix_sourced_count_positive(db: sqlite3.Connection) -> None:
    n = db.execute(
        "SELECT COUNT(*) FROM am_compat_matrix WHERE inferred_only=0"
    ).fetchone()[0]
    assert n >= 100, f"compat_matrix sourced rows ({n}) implausibly low"


def test_compat_matrix_status_enum_valid(db: sqlite3.Connection) -> None:
    row = db.execute(
        """
        SELECT COUNT(*) FROM am_compat_matrix
        WHERE compat_status NOT IN ('compatible','incompatible','case_by_case','unknown')
        """
    ).fetchone()
    assert row[0] == 0


def test_compat_matrix_no_self_loops(db: sqlite3.Connection) -> None:
    n = db.execute(
        "SELECT COUNT(*) FROM am_compat_matrix WHERE program_a_id=program_b_id"
    ).fetchone()[0]
    assert n == 0, f"{n} self-loop compat rows"


# ---------------------------------------------------------------------------
# 14..17  4-way join view (v_corp_program_judgment_law)
# ---------------------------------------------------------------------------


def test_v_corp_program_judgment_law_returns_rows(db: sqlite3.Connection) -> None:
    """Streaming LIMIT 1 — confirms at least one row exists without
    materializing the multi-billion cartesian product the view can express."""
    row = db.execute(
        "SELECT 1 FROM v_corp_program_judgment_law LIMIT 1"
    ).fetchone()
    assert row is not None, "4-way join view returned 0 rows — corpus is empty?"


def test_v_corp_program_judgment_law_canonical_axis_count(
    db: sqlite3.Connection,
) -> None:
    """Bounded count via the indexed canonical axis instead of the slow
    expression-join inside the view. Confirms the cross-corpus reach is
    on the order of 100K corp×adoption pairs."""
    n = db.execute(
        """
        SELECT COUNT(*) FROM am_entities e1
        JOIN am_entities e2
          ON e2.entity_id_canonical = e1.entity_id_canonical
        WHERE e1.record_kind='corporate_entity'
          AND e2.record_kind='adoption'
        """
    ).fetchone()[0]
    assert n >= 100_000, f"cross-corpus reach ({n}) implausibly low"


def test_v_corp_program_judgment_law_shape(db: sqlite3.Connection) -> None:
    """Verify the projection contract."""
    cur = db.execute("SELECT * FROM v_corp_program_judgment_law LIMIT 1")
    cols = [d[0] for d in cur.description]
    expected = {
        "corp_id",
        "corp_canonical",
        "corp_name",
        "houjin_bangou",
        "adoption_id",
        "adoption_canonical",
        "adoption_name",
        "program_id",
        "adoption_to_program_relation",
        "law_canonical_id",
        "article_id",
        "article_number",
        "article_title",
        "join_confidence",
    }
    missing = expected - set(cols)
    assert not missing, f"v_corp_program_judgment_law missing columns: {missing}"


def test_v_corp_program_judgment_law_houjin_bangou_normalized(
    db: sqlite3.Connection,
) -> None:
    """No row should carry a NULL or whitespace-only houjin_bangou."""
    row = db.execute(
        """
        SELECT COUNT(*) FROM v_corp_program_judgment_law
        WHERE houjin_bangou IS NULL OR TRIM(houjin_bangou)=''
        """
    ).fetchone()
    assert row[0] == 0


def test_v_corp_program_judgment_law_corp_adopt_share_houjin(
    db: sqlite3.Connection,
) -> None:
    """corp.houjin_bangou must equal adopt.houjin_bangou (no spurious joins)."""
    rows = db.execute(
        """
        SELECT corp_id, adoption_id, houjin_bangou
        FROM v_corp_program_judgment_law LIMIT 5
        """
    ).fetchall()
    assert rows  # non-empty smoke
    for corp_id, adoption_id, hb in rows:
        # Both sides must reference the same houjin_bangou — projection guarantees this.
        # We re-derive from facts to double-check.
        a = db.execute(
            "SELECT TRIM(field_value_text) FROM am_entity_facts "
            "WHERE entity_id=? AND field_name='houjin_bangou' LIMIT 1",
            (corp_id,),
        ).fetchone()
        b = db.execute(
            "SELECT TRIM(field_value_text) FROM am_entity_facts "
            "WHERE entity_id=? AND field_name='houjin_bangou' LIMIT 1",
            (adoption_id,),
        ).fetchone()
        assert a is not None and b is not None
        assert a[0] == b[0] == hb


# ---------------------------------------------------------------------------
# 18..20  ETL module-level smoke
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cc3_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cc3_etl", ETL_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cc3_etl"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_etl_exports_phase1_functions(cc3_module: ModuleType) -> None:
    for name in (
        "collect_duplicate_groups",
        "write_canonical_anchors",
        "assign_singletons",
    ):
        assert hasattr(cc3_module, name), f"missing ETL export: {name}"


def test_etl_exports_phase2_functions(cc3_module: ModuleType) -> None:
    for name in (
        "collect_heuristic_compat_rows",
        "upgrade_heuristic_to_sourced",
        "_verify_chunk",
    ):
        assert hasattr(cc3_module, name), f"missing ETL export: {name}"


def test_etl_dry_run_does_not_mutate(
    cc3_module: ModuleType,
    db: sqlite3.Connection,
) -> None:
    """Calling main with --dry-run must not change any counts."""
    before_canonical = db.execute(
        "SELECT COUNT(*) FROM am_entities WHERE entity_id_canonical IS NOT NULL"
    ).fetchone()[0]
    before_sourced = db.execute(
        "SELECT COUNT(*) FROM am_compat_matrix WHERE inferred_only=0"
    ).fetchone()[0]
    rc: int = cc3_module.main(["--db", str(AUTONOMATH_DB), "--dry-run"])
    assert rc == 0
    after_canonical = db.execute(
        "SELECT COUNT(*) FROM am_entities WHERE entity_id_canonical IS NOT NULL"
    ).fetchone()[0]
    after_sourced = db.execute(
        "SELECT COUNT(*) FROM am_compat_matrix WHERE inferred_only=0"
    ).fetchone()[0]
    assert before_canonical == after_canonical
    assert before_sourced == after_sourced
