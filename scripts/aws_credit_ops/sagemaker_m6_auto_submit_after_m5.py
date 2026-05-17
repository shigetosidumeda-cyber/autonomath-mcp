#!/usr/bin/env python3
"""Lane M6 — auto-submit cross-encoder training after M5 SimCSE completes.

Background
----------
SageMaker quota ``ml.g4dn.12xlarge for training job usage`` = 1 in
ap-northeast-1 on profile ``bookyou-recovery`` (verified
2026-05-17). The M5 SimCSE training job
``jpcite-bert-simcse-finetune-20260517T022501Z`` holds that single
slot and has MaxRuntimeInSeconds=43200 (12h). Submitting M6 while M5
is InProgress would fail synchronously with
``ResourceLimitExceeded``.

This driver polls M5's status every ``--poll-interval`` seconds and
invokes the M6 submit script with ``--commit`` only after M5 reaches
``Completed``.

Behaviour
---------
* On ``Completed`` — submit M6 (the M6 train pairs are already on
  S3 from ``cross_encoder_pair_gen_2026_05_17.py``).
* On ``Failed`` / ``Stopped`` — abort without submitting M6 so the
  operator can inspect the failed upstream lane first.
* On ``InProgress`` — sleep poll_interval and re-check.

Cost preflight + hard-stop are inherited from the wrapped submit
script. NO LLM API anywhere.

CLI
---

.. code-block:: text

    python scripts/aws_credit_ops/sagemaker_m6_auto_submit_after_m5.py \\
        --m5-job jpcite-bert-simcse-finetune-20260517T022501Z \\
        --poll-interval 300 \\
        [--commit]

The default is DRY_RUN (no actual submit) so the wait loop can be
exercised safely. Pass ``--commit`` to flip both this driver AND
the wrapped M6 submit script into live mode.
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
DEFAULT_M5_JOB: Final[str] = "jpcite-bert-simcse-finetune-20260517T022501Z"
DEFAULT_POLL_INTERVAL: Final[int] = 300  # 5 min
TERMINAL_STATES: Final[set[str]] = {"Completed", "Failed", "Stopped"}

M6_SUBMIT_SCRIPT: Final[Path] = (
    Path(__file__).parent / "sagemaker_cross_encoder_finetune_2026_05_17.py"
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
    *, m5_job: str, region: str, profile: str, poll_interval: int, max_wait: int
) -> tuple[str, int]:
    """Poll until M5 reaches a terminal state. Returns (status, waited_sec)."""

    sm = _boto3("sagemaker", region, profile)
    waited = 0
    while True:
        status, resp = describe_status(sm, m5_job)
        elapsed = int(resp.get("TrainingTimeInSeconds") or 0)
        print(
            f"[poll t+{waited}s] m5_status={status} m5_elapsed={elapsed}s",
            file=sys.stderr,
        )
        if status in TERMINAL_STATES:
            return status, waited
        if waited >= max_wait:
            print(
                f"[TIMEOUT] waited {waited}s >= max_wait {max_wait}s, aborting",
                file=sys.stderr,
            )
            return "Timeout", waited
        time.sleep(poll_interval)
        waited += poll_interval


def submit_m6(*, commit: bool, region: str, profile: str) -> int:
    """Invoke the M6 submit script."""

    cmd = [
        sys.executable,
        str(M6_SUBMIT_SCRIPT),
        "--region",
        region,
        "--profile",
        profile,
    ]
    if commit:
        cmd.append("--commit")
    print(f"[submit] {' '.join(cmd)}", file=sys.stderr)
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--m5-job", default=DEFAULT_M5_JOB)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL)
    p.add_argument(
        "--max-wait",
        type=int,
        default=14 * 3600,  # 14h ceiling (M5 has 12h MaxRuntime).
    )
    p.add_argument("--commit", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    commit = args.commit and os.environ.get("DRY_RUN", "0") == "0"

    started = dt.datetime.now(dt.UTC).isoformat()
    print(f"[start] auto-submit watcher at {started}", file=sys.stderr)
    print(
        f"[config] m5_job={args.m5_job} poll={args.poll_interval}s "
        f"max_wait={args.max_wait}s commit={commit}",
        file=sys.stderr,
    )

    status, waited = wait_until_terminal(
        m5_job=args.m5_job,
        region=args.region,
        profile=args.profile,
        poll_interval=args.poll_interval,
        max_wait=args.max_wait,
    )
    print(
        json.dumps(
            {
                "phase": "wait_done",
                "m5_status": status,
                "waited_seconds": waited,
                "next": "submit_m6" if status == "Completed" else "abort",
            }
        )
    )
    if status == "Timeout":
        return 3
    if status != "Completed":
        print(
            json.dumps(
                {
                    "phase": "abort",
                    "m5_terminal_status": status,
                    "reason": "M5 did not complete; refusing to submit M6",
                }
            )
        )
        return 2
    rc = submit_m6(commit=commit, region=args.region, profile=args.profile)
    print(
        json.dumps(
            {
                "phase": "submit_done",
                "rc": rc,
                "m5_terminal_status": status,
                "commit": commit,
            }
        )
    )
    return rc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
