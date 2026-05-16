#!/usr/bin/env python3
"""PERF-3 — Migrate top-N JsonSerDe packet tables to ZSTD Parquet + partition projection.

Context: Wave 67 Q11 showed the Wave 53-67 corpus is dominated by foundation
packets (houjin_360 + acceptance_probability + program_lineage = ~11.6M rows
out of ~11.8M total). All packet_* tables are currently registered against
Glue with the openx JsonSerDe (1 JSON file per packet, full S3 scan on every
Athena query). Migrating to ZSTD Parquet via CTAS yields:

  1. Column pruning at scan time (vs JSON full-file read).
  2. ZSTD compression typically 5-10x denser than minified JSON.
  3. Partition projection on cohort axes (subject_kind / fiscal_year /
     jsic_major / prefecture) lets Athena skip partition entirely.

Target — top 10 by row count, top 3 to migrate first (smoke):

  Top 10 (from Wave 67 Q11 + Glue catalog 2026-05-16 probe):
    1. packet_acceptance_probability         ~225K rows (cohort-partitionable)
    2. packet_entity_360_summary_v1          ~100K
    3. packet_houjin_360                     ~86K  (subject.kind/id)
    4. packet_entity_court_360_v1            ~100K
    5. packet_entity_partner_360_v1          ~100K
    6. packet_entity_risk_360_v1             ~100K
    7. packet_entity_subsidy_360_v1          ~100K
    8. packet_entity_succession_360_v1       ~100K
    9. packet_entity_temporal_pulse_v1       ~100K
   10. packet_program_lineage_v1             ~11K

  Top 3 (smoke first): acceptance_probability + houjin_360 + entity_360_summary_v1

Each CTAS:
  - Writes ZSTD Parquet to s3://jpcite-credit-993693061769-202605-derived/
    parquet/<table_basename>/ (separate bucket prefix; source unchanged)
  - Registers <table>_parquet in Glue with partition columns picked from
    the cohort axis (acceptance_probability: jsic_major+fiscal_year;
    houjin_360 + entity_*: subject_kind always 'houjin'; we pick
    pseudo-partition by first 2 chars of id for fan-out).
  - Source JSON tables are NOT dropped. Both coexist; downstream queries
    can swap.

Constraints honored:
  - bookyou-recovery profile (verified UserId AIDA6OXFY2KEYSUNJDC63).
  - region ap-northeast-1.
  - cost band <$5 (CTAS scan cost is the source-JSON read; tables already
    fit under Wave 67 budget caps).
  - workgroup jpcite-credit-2026-05 (BytesScannedCutoffPerQuery=100 GB
    cap still honored).
  - [lane:solo] commit marker per PERF series.

Usage:
  python scripts/aws_credit_ops/athena_parquet_migrate.py
      [--tables packet_acceptance_probability,packet_houjin_360,packet_entity_360_summary_v1]
      [--dry-run]
      [--compare-scan]      # run identical SELECT on JSON + Parquet, report scan
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.aws_credit_ops._aws import get_session

DATABASE = "jpcite_credit_2026_05"
WORKGROUP = "jpcite-credit-2026-05"
RESULT_S3 = "s3://jpcite-credit-993693061769-202605-derived/athena-results/"
PARQUET_S3_BASE = "s3://jpcite-credit-993693061769-202605-derived/parquet"
ATHENA_USD_PER_TB = 5.00
BUDGET_CAP_USD = 5.0
POLL_INTERVAL_SEC = 5
MAX_POLL_SEC = 1800

PROFILE = os.environ.get("AWS_PROFILE", "bookyou-recovery")
REGION = os.environ.get("AWS_REGION", "ap-northeast-1")


@dataclass
class TableSpec:
    """Per-table migration descriptor.

    name:       source Glue table (JsonSerDe).
    parquet:    target Glue table name (`<name>_parquet`).
    partition:  expression list for `partitioned_by` (in CTAS order).
    select_extras: SQL fragments to derive partition cols inside CTAS.
    sample_sql: identical-shape SELECT used for the JSON vs Parquet
                scan-size comparison.
    """

    name: str
    parquet: str
    partition_cols: list[str]
    select_extras: list[str]
    sample_sql_template: str  # use {table} placeholder


# Top 3 migration specs.
#
# For json-typed columns (subject / cohort_definition stored as `string`
# in Glue), we use `json_extract_scalar` to pull the partition key.
TOP_3: list[TableSpec] = [
    TableSpec(
        name="packet_acceptance_probability",
        parquet="packet_acceptance_probability_parquet",
        partition_cols=["jsic_major", "fiscal_year"],
        select_extras=[
            "COALESCE(json_extract_scalar(cohort_definition, '$.jsic_major'), 'unknown') AS jsic_major",
            "COALESCE(json_extract_scalar(cohort_definition, '$.fiscal_year'), 'unknown') AS fiscal_year",
        ],
        sample_sql_template=(
            "SELECT COUNT(*) AS row_cnt, AVG(probability_estimate) AS avg_prob FROM {table}"
        ),
    ),
    TableSpec(
        name="packet_houjin_360",
        parquet="packet_houjin_360_parquet",
        partition_cols=["subject_kind"],
        select_extras=[
            "COALESCE(json_extract_scalar(subject, '$.kind'), 'unknown') AS subject_kind",
        ],
        sample_sql_template=(
            "SELECT COUNT(*) AS row_cnt, "
            "COUNT(DISTINCT json_extract_scalar(subject, '$.id')) AS distinct_houjin "
            "FROM {table}"
        ),
    ),
    TableSpec(
        name="packet_entity_360_summary_v1",
        parquet="packet_entity_360_summary_v1_parquet",
        partition_cols=["subject_kind"],
        select_extras=[
            "COALESCE(json_extract_scalar(subject, '$.kind'), 'unknown') AS subject_kind",
        ],
        sample_sql_template=("SELECT COUNT(*) AS row_cnt FROM {table}"),
    ),
]

# Full top-10 list (for record-keeping; only first 3 migrate in this run)
TOP_10_NAMES = [
    "packet_acceptance_probability",
    "packet_entity_360_summary_v1",
    "packet_houjin_360",
    "packet_entity_court_360_v1",
    "packet_entity_partner_360_v1",
    "packet_entity_risk_360_v1",
    "packet_entity_subsidy_360_v1",
    "packet_entity_succession_360_v1",
    "packet_entity_temporal_pulse_v1",
    "packet_program_lineage_v1",
]


# PERF-24 (2026-05-16) — top 10 expansion: ranks 4-10.
#
# Schema observations (Glue probe 2026-05-16):
#   - All 6 entity_*_360_v1 / entity_temporal_pulse_v1 tables share the same
#     `subject` JSON column shape used by packet_houjin_360 + entity_360_summary_v1.
#     subject_kind partition is the right axis (subject.kind is typically
#     'houjin' for these tables — 1-value partition, but column pruning is
#     the real win).
#   - packet_program_lineage_v1 has only 11 columns (no `subject`, no
#     `cohort_definition`; the `program` column carries identity). There is
#     no natural cohort axis; we treat it as flat (partition_cols=[]) and
#     rely on Parquet ZSTD column pruning alone.
TOP_7_REMAINING: list[TableSpec] = [
    TableSpec(
        name="packet_entity_court_360_v1",
        parquet="packet_entity_court_360_v1_parquet",
        partition_cols=["subject_kind"],
        select_extras=[
            "COALESCE(json_extract_scalar(subject, '$.kind'), 'unknown') AS subject_kind",
        ],
        sample_sql_template="SELECT COUNT(*) AS row_cnt FROM {table}",
    ),
    TableSpec(
        name="packet_entity_partner_360_v1",
        parquet="packet_entity_partner_360_v1_parquet",
        partition_cols=["subject_kind"],
        select_extras=[
            "COALESCE(json_extract_scalar(subject, '$.kind'), 'unknown') AS subject_kind",
        ],
        sample_sql_template="SELECT COUNT(*) AS row_cnt FROM {table}",
    ),
    TableSpec(
        name="packet_entity_risk_360_v1",
        parquet="packet_entity_risk_360_v1_parquet",
        partition_cols=["subject_kind"],
        select_extras=[
            "COALESCE(json_extract_scalar(subject, '$.kind'), 'unknown') AS subject_kind",
        ],
        sample_sql_template="SELECT COUNT(*) AS row_cnt FROM {table}",
    ),
    TableSpec(
        name="packet_entity_subsidy_360_v1",
        parquet="packet_entity_subsidy_360_v1_parquet",
        partition_cols=["subject_kind"],
        select_extras=[
            "COALESCE(json_extract_scalar(subject, '$.kind'), 'unknown') AS subject_kind",
        ],
        sample_sql_template="SELECT COUNT(*) AS row_cnt FROM {table}",
    ),
    TableSpec(
        name="packet_entity_succession_360_v1",
        parquet="packet_entity_succession_360_v1_parquet",
        partition_cols=["subject_kind"],
        select_extras=[
            "COALESCE(json_extract_scalar(subject, '$.kind'), 'unknown') AS subject_kind",
        ],
        sample_sql_template="SELECT COUNT(*) AS row_cnt FROM {table}",
    ),
    TableSpec(
        name="packet_entity_temporal_pulse_v1",
        parquet="packet_entity_temporal_pulse_v1_parquet",
        partition_cols=["subject_kind"],
        select_extras=[
            "COALESCE(json_extract_scalar(subject, '$.kind'), 'unknown') AS subject_kind",
        ],
        sample_sql_template="SELECT COUNT(*) AS row_cnt FROM {table}",
    ),
    TableSpec(
        name="packet_program_lineage_v1",
        parquet="packet_program_lineage_v1_parquet",
        partition_cols=[],  # no natural cohort axis; flat table
        select_extras=[],
        sample_sql_template="SELECT COUNT(*) AS row_cnt FROM {table}",
    ),
]

# PERF-34 (2026-05-17) — ranks 11-30 sweep (20 more tables).
#
# Selection: ranked by query reference count across Wave 67/70/82 captured
# SQL files (the 17 executed queries with concrete bytes_scanned in
# `docs/_internal/ATHENA_QUERY_INDEX_2026_05_17.md`). Cutoff ranks 11..30.
# Ties broken by alphabetical name.
#
# Schema observation (Glue DESCRIBE probe 2026-05-17): most tables share
# the same shape used by the PERF-3/24 catalogue — `subject` JSON column +
# `cohort_definition` JSON column. We reuse the subject_kind partition
# axis (subject.kind is typically 'houjin'). The trademark/patent/business
# _partner/program_amendment_timeline families carry an explicit
# `prefecture` column but we do NOT promote it to a partition: high
# cardinality on flat 100k-row tables hurts scan latency more than ZSTD
# column pruning helps (PERF-3 lesson).
TOP_20_PERF34: list[TableSpec] = [
    TableSpec(
        name=name,
        parquet=f"{name}_parquet",
        partition_cols=["subject_kind"],
        select_extras=[
            "COALESCE(json_extract_scalar(subject, '$.kind'), 'unknown') AS subject_kind",
        ],
        sample_sql_template="SELECT COUNT(*) AS row_cnt FROM {table}",
    )
    for name in [
        # Rank 11-20 (highest ref count first)
        "packet_trademark_industry_density_v1",  # 13 refs
        "packet_patent_corp_360_v1",  # 10
        "packet_succession_program_matching_v1",  # 9
        "packet_region_industry_match_v1",  # 8
        "packet_program_amendment_timeline_v2",  # 8
        "packet_prefecture_program_heatmap_v1",  # 8
        "packet_business_partner_360_v1",  # 8
        "packet_board_member_overlap_v1",  # 8
        "packet_kfs_saiketsu_industry_radar_v1",  # 7
        "packet_enforcement_seasonal_trend_v1",  # 7
        # Rank 21-30
        "packet_adoption_fiscal_cycle_v1",  # 7
        "packet_trademark_brand_protection_v1",  # 6
        "packet_kanpou_gazette_watch_v1",  # 6
        "packet_gbiz_invoice_dispatch_match_v1",  # 6
        "packet_environmental_compliance_radar_v1",  # 6
        "packet_bond_issuance_pattern_v1",  # 6
        "packet_houjin_parent_subsidiary_v1",  # 5
        "packet_founding_succession_chain_v1",  # 5
        "packet_climate_transition_plan_v1",  # 5
        "packet_carbon_reporting_compliance_v1",  # 5
    ]
]

# Combined catalog of all specs the runner knows about (top 3 + top 7 + top 20).
ALL_SPECS: list[TableSpec] = TOP_3 + TOP_7_REMAINING + TOP_20_PERF34


def build_ctas(spec: TableSpec) -> str:
    """Compose the CTAS SQL for one table.

    Atomic: drops _parquet if it exists then CTAS-recreates. Athena
    does NOT support `CREATE OR REPLACE TABLE`, so we issue a separate
    DROP TABLE IF EXISTS up front via run_ddl().

    PERF-24 (2026-05-16): when `partition_cols` is empty the CTAS omits
    the `partitioned_by` clause entirely (Athena rejects an empty
    ARRAY[] there). The `external_location` is still set so the Parquet
    files land in the canonical s3://…/parquet/<source>/ prefix; this
    requires the workgroup's EnforceWorkGroupConfiguration to be
    temporarily disabled before CTAS (see PERF-3 doc).
    """
    extra_select_clause = ",\n  " + ",\n  ".join(spec.select_extras) if spec.select_extras else ""
    with_clauses = [
        "format = 'PARQUET'",
        "parquet_compression = 'ZSTD'",
        f"external_location = '{PARQUET_S3_BASE}/{spec.name}/'",
    ]
    if spec.partition_cols:
        partitioned_by = ", ".join(f"'{c}'" for c in spec.partition_cols)
        with_clauses.append(f"partitioned_by = ARRAY[{partitioned_by}]")
    with_block = ",\n  ".join(with_clauses)
    return f"""
