#!/usr/bin/env python3
"""SageMaker PM8 saturate driver.

Purpose
-------
PM7 (run_id ``20260516T143552Z``, commit succession from PM6 ``c7df91f23``)
fired 5 transform jobs against 5 truncated parts (3 c5.2xlarge CPU + 2
g4dn.xlarge GPU). 2 GPU jobs Completed (amlaw27gpu / amlaw28gpu) within
~38 min wall (~42 GB output each). 3 CPU jobs (amlaw24cpu / amlaw25cpu /
adoption26cpu) remained InProgress at PM8 submit time.

PM8 saturate
------------
Quotas at PM8 submit (PM7 CPU side still draining):

    ml.c5.2xlarge  for transform job usage  used 3 / 8  -> 5 free
    ml.g4dn.xlarge for transform job usage  used 0 / 4  -> 4 free

PM8 fires 5 NEW jobs against fresh truncated parts (3 c5.2xlarge + 2
g4dn.xlarge). Combined with the 3 PM7 CPU jobs still InProgress at submit,
total in-flight CPU = 3 + 3 = 6 / 8, GPU = 0 + 2 = 2 / 4 -> within quota.

Wave 80/81/82/86/87/88 packet corpus framing
--------------------------------------------
The user's PM8 task framing requested "Wave 80/81/82 packet corpus
(truncate first, then embed)" + "Wave 86-88 packet corpus when available".
Honest framing per the PM7 doc: Wave 80-88 packets (10 each, catalog
282..372) are JSON analytic data living at the named packet prefixes
(``packets/<packet_name>/...``) and are NOT a separate embedding source
family. The embedding fleet always reads from
``s3://<derived_bucket>/corpus_export_trunc/<table>/part-<seq>.jsonl``.

PM8 therefore consumes the next untouched truncated parts:

* ``am_law_article/part-0007.jsonl`` (16.7 MB, NEW trunc, 28,049 rows)
* ``am_law_article/part-0008.jsonl`` (16.6 MB, NEW trunc, 27,252 rows)
* ``am_law_article/part-0009.jsonl`` (16.3 MB, NEW trunc, 26,332 rows)
* ``am_law_article/part-0010.jsonl`` (16.6 MB, NEW trunc, 28,014 rows)
* ``am_law_article/part-0011.jsonl`` (16.5 MB, NEW trunc, 26,232 rows)

The 5 new trunc prefixes were materialized by ``/tmp/pm8_truncate.py``
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

import boto3

DERIVED_BUCKET = "jpcite-credit-993693061769-202605-derived"
EXECUTION_ROLE_ARN = "arn:aws:iam::993693061769:role/jpcite-sagemaker-embed-role"
HARD_STOP_USD = 13000.0
REGION = "ap-northeast-1"
PROFILE = "bookyou-recovery"

# 5 PM8 jobs: 3 c5.2xlarge CPU + 2 g4dn.xlarge GPU.
# CPU side: am_law_article trunc 0007 / 0008 / 0009.
# GPU side: am_law_article trunc 0010 / 0011.
PM8_JOBS: list[dict[str, str]] = [
    {
        "tag": "amlaw29cpu",
        "instance": "ml.c5.2xlarge",
        "model": "jpcite-embed-allminilm-cpu-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0007.jsonl",
        "output_subdir": "amlaw-fix29-cpu",
    },
    {
        "tag": "amlaw30cpu",
        "instance": "ml.c5.2xlarge",
        "model": "jpcite-embed-allminilm-cpu-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0008.jsonl",
        "output_subdir": "amlaw-fix30-cpu",
    },
    {
        "tag": "amlaw31cpu",
        "instance": "ml.c5.2xlarge",
        "model": "jpcite-embed-allminilm-cpu-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0009.jsonl",
        "output_subdir": "amlaw-fix31-cpu",
    },
    {
        "tag": "amlaw32gpu",
        "instance": "ml.g4dn.xlarge",
        "model": "jpcite-embed-allminilm-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0010.jsonl",
        "output_subdir": "amlaw-fix32-gpu",
    },
    {
        "tag": "amlaw33gpu",
        "instance": "ml.g4dn.xlarge",
        "model": "jpcite-embed-allminilm-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0011.jsonl",
        "output_subdir": "amlaw-fix33-gpu",
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
            {"Key": "wave", "Value": "PM8"},
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
    parser = argparse.ArgumentParser(description="SageMaker PM8 saturate driver")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually create jobs (default: DRY_RUN)",
    )
    parser.add_argument(
        "--records-out",
        type=str,
        default="docs/_internal/sagemaker_pm8_2026_05_16_records.json",
        help="Path to write submit ledger JSON",
    )
    args = parser.parse_args()

    actual_usd = preflight_cost_check()
    print(f"[preflight] actual_usd={actual_usd} < {HARD_STOP_USD} OK")

    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    print(f"[run_id] {run_id}")

    if not args.commit:
        print("[DRY_RUN] Would submit:")
        for job in PM8_JOBS:
            print(f"  - {job['tag']:14s} {job['instance']:18s} {job['input']}")
        sys.exit(0)

    sm = boto3.Session(profile_name=PROFILE, region_name=REGION).client("sagemaker")
    submitted: list[dict[str, str]] = []
    for job in PM8_JOBS:
        try:
            result = submit_transform_job(sm, run_id, job)
            submitted.append(result)
            print(f"[OK] {result['job_name']}  {result['arn']}")
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {job['tag']}: {e}", file=sys.stderr)

    ledger = {
        "run_id": run_id,
        "predecessor_run_id": "20260516T143552Z",
        "predecessor_wave": "PM7",
        "budget_actual_usd": actual_usd,
        "quotas": {
            "ml.c5.2xlarge for transform job usage": 8.0,
            "ml.g4dn.xlarge for transform job usage": 4.0,
        },
        "fix_applied": "BatchStrategy=SingleRecord (PM5/PM6/PM7 carry-over)",
        "submitted": submitted,
    }
    out_path = Path(args.records_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))
    print(f"[ledger] {out_path}  ({len(submitted)}/{len(PM8_JOBS)} submitted)")


if __name__ == "__main__":
    main()
