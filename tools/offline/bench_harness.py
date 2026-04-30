#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""Paired A/B bench harness for `direct_web` vs `jpcite_packet`.

This script is OPERATOR-DRIVEN. It does NOT call any LLM API. It does
two things:

  1. `--mode emit` (default): read a queries CSV and emit one JSONL line
     per (query_id, arm). The operator (or a customer / analyst) takes
     each line, runs the described LLM call themselves against their
     own provider, and writes the observed metrics into a results CSV.

  2. `--mode aggregate`: read a results CSV produced by step 1 and
     compute paired-sample p25/p50/p75 + cost-per-answer distribution
     per arm. Emit a single JSON document on stdout.

NO LLM IMPORTS HERE — see `tools/offline/README.md` and
`tests/test_no_llm_in_production.py` for the invariant. This file is
under `tools/offline/` precisely so production code (src/, scripts/,
tests/) never ships an LLM SDK on the hot path.

Per `docs/bench_methodology.md`, the emission MUST cover:

  - Arm `direct_web`: pass query alone, web_search ENABLED.
  - Arm `jpcite_packet`: prefetch
    `GET /v1/evidence/packets/query?q=<urlencoded>`, then pass
    `{query + packet}` with web_search DISABLED.

The harness writes the prefetch URL into the instruction line so the
operator pastes it into curl / their HTTP client without guesswork.

Usage:

    # 1. Generate the instruction set (one line per arm per query)
    python tools/offline/bench_harness.py \\
        --queries-csv tools/offline/bench_queries_2026_04_30.csv \\
        --mode emit \\
        --model claude-sonnet-4-6 \\
        --jpcite-base-url https://api.jpcite.com \\
        > bench_instructions.jsonl

    # 2. Operator runs each line by hand. Writes bench_results.csv with
    #    columns: query_id, query_text, arm, model, input_tokens,
    #    output_tokens, reasoning_tokens, web_searches, jpcite_requests,
    #    yen_cost_per_answer, latency_seconds, citation_rate,
    #    hallucination_rate, corpus_snapshot_id, packet_id, notes

    # 3. Aggregate
    python tools/offline/bench_harness.py \\
        --results-csv bench_results.csv \\
        --mode aggregate \\
        > bench_summary.json
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import urllib.parse
from pathlib import Path
from typing import Any

# These are the metric columns the operator MUST fill in for each arm
# row. The aggregator pulls them by name; missing columns raise.
NUMERIC_METRIC_COLUMNS: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "web_searches",
    "jpcite_requests",
    "yen_cost_per_answer",
    "latency_seconds",
)
RATE_METRIC_COLUMNS: tuple[str, ...] = (
    "citation_rate",
    "hallucination_rate",
)

# The two arms — must match docs/bench_methodology.md §2.
ARMS: tuple[str, ...] = ("direct_web", "jpcite_packet")


def load_queries(path: Path) -> list[dict[str, str]]:
    """Read the bench queries CSV.

    Required columns: query_id, domain, query_text.
    Optional: notes.
    """
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            qid = row.get("query_id", "").strip()
            qtxt = row.get("query_text", "").strip()
            if not qid or not qtxt:
                continue
            rows.append(
                {
                    "query_id": int(qid),
                    "domain": row.get("domain", "").strip(),
                    "query_text": qtxt,
                    "notes": row.get("notes", "").strip(),
                }
            )
    return rows


def build_instruction(
    query: dict[str, str],
    arm: str,
    model: str,
    jpcite_base_url: str,
) -> dict[str, Any]:
    """Build a single instruction record for one (query, arm) pair.

    The `instructions` field is a human-readable string the operator
    follows. Structured fields below it carry the same data in a form
    the operator's own automation (if any) can parse.
    """
    qid = query["query_id"]
    qtxt = query["query_text"]
    domain = query["domain"]

    if arm == "direct_web":
        text = (
            f"Run query Q (id={qid}, domain={domain}) via {model} with web_search "
            f"ENABLED. Pass ONLY the user query as the message — no Evidence "
            f"Packet, no extra context. Record token usage (input_tokens, "
            f"output_tokens, reasoning_tokens), web_search tool-call count, "
            f"latency_seconds, and rate the answer for citation_rate + "
            f"hallucination_rate. jpcite_requests=0 for this arm."
        )
        return {
            "query_id": qid,
            "domain": domain,
            "arm": arm,
            "model": model,
            "query_text": qtxt,
            "tools_enabled": ["web_search"],
            "prefetch_url": None,
            "system_prompt": (
                "Answer the user's question about Japanese public subsidies, "
                "laws, tax, or corporations. Cite primary government sources "
                "when possible."
            ),
            "instructions": text,
        }

    if arm == "jpcite_packet":
        encoded = urllib.parse.quote(qtxt, safe="")
        prefetch = f"{jpcite_base_url.rstrip('/')}/v1/evidence/packets/query?q={encoded}"
        text = (
            f"Fetch {prefetch} ; pass the user query AND the returned "
            f"Evidence Packet (pretty-printed JSON) to {model} with "
            f"web_search DISABLED. Record same metrics + corpus_snapshot_id "
            f"and packet_id from the prefetched packet. jpcite_requests "
            f"counts every billable jpcite call on this arm (≥1)."
        )
        return {
            "query_id": qid,
            "domain": domain,
            "arm": arm,
            "model": model,
            "query_text": qtxt,
            "tools_enabled": [],
            "prefetch_url": prefetch,
            "system_prompt": (
                "Answer using ONLY the provided evidence packet. Do not "
                "web-search. Cite the source_url, fetched_at, and "
                "corpus_snapshot_id from the packet."
            ),
            "instructions": text,
        }

    raise ValueError(f"unknown arm: {arm!r}")


