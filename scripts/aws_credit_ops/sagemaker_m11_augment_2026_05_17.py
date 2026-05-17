#!/usr/bin/env python3
"""Lane M11 Day 5 — Submit SageMaker data-augmentation training job.

The augmentation stage uses an open-source seq2seq translator stack
inside the training container — no LLM API. Two corpus expansion paths:

- **Back-translation**: Helsinki-NLP/opus-mt-ja-en + opus-mt-en-ja
  round-trip generates paraphrased Japanese sentences.
- **Synonym/morph perturbation**: light Japanese-side rule (fugashi
  particle / okurigana variant swap) — already embedded in the
  ``multitask_train_entry.py`` data path when ``augment=1`` is set.

For Day 5 we dispatch an additional fine-tune training job over the
*augmented* train.jsonl shard at
``s3://<bucket>/finetune_corpus_multitask/augmented/train.jsonl``
(produced by an upcoming local prep step; if not present the job falls
through to the Day-1 train.jsonl harmlessly).

24h × $3.91/h ≈ $94 hard cap.

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
    p = argparse.ArgumentParser(description="Submit Lane M11 augmented-corpus training job.")
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--commit", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    job_name = f"jpcite-multitask-augment-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
    train_uri = f"s3://{args.bucket}/finetune_corpus_multitask/augmented/train.jsonl"
    val_uri = f"s3://{args.bucket}/finetune_corpus_multitask/augmented/val.jsonl"
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
        "models/jpcite-multitask-augmented",
        "--source-prefix",
        "finetune_corpus_multitask/augmented/source",
        "--epochs",
        "2",
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
    env = os.environ.copy()
    if not args.commit:
        env["DRY_RUN"] = "1"
    res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr)
    print(
        json.dumps(
            {"stage": "augment", "job_name": job_name, "rc": res.returncode}, ensure_ascii=False
        )
    )
    return res.returncode


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
