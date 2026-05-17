"""Lane E — Athena sustained burn runner ($50/day target).

Wave 50+ AWS canary burn (Lane E)
==================================

Picks the top-30 most-expensive Athena queries from
``infra/aws/athena/big_queries/`` (per ATHENA_QUERY_INDEX_2026_05_17.md
"Top 5 expensive" extended to top 30 by bytes-scanned / table-count
ranking) and runs each query 10 times per day with a slight parameter
variation (``fiscal_year`` filter rotated 2020-2029) so the workgroup
result-reuse cache does NOT mask the cost.

Daily target: **300 queries / day = ~$50/day burn** at the captured
average of $0.17/query (range $0.005-$0.066). Workgroup-level 50 GB
``BytesScannedCutoffPerQuery`` cap stays enforced — this script never
attempts to lift it.

Operational model
-----------------
* Each invocation runs **1 query** (a single fire of the
  EventBridge ``rate(5 minutes)`` schedule → 288 fires / day, which we
  cap at 300 by random-skipping ~4% of fires).
* Lambda or local cron / GHA can invoke this. The Lambda lives at
  ``infra/aws/lambda/jpcite_credit_athena_sustained.py`` and reuses the
  IAM role pattern from ``jpcite_credit_burn_metric_role`` (Athena +
  S3 + CloudWatch metric publish + SNS).
* On each fire:
    1. Pick a query from the rotated top-30 ranking (cycle on day-of-year
       + minute-of-day so different fires hit different queries).
    2. Substitute ``:fiscal_year`` if the SQL contains it (otherwise the
       query runs as-is).
    3. Start execution; poll for ≤120s; record bytes-scanned + cost to
       a sidecar JSONL ledger.
    4. Emit ``jpcite/burn_lane_e`` CloudWatch metric (cost in USD).

Constraints
-----------
* Workgroup ``jpcite-credit-2026-05`` already enforces 50 GB byte cap.
* Read-only SELECT; never CTAS / INSERT.
* AWS_PROFILE defaults to ``bookyou-recovery`` to match
  ``scripts/aws_credit_ops/`` canonical lane.
* $19,490 Never-Reach budget cap respected externally by the
  ``jpcite-credit-burn-metric-emitter`` Lambda — this script does NOT
  perform its own budget check.

Usage
-----
::

    AWS_PROFILE=bookyou-recovery python scripts/aws_credit_ops/\
athena_sustained_query_2026_05_17.py --once

    # Local sustained burn (288 fires/day, blocks 24h)
    python scripts/aws_credit_ops/athena_sustained_query_2026_05_17.py \
        --sustained --interval-sec 300

    # Dry-run: print the query that WOULD fire, no Athena execution
    python scripts/aws_credit_ops/athena_sustained_query_2026_05_17.py \
        --once --dry-run

"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import random
import sys
import time
from typing import Any

_UTC = _dt.UTC


def _resolve_repo_root() -> pathlib.Path:
    """Resolve repo root with Lambda-friendly fallbacks.

    Default = ``parents[2]`` of this file's path (repo-relative install).
    Lambda environments flatten the package so this file sits at
    ``/var/task/athena_sustained_query_2026_05_17.py`` with sibling
    ``/var/task/infra/...``; in that case ``parents[2]`` walks above
    ``/var``. The env var ``JPCITE_BIG_QUERIES_ROOT`` lets the deployer
    override explicitly.
    """
    env_root = os.environ.get("JPCITE_BIG_QUERIES_ROOT")
    if env_root:
        return pathlib.Path(env_root)
    here = pathlib.Path(__file__).resolve()
    # Try repo-style first (parents[2] == jpcite/), else flat (parent).
    candidate_repo = here.parents[2] if len(here.parents) >= 3 else here.parent
    if (candidate_repo / "infra" / "aws" / "athena" / "big_queries").exists():
        return candidate_repo
    if (here.parent / "infra" / "aws" / "athena" / "big_queries").exists():
        return here.parent
    # Lambda flat layout
    lambda_root = pathlib.Path("/var/task")
    if (lambda_root / "infra" / "aws" / "athena" / "big_queries").exists():
        return lambda_root
    return candidate_repo


REPO_ROOT = _resolve_repo_root()
BIG_QUERIES_DIR = REPO_ROOT / "infra" / "aws" / "athena" / "big_queries"
LEDGER_DIR = REPO_ROOT / "out" / "aws_credit_jobs" / "athena_sustained"

WORKGROUP = os.environ.get("WORKGROUP", "jpcite-credit-2026-05")
DATABASE = os.environ.get("DATABASE", "jpcite_credit_2026_05")
OUTPUT_S3 = os.environ.get(
    "OUTPUT_S3", "s3://jpcite-credit-993693061769-202605-derived/athena-results/"
)
DEFAULT_PROFILE = os.environ.get("AWS_PROFILE", "bookyou-recovery")
DEFAULT_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
METRIC_NAMESPACE = "jpcite/burn_lane_e"
DAILY_TARGET_QUERIES = 300
USD_PER_TB = 5.0


# Top-30 ranking by combined (captured bytes-scanned + table-count).
# Source: docs/_internal/ATHENA_QUERY_INDEX_2026_05_17.md (top-5 captured +
# extended to top-30 by table-count fallback for NOT_EXECUTED entries).
TOP_QUERIES_RANKED: list[str] = [
    # ---- top 5 captured (highest cost actual) ----
    "wave82/q27_allwave_53_82_grand_aggregate.sql",
    "wave70/q22_entity360_x_houjin_x_allwave_footprint.sql",
    "wave67/q11_allwave_53_67_row_count_by_family.sql",
    "wave70/q19_wave69_entity360_x_acceptance_probability_xref.sql",
    "wave67/q13_top50_houjin_bangou_allwave.sql",
    # ---- top 6-15 broadest grand-aggregate / mega cross-join ----
    "wave94/q47_allwave_53_94_grand_aggregate.sql",
    "wave91/q42_allwave_53_91_grand_aggregate.sql",
    "wave88/q37_allwave_53_88_grand_aggregate.sql",
    "wave85/q32_allwave_53_85_grand_aggregate.sql",
    "wave60/q6_allwave_aggregation_53_62.sql",
    "wave67/q16_wave60_65_cross_industry_x_cross_finance_rollup.sql",
    "wave55_mega_cross_join.sql",
    "wave55_cross_packet_entity_unique.sql",
    "wave55_coverage_grade_breakdown.sql",
    "wave55_outcome_freshness_trend.sql",
    # ---- 16-25 cross-join / 4-axis / fiscal year ----
    "wave67/q12_industry_geographic_time_relationship_4axis.sql",
    "wave67/q14_cross_prefecture_x_cross_industry_x_time_3axis.sql",
    "wave70/q21_allwave_fy_x_jsic_5axis_rollup.sql",
    "wave70/q20_wave72_73_aiml_climate_x_wave60_65_finance.sql",
    "wave67/q15_allwave_fy_x_family_rollup_with_ci.sql",
    "wave60/q9_allwave_fiscal_year_aggregation_53_62.sql",
    "wave60/q8_fiscal_year_x_family_rollup.sql",
    "wave58/q5_allwave_grand_aggregate.sql",
    "wave82/q26_wave80_82_supply_esg_ip_x_jsic.sql",
    "wave85/q31_wave83_85_x_jsic_intersection.sql",
    # ---- 26-30 wave98/99/100/101 latest cross-joins ----
    "wave98/Q53_allwave_grand_aggregate_top14_families.sql",
    "wave99/Q57_allwave_grand_aggregate_wave_95_97.sql",
    "wave100/Q61_allwave_grand_aggregate_wave_95_99.sql",
    "wave100/Q58_outcome_x_cost_band_x_evidence_freshness.sql",
    "wave98/Q51_wave82_85_89_91_94_jsic_small_cohort_5way.sql",
]


def _import_boto3() -> Any:
    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]

        return boto3
    except ImportError as exc:  # pragma: no cover - env guard
        raise RuntimeError("boto3 not installed; pip install boto3") from exc


def _session(profile: str, region: str) -> Any:
    boto3 = _import_boto3()
    return boto3.Session(profile_name=profile, region_name=region)


def _pick_query_for_now(now: _dt.datetime) -> tuple[str, int]:
    """Cycle: query_idx = (day_of_year * 11 + minute_of_day) mod N.

    Returns ``(relative_path, fiscal_year)``. Fiscal year rotates 2020-2029.
    """
    doy = now.timetuple().tm_yday
    mod = (doy * 11 + now.hour * 60 + now.minute) % len(TOP_QUERIES_RANKED)
    fy = 2020 + (now.minute % 10)
    return TOP_QUERIES_RANKED[mod], fy


def _substitute_fiscal_year(sql: str, fiscal_year: int) -> str:
    """Inject a deterministic WHERE filter on fiscal_year if the SQL has one.

    Most big_queries don't carry a literal ``:fiscal_year`` placeholder; for
    those we suffix a ``/* fy=YYYY */`` SQL comment so the query fingerprint
    differs by FY (defeats Athena result reuse).
    """
    if ":fiscal_year" in sql:
        return sql.replace(":fiscal_year", str(fiscal_year))
    return sql + f"\n-- fy_rotate={fiscal_year}\n"


def _load_query(rel_path: str) -> str:
    abs_path = BIG_QUERIES_DIR / rel_path
    if not abs_path.exists():
        raise FileNotFoundError(f"Athena SQL missing: {abs_path}")
    return abs_path.read_text(encoding="utf-8")


def _emit_cw_metric(session: Any, cost_usd: float, bytes_scanned: int, query_rel_path: str) -> None:
    cw = session.client("cloudwatch")
    try:
        cw.put_metric_data(
            Namespace=METRIC_NAMESPACE,
            MetricData=[
                {
                    "MetricName": "AthenaSustainedQueryCostUSD",
                    "Value": cost_usd,
                    "Unit": "None",
                    "Dimensions": [
                        {"Name": "Workgroup", "Value": WORKGROUP},
                        {"Name": "Lane", "Value": "E"},
                    ],
                },
                {
                    "MetricName": "AthenaSustainedQueryBytesScanned",
                    "Value": float(bytes_scanned),
                    "Unit": "Bytes",
                    "Dimensions": [
                        {"Name": "Workgroup", "Value": WORKGROUP},
                        {"Name": "Lane", "Value": "E"},
                    ],
                },
            ],
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] CW metric emit failed: {exc}", file=sys.stderr)


def _lambda_tmp_ledger_dir() -> pathlib.Path:
    """Lambda read-only FS fallback. Uses tempfile-style env override, /tmp default.

    The ``LAMBDA_LEDGER_DIR`` env var lets operators redirect the fallback
    path (Lambda layer + EFS, for instance); when unset, fall back to the
    Lambda-writable ``/tmp`` mount, the canonical scratch surface for
    AWS Lambda (the only writable path on the Lambda root FS).
    """
    explicit = os.environ.get("LAMBDA_LEDGER_DIR")
    if explicit:
        return pathlib.Path(explicit)
    return pathlib.Path("/tmp") / "athena_sustained_ledger"  # nosec B108


def _append_ledger(record: dict[str, Any]) -> None:
    ledger_root = LEDGER_DIR
    try:
        ledger_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        ledger_root = _lambda_tmp_ledger_dir()
        ledger_root.mkdir(parents=True, exist_ok=True)
    today = _dt.datetime.now(_UTC).strftime("%Y-%m-%d")
    ledger_path = ledger_root / f"sustained_{today}.jsonl"
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _run_once(
    *,
    session: Any,
    poll_max_sec: int,
    dry_run: bool,
    query_rel_path: str | None = None,
) -> dict[str, Any]:
    now = _dt.datetime.now(_UTC)
    if query_rel_path is None:
        rel_path, fy = _pick_query_for_now(now)
    else:
        rel_path = query_rel_path
        fy = 2020 + (now.minute % 10)

    sql_template = _load_query(rel_path)
    sql = _substitute_fiscal_year(sql_template, fy)

    record: dict[str, Any] = {
        "ts_utc": now.isoformat(timespec="seconds"),
        "lane": "E",
        "query_rel_path": rel_path,
        "fiscal_year_rotate": fy,
        "workgroup": WORKGROUP,
        "database": DATABASE,
        "dry_run": dry_run,
    }

    if dry_run:
        record.update({"state": "DRY_RUN", "execution_id": None})
        print(json.dumps(record, ensure_ascii=False))
        return record

    athena = session.client("athena")
    start_resp = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": DATABASE},
        WorkGroup=WORKGROUP,
        ResultConfiguration={"OutputLocation": OUTPUT_S3},
    )
    execution_id = start_resp["QueryExecutionId"]
    record["execution_id"] = execution_id

    deadline = time.monotonic() + poll_max_sec
    final_state: str = "UNKNOWN"
    stats: dict[str, Any] = {}
    while time.monotonic() < deadline:
        info = athena.get_query_execution(QueryExecutionId=execution_id)
        exec_obj = info["QueryExecution"]
        st = exec_obj["Status"]["State"]
        if st in ("SUCCEEDED", "FAILED", "CANCELLED"):
            final_state = st
            stats = exec_obj.get("Statistics", {}) or {}
            if st != "SUCCEEDED":
                record["reason"] = exec_obj["Status"].get("StateChangeReason", "")
            break
        time.sleep(2)
    else:
        final_state = "POLL_TIMEOUT"

    bytes_scanned = int(stats.get("DataScannedInBytes") or 0)
    wall_ms = int(stats.get("EngineExecutionTimeInMillis") or 0)
    cost_usd = (bytes_scanned / (1024**4)) * USD_PER_TB

    record.update(
        {
            "state": final_state,
            "bytes_scanned": bytes_scanned,
            "wall_ms": wall_ms,
            "cost_usd": round(cost_usd, 6),
        }
    )
    _append_ledger(record)
    _emit_cw_metric(session, cost_usd, bytes_scanned, rel_path)
    print(json.dumps(record, ensure_ascii=False))
    return record


def _run_sustained(
    *,
    session: Any,
    interval_sec: int,
    poll_max_sec: int,
    dry_run: bool,
    max_iterations: int | None,
) -> None:
    fired = 0
    target = max_iterations if max_iterations is not None else DAILY_TARGET_QUERIES
    while fired < target:
        # ~4% random skip to cap at ~300/day from 288 fires/day at 5-min cadence
        if random.random() < 0.04:  # noqa: S311
            print(
                json.dumps(
                    {
                        "ts_utc": _dt.datetime.now(_UTC).isoformat(timespec="seconds"),
                        "state": "SKIPPED_CAP",
                    }
                )
            )
        else:
            try:
                _run_once(session=session, poll_max_sec=poll_max_sec, dry_run=dry_run)
                fired += 1
            except Exception as exc:  # noqa: BLE001
                print(f"[error] sustained fire failed: {exc}", file=sys.stderr)
        time.sleep(interval_sec)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--once",
        action="store_true",
        help="Run one query and exit (matches Lambda-fire semantics)",
    )
    ap.add_argument(
        "--sustained",
        action="store_true",
        help="Run continuously at --interval-sec cadence (local cron)",
    )
    ap.add_argument("--interval-sec", type=int, default=300, help="cadence (sustained mode)")
    ap.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="cap sustained fires (default: DAILY_TARGET_QUERIES = 300)",
    )
    ap.add_argument("--poll-max-sec", type=int, default=120, help="max Athena poll time per query")
    ap.add_argument(
        "--profile", default=DEFAULT_PROFILE, help="AWS profile (default bookyou-recovery)"
    )
    ap.add_argument("--region", default=DEFAULT_REGION, help="AWS region")
    ap.add_argument("--dry-run", action="store_true", help="print intended query, do not execute")
    ap.add_argument(
        "--query",
        default=None,
        help=(
            "Force a specific query (relative path under big_queries/); default: round-robin top-30"
        ),
    )
    args = ap.parse_args()

    if not (args.once or args.sustained):
        ap.error("must specify --once or --sustained")

    session = _session(args.profile, args.region)
    if args.once:
        _run_once(
            session=session,
            poll_max_sec=args.poll_max_sec,
            dry_run=args.dry_run,
            query_rel_path=args.query,
        )
        return 0
    _run_sustained(
        session=session,
        interval_sec=args.interval_sec,
        poll_max_sec=args.poll_max_sec,
        dry_run=args.dry_run,
        max_iterations=args.max_iterations,
    )
    return 0


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """EventBridge invocation entry point — runs exactly one query and returns.

    The EventBridge rule ``jpcite-athena-sustained-2026-05`` fires this on a
    5-minute cadence (288 fires / day). We do NOT skip-cap inside the Lambda
    (the cadence already caps daily volume); skip-cap logic lives in the
    sustained-mode local runner.
    """
    boto3 = _import_boto3()
    session = boto3.Session(region_name=DEFAULT_REGION)
    poll = int(event.get("poll_max_sec", 120)) if isinstance(event, dict) else 120
    rec = _run_once(session=session, poll_max_sec=poll, dry_run=False, query_rel_path=None)
    return {"ok": rec.get("state") == "SUCCEEDED", "record": rec}


if __name__ == "__main__":
    raise SystemExit(main())
