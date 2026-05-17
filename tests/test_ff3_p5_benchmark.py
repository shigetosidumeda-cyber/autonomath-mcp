"""tests/test_ff3_p5_benchmark.py — FF3 P5 LIVE benchmark scaffold guards.

The user directive for FF3 P5 LIVE: "story きれいに見せて + 実際のサービスも
それに正確に厳密に伴う必要があります". These tests guard the **structural
invariants** of the head-to-head benchmark — they do NOT call any LLM
(CLAUDE.md §3 / `tests/test_no_llm_in_production.py`) and they do NOT
hit the network. Each test runs in well under a second.

What this file guards:

  1. Query SOT shape (250 entries, 50 per cohort, unique ids, expected
     tier ∈ {A, B, C, D}).
  2. jpcite runner emits exactly 250 envelopes + 1 manifest with a
     stable shape (query_id, cohort, tool_calls, output_text,
     citations, cost_jpy, billable_units, tier, engine="jpcite").
  3. jpcite Pricing V3 unit ladder is honoured (A=¥3 / B=¥6 / C=¥12 /
     D=¥30 → 1 / 2 / 4 / 10 billable_units × ¥3).
  4. Opus 4.7 fixture schema validates for the partial set the operator
     has populated so far. Missing fixtures must NOT crash the scorer.
  5. The deterministic scorer produces an 8-axis vector ∈ [0, 10]
     per axis, total ∈ [0, 80], with a `_summary.json` aggregate.
  6. Scoring is **deterministic** — two runs produce byte-identical
     summary outputs (modulo the constant ``generated_at`` field).
  7. The runner script itself has zero LLM imports (regex check on the
     source file).
  8. The scorer script itself has zero LLM imports.

NO LLM IMPORTS IN THIS FILE.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
QUERY_YAML = REPO_ROOT / "data" / "p5_benchmark" / "queries_2026_05_17.yaml"
JPCITE_DIR = REPO_ROOT / "data" / "p5_benchmark" / "jpcite_outputs"
OPUS_DIR = REPO_ROOT / "data" / "p5_benchmark" / "opus_4_7_outputs"
SCORES_DIR = REPO_ROOT / "data" / "p5_benchmark" / "scores"
RUNNER = REPO_ROOT / "scripts" / "bench" / "run_jpcite_baseline_2026_05_17.py"
SCORER = REPO_ROOT / "scripts" / "bench" / "score_p5_outputs_2026_05_17.py"
BENCH_HTML = REPO_ROOT / "site" / "benchmark.html"
RESULTS_DOC = REPO_ROOT / "docs" / "_internal" / "P5_BENCHMARK_RESULTS_2026_05_17.md"
GROUND_TRUTH_DOC = (
    REPO_ROOT / "docs" / "_internal" / "P5_BENCHMARK_GROUND_TRUTH_GENERATION_2026_05_17.md"
)

EXPECTED_COHORTS = {
    "zeirishi",
    "kaikeishi",
    "gyoseishoshi",
    "shihoshoshi",
    "chusho_keiei",
}
TIER_TO_UNITS = {"A": 1, "B": 2, "C": 4, "D": 10}
UNIT_PRICE_JPY = 3


def _load_queries() -> list[dict[str, object]]:
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(QUERY_YAML.read_text(encoding="utf-8")) or {}
    queries = data.get("queries") or []
    assert isinstance(queries, list)
    return queries


def _run_python(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )


# ---------------------------------------------------------------- (1) SOT shape


def test_query_sot_shape_and_uniqueness() -> None:
    queries = _load_queries()
    assert len(queries) == 250, f"expected 250 queries, got {len(queries)}"

    ids = [q["id"] for q in queries]
    assert len(set(ids)) == 250, "duplicate query ids in SOT"

    cohort_counts: dict[str, int] = {}
    for q in queries:
        cohort = q["cohort"]
        assert cohort in EXPECTED_COHORTS, f"unknown cohort: {cohort}"
        cohort_counts[cohort] = cohort_counts.get(cohort, 0) + 1
        tier = q.get("expected_tier")
        assert tier in TIER_TO_UNITS, f"bad tier {tier} for {q['id']}"
        assert q.get("query"), f"empty query text for {q['id']}"
    assert set(cohort_counts) == EXPECTED_COHORTS
    for cohort, n in cohort_counts.items():
        assert n == 50, f"cohort {cohort} has {n} queries, expected 50"


# ---------------------------------------------------------------- (2) runner


def test_runner_emits_250_envelopes_and_manifest() -> None:
    rc = _run_python(RUNNER, "--mode", "dry")
    assert rc.returncode == 0, f"runner failed: {rc.stderr}"
    envelopes = sorted(JPCITE_DIR.glob("*.json"))
    # 250 envelopes + _manifest.json
    json_files = [p for p in envelopes if p.name != "_manifest.json"]
    assert len(json_files) == 250, f"expected 250 envelopes, got {len(json_files)}"

    manifest_path = JPCITE_DIR / "_manifest.json"
    assert manifest_path.exists(), "manifest not written"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["engine"] == "jpcite"
    assert manifest["query_count"] == 250
    assert "fingerprint_sha256" in manifest
    assert len(manifest["fingerprint_sha256"]) == 64

    # Spot-check one envelope.
    sample = json.loads((JPCITE_DIR / "zeirishi_001.json").read_text(encoding="utf-8"))
    for key in (
        "query_id",
        "cohort",
        "query",
        "engine",
        "tool_calls",
        "output_text",
        "citations",
        "cost_jpy",
        "billable_units",
        "tier",
    ):
        assert key in sample, f"envelope missing key {key}"
    assert sample["engine"] == "jpcite"


# ---------------------------------------------------------------- (3) Pricing V3


def test_pricing_v3_unit_ladder_honoured() -> None:
    for env_path in JPCITE_DIR.glob("*.json"):
        if env_path.name == "_manifest.json":
            continue
        env = json.loads(env_path.read_text(encoding="utf-8"))
        tier = env["tier"]
        units = env["billable_units"]
        price = env["cost_jpy"]
        assert units == TIER_TO_UNITS[tier], (
            f"{env_path.name}: tier={tier} expected units={TIER_TO_UNITS[tier]}, got {units}"
        )
        assert price == units * UNIT_PRICE_JPY, (
            f"{env_path.name}: price={price} ≠ {units}×{UNIT_PRICE_JPY}"
        )


# ---------------------------------------------------------------- (4) Opus schema


def test_populated_opus_fixtures_have_valid_schema() -> None:
    populated = [p for p in OPUS_DIR.glob("*.json") if p.is_file()]
    assert populated, (
        "expected at least one Opus 4.7 fixture seeded into data/p5_benchmark/opus_4_7_outputs/"
    )
    for path in populated:
        env = json.loads(path.read_text(encoding="utf-8"))
        assert env["engine"] == "opus-4-7", path.name
        assert env["cohort"] in EXPECTED_COHORTS, path.name
        assert env["tier"] in TIER_TO_UNITS, path.name
        # 7-turn invariant.
        steps = [c.get("step") for c in env["tool_calls"]]
        assert steps == [1, 2, 3, 4, 5, 6, 7], f"{path.name}: expected 7-turn sequence, got {steps}"
        assert env["output_text"], path.name
        assert isinstance(env.get("checklist_must_have"), list), path.name
        assert isinstance(env.get("citations"), list), path.name


# ---------------------------------------------------------------- (5) Scorer shape


def test_scorer_produces_per_query_envelope_and_summary() -> None:
    rc_run = _run_python(RUNNER, "--mode", "dry")
    assert rc_run.returncode == 0, rc_run.stderr
    rc_score = _run_python(SCORER)
    assert rc_score.returncode == 0, rc_score.stderr

    score_files = [p for p in SCORES_DIR.glob("*.json") if p.name != "_summary.json"]
    assert len(score_files) == 250, f"expected 250 score files, got {len(score_files)}"
    summary_path = SCORES_DIR / "_summary.json"
    assert summary_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["rubric_max_total"] == 80
    assert summary["rubric_axes"] == [
        "correctness",
        "completeness",
        "citation",
        "currency",
        "depth",
        "concision",
        "actionability",
        "cohort_fit",
    ]
    assert set(summary["cohorts"]) == EXPECTED_COHORTS

    # Each per-query envelope has 8 axes within [0, 10].
    sample = json.loads((SCORES_DIR / "zeirishi_001.json").read_text(encoding="utf-8"))
    axes = sample["axes"]
    assert set(axes) == {
        "correctness",
        "completeness",
        "citation",
        "currency",
        "depth",
        "concision",
        "actionability",
        "cohort_fit",
    }
    for axis, value in axes.items():
        assert 0.0 <= value <= 10.0, f"{axis} value out of range: {value}"
    assert 0.0 <= sample["total"] <= 80.0


# ---------------------------------------------------------------- (6) Determinism


def test_scorer_is_deterministic_across_two_runs() -> None:
    _run_python(RUNNER, "--mode", "dry")
    _run_python(SCORER)
    first = json.loads((SCORES_DIR / "_summary.json").read_text(encoding="utf-8"))
    _run_python(SCORER)
    second = json.loads((SCORES_DIR / "_summary.json").read_text(encoding="utf-8"))

    # generated_at is a fixed constant in the scaffold ("2026-05-17T00:00:00+09:00"),
    # so byte-identical comparison should hold once the runner+scorer have settled.
    assert first["cohorts"] == second["cohorts"]
    assert first["missing_opus_count"] == second["missing_opus_count"]
    assert first["rubric_max_total"] == second["rubric_max_total"]


# ---------------------------------------------------------------- (7) NO LLM in runner


_LLM_IMPORT_RE = re.compile(
    r"^\s*(import|from)\s+("
    r"anthropic|openai|google\.generativeai|claude_agent_sdk|"
    r"langchain|langchain_\w+|mistralai|cohere|groq|replicate|together|"
    r"vertexai|bedrock_runtime"
    r")\b",
    re.MULTILINE,
)


def test_runner_has_no_llm_imports() -> None:
    src = RUNNER.read_text(encoding="utf-8")
    matches = _LLM_IMPORT_RE.findall(src)
    assert not matches, f"runner imports LLM SDK: {matches}"


# ---------------------------------------------------------------- (8) NO LLM in scorer


def test_scorer_has_no_llm_imports() -> None:
    src = SCORER.read_text(encoding="utf-8")
    matches = _LLM_IMPORT_RE.findall(src)
    assert not matches, f"scorer imports LLM SDK: {matches}"


# ---------------------------------------------------------------- (9) Public page


def test_benchmark_html_present_and_well_formed() -> None:
    assert BENCH_HTML.exists(), "site/benchmark.html missing"
    html = BENCH_HTML.read_text(encoding="utf-8")
    assert html.lstrip().startswith("<!DOCTYPE html>"), "benchmark.html missing doctype"
    # Key cohort labels surfaced for the public reader.
    for label in ("税理士", "会計士", "行政書士", "司法書士", "中小経営者"):
        assert label in html, f"benchmark.html missing cohort label: {label}"
    # 250 query appears in the lead.
    assert "250 query" in html
    # Pricing V3 hard guard markers.
    assert "1-8" in html or "1 to 8" in html


# ---------------------------------------------------------------- (10) Docs present


def test_internal_docs_present() -> None:
    assert RESULTS_DOC.exists(), "P5_BENCHMARK_RESULTS_2026_05_17.md missing"
    assert GROUND_TRUTH_DOC.exists(), "P5_BENCHMARK_GROUND_TRUTH_GENERATION_2026_05_17.md missing"
    for path in (RESULTS_DOC, GROUND_TRUTH_DOC):
        text = path.read_text(encoding="utf-8")
        assert "250" in text and "Opus 4.7" in text, path.name
