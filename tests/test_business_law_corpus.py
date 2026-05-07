"""DEEP-63 業法 fence test corpus golden-set runner.

Contract
--------
- Load `tests/fixtures/business_law_golden_set.yaml` (50 violation + 50 clean,
  per-業法 7 軸 coverage).
- Run each sample through DEEP-38 detector
  (`jpintel_mcp.api._business_law_detector.detect_violations`).
- Compute per-業法 confusion matrix (TP / FP / FN / TN).
- Gate on:
    * overall true positive rate > 95% (>= 48/50)
    * overall false positive rate < 5%  (<=  2/50)
    * per-業法 coverage >= 7 violation + >= 7 clean for the 7 main laws
    * LLM-API import zero on detector module + this test file (AST scan)

Spec source
-----------
``tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_63_business_law_test_corpus.md``

No-LLM invariant
----------------
This file imports nothing beyond stdlib + pytest + yaml + the detector. The
``test_no_llm_in_corpus_runner`` case AST-scans both the detector module and
this test file to confirm. Any LLM SDK import here would be a regression.
"""

from __future__ import annotations

import ast
import pathlib
from collections import defaultdict
from typing import Any

import pytest
import yaml

from jpintel_mcp.api import _business_law_detector as bld

# ---------------------------------------------------------------------------
# Paths + constants
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
GOLDEN_SET_PATH = REPO_ROOT / "tests" / "fixtures" / "business_law_golden_set.yaml"
DETECTOR_PATH = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "_business_law_detector.py"
THIS_FILE = pathlib.Path(__file__).resolve()

# Per spec §5 acceptance criteria (3) + (4)
TP_RATE_FLOOR = 0.95
FP_RATE_CEILING = 0.05

EXPECTED_LAWS = (
    "税理士法",
    "弁護士法",
    "行政書士法",
    "司法書士法",
    "弁理士法",
    "社労士法",
    "公認会計士法",
)

