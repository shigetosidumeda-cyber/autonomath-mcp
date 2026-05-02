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
import sys
from pathlib import Path
from typing import Any

from jpintel_mcp.config import settings
from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

DEFAULT_QUERIES_CSV = Path("tools/offline/bench_queries_2026_04_30.csv")

ROW_FIELDNAMES: tuple[str, ...] = (
    "query_id",
    "domain",
    "query_text",
    "records_returned",
    "precomputed_record_count",
    "packet_tokens_estimate",
    "source_tokens_basis",
    "source_tokens_estimate",
    "avoided_tokens_estimate",
    "compression_ratio",
    "break_even_avoided_tokens",
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
        "source_tokens_estimate",
    )
    source_tokens_basis = "token_count" if source_token_count is not None else "unknown"
    env = composer.compose_for_query(
        row["query_text"],
        limit=limit,
        include_facts=include_facts,
        include_rules=False,
        include_compression=True,
        input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
        source_tokens_basis=source_tokens_basis,
        source_token_count=source_token_count,
    )
    records = env.get("records") or []
    compression = env.get("compression") or {}
    savings = compression.get("cost_savings_estimate") or {}
    return {
        "query_id": row["query_id"],
        "domain": row.get("domain", ""),
        "query_text": row["query_text"],
        "records_returned": len(records),
        "precomputed_record_count": sum(
            1 for record in records if record.get("precomputed")
        ),
        "packet_tokens_estimate": compression.get("packet_tokens_estimate"),
        "source_tokens_basis": compression.get("source_tokens_basis"),
        "source_tokens_estimate": compression.get("source_tokens_estimate"),
        "avoided_tokens_estimate": compression.get("avoided_tokens_estimate"),
        "compression_ratio": compression.get("compression_ratio"),
        "break_even_avoided_tokens": savings.get("break_even_avoided_tokens"),
        "break_even_met": savings.get("break_even_met"),
        "net_savings_jpy_ex_tax": savings.get("net_savings_jpy_ex_tax"),
        "corpus_snapshot_id": env.get("corpus_snapshot_id"),
        "packet_id": env.get("packet_id"),
        "answer_basis": env.get("answer_basis", "metadata_only"),
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    zero = sum(1 for row in rows if int(row["records_returned"]) == 0)
    with_precomputed = sum(
        1 for row in rows if int(row["precomputed_record_count"]) > 0
    )
    with_source_tokens = [
        row for row in rows if row.get("source_tokens_estimate") not in (None, "")
    ]
    break_even_rows = [
        row for row in rows if str(row.get("break_even_met")).lower() == "true"
    ]
    avoided_tokens_total = sum(
        int(row["avoided_tokens_estimate"] or 0) for row in with_source_tokens
    )
    net_savings_values = [
        float(row["net_savings_jpy_ex_tax"])
        for row in rows
        if row.get("net_savings_jpy_ex_tax") not in (None, "")
    ]
    return {
        "total_queries": total,
        "zero_result_queries": zero,
        "zero_result_rate": round(zero / total, 4) if total else 0.0,
        "queries_with_precomputed": with_precomputed,
        "precomputed_query_rate": (
            round(with_precomputed / total, 4) if total else 0.0
        ),
        "records_total": sum(int(row["records_returned"]) for row in rows),
        "precomputed_records_total": sum(
            int(row["precomputed_record_count"]) for row in rows
        ),
        "queries_with_source_token_baseline": len(with_source_tokens),
        "break_even_queries": len(break_even_rows),
        "break_even_rate": (
            round(len(break_even_rows) / len(with_source_tokens), 4)
            if with_source_tokens else 0.0
        ),
        "avoided_tokens_total": avoided_tokens_total,
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
            "to compute break-even estimates."
        ),
    )
    parser.add_argument(
        "--rows-csv",
        type=Path,
        default=None,
        help="Optional path to write per-query metrics as CSV",
    )
    return parser.parse_args(argv)


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
    try:
        out.write(json.dumps(_summary(rows), ensure_ascii=False, indent=2) + "\n")
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
