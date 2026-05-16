#!/usr/bin/env python3
"""SageMaker PM7 saturate driver.

Purpose
-------
PM6 (run_id ``20260516T105156Z``, commit succession from PM5 ``c7df91f23``)
fired 2 ml.g4dn.xlarge transform jobs on truncated ``am_law_article`` parts
0001 + 0002 with ``BatchStrategy=SingleRecord``. Both Completed:

    amlaw22gpu  ml.g4dn.xlarge  Completed  part-0001 (17.2 MB trunc input)
    amlaw23gpu  ml.g4dn.xlarge  Completed  part-0002 (16.7 MB trunc input)

PM7 saturate
------------
After PM5 + PM6 fully drained (no in-flight transform jobs at submit),
both quotas are again completely free:

    ml.c5.2xlarge  for transform job usage  used 0 / 8  -> 8 free
    ml.g4dn.xlarge for transform job usage  used 0 / 4  -> 4 free

PM7 fires 5 jobs (3 c5.2xlarge + 2 g4dn.xlarge) on the next batch of
truncated parts. Wave 80-82 packets (10 each, catalog 282..312) are
JSON analytic data living at the named packet prefixes
(``packets/<packet_name>/...``); they are NOT a separate embedding source
family. The embedding fleet always reads from
``s3://<derived_bucket>/corpus_export_trunc/<table>/part-<seq>.jsonl``.

Untouched truncated prefixes available at PM7 submit time:

* ``am_law_article/part-0003.jsonl`` (16.8 MB, pre-existing trunc, never run)
* ``am_law_article/part-0004.jsonl`` (16.8 MB, pre-existing trunc, never run)
* ``am_law_article/part-0005.jsonl`` (16.3 MB, NEW trunc this run, 26,480 rows)
* ``am_law_article/part-0006.jsonl`` (16.7 MB, NEW trunc this run, 28,764 rows)
* ``adoption_records/part-0000.jsonl`` (21.0 MB, NEW trunc this run, 116,335 rows)

The new trunc prefixes were materialized by ``/tmp/pm7_truncate.py``
which streams the raw ``corpus_export/`` JSONL, truncates ``inputs`` to
320 chars (BERT 512 cap headroom), and re-uploads to
``corpus_export_trunc/``.

5-line hard-stop
----------------
Cost preflight ``aws ce get-cost-and-usage`` is sampled; any actual
month-to-date >= ``HARD_STOP_USD`` aborts before ``create_transform_job``.
AWS Budget Action at $18,900 is the ultimate stop.

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import boto3  # type: ignore[import-untyped]

DERIVED_BUCKET = "jpcite-credit-993693061769-202605-derived"
EXECUTION_ROLE_ARN = "arn:aws:iam::993693061769:role/jpcite-sagemaker-embed-role"
HARD_STOP_USD = 13000.0
REGION = "ap-northeast-1"
PROFILE = "bookyou-recovery"

# 5 PM7 jobs: 3 c5.2xlarge CPU + 2 g4dn.xlarge GPU.
# CPU side: 2 existing am_law_article trunc parts (0003, 0004) + the new
# adoption_records part-0000 (116K rows, expected ~30-40 min CPU walk).
# GPU side: 2 new am_law_article trunc parts (0005, 0006).
PM7_JOBS: list[dict[str, str]] = [
    {
        "tag": "amlaw24cpu",
        "instance": "ml.c5.2xlarge",
        "model": "jpcite-embed-allminilm-cpu-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0003.jsonl",
        "output_subdir": "amlaw-fix24-cpu",
    },
    {
        "tag": "amlaw25cpu",
        "instance": "ml.c5.2xlarge",
        "model": "jpcite-embed-allminilm-cpu-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0004.jsonl",
        "output_subdir": "amlaw-fix25-cpu",
    },
    {
        "tag": "adoption26cpu",
        "instance": "ml.c5.2xlarge",
        "model": "jpcite-embed-allminilm-cpu-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/adoption_records/part-0000.jsonl",
        "output_subdir": "adoption-fix26-cpu",
    },
    {
        "tag": "amlaw27gpu",
        "instance": "ml.g4dn.xlarge",
        "model": "jpcite-embed-allminilm-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0005.jsonl",
        "output_subdir": "amlaw-fix27-gpu",
    },
    {
        "tag": "amlaw28gpu",
        "instance": "ml.g4dn.xlarge",
        "model": "jpcite-embed-allminilm-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0006.jsonl",
        "output_subdir": "amlaw-fix28-gpu",
    },
]


def preflight_cost_check() -> float:
    """Run 5-line hard-stop preflight."""
    ce = boto3.Session(profile_name=PROFILE, region_name=REGION).client("ce")
    today = dt.date.today()
    first_of_month = today.replace(day=1).isoformat()
    tomorrow = (today + dt.timedelta(days=1)).isoformat()
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": first_of_month, "End": tomorrow},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )
    amt = float(resp["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"])
    if amt >= HARD_STOP_USD:
        print(
            f"[HARD-STOP] actual_usd={amt} >= {HARD_STOP_USD}, aborting",
            file=sys.stderr,
        )
        sys.exit(2)
    return amt


def submit_transform_job(sm: Any, run_id: str, job: dict[str, str]) -> dict[str, str]:
    """Submit one SageMaker batch transform job with SingleRecord strategy."""
    job_name = f"jpcite-embed-{run_id}-{job['tag']}"
    output_path = f"s3://{DERIVED_BUCKET}/embeddings_burn/{job['output_subdir']}/"
    spec: dict[str, Any] = {
        "TransformJobName": job_name,
        "ModelName": job["model"],
        "BatchStrategy": "SingleRecord",
        "TransformInput": {
            "DataSource": {
                "S3DataSource": {
                    "S3DataType": "S3Prefix",
                    "S3Uri": job["input"],
                }
            },
            "ContentType": "application/json",
            "CompressionType": "None",
            "SplitType": "Line",
        },
        "TransformOutput": {
            "S3OutputPath": output_path,
            "Accept": "application/json",
            "AssembleWith": "Line",
        },
        "TransformResources": {
            "InstanceType": job["instance"],
            "InstanceCount": 1,
        },
        "MaxConcurrentTransforms": 1,
        "MaxPayloadInMB": 6,
        "Tags": [
            {"Key": "lane", "Value": "solo"},
            {"Key": "run_id", "Value": run_id},
            {"Key": "wave", "Value": "PM7"},
        ],
    }
    resp = sm.create_transform_job(**spec)
    return {
        "tag": job["tag"],
        "job_name": job_name,
        "instance_type": job["instance"],
        "model": job["model"],
        "input": job["input"],
        "output": output_path,
        "arn": resp["TransformJobArn"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="SageMaker PM7 saturate driver")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually create jobs (default: DRY_RUN)",
    )
    parser.add_argument(
        "--records-out",
        type=str,
        default="docs/_internal/sagemaker_pm7_2026_05_16_records.json",
        help="Path to write submit ledger JSON",
    )
    args = parser.parse_args()

    actual_usd = preflight_cost_check()
    print(f"[preflight] actual_usd={actual_usd} < {HARD_STOP_USD} OK")

    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    print(f"[run_id] {run_id}")

    if not args.commit:
        print("[DRY_RUN] Would submit:")
        for job in PM7_JOBS:
            print(f"  - {job['tag']:14s} {job['instance']:18s} {job['input']}")
        sys.exit(0)

    sm = boto3.Session(profile_name=PROFILE, region_name=REGION).client("sagemaker")
    submitted: list[dict[str, str]] = []
    for job in PM7_JOBS:
        try:
            result = submit_transform_job(sm, run_id, job)
            submitted.append(result)
            print(f"[OK] {result['job_name']}  {result['arn']}")
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {job['tag']}: {e}", file=sys.stderr)

    ledger = {
        "run_id": run_id,
        "predecessor_run_id": "20260516T105156Z",
        "predecessor_wave": "PM6",
        "budget_actual_usd": actual_usd,
        "quotas": {
            "ml.c5.2xlarge for transform job usage": 8.0,
            "ml.g4dn.xlarge for transform job usage": 4.0,
        },
        "fix_applied": "BatchStrategy=SingleRecord (PM5/PM6 carry-over)",
        "submitted": submitted,
    }
    out_path = Path(args.records_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))
    print(f"[ledger] {out_path}  ({len(submitted)}/{len(PM7_JOBS)} submitted)")


if __name__ == "__main__":
    main()
