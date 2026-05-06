"""Composite benchmark guard.

Asserts that every row in benchmarks/composite_vs_naive/results.jsonl is
classified by result_kind (real / synth / fallback), and that public copy
publishes both real_calls_total and synthesized_count side-by-side, and
that no public surface claims "100% real" while synthesized_count > 0.

Spec source:
- ``tools/offline/_inbox/value_growth_dual/_m00_implementation/M00_C_proof_hardening/DC_01_jcrb_seed_synth_verified_guards.md``
- SYNTHESIS §8.6 (real_calls_total / synthesized_count separation)

No LLM provider call. Pure file inspection.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
RESULTS_JSONL = REPO / "benchmarks" / "composite_vs_naive" / "results.jsonl"
PUBLIC_MD = REPO / "docs" / "integrations" / "composite-bench-results.md"
BENCHMARK_HTML = REPO / "site" / "benchmark" / "index.html"

ALLOWED_RESULT_KINDS = {"real", "synth", "fallback"}
ALLOWED_COLUMN_KINDS = {"real", "synth"}

ALL_REAL_CLAIM_PATTERNS = [
    re.compile(r"100\s*%\s*実測"),
    re.compile(r"全行\s*実測"),
    re.compile(r"all\s+rows?\s+are\s+real", re.IGNORECASE),
    re.compile(r"no\s+synth", re.IGNORECASE),
    re.compile(r"全件\s*live"),
]

REAL_CALLS_TOTAL_RE = re.compile(r"real_calls_total\s*[:=]\s*(\d+)")
SYNTHESIZED_COUNT_RE = re.compile(r"synthesized_count\s*[:=]\s*(\d+)")


def _load_rows() -> list[dict]:
    if not RESULTS_JSONL.exists():
        pytest.skip(f"{RESULTS_JSONL} missing — run benchmarks/composite_vs_naive/run.py")
    out: list[dict] = []
    for line in RESULTS_JSONL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def test_composite_results_rows_have_result_kind() -> None:
    """Every row must carry result_kind in {real, synth, fallback}."""
    rows = _load_rows()
    if not rows:
        pytest.skip("no rows in results.jsonl")
    bad = [
        r.get("scenario", "?") + "/" + str(r.get("program_id", "?"))
        for r in rows
        if r.get("result_kind") not in ALLOWED_RESULT_KINDS
    ]
    assert not bad, (
        f"{len(bad)} rows missing or invalid result_kind (first 5): {bad[:5]}. "
        f"Run scripts/etl/annotate_composite_result_kind.py to backfill. "
        f"Allowed values: {sorted(ALLOWED_RESULT_KINDS)}."
    )


def test_composite_column_level_kinds_present() -> None:
    """For real classifications, every measured column must carry its own
    kind so wall_ms_kind != tokens_kind != cost_kind is detectable."""
    rows = _load_rows()
    if not rows:
        pytest.skip("no rows")
    required_columns = {"wall_ms_kind", "tokens_kind", "cost_kind"}
    bad: list[tuple[str, set[str]]] = []
    for r in rows:
        rk = r.get("result_kind")
        if rk not in ALLOWED_RESULT_KINDS:
            continue
        missing_cols = required_columns - r.keys()
        if missing_cols:
            bad.append((r.get("scenario", "?") + "/" + str(r.get("program_id", "?")), missing_cols))
            continue
        bad_vals = {c for c in required_columns if r.get(c) not in ALLOWED_COLUMN_KINDS}
        if bad_vals:
            bad.append((r.get("scenario", "?") + "/" + str(r.get("program_id", "?")), bad_vals))
    assert not bad, (
        f"{len(bad)} rows missing column-level kinds (first 5): {bad[:5]}. "
        f"Allowed column-kind values: {sorted(ALLOWED_COLUMN_KINDS)}."
    )


def test_composite_summary_publishes_real_and_synth_counts() -> None:
    """Public summary surface must publish both real_calls_total and
    synthesized_count, machine-readable."""
    if not PUBLIC_MD.exists():
        pytest.skip(f"{PUBLIC_MD} missing")
    md = PUBLIC_MD.read_text(encoding="utf-8")
    assert REAL_CALLS_TOTAL_RE.search(md), (
        f"{PUBLIC_MD.name} does not publish real_calls_total. "
        f"Expected literal `real_calls_total: <int>` somewhere in the body."
    )
    assert SYNTHESIZED_COUNT_RE.search(md), (
        f"{PUBLIC_MD.name} does not publish synthesized_count. "
        f"Expected literal `synthesized_count: <int>` somewhere in the body."
    )


def test_composite_no_100_percent_real_claim_when_synth_positive() -> None:
    """If synthesized_count > 0 in the jsonl, public copy must not assert
    "100% real" / "全行実測" / equivalent outside data-result-kind=real scope."""
    rows = _load_rows()
    if not rows:
        pytest.skip("no rows")
    synth_count = sum(1 for r in rows if r.get("result_kind") != "real")
    if synth_count == 0:
        # nothing to enforce
        return
    surfaces: list[tuple[str, str]] = []
    if PUBLIC_MD.exists():
        surfaces.append((str(PUBLIC_MD.relative_to(REPO)), PUBLIC_MD.read_text(encoding="utf-8")))
    if BENCHMARK_HTML.exists():
        surfaces.append(
            (str(BENCHMARK_HTML.relative_to(REPO)), BENCHMARK_HTML.read_text(encoding="utf-8"))
        )
    bad: list[tuple[str, str]] = []
    for surface_name, body in surfaces:
        for pat in ALL_REAL_CLAIM_PATTERNS:
            m = pat.search(body)
            if m:
                bad.append((surface_name, m.group(0)))
    assert not bad, (
        f"synthesized_count={synth_count} but public copy still claims "
        f"all-real (first 5 of {len(bad)}): {bad[:5]}. "
        f"Either qualify the claim with N=<real_count> or change the wording."
    )


def test_composite_real_calls_total_matches_jsonl() -> None:
    """When public surface publishes real_calls_total, the integer must
    match the count of rows where result_kind == 'real' in the jsonl."""
    if not PUBLIC_MD.exists():
        pytest.skip(f"{PUBLIC_MD} missing")
    md = PUBLIC_MD.read_text(encoding="utf-8")
    m = REAL_CALLS_TOTAL_RE.search(md)
    if not m:
        pytest.skip("public surface missing real_calls_total — covered by other test")
    declared = int(m.group(1))
    rows = _load_rows()
    actual = sum(1 for r in rows if r.get("result_kind") == "real")
    assert declared == actual, (
        f"public real_calls_total={declared} does not match jsonl count {actual}. "
        f"results.jsonl is the source of truth — regenerate the markdown."
    )