FORBIDDEN_LLM_MODULES = {"anthropic", "openai", "claude_agent_sdk"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _load_corpus() -> list[dict[str, Any]]:
    raw = GOLDEN_SET_PATH.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    assert isinstance(parsed, list), "corpus must be a YAML sequence"
    return parsed


@pytest.fixture(scope="module")
def corpus() -> list[dict[str, Any]]:
    return _load_corpus()


@pytest.fixture(autouse=True)
def _reload_catalog():
    bld.reload_catalog()
    yield
    bld.reload_catalog()


# ---------------------------------------------------------------------------
# Corpus shape sanity (acceptance criteria §1, §2)
# ---------------------------------------------------------------------------


def test_corpus_loads_and_has_100_samples(corpus):
    assert len(corpus) == 100, f"expected 100 samples, got {len(corpus)}"


def test_corpus_50_violation_50_clean(corpus):
    violations = [s for s in corpus if s["expected_violation"]]
    cleans = [s for s in corpus if not s["expected_violation"]]
    assert len(violations) == 50, f"expected 50 violation samples, got {len(violations)}"
    assert len(cleans) == 50, f"expected 50 clean samples, got {len(cleans)}"


def test_corpus_ids_unique(corpus):
    ids = [s["id"] for s in corpus]
    assert len(ids) == len(set(ids)), "duplicate sample ids"


def test_corpus_required_fields(corpus):
    required = {"id", "text", "expected_violation", "laws", "forbidden_phrases", "cohort"}
    for s in corpus:
        missing = required - set(s.keys())
        assert not missing, f"sample {s.get('id')!r} missing fields: {missing}"


def test_per_law_coverage_seven_axes(corpus):
    """Each of the 7 業法 must have >= 7 violation samples + >= 7 clean samples."""
    per_law_violation: dict[str, int] = defaultdict(int)
    per_law_clean: dict[str, int] = defaultdict(int)

    for s in corpus:
        if s["expected_violation"]:
            for law in s["laws"]:
                per_law_violation[law] += 1
        else:
            # Clean samples are bucketed by cohort string heuristics — count
            # one row per law via cohort prefix mapping below. The §52/§72/...
            # laws map onto cohorts 1:1.
            cohort_to_law = {
                "税理士事務所": "税理士法",
                "法律事務所": "弁護士法",
                "行政書士事務所": "行政書士法",
                "司法書士事務所": "司法書士法",
                "特許事務所": "弁理士法",
                "社労士事務所": "社労士法",
                "監査法人": "公認会計士法",
            }
            mapped = cohort_to_law.get(s["cohort"])
            if mapped:
                per_law_clean[mapped] += 1

    for law in EXPECTED_LAWS:
        assert (
            per_law_violation[law] >= 7
        ), f"{law}: only {per_law_violation[law]} violation samples (need >= 7)"
        assert (
            per_law_clean[law] >= 7
        ), f"{law}: only {per_law_clean[law]} clean samples (need >= 7)"


# ---------------------------------------------------------------------------
# Detector accuracy (acceptance criteria §3 TP > 95%, §4 FP < 5%)
# ---------------------------------------------------------------------------


def _run_detector(sample: dict[str, Any]) -> list[dict[str, Any]]:
    return bld.detect_violations(sample["text"])


def _build_confusion_matrix(corpus: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute overall + per-業法 TP/FP/FN/TN."""
    overall = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    per_law: dict[str, dict[str, int]] = {
        law: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for law in EXPECTED_LAWS
    }
    miss_ids: list[str] = []
    fp_ids: list[str] = []

    for s in corpus:
        result = _run_detector(s)
        detected_laws = {v["law"] for v in result}
        expected = bool(s["expected_violation"])

        # Overall — was anything detected?
        if expected and result:
            overall["tp"] += 1
        elif expected and not result:
            overall["fn"] += 1
            miss_ids.append(s["id"])
        elif not expected and result:
            overall["fp"] += 1
            fp_ids.append(s["id"])
        else:
            overall["tn"] += 1

        # Per-業法
        expected_laws_set = set(s["laws"]) if expected else set()
        for law in EXPECTED_LAWS:
            law_expected = law in expected_laws_set
            law_detected = law in detected_laws
            if law_expected and law_detected:
                per_law[law]["tp"] += 1
            elif law_expected and not law_detected:
                per_law[law]["fn"] += 1
            elif not law_expected and law_detected:
                per_law[law]["fp"] += 1
            else:
                per_law[law]["tn"] += 1

    return {
        "overall": overall,
        "per_law": per_law,
        "miss_ids": miss_ids,
        "fp_ids": fp_ids,
    }


def test_overall_true_positive_rate_above_95pct(corpus):
    cm = _build_confusion_matrix(corpus)
    overall = cm["overall"]
    expected_violations = overall["tp"] + overall["fn"]
    assert expected_violations == 50, f"violation cohort changed: {expected_violations}"
    rate = overall["tp"] / expected_violations
    assert (
        rate > TP_RATE_FLOOR
    ), f"TP rate {rate:.2%} below floor {TP_RATE_FLOOR:.0%} (missed: {cm['miss_ids']})"


def test_overall_false_positive_rate_below_5pct(corpus):
    cm = _build_confusion_matrix(corpus)
    overall = cm["overall"]
    expected_cleans = overall["fp"] + overall["tn"]
    assert expected_cleans == 50, f"clean cohort changed: {expected_cleans}"
    rate = overall["fp"] / expected_cleans
    assert (
        rate < FP_RATE_CEILING
    ), f"FP rate {rate:.2%} above ceiling {FP_RATE_CEILING:.0%} (false hits: {cm['fp_ids']})"


def test_per_law_no_false_negative_storm(corpus):
    """No single 業法 should have FN > 1 (each has 7 violation samples)."""
    cm = _build_confusion_matrix(corpus)
    for law, mat in cm["per_law"].items():
        assert mat["fn"] <= 1, f"{law}: too many false negatives ({mat})"


def test_confusion_matrix_smoke(corpus):
    """Sanity: confusion matrix sums to corpus size for each axis."""
    cm = _build_confusion_matrix(corpus)
    total = sum(cm["overall"].values())
    assert total == len(corpus), f"overall confusion matrix sum {total} != {len(corpus)}"
    for law, mat in cm["per_law"].items():
        assert sum(mat.values()) == len(corpus), f"{law} confusion sums wrong: {mat}"


# ---------------------------------------------------------------------------
# LLM API import zero (acceptance criteria §5)
# ---------------------------------------------------------------------------


def _scan_imports(path: pathlib.Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                if head in FORBIDDEN_LLM_MODULES:
                    hits.append(f"import {alias.name}")
                if alias.name.startswith("google.generativeai"):
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            head = node.module.split(".")[0]
            if head in FORBIDDEN_LLM_MODULES:
                hits.append(f"from {node.module} import ...")
            if node.module.startswith("google.generativeai"):
                hits.append(f"from {node.module} import ...")
    return hits


def test_no_llm_in_corpus_runner():
    assert _scan_imports(THIS_FILE) == [], "LLM SDK leaked into corpus runner"


def test_no_llm_in_detector_module_via_corpus():
    """Re-assert at the corpus boundary that the detector is LLM-free."""
    assert _scan_imports(DETECTOR_PATH) == [], "LLM SDK leaked into detector"


# ---------------------------------------------------------------------------
# Per-sample parametric test — surfaces individual misses by id
# ---------------------------------------------------------------------------


def _ids_for(corpus_loaded: list[dict[str, Any]]) -> list[str]:
    return [s["id"] for s in corpus_loaded]


_CORPUS_AT_COLLECT = _load_corpus()


@pytest.mark.parametrize(
    "sample",
    _CORPUS_AT_COLLECT,
    ids=_ids_for(_CORPUS_AT_COLLECT),
)
def test_each_sample_matches_expectation(sample):
    result = bld.detect_violations(sample["text"])
    if sample["expected_violation"]:
        assert result, f"FN {sample['id']}: expected hit on laws={sample['laws']}"
        detected_laws = {v["law"] for v in result}
        # At least one expected law should match (don't gate on superset).
        assert detected_laws & set(
            sample["laws"]
        ), f"FN {sample['id']}: detected={detected_laws}, expected one of {sample['laws']}"
    else:
        assert not result, f"FP {sample['id']}: unexpected hits {result}"
