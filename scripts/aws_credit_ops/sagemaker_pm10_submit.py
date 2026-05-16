#!/usr/bin/env python3
"""SageMaker PM10 saturate driver.

Purpose
-------
PM9 (run_id ``20260516T154052Z``, commit ``cb8bde75c`` + ``1e03fd540``)
fired 3 transform jobs (2 c5.2xlarge CPU + 1 g4dn.xlarge GPU) on
adoption_records/part-0001 + am_law_article/part-0012 + am_law_article
/part-0013. At PM10 submit time: PM9 amlaw36gpu Completed, PM9
adoption34cpu + amlaw35cpu still InProgress. PM7 fully drained, PM8
3/5 CPU still InProgress (amlaw29cpu / 30cpu / 31cpu); PM8 GPU side
(amlaw32gpu / 33gpu) Completed.

PM10 final-head closure + GPU mirror
------------------------------------
PM10 closes the **last missing head** in the am_law_article corpus
(part-0000 was never trunc'd, never embedded — PM5..PM9 covered
0001..0013 only) and re-truncates adoption_records/part-0000 properly
(the existing trunc was a bytewise copy, not actually truncated). It
then adds 3 g4dn.xlarge GPU mirror jobs on PM8 am_law_article parts
0007..0009 (currently InProgress on CPU only) — same pattern as
PM6/PM7 GPU re-runs on completed CPU shards, giving the FAISS expand
consumer independent GPU-quality embedding for those parts.

Quota at PM10 submit (PM8 3 CPU + PM9 2 CPU still in-flight, 0 GPU):
    ml.c5.2xlarge  for transform job usage  used 5 / 8  -> 3 free
    ml.g4dn.xlarge for transform job usage  used 0 / 4  -> 4 free

PM10 adds 2 CPU + 3 GPU -> total in-flight 7/8 CPU + 3/4 GPU. Within quota.

The 2 new trunc prefixes were materialized by ``/tmp/pm10_truncate.py``
(streams raw ``corpus_export/`` JSONL, truncates ``inputs`` to 320 chars
for BERT 512 cap headroom, re-uploads to ``corpus_export_trunc/``):

* am_law_article/part-0000.jsonl   (raw 20 MB, 22,233 rows, trunc 14.6 MB)
* adoption_records/part-0000.jsonl (raw 20 MB, 116,335 rows, trunc 20.0 MB
  — adoption rows have short inputs and never exceed 320 chars; sizes equal)

The 3 GPU mirror jobs read the **existing** PM8 trunc prefixes (parts
0007/0008/0009 in ``corpus_export_trunc/am_law_article/``).

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

# 5 PM10 jobs: 2 c5.2xlarge CPU (new shards) + 3 g4dn.xlarge GPU (mirror).
# CPU side:
#   amlaw37cpu — am_law_article/part-0000 (NEW: final missing head, 22,233 rows)
#   adoption38cpu — adoption_records/part-0000 (re-trunc, 116,335 rows)
# GPU side: am_law_article/part-0007..0009 GPU mirror of PM8 CPU InProgress.
PM10_JOBS: list[dict[str, str]] = [
    {
        "tag": "amlaw37cpu",
        "instance": "ml.c5.2xlarge",
        "model": "jpcite-embed-allminilm-cpu-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0000.jsonl",
        "output_subdir": "amlaw-fix37-cpu",
    },
    {
        "tag": "adoption38cpu",
        "instance": "ml.c5.2xlarge",
        "model": "jpcite-embed-allminilm-cpu-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/adoption_records/part-0000.jsonl",
        "output_subdir": "adoption-fix38-cpu",
    },
    {
        "tag": "amlaw39gpu",
        "instance": "ml.g4dn.xlarge",
        "model": "jpcite-embed-allminilm-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0007.jsonl",
        "output_subdir": "amlaw-fix39-gpu",
    },
    {
        "tag": "amlaw40gpu",
        "instance": "ml.g4dn.xlarge",
        "model": "jpcite-embed-allminilm-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0008.jsonl",
        "output_subdir": "amlaw-fix40-gpu",
    },
    {
        "tag": "amlaw41gpu",
        "instance": "ml.g4dn.xlarge",
        "model": "jpcite-embed-allminilm-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0009.jsonl",
        "output_subdir": "amlaw-fix41-gpu",
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
            {"Key": "wave", "Value": "PM10"},
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
    parser = argparse.ArgumentParser(description="SageMaker PM10 saturate driver")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually create jobs (default: DRY_RUN)",
    )
    parser.add_argument(
        "--records-out",
        type=str,
        default="docs/_internal/sagemaker_pm10_2026_05_17_records.json",
        help="Path to write submit ledger JSON",
    )
    args = parser.parse_args()

    actual_usd = preflight_cost_check()
    print(f"[preflight] actual_usd={actual_usd} < {HARD_STOP_USD} OK")

    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    print(f"[run_id] {run_id}")

    if not args.commit:
        print("[DRY_RUN] Would submit:")
        for job in PM10_JOBS:
            print(f"  - {job['tag']:14s} {job['instance']:18s} {job['input']}")
        sys.exit(0)

    sm = boto3.Session(profile_name=PROFILE, region_name=REGION).client("sagemaker")
    submitted: list[dict[str, str]] = []
    for job in PM10_JOBS:
        try:
            result = submit_transform_job(sm, run_id, job)
            submitted.append(result)
            print(f"[OK] {result['job_name']}  {result['arn']}")
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {job['tag']}: {e}", file=sys.stderr)

    ledger = {
        "run_id": run_id,
        "predecessor_run_id": "20260516T154052Z",
        "predecessor_wave": "PM9",
        "budget_actual_usd": actual_usd,
        "quotas": {
            "ml.c5.2xlarge for transform job usage": 8.0,
            "ml.g4dn.xlarge for transform job usage": 4.0,
        },
        "fix_applied": "BatchStrategy=SingleRecord (PM5..PM9 carry-over)",
        "submitted": submitted,
    }
    out_path = Path(args.records_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))
    print(f"[ledger] {out_path}  ({len(submitted)}/{len(PM10_JOBS)} submitted)")


if __name__ == "__main__":
    main()
