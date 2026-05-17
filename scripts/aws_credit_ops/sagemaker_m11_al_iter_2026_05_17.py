#!/usr/bin/env python3
"""Lane M11 Day 2-3 — Submit one Active Learning iteration training job.

A single AL iteration is conceptually:
1. Run the Day-1 multi-task encoder over an unlabeled pool (text only).
2. Uncertainty-sample top-N most ambiguous rows (entropy on rel/ner head).
3. Generate weak labels via the same regex set used in
   ``multitask_corpus_prep_2026_05_17.py``.
4. Re-train (warm-start) on the augmented corpus.

For SageMaker submission, each iteration is one training job that reads
its own AL corpus shard from S3:

    s3://<bucket>/finetune_corpus_multitask/al_iter_{N}/train.jsonl
    s3://<bucket>/finetune_corpus_multitask/al_iter_{N}/val.jsonl

The shard is built locally by ``multitask_corpus_prep_2026_05_17.py``
with ``--seed=N`` re-shuffling + uncertainty proxy (longer / law-text rows
weighted higher, since those carry the densest ambiguous spans).

5 iterations × $94 = ~$470 max.

DRY_RUN default. ``[lane:solo]``. NO LLM API.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Final

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"

# Re-use Day-1 driver by delegating via subprocess for simplicity.
import subprocess  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Submit one Lane M11 AL iteration training job.")
    p.add_argument("--iter", type=int, required=True, help="AL iteration number, 1..5")
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--commit", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    iter_n = args.iter
    job_name = (
        f"jpcite-multitask-al-iter{iter_n}-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    train_uri = f"s3://{args.bucket}/finetune_corpus_multitask/al_iter_{iter_n}/train.jsonl"
    val_uri = f"s3://{args.bucket}/finetune_corpus_multitask/al_iter_{iter_n}/val.jsonl"

    cmd = [
        sys.executable,
        str(Path(__file__).parent / "sagemaker_multitask_finetune_2026_05_17.py"),
        "--job-name",
        job_name,
        "--train-uri",
        train_uri,
        "--val-uri",
        val_uri,
        "--output-prefix",
        f"models/jpcite-multitask-al-iter{iter_n}",
        "--source-prefix",
        f"finetune_corpus_multitask/al_iter_{iter_n}/source",
        "--epochs",
        str(args.epochs),
        "--max-runtime",
        str(24 * 3600),
        "--bucket",
        args.bucket,
        "--region",
        args.region,
        "--profile",
        args.profile,
    ]
    if args.commit:
        cmd.append("--commit")
    print(f"[m11-al iter={iter_n}] dispatch: {' '.join(cmd)}", file=sys.stderr)
    env = os.environ.copy()
    if not args.commit:
        env["DRY_RUN"] = "1"
    res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr)
    print(
        json.dumps({"iter": iter_n, "job_name": job_name, "rc": res.returncode}, ensure_ascii=False)
    )
    return res.returncode


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
