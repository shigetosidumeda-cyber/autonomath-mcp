#!/usr/bin/env python3
# OPERATOR ONLY: offline hit-rate probe. No LLM API, no network.
"""Measure precomputed-intelligence hit-rate for benchmark queries.

This script reads the benchmark query CSV and runs the local
EvidencePacketComposer against the configured SQLite corpus. It is meant
to run before any operator-owned LLM calls so the benchmark can separate
"jpcite lookup coverage" from "LLM answer quality".
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

from jpintel_mcp.config import settings
from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

DEFAULT_QUERIES_CSV = Path("tools/offline/bench_queries_2026_04_30.csv")
JPCITE_BILLABLE_UNIT_JPY_EX_TAX = 3

ROW_FIELDNAMES: tuple[str, ...] = (
    "query_id",
    "domain",
    "query_text",
    "records_returned",
    "precomputed_record_count",
    "packet_tokens_estimate",
    "source_tokens_basis",
    "baseline_source_method",
    "baseline_source_label",
    "source_pdf_pages",
    "source_token_count",
    "source_tokens_estimate",
    "avoided_tokens_estimate",
    "compression_ratio",
    "input_context_reduction_rate",
    "input_token_price_jpy_per_1m",
    "gross_input_savings_jpy_ex_tax",
    "break_even_avoided_tokens",
    "break_even_source_tokens_estimate",
    "break_even_met",
    "net_savings_jpy_ex_tax",
    "corpus_snapshot_id",
    "packet_id",
    "answer_basis",
)


def _read_queries(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return [row for row in csv.DictReader(f) if row.get("query_id")]


def _optional_positive_int(row: dict[str, str], *names: str) -> int | None:
    for name in names:
        raw = (row.get(name) or "").strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            continue
        if value > 0:
            return value
    return None


def _probe_row(
    composer: EvidencePacketComposer,
    row: dict[str, str],
    *,
    limit: int,
    include_facts: bool,
    input_token_price_jpy_per_1m: float | None,
) -> dict[str, Any]:
    source_token_count = _optional_positive_int(
        row,
        "source_token_count",
        "baseline_source_tokens",
    )
    source_pdf_pages = _optional_positive_int(
        row,
        "source_pdf_pages",
        "baseline_source_pdf_pages",
        "baseline_pdf_pages",
    )
    if source_token_count is not None:
        source_tokens_basis = "token_count"
        source_pdf_pages = None
        default_baseline_method = "caller_token_count"
    elif source_pdf_pages is not None:
        source_tokens_basis = "pdf_pages"
        default_baseline_method = "pdf_pages_estimate"
    else:
        source_tokens_basis = "unknown"
        default_baseline_method = ""
    baseline_source_method = (
        row.get("baseline_source_method")
        or row.get("source_token_method")
        or default_baseline_method
    ).strip()
    baseline_source_label = (
        row.get("baseline_source_label") or row.get("source_label") or ""
    ).strip()
    env = composer.compose_for_query(
        row["query_text"],
        limit=limit,
        include_facts=include_facts,
        include_rules=False,
        include_compression=True,
        input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
        source_tokens_basis=source_tokens_basis,
        source_pdf_pages=source_pdf_pages,
        source_token_count=source_token_count,
    )
    records = env.get("records") or []
    compression = env.get("compression") or {}
    savings = compression.get("cost_savings_estimate") or {}
    packet_tokens = compression.get("packet_tokens_estimate")
    source_tokens = compression.get("source_tokens_estimate")
    avoided_tokens = compression.get("avoided_tokens_estimate")
    break_even_avoided = savings.get("break_even_avoided_tokens")
    input_context_reduction_rate = None
    if source_tokens not in (None, "", 0) and avoided_tokens not in (None, ""):
        input_context_reduction_rate = round(float(avoided_tokens) / float(source_tokens), 4)
    gross_input_savings = None
    if input_token_price_jpy_per_1m is not None and avoided_tokens not in (None, ""):
        gross_input_savings = round(
            float(avoided_tokens) * input_token_price_jpy_per_1m / 1_000_000, 4
        )
    break_even_source_tokens = None
    if packet_tokens not in (None, "") and break_even_avoided not in (None, ""):
        break_even_source_tokens = int(packet_tokens) + int(break_even_avoided)
    return {
        "query_id": row["query_id"],
        "domain": row.get("domain", ""),
        "query_text": row["query_text"],
        "records_returned": len(records),
        "precomputed_record_count": sum(1 for record in records if record.get("precomputed")),
        "packet_tokens_estimate": compression.get("packet_tokens_estimate"),
        "source_tokens_basis": compression.get("source_tokens_basis"),
        "baseline_source_method": baseline_source_method,
        "baseline_source_label": baseline_source_label,
        "source_pdf_pages": compression.get("source_pdf_pages"),
        "source_token_count": compression.get("source_token_count"),
        "source_tokens_estimate": compression.get("source_tokens_estimate"),
        "avoided_tokens_estimate": compression.get("avoided_tokens_estimate"),
        "compression_ratio": compression.get("compression_ratio"),
        "input_context_reduction_rate": input_context_reduction_rate,
        "input_token_price_jpy_per_1m": input_token_price_jpy_per_1m,
        "gross_input_savings_jpy_ex_tax": gross_input_savings,
        "break_even_avoided_tokens": savings.get("break_even_avoided_tokens"),
        "break_even_source_tokens_estimate": break_even_source_tokens,
        "break_even_met": savings.get("break_even_met"),
        "net_savings_jpy_ex_tax": savings.get("net_savings_jpy_ex_tax"),
        "corpus_snapshot_id": env.get("corpus_snapshot_id"),
        "packet_id": env.get("packet_id"),
        "answer_basis": env.get("answer_basis", "metadata_only"),
    }


def _price_key(price: float) -> str:
    return str(int(price)) if float(price).is_integer() else str(price)


def _break_even_for_price(rows: list[dict[str, Any]], price: float) -> dict[str, Any]:
    eligible = [
        row
        for row in rows
        if row.get("source_tokens_estimate") not in (None, "")
        and row.get("packet_tokens_estimate") not in (None, "")
    ]
    if price <= 0 or not eligible:
        return {
            "queries_with_source_token_baseline": len(eligible),
            "break_even_queries": 0,
            "break_even_rate": 0.0,
            "break_even_avoided_tokens": None,
        }
    break_even_tokens = math.ceil(JPCITE_BILLABLE_UNIT_JPY_EX_TAX / (price / 1_000_000))
    met = 0
    net_values: list[float] = []
    for row in eligible:
        source_tokens = int(row["source_tokens_estimate"])
        packet_tokens = int(row["packet_tokens_estimate"])
        avoided = max(0, source_tokens - packet_tokens)
        if avoided >= break_even_tokens:
            met += 1
        net_values.append(round(avoided * price / 1_000_000 - JPCITE_BILLABLE_UNIT_JPY_EX_TAX, 4))
    return {
        "queries_with_source_token_baseline": len(eligible),
        "break_even_queries": met,
        "break_even_rate": round(met / len(eligible), 4),
        "break_even_avoided_tokens": break_even_tokens,
        "net_savings_jpy_ex_tax_total": round(sum(net_values), 4),
    }


def _summary(
    rows: list[dict[str, Any]],
    *,
    price_scenarios_jpy_per_1m: list[float] | None = None,
) -> dict[str, Any]:
    total = len(rows)
    zero = sum(1 for row in rows if int(row["records_returned"]) == 0)
    with_precomputed = sum(1 for row in rows if int(row["precomputed_record_count"]) > 0)
    with_source_tokens = [
        row for row in rows if row.get("source_tokens_estimate") not in (None, "")
    ]
    break_even_input_rows = [
        row
        for row in with_source_tokens
        if row.get("input_token_price_jpy_per_1m") not in (None, "")
    ]
    break_even_rows = [
        row for row in break_even_input_rows if str(row.get("break_even_met")).lower() == "true"
    ]
    avoided_tokens_total = sum(
        int(row["avoided_tokens_estimate"] or 0) for row in with_source_tokens
    )
    net_savings_values = [
        float(row["net_savings_jpy_ex_tax"])
        for row in rows
        if row.get("net_savings_jpy_ex_tax") not in (None, "")
    ]
    context_reduction_values = [
        float(row["input_context_reduction_rate"])
        for row in with_source_tokens
        if row.get("input_context_reduction_rate") not in (None, "")
    ]

    def median(values: list[float]) -> float | None:
        return percentile(values, 0.5)

    def percentile(values: list[float], q: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        if len(ordered) == 1:
            return round(ordered[0], 4)
        position = (len(ordered) - 1) * q
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        weight = position - lower
        return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 4)

    by_domain: dict[str, dict[str, Any]] = {}
    for row in with_source_tokens:
        domain = str(row.get("domain") or "unknown")
        bucket = by_domain.setdefault(
            domain,
            {
                "queries_with_source_token_baseline": 0,
                "break_even_queries": 0,
                "context_reduction_rates": [],
            },
        )
        bucket["queries_with_source_token_baseline"] += 1
        if str(row.get("break_even_met")).lower() == "true":
            bucket["break_even_queries"] += 1
        if row.get("input_context_reduction_rate") not in (None, ""):
            bucket["context_reduction_rates"].append(float(row["input_context_reduction_rate"]))
    break_even_rate_by_domain = {}
    for domain, bucket in sorted(by_domain.items()):
        baseline_count = int(bucket["queries_with_source_token_baseline"])
        break_even_count = int(bucket["break_even_queries"])
        break_even_rate_by_domain[domain] = {
            "queries_with_source_token_baseline": baseline_count,
            "break_even_queries": break_even_count,
            "break_even_rate": round(break_even_count / baseline_count, 4)
            if baseline_count
            else 0.0,
            "median_context_reduction_rate": median(bucket["context_reduction_rates"]),
        }

    by_baseline_method: dict[str, dict[str, Any]] = {}
    for row in with_source_tokens:
        method = str(row.get("baseline_source_method") or "unknown")
        bucket = by_baseline_method.setdefault(
            method,
            {
                "queries_with_source_token_baseline": 0,
                "break_even_queries": 0,
                "context_reduction_rates": [],
                "source_tokens_total": 0,
            },
        )
        bucket["queries_with_source_token_baseline"] += 1
        bucket["source_tokens_total"] += int(row["source_tokens_estimate"] or 0)
        if str(row.get("break_even_met")).lower() == "true":
            bucket["break_even_queries"] += 1
        if row.get("input_context_reduction_rate") not in (None, ""):
            bucket["context_reduction_rates"].append(float(row["input_context_reduction_rate"]))
    baseline_source_method_breakdown = {}
    for method, bucket in sorted(by_baseline_method.items()):
        baseline_count = int(bucket["queries_with_source_token_baseline"])
        break_even_count = int(bucket["break_even_queries"])
        baseline_source_method_breakdown[method] = {
            "queries_with_source_token_baseline": baseline_count,
            "source_tokens_total": int(bucket["source_tokens_total"]),
            "break_even_queries": break_even_count,
            "break_even_rate": round(break_even_count / baseline_count, 4)
            if baseline_count
            else 0.0,
            "median_context_reduction_rate": median(bucket["context_reduction_rates"]),
        }

    price_scenarios = price_scenarios_jpy_per_1m or []
    break_even_rate_by_price = {
        _price_key(price): _break_even_for_price(rows, price)
        for price in price_scenarios
        if price > 0
    }
    return {
        "total_queries": total,
        "zero_result_queries": zero,
        "zero_result_rate": round(zero / total, 4) if total else 0.0,
        "queries_with_precomputed": with_precomputed,
        "precomputed_query_rate": (round(with_precomputed / total, 4) if total else 0.0),
        "records_total": sum(int(row["records_returned"]) for row in rows),
        "precomputed_records_total": sum(int(row["precomputed_record_count"]) for row in rows),
        "queries_with_source_token_baseline": len(with_source_tokens),
        "queries_with_break_even_inputs": len(break_even_input_rows),
        "break_even_queries": len(break_even_rows),
        "break_even_rate": (
            round(len(break_even_rows) / len(break_even_input_rows), 4)
            if break_even_input_rows
            else 0.0
        ),
        "avoided_tokens_total": avoided_tokens_total,
        "rows_missing_source_token_baseline": total - len(with_source_tokens),
        "rows_without_price": len(with_source_tokens) - len(break_even_input_rows),
        "negative_context_rows": sum(
            1
            for row in with_source_tokens
            if float(row.get("input_context_reduction_rate") or 0) <= 0
        ),
        "median_context_reduction_rate": median(context_reduction_values),
        "context_reduction_rate_p25": percentile(context_reduction_values, 0.25),
        "context_reduction_rate_p75": percentile(context_reduction_values, 0.75),
        "context_reduction_rate_min": (
            round(min(context_reduction_values), 4) if context_reduction_values else None
        ),
        "context_reduction_rate_max": (
            round(max(context_reduction_values), 4) if context_reduction_values else None
        ),
        "break_even_rate_by_domain": break_even_rate_by_domain,
        "baseline_source_method_breakdown": baseline_source_method_breakdown,
        "price_scenarios_jpy_per_1m": price_scenarios,
        "break_even_rate_by_price": break_even_rate_by_price,
        "net_savings_jpy_ex_tax_total": (
            round(sum(net_savings_values), 1) if net_savings_values else None
        ),
        "rows": rows,
    }


def _write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ROW_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--queries-csv",
        type=Path,
        default=DEFAULT_QUERIES_CSV,
        help=f"Benchmark query CSV (default: {DEFAULT_QUERIES_CSV})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="records[] cap per query for the local composer probe",
    )
    parser.add_argument(
        "--include-facts",
        action="store_true",
        help="Include raw facts in packets; default false keeps probe compact",
    )
    parser.add_argument(
        "--input-token-price-jpy-per-1m",
        type=float,
        default=None,
        help=(
            "Optional caller-supplied input-token price in JPY per 1M tokens. "
            "Used only with per-row source_token_count/baseline_source_tokens "
            "or source_pdf_pages/baseline_source_pdf_pages to compute "
            "break-even estimates."
        ),
    )
    parser.add_argument(
        "--price-scenarios",
        default="",
        help=(
            "Optional comma-separated JPY-per-1M input-token prices for "
            "summary-only break-even sensitivity, for example 100,300,1000."
        ),
    )
    parser.add_argument(
        "--rows-csv",
        type=Path,
        default=None,
        help="Optional path to write per-query metrics as CSV",
    )
    return parser.parse_args(argv)


def _parse_price_scenarios(raw: str) -> list[float]:
    prices: list[float] = []
    seen: set[float] = set()
    for part in raw.split(","):
        text = part.strip()
        if not text:
            continue
        try:
            price = float(text)
        except ValueError:
            continue
        if price <= 0 or price in seen:
            continue
        seen.add(price)
        prices.append(price)
    return prices


def main(argv: list[str] | None = None, out=sys.stdout) -> int:
    args = parse_args(argv)
    queries = _read_queries(args.queries_csv)
    if not queries:
        print(f"ERROR: no queries loaded from {args.queries_csv}", file=sys.stderr)
        return 2
    composer = EvidencePacketComposer(
        jpintel_db=settings.db_path,
        autonomath_db=settings.autonomath_db_path,
    )
    rows = [
        _probe_row(
            composer,
            row,
            limit=max(1, args.limit),
            include_facts=args.include_facts,
            input_token_price_jpy_per_1m=args.input_token_price_jpy_per_1m,
        )
        for row in queries
    ]
    if args.rows_csv is not None:
        _write_rows_csv(args.rows_csv, rows)
    price_scenarios = _parse_price_scenarios(args.price_scenarios)
    if (
        args.input_token_price_jpy_per_1m is not None
        and args.input_token_price_jpy_per_1m > 0
        and args.input_token_price_jpy_per_1m not in set(price_scenarios)
    ):
        price_scenarios.append(args.input_token_price_jpy_per_1m)
    try:
        out.write(
            json.dumps(
                _summary(rows, price_scenarios_jpy_per_1m=price_scenarios),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
