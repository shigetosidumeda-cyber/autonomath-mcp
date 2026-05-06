#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""Paired token-cost bench harness for direct_web and jpcite arms.

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

Per `docs/bench_methodology.md`, the default emission MUST cover:

  - Arm `direct_web`: pass query alone, web_search ENABLED.
  - Arm `jpcite_packet`: prefetch
    `POST /v1/evidence/packets/query`, then pass
    `{query + packet}` with web_search DISABLED.
  - Arm `jpcite_precomputed_intelligence`: prefetch the operator-owned
    precomputed intelligence bundle, then pass `{query + bundle}` with
    web_search DISABLED.

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

# These are the metric columns the operator MUST fill in for each arm row.
REQUIRED_NUMERIC_METRIC_COLUMNS: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "web_searches",
    "jpcite_requests",
    "yen_cost_per_answer",
    "latency_seconds",
)
OPTIONAL_NUMERIC_METRIC_COLUMNS: tuple[str, ...] = (
    "records_returned",
    "precomputed_record_count",
    "packet_tokens_estimate",
    "source_tokens_estimate",
)
RATE_METRIC_COLUMNS: tuple[str, ...] = (
    "citation_rate",
    "hallucination_rate",
)
NUMERIC_METRIC_COLUMNS: tuple[str, ...] = (
    REQUIRED_NUMERIC_METRIC_COLUMNS + OPTIONAL_NUMERIC_METRIC_COLUMNS
)

# Arms — must match docs/bench_methodology.md §2.
BASELINE_ARM = "direct_web"
PACKET_ARM = "jpcite_packet"
PRECOMPUTED_ARM = "jpcite_precomputed_intelligence"
ARMS: tuple[str, ...] = (BASELINE_ARM, PACKET_ARM, PRECOMPUTED_ARM)


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

    if arm == BASELINE_ARM:
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

    if arm == PACKET_ARM:
        prefetch = f"{jpcite_base_url.rstrip('/')}/v1/evidence/packets/query"
        prefetch_body = {
            "query_text": qtxt,
            "limit": 5,
            "include_facts": True,
            "include_rules": False,
            "include_compression": True,
        }
        text = (
            f"POST {prefetch} with JSON body "
            f"{json.dumps(prefetch_body, ensure_ascii=False)} ; pass the "
            f"user query AND the returned Evidence Packet (pretty-printed "
            f"JSON) to {model} with web_search DISABLED. Record same "
            f"metrics + corpus_snapshot_id and packet_id from the "
            f"prefetched packet. jpcite_requests counts every billable "
            f"jpcite call on this arm (>=1)."
        )
        return {
            "query_id": qid,
            "domain": domain,
            "arm": arm,
            "model": model,
            "query_text": qtxt,
            "tools_enabled": [],
            "prefetch_method": "POST",
            "prefetch_url": prefetch,
            "prefetch_body": prefetch_body,
            "system_prompt": (
                "Answer using ONLY the provided evidence packet. Do not "
                "web-search. Cite the source_url, fetched_at, and "
                "corpus_snapshot_id from the packet."
            ),
            "instructions": text,
        }

    if arm == PRECOMPUTED_ARM:
        encoded = urllib.parse.quote(qtxt, safe="")
        prefetch = f"{jpcite_base_url.rstrip('/')}/v1/intelligence/precomputed/query?q={encoded}"
        text = (
            f"Fetch the operator-owned precomputed intelligence bundle for "
            f"Q id={qid} from {prefetch} (or the equivalent internal/customer "
            f"export for this query); pass the user query AND the returned "
            f"precomputed intelligence JSON to {model} with web_search "
            f"DISABLED. Record same metrics + corpus_snapshot_id and the "
            f"precomputed bundle id in packet_id if present. jpcite_requests "
            f"counts every billable jpcite call/export used for this arm (>=1)."
        )
        return {
            "query_id": qid,
            "domain": domain,
            "arm": arm,
            "model": model,
            "query_text": qtxt,
            "tools_enabled": [],
            "prefetch_method": "GET",
            "prefetch_url": prefetch,
            "prefetch_body": None,
            "system_prompt": (
                "Answer using ONLY the provided precomputed jpcite "
                "intelligence bundle. Do not web-search. Cite source_url, "
                "fetched_at, corpus_snapshot_id, and any bundle/provenance id "
                "present in the bundle."
            ),
            "instructions": text,
        }

    raise ValueError(f"unknown arm: {arm!r}")


def _parse_arms(raw: str | None) -> tuple[str, ...]:
    """Parse a comma-separated arm list, preserving canonical order."""
    if raw is None:
        return ARMS
    requested = [part.strip() for part in raw.split(",") if part.strip()]
    if not requested:
        raise ValueError("--arms must name at least one arm")
    unknown = sorted(set(requested) - set(ARMS))
    if unknown:
        raise ValueError(f"unknown arm(s): {', '.join(unknown)}; valid arms: {', '.join(ARMS)}")
    requested_set = set(requested)
    return tuple(arm for arm in ARMS if arm in requested_set)


