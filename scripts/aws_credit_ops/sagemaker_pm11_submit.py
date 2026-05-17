#!/usr/bin/env python3
"""SageMaker PM11 saturate driver (Lane B — 20 jobs parallel).

Purpose
-------
PM10 (run_id ``20260516T160602Z``) closed the last missing head in
``am_law_article`` (part-0000) + re-truncated ``adoption_records``
part-0000 + GPU-mirrored 3 ``am_law_article`` parts (0007/0008/0009).
At PM11 submit time PM10 was fully drained (5/5 Completed, 0
InProgress).

PM11 fires **20 parallel transform jobs** across all 21 trunc parts in
S3 today (14 ``am_law_article`` + 2 ``adoption_records`` + 5 single-
part heads: ``court_decisions`` / ``invoice_registrants`` /
``nta_saiketsu`` / ``nta_tsutatsu_index`` / ``programs``) using a CPU /
GPU mix that fits inside the live transform-job quota matrix.

Quota matrix (PM11 submit, all transform job quotas, region ap-northeast-1):

    ml.c5.2xlarge   8  primary CPU  (PM10 PEAK 7 -> 8 headroom)
    ml.c5.xlarge   16  burst CPU    (unused PM5..PM10)
    ml.m5.xlarge    8  burst CPU    (unused PM5..PM10)
    ml.g4dn.xlarge  4  primary GPU
    ml.g5.xlarge    2  burst GPU

PM11 allocation: 8 c5.2xlarge + 6 c5.xlarge + 4 m5.xlarge (CPU) + 2 g4dn.xlarge
(GPU) = **20 in-flight**. CPU heavy because most parts are ~16 MB JSONL,
embedding throughput is I/O dominated for c5; GPU reserved for the
two longest single-part heads (``am_law_article/part-0000`` already
done — instead we GPU-mirror two of the densest CPU-completed parts to
double-cover the embedding substrate for FAISS shard expand).

Target burn
-----------
- Per-job cost band: $0.06 - $0.50 wall (35-78 min CPU short, ~39 min GPU)
- 20 jobs in parallel: ~$2-10 per drain cycle
- User-stated $260/day target: assumes back-to-back drain + re-fire
  cycles (not single-shot); this script lands the first cycle.

5-line hard-stop
----------------
Cost preflight ``aws ce get-cost-and-usage`` is sampled; any actual
month-to-date >= ``HARD_STOP_USD`` (=$13,000) aborts before
``create_transform_job``. AWS Budget Action at $18,900 is the ultimate stop.

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from scripts.aws_credit_ops._aws import ce_client, sagemaker_client

DERIVED_BUCKET = "jpcite-credit-993693061769-202605-derived"
EXECUTION_ROLE_ARN = "arn:aws:iam::993693061769:role/jpcite-sagemaker-embed-role"
HARD_STOP_USD = 13000.0
REGION = "ap-northeast-1"
PROFILE = "bookyou-recovery"

CPU_MODEL = "jpcite-embed-allminilm-cpu-v1"
GPU_MODEL = "jpcite-embed-allminilm-v1"

# 20 PM11 jobs distributed across 5 instance types and 7 source families.
# Allocation rule:
#   - All 14 am_law_article parts -> CPU saturation (mixed c5.2x / c5.x / m5.x)
#   - 2 adoption_records parts    -> CPU c5.2xlarge (long, dense)
#   - 5 single-part source heads  -> CPU c5.xlarge (court / invoice / saiketsu / tsutatsu / programs)
#   = 21 candidate parts, we pick 18 CPU + 2 GPU mirror = 20 total
# GPU mirror picks the two densest CPU-completed parts for FAISS substrate
# expand (parts 0001 + 0012 = largest law_article shards by row count).
PM11_JOBS: list[dict[str, str]] = [
    # ---- 8 x c5.2xlarge CPU (heavy parts, primary lane) ----
    {
        "tag": "amlaw42cpu",
        "instance": "ml.c5.2xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0001.jsonl",
        "output_subdir": "amlaw-pm11-42-cpu",
    },
    {
        "tag": "amlaw43cpu",
        "instance": "ml.c5.2xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0002.jsonl",
        "output_subdir": "amlaw-pm11-43-cpu",
    },
    {
        "tag": "amlaw44cpu",
        "instance": "ml.c5.2xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0003.jsonl",
        "output_subdir": "amlaw-pm11-44-cpu",
    },
    {
        "tag": "amlaw45cpu",
        "instance": "ml.c5.2xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0004.jsonl",
        "output_subdir": "amlaw-pm11-45-cpu",
    },
    {
        "tag": "amlaw46cpu",
        "instance": "ml.c5.2xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0005.jsonl",
        "output_subdir": "amlaw-pm11-46-cpu",
    },
    {
        "tag": "amlaw47cpu",
        "instance": "ml.c5.2xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0006.jsonl",
        "output_subdir": "amlaw-pm11-47-cpu",
    },
    {
        "tag": "amlaw48cpu",
        "instance": "ml.c5.2xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0010.jsonl",
        "output_subdir": "amlaw-pm11-48-cpu",
    },
    {
        "tag": "amlaw49cpu",
        "instance": "ml.c5.2xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0011.jsonl",
        "output_subdir": "amlaw-pm11-49-cpu",
    },
    # ---- 6 x c5.xlarge CPU (burst lane, smaller parts) ----
    {
        "tag": "amlaw50cpu",
        "instance": "ml.c5.xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0012.jsonl",
        "output_subdir": "amlaw-pm11-50-cpu",
    },
    {
        "tag": "amlaw51cpu",
        "instance": "ml.c5.xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0013.jsonl",
        "output_subdir": "amlaw-pm11-51-cpu",
    },
    {
        "tag": "court52cpu",
        "instance": "ml.c5.xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/court_decisions/part-0000.jsonl",
        "output_subdir": "court-pm11-52-cpu",
    },
    {
        "tag": "invoice53cpu",
        "instance": "ml.c5.xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/invoice_registrants/part-0000.jsonl",
        "output_subdir": "invoice-pm11-53-cpu",
    },
    {
        "tag": "saiketsu54cpu",
        "instance": "ml.c5.xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/nta_saiketsu/part-0000.jsonl",
        "output_subdir": "saiketsu-pm11-54-cpu",
    },
    {
        "tag": "tsutatsu55cpu",
        "instance": "ml.c5.xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/nta_tsutatsu_index/part-0000.jsonl",
        "output_subdir": "tsutatsu-pm11-55-cpu",
    },
    # ---- 4 x m5.xlarge CPU (burst lane, mid-sized parts) ----
    {
        "tag": "programs56cpu",
        "instance": "ml.m5.xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/programs/part-0000.jsonl",
        "output_subdir": "programs-pm11-56-cpu",
    },
    {
        "tag": "adoption57cpu",
        "instance": "ml.m5.xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/adoption_records/part-0001.jsonl",
        "output_subdir": "adoption-pm11-57-cpu",
    },
    {
        "tag": "amlaw58cpu",
        "instance": "ml.m5.xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0007.jsonl",
        "output_subdir": "amlaw-pm11-58-cpu",
    },
    {
        "tag": "amlaw59cpu",
        "instance": "ml.m5.xlarge",
        "model": CPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0008.jsonl",
        "output_subdir": "amlaw-pm11-59-cpu",
    },
    # ---- 2 x g4dn.xlarge GPU (mirror lane for densest law_article parts) ----
    {
        "tag": "amlaw60gpu",
        "instance": "ml.g4dn.xlarge",
        "model": GPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0001.jsonl",
        "output_subdir": "amlaw-pm11-60-gpu",
    },
    {
        "tag": "amlaw61gpu",
        "instance": "ml.g4dn.xlarge",
        "model": GPU_MODEL,
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0012.jsonl",
        "output_subdir": "amlaw-pm11-61-gpu",
    },
]


def preflight_cost_check() -> float:
    """Run 5-line hard-stop preflight."""
    ce = ce_client(region_name=REGION, profile_name=PROFILE)
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
            {"Key": "wave", "Value": "PM11"},
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
    parser = argparse.ArgumentParser(description="SageMaker PM11 saturate driver (Lane B 20 jobs)")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually create jobs (default: DRY_RUN)",
    )
    parser.add_argument(
        "--records-out",
        type=str,
        default="docs/_internal/sagemaker_pm11_2026_05_17_records.json",
        help="Path to write submit ledger JSON",
    )
    args = parser.parse_args()

    actual_usd = preflight_cost_check()
    print(f"[preflight] actual_usd={actual_usd} < {HARD_STOP_USD} OK")

    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    print(f"[run_id] {run_id}")

    print(f"[plan] PM11 jobs = {len(PM11_JOBS)}")
    instance_dist: dict[str, int] = {}
    for job in PM11_JOBS:
        instance_dist[job["instance"]] = instance_dist.get(job["instance"], 0) + 1
    for inst, count in sorted(instance_dist.items()):
        print(f"  {inst:24s} x {count}")

    if not args.commit:
        print("[DRY_RUN] Would submit:")
        for job in PM11_JOBS:
            print(f"  - {job['tag']:18s} {job['instance']:18s} {job['input']}")
        sys.exit(0)

    sm = sagemaker_client(region_name=REGION, profile_name=PROFILE)
    submitted: list[dict[str, str]] = []
    for job in PM11_JOBS:
        try:
            result = submit_transform_job(sm, run_id, job)
            submitted.append(result)
            print(f"[OK] {result['job_name']}  {result['arn']}")
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {job['tag']}: {e}", file=sys.stderr)

    ledger = {
        "run_id": run_id,
        "predecessor_run_id": "20260516T160602Z",
        "predecessor_wave": "PM10",
        "budget_actual_usd": actual_usd,
        "quotas": {
            "ml.c5.2xlarge for transform job usage": 8.0,
            "ml.c5.xlarge for transform job usage": 16.0,
            "ml.m5.xlarge for transform job usage": 8.0,
            "ml.g4dn.xlarge for transform job usage": 4.0,
        },
        "instance_distribution": instance_dist,
        "lane": "B",
        "target_jobs": len(PM11_JOBS),
        "submitted_count": len(submitted),
        "submitted": submitted,
    }
    out_path = Path(args.records_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))
    print(f"[ledger] {out_path}  ({len(submitted)}/{len(PM11_JOBS)} submitted)")


if __name__ == "__main__":
    main()
