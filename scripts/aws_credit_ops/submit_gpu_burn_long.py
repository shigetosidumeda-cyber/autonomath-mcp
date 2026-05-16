#!/usr/bin/env python3
"""Submit 6 long-running EC2 Spot GPU Batch jobs for sustained credit burn.

Targets ``jpcite-credit-ec2-spot-gpu-queue`` using the new ``jpcite-gpu-burn-long``
job definition (registered 2026-05-16) which uses a public Python slim image
(no rogue ENTRYPOINT) and a 21-hour ``attemptDurationSeconds``. Each job sets
``MIN_RUNTIME_SECONDS=72000`` (20 hours) so the GPU matmul idle-loop pads the
attempt floor to the credit-burn budget.

Workload split (each job 1× GPU, 16 vCPU, 60 GB RAM):

* 3 FAISS index rebuilds on the canonical ``intfloat/multilingual-e5-small``
  model across different corpus shards (cohort A: ``programs``, cohort B:
  ``am_law_article``, cohort C: ``adoption_records,court_decisions,nta_*``)
  with varying ``FAISS_LIMIT`` for "different shard sizes" retrieval testing.
* 3 sentence-transformer "fine-tune-style" encoding sweeps using the smaller
  ``sentence-transformers/all-MiniLM-L6-v2`` model (also 384-d → drop-in
  compatible with downstream FAISS readers). Same encoding pipeline, different
  cohort emphasis. Open-weight only. NO LLM API.

Burn math:

* Spot pricing on g4dn.4xlarge / g4dn.8xlarge / g5.4xlarge / g5.8xlarge mix
  averages ~$0.55-1.10/hr in ap-northeast-1 (varies by AZ + capacity).
* 6 × 20h × ~$1.50/hr (after EBS + data egress headroom) ≈ ~$180/day burn,
  ≈ ~$900 over the full 5-day run. Well under the $1,500 task budget cap.
* GPU CE max vCPU 64. Each job needs 16 vCPU → max 4 concurrent. Jobs 5-6
  queue and run in the next Spot wave (RUNNABLE → STARTING when capacity
  recycles), which is intentional — the queue holds them while early jobs
  finish.

Constraints (verified):

* ``bookyou-recovery`` AWS profile.
* Open-weight sentence-transformers only (e5-small, all-MiniLM-L6-v2).
* NO LLM API.
* Each job ``attemptDurationSeconds=75600`` (21h) and
  ``MIN_RUNTIME_SECONDS=72000`` (20h).
* Heavy tags ``Workload=long_burn_gpu``, ``AutoStop=2026-05-29`` for the
  auto-stop Lambda + budget guard.
* Budget Action hard-stop at $18,900 is the safety net — we stay <$1,500 of
  cumulative burn for this batch by capping at 6 jobs × 20h.

``[lane:solo]`` marker on the parent commit.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

try:
    from scripts.aws_credit_ops._aws import get_session
except ImportError:  # pragma: no cover - boto3 always present in our venv
    sys.stderr.write("boto3 not installed; pip install boto3\n")
    sys.exit(2)

logger = logging.getLogger("submit_gpu_burn_long")

JOB_QUEUE = "jpcite-credit-ec2-spot-gpu-queue"
JOB_DEFINITION = "jpcite-gpu-burn-long"
REGION = "ap-northeast-1"

# 20 hours sustained burn floor + 21 hours attempt cap. Spot may interrupt
# earlier; the retryStrategy on the job def is attempts=1 because we are
# happy to lose a job to a Spot reclaim — submitting 6 means we still get
# ~5 full runs even with 1 interruption.
MIN_RUNTIME_SECONDS = "72000"

# 6 jobs — 3 FAISS index rebuilds across cohorts, 3 fine-tune-style sweeps.
JOBS: list[dict[str, Any]] = [
    {
        "name_suffix": "faiss-programs-deep",
        "tables": "programs",
        "limit": "150000",
        "model": "intfloat/multilingual-e5-small",
        "workload_tag": "long_burn_gpu",
        "subwork_tag": "faiss-programs-deep",
    },
    {
        "name_suffix": "faiss-laws-deep",
        "tables": "am_law_article",
        "limit": "200000",
        "model": "intfloat/multilingual-e5-small",
        "workload_tag": "long_burn_gpu",
        "subwork_tag": "faiss-laws-deep",
    },
    {
        "name_suffix": "faiss-cross-cohort",
        "tables": "adoption_records,court_decisions,nta_saiketsu,nta_tsutatsu_index",
        "limit": "200000",
        "model": "intfloat/multilingual-e5-small",
        "workload_tag": "long_burn_gpu",
        "subwork_tag": "faiss-cross-cohort",
    },
    {
        "name_suffix": "finetune-minilm-programs",
        "tables": "programs",
        "limit": "120000",
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "workload_tag": "long_burn_gpu",
        "subwork_tag": "finetune-minilm-programs",
    },
    {
        "name_suffix": "finetune-minilm-laws",
        "tables": "am_law_article",
        "limit": "180000",
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "workload_tag": "long_burn_gpu",
        "subwork_tag": "finetune-minilm-laws",
    },
    {
        "name_suffix": "finetune-minilm-adoption",
        "tables": "adoption_records",
        "limit": "150000",
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "workload_tag": "long_burn_gpu",
        "subwork_tag": "finetune-minilm-adoption",
    },
]


def _ts() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def build_submit_kwargs(spec: dict[str, Any], stamp: str) -> dict[str, Any]:
    job_name = f"jpcite-gpu-burn-{spec['name_suffix']}-{stamp}"
    return {
        "jobName": job_name,
        "jobQueue": JOB_QUEUE,
        "jobDefinition": JOB_DEFINITION,
        "tags": {
            "Project": "jpcite",
            "AutoStop": "2026-05-29",
            "CreditRun": "2026-05",
            "Workload": spec["workload_tag"],
            "Subwork": spec["subwork_tag"],
            "RuntimeFloorHours": "20",
        },
        "propagateTags": True,
        "containerOverrides": {
            "environment": [
                {"name": "FAISS_TABLES", "value": spec["tables"]},
                {"name": "FAISS_LIMIT", "value": spec["limit"]},
                {"name": "FAISS_MODEL", "value": spec["model"]},
                {"name": "MIN_RUNTIME_SECONDS", "value": MIN_RUNTIME_SECONDS},
                {"name": "JPCITE_SUBWORK", "value": spec["subwork_tag"]},
            ],
        },
    }


def submit_all(
    *,
    profile: str,
    dry_run: bool,
    only: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    session = get_session(region_name=REGION, profile_name=profile)
    batch = session.client("batch")
    stamp = _ts()
    submitted: list[dict[str, Any]] = []
    for spec in JOBS:
        if only and spec["name_suffix"] not in only:
            logger.info("skipping %s (not in --only list)", spec["name_suffix"])
            continue
        kwargs = build_submit_kwargs(spec, stamp)
        logger.info(
            "submit job=%s tables=%s model=%s limit=%s",
            kwargs["jobName"],
            spec["tables"],
            spec["model"],
            spec["limit"],
        )
        if dry_run:
            submitted.append(
                {
                    "jobName": kwargs["jobName"],
                    "dry_run": True,
                    "kwargs": kwargs,
                }
            )
            continue
        resp = batch.submit_job(**kwargs)
        submitted.append(
            {
                "jobName": resp["jobName"],
                "jobId": resp["jobId"],
                "jobArn": resp["jobArn"],
                "subwork": spec["subwork_tag"],
                "model": spec["model"],
                "tables": spec["tables"],
                "limit": spec["limit"],
            }
        )
    return submitted


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--profile", default="bookyou-recovery")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="optional whitelist of name_suffix values to submit",
    )
    p.add_argument(
        "--output",
        default=None,
        help="optional path to write the submission ledger JSON",
    )
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    args = parse_args(argv)
    submitted = submit_all(
        profile=args.profile,
        dry_run=args.dry_run,
        only=args.only,
    )
    out_text = json.dumps(
        {
            "submitted_at": _ts(),
            "job_queue": JOB_QUEUE,
            "job_definition": JOB_DEFINITION,
            "region": REGION,
            "dry_run": args.dry_run,
            "jobs": submitted,
        },
        ensure_ascii=False,
        indent=2,
    )
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out_text + "\n")
        logger.info("wrote ledger to %s", args.output)
    sys.stdout.write(out_text + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
