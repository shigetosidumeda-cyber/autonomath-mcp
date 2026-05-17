#!/usr/bin/env python3
"""Lane K Phase 2 — Glue ETL packet-to-parquet driver (2026-05-17).

Drives the Lane K $230/day Glue ETL burn lever by:

1. Uploading the Spark ETL script
   (``infra/aws/glue/jpcite_packet_to_parquet_etl.py``) to S3 under
   ``s3://jpcite-credit-993693061769-202605-derived/glue/scripts/lane_k_phase2/``.
2. Creating (or updating) the Glue Job
   ``jpcite-packet-to-parquet-2026-05-17`` with 50 DPU PySpark
   (``WorkerType=G.1X``, ``NumberOfWorkers=50``).
3. Reading the table list from
   ``/tmp/lane_k/glue_etl_tables.txt`` (1 source table per line) — built
   by the same task brief that ran
   ``aws glue get-tables --database-name jpcite_credit_2026_05`` and
   filtered out tables already paired with a ``*_parquet`` variant.
4. For each source table, submitting one ``start-job-run`` with
   ``--source_table=<t>`` + ``--target_prefix=parquet_zstd_2026_05_17/<t>``.
   The driver waits between submissions so we don't blow past the AWS
   per-account concurrent Glue Job ceiling (default 50); the dispatch
   loop sleeps ``--submit-interval-sec`` (default 60) between submits.

Cost contract
-------------
50 DPU × $0.44 / DPU-hr = $22/hour. A single packet table at ~5 MB
JSON typically completes in under 1 minute, so the dominant cost is
Glue's billable DPU-minute floor (10 min minimum / Spark job).

  10 minutes × $22/hour = $3.67 per job
  $230/day target / $3.67 per job = ~63 jobs/day

To absorb ~$242/day target burn we submit ~67 runs/day (one every ~21
minutes) which leaves headroom for the 11-hour pacing window. The
driver default ``--submit-interval-sec 60`` is intentionally tighter so
the operator can throttle later with a knob bump; Lane J monitor
verifies realized burn against the budget cap.

Constraints honoured
--------------------
* AWS profile ``bookyou-recovery``; region ``ap-northeast-1``.
* IAM role ``jpcite-glue-crawler-role`` (R/W to derived bucket per
  ``jpcite_credit_derived_crawler.json``). Glue ETL reuses the same
  role since trust + inline policy already cover S3 access; no new IAM
  artifact lands.
* NO LLM calls — pure Glue + S3.
* ``DRY_RUN=1`` default. ``--commit`` lifts the dry-run guard and
  submits the actual ``aws glue start-job-run`` calls (user authorised
  this Lane K run per the 2026-05-17 task brief).
* robots.txt + per-source TOS honor — no new PDF crawl; this lever
  only re-formats already-landed JSON packets.
* ``[lane:solo]`` marker per dual-CLI atomic lane convention.

Usage
-----
::

    # Preview (dry-run default):
    .venv/bin/python scripts/aws_credit_ops/run_lane_k_glue_etl.py

    # Actual submission:
    .venv/bin/python scripts/aws_credit_ops/run_lane_k_glue_etl.py --commit

    # Throttle to a slower pace (use $130/day instead of $242/day):
    .venv/bin/python scripts/aws_credit_ops/run_lane_k_glue_etl.py \
        --commit --submit-interval-sec 120 --max-runs 35
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_PROFILE = "bookyou-recovery"
DEFAULT_REGION = "ap-northeast-1"
DEFAULT_DATABASE = "jpcite_credit_2026_05"
DEFAULT_BUCKET = "jpcite-credit-993693061769-202605-derived"
DEFAULT_JOB_NAME = "jpcite-packet-to-parquet-2026-05-17"
DEFAULT_ROLE_ARN = "arn:aws:iam::993693061769:role/jpcite-glue-crawler-role"
DEFAULT_SCRIPT_LOCAL = "infra/aws/glue/jpcite_packet_to_parquet_etl.py"
DEFAULT_SCRIPT_S3_PREFIX = "glue/scripts/lane_k_phase2/"
DEFAULT_TARGET_PREFIX_BASE = "parquet_zstd_2026_05_17"
# Operator-scratch path; the driver reads the table list from disk before
# any AWS call so the operator can review/edit it. The temp path is the
# documented contract (see `task brief 2026-05-17`), not arbitrary I/O.
DEFAULT_TABLES_FILE = "/tmp/lane_k/glue_etl_tables.txt"  # nosec B108
DEFAULT_LEDGER_PATH = "data/lane_k_glue_etl_ledger_2026_05_17.json"
DEFAULT_SUBMIT_INTERVAL_SEC = 60
DEFAULT_MAX_RUNS = 100
DEFAULT_DPU = 50  # G.1X workers; matches $0.44 / DPU-hr × 50 = $22/hr lever
DEFAULT_TIMEOUT_MIN = 10  # per-job timeout (minutes); caps stall cost at $3.67


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Lane K Phase 2 Glue ETL packet-to-parquet burn driver.",
    )
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--database", default=DEFAULT_DATABASE)
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--job-name", default=DEFAULT_JOB_NAME)
    p.add_argument("--role-arn", default=DEFAULT_ROLE_ARN)
    p.add_argument("--script-local", default=DEFAULT_SCRIPT_LOCAL)
    p.add_argument("--script-s3-prefix", default=DEFAULT_SCRIPT_S3_PREFIX)
    p.add_argument("--target-prefix-base", default=DEFAULT_TARGET_PREFIX_BASE)
    p.add_argument("--tables-file", default=DEFAULT_TABLES_FILE)
    p.add_argument("--ledger-path", default=DEFAULT_LEDGER_PATH)
    p.add_argument(
        "--submit-interval-sec",
        type=int,
        default=DEFAULT_SUBMIT_INTERVAL_SEC,
        help="Seconds between successive start-job-run submissions.",
    )
    p.add_argument(
        "--max-runs",
        type=int,
        default=DEFAULT_MAX_RUNS,
        help="Maximum job runs to submit in this driver invocation.",
    )
    p.add_argument(
        "--dpu",
        type=int,
        default=DEFAULT_DPU,
        help="NumberOfWorkers for the Glue Job (G.1X = 1 DPU each).",
    )
    p.add_argument(
        "--timeout-min",
        type=int,
        default=DEFAULT_TIMEOUT_MIN,
        help="Per-job timeout in minutes (caps stall cost).",
    )
    p.add_argument(
        "--commit",
        action="store_true",
        help="Lift dry-run guard; actually call aws glue start-job-run.",
    )
    return p.parse_args(argv)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_tables(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        print(f"[lane_k_glue] FATAL: tables file not found: {path}", file=sys.stderr)
        sys.exit(2)
    out: list[str] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def _ensure_script_in_s3(
    *,
    s3_client: Any,
    bucket: str,
    script_local: str,
    script_s3_prefix: str,
    commit: bool,
) -> str:
    """Upload the Spark ETL script to S3. Returns the s3:// URI."""

    local_p = Path(script_local)
    if not local_p.exists():
        print(f"[lane_k_glue] FATAL: script not found: {script_local}", file=sys.stderr)
        sys.exit(2)
    key = f"{script_s3_prefix.rstrip('/')}/{local_p.name}"
    s3_uri = f"s3://{bucket}/{key}"
    if not commit:
        print(f"[lane_k_glue] DRY_RUN: would upload {local_p} -> {s3_uri}")
        return s3_uri
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=local_p.read_bytes(),
        ContentType="text/x-python",
    )
    print(f"[lane_k_glue] uploaded script: {s3_uri}")
    return s3_uri