CREATE TABLE {spec.parquet}
WITH (
  {with_block}
) AS
SELECT
  *{extra_select_clause}
FROM {spec.name}
""".strip()


def run_ddl(athena: Any, sql: str) -> dict[str, Any]:
    """Submit a DDL/DML query, block until terminal, return QueryExecution.

    Used for both DROP-TABLE-IF-EXISTS and CTAS.
    """
    resp = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": DATABASE},
        WorkGroup=WORKGROUP,
        ResultConfiguration={"OutputLocation": RESULT_S3},
    )
    qid: str = resp["QueryExecutionId"]
    waited = 0
    while waited <= MAX_POLL_SEC:
        info: dict[str, Any] = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
        state = info["Status"]["State"]
        if state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return info
        time.sleep(POLL_INTERVAL_SEC)
        waited += POLL_INTERVAL_SEC
    raise RuntimeError(f"Athena {qid} timeout after {MAX_POLL_SEC}s")


def summarize(label: str, info: dict[str, Any]) -> dict[str, Any]:
    """Reduce QueryExecution to bytes/cost/ms record."""
    status = info["Status"]
    stats = info.get("Statistics", {}) or {}
    bytes_scanned = int(stats.get("DataScannedInBytes", 0) or 0)
    total_ms = int(stats.get("TotalExecutionTimeInMillis", 0) or 0)
    cost_usd = round((bytes_scanned / (1024**4)) * ATHENA_USD_PER_TB, 6)
    return {
        "label": label,
        "exec_id": info["QueryExecutionId"],
        "state": status["State"],
        "bytes_scanned": bytes_scanned,
        "bytes_mb": round(bytes_scanned / (1024**2), 4),
        "cost_usd": cost_usd,
        "total_ms": total_ms,
        "state_reason": status.get("StateChangeReason", ""),
    }


def migrate_one(athena: Any, spec: TableSpec, *, dry_run: bool) -> dict[str, Any]:
    """Drop+CTAS one table. dry_run prints SQL and skips execution."""
    drop_sql = f"DROP TABLE IF EXISTS {spec.parquet}"
    ctas_sql = build_ctas(spec)
    if dry_run:
        print(f"\n--- DRY-RUN: {spec.name} → {spec.parquet} ---", flush=True)
        print(drop_sql, flush=True)
        print(ctas_sql, flush=True)
        return {"label": spec.name, "state": "DRY_RUN"}
    print(f"[migrate] {spec.name}: DROP {spec.parquet} if exists", flush=True)
    drop_info = run_ddl(athena, drop_sql)
    if drop_info["Status"]["State"] != "SUCCEEDED":
        return {
            "label": spec.name,
            "state": "DROP_FAILED",
            "reason": drop_info["Status"].get("StateChangeReason", ""),
        }
    print(f"[migrate] {spec.name}: CTAS Parquet", flush=True)
    ctas_info = run_ddl(athena, ctas_sql)
    row = summarize(f"ctas_{spec.name}", ctas_info)
    return row


def compare_scan(athena: Any, spec: TableSpec) -> dict[str, Any]:
    """Run identical SELECT on JSON + Parquet, return both scan sizes."""
    json_sql = spec.sample_sql_template.format(table=spec.name)
    parquet_sql = spec.sample_sql_template.format(table=spec.parquet)
    print(f"[compare] {spec.name}: scan JSON…", flush=True)
    info_json = run_ddl(athena, json_sql)
    row_json = summarize(f"scan_{spec.name}_json", info_json)
    print(f"[compare] {spec.name}: scan Parquet…", flush=True)
    info_par = run_ddl(athena, parquet_sql)
    row_par = summarize(f"scan_{spec.name}_parquet", info_par)
    if row_json["bytes_scanned"] > 0:
        reduction_pct = round(
            100.0 * (1.0 - row_par["bytes_scanned"] / row_json["bytes_scanned"]),
            2,
        )
    else:
        reduction_pct = 0.0
    return {
        "label": spec.name,
        "json": row_json,
        "parquet": row_par,
        "reduction_pct": reduction_pct,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PERF-3 Athena Parquet migration")
    p.add_argument(
        "--tables",
        default="",
        help="Comma-separated table names (subset of top 3). Default: all 3.",
    )
    p.add_argument("--dry-run", action="store_true", help="Print SQL only, no execution.")
    p.add_argument(
        "--compare-scan",
        action="store_true",
        help="Run identical SELECT on JSON + Parquet, report scan-size delta.",
    )
    p.add_argument(
        "--skip-migrate",
        action="store_true",
        help="Skip CTAS step (e.g., when comparing only).",
    )
    p.add_argument(
        "--out",
        default="out/athena_parquet_migrate_2026_05_16.json",
        help="JSON ledger path (default preserves PERF-3 layout; PERF-24 uses a separate path).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    session = get_session(region_name=REGION, profile_name=PROFILE)
    athena = session.client("athena")

    if args.tables:
        wanted = set(args.tables.split(","))
        # PERF-24: search the full top-10 catalog (TOP_3 + TOP_7_REMAINING)
        # so the same runner can target the remaining 7 expansion tables.
        specs = [s for s in ALL_SPECS if s.name in wanted]
    else:
        specs = TOP_3

    if not specs:
        print("[main] no tables to migrate", file=sys.stderr)
        return 2

    migrate_rows: list[dict[str, Any]] = []
    if not args.skip_migrate:
        for spec in specs:
            try:
                row = migrate_one(athena, spec, dry_run=args.dry_run)
            except Exception as e:  # noqa: BLE001
                row = {"label": spec.name, "state": "EXCEPTION", "error": str(e)[:300]}
            migrate_rows.append(row)
            state = row.get("state", "?")
            bytes_mb = row.get("bytes_mb", "n/a")
            cost = row.get("cost_usd", "n/a")
            print(
                f"[done]   {spec.name:42s} state={state:12s} bytes_mb={bytes_mb} cost_usd={cost}",
                flush=True,
            )

    compare_rows: list[dict[str, Any]] = []
    if args.compare_scan and not args.dry_run:
        for spec in specs:
            try:
                cmp = compare_scan(athena, spec)
            except Exception as e:  # noqa: BLE001
                cmp = {"label": spec.name, "state": "EXCEPTION", "error": str(e)[:300]}
            compare_rows.append(cmp)
            if "json" in cmp and "parquet" in cmp:
                print(
                    f"[scan]   {spec.name:42s} "
                    f"json_mb={cmp['json']['bytes_mb']:>10}  "
                    f"parquet_mb={cmp['parquet']['bytes_mb']:>10}  "
                    f"reduction={cmp['reduction_pct']}%",
                    flush=True,
                )

    summary = {
        "database": DATABASE,
        "workgroup": WORKGROUP,
        "rate_usd_per_tb": ATHENA_USD_PER_TB,
        "budget_cap_usd": BUDGET_CAP_USD,
        "tables_attempted": [s.name for s in specs],
        "migrate_rows": migrate_rows,
        "compare_rows": compare_rows,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n[summary] wrote {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
