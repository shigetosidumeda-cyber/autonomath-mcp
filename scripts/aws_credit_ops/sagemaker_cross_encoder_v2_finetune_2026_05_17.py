#!/usr/bin/env python3
"""Lane M6 v2 — Submit SageMaker training for jpcite cross-encoder v2.

Thin wrapper around ``sagemaker_cross_encoder_finetune_2026_05_17.py``
that flips ``--version v2`` and pre-applies the v2 hyperparameter
delta:

    - epochs       : 10  (v1 default 5)
    - batch_size   : 32  (unchanged)
    - lr           : 1e-5 (unchanged)
    - max_runtime  : 48h (v1 default 24h)
    - train_uri    : s3://.../cross_encoder_pairs/v2/train.jsonl
    - val_uri      : s3://.../cross_encoder_pairs/v2/val.jsonl
    - output       : s3://.../models/jpcite-cross-encoder-v2/

Pair count target: 385K (v1 285K + AA5 narrative-derived 100K).

Cost
----
- ap-northeast-1 ml.g4dn.12xlarge × 48h × $3.91/h ≈ $187 hard cap.

Pre-condition
-------------
M6 v1 (``jpcite-cross-encoder-finetune-*``, auto-submitted by
``sagemaker_m6_auto_submit_after_m5.py``) must reach a terminal state
AND ``cross_encoder_pairs/v2/{train,val}.jsonl`` must exist on S3
(produced by ``cross_encoder_pair_gen_v2_2026_05_17.py``).

Constraints
-----------
- DRY_RUN default; ``--commit`` to actually create the job.
- ``[lane:solo]``, mypy --strict friendly, NO LLM API.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path
from typing import Final

V1_SUBMIT_SCRIPT: Final[Path] = (
    Path(__file__).parent / "sagemaker_cross_encoder_finetune_2026_05_17.py"
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Submit jpcite cross-encoder v2 fine-tune training job.",
    )
    p.add_argument("--bucket", default="jpcite-credit-993693061769-202605-derived")
    p.add_argument("--region", default="ap-northeast-1")
    p.add_argument("--profile", default="bookyou-recovery")
    p.add_argument(
        "--role-arn",
        default="arn:aws:iam::993693061769:role/jpcite-sagemaker-execution-role",
    )
    p.add_argument(
        "--job-name",
        default=(
            f"jpcite-cross-encoder-v2-finetune-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
        ),
    )
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr", type=float, default=1e-5)
    p.add_argument("--max-runtime", type=int, default=48 * 3600)
    p.add_argument("--instance-type", default="ml.g4dn.12xlarge")
    p.add_argument("--commit", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not V1_SUBMIT_SCRIPT.exists():
        print(f"[FAIL] v1 submit script missing: {V1_SUBMIT_SCRIPT}", file=sys.stderr)
        return 2
    cmd = [
        sys.executable,
        str(V1_SUBMIT_SCRIPT),
        "--version",
        "v2",
        "--bucket",
        args.bucket,
        "--region",
        args.region,
        "--profile",
        args.profile,
        "--role-arn",
        args.role_arn,
        "--job-name",
        args.job_name,
        "--epochs",
        str(args.epochs),
        "--batch-size",
        str(args.batch_size),
        "--lr",
        str(args.lr),
        "--max-runtime",
        str(args.max_runtime),
        "--instance-type",
        args.instance_type,
    ]
    if args.commit and os.environ.get("DRY_RUN", "0") == "0":
        cmd.append("--commit")
    print(f"[wrap] invoking {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
