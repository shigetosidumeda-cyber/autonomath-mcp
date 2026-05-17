#!/usr/bin/env python3
"""Lane BB4 — Submit SageMaker training job for jpcite-bert-v1 LoRA per cohort.

Wraps ``aws sagemaker create-training-job`` to fine-tune a PEFT LoRA
adapter on top of the M5 jpcite-bert-v1 SimCSE checkpoint for one of
the 5 cohort (zeirishi / kaikeishi / gyouseishoshi / shihoshoshi /
chusho_keieisha).

Quota note (2026-05-17)
-----------------------
ap-northeast-1 / profile bookyou-recovery:
    ml.g4dn.xlarge for training job usage = 1
This is a per-instance-family quota; the M5 SimCSE job is on
ml.g4dn.12xlarge (separate quota slot). So a single LoRA cohort job
on ml.g4dn.xlarge does NOT contend with M5. 5 cohort jobs, however,
must run SERIALLY (one ml.g4dn.xlarge slot total). The companion
script ``sagemaker_lora_cohort_watch_and_chain.py`` chains them
post-M5 in deterministic order.

Cost preflight
--------------
- ``aws ce get-cost-and-usage`` MTD sampled; abort if >= HARD_STOP_USD.
- HARD_STOP_USD = 18000 (well under the $19,490 Never-Reach absolute).
- Training instance ml.g4dn.xlarge × 1 × MaxRuntime=6h ≈ $4 hard cap/job.
- 5 jobs serial = ~$20 max (well under budget).

NO LLM API; encoder LoRA fine-tune only.

Constraints
-----------
- DRY_RUN default; pass ``--commit`` to actually create job.
- ``[lane:solo]`` marker.
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

VALID_COHORTS: Final[tuple[str, ...]] = (
    "zeirishi",
    "kaikeishi",
    "gyouseishoshi",
    "shihoshoshi",
    "chusho_keieisha",
)

#: ap-northeast-1 HuggingFace PyTorch GPU training image (matches M5 base).
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
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/x-tar",
    )
    return f"s3://{bucket}/{key}"


def build_spec(
    *,
    job_name: str,
    cohort: str,
    bucket: str,
    role_arn: str,
    region: str,
    train_uri: str,
    val_uri: str,
    base_model_uri: str | None,
    output_prefix: str,
    source_uri: str,
    epochs: int,
    batch_size: int,
    lr: float,
    lora_rank: int,
    lora_alpha: int,
    lora_dropout: float,
    max_runtime: int,
    instance_type: str,
) -> dict[str, Any]:
    """Construct the create-training-job spec."""

    inputs: list[dict[str, Any]] = [
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
    ]
    if base_model_uri:
        inputs.append(
            {
                "ChannelName": "base_model",
                "DataSource": {
                    "S3DataSource": {
                        "S3DataType": "S3Prefix",
                        "S3Uri": base_model_uri,
                        "S3DataDistributionType": "FullyReplicated",
                    }
                },
                "ContentType": "application/x-tar",
                "CompressionType": "None",
            }
        )
    spec: dict[str, Any] = {
        "TrainingJobName": job_name,
        "AlgorithmSpecification": {
            "TrainingImage": TRAINING_IMAGE,
            "TrainingInputMode": "File",
        },
        "RoleArn": role_arn,
        "InputDataConfig": inputs,
        "OutputDataConfig": {"S3OutputPath": f"s3://{bucket}/{output_prefix}/"},
        "ResourceConfig": {
            "InstanceType": instance_type,
            "InstanceCount": 1,
            "VolumeSizeInGB": 100,
        },
        "StoppingCondition": {"MaxRuntimeInSeconds": max_runtime},
        "HyperParameters": {
            "sagemaker_program": "lora_cohort_train_entry.py",
            "sagemaker_submit_directory": source_uri,
            "sagemaker_container_log_level": "20",
            "sagemaker_region": region,
            "cohort": cohort,
            "epochs": str(epochs),
            "batch_size": str(batch_size),
            "lr": str(lr),
            "lora_rank": str(lora_rank),
            "lora_alpha": str(lora_alpha),
            "lora_dropout": str(lora_dropout),
            "model_name": "cl-tohoku/bert-base-japanese-v3",
            "max_length": "128",
            "temperature": "0.05",
        },
        "EnableManagedSpotTraining": False,
        "Tags": [
            {"Key": "lane", "Value": "solo"},
            {"Key": "wave", "Value": "BB4"},
            {"Key": "cohort", "Value": cohort},
            {"Key": "purpose", "Value": "jpcite-bert-v1-lora-cohort-finetune"},
        ],
    }
    return spec


def submit(
    *,
    spec: dict[str, Any],
    region: str,
    profile: str,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return {"dry_run": True, "spec": spec}
    sm = _boto3("sagemaker", region, profile)
    resp = sm.create_training_job(**spec)
    return {"dry_run": False, "spec": spec, "response": {"arn": resp.get("TrainingJobArn", "")}}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="BB4 — Submit jpcite-bert-v1 LoRA fine-tune training job per cohort."
    )
    p.add_argument("--cohort", required=True, choices=list(VALID_COHORTS))
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--role-arn", default=DEFAULT_ROLE_ARN)
    p.add_argument(
        "--job-name",
        default="",
        help="Defaults to jpcite-bert-lora-{cohort}-{TS} if empty.",
    )
    p.add_argument(
        "--corpus-prefix",
        default="finetune_corpus_lora_cohort_{cohort}",
        help="Template; {cohort} substituted.",
    )
    p.add_argument(
        "--base-model-uri",
        default="",
        help=(
            "Optional s3:// URI of M5 jpcite-bert-v1 model.tar.gz channel. "
            "Leave empty to use HuggingFace base model directly."
        ),
    )
    p.add_argument(
        "--output-prefix",
        default="models/jpcite-bert-lora-{cohort}",
        help="Template; {cohort} substituted.",
    )
    p.add_argument(
        "--source-prefix",
        default="finetune_corpus_lora_cohort_source",
    )
    p.add_argument(
        "--entry-file",
        default=str(Path(__file__).parent / "lora_cohort_train_entry.py"),
    )
    p.add_argument(
        "--requirements",
        default=str(Path(__file__).parent / "lora_cohort_train_requirements.txt"),
    )
    p.add_argument("--epochs", type=int, default=2)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr", type=float, default=5e-4)
    p.add_argument("--lora-rank", type=int, default=16)
    p.add_argument("--lora-alpha", type=int, default=32)
    p.add_argument("--lora-dropout", type=float, default=0.05)
    p.add_argument("--max-runtime", type=int, default=6 * 3600)
    p.add_argument("--instance-type", default="ml.g4dn.xlarge")
    p.add_argument("--commit", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dry_run = not args.commit and os.environ.get("DRY_RUN", "1") != "0"
    cohort = args.cohort

    job_name = args.job_name or (
        f"jpcite-bert-lora-{cohort.replace('_', '-')}-"
        f"{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    # SageMaker training job names must be <=63 chars and match
    # ^[a-zA-Z0-9](-*[a-zA-Z0-9]){0,62}$ — sanitize underscores.

    corpus_prefix = args.corpus_prefix.format(cohort=cohort)
    output_prefix = args.output_prefix.format(cohort=cohort)
    train_uri = f"s3://{args.bucket}/{corpus_prefix}/train.jsonl"
    val_uri = f"s3://{args.bucket}/{corpus_prefix}/val.jsonl"

    mtd = preflight_cost(args.region, args.profile)
    print(f"[preflight] mtd_usd={mtd:.4f} < {HARD_STOP_USD}", file=sys.stderr)

    entry = Path(args.entry_file)
    req = Path(args.requirements) if args.requirements else None
    if not entry.exists():
        print(f"[FAIL] entry file missing: {entry}", file=sys.stderr)
        return 2

    tar_body = _build_source_tar(entry, req)
    source_key = f"{args.source_prefix.rstrip('/')}/sourcedir-{job_name}.tar.gz"

    if dry_run:
        source_uri = f"s3://{args.bucket}/{source_key}"
        print(f"[DRY_RUN] would upload source tar ({len(tar_body)} bytes) to {source_uri}")
    else:
        s3 = _boto3("s3", args.region, args.profile)
        source_uri = upload_source_tar(s3, bucket=args.bucket, key=source_key, body=tar_body)
        print(f"[OK] uploaded source tar to {source_uri}")

    spec = build_spec(
        job_name=job_name,
        cohort=cohort,
        bucket=args.bucket,
        role_arn=args.role_arn,
        region=args.region,
        train_uri=train_uri,
        val_uri=val_uri,
        base_model_uri=args.base_model_uri or None,
        output_prefix=output_prefix,
        source_uri=source_uri,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        lora_rank=args.lora_rank,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        max_runtime=args.max_runtime,
        instance_type=args.instance_type,
    )
    result = submit(
        spec=spec,
        region=args.region,
        profile=args.profile,
        dry_run=dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
