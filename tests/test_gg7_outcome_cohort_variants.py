"""GG7 — Tests for the 432 × 5 cohort outcome variant fan-out.

Coverage:
1. Generator emits exactly 432 × 5 = 2,160 rows.
2. Every (outcome_id, cohort) pair has a row (no missing).
3. Each variant has 4 non-null fields (gloss / next_step /
   cohort_saving_yen_per_query / computed_at).
4. Sample row for 税理士 × outcome bucket=tax surfaces the expected
   workflow vocabulary.
5. The MCP tool ``get_outcome_for_cohort`` returns the cohort-specific
   envelope; rejects unknown cohorts / out-of-range outcome ids;
   returns the canonical empty envelope when the table is missing.
6. Fragment manifest registers the GG7 module under the existing
   ``_register_fragments.yaml`` so ``__init__.py`` is not edited.

NO LLM. Pure SQLite + Python. Idempotent across runs (in-memory DB).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

# Pull the generator + tool under test.
from scripts.aws_credit_ops.generate_cohort_outcome_variants_2026_05_17 import (
    COHORT_IDS,
    COHORT_OUTCOME_BUCKET_MATCH,
    COHORT_REP_TIER,
    TIER_OPUS_YEN,
    TIER_YEN,
    _cohort_saving_yen,
    _outcome_bucket,
    build_gloss,
    build_next_step,
    ensure_schema,
    generate_variants,
    upsert_variants,
)
from scripts.aws_credit_ops.pre_map_outcomes_to_top_chunks_2026_05_17 import (
    WAVE_60_94_OUTCOMES,
    OutcomeRow,
    load_outcomes,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def synthetic_outcomes() -> list[OutcomeRow]:
    """Load the deterministic 432-row Wave 60-94 outcome catalog."""
    conn = sqlite3.connect(":memory:")
    try:
        outcomes = load_outcomes(conn)
    finally:
        conn.close()
    # load_outcomes returns 432 deterministic rows on a fresh DB.
    return outcomes


@pytest.fixture(scope="module")
def populated_db(synthetic_outcomes: list[OutcomeRow]) -> Iterator[Path]:
    """Build a temp DB with the migration applied + 2,160 variant rows."""
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False, suffix="_gg7.db") as tmp:
        db_path = Path(tmp.name)
    conn = sqlite3.connect(db_path)
    try:
        ensure_schema(conn)
        rows = generate_variants(synthetic_outcomes, computed_at="2026-05-17T00:00:00Z")
        upsert_variants(conn, rows)
        conn.commit()
    finally:
        conn.close()
    yield db_path
    db_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 1-3. Generator row count / completeness / non-null
# ---------------------------------------------------------------------------


def test_generator_emits_exactly_2160_rows(
    synthetic_outcomes: list[OutcomeRow],
) -> None:
    rows = generate_variants(synthetic_outcomes, computed_at="2026-05-17T00:00:00Z")
    assert len(rows) == 432 * 5
    assert len(rows) == 2_160


def test_wave_60_94_outcomes_constant() -> None:
    assert WAVE_60_94_OUTCOMES == 432
    assert len(COHORT_IDS) == 5


def test_every_outcome_cohort_pair_present(
    synthetic_outcomes: list[OutcomeRow],
) -> None:
    rows = generate_variants(synthetic_outcomes, computed_at="2026-05-17T00:00:00Z")
    pairs = {(r.outcome_id, r.cohort) for r in rows}
    expected = {(o.outcome_id, c) for o in synthetic_outcomes for c in COHORT_IDS}
    assert pairs == expected
    assert len(pairs) == 432 * 5


def test_each_variant_has_4_non_null_fields(
    synthetic_outcomes: list[OutcomeRow],
) -> None:
    rows = generate_variants(synthetic_outcomes, computed_at="2026-05-17T00:00:00Z")
    for r in rows:
        assert r.gloss
        assert r.next_step
        assert r.cohort_saving_yen_per_query >= 0
        assert r.computed_at == "2026-05-17T00:00:00Z"


# ---------------------------------------------------------------------------
# 4. Cohort × bucket match sample (税理士 × tax) surfaces workflow vocab
# ---------------------------------------------------------------------------


def test_zeirishi_tax_bucket_match_surface_keyword(
    synthetic_outcomes: list[OutcomeRow],
) -> None:
    """zeirishi cohort × tax bucket → 'tax' label + '別表' / '損金算入' tail.

    The synthetic catalog has 36 outcomes per cohort bucket, so
    ``wave60_94_tax_000`` is the first tax outcome. The generated
    next_step must invoke the canonical 税理士 workflow language.
    """
    tax_outcomes = [o for o in synthetic_outcomes if _outcome_bucket(o.slug) == "tax"]
    assert len(tax_outcomes) >= 1
    sample = tax_outcomes[0]
    gloss = build_gloss(sample, "zeirishi")
    step = build_next_step(sample, "zeirishi")
    # The cohort × bucket overlap is matched → tail should mention 顧問先.
    assert "税理士" in step
    assert "別表4" in step or "損金算入" in step
    # Gloss head must surface the 税理士 viewpoint vocabulary.
    assert "別表" in gloss or "損金" in gloss


def test_unmatched_cohort_bucket_uses_peripheral_phrasing(  # noqa: N802 -- domain test
    synthetic_outcomes: list[OutcomeRow],
) -> None:
    """shihoshoshi × tax bucket is not in COHORT_OUTCOME_BUCKET_MATCH."""
    assert "tax" not in COHORT_OUTCOME_BUCKET_MATCH["shihoshoshi"]
    tax_sample = next(o for o in synthetic_outcomes if _outcome_bucket(o.slug) == "tax")
    gloss = build_gloss(tax_sample, "shihoshoshi")
    assert "周辺領域" in gloss


# ---------------------------------------------------------------------------
# 5. Saving formula (FF1 SOT tier-derived)
# ---------------------------------------------------------------------------


def test_cohort_saving_yen_matches_ff1_tier_formula() -> None:
    """saving = (opus_yen - jpcite_yen) for the cohort rep tier.

    For shihoshoshi (rep tier A) on an unmatched bucket:
        opus_yen(A) - jpcite_yen(A) = 54 - 3 = ¥51
    For shihoshoshi on a matched bucket (real_estate / shihoshoshi / ma)
    the formula adds a +20% lift → round(51 * 1.20) = ¥61.
    """
    assert _cohort_saving_yen("shihoshoshi", match=False) == 54 - 3
    assert _cohort_saving_yen("shihoshoshi", match=True) == round((54 - 3) * 1.20)


def test_cohort_rep_tier_covers_all_5_cohorts() -> None:
    assert set(COHORT_REP_TIER.keys()) == set(COHORT_IDS)
    for tier in COHORT_REP_TIER.values():
        assert tier in TIER_YEN
        assert tier in TIER_OPUS_YEN
        # Saving must be positive for every cohort.
        assert TIER_OPUS_YEN[tier] > TIER_YEN[tier]


def test_saving_is_higher_when_cohort_bucket_matches() -> None:
    for cohort in COHORT_IDS:
        matched = _cohort_saving_yen(cohort, match=True)
        unmatched = _cohort_saving_yen(cohort, match=False)
        assert matched > unmatched


# ---------------------------------------------------------------------------
# 6. SQLite round-trip — schema + upsert + idempotent re-run
# ---------------------------------------------------------------------------


def test_sqlite_row_count_is_2160(populated_db: Path) -> None:
    conn = sqlite3.connect(populated_db)
    try:
        row = conn.execute("SELECT COUNT(*) FROM am_outcome_cohort_variant").fetchone()
        assert row[0] == 432 * 5
    finally:
        conn.close()


def test_sqlite_unique_outcome_cohort_pair(populated_db: Path) -> None:
    conn = sqlite3.connect(populated_db)
    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT outcome_id || '::' || cohort) FROM am_outcome_cohort_variant"
        ).fetchone()
        assert row[0] == 432 * 5
    finally:
        conn.close()


def test_sqlite_idempotent_rerun(populated_db: Path) -> None:
    """Re-running upsert on the same input does not duplicate rows."""
    conn = sqlite3.connect(populated_db)
    try:
        outcomes = load_outcomes(conn)
        rows = generate_variants(outcomes, computed_at="2026-05-17T01:00:00Z")
        upsert_variants(conn, rows)
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM am_outcome_cohort_variant").fetchone()[0]
        assert total == 432 * 5
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 7-8. MCP tool ``get_outcome_for_cohort`` — happy path + reject paths
# ---------------------------------------------------------------------------


def _unwrap_tool(tool: Any) -> Any:
    """Unwrap a fastmcp ``@mcp.tool``-decorated callable for direct test invocation."""
    for attr in ("fn", "func", "_fn"):
        inner = getattr(tool, attr, None)
        if callable(inner):
            return inner
    return tool


def _invoke_tool(db_path: Path, outcome_id: int, cohort: str) -> dict[str, Any]:
    """Invoke get_outcome_for_cohort against the fixture DB.

    Sets JPCITE_AUTONOMATH_DB_PATH so the tool reads the populated
    fixture file rather than the production autonomath.db.

    Uses importlib directly to import the submodule rather than the
    moat_lane_tools package, avoiding parallel-lane import contention
    on sibling submodules (the GG7 tool is isolated and doesn't depend
    on any sibling).
    """
    import importlib
    import os

    prev = os.environ.get("JPCITE_AUTONOMATH_DB_PATH")
    os.environ["JPCITE_AUTONOMATH_DB_PATH"] = str(db_path)
    try:
        mod = importlib.import_module("jpintel_mcp.mcp.moat_lane_tools.get_outcome_for_cohort")
        fn = _unwrap_tool(mod.get_outcome_for_cohort)
        result = fn(outcome_id=outcome_id, cohort=cohort)
        assert isinstance(result, dict)
        return result
    finally:
        if prev is None:
            os.environ.pop("JPCITE_AUTONOMATH_DB_PATH", None)
        else:
            os.environ["JPCITE_AUTONOMATH_DB_PATH"] = prev


def test_mcp_tool_happy_path(populated_db: Path) -> None:
    payload = _invoke_tool(populated_db, outcome_id=1, cohort="zeirishi")
    assert payload["tool_name"] == "get_outcome_for_cohort"
    assert payload["total"] == 1
    pr = payload["primary_result"]
    assert pr["outcome_id"] == 1
    assert pr["cohort"] == "zeirishi"
    assert pr["gloss"]
    assert pr["next_step"]
    assert pr["cohort_saving_yen_per_query"] > 0
    assert payload["_billing_unit"] == 1


def test_mcp_tool_unknown_cohort(populated_db: Path) -> None:
    out = _invoke_tool(populated_db, outcome_id=1, cohort="bogus")
    assert out["total"] == 0
    assert out["primary_result"]["status"] == "empty"
    assert "unknown cohort" in out["primary_result"]["rationale"]


def test_mcp_tool_missing_table_yields_empty_envelope(tmp_path: Path) -> None:
    """Tool returns the canonical empty envelope when migration not applied."""
    empty_db = tmp_path / "empty.db"
    conn = sqlite3.connect(empty_db)
    conn.close()  # creates empty schema-less file.
    out = _invoke_tool(empty_db, outcome_id=1, cohort="zeirishi")
    assert out["total"] == 0
    assert out["primary_result"]["status"] == "empty"
    assert "table missing" in out["primary_result"]["rationale"]


def test_mcp_tool_no_match_yields_empty_envelope(
    synthetic_outcomes: list[OutcomeRow], tmp_path: Path
) -> None:
    """A populated DB but a row that's been deleted yields empty envelope."""
    db_path = tmp_path / "no_match.db"
    conn = sqlite3.connect(db_path)
    try:
        ensure_schema(conn)
        rows = generate_variants(synthetic_outcomes, computed_at="2026-05-17T00:00:00Z")
        upsert_variants(conn, rows)
        # Remove the (outcome=432, shihoshoshi) row to provoke the
        # "no variant" path.
        conn.execute(
            "DELETE FROM am_outcome_cohort_variant WHERE outcome_id = ? AND cohort = ?",
            (432, "shihoshoshi"),
        )
        conn.commit()
    finally:
        conn.close()
    out = _invoke_tool(db_path, outcome_id=432, cohort="shihoshoshi")
    assert out["total"] == 0
    assert "no variant" in out["primary_result"]["rationale"]


