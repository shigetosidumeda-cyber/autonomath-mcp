#!/usr/bin/env python3
"""Lane M11 BB3 — Chain dispatcher for the 20-iter AL / Distill / Augment + distill v2 cycle.

BB3 (2026-05-17) variant of ``sagemaker_m11_chain_dispatch_2026_05_17.py``.
The original dispatcher is hard-wired to a 5-iter AL window then
distill + augment. BB3 expands the AL loop to **20 iters** for deeper
uncertainty-sampled fine-tune coverage and appends a second distillation
stage (``distill_v2``) using the iter-20 teacher.

Per-iter cost cap: ~$16 on g4dn.12xlarge (4 h × $3.91/h)
Incremental BB3 burn vs the 5-iter chain: 15 iters × $16 = $240 plus
distill v2 (~$47) = **~$287** — comfortably inside the Never-Reach
$19,490 envelope.

Sequence (each row fires only after the prior one ends Completed.
Failed / Stopped prior jobs halt the chain; ``--start-iter`` lets you
resume from a partially-burned chain after the failure is fixed):

    1..N. al_iter_{S..N}    (S = ``--start-iter``, N = ``--max-iter``)
    N+1.  distill            (after final AL iter)
    N+2.  augment            (after distill)
    N+3.  distill_v2         (only when ``--distill-v2``; teacher = iter N)

For BB3 expand cycle:

    python scripts/aws_credit_ops/sagemaker_m11_chain_dispatch_bb3_2026_05_17.py \\
        --first-job jpcite-multitask-large-20260517T040000Z \\
        --start-iter 1 \\
        --max-iter 20 \\
        --distill-v2 \\
        --commit \\
        --ledger docs/_internal/sagemaker_m11_chain_records_bb3_2026_05_17.json

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
DEFAULT_MAX_ITER: Final[int] = 20
DEFAULT_START_ITER: Final[int] = 1


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
    """Fire one stage and return the resulting job name.

    ``distill_v2`` re-uses the same distill submitter (the teacher prefix
    is implicit via ``models/jpcite-multitask-al-iter{N}/...``). The v2
    label only affects the chain ledger so the history stays traceable.
    """
    script_map = {
        "al": "sagemaker_m11_al_iter_2026_05_17.py",
        "distill": "sagemaker_m11_distill_2026_05_17.py",
        "distill_v2": "sagemaker_m11_distill_2026_05_17.py",
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
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("{") and "job_name" in line:
            try:
                obj = json.loads(line)
                return str(obj.get("job_name", ""))
            except json.JSONDecodeError:
                continue
    return ""


def _write_ledger(path: str, ledger: list[dict[str, Any]]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lane M11 BB3 sequential chain dispatcher.")
    p.add_argument(
        "--first-job",
        required=True,
        help="Day-1 multi-task (or prior AL iter) job to wait on first.",
    )
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--commit", action="store_true")
    p.add_argument(
        "--max-iter",
        type=int,
        default=DEFAULT_MAX_ITER,
        help="Number of AL iterations (default 20 for BB3 expand).",
    )
    p.add_argument(
        "--start-iter",
        type=int,
        default=DEFAULT_START_ITER,
        help="First AL iter to fire (default 1). Use >1 to resume a broken chain.",
    )
    p.add_argument(
        "--distill-v2",
        action="store_true",
        help="Append a second distill stage that uses the final AL iter as teacher.",
    )
    p.add_argument(
        "--ledger",
        default=(
            f"docs/_internal/sagemaker_m11_chain_records_bb3_{dt.date.today().isoformat()}.json"
        ),
    )
    return p.parse_args(argv)


def build_chain(start_iter: int, max_iter: int, distill_v2: bool) -> list[tuple[str, int]]:
    """Build the chain plan.

    ``start_iter > max_iter`` is a no-op for the AL section (resume past
    the AL window straight into distill / augment / distill_v2).
    """
    chain: list[tuple[str, int]] = [("al", n) for n in range(start_iter, max_iter + 1)]
    chain.append(("distill", 0))
    chain.append(("augment", 0))
    if distill_v2:
        chain.append(("distill_v2", max_iter))
    return chain


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    chain = build_chain(
        start_iter=args.start_iter,
        max_iter=args.max_iter,
        distill_v2=args.distill_v2,
    )
    print(f"[bb3] plan = {len(chain)} stages", flush=True)
    for i, (stage, n) in enumerate(chain):
        print(f"  {i + 1:3d}. {stage} iter={n}", flush=True)
    ledger: list[dict[str, Any]] = []
    cur_job = args.first_job
    for stage, n in chain:
        status = wait_for_terminal(cur_job, profile=args.profile, region=args.region)
        if status != "Completed":
            ledger.append(
                {
                    "stage": stage,
                    "iter": n,
                    "prior_job": cur_job,
                    "prior_status": status,
                    "new_job": "",
                    "halted": True,
                    "reason": "prior job did not complete; refusing to fire next M11 stage",
                    "fired_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
                }
            )
            _write_ledger(args.ledger, ledger)
            print(
                json.dumps(
                    {
                        "ok": False,
                        "halted": True,
                        "ledger": args.ledger,
                        "prior_job": cur_job,
                        "prior_status": status,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(f"[chain] prior {cur_job} -> {status}; firing {stage} iter={n}", flush=True)
        new_job = fire_one(stage, commit=args.commit, iter_n=n)
        ledger.append(
            {
                "stage": stage,
                "iter": n,
                "prior_job": cur_job,
                "prior_status": status,
                "new_job": new_job,
                "fired_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
            }
        )
        _write_ledger(args.ledger, ledger)
        cur_job = new_job or cur_job
    final_status = wait_for_terminal(cur_job, profile=args.profile, region=args.region)
    ledger.append({"final_job": cur_job, "final_status": final_status})
    _write_ledger(args.ledger, ledger)
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