def emit(args: argparse.Namespace, out=sys.stdout) -> int:
    """Emit one JSONL line per (query, arm) to `out`."""
    try:
        arms = _parse_arms(args.arms)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    queries = load_queries(Path(args.queries_csv))
    if not queries:
        print("ERROR: no queries loaded from CSV", file=sys.stderr)
        return 2
    for q in queries:
        for arm in arms:
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
    try:
        configured_arms = _parse_arms(args.arms)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    path = Path(args.results_csv)
    if not path.exists():
        print(f"ERROR: results CSV not found: {path}", file=sys.stderr)
        return 2

    optional_numeric_columns: tuple[str, ...] = ()
    active_numeric_columns = REQUIRED_NUMERIC_METRIC_COLUMNS
    per_arm: dict[str, dict[str, list[float]]] = {
        arm: {col: [] for col in NUMERIC_METRIC_COLUMNS + RATE_METRIC_COLUMNS} for arm in ARMS
    }
    paired_query_ids: dict[str, set[int]] = {arm: set() for arm in ARMS}
    seen_arms: set[str] = set()

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        header = set(reader.fieldnames or ())
        optional_numeric_columns = tuple(
            col for col in OPTIONAL_NUMERIC_METRIC_COLUMNS if col in header
        )
        active_numeric_columns = REQUIRED_NUMERIC_METRIC_COLUMNS + optional_numeric_columns
        for row in reader:
            arm = row.get("arm", "").strip()
            if arm not in configured_arms:
                continue
            seen_arms.add(arm)
            try:
                qid = int(row.get("query_id", "").strip())
            except (TypeError, ValueError):
                continue
            paired_query_ids[arm].add(qid)
            for col in active_numeric_columns + RATE_METRIC_COLUMNS:
                raw = row.get(col, "").strip()
                if raw == "":
                    continue
                try:
                    per_arm[arm][col].append(float(raw))
                except ValueError:
                    continue

    active_arms = configured_arms if args.arms else tuple(arm for arm in ARMS if arm in seen_arms)

    if active_arms:
        paired_query_count = len(set.intersection(*(paired_query_ids[arm] for arm in active_arms)))
    else:
        paired_query_count = 0

    summary: dict[str, Any] = {
        "configured_arms": list(configured_arms),
        "active_arms": list(active_arms),
        "optional_numeric_metrics": list(optional_numeric_columns),
        "arms": {},
        "paired_query_count": paired_query_count,
        "queries_missing_by_arm": {
            arm: sorted(
                set.union(*(paired_query_ids[other] for other in active_arms))
                - paired_query_ids[arm]
            )
            for arm in active_arms
        },
    }

    # Backward-compatible two-arm diagnostics used by existing consumers.
    if BASELINE_ARM in active_arms and PACKET_ARM in active_arms:
        summary["queries_only_in_direct_web"] = sorted(
            paired_query_ids[BASELINE_ARM] - paired_query_ids[PACKET_ARM]
        )
        summary["queries_only_in_jpcite_packet"] = sorted(
            paired_query_ids[PACKET_ARM] - paired_query_ids[BASELINE_ARM]
        )

    for arm in active_arms:
        arm_block: dict[str, Any] = {}
        for col in active_numeric_columns:
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

    # Convenience: median delta % against direct_web for every non-baseline
    # active arm. Operator still owns the published phrasing per
    # docs/bench_methodology.md §6.
    summary["median_delta_pct_vs_direct_web"] = {}
    if BASELINE_ARM in active_arms:
        for arm in active_arms:
            if arm == BASELINE_ARM:
                continue
            arm_delta: dict[str, float | None] = {}
            for col in active_numeric_columns:
                baseline = summary["arms"][BASELINE_ARM][col]["p50"]
                candidate = summary["arms"][arm][col]["p50"]
                if baseline == 0:
                    arm_delta[col] = None
                else:
                    arm_delta[col] = round((baseline - candidate) / baseline * 100.0, 2)
            summary["median_delta_pct_vs_direct_web"][arm] = arm_delta

    # Preserve the original top-level key for the legacy direct_web vs
    # jpcite_packet comparison.
    summary["median_delta_pct"] = summary["median_delta_pct_vs_direct_web"].get(PACKET_ARM, {})

    out.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="bench_harness",
        description=(
            "Paired token-cost bench harness for direct_web and jpcite arms. "
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
        help="jpcite API base for jpcite prefetch URLs",
    )
    p.add_argument(
        "--arms",
        type=str,
        default=None,
        help=(
            "comma-separated arms to emit/aggregate; default emits all arms and "
            "aggregate infers arms present in the CSV"
        ),
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