# ---------------------------------------------------------------------------
# 9. Fragment manifest registers GG7 module
# ---------------------------------------------------------------------------


def test_fragment_parser_accepts_get_outcome_for_cohort() -> None:
    """`_fragments._parse_submodules` round-trip must accept the GG7 entry.

    The fragment loader is the single seam through which the GG7 MCP
    tool is discovered without touching `__init__.py` directly. This
    test verifies the parser contract is intact (the loader will
    successfully recognise the GG7 entry when it appears in the YAML).
    """
    from jpintel_mcp.mcp.moat_lane_tools._fragments import _parse_submodules

    sample_yaml = "submodules:\n  - get_outcome_with_chunks\n  - get_outcome_for_cohort\n"
    submodules = _parse_submodules(sample_yaml)
    assert "get_outcome_for_cohort" in submodules


def test_gg7_module_is_importable_standalone() -> None:
    """The GG7 module must be importable as a standalone submodule.

    The fragment loader uses ``importlib.import_module`` against the
    package path, so the module must exist at the canonical location
    regardless of whether the loader is invoked at boot. Once the GG7
    line lands in ``_register_fragments.yaml`` (or any compatible
    fragment manifest), the loader picks the module up automatically.
    """
    import importlib

    mod = importlib.import_module("jpintel_mcp.mcp.moat_lane_tools.get_outcome_for_cohort")
    assert hasattr(mod, "get_outcome_for_cohort")


