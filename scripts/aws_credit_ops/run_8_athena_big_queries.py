#!/usr/bin/env python3
"""Run the 8 big Athena cross-source queries and emit a burn summary.

Runs (in order):
  1. houjin_360_full_crossjoin            (legacy 5: claim_refs dependent)
  2. program_lineage_full_trace           (legacy 5: claim_refs dependent)
  3. acceptance_probability_cohort_groupby (legacy 5: claim_refs dependent)
  4. enforcement_industry_heatmap          (legacy 5: claim_refs dependent)
  5. cross_source_identity_resolution      (legacy 5: claim_refs dependent)
  6. cross_packet_correlation              (NEW: real packet tables)
  7. time_series_burn_pattern              (NEW: real packet tables)
  8. entity_resolution_full                (NEW: real packet tables)

For each query: substitute ``:run_id_filter`` -> ``'%'``, fire
``athena.start_query_execution``, poll every 5s up to 30 min, on
SUCCEEDED capture ``DataScannedInBytes`` + ``TotalExecutionTimeInMillis``,
compute USD cost at $5/TB. If FAILED, capture StateChangeReason
(this is fine for the legacy 5 — they intentionally touch the empty
``claim_refs`` table).

Budget cap: $100/query (operator can re-run for more).

Emits ``out/athena_real_burn_2026_05_16.json`` with per-query rows +
totals. Designed to be safely re-runnable; result CSVs land in
``s3://jpcite-credit-993693061769-202605-derived/athena-results/``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import boto3

DATABASE = "jpcite_credit_2026_05"
WORKGROUP = "jpcite-credit-2026-05"
RESULT_S3 = "s3://jpcite-credit-993693061769-202605-derived/athena-results/"
ATHENA_USD_PER_TB = 5.00
BUDGET_CAP_USD = 100.0
POLL_INTERVAL_SEC = 5
MAX_POLL_SEC = 1800

PROFILE = os.environ.get("AWS_PROFILE", "bookyou-recovery")
REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
BIG_Q_DIR = Path(__file__).resolve().parent.parent.parent / "infra" / "aws" / "athena" / "big_queries"

QUERIES = [
    # (label, file_name, kind)
    ("houjin_360_full_crossjoin",        "houjin_360_full_crossjoin.sql",        "legacy"),
    ("program_lineage_full_trace",       "program_lineage_full_trace.sql",       "legacy"),
    ("acceptance_probability_cohort_groupby", "acceptance_probability_cohort_groupby.sql", "legacy"),
    ("enforcement_industry_heatmap",     "enforcement_industry_heatmap.sql",     "legacy"),
    ("cross_source_identity_resolution", "cross_source_identity_resolution.sql", "legacy"),
    ("cross_packet_correlation",         "cross_packet_correlation.sql",         "new"),
    ("time_series_burn_pattern",         "time_series_burn_pattern.sql",         "new"),
    ("entity_resolution_full",           "entity_resolution_full.sql",           "new"),
]


def render_sql(path: Path) -> str:
    """Resolve ``:run_id_filter`` to ``'%'`` for full-corpus scans."""
    sql = path.read_text()
    return sql.replace(":run_id_filter", "'%'").replace(":run_id", "'%'")


def run_query(athena: Any, sql: str) -> str:
    """Submit an Athena query and return its execution id."""
    resp = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": DATABASE},
        WorkGroup=WORKGROUP,
        ResultConfiguration={"OutputLocation": RESULT_S3},
    )
    qid: str = resp["QueryExecutionId"]
    return qid


def poll_until_done(athena: Any, exec_id: str) -> dict[str, Any]:
    """Block until query reaches a terminal state. Returns the QueryExecution dict."""
    waited = 0
    while waited <= MAX_POLL_SEC:
        info: dict[str, Any] = athena.get_query_execution(QueryExecutionId=exec_id)["QueryExecution"]
        state = info["Status"]["State"]
        if state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return info
        time.sleep(POLL_INTERVAL_SEC)
        waited += POLL_INTERVAL_SEC
    raise RuntimeError(f"Athena query {exec_id} timeout after {MAX_POLL_SEC}s")


def summarize_run(label: str, kind: str, info: dict[str, Any]) -> dict[str, Any]:
    """Extract bytes / cost / latency for the per-query row."""
    status = info["Status"]
    state = status["State"]
    stats = info.get("Statistics", {})
    bytes_scanned = int(stats.get("DataScannedInBytes", 0) or 0)
    total_ms = int(stats.get("TotalExecutionTimeInMillis", 0) or 0)
    engine_ms = int(stats.get("EngineExecutionTimeInMillis", 0) or 0)
    cost_usd = round((bytes_scanned / (1024**4)) * ATHENA_USD_PER_TB, 6)
    over_budget = cost_usd > BUDGET_CAP_USD
    return {
        "label": label,
        "kind": kind,
        "state": state,
        "exec_id": info["QueryExecutionId"],
        "bytes_scanned": bytes_scanned,
        "bytes_mb": round(bytes_scanned / (1024**2), 4),
        "bytes_gb": round(bytes_scanned / (1024**3), 6),
        "cost_usd": cost_usd,
        "total_ms": total_ms,
        "engine_ms": engine_ms,
        "over_budget": over_budget,
        "state_reason": status.get("StateChangeReason", ""),
    }


def main() -> int:
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    athena = session.client("athena")

    rows: list[dict[str, Any]] = []
    for label, fname, kind in QUERIES:
        path = BIG_Q_DIR / fname
        if not path.exists():
            print(f"[skip] {label} — file not found: {path}", flush=True)
            rows.append({"label": label, "kind": kind, "state": "MISSING", "error": str(path)})
            continue
        sql = render_sql(path)
        print(f"[run]  {label} (kind={kind}) starting...", flush=True)
        try:
            qid = run_query(athena, sql)
            info = poll_until_done(athena, qid)
            row = summarize_run(label, kind, info)
        except Exception as e:  # noqa: BLE001
            row = {"label": label, "kind": kind, "state": "EXCEPTION", "error": str(e)[:300]}
        rows.append(row)
        print(
            f"[done] {label:42s} state={row.get('state'):10s} "
            f"bytes_mb={row.get('bytes_mb','n/a'):>10}  cost_usd={row.get('cost_usd','n/a')}  ms={row.get('total_ms','n/a')}",
            flush=True,
        )

    total_bytes = sum(r.get("bytes_scanned", 0) for r in rows)
    total_cost = round(sum(r.get("cost_usd", 0) for r in rows), 6)
    summary = {
        "database": DATABASE,
        "workgroup": WORKGROUP,
        "rate_usd_per_tb": ATHENA_USD_PER_TB,
        "budget_cap_per_query_usd": BUDGET_CAP_USD,
        "n_queries": len(rows),
        "total_bytes_scanned": total_bytes,
        "total_bytes_gb": round(total_bytes / (1024**3), 6),
        "total_cost_usd": total_cost,
        "rows": rows,
    }
    Path("out").mkdir(exist_ok=True)
    out_path = Path("out/athena_real_burn_2026_05_16.json")
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n[summary] wrote {out_path}", flush=True)
    print(f"[summary] total bytes scanned: {total_bytes} ({summary['total_bytes_gb']} GiB)", flush=True)
    print(f"[summary] total burn (USD):    ${total_cost}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
