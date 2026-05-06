"""DEEP-64 identity_confidence golden-set runner — 1,200 entries.

Contract
--------
- Load ``tests/fixtures/identity_confidence_golden.yaml``
  (1,200 entries = 200 samples × 6 axes; deterministic seed=20260507).
- For each entry, compute the DEEP-18 identity_confidence score via
  ``jpintel_mcp.api._identity_confidence.score`` (provisional calculator;
  spec target is ``db/identity_confidence.py``).
- Assert score lies in ``[expected_confidence_min, expected_confidence_max]``.
- Build a per-axis confusion matrix (in-range / over / under).
- Gate on:
    * axis 1 (houjin_bangou_exact) accuracy = 100% (DEEP-64 §5 (2) hard floor).
    * axes 2-4 accuracy >= 92% (DEEP-64 §5 (2)).
    * axes 5-6 accuracy >= 88% (DEEP-64 §5 (2) low-band tolerance).
    * overall accuracy > 90% (DEEP-64 §5 (2)).
- AST-scan the fixture, generator, calculator and this file for LLM SDK imports
  (DEEP-64 §5 (4)).

Spec source
-----------
``tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_64_identity_confidence_golden_set.md``

No-LLM invariant
----------------
This file imports ``ast`` + ``pathlib`` + ``pytest`` + ``yaml`` +
``jpintel_mcp.api._identity_confidence`` only. The calculator imports stdlib
``re`` + ``unicodedata``. Both are AST-scanned in
``test_no_llm_imports_in_chain`` for safety.
"""

from __future__ import annotations

import ast
import pathlib
from collections import defaultdict
from typing import Any

import pytest
import yaml

from jpintel_mcp.api._identity_confidence import AXIS_SCORE, score

# ---------------------------------------------------------------------------
# Paths + constants
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
GOLDEN_PATH = REPO_ROOT / "tests" / "fixtures" / "identity_confidence_golden.yaml"
GENERATOR_PATH = REPO_ROOT / "scripts" / "ops" / "generate_identity_confidence_golden.py"
CALCULATOR_PATH = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "_identity_confidence.py"
THIS_FILE = pathlib.Path(__file__).resolve()

PER_AXIS_TARGET = 200
TOTAL_TARGET = 1200

# DEEP-64 §5 (2)
AXIS_ACCURACY_FLOOR = {
    "houjin_bangou_exact": 1.00,  # axis 1 must be 100%
    "kana_normalized": 0.92,
    "legal_form_variant": 0.92,
    "partial_with_address": 0.92,
    "partial_only": 0.88,
    "alias_only": 0.88,
}
OVERALL_ACCURACY_FLOOR = 0.90

