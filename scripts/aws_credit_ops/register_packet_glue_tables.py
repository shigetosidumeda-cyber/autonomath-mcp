#!/usr/bin/env python3
"""Register Glue Catalog tables for all packet outcomes + 3 packet sources.

Creates one EXTERNAL TABLE per S3 prefix under
``s3://jpcite-credit-993693061769-202605-derived/`` so Athena can run
cross-source / cross-join queries on the populated derived corpus.

Each row corresponds to one JSON document under the prefix; the table
schema deliberately uses minimal STRING / DOUBLE / BIGINT columns plus
a generic ``data`` JSON column so the regression-resistant downstream
queries can ``json_extract(...)`` on any nested field without re-running
this script. Tables that hold nested arrays (``records`` /
``top_houjin`` / ``metrics``) keep them as ``STRING`` JSON blobs to
side-step JSON-vs-Parquet schema drift.

Tables registered:

- ``packet_houjin_360``         — ``houjin_360/`` (86,849 JSON)
- ``packet_acceptance_probability`` — ``acceptance_probability/`` (225,600 JSON)
- ``packet_program_lineage``    — ``program_lineage/`` (11,601 JSON, uploading)
- 16 Wave 53 outcome tables ``packet_<outcome_kind>`` for each prefix

All tables share the JsonSerDe ``org.openx.data.jsonserde.JsonSerDe``
with ``ignore.malformed.json = true`` and ``case.insensitive = false``.

Idempotent: ``CREATE EXTERNAL TABLE IF NOT EXISTS`` only. Re-running
the script is a no-op for already-registered tables.

Reads AWS_PROFILE=bookyou-recovery / REGION=ap-northeast-1 by default.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import boto3

DATABASE = "jpcite_credit_2026_05"
WORKGROUP = "jpcite-credit-2026-05"
BUCKET = "jpcite-credit-993693061769-202605-derived"
RESULT_S3 = f"s3://{BUCKET}/athena-results/"
PROFILE = os.environ.get("AWS_PROFILE", "bookyou-recovery")
REGION = os.environ.get("AWS_REGION", "ap-northeast-1")

# Table registry: (table_name, prefix, columns) — columns is a list of
# (column_name, athena_type). Columns are flat top-level fields commonly
# present in the JSON; nested structures live in raw_json STRING below.
PACKET_TABLES: list[tuple[str, str, list[tuple[str, str]]]] = [
    # 3 packet sources (the high-row-count tier).
    (
        "packet_houjin_360",
        "houjin_360/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_id", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),  # JSON struct kept as string
            ("coverage", "string"),
            ("sources", "string"),
            ("records", "string"),
            ("sections", "string"),
        ],
    ),
    (
        "packet_acceptance_probability",
        "acceptance_probability/",
        [
            ("package_kind", "string"),
            ("probability_estimate", "double"),
            ("n_sample", "bigint"),
            ("n_eligible_programs", "bigint"),
            ("freshest_announced_at", "string"),
            ("cohort_definition", "string"),
            ("confidence_interval", "string"),
            ("disclaimer", "string"),
            ("known_gaps", "string"),
            ("adjacency_suggestions", "string"),
            ("header", "string"),
        ],
    ),
    (
        "packet_program_lineage",
        "program_lineage/",
        [
            ("package_kind", "string"),
            ("athena_workgroup", "string"),
            ("header", "string"),
            ("program", "string"),
            ("legal_basis_chain", "string"),
            ("notice_chain", "string"),
            ("saiketsu_chain", "string"),
            ("precedent_chain", "string"),
            ("amendment_timeline", "string"),
            ("coverage_score", "string"),
            ("chain_counts", "string"),
            ("billing_unit", "bigint"),
            ("disclaimer", "string"),
        ],
    ),
    # 16 Wave 53 outcome tables.
    (
        "packet_application_strategy_v1",
        "application_strategy_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("generated_at", "string"),
            ("producer", "string"),
            ("schema_version", "string"),
            ("subject", "string"),
            ("strategy", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_bid_opportunity_matching_v1",
        "bid_opportunity_matching_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("cohort_definition", "string"),
            ("metrics", "string"),
            ("matches", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_cohort_program_recommendation_v1",
        "cohort_program_recommendation_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("cohort_definition", "string"),
            ("recommendations", "string"),
            ("metrics", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_company_public_baseline_v1",
        "company_public_baseline_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("coverage", "string"),
            ("sources", "string"),
            ("records", "string"),
        ],
    ),
    (
        "packet_enforcement_industry_heatmap_v1",
        "enforcement_industry_heatmap_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("cohort_definition", "string"),
            ("metrics", "string"),
            ("top_houjin", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_invoice_houjin_cross_check_v1",
        "invoice_houjin_cross_check_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("nta_invoice", "string"),
            ("gbiz_master", "string"),
            ("mismatch", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_invoice_registrant_public_check_v1",
        "invoice_registrant_public_check_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("nta_status", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_kanpou_gazette_watch_v1",
        "kanpou_gazette_watch_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("entries", "string"),
            ("metrics", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_local_government_subsidy_aggregator_v1",
        "local_government_subsidy_aggregator_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("cohort_definition", "string"),
            ("programs", "string"),
            ("metrics", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_permit_renewal_calendar_v1",
        "permit_renewal_calendar_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("schedule", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_program_law_amendment_impact_v1",
        "program_law_amendment_impact_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("amendment_chain", "string"),
            ("impacted_programs", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_regulatory_change_radar_v1",
        "regulatory_change_radar_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("cohort_definition", "string"),
            ("signals", "string"),
            ("metrics", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_subsidy_application_timeline_v1",
        "subsidy_application_timeline_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("cohort_definition", "string"),
            ("rounds", "string"),
            ("metrics", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_succession_program_matching_v1",
        "succession_program_matching_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("matches", "string"),
            ("metrics", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_tax_treaty_japan_inbound_v1",
        "tax_treaty_japan_inbound_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("treaty_summary", "string"),
            ("withholding", "string"),
            ("sources", "string"),
        ],
    ),
    (
        "packet_vendor_due_diligence_v1",
        "vendor_due_diligence_v1/",
        [
            ("object_id", "string"),
            ("object_type", "string"),
            ("package_kind", "string"),
            ("created_at", "string"),
            ("subject", "string"),
            ("dd_checks", "string"),
            ("score", "string"),
            ("sources", "string"),
        ],
    ),
]


def render_ddl(table: str, prefix: str, columns: list[tuple[str, str]]) -> str:
    """Render a single ``CREATE EXTERNAL TABLE IF NOT EXISTS`` for a packet table."""
    col_block = ",\n  ".join(f"{name} {sql_type}" for name, sql_type in columns)
    location = f"s3://{BUCKET}/{prefix}"
    return f"""CREATE EXTERNAL TABLE IF NOT EXISTS {DATABASE}.{table} (
  {col_block}
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
WITH SERDEPROPERTIES (
  'ignore.malformed.json' = 'true',
  'case.insensitive' = 'false'
)
STORED AS INPUTFORMAT 'org.apache.hadoop.mapred.TextInputFormat'
OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat'
LOCATION '{location}'
TBLPROPERTIES (
  'classification' = 'json',
  'project' = 'jpcite',
  'credit_run' = '2026-05',
  'auto_stop' = '2026-05-29',
  'contract' = 'jpcir.packet.v1'
)"""


def run_athena_ddl(athena: Any, ddl: str) -> str:
    """Submit a DDL via Athena and block until SUCCEEDED / FAILED."""
    resp = athena.start_query_execution(
        QueryString=ddl,
        QueryExecutionContext={"Database": DATABASE},
        WorkGroup=WORKGROUP,
        ResultConfiguration={"OutputLocation": RESULT_S3},
    )
    qid: str = resp["QueryExecutionId"]
    for _ in range(60):
        status = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        state = status["State"]
        if state == "SUCCEEDED":
            return qid
        if state in {"FAILED", "CANCELLED"}:
            reason = status.get("StateChangeReason", "")
            raise RuntimeError(f"DDL FAILED ({qid}): {reason}\nSQL=\n{ddl[:400]}")
        time.sleep(1)
    raise RuntimeError(f"DDL timeout ({qid})")


def main() -> None:
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    athena = session.client("athena")
    glue = session.client("glue")

    summary: list[dict[str, Any]] = []
    for table, prefix, cols in PACKET_TABLES:
        ddl = render_ddl(table, prefix, cols)
        try:
            qid = run_athena_ddl(athena, ddl)
            # Sanity: confirm in Glue catalog.
            glue.get_table(DatabaseName=DATABASE, Name=table)
            summary.append({"table": table, "prefix": prefix, "exec_id": qid, "state": "OK"})
            print(f"[ok] {table:48s}  {prefix:42s}  exec={qid}", flush=True)
        except Exception as e:  # noqa: BLE001
            summary.append({"table": table, "prefix": prefix, "state": "FAIL", "error": str(e)[:200]})
            print(f"[fail] {table:48s}  {prefix:42s}  err={str(e)[:160]}", flush=True)

    out_path = "out/glue_packet_table_register.json"
    os.makedirs("out", exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump({"database": DATABASE, "tables": summary}, fh, indent=2)
    print(f"[summary] wrote {out_path}  total={len(summary)}  ok={sum(1 for s in summary if s['state']=='OK')}")


if __name__ == "__main__":
    main()
    sys.exit(0)
