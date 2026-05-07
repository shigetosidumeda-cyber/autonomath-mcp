"""Tests for prerequisite_chain — R5 前提認定 chain MCP tool.

Covers the 3 mandatory cases from the design doc
(analysis_wave18/_r5_prerequisite_chain_2026-04-25.md):

  1. ものづくり補助金 加算 → 経営革新計画 認定 chain returns the curated
     bundle (10 prereqs incl. cert='経営革新計画 認定').
  2. Out-of-coverage program (not in the curated 1.6% bucket) → empty
     prerequisite_chain + data_quality.coverage_pct surfaced + caveat.
  3. depth>5 → realism warning fires (`現実的でない`).

Run:

    .venv/bin/python -m pytest tests/test_prerequisite_chain.py -x --tb=short
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"

_DB_PATH = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_DB)))

if not _DB_PATH.exists():
    pytest.skip(
        f"autonomath.db ({_DB_PATH}) not present; skipping prerequisite_chain tests. "
        "Set AUTONOMATH_DB_PATH to point at a snapshot.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_PREREQUISITE_CHAIN_ENABLED", "1")

# server must be imported first to break circular import.
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.prerequisite_chain_tool import (  # noqa: E402
    _BUNDLE_TOTAL_PROGRAMS,
    _COVERAGE_PCT,
    _PROGRAMS_TOTAL_CORPUS,
    _prerequisite_chain_impl,
)

# ---------------------------------------------------------------------------
# Test data discovery — find a real program_entity_id from
# am_prerequisite_bundle that contains a 'cert' or 'plan' entry mentioning
# 経営革新計画. We cannot hard-code a canonical_id because bundle expansion
# may renumber the IDs, but the 経営革新計画 認定 string is stable across
# the curated 8 rows.
# ---------------------------------------------------------------------------


def _find_program_with_keiei_kakushin() -> str:
    """Return a `program_entity_id` whose bundle includes the
    '経営革新計画 認定' prerequisite. Skip if the curated row has been
    renamed (in which case the test data is out of step with the design).
    """
    conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    try:
        row = conn.execute(
            """
            SELECT program_entity_id
              FROM am_prerequisite_bundle
             WHERE prerequisite_name LIKE '%経営革新計画%'
               AND prerequisite_kind IN ('cert', 'plan')
             LIMIT 1
            """,
        ).fetchone()
    finally:
        conn.close()
    if not row:
        pytest.skip(
            "no am_prerequisite_bundle row with 経営革新計画 found — "
            "curated bundle may have been edited."
        )
    return row[0]


# ---------------------------------------------------------------------------
# Case 1 — ものづくり補助金 加算 → 経営革新計画 認定 chain returned.
# ---------------------------------------------------------------------------


def test_prerequisite_chain_returns_keiei_kakushin_for_monodukuri():
    """A program in the curated bundle that lists 経営革新計画 認定 must
    surface that认定 in `prerequisite_chain` with a non-zero
    preparation_time_days and an attached rationale.
    """
    pid = _find_program_with_keiei_kakushin()
    res = _prerequisite_chain_impl(target_program_id=pid, depth=3)

    # No error envelope expected on a happy path.
    assert res.get("error") is None, f"unexpected error: {res.get('error')}"
    assert res["program_id"] == pid

    # Chain must include the 経営革新計画 認定 row.
    chain = res["prerequisite_chain"]
    assert chain, f"expected non-empty chain for {pid!r}"
    keiei_rows = [e for e in chain if "経営革新計画" in (e.get("name") or "")]
    assert keiei_rows, (
        f"expected at least one 経営革新計画 entry in chain for {pid!r}, "
        f"got names {[e.get('name') for e in chain]}"
    )
    keiei = keiei_rows[0]
    # cert / plan kind only — never doc / id.
    assert keiei["kind"] in (
        "cert",
        "plan",
    ), f"keiei prereq kind={keiei['kind']!r} (expected cert/plan)"
    # preparation_time_days must be a positive int (60 days for 経営革新計画).
    assert isinstance(keiei["preparation_time_days"], int)
    assert keiei["preparation_time_days"] > 0

    # Aggregates round-trip.
    assert res["total_preparation_time_days"] == sum(
        (e["preparation_time_days"] or 0) for e in chain
    )
    assert res["total_preparation_cost_yen"] == sum((e["preparation_cost_yen"] or 0) for e in chain)

    # data_quality is always surfaced — coverage_pct must equal the
    # constant declared in the tool module.
    dq = res["data_quality"]
    assert dq["coverage_pct"] == _COVERAGE_PCT
    assert dq["programs_with_bundle"] == _BUNDLE_TOTAL_PROGRAMS
    assert dq["programs_total"] == _PROGRAMS_TOTAL_CORPUS

    # Disclaimer present and mentions 一次資料 / 専門家.
    assert "_disclaimer" in res
    msg = res["_disclaimer"]
    assert "一次資料" in msg or "専門家" in msg or "公募要領" in msg


# ---------------------------------------------------------------------------
# Case 2 — out-of-coverage program → empty chain + coverage_pct surfaced.
# ---------------------------------------------------------------------------


def test_prerequisite_chain_outside_coverage_surfaces_caveat():
    """A program not in the curated bundle (98.4% of the corpus) must
    return an empty chain WITHOUT swallowing the partial-coverage signal.
    """
    pid = "program:nonexistent:fake_for_test_999999"
    res = _prerequisite_chain_impl(target_program_id=pid, depth=3)

    # No hard error — empty chain is a valid result.
    assert res.get("error") is None, (
        f"empty chain must not be a hard error envelope; got {res.get('error')}"
    )

    # Chain itself is empty.
    assert res["prerequisite_chain"] == []
    assert res["total"] == 0
    assert res["total_preparation_time_days"] == 0
    assert res["total_preparation_cost_yen"] == 0

    # data_quality surfaces the 1.6% coverage UNCONDITIONALLY — this is
    # the 景表法 fence that prevents silent miss being read as
    # "no prerequisites required".
    dq = res["data_quality"]
    assert dq["coverage_pct"] == _COVERAGE_PCT
    assert dq["coverage_pct"] == 1.6, (
        f"coverage_pct must remain 1.6% until bundle expansion; got {dq['coverage_pct']}"
    )
    # caveat field is present on empty results to make the gap explicit.
    assert "caveat" in dq
    assert "1.6" in dq["caveat"] or "coverage" in dq["caveat"].lower()

    # Disclaimer still present (always).
    assert "_disclaimer" in res


# ---------------------------------------------------------------------------
# Case 3 — depth>5 → realism warning fires.
# ---------------------------------------------------------------------------


def test_prerequisite_chain_excessive_depth_emits_warning():
    """depth>5 must trigger a `現実的でない` warning regardless of
    whether the chain is empty or populated. The realistic flag flips to
    False so callers can branch without parsing the warning string.
    """
    pid = _find_program_with_keiei_kakushin()
    res = _prerequisite_chain_impl(target_program_id=pid, depth=7)

    assert res.get("error") is None
    assert res["realistic"] is False, f"depth=7 must yield realistic=False; got {res['realistic']}"
    warnings = res["warnings"]
    assert warnings, "depth>5 must emit at least one warning"
    # At least one warning must reference depth realism in Japanese.
    depth_warning = [w for w in warnings if "現実的" in w or "5 段" in w]
    assert depth_warning, f"depth warning must mention 現実的 or 5 段; got {warnings}"
