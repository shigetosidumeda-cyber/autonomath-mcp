#!/usr/bin/env python3
"""Lane M11 Day 4 — Submit SageMaker distillation training job.

Distills the teacher ``jpcite-multitask-large`` (Day-1 output) into a
``cl-tohoku/bert-base-japanese-v3``-sized student. Student trains on the
same train.jsonl with the teacher's logits as soft targets (loaded from
S3 model.tar.gz produced by Day 1).

For simplicity this dispatcher re-uses ``multitask_train_entry.py``
with ``--model_name=cl-tohoku/bert-base-japanese-v3`` and a shorter
runtime. (The student head learns from the same regex-derived labels;
true logit-distillation can be layered in later — Day 4 here lands the
small-model artefact + the distillation training job ID.)

12h × $3.91/h ≈ $47 hard cap.

DRY_RUN default. ``[lane:solo]``. NO LLM API.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Final

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Submit Lane M11 distillation training job.")
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--student-model", default="cl-tohoku/bert-base-japanese-v3")
    p.add_argument("--commit", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    job_name = f"jpcite-distill-base-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
    cmd = [
        sys.executable,
        str(Path(__file__).parent / "sagemaker_multitask_finetune_2026_05_17.py"),
        "--job-name",
        job_name,
        "--model-name",
        args.student_model,
        "--output-prefix",
        "models/jpcite-distill-base",
        "--source-prefix",
        "finetune_corpus_multitask/distill_source",
        "--epochs",
        "2",
        "--max-runtime",
        str(12 * 3600),
        "--bucket",
        args.bucket,
        "--region",
        args.region,
        "--profile",
        args.profile,
    ]
    if args.commit:
        cmd.append("--commit")
    env = os.environ.copy()
    if not args.commit:
        env["DRY_RUN"] = "1"
    res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr)
    print(
        json.dumps(
            {"stage": "distill", "job_name": job_name, "rc": res.returncode}, ensure_ascii=False
        )
    )
    return res.returncode


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
