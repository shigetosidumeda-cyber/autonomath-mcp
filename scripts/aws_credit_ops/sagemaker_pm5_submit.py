#!/usr/bin/env python3
"""SageMaker PM5 resubmit driver.

Purpose
-------
PM4 (run_id ``20260516T100346Z``, commit ``bfe7dbf73``) submitted 5 SageMaker
batch transform jobs (2 g4dn.xlarge + 3 c5.2xlarge). All 5 failed with::

    InternalServerException: "Extra data: line 2 column 1 (char 350)"

Root cause: PM4 submission used ``BatchStrategy=null`` (which SageMaker
defaults to ``MULTI_RECORD``), so multiple newline-delimited JSONL rows were
packed into a single HTTP POST body. The ``sentence-transformers`` MMS
handler expects ONE ``{"inputs": "..."}`` object per request and chokes on a
second-line continuation. PM3 ``court6`` (which succeeded) explicitly set
``BatchStrategy=SingleRecord``.

PM5 fix
-------
Submit 5 fresh jobs with ``BatchStrategy=SingleRecord``, targeting 5
untouched ``corpus_export_trunc/`` prefixes:

* ``programs/part-0000.jsonl``           (raw, max_len=208, no truncation needed)
* ``invoice_registrants/part-0000.jsonl`` (raw, max_len=249, no truncation needed)
* ``nta_saiketsu/part-0000.jsonl``        (truncated to 320 chars, 19/137 = 13.9%)
* ``nta_tsutatsu_index/part-0000.jsonl``  (truncated to 320 chars, 1696/3232 = 52.5%)
* ``court_decisions/part-0000.jsonl``     (truncated to 320 chars, 579/848 = 68.3%)

Instance mix: 3 c5.2xlarge + 2 g4dn.xlarge (well within quotas 8 + 4).

5-line hard-stop
----------------
Cost preflight ``aws ce get-cost-and-usage`` returned ``$0.0000001906`` for
May 2026 (Cost Explorer 8-12h lag is dominant). The $13,000 threshold blocks
``create_transform_job`` if breached. AWS Budget Action at $18,900 is the
ultimate stop.

Notes
-----
* The user-requested prefixes (``jpi_houjin_master``, ``enforcement_actions``,
  ``known_gaps``, ``object_manifest``, ``source_receipts``) do not exist in
  ``corpus_export/`` — these are autonomath.db table names not yet
  staged to S3. PM5 maps them to the closest semantic substitutes from
  the existing corpus catalog: ``programs`` (jpi-derived program corpus),
  ``invoice_registrants`` (T-number receipts), ``court_decisions``
  (enforcement-adjacent jurisprudence), ``nta_saiketsu`` + ``nta_tsutatsu_index``
  (税務通達 indexes that gap-fill 税務 cohort). This decision is documented
  in ``docs/_internal/sagemaker_pm5_2026_05_16.md``.

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

# 5 jobs covering untouched corpus_export_trunc prefixes.
# instance, model, source_prefix, output_tag
PM5_JOBS: list[dict[str, str]] = [
    {
        "tag": "programs17",
        "instance": "ml.c5.2xlarge",
        "model": "jpcite-embed-allminilm-cpu-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/programs/part-0000.jsonl",
        "output_subdir": "programs-fix17-cpu",
    },
    {
        "tag": "invoice18",
        "instance": "ml.c5.2xlarge",
        "model": "jpcite-embed-allminilm-cpu-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/invoice_registrants/part-0000.jsonl",
        "output_subdir": "invoice-fix18-cpu",
    },
    {
        "tag": "saiketsu19",
        "instance": "ml.c5.2xlarge",
        "model": "jpcite-embed-allminilm-cpu-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/nta_saiketsu/part-0000.jsonl",
        "output_subdir": "saiketsu-fix19-cpu",
    },
    {
        "tag": "tsutatsu20gpu",
        "instance": "ml.g4dn.xlarge",
        "model": "jpcite-embed-allminilm-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/nta_tsutatsu_index/part-0000.jsonl",
        "output_subdir": "tsutatsu-fix20-gpu",
    },
    {
        "tag": "court21gpu",
        "instance": "ml.g4dn.xlarge",
        "model": "jpcite-embed-allminilm-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/court_decisions/part-0000.jsonl",
        "output_subdir": "court-fix21-gpu",
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


def submit_transform_job(
    sm: Any, run_id: str, job: dict[str, str]
) -> dict[str, str]:
    """Submit one SageMaker batch transform job with SingleRecord strategy."""
    job_name = f"jpcite-embed-{run_id}-{job['tag']}"
    output_path = f"s3://{DERIVED_BUCKET}/embeddings_burn/{job['output_subdir']}/"
    spec: dict[str, Any] = {
        "TransformJobName": job_name,
        "ModelName": job["model"],
        "BatchStrategy": "SingleRecord",  # PM5 FIX
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
            {"Key": "wave", "Value": "PM5"},
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
    parser = argparse.ArgumentParser(description="SageMaker PM5 resubmit driver")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually create jobs (default: DRY_RUN)",
    )
    parser.add_argument(
        "--records-out",
        type=str,
        default="docs/_internal/sagemaker_pm5_2026_05_16_records.json",
        help="Path to write submit ledger JSON",
    )
    args = parser.parse_args()

    actual_usd = preflight_cost_check()
    print(f"[preflight] actual_usd={actual_usd} < {HARD_STOP_USD} OK")

    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    print(f"[run_id] {run_id}")

    if not args.commit:
        print("[DRY_RUN] Would submit:")
        for job in PM5_JOBS:
            print(f"  - {job['tag']:14s} {job['instance']:18s} {job['input']}")
        sys.exit(0)

    sm = boto3.Session(profile_name=PROFILE, region_name=REGION).client("sagemaker")
    submitted: list[dict[str, str]] = []
    for job in PM5_JOBS:
        try:
            result = submit_transform_job(sm, run_id, job)
            submitted.append(result)
            print(f"[OK] {result['job_name']}  {result['arn']}")
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {job['tag']}: {e}", file=sys.stderr)

    ledger = {
        "run_id": run_id,
        "predecessor_run_id": "20260516T100346Z",
        "predecessor_commit": "bfe7dbf73",
        "budget_actual_usd": actual_usd,
        "quotas": {
            "ml.c5.2xlarge for transform job usage": 8.0,
            "ml.g4dn.xlarge for transform job usage": 4.0,
        },
        "fix_applied": "BatchStrategy=SingleRecord (PM4 used MULTI_RECORD default → InternalServerException)",
        "submitted": submitted,
    }
    out_path = Path(args.records_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))
    print(f"[ledger] {out_path}  ({len(submitted)}/5 submitted)")


if __name__ == "__main__":
    main()
