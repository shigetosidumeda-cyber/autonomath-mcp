#!/usr/bin/env python3
"""Lane M6 v1 — Submit SageMaker training for jpcite cross-encoder.

This file is the **target of the M6 auto-submit watcher**
(``sagemaker_m6_auto_submit_after_m5.py``) and must therefore exist
before M5 v1 reaches a terminal state — otherwise the watcher's
``subprocess.run([sys.executable, str(M6_SUBMIT_SCRIPT), ...])`` raises
``FileNotFoundError`` the moment M5 completes.

What it does
------------
- Tarballs ``cross_encoder_train_entry.py`` (+ requirements) as the
  HuggingFace ``source_dir``.
- Submits a ``create_training_job`` call against the HuggingFace
  PyTorch GPU training image on ml.g4dn.12xlarge × 1.
- Reads ``(query, doc, label)`` triples from
  ``s3://.../cross_encoder_pairs/v1/{train,val}.jsonl``.
- Writes the fine-tuned reranker checkpoint to
  ``s3://.../models/jpcite-cross-encoder-v1/``.

Honest framing on pair count
----------------------------
The M6 brief calls for 285K v1 pairs. The pair generator
(``cross_encoder_pair_gen_2026_05_17.py``) must produce them; this
driver does not synthesize pairs itself. If the train.jsonl object is
absent at submit time, SageMaker will fail the input-channel
validation and the driver surfaces that error verbatim.

Cost
----
- ap-northeast-1 ml.g4dn.12xlarge ≈ $3.91/h × MaxRuntime 24h ≈ $94 hard cap.
- HARD_STOP_USD = 18000 (well under the $19,490 Never-Reach absolute).
- NO LLM API.

Constraints
-----------
- DRY_RUN default; ``--commit`` for actual create.
- ``[lane:solo]``.
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
    version: str,
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
            "sagemaker_program": "cross_encoder_train_entry.py",
            "sagemaker_submit_directory": source_uri,
            "sagemaker_container_log_level": "20",
            "sagemaker_region": region,
            "epochs": str(epochs),
            "batch_size": str(batch_size),
            "lr": str(lr),
            "model_name": "hotchpotch/japanese-reranker-cross-encoder-large-v1",
            "max_length": "256",
        },
        "EnableManagedSpotTraining": False,
        "Tags": [
            {"Key": "lane", "Value": "solo"},
            {"Key": "wave", "Value": "M6"},
            {"Key": "purpose", "Value": f"jpcite-cross-encoder-{version}-finetune"},
            {"Key": "version", "Value": version},
        ],
    }
    if dry_run:
        return {"dry_run": True, "spec": spec}
    sm = _boto3("sagemaker", region, profile)
    resp = sm.create_training_job(**spec)
    return {"dry_run": False, "spec": spec, "response": {"arn": resp.get("TrainingJobArn", "")}}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Submit jpcite cross-encoder fine-tune training job.")
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--role-arn", default=DEFAULT_ROLE_ARN)
    p.add_argument("--version", default="v1", choices=("v1", "v2"))
    p.add_argument(
        "--job-name",
        default=(
            f"jpcite-cross-encoder-finetune-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
        ),
    )
    p.add_argument("--train-uri", default=None)
    p.add_argument("--val-uri", default=None)
    p.add_argument("--output-prefix", default=None)
    p.add_argument("--source-prefix", default=None)
    p.add_argument(
        "--entry-file",
        default=str(Path(__file__).parent / "cross_encoder_train_entry.py"),
    )
    p.add_argument(
        "--requirements",
        default=str(Path(__file__).parent / "simcse_train_requirements.txt"),
    )
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr", type=float, default=1e-5)
    p.add_argument("--max-runtime", type=int, default=24 * 3600)
    p.add_argument("--instance-type", default="ml.g4dn.12xlarge")
    p.add_argument("--commit", action="store_true")
    return p.parse_args(argv)


def _resolve_defaults(args: argparse.Namespace) -> None:
    """Fill train/val/output URIs from --version when not explicitly set."""

    if args.version == "v1":
        train = f"s3://{args.bucket}/cross_encoder_pairs/v1/train.jsonl"
        val = f"s3://{args.bucket}/cross_encoder_pairs/v1/val.jsonl"
        output = "models/jpcite-cross-encoder-v1"
        source = "cross_encoder_pairs/v1/source"
    else:  # v2
        train = f"s3://{args.bucket}/cross_encoder_pairs/v2/train.jsonl"
        val = f"s3://{args.bucket}/cross_encoder_pairs/v2/val.jsonl"
        output = "models/jpcite-cross-encoder-v2"
        source = "cross_encoder_pairs/v2/source"
    if args.train_uri is None:
        args.train_uri = train
    if args.val_uri is None:
        args.val_uri = val
    if args.output_prefix is None:
        args.output_prefix = output
    if args.source_prefix is None:
        args.source_prefix = source


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _resolve_defaults(args)
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
        version=args.version,
        dry_run=dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
