#!/usr/bin/env python3
"""Lane M5 v2 — Submit SageMaker training for jpcite SimCSE BERT v2.

v2 vs v1 deltas
---------------
- Training corpus  : ``finetune_corpus_v2/`` (v1 + AA1/AA2 supplemental).
- Output prefix    : ``models/jpcite-bert-v2/``.
- Epochs           : 5 (v1: 3)  → 1.67x update steps.
- LR               : 1e-5 (v1: 3e-5)  → finer fine-tune over richer corpus.
- Batch size       : 64 (unchanged).
- Instance         : ml.g4dn.12xlarge × 1 (unchanged, single quota).
- MaxRuntime       : 18h (v1: 12h)  → covers 1.67x epochs * 1.05x corpus.

Cost
----
- ap-northeast-1 ml.g4dn.12xlarge ≈ $3.91/h  →  18h ≈ $70 hard cap.
- $19,490 Never-Reach guard inherited via ``HARD_STOP_USD = 18000``.
- NO LLM API anywhere — encoder fine-tune only.

Pre-condition
-------------
M5 v1 (``jpcite-bert-simcse-finetune-20260517T022501Z``) must reach a
terminal state. That contract is enforced by
``sagemaker_m6_auto_submit_after_m5.py`` for the M6 v1 hand-off; this
v2 driver expects the operator (or v2 watcher) to invoke it manually
after the v1 cascade settles.

Constraints
-----------
- DRY_RUN default; ``--commit`` to actually create the job.
- ``[lane:solo]`` marker.
- mypy --strict friendly.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import sys
import tarfile
from pathlib import Path
from typing import Any, Final

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"
DEFAULT_ROLE_ARN: Final[str] = "arn:aws:iam::993693061769:role/jpcite-sagemaker-execution-role"
HARD_STOP_USD: Final[float] = 18000.0

#: ap-northeast-1 HuggingFace PyTorch GPU training image
#: (2.1.0 / 4.36.0 / py310 / cu121). Verified in v1 driver.
TRAINING_IMAGE: Final[str] = (
    "763104351884.dkr.ecr.ap-northeast-1.amazonaws.com/"
    "huggingface-pytorch-training:2.1.0-transformers4.36.0-gpu-py310-cu121-ubuntu20.04"
)


def _boto3(service: str, region: str, profile: str) -> Any:
    import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]

    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client(service)


def preflight_cost(region: str, profile: str) -> float:
    ce = _boto3("ce", "us-east-1", profile)
    today = dt.date.today()
    start = today.replace(day=1).isoformat()
    tomorrow = (today + dt.timedelta(days=1)).isoformat()
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": tomorrow},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )
    amt = float(resp["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"])
    if amt >= HARD_STOP_USD:
        print(
            f"[HARD-STOP] mtd_usd={amt:.2f} >= {HARD_STOP_USD}, aborting",
            file=sys.stderr,
        )
        sys.exit(2)
    return amt


def _build_source_tar(entry_file: Path, requirements: Path | None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(str(entry_file), arcname=entry_file.name)
        if requirements is not None and requirements.exists():
            tar.add(str(requirements), arcname="requirements.txt")
    return buf.getvalue()


def upload_source_tar(s3: Any, *, bucket: str, key: str, body: bytes) -> str:
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/x-tar")
    return f"s3://{bucket}/{key}"


def submit(
    *,
    job_name: str,
    bucket: str,
    role_arn: str,
    region: str,
    profile: str,
    train_uri: str,
    val_uri: str,
    output_prefix: str,
    source_uri: str,
    epochs: int,
    batch_size: int,
    lr: float,
    max_runtime: int,
    instance_type: str,
    dry_run: bool,
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "TrainingJobName": job_name,
        "AlgorithmSpecification": {
            "TrainingImage": TRAINING_IMAGE,
            "TrainingInputMode": "File",
        },
        "RoleArn": role_arn,
        "InputDataConfig": [
            {
                "ChannelName": "train",
                "DataSource": {
                    "S3DataSource": {
                        "S3DataType": "S3Prefix",
                        "S3Uri": train_uri,
                        "S3DataDistributionType": "FullyReplicated",
                    }
                },
                "ContentType": "application/jsonlines",
                "CompressionType": "None",
            },
            {
                "ChannelName": "val",
                "DataSource": {
                    "S3DataSource": {
                        "S3DataType": "S3Prefix",
                        "S3Uri": val_uri,
                        "S3DataDistributionType": "FullyReplicated",
                    }
                },
                "ContentType": "application/jsonlines",
                "CompressionType": "None",
            },
        ],
        "OutputDataConfig": {"S3OutputPath": f"s3://{bucket}/{output_prefix}/"},
        "ResourceConfig": {
            "InstanceType": instance_type,
            "InstanceCount": 1,
            "VolumeSizeInGB": 200,
        },
        "StoppingCondition": {"MaxRuntimeInSeconds": max_runtime},
        "HyperParameters": {
            "sagemaker_program": "simcse_train_entry.py",
            "sagemaker_submit_directory": source_uri,
            "sagemaker_container_log_level": "20",
            "sagemaker_region": region,
            "epochs": str(epochs),
            "batch_size": str(batch_size),
            "lr": str(lr),
            "model_name": "cl-tohoku/bert-base-japanese-v3",
            "max_length": "128",
            "temperature": "0.05",
        },
        "EnableManagedSpotTraining": False,
        "Tags": [
            {"Key": "lane", "Value": "solo"},
            {"Key": "wave", "Value": "M5"},
            {"Key": "purpose", "Value": "jpcite-bert-v2-simcse-finetune"},
            {"Key": "version", "Value": "v2"},
        ],
    }
    if dry_run:
        return {"dry_run": True, "spec": spec}
    sm = _boto3("sagemaker", region, profile)
    resp = sm.create_training_job(**spec)
    return {"dry_run": False, "spec": spec, "response": {"arn": resp.get("TrainingJobArn", "")}}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Submit jpcite SimCSE BERT v2 fine-tune training job.")
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--role-arn", default=DEFAULT_ROLE_ARN)
    p.add_argument(
        "--job-name",
        default=(
            f"jpcite-bert-simcse-v2-finetune-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
        ),
    )
    p.add_argument(
        "--train-uri",
        default=f"s3://{DEFAULT_BUCKET}/finetune_corpus_v2/train.jsonl",
    )
    p.add_argument(
        "--val-uri",
        default=f"s3://{DEFAULT_BUCKET}/finetune_corpus_v2/val.jsonl",
    )
    p.add_argument("--output-prefix", default="models/jpcite-bert-v2")
    p.add_argument("--source-prefix", default="finetune_corpus_v2/source")
    p.add_argument(
        "--entry-file",
        default=str(Path(__file__).parent / "simcse_train_entry.py"),
    )
    p.add_argument(
        "--requirements",
        default=str(Path(__file__).parent / "simcse_train_requirements.txt"),
    )
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--lr", type=float, default=1e-5)
    p.add_argument("--max-runtime", type=int, default=18 * 3600)
    p.add_argument("--instance-type", default="ml.g4dn.12xlarge")
    p.add_argument("--commit", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dry_run = not args.commit and os.environ.get("DRY_RUN", "1") != "0"

    mtd = preflight_cost(args.region, args.profile)
    print(f"[preflight] mtd_usd={mtd:.4f} < {HARD_STOP_USD}", file=sys.stderr)

    entry = Path(args.entry_file)
    req = Path(args.requirements) if args.requirements else None
    if not entry.exists():
        print(f"[FAIL] entry file missing: {entry}", file=sys.stderr)
        return 2

    tar_body = _build_source_tar(entry, req)
    source_key = f"{args.source_prefix.rstrip('/')}/sourcedir-{args.job_name}.tar.gz"

    if dry_run:
        source_uri = f"s3://{args.bucket}/{source_key}"
        print(f"[DRY_RUN] would upload source tar ({len(tar_body)} bytes) to {source_uri}")
    else:
        s3 = _boto3("s3", args.region, args.profile)
        source_uri = upload_source_tar(s3, bucket=args.bucket, key=source_key, body=tar_body)
        print(f"[OK] uploaded source tar to {source_uri}")

    result = submit(
        job_name=args.job_name,
        bucket=args.bucket,
        role_arn=args.role_arn,
        region=args.region,
        profile=args.profile,
        train_uri=args.train_uri,
        val_uri=args.val_uri,
        output_prefix=args.output_prefix,
        source_uri=source_uri,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        max_runtime=args.max_runtime,
        instance_type=args.instance_type,
        dry_run=dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