def _ensure_glue_job(
    *,
    glue_client: Any,
    job_name: str,
    role_arn: str,
    script_s3_uri: str,
    dpu: int,
    timeout_min: int,
    commit: bool,
) -> None:
    """Create (or update) the Glue Job definition."""

    job_def = {
        "Description": (
            "Lane K Phase 2 — packet JSON to ZSTD Parquet burn lever "
            "(2026-05-17). 50 DPU PySpark. Cost contract: $22/hr × ~11h = "
            "$242/day. DRY_RUN default in driver script."
        ),
        "Role": role_arn,
        "ExecutionProperty": {"MaxConcurrentRuns": 10},
        "Command": {
            "Name": "glueetl",
            "ScriptLocation": script_s3_uri,
            "PythonVersion": "3",
        },
        "DefaultArguments": {
            "--job-language": "python",
            "--enable-metrics": "true",
            "--enable-continuous-cloudwatch-log": "true",
            "--enable-spark-ui": "false",
            "--TempDir": f"s3://{DEFAULT_BUCKET}/glue/tmp/lane_k_phase2/",
            "--compression": "zstd",
            "--coalesce_partitions": "8",
        },
        "MaxRetries": 0,
        "Timeout": timeout_min,
        "GlueVersion": "4.0",
        "NumberOfWorkers": dpu,
        "WorkerType": "G.1X",
        "Tags": {
            "Project": "jpcite",
            "CreditRun": "2026-05",
            "Lane": "K",
            "AutoStop": "2026-05-29",
        },
    }

    if not commit:
        print(
            f"[lane_k_glue] DRY_RUN: would create/update Glue Job "
            f"{job_name} ({dpu} workers G.1X, timeout {timeout_min}min)"
        )
        return

    try:
        glue_client.get_job(JobName=job_name)
        # Job exists — update
        update_payload = dict(job_def)
        glue_client.update_job(JobName=job_name, JobUpdate=update_payload)
        print(f"[lane_k_glue] updated existing Glue Job: {job_name}")
    except glue_client.exceptions.EntityNotFoundException:
        glue_client.create_job(Name=job_name, **job_def)
        print(f"[lane_k_glue] created Glue Job: {job_name}")


