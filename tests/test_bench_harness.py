"""Tests for the operator-only bench harness at tools/offline/bench_harness.py.

The harness is intentionally NOT imported as a Python module here — it
lives under `tools/offline/` and the CI guard
`tests/test_no_llm_in_production.py` forbids `import tools.offline...`
from anywhere under `tests/`. We invoke the script via `subprocess` the
same way an operator would call it from the command line.

These tests verify:
  1. `--mode emit` produces 3 instruction lines per query (one per arm),
     with the expected schema.
  2. `--mode aggregate` reads a results CSV and returns paired-sample
     median/p25/p75 per arm + a median delta % per metric.
  3. The harness file itself does NOT import any LLM SDK.

NO LLM IMPORTS HERE.
"""
from __future__ import annotations

import ast
import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = REPO_ROOT / "tools" / "offline" / "bench_harness.py"
SAMPLE_QUERIES_CSV = REPO_ROOT / "tools" / "offline" / "bench_queries_2026_04_30.csv"


def _run_harness(*args: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    """Invoke the harness as a script (no python-level import)."""
    return subprocess.run(
        [sys.executable, str(HARNESS_PATH), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        check=False,
    )


# -- 1. emit ----------------------------------------------------------------


def test_emit_generates_three_lines_per_query() -> None:
    """For N queries, --mode emit must output exactly 3N JSONL lines."""
    assert SAMPLE_QUERIES_CSV.exists(), f"missing fixture: {SAMPLE_QUERIES_CSV}"
    with SAMPLE_QUERIES_CSV.open("r", encoding="utf-8") as f:
        n_queries = sum(1 for _ in csv.DictReader(f))
    assert n_queries == 30, (
        f"expected 30 sample queries, got {n_queries} — keep the canonical "
        f"30-row distribution in tools/offline/bench_queries_2026_04_30.csv"
    )

    res = _run_harness(
        "--mode", "emit",
        "--queries-csv", str(SAMPLE_QUERIES_CSV),
        "--model", "claude-sonnet-4-6",
        "--jpcite-base-url", "https://api.jpcite.com",
    )
    assert res.returncode == 0, res.stderr
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    assert len(lines) == 3 * n_queries, (
        f"expected {3 * n_queries} instruction lines, got {len(lines)}"
    )

    # Per-line schema check
    arms_seen_per_query: dict[int, set[str]] = {}
    expected_arms = {
        "direct_web",
        "jpcite_packet",
        "jpcite_precomputed_intelligence",
    }
    for ln in lines:
        rec = json.loads(ln)
        for required in (
            "query_id",
            "domain",
            "arm",
            "model",
            "query_text",
            "tools_enabled",
            "prefetch_url",
            "system_prompt",
            "instructions",
        ):
            assert required in rec, f"missing key {required!r} in {rec}"
        assert rec["arm"] in expected_arms
        assert rec["model"] == "claude-sonnet-4-6"
        arms_seen_per_query.setdefault(rec["query_id"], set()).add(rec["arm"])
        if rec["arm"] == "direct_web":
            assert rec["tools_enabled"] == ["web_search"]
            assert rec["prefetch_url"] is None
        elif rec["arm"] == "jpcite_packet":
            assert rec["tools_enabled"] == []
            assert rec["prefetch_method"] == "POST"
            assert rec["prefetch_url"] is not None
            assert rec["prefetch_url"] == (
                "https://api.jpcite.com/v1/evidence/packets/query"
            )
            assert rec["prefetch_body"]["query_text"] == rec["query_text"]
            assert rec["prefetch_body"]["include_compression"] is True
        elif rec["arm"] == "jpcite_precomputed_intelligence":
            assert rec["tools_enabled"] == []
            assert rec["prefetch_method"] == "GET"
            assert rec["prefetch_url"] is not None
            assert rec["prefetch_url"].startswith(
                "https://api.jpcite.com/v1/intelligence/precomputed/query?q="
            )

    # Every query must have all three arms present.
    for qid, arms in arms_seen_per_query.items():
        assert arms == expected_arms, f"query {qid} missing arms: got {arms}"


def test_emit_can_still_generate_legacy_two_arm_run() -> None:
    """Operators can still emit only the original paired A/B arms."""
    with SAMPLE_QUERIES_CSV.open("r", encoding="utf-8") as f:
        n_queries = sum(1 for _ in csv.DictReader(f))

    res = _run_harness(
        "--mode",
        "emit",
        "--queries-csv",
        str(SAMPLE_QUERIES_CSV),
        "--arms",
        "direct_web,jpcite_packet",
    )
    assert res.returncode == 0, res.stderr
    lines = [json.loads(ln) for ln in res.stdout.splitlines() if ln.strip()]
    assert len(lines) == 2 * n_queries
    assert {rec["arm"] for rec in lines} == {"direct_web", "jpcite_packet"}


def test_emit_with_missing_csv_arg_errors() -> None:
    res = _run_harness("--mode", "emit")
    assert res.returncode == 2
    assert "queries-csv" in res.stderr.lower()


# -- 2. aggregate -----------------------------------------------------------


@pytest.fixture()
def fixture_results_csv(tmp_path: Path) -> Path:
    """Hand-rolled paired results CSV with known medians.

    direct_web input_tokens: [10000, 20000, 30000] -> median 20000
    jpcite_packet input_tokens: [1000, 2000, 3000] -> median 2000
    Δ% on input_tokens median = (20000 - 2000) / 20000 * 100 = 90.0%
    """
    path = tmp_path / "bench_results.csv"
    rows = [
        # direct_web rows
        {
            "query_id": 1, "query_text": "Q1", "arm": "direct_web",
            "model": "claude-sonnet-4-6",
            "input_tokens": 10000, "output_tokens": 500, "reasoning_tokens": 0,
            "web_searches": 3, "jpcite_requests": 0,
            "yen_cost_per_answer": 12.0, "latency_seconds": 8.0,
            "citation_rate": 0.6, "hallucination_rate": 0.2,
            "corpus_snapshot_id": "", "packet_id": "", "notes": "",
        },
        {
            "query_id": 2, "query_text": "Q2", "arm": "direct_web",
            "model": "claude-sonnet-4-6",
            "input_tokens": 20000, "output_tokens": 800, "reasoning_tokens": 0,
            "web_searches": 5, "jpcite_requests": 0,
            "yen_cost_per_answer": 18.0, "latency_seconds": 12.0,
            "citation_rate": 0.7, "hallucination_rate": 0.15,
            "corpus_snapshot_id": "", "packet_id": "", "notes": "",
        },
        {
            "query_id": 3, "query_text": "Q3", "arm": "direct_web",
            "model": "claude-sonnet-4-6",
            "input_tokens": 30000, "output_tokens": 1100, "reasoning_tokens": 0,
            "web_searches": 7, "jpcite_requests": 0,
            "yen_cost_per_answer": 25.0, "latency_seconds": 15.0,
            "citation_rate": 0.8, "hallucination_rate": 0.1,
            "corpus_snapshot_id": "", "packet_id": "", "notes": "",
        },
        # jpcite_packet rows (paired by query_id)
        {
            "query_id": 1, "query_text": "Q1", "arm": "jpcite_packet",
            "model": "claude-sonnet-4-6",
            "input_tokens": 1000, "output_tokens": 400, "reasoning_tokens": 0,
            "web_searches": 0, "jpcite_requests": 1,
            "yen_cost_per_answer": 5.0, "latency_seconds": 3.0,
            "citation_rate": 0.95, "hallucination_rate": 0.05,
            "corpus_snapshot_id": "corpus-2026-04-29", "packet_id": "evp_x1", "notes": "",
        },
        {
            "query_id": 2, "query_text": "Q2", "arm": "jpcite_packet",
            "model": "claude-sonnet-4-6",
            "input_tokens": 2000, "output_tokens": 600, "reasoning_tokens": 0,
            "web_searches": 0, "jpcite_requests": 1,
            "yen_cost_per_answer": 6.0, "latency_seconds": 3.5,
            "citation_rate": 0.92, "hallucination_rate": 0.06,
            "corpus_snapshot_id": "corpus-2026-04-29", "packet_id": "evp_x2", "notes": "",
        },
        {
            "query_id": 3, "query_text": "Q3", "arm": "jpcite_packet",
            "model": "claude-sonnet-4-6",
            "input_tokens": 3000, "output_tokens": 700, "reasoning_tokens": 0,
            "web_searches": 0, "jpcite_requests": 1,
            "yen_cost_per_answer": 7.0, "latency_seconds": 4.0,
            "citation_rate": 0.94, "hallucination_rate": 0.04,
            "corpus_snapshot_id": "corpus-2026-04-29", "packet_id": "evp_x3", "notes": "",
        },
    ]
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def test_aggregate_computes_correct_medians(fixture_results_csv: Path) -> None:
    res = _run_harness("--mode", "aggregate", "--results-csv", str(fixture_results_csv))
    assert res.returncode == 0, res.stderr
    summary = json.loads(res.stdout)

    # Paired count = 3 (query_ids 1,2,3 in both arms)
    assert summary["paired_query_count"] == 3
    assert summary["active_arms"] == ["direct_web", "jpcite_packet"]
    assert summary["queries_only_in_direct_web"] == []
    assert summary["queries_only_in_jpcite_packet"] == []

    # direct_web medians
    dw = summary["arms"]["direct_web"]
    assert dw["input_tokens"]["p50"] == 20000.0
    assert dw["input_tokens"]["p25"] == 15000.0  # midway 10000-20000
    assert dw["input_tokens"]["p75"] == 25000.0  # midway 20000-30000
    assert dw["input_tokens"]["n"] == 3
    assert dw["web_searches"]["p50"] == 5.0
    assert dw["jpcite_requests"]["p50"] == 0.0
    assert summary["optional_numeric_metrics"] == []
    assert "records_returned" not in dw

    # jpcite_packet medians
    jp = summary["arms"]["jpcite_packet"]
    assert jp["input_tokens"]["p50"] == 2000.0
    assert jp["web_searches"]["p50"] == 0.0
    assert jp["jpcite_requests"]["p50"] == 1.0

    # Rates: arithmetic mean
    assert dw["citation_rate"]["mean"] == pytest.approx((0.6 + 0.7 + 0.8) / 3, abs=1e-4)
    assert jp["citation_rate"]["mean"] == pytest.approx((0.95 + 0.92 + 0.94) / 3, abs=1e-4)

    # Median delta % on input_tokens
    assert summary["median_delta_pct"]["input_tokens"] == 90.0
    # No-baseline edge case: web_searches direct_web=5, jpcite=0 -> 100.0
    assert summary["median_delta_pct"]["web_searches"] == 100.0


def test_aggregate_includes_optional_prefetch_metrics_when_present(
    tmp_path: Path,
) -> None:
    """New prefetch metrics are aggregated only when the CSV includes them."""
    path = tmp_path / "bench_results_with_prefetch_metrics.csv"
    rows = [
        {
            "query_id": 1,
            "query_text": "Q1",
            "arm": "direct_web",
            "model": "claude-sonnet-4-6",
            "input_tokens": 10000,
            "output_tokens": 500,
            "reasoning_tokens": 0,
            "web_searches": 3,
            "jpcite_requests": 0,
            "yen_cost_per_answer": 12.0,
            "latency_seconds": 8.0,
            "citation_rate": 0.6,
            "hallucination_rate": 0.2,
            "records_returned": "",
            "precomputed_record_count": "",
            "packet_tokens_estimate": "",
            "source_tokens_estimate": "",
            "corpus_snapshot_id": "",
            "packet_id": "",
            "notes": "",
        },
        {
            "query_id": 2,
            "query_text": "Q2",
            "arm": "direct_web",
            "model": "claude-sonnet-4-6",
            "input_tokens": 20000,
            "output_tokens": 800,
            "reasoning_tokens": 0,
            "web_searches": 5,
            "jpcite_requests": 0,
            "yen_cost_per_answer": 18.0,
            "latency_seconds": 12.0,
            "citation_rate": 0.7,
            "hallucination_rate": 0.15,
            "records_returned": "",
            "precomputed_record_count": "",
            "packet_tokens_estimate": "",
            "source_tokens_estimate": "",
            "corpus_snapshot_id": "",
            "packet_id": "",
            "notes": "",
        },
        {
            "query_id": 1,
            "query_text": "Q1",
            "arm": "jpcite_packet",
            "model": "claude-sonnet-4-6",
            "input_tokens": 1000,
            "output_tokens": 400,
            "reasoning_tokens": 0,
            "web_searches": 0,
            "jpcite_requests": 1,
            "yen_cost_per_answer": 5.0,
            "latency_seconds": 3.0,
            "citation_rate": 0.95,
            "hallucination_rate": 0.05,
            "records_returned": 4,
            "precomputed_record_count": 10,
            "packet_tokens_estimate": 1200,
            "source_tokens_estimate": 5000,
            "corpus_snapshot_id": "corpus-2026-04-29",
            "packet_id": "evp_x1",
            "notes": "",
        },
        {
            "query_id": 2,
            "query_text": "Q2",
            "arm": "jpcite_packet",
            "model": "claude-sonnet-4-6",
            "input_tokens": 2000,
            "output_tokens": 600,
            "reasoning_tokens": 0,
            "web_searches": 0,
            "jpcite_requests": 1,
            "yen_cost_per_answer": 6.0,
            "latency_seconds": 3.5,
            "citation_rate": 0.92,
            "hallucination_rate": 0.06,
            "records_returned": 8,
            "precomputed_record_count": 12,
            "packet_tokens_estimate": 1800,
            "source_tokens_estimate": 7000,
            "corpus_snapshot_id": "corpus-2026-04-29",
            "packet_id": "evp_x2",
            "notes": "",
        },
    ]
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    res = _run_harness("--mode", "aggregate", "--results-csv", str(path))
    assert res.returncode == 0, res.stderr
    summary = json.loads(res.stdout)

    assert summary["optional_numeric_metrics"] == [
        "records_returned",
        "precomputed_record_count",
        "packet_tokens_estimate",
        "source_tokens_estimate",
    ]
    packet = summary["arms"]["jpcite_packet"]
    assert packet["records_returned"]["p50"] == 6.0
    assert packet["records_returned"]["n"] == 2
    assert packet["precomputed_record_count"]["p50"] == 11.0
    assert packet["packet_tokens_estimate"]["p50"] == 1500.0
    assert packet["source_tokens_estimate"]["p50"] == 6000.0
    assert summary["arms"]["direct_web"]["records_returned"]["n"] == 0
    assert summary["median_delta_pct"]["records_returned"] is None


def test_aggregate_computes_three_arm_pairing_and_deltas(tmp_path: Path) -> None:
    """Three-arm results pair on query_id across all active arms."""
    path = tmp_path / "bench_results_three_arm.csv"
    base = {
        "model": "claude-sonnet-4-6",
        "output_tokens": 100,
        "reasoning_tokens": 0,
        "citation_rate": 1.0,
        "hallucination_rate": 0.0,
        "corpus_snapshot_id": "",
        "packet_id": "",
        "notes": "",
    }
    rows = [
        {
            **base,
            "query_id": 1,
            "query_text": "Q1",
            "arm": "direct_web",
            "input_tokens": 1000,
            "web_searches": 2,
            "jpcite_requests": 0,
            "yen_cost_per_answer": 10,
            "latency_seconds": 10,
        },
        {
            **base,
            "query_id": 2,
            "query_text": "Q2",
            "arm": "direct_web",
            "input_tokens": 2000,
            "web_searches": 4,
            "jpcite_requests": 0,
            "yen_cost_per_answer": 20,
            "latency_seconds": 20,
        },
        {
            **base,
            "query_id": 1,
            "query_text": "Q1",
            "arm": "jpcite_packet",
            "input_tokens": 500,
            "web_searches": 0,
            "jpcite_requests": 1,
            "yen_cost_per_answer": 6,
            "latency_seconds": 5,
        },
        {
            **base,
            "query_id": 2,
            "query_text": "Q2",
            "arm": "jpcite_packet",
            "input_tokens": 1000,
            "web_searches": 0,
            "jpcite_requests": 1,
            "yen_cost_per_answer": 8,
            "latency_seconds": 8,
        },
        {
            **base,
            "query_id": 1,
            "query_text": "Q1",
            "arm": "jpcite_precomputed_intelligence",
            "input_tokens": 250,
            "web_searches": 0,
            "jpcite_requests": 1,
            "yen_cost_per_answer": 4,
            "latency_seconds": 3,
        },
        {
            **base,
            "query_id": 2,
            "query_text": "Q2",
            "arm": "jpcite_precomputed_intelligence",
            "input_tokens": 500,
            "web_searches": 0,
            "jpcite_requests": 1,
            "yen_cost_per_answer": 5,
            "latency_seconds": 4,
        },
    ]
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    res = _run_harness("--mode", "aggregate", "--results-csv", str(path))
    assert res.returncode == 0, res.stderr
    summary = json.loads(res.stdout)

    assert summary["active_arms"] == [
        "direct_web",
        "jpcite_packet",
        "jpcite_precomputed_intelligence",
    ]
    assert summary["paired_query_count"] == 2
    assert summary["queries_missing_by_arm"] == {
        "direct_web": [],
        "jpcite_packet": [],
        "jpcite_precomputed_intelligence": [],
    }
    assert summary["arms"]["jpcite_precomputed_intelligence"]["input_tokens"][
        "p50"
    ] == 375.0
    assert summary["median_delta_pct_vs_direct_web"]["jpcite_packet"][
        "input_tokens"
    ] == 50.0
    assert summary["median_delta_pct_vs_direct_web"][
        "jpcite_precomputed_intelligence"
    ]["input_tokens"] == 75.0


def test_aggregate_with_missing_csv_arg_errors() -> None:
    res = _run_harness("--mode", "aggregate")
    assert res.returncode == 2
    assert "results-csv" in res.stderr.lower()


def test_aggregate_with_missing_file_errors(tmp_path: Path) -> None:
    fake = tmp_path / "nonexistent.csv"
    res = _run_harness("--mode", "aggregate", "--results-csv", str(fake))
    assert res.returncode == 2


# -- 3. invariant: harness has no LLM imports -------------------------------


def test_harness_has_no_llm_imports() -> None:
    """The harness file itself must not import anthropic / openai / etc.

    This is belt-and-suspenders: tests/test_no_llm_in_production.py
    explicitly does NOT scan tools/offline/ (operator-only scripts may
    legitimately use LLMs there). The bench_harness specifically must
    not, since its job is to instruct the operator and then aggregate
    results — not to make calls.
    """
    assert HARNESS_PATH.exists()
    src = HARNESS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"anthropic", "openai", "google.generativeai", "claude_agent_sdk"}
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                if head in {
                    "anthropic",
                    "openai",
                    "claude_agent_sdk",
                } or alias.name == "google.generativeai" or alias.name.startswith(
                    "google.generativeai."
                ):
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module and (
            node.module.split(".")[0]
            in {
                "anthropic",
                "openai",
                "claude_agent_sdk",
            }
            or node.module == "google.generativeai"
            or node.module.startswith("google.generativeai.")
        ):
            hits.append(f"from {node.module} import ...")
    assert not hits, (
        f"bench_harness.py must not import any LLM SDK; found: {hits}. "
        f"Forbidden modules: {sorted(forbidden)}"
    )
