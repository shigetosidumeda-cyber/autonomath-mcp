#!/usr/bin/env python3
"""SageMaker PM9 saturate driver.

Purpose
-------
PM8 (run_id ``20260516T152037Z``, commit ``41cde5f3e``) fired 5 transform
jobs (3 c5.2xlarge CPU + 2 g4dn.xlarge GPU) on am_law_article trunc parts
0007..0011. PM7 adoption26cpu remained InProgress at PM9 submit time, the
4 other PM7 jobs (amlaw24cpu/25cpu/27gpu/28gpu) Completed.

PM9 cross-corpus expansion
--------------------------
PM9 picks up where PM8 stopped on a 3-corpus grow (not pure am_law
saturation). The user's original PM9 brief mentioned "Truncated
court_decisions/ remaining parts" + "Other corpus tables not yet
embedded"; honest framing per the S3 inventory:

* court_decisions/part-0001 does NOT exist — court_decisions raw is a
  single part-0000 (1.4 MB), already truncated to 682.7 KB by PM5 and
  embedded by court21gpu. No remaining court parts.
* Single-part corpora already drained: programs/0000, invoice_registrants
  /0000, nta_saiketsu/0000, nta_tsutatsu_index/0000 (all 1 part each,
  all done in PM5/PM6).
* The genuinely remaining cross-corpus untouched content is:
  - adoption_records/part-0001 (8.7 MB raw, 44,041 rows after trunc)
  - am_law_article/part-0012   (20 MB raw, 24,429 rows after trunc)
  - am_law_article/part-0013   (260 KB raw sentinel tail, 340 rows)

PM9 fires 3 jobs (2 c5.2xlarge CPU + 1 g4dn.xlarge GPU) on these. The
two am_law parts complete the am_law_article corpus to part-0013 (the
sentinel). adoption_records part-0001 is the second adoption batch
beyond PM7 adoption26cpu (which handled part-0000, 116K rows).

Quota at PM9 submit (PM7 adoption26cpu + PM8 5 in-flight):
    ml.c5.2xlarge  for transform job usage  used 4 / 8  -> 4 free
    ml.g4dn.xlarge for transform job usage  used 2 / 4  -> 2 free

PM9 adds 2 CPU + 1 GPU -> total in-flight 6/8 CPU + 3/4 GPU. Within quota.

The 3 new trunc prefixes were materialized by ``/tmp/pm9_truncate.py``
which streams raw ``corpus_export/`` JSONL, truncates ``inputs`` to
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

# 3 PM9 jobs: 2 c5.2xlarge CPU + 1 g4dn.xlarge GPU.
# CPU side: adoption_records trunc 0001 (44,041 rows, ~30 min) +
#           am_law_article trunc 0012 (24,429 rows, ~17 min).
# GPU side: am_law_article trunc 0013 (340 rows, ~30 sec actual but
#           transform job overhead dominates ~5-8 min).
PM9_JOBS: list[dict[str, str]] = [
    {
        "tag": "adoption34cpu",
        "instance": "ml.c5.2xlarge",
        "model": "jpcite-embed-allminilm-cpu-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/adoption_records/part-0001.jsonl",
        "output_subdir": "adoption-fix34-cpu",
    },
    {
        "tag": "amlaw35cpu",
        "instance": "ml.c5.2xlarge",
        "model": "jpcite-embed-allminilm-cpu-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0012.jsonl",
        "output_subdir": "amlaw-fix35-cpu",
    },
    {
        "tag": "amlaw36gpu",
        "instance": "ml.g4dn.xlarge",
        "model": "jpcite-embed-allminilm-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0013.jsonl",
        "output_subdir": "amlaw-fix36-gpu",
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
            {"Key": "wave", "Value": "PM9"},
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
    parser = argparse.ArgumentParser(description="SageMaker PM9 saturate driver")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually create jobs (default: DRY_RUN)",
    )
    parser.add_argument(
        "--records-out",
        type=str,
        default="docs/_internal/sagemaker_pm9_2026_05_17_records.json",
        help="Path to write submit ledger JSON",
    )
    args = parser.parse_args()

    actual_usd = preflight_cost_check()
    print(f"[preflight] actual_usd={actual_usd} < {HARD_STOP_USD} OK")

    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    print(f"[run_id] {run_id}")

    if not args.commit:
        print("[DRY_RUN] Would submit:")
        for job in PM9_JOBS:
            print(f"  - {job['tag']:14s} {job['instance']:18s} {job['input']}")
        sys.exit(0)

    sm = boto3.Session(profile_name=PROFILE, region_name=REGION).client("sagemaker")
    submitted: list[dict[str, str]] = []
    for job in PM9_JOBS:
        try:
            result = submit_transform_job(sm, run_id, job)
            submitted.append(result)
            print(f"[OK] {result['job_name']}  {result['arn']}")
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {job['tag']}: {e}", file=sys.stderr)

    ledger = {
        "run_id": run_id,
        "predecessor_run_id": "20260516T152037Z",
        "predecessor_wave": "PM8",
        "budget_actual_usd": actual_usd,
        "quotas": {
            "ml.c5.2xlarge for transform job usage": 8.0,
            "ml.g4dn.xlarge for transform job usage": 4.0,
        },
        "fix_applied": "BatchStrategy=SingleRecord (PM5..PM8 carry-over)",
        "submitted": submitted,
    }
    out_path = Path(args.records_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))
    print(f"[ledger] {out_path}  ({len(submitted)}/{len(PM9_JOBS)} submitted)")


if __name__ == "__main__":
    main()
