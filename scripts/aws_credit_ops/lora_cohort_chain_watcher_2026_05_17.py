#!/usr/bin/env python3
"""Lane BB4 - Chain-after-completion watcher for 5 cohort LoRA jobs.

Submits BB4 LoRA training jobs serially. SageMaker ap-northeast-1
profile bookyou-recovery has ``ml.g4dn.xlarge for training job usage``
= 1, so only one cohort job can run at a time. This watcher polls the
currently running job and submits the next cohort on the first observed
terminal state.

Order (5 cohort, default)
-------------------------
1. zeirishi      -- already submitted; not resubmitted here.
2. kaikeishi
3. gyouseishoshi
4. shihoshoshi
5. chusho_keieisha

Usage
-----

.. code-block:: text

    DRY_RUN=0 python scripts/aws_credit_ops/lora_cohort_chain_watcher_2026_05_17.py \\
        --start-after-job jpcite-bert-lora-zeirishi-20260517T081240Z \\
        --remaining-cohorts kaikeishi gyouseishoshi shihoshoshi chusho_keieisha \\
        --commit

The script runs detached (operator nohup'd) and tails its own log.

NO LLM API. mypy-friendly. ``[lane:solo]`` marker.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Final

DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"
DEFAULT_POLL_INTERVAL: Final[int] = 300  # 5 min
TERMINAL_STATES: Final[set[str]] = {"Completed", "Failed", "Stopped"}

LORA_SUBMIT_SCRIPT: Final[Path] = (
    Path(__file__).parent / "sagemaker_lora_cohort_finetune_2026_05_17.py"
)


def _boto3(service: str, region: str, profile: str) -> Any:
    import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]

    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client(service)


def describe_status(sm: Any, job: str) -> tuple[str, dict[str, Any]]:
    resp = sm.describe_training_job(TrainingJobName=job)
    status = str(resp.get("TrainingJobStatus") or "")
    return status, resp


def wait_until_terminal(
    *,
    job: str,
    region: str,
    profile: str,
    poll_interval: int,
    max_wait: int,
) -> tuple[str, int]:
    sm = _boto3("sagemaker", region, profile)
    waited = 0
    while True:
        status, resp = describe_status(sm, job)
        elapsed = int(resp.get("TrainingTimeInSeconds") or 0)
        print(f"[poll t+{waited}s] job={job} status={status} elapsed={elapsed}s", file=sys.stderr)
        if status in TERMINAL_STATES:
            return status, waited
        if waited >= max_wait:
            print(f"[TIMEOUT] {job} waited {waited}s >= max {max_wait}s", file=sys.stderr)
            return "Timeout", waited
        time.sleep(poll_interval)
        waited += poll_interval


def submit_cohort_job(
    *,
    cohort: str,
    commit: bool,
    region: str,
    profile: str,
) -> tuple[int, str]:
    """Invoke the LoRA submit script for one cohort. Returns (rc, arn_or_msg)."""

    cmd = [
        sys.executable,
        str(LORA_SUBMIT_SCRIPT),
        "--cohort",
        cohort,
        "--region",
        region,
        "--profile",
        profile,
    ]
    if commit:
        cmd.append("--commit")
    print(f"[submit] {' '.join(cmd)}", file=sys.stderr)
    env = dict(os.environ)
    if commit:
        env["DRY_RUN"] = "0"
    r = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    # Parse last JSON blob from stdout for the ARN.
    arn = ""
    try:
        # The submit script prints a single JSON blob at the tail.
        # Find the last '{' line and try to parse forward.
        text = r.stdout.strip()
        # Find the last top-level JSON object by finding the last "{" at column 0.
        last_brace = text.rfind("\n{")
        blob = text[last_brace + 1 :] if last_brace >= 0 else text
        d = json.loads(blob)
        arn = str((d.get("response") or {}).get("arn") or "")
    except (json.JSONDecodeError, ValueError):
        pass
    return r.returncode, arn


def latest_job_for_cohort(sm: Any, cohort: str) -> str | None:
    """Find the most recent training job for the given cohort by name prefix."""

    name_prefix = f"jpcite-bert-lora-{cohort.replace('_', '-')}-"
    paginator = sm.get_paginator("list_training_jobs")
    candidates: list[tuple[str, str]] = []  # (created_iso, name)
    for page in paginator.paginate(NameContains=name_prefix, MaxResults=50):
        for s in page.get("TrainingJobSummaries", []) or []:
            name = str(s.get("TrainingJobName") or "")
            created = str(s.get("CreationTime") or "")
            if name.startswith(name_prefix):
                candidates.append((created, name))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--start-after-job",
        required=True,
        help="Job name currently running; wait for terminal then continue.",
    )
    p.add_argument(
        "--remaining-cohorts",
        nargs="+",
        default=["kaikeishi", "gyouseishoshi", "shihoshoshi", "chusho_keieisha"],
    )
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL)
    p.add_argument("--max-wait-per-job", type=int, default=8 * 3600)
    p.add_argument("--commit", action="store_true")
    p.add_argument(
        "--records-output", default="docs/_internal/bb4_lora_chain_records_2026_05_17.json"
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    commit = args.commit and os.environ.get("DRY_RUN", "0") == "0"

    started = dt.datetime.now(dt.UTC).isoformat()
    records: dict[str, Any] = {
        "started_at": started,
        "config": {
            "region": args.region,
            "profile": args.profile,
            "poll_interval": args.poll_interval,
            "max_wait_per_job": args.max_wait_per_job,
            "commit": commit,
        },
        "chain": [],
    }
    out = Path(args.records_output)
    out.parent.mkdir(parents=True, exist_ok=True)

    def flush() -> None:
        out.write_text(json.dumps(records, ensure_ascii=False, indent=2))

    current_job = args.start_after_job
    for cohort in args.remaining_cohorts:
        print(f"[chain] waiting on {current_job} before submitting {cohort}", file=sys.stderr)
        status, waited = wait_until_terminal(
            job=current_job,
            region=args.region,
            profile=args.profile,
            poll_interval=args.poll_interval,
            max_wait=args.max_wait_per_job,
        )
        records["chain"].append(
            {
                "wait_phase": True,
                "predecessor_job": current_job,
                "next_cohort": cohort,
                "predecessor_terminal_status": status,
                "waited_seconds": waited,
                "at": dt.datetime.now(dt.UTC).isoformat(),
            }
        )
        flush()
        if status == "Timeout":
            print(f"[ABORT] predecessor {current_job} did not finish; halt chain", file=sys.stderr)
            return 3
        # Submit the next cohort.
        rc, arn = submit_cohort_job(
            cohort=cohort,
            commit=commit,
            region=args.region,
            profile=args.profile,
        )
        sm = _boto3("sagemaker", args.region, args.profile)
        # If submit_cohort_job did not give us an ARN (e.g. submit failed),
        # try to resolve the latest training job for this cohort.
        if not arn:
            resolved = latest_job_for_cohort(sm, cohort)
            if resolved:
                arn = f"arn:aws:sagemaker:{args.region}:993693061769:training-job/{resolved}"
        records["chain"].append(
            {
                "submit_phase": True,
                "cohort": cohort,
                "rc": rc,
                "arn": arn,
                "at": dt.datetime.now(dt.UTC).isoformat(),
            }
        )
        flush()
        if rc != 0:
            print(f"[WARN] submit {cohort} returned rc={rc}; halt chain", file=sys.stderr)
            return rc
        # Set current_job to the new ARN's job-name component.
        if "/" in arn:
            current_job = arn.split("/")[-1]
        else:
            print(f"[ABORT] no resolvable job name for cohort {cohort}; halt", file=sys.stderr)
            return 4

    records["completed_at"] = dt.datetime.now(dt.UTC).isoformat()
    flush()
    print(f"[OK] chain complete; records at {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