def _submit_run(
    *,
    glue_client: Any,
    job_name: str,
    source_table: str,
    target_prefix: str,
    commit: bool,
) -> dict[str, Any]:
    arguments = {
        "--source_table": source_table,
        "--target_prefix": target_prefix,
    }
    record: dict[str, Any] = {
        "source_table": source_table,
        "target_prefix": target_prefix,
        "submitted_at_utc": _now_iso(),
        "dry_run": not commit,
    }
    if not commit:
        record["job_run_id"] = "DRY_RUN"
        print(f"[lane_k_glue] DRY_RUN: would start_job_run {job_name} source_table={source_table}")
        return record
    resp = glue_client.start_job_run(
        JobName=job_name,
        Arguments=arguments,
    )
    record["job_run_id"] = resp.get("JobRunId", "")
    print(
        f"[lane_k_glue] start_job_run OK "
        f"source_table={source_table} job_run_id={record['job_run_id']}"
    )
    return record


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    commit = bool(args.commit) and os.environ.get("DRY_RUN", "1") != "1"
    if args.commit and os.environ.get("DRY_RUN", "1") == "1":
        # --commit overrides DRY_RUN env (matches Lane C textract_bulk pattern).
        commit = True

    print(f"[lane_k_glue] mode={'COMMIT' if commit else 'DRY_RUN'}")
    print(f"[lane_k_glue] profile={args.profile} region={args.region}")

    tables = _load_tables(args.tables_file)
    if not tables:
        print(f"[lane_k_glue] no tables in {args.tables_file}", file=sys.stderr)
        return 2
    print(f"[lane_k_glue] tables to process: {len(tables)}")

    try:
        import boto3
    except ImportError:
        print("[lane_k_glue] FATAL: boto3 not importable", file=sys.stderr)
        return 2

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    s3 = session.client("s3")
    glue = session.client("glue")

    script_s3_uri = _ensure_script_in_s3(
        s3_client=s3,
        bucket=args.bucket,
        script_local=args.script_local,
        script_s3_prefix=args.script_s3_prefix,
        commit=commit,
    )
    _ensure_glue_job(
        glue_client=glue,
        job_name=args.job_name,
        role_arn=args.role_arn,
        script_s3_uri=script_s3_uri,
        dpu=args.dpu,
        timeout_min=args.timeout_min,
        commit=commit,
    )

    runs: list[dict[str, Any]] = []
    max_runs = min(args.max_runs, len(tables))
    for i, table in enumerate(tables[:max_runs], start=1):
        target_prefix = f"{args.target_prefix_base}/{table}"
        record = _submit_run(
            glue_client=glue,
            job_name=args.job_name,
            source_table=table,
            target_prefix=target_prefix,
            commit=commit,
        )
        runs.append(record)
        if i < max_runs:
            time.sleep(args.submit_interval_sec)

    ledger = {
        "ledger_id": "lane_k_glue_etl_2026_05_17",
        "started_at_utc": _now_iso(),
        "profile": args.profile,
        "region": args.region,
        "job_name": args.job_name,
        "script_s3_uri": script_s3_uri,
        "dpu": args.dpu,
        "timeout_min": args.timeout_min,
        "submit_interval_sec": args.submit_interval_sec,
        "max_runs": max_runs,
        "table_count": len(tables),
        "dry_run": not commit,
        "runs": runs,
    }
    Path(args.ledger_path).parent.mkdir(parents=True, exist_ok=True)
    Path(args.ledger_path).write_text(json.dumps(ledger, ensure_ascii=False, indent=2))
    print(f"[lane_k_glue] ledger written: {args.ledger_path} runs={len(runs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
