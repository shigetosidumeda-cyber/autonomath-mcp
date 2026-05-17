#!/usr/bin/env python3
"""Lane H — CodeBuild burst for AWS credit burn.

Triggers a paced sequence of CodeBuild builds against the existing
``jpcite-crawler-build`` project. Each build is a real Docker rebuild +
ECR push so the output is genuine (not throwaway). Burn rate is
controlled by compute-type override and inter-launch spacing.

Constraints honoured
--------------------
- $19,490 Never-Reach hard cap (see memory ``feedback_aws_canary_hard_stop_5_line_defense``).
- No live re-enable of Phase 9 EventBridge; this script touches only
  CodeBuild + its source repo.
- Build counter + DRY_RUN default + ``--commit`` flag mirroring the
  teardown script pattern.
- Slight env-var variation per build so each run is distinct in CW logs.

Pricing (ap-northeast-1, 2026-05 published):
  BUILD_GENERAL1_SMALL  $0.005 / min   (3 vCPU)
  BUILD_GENERAL1_MEDIUM $0.010 / min   (7 vCPU)
  BUILD_GENERAL1_LARGE  $0.020 / min  (15 vCPU)

Observed phase durations on jpcite-crawler-build (BUILD_GENERAL1_SMALL):
  total ~130 sec ≈ 2.17 min → $0.011 / build at SMALL,
                              $0.043 / build at LARGE.

Target = $50/day at LARGE compute → ~1,160 builds/day = 48 / hour.
With concurrency cap 300 + ECR throttle, sustainable rate is 30-60 / hour.

Usage
-----
    # Dry-run (default — prints plan without launching):
    python scripts/aws_credit_ops/codebuild_burst_2026_05_17.py \\
        --total-builds 100 --compute-type BUILD_GENERAL1_LARGE

    # Commit (actually launch):
    python scripts/aws_credit_ops/codebuild_burst_2026_05_17.py \\
        --total-builds 100 --compute-type BUILD_GENERAL1_LARGE --commit

The script staggers launches with ``--interval-sec`` to avoid ECR
push throttle (default 30 sec spacing).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time

PROJECT_NAME = "jpcite-crawler-build"
PROFILE = "bookyou-recovery"
REGION = "ap-northeast-1"
# $/min by compute type (ap-northeast-1, on-demand). Update if AWS bumps prices.
COMPUTE_RATE_USD_PER_MIN = {
    "BUILD_GENERAL1_SMALL": 0.005,
    "BUILD_GENERAL1_MEDIUM": 0.010,
    "BUILD_GENERAL1_LARGE": 0.020,
}
DEFAULT_BUILD_MIN = 2.17  # observed median across recent builds


def start_build(
    build_idx: int,
    total: int,
    compute_type: str,
    dry_run: bool,
) -> dict:
    """Launch one CodeBuild and return the build ID + metadata."""
    env_overrides = [
        {"name": "JPCITE_BURST_INDEX", "value": str(build_idx), "type": "PLAINTEXT"},
        {"name": "JPCITE_BURST_TOTAL", "value": str(total), "type": "PLAINTEXT"},
        {"name": "JPCITE_BURST_LANE", "value": "H_codebuild_burst", "type": "PLAINTEXT"},
        {
            "name": "JPCITE_BURST_LAUNCHED_AT",
            "value": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "type": "PLAINTEXT",
        },
    ]
    if dry_run:
        return {
            "buildId": f"DRYRUN-{build_idx:04d}",
            "computeType": compute_type,
            "env": env_overrides,
        }
    cmd = [
        "aws",
        "codebuild",
        "start-build",
        "--project-name",
        PROJECT_NAME,
        "--environment-variables-override",
        json.dumps(env_overrides),
        "--compute-type-override",
        compute_type,
        "--profile",
        PROFILE,
        "--region",
        REGION,
        "--output",
        "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"start-build failed for idx={build_idx}: rc={proc.returncode}\nstderr={proc.stderr}"
        )
    data = json.loads(proc.stdout)
    bid = data["build"]["id"]
    return {
        "buildId": bid,
        "computeType": compute_type,
        "arn": data["build"]["arn"],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--total-builds",
        type=int,
        default=100,
        help="total builds to launch in this run (default 100)",
    )
    p.add_argument(
        "--compute-type",
        choices=list(COMPUTE_RATE_USD_PER_MIN.keys()),
        default="BUILD_GENERAL1_LARGE",
        help="CodeBuild compute type override",
    )
    p.add_argument(
        "--interval-sec",
        type=float,
        default=30.0,
        help="seconds between launches (ECR push throttle guard)",
    )
    p.add_argument(
        "--commit",
        action="store_true",
        help="actually launch builds (default is dry-run print-only)",
    )
    p.add_argument(
        "--ledger",
        type=str,
        default="docs/_internal/codebuild_burst_ledger_2026_05_17.json",
        help="where to write the launched-build ledger",
    )
    args = p.parse_args()

    dry_run = not args.commit
    rate = COMPUTE_RATE_USD_PER_MIN[args.compute_type]
    est_per_build = rate * DEFAULT_BUILD_MIN
    est_total = est_per_build * args.total_builds

    print("=== Lane H CodeBuild burst plan ===")
    print(f"  project          = {PROJECT_NAME}")
    print(f"  region           = {REGION}")
    print(f"  total builds     = {args.total_builds}")
    print(f"  compute type     = {args.compute_type}")
    print(f"  $/min            = ${rate:.4f}")
    print(f"  median min/build = {DEFAULT_BUILD_MIN:.2f}")
    print(f"  est $/build      = ${est_per_build:.4f}")
    print(f"  est total cost   = ${est_total:.2f}")
    print(f"  launch interval  = {args.interval_sec}s")
    print(f"  total walltime   = {args.interval_sec * args.total_builds / 60:.1f} min")
    print(f"  mode             = {'WET (--commit)' if args.commit else 'DRY-RUN (default)'}")
    print()

    launched: list[dict] = []
    started_at = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"

    for idx in range(1, args.total_builds + 1):
        try:
            rec = start_build(
                build_idx=idx,
                total=args.total_builds,
                compute_type=args.compute_type,
                dry_run=dry_run,
            )
        except Exception as e:
            print(f"[{idx:4d}/{args.total_builds}] FAILED: {e}", file=sys.stderr)
            launched.append({"idx": idx, "error": str(e)})
            continue
        launched.append({"idx": idx, **rec})
        print(f"[{idx:4d}/{args.total_builds}] {rec['buildId']}")
        if idx < args.total_builds:
            time.sleep(args.interval_sec)

    finished_at = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    ledger = {
        "lane": "H_codebuild_burst_2026_05_17",
        "project": PROJECT_NAME,
        "region": REGION,
        "compute_type": args.compute_type,
        "total_builds_planned": args.total_builds,
        "total_builds_launched": sum(
            1 for r in launched if "buildId" in r and not r["buildId"].startswith("DRYRUN-")
        ),
        "total_dry_run": sum(1 for r in launched if r.get("buildId", "").startswith("DRYRUN-")),
        "interval_sec": args.interval_sec,
        "est_cost_per_build_usd": est_per_build,
        "est_total_cost_usd": est_total,
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "dry_run": dry_run,
        "builds": launched,
    }
    out_path = os.path.abspath(args.ledger)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(ledger, f, indent=2)
    print()
    print(f"ledger -> {out_path}")
    print(
        f"summary: launched={ledger['total_builds_launched']} "
        f"dry_run={ledger['total_dry_run']} est_cost=${est_total:.2f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
