#!/usr/bin/env python3
"""Lane M11 — Chain dispatcher for the 7-job AL/Distill/Augment sequence.

Polls the previous SageMaker training job until it terminates, then
fires the next one. Designed to be left running for ~5 days as the
training plane sequentially burns through each stage with a stable
single-instance GPU quota footprint.

Sequence (each row fires only after the prior one ends Completed/Failed):

    1. al_iter_1   (Day 2)
    2. al_iter_2
    3. al_iter_3
    4. al_iter_4
    5. al_iter_5   (Day 3 end)
    6. distill     (Day 4)
    7. augment     (Day 5)

DRY_RUN default. ``--commit`` to actually fire jobs. ``[lane:solo]``.
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

DEFAULT_PROFILE: Final[str] = "bookyou-recovery"
DEFAULT_REGION: Final[str] = "ap-northeast-1"


def _boto3(service: str, profile: str, region: str) -> Any:
    import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]

    return boto3.Session(profile_name=profile, region_name=region).client(service)


def wait_for_terminal(job_name: str, *, profile: str, region: str, poll_sec: int = 120) -> str:
    sm = _boto3("sagemaker", profile, region)
    while True:
        resp = sm.describe_training_job(TrainingJobName=job_name)
        status = resp["TrainingJobStatus"]
        sec = resp.get("SecondaryStatus", "")
        print(f"[wait] {job_name} status={status} secondary={sec}", flush=True)
        if status in {"Completed", "Failed", "Stopped"}:
            return str(status)
        time.sleep(poll_sec)


def fire_one(stage: str, *, commit: bool, iter_n: int = 0) -> str:
    """Fire one stage and return the resulting job name."""
    script_map = {
        "al": "sagemaker_m11_al_iter_2026_05_17.py",
        "distill": "sagemaker_m11_distill_2026_05_17.py",
        "augment": "sagemaker_m11_augment_2026_05_17.py",
    }
    if stage not in script_map:
        raise ValueError(f"unknown stage {stage}")
    script = Path(__file__).parent / script_map[stage]
    cmd = [sys.executable, str(script)]
    if stage == "al":
        cmd += ["--iter", str(iter_n)]
    if commit:
        cmd += ["--commit"]
    env = os.environ.copy()
    if not commit:
        env["DRY_RUN"] = "1"
    res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    print(res.stdout, flush=True)
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr, flush=True)
    # Extract job name from stdout (the dispatcher prints
    # ``{"iter":..., "job_name":"...", "rc":0}`` or ``{"stage":..., "job_name":...}``).
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("{") and "job_name" in line:
            try:
                obj = json.loads(line)
                return str(obj.get("job_name", ""))
            except json.JSONDecodeError:
                continue
    return ""


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lane M11 sequential chain dispatcher.")
    p.add_argument("--first-job", required=True, help="Day-1 multi-task job to wait on first.")
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--commit", action="store_true")
    p.add_argument(
        "--ledger",
        default=f"docs/_internal/sagemaker_m11_chain_records_{dt.date.today().isoformat()}.json",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    chain: list[tuple[str, int]] = [
        ("al", 1),
        ("al", 2),
        ("al", 3),
        ("al", 4),
        ("al", 5),
        ("distill", 0),
        ("augment", 0),
    ]
    ledger: list[dict[str, Any]] = []
    cur_job = args.first_job
    for stage, n in chain:
        status = wait_for_terminal(cur_job, profile=args.profile, region=args.region)
        print(f"[chain] prior {cur_job} -> {status}; firing {stage} iter={n}", flush=True)
        new_job = fire_one(stage, commit=args.commit, iter_n=n)
        ledger.append(
            {
                "stage": stage,
                "iter": n,
                "prior_job": cur_job,
                "prior_status": status,
                "new_job": new_job,
                "fired_at": dt.datetime.utcnow().isoformat() + "Z",
            }
        )
        Path(args.ledger).parent.mkdir(parents=True, exist_ok=True)
        Path(args.ledger).write_text(
            json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        cur_job = new_job or cur_job
    final_status = wait_for_terminal(cur_job, profile=args.profile, region=args.region)
    ledger.append({"final_job": cur_job, "final_status": final_status})
    Path(args.ledger).write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"ok": True, "ledger": args.ledger, "final_status": final_status},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
