#!/usr/bin/env python3
"""Run the Wave 55 mega cross-join + 5 new big Athena queries.

Runs (in order):
  1. wave55_mega_cross_join              (39-table mega join, mother of all)
  2. wave55_cross_packet_entity_unique   (COUNT(DISTINCT subject_id))
  3. wave55_packet_size_distribution     (histogram of approx_bytes)
  4. wave55_coverage_grade_breakdown     (A/B/C/D quality grade)
  5. wave55_outcome_freshness_trend      (generated_at 24h buckets)
  6. wave55_gap_code_frequency           (7-enum gap codes via UNNEST)

For each query: fire ``athena.start_query_execution``, poll every 5s up
to 30 min, on SUCCEEDED capture ``DataScannedInBytes`` +
``TotalExecutionTimeInMillis``, compute USD cost at $5/TB.

Budget cap: $100/query (advisory; workgroup also enforces 100GB scan
cutoff). Emits ``out/athena_wave55_mega_join_2026_05_16.json``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from scripts.aws_credit_ops._aws import get_session

DATABASE = "jpcite_credit_2026_05"
WORKGROUP = "jpcite-credit-2026-05"
RESULT_S3 = "s3://jpcite-credit-993693061769-202605-derived/athena-results/"
ATHENA_USD_PER_TB = 5.00
BUDGET_CAP_USD = 100.0
POLL_INTERVAL_SEC = 5
MAX_POLL_SEC = 1800

PROFILE = os.environ.get("AWS_PROFILE", "bookyou-recovery")
REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
BIG_Q_DIR = (
    Path(__file__).resolve().parent.parent.parent / "infra" / "aws" / "athena" / "big_queries"
)

QUERIES = [
    ("wave55_mega_cross_join", "wave55_mega_cross_join.sql", "mega"),
    ("wave55_cross_packet_entity_unique", "wave55_cross_packet_entity_unique.sql", "new"),
    ("wave55_packet_size_distribution", "wave55_packet_size_distribution.sql", "new"),
    ("wave55_coverage_grade_breakdown", "wave55_coverage_grade_breakdown.sql", "new"),
    ("wave55_outcome_freshness_trend", "wave55_outcome_freshness_trend.sql", "new"),
    ("wave55_gap_code_frequency", "wave55_gap_code_frequency.sql", "new"),
]


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
        info: dict[str, Any] = athena.get_query_execution(QueryExecutionId=exec_id)[
            "QueryExecution"
        ]
        state = info["Status"]["State"]
        if state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return info
        time.sleep(POLL_INTERVAL_SEC)
        waited += POLL_INTERVAL_SEC
    raise RuntimeError(f"Athena query {exec_id} timeout after {MAX_POLL_SEC}s")


def fetch_row_count(athena: Any, exec_id: str) -> int | None:
    """For mega join: pull total row count via get_query_results pagination header.

    Athena returns ResultSet.Rows with a header row + data rows; we
    paginate to count. Skipped if any failure occurs.
    """
    try:
        total = 0
        first = True
        next_token: str | None = None
        for _ in range(50):  # safety bound: 50 pages × 1000 rows = 50k rows max counted
            kwargs: dict[str, Any] = {"QueryExecutionId": exec_id, "MaxResults": 1000}
            if next_token:
                kwargs["NextToken"] = next_token
            resp = athena.get_query_results(**kwargs)
            rows = resp["ResultSet"]["Rows"]
            if first and rows:
                rows = rows[1:]  # strip header
                first = False
            total += len(rows)
            next_token = resp.get("NextToken")
            if not next_token:
                break
        return total
    except Exception:  # noqa: BLE001
        return None


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
    session = get_session(region_name=REGION, profile_name=PROFILE)
    athena = session.client("athena")

    rows: list[dict[str, Any]] = []
    for label, fname, kind in QUERIES:
        path = BIG_Q_DIR / fname
        if not path.exists():
            print(f"[skip] {label} — file not found: {path}", flush=True)
            rows.append({"label": label, "kind": kind, "state": "MISSING", "error": str(path)})
            continue
        sql = path.read_text()
        print(f"[run]  {label} (kind={kind}) starting...", flush=True)
        try:
            qid = run_query(athena, sql)
            info = poll_until_done(athena, qid)
            row = summarize_run(label, kind, info)
            if row["state"] == "SUCCEEDED" and kind == "mega":
                row["row_count"] = fetch_row_count(athena, qid)
        except Exception as e:  # noqa: BLE001
            row = {"label": label, "kind": kind, "state": "EXCEPTION", "error": str(e)[:300]}
        rows.append(row)
        print(
            f"[done] {label:42s} state={row.get('state', '?'):10s} "
            f"bytes_mb={row.get('bytes_mb', 'n/a'):>10}  cost_usd={row.get('cost_usd', 'n/a')}  ms={row.get('total_ms', 'n/a')}",
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
    out_path = Path("out/athena_wave55_mega_join_2026_05_16.json")
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n[summary] wrote {out_path}", flush=True)
    print(
        f"[summary] total bytes scanned: {total_bytes} ({summary['total_bytes_gb']} GiB)",
        flush=True,
    )
    print(f"[summary] total burn (USD):    ${total_cost}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