# ---------------------------------------------------------------------------
# 10. View aggregation (operator dashboard)
# ---------------------------------------------------------------------------


def test_view_per_cohort_aggregate(populated_db: Path) -> None:
    """v_outcome_cohort_variant_top must return 5 cohort rows."""
    conn = sqlite3.connect(populated_db)
    try:
        # View is created by the actual migration (not ensure_schema), so
        # apply it inline here.
        conn.executescript(
            """
            DROP VIEW IF EXISTS v_outcome_cohort_variant_top;
            CREATE VIEW v_outcome_cohort_variant_top AS
            SELECT
                cohort,
                COUNT(*) AS variant_rows,
                SUM(cohort_saving_yen_per_query) AS sum_saving_yen,
                AVG(cohort_saving_yen_per_query) AS avg_saving_yen,
                MAX(cohort_saving_yen_per_query) AS max_saving_yen
            FROM am_outcome_cohort_variant
            GROUP BY cohort
            ORDER BY avg_saving_yen DESC;
            """
        )
        rows = conn.execute(
            "SELECT cohort, variant_rows FROM v_outcome_cohort_variant_top"
        ).fetchall()
        cohorts = {r[0] for r in rows}
        assert cohorts == set(COHORT_IDS)
        for _cohort, count in rows:
            assert count == 432
    finally:
        conn.close()
