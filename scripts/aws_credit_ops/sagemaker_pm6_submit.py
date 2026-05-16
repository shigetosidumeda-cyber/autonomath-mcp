#!/usr/bin/env python3
"""SageMaker PM6 saturate driver.

Purpose
-------
PM5 (run_id ``20260516T103042Z``, commit ``c7df91f23``) submitted 5 transform
jobs (3 c5.2xlarge CPU + 2 g4dn.xlarge GPU) with ``BatchStrategy=SingleRecord``.
All 5 Completed successfully. Per-job timings::

    court21gpu       ml.g4dn.xlarge   ~5 min   part-0000 (848 rows truncated)
    tsutatsu20gpu    ml.g4dn.xlarge   ~8 min   part-0000 (3,232 rows truncated)
    saiketsu19       ml.c5.2xlarge    ~2 min   part-0000 (137 rows)
    invoice18        ml.c5.2xlarge    ~9 min   part-0000 (13,801 rows)
    programs17       ml.c5.2xlarge    ~9 min   part-0000 (12,753 rows)

PM6 saturate
------------
After PM5 drained (5/5 Completed, 0 in-flight at submit), the ``ml.g4dn.xlarge``
quota is fully free (used 0 / 4). PM6 submits 2 more g4dn.xlarge jobs on the
next 2 untouched truncated ``am_law_article/part-0001.jsonl`` and
``am_law_article/part-0002.jsonl`` prefixes — both 16-17 MB and never embedded
in any prior PM* run.

Task note: the user asked for ``am_law_article/part-0006.jsonl`` (next part)
and ``court_decisions/part-0001.jsonl`` (next part if exists). Neither exist:

* ``corpus_export_trunc/am_law_article/`` has only parts 0001-0004 (4 truncated
  parts; PM4 attempted parts 0001-0002 but failed with MULTI_RECORD body bug).
* ``corpus_export_trunc/court_decisions/`` has only ``part-0000.jsonl``
  (PM5 court21gpu already consumed it).

So PM6 substitutes with the **actual** next 2 untouched truncated am_law_article
parts (0001 + 0002) to fully saturate the 2 remaining g4dn slots. The PM4
contract regression is irrelevant here because PM6 uses
``BatchStrategy=SingleRecord`` (carried over from PM5).

5-line hard-stop
----------------
Cost preflight ``aws ce get-cost-and-usage`` returned ``$0.0000001906`` for
May 2026. $13K threshold blocks ``create_transform_job`` if breached. AWS
Budget Action at $18,900 is the ultimate stop.

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

# 2 g4dn.xlarge jobs saturating the remaining GPU slots after PM5.
PM6_JOBS: list[dict[str, str]] = [
    {
        "tag": "amlaw22gpu",
        "instance": "ml.g4dn.xlarge",
        "model": "jpcite-embed-allminilm-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0001.jsonl",
        "output_subdir": "amlaw-fix22-gpu",
    },
    {
        "tag": "amlaw23gpu",
        "instance": "ml.g4dn.xlarge",
        "model": "jpcite-embed-allminilm-v1",
        "input": f"s3://{DERIVED_BUCKET}/corpus_export_trunc/am_law_article/part-0002.jsonl",
        "output_subdir": "amlaw-fix23-gpu",
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
        "BatchStrategy": "SingleRecord",  # PM5/PM6 fix carry-over
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
            {"Key": "wave", "Value": "PM6"},
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
    parser = argparse.ArgumentParser(description="SageMaker PM6 saturate driver")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually create jobs (default: DRY_RUN)",
    )
    parser.add_argument(
        "--records-out",
        type=str,
        default="docs/_internal/sagemaker_pm6_2026_05_16_records.json",
        help="Path to write submit ledger JSON",
    )
    args = parser.parse_args()

    actual_usd = preflight_cost_check()
    print(f"[preflight] actual_usd={actual_usd} < {HARD_STOP_USD} OK")

    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    print(f"[run_id] {run_id}")

    if not args.commit:
        print("[DRY_RUN] Would submit:")
        for job in PM6_JOBS:
            print(f"  - {job['tag']:14s} {job['instance']:18s} {job['input']}")
        sys.exit(0)

    sm = sagemaker_client(region_name=REGION, profile_name=PROFILE)
    submitted: list[dict[str, str]] = []
    for job in PM6_JOBS:
        try:
            result = submit_transform_job(sm, run_id, job)
            submitted.append(result)
            print(f"[OK] {result['job_name']}  {result['arn']}")
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {job['tag']}: {e}", file=sys.stderr)

    ledger = {
        "run_id": run_id,
        "predecessor_run_id": "20260516T103042Z",
        "predecessor_commit": "c7df91f23",
        "budget_actual_usd": actual_usd,
        "quotas": {
            "ml.c5.2xlarge for transform job usage": 8.0,
            "ml.g4dn.xlarge for transform job usage": 4.0,
        },
        "fix_applied": "BatchStrategy=SingleRecord (PM5 carry-over; PM4 default MULTI_RECORD broke MMS handler)",
        "submitted": submitted,
    }
    out_path = Path(args.records_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))
    print(f"[ledger] {out_path}  ({len(submitted)}/{len(PM6_JOBS)} submitted)")


if __name__ == "__main__":
    main()
