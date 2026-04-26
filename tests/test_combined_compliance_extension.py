"""Tests for P0.3 — `combined_compliance_check` dark-inventory extension.

Design doc: analysis_wave18/_p03_combined_compliance_extension_2026-04-25.md

Three mandatory cases:

  1. existing jpi_exclusion_rules pair path is preserved (legacy call shape,
     no `candidate_program_ids` → response has NO `compat_matrix` /
     `combo_calculator` / `data_quality` keys; byte-equivalent acceptance gate
     of the design doc §6).
  2. `candidate_program_ids=[a, b]` activates the compat_matrix pass — the
     pair is looked up in `am_compat_matrix` in its native key shape (no
     silent rekeying) and surfaced under `compat_matrix.pairs[]`.
  3. when the candidate pair lands in the 4,849-row `compat_status='unknown'`
     bucket, `data_quality.compat_unknown_bucket_pct` is surfaced as a
     non-zero float — honest dark-inventory disclosure (silent miss = 詐欺
     risk per CLAUDE.md / memory).

Run:

    .venv/bin/python -m pytest tests/test_combined_compliance_extension.py \
        tests/test_rule_engine.py -x --tb=short
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"
_DB_PATH = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_DB)))

if not _DB_PATH.exists():
    pytest.skip(
        f"autonomath.db ({_DB_PATH}) not present; skipping P0.3 extension tests. "
        "Set AUTONOMATH_DB_PATH to point at a snapshot.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")

# Server import wires the @mcp.tool decorator and gives us the underlying
# function via the module attribute. We DO NOT go through FastMCP dispatch —
# the goal is unit-level coverage of the extension code path.
from jpintel_mcp.mcp import server  # noqa: E402

# `combined_compliance_check` is wrapped by @_with_mcp_telemetry and @mcp.tool.
# The wrappers stack as: mcp.tool → telemetry → original function. We reach the
# raw callable via the FastMCP tool registry; if structure changes the test
# fixture below will surface a clear NameError.
_TOOL = server.combined_compliance_check


def _profile() -> dict[str, Any]:
    """Minimal business profile — no tax/bid filtering, just enough for the call."""
    return {
        "prefecture": "東京都",
        "industry_jsic": "E",
        "annual_revenue_yen": 50_000_000,
        "business_type": "corporation",
        "employees": 10,
    }


def _find_pair_with_status(status: str) -> tuple[str, str]:
    """Find a real (program_a_id, program_b_id) pair with the given compat_status."""
    conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT program_a_id, program_b_id FROM am_compat_matrix "
            "WHERE compat_status = ? LIMIT 1",
            (status,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        pytest.skip(f"no am_compat_matrix row with status={status!r}")
    return row[0], row[1]


# ---------------------------------------------------------------------------
# Case 1 — legacy path preserved: no candidate_program_ids → no new sections.
# ---------------------------------------------------------------------------


def test_legacy_path_preserves_existing_shape_when_no_candidate_ids():
    """When `candidate_program_ids` is None (or empty), the response MUST NOT
    contain `compat_matrix` / `combo_calculator` / `data_quality` keys —
    the P0.3 §6 acceptance gate (byte-equivalent legacy shape).
    """
    res = _TOOL(
        business_profile=_profile(),
        program_unified_id=None,
        include_tax_eval=False,
        top_bids=0,
        candidate_program_ids=None,
    )
    # Tool name varies through envelope wrapper; we accept either dict path.
    assert isinstance(res, dict)
    # The three new sections MUST be absent on the legacy path.
    assert "compat_matrix" not in res, (
        f"legacy call (no candidate_program_ids) leaked compat_matrix key: {res.keys()}"
    )
    assert "combo_calculator" not in res
    assert "data_quality" not in res
    # The existing keys remain.
    assert "exclusion_check" in res
    assert "tax_evaluation" in res
    assert "relevant_bids" in res
    assert "summary" in res
    # Summary must NOT mention compat_pairs / combo_matches.
    assert "compat_pairs" not in res["summary"]
    assert "combo_matches" not in res["summary"]

    # Same when candidate_program_ids is an empty list (len < 2 short-circuit).
    res2 = _TOOL(
        business_profile=_profile(),
        program_unified_id=None,
        include_tax_eval=False,
        top_bids=0,
        candidate_program_ids=[],
    )
    assert "compat_matrix" not in res2
    assert "combo_calculator" not in res2
    assert "data_quality" not in res2

    # Length-1 also short-circuits (pairs require ≥2).
    res3 = _TOOL(
        business_profile=_profile(),
        program_unified_id=None,
        include_tax_eval=False,
        top_bids=0,
        candidate_program_ids=["program:base:3b5ec4f12e"],
    )
    assert "compat_matrix" not in res3


# ---------------------------------------------------------------------------
# Case 2 — candidate_program_ids ≥ 2 activates compat_matrix pass.
# ---------------------------------------------------------------------------


def test_candidate_program_ids_triggers_compat_matrix_lookup():
    """Pass a real (a, b) pair from am_compat_matrix → response surfaces it
    under `compat_matrix.pairs[]` with the matrix's native key shape preserved
    (no rekeying to UNI-*).
    """
    pa, pb = _find_pair_with_status("compatible")
    res = _TOOL(
        business_profile=_profile(),
        program_unified_id=None,
        include_tax_eval=False,
        top_bids=0,
        candidate_program_ids=[pa, pb],
    )
    assert "compat_matrix" in res, (
        f"candidate_program_ids=[a,b] should surface compat_matrix; got {res.keys()}"
    )
    cm = res["compat_matrix"]
    # Must be a dict with the design's required keys.
    for k in ("pairs", "incompatible_count", "case_by_case_count",
              "unknown_count", "missing_count"):
        assert k in cm, f"compat_matrix missing required key {k!r}; got {cm.keys()}"
    # Exactly one pair was passed (binomial(2,2)=1) so pairs[] has exactly one
    # entry on a hit, zero if missing. The compat lookup MUST succeed for a
    # known compatible pair sourced from the live matrix.
    assert cm["missing_count"] == 0, (
        f"known-compatible pair reported missing — lookup logic regression: {cm}"
    )
    assert len(cm["pairs"]) == 1, (
        f"expected exactly 1 pair entry for binomial(2,2), got {len(cm['pairs'])}"
    )
    found = cm["pairs"][0]
    # The native key shape is preserved by the read pass (no rekeying). The
    # MCP envelope's INV-22 景表法 sanitizer may rewrite 6-digit substrings
    # as <phone-redacted> in the surface response, but the lookup itself uses
    # the raw strings — proven by the successful match (missing_count == 0
    # AND status correctly resolved to 'compatible' below).
    assert found["compat_status"] == "compatible"
    # Both id fields are echoed (sanitized or not).
    assert isinstance(found["program_a_id"], str) and found["program_a_id"]
    assert isinstance(found["program_b_id"], str) and found["program_b_id"]
    # combo_calculator section also surfaced.
    assert "combo_calculator" in res
    assert "matched_combos" in res["combo_calculator"]
    assert "unmatched_count" in res["combo_calculator"]
    # Summary updated to mention compat_pairs / combo_matches.
    assert "compat_pairs=" in res["summary"]
    assert "combo_matches=" in res["summary"]


# ---------------------------------------------------------------------------
# Case 3 — unknown bucket honesty surface: data_quality.compat_unknown_bucket_pct.
# ---------------------------------------------------------------------------


def test_unknown_bucket_pct_is_honestly_surfaced():
    """When the candidate pair is in the unknown bucket, `data_quality.
    compat_unknown_bucket_pct` must report the GLOBAL ratio of unknown rows in
    am_compat_matrix as a positive float (verified ≈9.93% on 2026-04-25).
    The pair's compat_status MUST also surface as 'unknown' inside pairs[].
    """
    pa, pb = _find_pair_with_status("unknown")
    res = _TOOL(
        business_profile=_profile(),
        program_unified_id=None,
        include_tax_eval=False,
        top_bids=0,
        candidate_program_ids=[pa, pb],
    )
    # data_quality must be present and carry the honesty surface.
    assert "data_quality" in res, (
        f"candidate_program_ids ≥ 2 must surface data_quality; got {res.keys()}"
    )
    dq = res["data_quality"]
    assert "compat_unknown_bucket_pct" in dq
    pct = dq["compat_unknown_bucket_pct"]
    assert isinstance(pct, (int, float)), (
        f"compat_unknown_bucket_pct must be numeric, got {type(pct).__name__}"
    )
    # 4,849 / 48,815 ≈ 9.93%. Allow a small tolerance band so the test stays
    # green as the matrix grows. We require a strictly positive non-trivial
    # value — silent zero would be the failure mode the test guards against.
    assert pct > 5.0, (
        f"compat_unknown_bucket_pct={pct} is suspiciously low — unknown bucket "
        "should surface ~9.93% on the 2026-04-25 snapshot. Silent zero would "
        "be a 詐欺 risk regression."
    )
    assert pct < 30.0, (
        f"compat_unknown_bucket_pct={pct} is too high; check matrix integrity."
    )
    # exclusion_join_coverage_pct also present (P0.3 §6 design — both keys
    # must be in data_quality even when one is honestly 0.0).
    assert "exclusion_join_coverage_pct" in dq

    # The unknown pair itself must surface inside pairs[] with status='unknown'.
    # We don't compare exact id strings (the MCP envelope's 景表法 sanitizer
    # may rewrite 6-digit substrings); status-driven assertion is sufficient.
    cm = res["compat_matrix"]
    assert cm["missing_count"] == 0, (
        f"known-unknown-bucket pair reported missing — lookup regression: {cm}"
    )
    assert len(cm["pairs"]) == 1
    assert cm["pairs"][0]["compat_status"] == "unknown"
    # And the unknown_count summary must reflect ≥1.
    assert cm["unknown_count"] >= 1
