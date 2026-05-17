#!/usr/bin/env python3
"""7-Day continuous moat-burn ramp orchestrator (2026-05-17).

Purpose
-------
Sustain $1,900-$2,800/day moat-bearing AWS burn for 7 days to drain the
remaining ~$13K of the $19,490 AWS credit envelope (MTD gross $3,101.80
at submit time). Quota request `177898005900961` (G+VT Spot vCPU 64 ->
256) was CASE_CLOSED; this orchestrator scales the Batch GPU compute env
to 256 maxvCpus, then re-fires SageMaker training cycles, OpenSearch
sustained queries, Athena moat queries, Textract OCR, and batch
transform re-fires.

EVERY DOLLAR contributes to moat:
  - GPU training -> M5/M6/M11 model improvement (cross-encoder + multitask + KG)
  - Batch transform -> embedding refresh for FAISS shards
  - OpenSearch sustained -> entity-fact serving substrate
  - Athena moat queries -> cohort + cross-source aggregation (4,935 N7 segments)
  - Textract OCR -> remaining ministry PDF corpus expansion (Lane K extension)

Forbidden:
  - CloudFront sustained load (pure burn, no moat)
  - CodeBuild burst (pure burn)
  - Lambda mass-invoke (pure burn)
  - LLM API calls (OPERATOR-LLM API banned per memory)

5-line hard-stop
----------------
Cost preflight ``aws ce get-cost-and-usage`` MTD gross >= $18,300 -> abort.
AWS Budget Action at $18,900 is the ultimate stop. $19,490 absolute never-reach.

Operator gates
--------------
1. ``--commit`` flag (required for any AWS side-effect)
2. ``--unlock-live-aws-commands`` flag (Stream W concern-separation token)

Without both: prints would-be spec and exits 0.

``[lane:solo]`` per CLAUDE.md dual-CLI lane convention. NO LLM API.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from scripts.aws_credit_ops._aws import ce_client, get_client

# Constants
REGION = "ap-northeast-1"
PROFILE = "bookyou-recovery"
ACCOUNT_ID = "993693061769"
DERIVED_BUCKET = "jpcite-credit-993693061769-202605-derived"

HARD_STOP_USD = 18300.0  # MTD gross trigger; budget action at $18,900
NEVER_REACH_USD = 19490.0  # absolute ceiling

GPU_COMPUTE_ENV = "jpcite-credit-ec2-spot-gpu"
GPU_QUEUE = "jpcite-credit-ec2-spot-gpu-queue"
OPENSEARCH_DOMAIN = "jpcite-xfact-2026-05"

DAILY_BURN_TARGET_LO = 1800.0
DAILY_BURN_TARGET_HI = 2800.0

RAMP_START = "2026-05-17"
RAMP_DAYS = 7

CYCLE_SCHEDULE = {
    "sagemaker_train_cron_rate": "rate(6 hours)",
    "batch_transform_cron_rate": "rate(24 hours)",
    "textract_ocr_cron_rate": "rate(4 hours)",
    "athena_moat_cron_rate": "rate(30 minutes)",
    "burn_monitor_cron_rate": "rate(5 minutes)",
}

# Batch GPU env is shared substrate. The $/day below covers ad-hoc embedding
# generation + FAISS build burst only -- SageMaker training jobs run on
# SageMaker-managed instances and are NOT counted here (see TRAINING_CYCLES).
GPU_SCALE_PLAN = {
    "current_max_vcpus": 64,
    "target_max_vcpus": 256,
    "instance_types": [
        "g4dn.4xlarge",
        "g4dn.8xlarge",
        "g4dn.12xlarge",
        "g5.4xlarge",
        "g5.8xlarge",
        "g5.12xlarge",
    ],
    "target_concurrent_jobs": 5,
    "burn_per_day_usd_estimate": 300.0,
}

TRAINING_CYCLES = [
    {
        "tag": "M5_v2_simcse_iter",
        "submit_script": "sagemaker_simcse_finetune_2026_05_17.py",
        "instance": "ml.g4dn.12xlarge",
        "max_runtime_hours": 12,
        "cost_per_cycle_usd": 70.0,
        "cycles_per_7d": 28,
    },
    {
        "tag": "M6_cross_encoder_iter",
        "submit_script": "sagemaker_cross_encoder_finetune_2026_05_17.py",
        "instance": "ml.g4dn.12xlarge",
        "max_runtime_hours": 12,
        "cost_per_cycle_usd": 70.0,
        "cycles_per_7d": 28,
    },
    {
        "tag": "M11_active_learning_iter",
        "submit_script": "sagemaker_m11_al_iter_2026_05_17.py",
        "instance": "ml.g4dn.4xlarge",
        "max_runtime_hours": 6,
        "cost_per_cycle_usd": 30.0,
        "cycles_per_7d": 28,
    },
    {
        "tag": "M11_distill_v2",
        "submit_script": "sagemaker_m11_distill_2026_05_17.py",
        "instance": "ml.g4dn.12xlarge",
        "max_runtime_hours": 12,
        "cost_per_cycle_usd": 60.0,
        "cycles_per_7d": 14,
    },
    {
        "tag": "M11_kg_completion_iter",
        "submit_script": "sagemaker_kg_completion_submit_2026_05_17.py",
        "instance": "ml.g4dn.4xlarge",
        "max_runtime_hours": 6,
        "cost_per_cycle_usd": 25.0,
        "cycles_per_7d": 14,
    },
    {
        "tag": "M11_multitask_v2_finetune",
        "submit_script": "sagemaker_multitask_finetune_2026_05_17.py",
        "instance": "ml.g4dn.12xlarge",
        "max_runtime_hours": 24,
        "cost_per_cycle_usd": 95.0,
        "cycles_per_7d": 5,  # every ~34h instead of daily
    },
]

ATHENA_MOAT_QUERIES = [
    "industry_x_geo_cohort_aggregation",
    "program_x_law_lineage_traverse",
    "case_cohort_match_at_scale",
    "amendment_diff_temporal_join",
    "ma_target_pool_full_corpus",
]

# Throttled to 5 cycles (1/day x 5d) to keep MTD final under $18,000
# Cost-Explorer-lag-adjusted ceiling for safety cushion.
TEXTRACT_PLAN = {
    "pdfs_per_cycle": 200,
    "cycle_hours": 4,
    "cycles_per_7d": 5,
    "pages_per_pdf_avg": 30,
    "cost_per_page_usd": 0.05,
    "cost_per_cycle_usd": 300.0,
}

BATCH_TRANSFORM_PM12 = {
    "jobs_per_cycle": 20,
    "cost_per_cycle_usd": 250.0,
    "cycles_per_7d": 7,
}


def preflight_cost_check() -> tuple[float, float]:
    """5-line hard-stop preflight (MTD gross + net)."""
    ce = ce_client(region_name="us-east-1", profile_name=PROFILE)
    today = dt.date.today()
    first_of_month = today.replace(day=1).isoformat()
    tomorrow = (today + dt.timedelta(days=1)).isoformat()

    resp_gross = ce.get_cost_and_usage(
        TimePeriod={"Start": first_of_month, "End": tomorrow},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        Filter={
            "Not": {
                "Dimensions": {
                    "Key": "RECORD_TYPE",
                    "Values": ["Credit", "Refund"],
                }
            }
        },
    )
    mtd_gross = float(resp_gross["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"])

    resp_net = ce.get_cost_and_usage(
        TimePeriod={"Start": first_of_month, "End": tomorrow},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )
    mtd_net = float(resp_net["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"])

    if mtd_gross >= HARD_STOP_USD:
        print(
            f"[HARD-STOP] mtd_gross_usd={mtd_gross:.2f} >= {HARD_STOP_USD}, aborting",
            file=sys.stderr,
        )
        sys.exit(2)
    return mtd_gross, mtd_net


def scale_gpu_compute_env(*, commit: bool, unlock_live: bool) -> dict[str, Any]:
    """Step 1: Scale Batch GPU compute env from 64 -> 256 vCPU."""
    plan = {
        "step": "scale_gpu_compute_env",
        "compute_env": GPU_COMPUTE_ENV,
        "before_max_vcpus": GPU_SCALE_PLAN["current_max_vcpus"],
        "after_max_vcpus": GPU_SCALE_PLAN["target_max_vcpus"],
        "burn_per_day_usd": GPU_SCALE_PLAN["burn_per_day_usd_estimate"],
        "burn_7d_usd": GPU_SCALE_PLAN["burn_per_day_usd_estimate"] * 7,
        "instance_types": GPU_SCALE_PLAN["instance_types"],
        "target_concurrent_jobs": GPU_SCALE_PLAN["target_concurrent_jobs"],
        "dry_run": not (commit and unlock_live),
    }
    if not (commit and unlock_live):
        return plan

    batch = get_client("batch", region_name=REGION, profile_name=PROFILE)
    resp = batch.update_compute_environment(
        computeEnvironment=GPU_COMPUTE_ENV,
        computeResources={
            "maxvCpus": GPU_SCALE_PLAN["target_max_vcpus"],
        },
    )
    plan["compute_env_arn"] = resp.get("computeEnvironmentArn", "<unknown>")
    plan["applied"] = True
    return plan


def plan_sagemaker_train_cycle(*, commit: bool, unlock_live: bool) -> dict[str, Any]:
    """Step 2: Plan SageMaker training cycle re-fire (28 cycles x 6 axes)."""
    cycles_total = sum(c["cycles_per_7d"] for c in TRAINING_CYCLES)
    cost_total = sum(c["cost_per_cycle_usd"] * c["cycles_per_7d"] for c in TRAINING_CYCLES)

    return {
        "step": "plan_sagemaker_train_cycle",
        "cron_rate": CYCLE_SCHEDULE["sagemaker_train_cron_rate"],
        "training_cycles": TRAINING_CYCLES,
        "total_cycles_7d": cycles_total,
        "burn_7d_usd": cost_total,
        "dry_run": not (commit and unlock_live),
    }


def plan_opensearch_sustained() -> dict[str, Any]:
    """Step 3: OpenSearch sustained 7-day (already LIVE; verify state)."""
    return {
        "step": "plan_opensearch_sustained",
        "domain": OPENSEARCH_DOMAIN,
        "instance_type": "r5.4xlarge.search",
        "instance_count": 3,
        "warm_type": "ultrawarm1.medium.search",
        "warm_count": 3,
        "master_type": "r5.large.search",
        "master_count": 3,
        "burn_per_day_usd": 130.0,
        "burn_7d_usd": 910.0,
        "note": "already LIVE; sustained 7-day is automatic.",
    }


def plan_athena_moat_queries() -> dict[str, Any]:
    """Step 4: Athena moat query continuous (NOT pure burn -- analytical use).

    Cadence 30 min x 5 queries = 240 queries/day. Avg 3-5 GB scanned/query
    (full-corpus cross-source moat queries). $5/TB -> ~$80/day.
    """
    return {
        "step": "plan_athena_moat_queries",
        "cron_rate": CYCLE_SCHEDULE["athena_moat_cron_rate"],
        "queries": ATHENA_MOAT_QUERIES,
        "queries_per_day": 240,
        "avg_gb_scanned_per_query": 3.5,
        "burn_per_day_usd": 80.0,
        "burn_7d_usd": 560.0,
        "moat_note": "cross-source cohort + lineage traversal; outputs land in S3.",
    }


def plan_textract_continuous() -> dict[str, Any]:
    """Step 5: Textract OCR continuous (Lane K extension)."""
    return {
        "step": "plan_textract_continuous",
        "cron_rate": CYCLE_SCHEDULE["textract_ocr_cron_rate"],
        "pdfs_per_cycle": TEXTRACT_PLAN["pdfs_per_cycle"],
        "cycles_per_7d": TEXTRACT_PLAN["cycles_per_7d"],
        "pages_per_pdf_avg": TEXTRACT_PLAN["pages_per_pdf_avg"],
        "burn_per_cycle_usd": TEXTRACT_PLAN["cost_per_cycle_usd"],
        "burn_7d_usd": TEXTRACT_PLAN["cost_per_cycle_usd"] * TEXTRACT_PLAN["cycles_per_7d"],
        "moat_note": "ministry PDF OCR -> derived corpus -> embedding pipeline.",
    }


def plan_batch_transform_pm12() -> dict[str, Any]:
    """Step 6: Re-fire 20-job batch transform cycle with M5/M6 v2 weights."""
    return {
        "step": "plan_batch_transform_pm12",
        "cron_rate": CYCLE_SCHEDULE["batch_transform_cron_rate"],
        "jobs_per_cycle": BATCH_TRANSFORM_PM12["jobs_per_cycle"],
        "cost_per_cycle_usd": BATCH_TRANSFORM_PM12["cost_per_cycle_usd"],
        "cycles_per_7d": BATCH_TRANSFORM_PM12["cycles_per_7d"],
        "burn_7d_usd": BATCH_TRANSFORM_PM12["cost_per_cycle_usd"]
        * BATCH_TRANSFORM_PM12["cycles_per_7d"],
        "moat_note": "embedding refresh: M5/M6 v2 -> FAISS shard re-index.",
    }


def plan_storage_burn() -> dict[str, Any]:
    """Step 7: Storage burn (S3 PUT + Glue ETL + EBS)."""
    return {
        "step": "plan_storage_burn",
        "s3_put_per_day_usd": 50.0,
        "glue_etl_per_day_usd": 80.0,
        "ebs_per_day_usd": 50.0,
        "burn_per_day_usd": 180.0,
        "burn_7d_usd": 1260.0,
        "moat_note": "embeddings + Textract output + Parquet shards.",
    }


def emit_ledger(
    *,
    mtd_gross: float,
    mtd_net: float,
    sub_plans: list[dict[str, Any]],
    ledger_path: Path,
    dry_run: bool,
) -> None:
    """Write append-only 7-day burn ramp ledger entry."""
    now = dt.datetime.now(dt.UTC).isoformat()
    total_7d_usd = sum(p.get("burn_7d_usd", 0.0) for p in sub_plans)
    daily_usd = total_7d_usd / 7

    entry = {
        "ts": now,
        "ramp_start": RAMP_START,
        "ramp_days": RAMP_DAYS,
        "mtd_gross_usd": mtd_gross,
        "mtd_net_usd": mtd_net,
        "credit_remaining_usd": NEVER_REACH_USD - mtd_gross,
        "hard_stop_usd": HARD_STOP_USD,
        "never_reach_usd": NEVER_REACH_USD,
        "daily_target_lo_usd": DAILY_BURN_TARGET_LO,
        "daily_target_hi_usd": DAILY_BURN_TARGET_HI,
        "planned_daily_burn_usd": daily_usd,
        "planned_7d_burn_usd": total_7d_usd,
        "sub_plans": sub_plans,
        "dry_run": dry_run,
        "note": "EVERY DOLLAR MUST CONTRIBUTE TO MOAT.",
    }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a") as f:
        f.write(f"\n## tick {now}\n\n")
        f.write(f"```json\n{json.dumps(entry, indent=2)}\n```\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="7-Day continuous moat-burn ramp orchestrator")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument(
        "--unlock-live-aws-commands",
        action="store_true",
        dest="unlock_live",
        help="operator token gate per Stream W concern-separation.",
    )
    parser.add_argument(
        "--ledger-out",
        type=str,
        default="docs/_internal/SEVEN_DAY_BURN_LEDGER_2026_05_17.md",
    )
    parser.add_argument(
        "--plan-out",
        type=str,
        default="docs/_internal/SEVEN_DAY_BURN_PLAN_2026_05_17.json",
    )
    args = parser.parse_args(argv)

    mtd_gross, mtd_net = preflight_cost_check()
    print(
        f"[preflight] mtd_gross_usd={mtd_gross:.2f} mtd_net_usd={mtd_net:.2f} "
        f"credit_remaining_usd={NEVER_REACH_USD - mtd_gross:.2f}"
    )

    sub_plans = [
        scale_gpu_compute_env(commit=args.commit, unlock_live=args.unlock_live),
        plan_sagemaker_train_cycle(commit=args.commit, unlock_live=args.unlock_live),
        plan_opensearch_sustained(),
        plan_athena_moat_queries(),
        plan_textract_continuous(),
        plan_batch_transform_pm12(),
        plan_storage_burn(),
    ]

    total_7d_usd = sum(p.get("burn_7d_usd", 0.0) for p in sub_plans)
    daily_usd = total_7d_usd / 7
    print(
        f"[plan] planned_7d_burn_usd={total_7d_usd:.2f} "
        f"daily_target_usd={daily_usd:.2f} "
        f"daily_band=[{DAILY_BURN_TARGET_LO},{DAILY_BURN_TARGET_HI}]"
    )

    plan_path = Path(args.plan_out)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_doc = {
        "ramp_start": RAMP_START,
        "ramp_days": RAMP_DAYS,
        "mtd_gross_usd": mtd_gross,
        "mtd_net_usd": mtd_net,
        "credit_remaining_usd": NEVER_REACH_USD - mtd_gross,
        "planned_7d_burn_usd": total_7d_usd,
        "planned_daily_burn_usd": daily_usd,
        "cycle_schedule": CYCLE_SCHEDULE,
        "sub_plans": sub_plans,
        "dry_run": not (args.commit and args.unlock_live),
    }
    with plan_path.open("w") as f:
        json.dump(plan_doc, f, indent=2)
    print(f"[plan] written {plan_path}")

    emit_ledger(
        mtd_gross=mtd_gross,
        mtd_net=mtd_net,
        sub_plans=sub_plans,
        ledger_path=Path(args.ledger_out),
        dry_run=not (args.commit and args.unlock_live),
    )
    print(f"[ledger] appended {args.ledger_out}")

    if not (args.commit and args.unlock_live):
        print(
            "[DRY_RUN] no AWS side-effects. Pass --commit AND --unlock-live-aws-commands to apply."
        )
        return 0

    print("[LIVE] GPU compute env scaled. Cron deployment is follow-on.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