FORBIDDEN_LLM_MODULES = {
    "anthropic",
    "openai",
    "google.generativeai",
    "claude_agent_sdk",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _load_corpus() -> list[dict[str, Any]]:
    raw = GOLDEN_PATH.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    assert isinstance(parsed, list), "corpus must be a YAML sequence"
    return parsed


@pytest.fixture(scope="module")
def corpus() -> list[dict[str, Any]]:
    return _load_corpus()


def _entry_to_candidate(entry: dict[str, Any]) -> dict[str, Any]:
    """Project a fixture entry into the score()-compatible candidate dict."""
    cand: dict[str, Any] = {}
    if entry.get("candidate_houjin_bangou"):
        cand["houjin_bangou"] = entry["candidate_houjin_bangou"]
    if entry.get("candidate_houjin_name"):
        cand["houjin_name"] = entry["candidate_houjin_name"]
    addr = entry.get("address_match")
    cand["address_match"] = addr is True
    if entry.get("alias_only") is True:
        cand["alias_only"] = True
    return cand


# ---------------------------------------------------------------------------
# Structural assertions (DEEP-64 §5 (1))
# ---------------------------------------------------------------------------


def test_corpus_has_1200_entries(corpus: list[dict[str, Any]]) -> None:
    assert len(corpus) == TOTAL_TARGET, f"expected {TOTAL_TARGET}, got {len(corpus)}"


def test_corpus_has_unique_ids(corpus: list[dict[str, Any]]) -> None:
    ids = [e["id"] for e in corpus]
    assert len(set(ids)) == len(ids), "duplicate id present"


def test_corpus_per_axis_count(corpus: list[dict[str, Any]]) -> None:
    counts: dict[str, int] = defaultdict(int)
    for e in corpus:
        counts[e["axis"]] += 1
    expected_axes = set(AXIS_SCORE.keys())
    assert set(counts.keys()) == expected_axes, (
        f"axis set mismatch: {set(counts.keys())} vs {expected_axes}"
    )
    for axis, c in counts.items():
        assert c == PER_AXIS_TARGET, f"axis {axis} has {c}, expected {PER_AXIS_TARGET}"


def test_corpus_schema_keys(corpus: list[dict[str, Any]]) -> None:
    """Every entry has the required keys (DEEP-64 §1 metadata schema)."""
    required = {
        "id",
        "axis",
        "query",
        "expected_confidence_min",
        "expected_confidence_max",
        "cohort",
        "address_match",
        "notes",
    }
    for e in corpus:
        missing = required - set(e.keys())
        assert not missing, f"entry {e.get('id')} missing keys {missing}"
        # Each entry must have at least one candidate_* identifier
        assert "candidate_houjin_bangou" in e or "candidate_houjin_name" in e, (
            f"entry {e['id']} has no candidate_* field"
        )


def test_expected_ranges_match_axis_table(corpus: list[dict[str, Any]]) -> None:
    """Each entry's expected range must match the DEEP-64 §1 table."""
    table = {
        "houjin_bangou_exact": (0.99, 1.00),
        "kana_normalized": (0.90, 0.97),
        "legal_form_variant": (0.85, 0.95),
        "partial_with_address": (0.78, 0.90),
        "partial_only": (0.55, 0.72),
        "alias_only": (0.45, 0.62),
    }
    for e in corpus:
        lo, hi = table[e["axis"]]
        assert e["expected_confidence_min"] == pytest.approx(lo), e["id"]
        assert e["expected_confidence_max"] == pytest.approx(hi), e["id"]


# ---------------------------------------------------------------------------
# Per-axis accuracy assertions (DEEP-64 §5 (2))
# ---------------------------------------------------------------------------


def _evaluate(corpus: list[dict[str, Any]]) -> dict[str, Any]:
    """Run scorer over corpus, return per-axis confusion + global rate."""
    per_axis: dict[str, dict[str, int]] = defaultdict(
        lambda: {"in_range": 0, "over": 0, "under": 0, "total": 0}
    )
    misses: list[dict[str, Any]] = []
    for e in corpus:
        cand = _entry_to_candidate(e)
        s, axis_pred, _axes = score(e["query"], cand)
        bucket = per_axis[e["axis"]]
        bucket["total"] += 1
        lo = float(e["expected_confidence_min"])
        hi = float(e["expected_confidence_max"])
        if lo <= s <= hi:
            bucket["in_range"] += 1
        elif s > hi:
            bucket["over"] += 1
            misses.append({**e, "score": s, "axis_pred": axis_pred})
        else:
            bucket["under"] += 1
            misses.append({**e, "score": s, "axis_pred": axis_pred})
    return {"per_axis": per_axis, "misses": misses}


def test_axis_1_houjin_bangou_exact_100_percent(
    corpus: list[dict[str, Any]],
) -> None:
    """DEEP-64 §5 (2) — axis 1 MUST hit 100% (else DEEP-18 全壊)."""
    res = _evaluate(corpus)
    bucket = res["per_axis"]["houjin_bangou_exact"]
    accuracy = bucket["in_range"] / bucket["total"]
    assert accuracy == 1.0, (
        f"axis 1 (houjin_bangou_exact) accuracy = {accuracy:.4f} (must be 1.0); "
        f"in_range={bucket['in_range']} over={bucket['over']} under={bucket['under']}"
    )


def test_per_axis_accuracy_floor(corpus: list[dict[str, Any]]) -> None:
    """DEEP-64 §5 (2) — each axis must clear its accuracy floor."""
    res = _evaluate(corpus)
    failures: list[str] = []
    for axis, floor in AXIS_ACCURACY_FLOOR.items():
        bucket = res["per_axis"][axis]
        accuracy = bucket["in_range"] / bucket["total"]
        if accuracy < floor:
            failures.append(
                f"axis {axis}: {accuracy:.4f} < floor {floor:.2f} "
                f"(in_range={bucket['in_range']} over={bucket['over']} "
                f"under={bucket['under']})"
            )
    if failures:
        sample_misses = res["misses"][:5]
        miss_strs = [
            f"  - {m['id']} axis={m['axis']} score={m['score']:.3f} "
            f"range=[{m['expected_confidence_min']},{m['expected_confidence_max']}]"
            for m in sample_misses
        ]
        msg = "\n".join(["per-axis accuracy floor breaches:", *failures, *miss_strs])
        raise AssertionError(msg)


def test_overall_accuracy_above_90_percent(corpus: list[dict[str, Any]]) -> None:
    """DEEP-64 §5 (2) — overall accuracy > 90%."""
    res = _evaluate(corpus)
    total = sum(b["total"] for b in res["per_axis"].values())
    in_range = sum(b["in_range"] for b in res["per_axis"].values())
    accuracy = in_range / total
    assert accuracy >= OVERALL_ACCURACY_FLOOR, (
        f"overall accuracy {accuracy:.4f} below floor {OVERALL_ACCURACY_FLOOR}"
    )


# ---------------------------------------------------------------------------
# Per-cohort matrix (DEEP-64 §5 (3) — 4-cell axis × cohort artifact)
# ---------------------------------------------------------------------------


def test_per_cohort_accuracy(corpus: list[dict[str, Any]]) -> None:
    """DEEP-64 §5 (3) — kabushiki / godo / yugen / ippan / sole each >= 75%."""
    by_cohort: dict[str, dict[str, int]] = defaultdict(lambda: {"in_range": 0, "total": 0})
    for e in corpus:
        cand = _entry_to_candidate(e)
        s, _axis, _axes = score(e["query"], cand)
        bucket = by_cohort[e["cohort"]]
        bucket["total"] += 1
        lo = float(e["expected_confidence_min"])
        hi = float(e["expected_confidence_max"])
        if lo <= s <= hi:
            bucket["in_range"] += 1
    failures = []
    for cohort, bucket in by_cohort.items():
        if bucket["total"] < 1:
            continue
        accuracy = bucket["in_range"] / bucket["total"]
        if accuracy < 0.75:
            failures.append(
                f"cohort {cohort}: {accuracy:.4f} < 0.75 "
                f"(in_range={bucket['in_range']}/{bucket['total']})"
            )
    assert not failures, "\n".join(["per-cohort accuracy floor breaches:", *failures])


# ---------------------------------------------------------------------------
# No-LLM invariant (DEEP-64 §5 (4))
# ---------------------------------------------------------------------------


def _module_imports(path: pathlib.Path) -> set[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module.split(".")[0])
    return mods


def test_no_llm_imports_in_chain() -> None:
    """DEEP-64 §5 (4) — fixture chain MUST have zero LLM SDK imports."""
    paths = [GENERATOR_PATH, CALCULATOR_PATH, THIS_FILE]
    forbidden_root = {m.split(".")[0] for m in FORBIDDEN_LLM_MODULES}
    for p in paths:
        mods = _module_imports(p)
        violation = mods & forbidden_root
        assert not violation, f"{p}: forbidden imports {violation}"


# ---------------------------------------------------------------------------
# Diagnostic summary (always-pass — for stdout calibration feedback loop)
# ---------------------------------------------------------------------------


def test_diagnostic_summary(
    corpus: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    """Emit per-axis confusion matrix to stdout for the calibration loop.

    Always passes. Use ``pytest -s`` to view.
    """
    res = _evaluate(corpus)
    print("\n--- DEEP-64 identity_confidence golden-set summary ---")
    for axis in (
        "houjin_bangou_exact",
        "kana_normalized",
        "legal_form_variant",
        "partial_with_address",
        "partial_only",
        "alias_only",
    ):
        b = res["per_axis"][axis]
        accuracy = b["in_range"] / b["total"] if b["total"] else 0.0
        print(
            f"  {axis:>22s}: in={b['in_range']:>3d}/{b['total']:>3d} "
            f"({accuracy * 100:5.1f}%) over={b['over']:>3d} under={b['under']:>3d}"
        )
    total = sum(b["total"] for b in res["per_axis"].values())
    in_range = sum(b["in_range"] for b in res["per_axis"].values())
    print(f"  {'OVERALL':>22s}: {in_range}/{total} ({in_range / total * 100:.2f}%)")
    # capsys is bound just so pytest renders captured output; this test
    # asserts nothing structural.
    assert True