def emit(args: argparse.Namespace, out=sys.stdout) -> int:
    """Emit one JSONL line per (query, arm) to `out`."""
    queries = load_queries(Path(args.queries_csv))
    if not queries:
        print("ERROR: no queries loaded from CSV", file=sys.stderr)
        return 2
    for q in queries:
        for arm in ARMS:
            rec = build_instruction(q, arm, args.model, args.jpcite_base_url)
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return 0


def _percentiles(values: list[float]) -> dict[str, float]:
    """Return p25 / p50 / p75 of `values`.

    Uses statistics.quantiles for n>1; falls back gracefully on tiny n.
    """
    if not values:
        return {"p25": 0.0, "p50": 0.0, "p75": 0.0, "n": 0}
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        v = float(sorted_vals[0])
        return {"p25": v, "p50": v, "p75": v, "n": 1}
    # statistics.quantiles with n=4 gives [Q1, Q2, Q3].
    q = statistics.quantiles(sorted_vals, n=4, method="inclusive")
    return {
        "p25": float(q[0]),
        "p50": float(q[1]),
        "p75": float(q[2]),
        "n": n,
    }


def aggregate(args: argparse.Namespace, out=sys.stdout) -> int:
    """Read results CSV, compute per-arm aggregates, emit JSON."""
    path = Path(args.results_csv)
    if not path.exists():
        print(f"ERROR: results CSV not found: {path}", file=sys.stderr)
        return 2

    per_arm: dict[str, dict[str, list[float]]] = {
        arm: {col: [] for col in NUMERIC_METRIC_COLUMNS + RATE_METRIC_COLUMNS}
        for arm in ARMS
    }
    paired_query_ids: dict[str, set[int]] = {arm: set() for arm in ARMS}

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            arm = row.get("arm", "").strip()
            if arm not in ARMS:
                continue
            try:
                qid = int(row.get("query_id", "").strip())
            except (TypeError, ValueError):
                continue
            paired_query_ids[arm].add(qid)
            for col in NUMERIC_METRIC_COLUMNS + RATE_METRIC_COLUMNS:
                raw = row.get(col, "").strip()
                if raw == "":
                    continue
                try:
                    per_arm[arm][col].append(float(raw))
                except ValueError:
                    continue

    summary: dict[str, Any] = {
        "arms": {},
        "paired_query_count": len(paired_query_ids[ARMS[0]] & paired_query_ids[ARMS[1]]),
        "queries_only_in_direct_web": sorted(
            paired_query_ids["direct_web"] - paired_query_ids["jpcite_packet"]
        ),
        "queries_only_in_jpcite_packet": sorted(
            paired_query_ids["jpcite_packet"] - paired_query_ids["direct_web"]
        ),
    }

    for arm in ARMS:
        arm_block: dict[str, Any] = {}
        for col in NUMERIC_METRIC_COLUMNS:
            arm_block[col] = _percentiles(per_arm[arm][col])
        for col in RATE_METRIC_COLUMNS:
            vals = per_arm[arm][col]
            arm_block[col] = {
                "mean": round(sum(vals) / len(vals), 4) if vals else 0.0,
                "n": len(vals),
            }
        # Cost-per-answer distribution (full sorted list, capped at 200 to
        # keep the JSON small — for N=30 this is the full list anyway).
        cost = sorted(per_arm[arm]["yen_cost_per_answer"])
        arm_block["yen_cost_per_answer_distribution"] = cost[:200]
        summary["arms"][arm] = arm_block

    # Convenience: median delta % (direct_web vs jpcite_packet) for each
    # numeric metric. Operator still owns the published phrasing per
    # docs/bench_methodology.md §6.
    summary["median_delta_pct"] = {}
    for col in NUMERIC_METRIC_COLUMNS:
        a = summary["arms"]["direct_web"][col]["p50"]
        b = summary["arms"]["jpcite_packet"][col]["p50"]
        if a == 0:
            summary["median_delta_pct"][col] = None
        else:
            summary["median_delta_pct"][col] = round((a - b) / a * 100.0, 2)

    out.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="bench_harness",
        description=(
            "Paired A/B bench harness for direct_web vs jpcite_packet. "
            "Operator-driven, NO LLM call from this script."
        ),
    )
    p.add_argument(
        "--mode",
        choices=("emit", "aggregate"),
        default="emit",
        help="emit instructions (default) or aggregate operator-collected results",
    )
    p.add_argument(
        "--queries-csv",
        type=str,
        default=None,
        help="path to queries CSV (required for --mode emit)",
    )
    p.add_argument(
        "--results-csv",
        type=str,
        default=None,
        help="path to results CSV (required for --mode aggregate)",
    )
    p.add_argument(
        "--model",
        type=str,
        default="claude-sonnet-4-6",
        help="model identifier passed through to instructions (operator runs the call)",
    )
    p.add_argument(
        "--jpcite-base-url",
        type=str,
        default="https://api.jpcite.com",
        help="jpcite API base for the prefetch URL on the jpcite_packet arm",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode == "emit":
        if not args.queries_csv:
            print("ERROR: --queries-csv is required for --mode emit", file=sys.stderr)
            return 2
        return emit(args)
    if args.mode == "aggregate":
        if not args.results_csv:
            print("ERROR: --results-csv is required for --mode aggregate", file=sys.stderr)
            return 2
        return aggregate(args)
    print(f"ERROR: unknown mode {args.mode!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
