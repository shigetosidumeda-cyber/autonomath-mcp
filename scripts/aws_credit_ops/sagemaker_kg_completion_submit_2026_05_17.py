#!/usr/bin/env python3
"""Lane M7 — Submit 4 SageMaker training jobs for KG embedding ensemble.

Trains TransE / RotatE / ComplEx / ConvE on the jpcite knowledge graph
exported to ``s3://.../kg_corpus/`` by
``kg_completion_export_2026_05_17.py``. Each job runs on a single
``ml.g4dn.12xlarge`` (4× T4 GPU, $3.91/h) with a 24h max-runtime cap.

Default mode is **sequential** — submits one job at a time, waits ~24h,
then submits the next. Sequential mode respects a 64-vCPU quota (the
g4dn.12xlarge is 48 vCPU, so two in parallel = 96 vCPU which trips a
default quota). With a 256-vCPU quota approval, pass ``--parallel`` to
submit all 4 simultaneously.

Cost preflight
--------------
- ``aws ce get-cost-and-usage`` MTD sampled; abort if >= HARD_STOP_USD.
- HARD_STOP_USD = 18,000 (well under the $19,490 Never-Reach absolute).
- 4× $94 = ~$376 absolute ceiling for the ensemble.

Live-mode gate
--------------
Default is **DRY_RUN**. Live submission requires ALL THREE:
  1. ``--commit`` flag, AND
  2. ``--unlock-live-aws-commands`` flag (operator token gate per Stream W
     concern-separation memory ``feedback_loop_promote_concern_separation``),
     AND
  3. ``DRY_RUN=0`` in the environment.

Without all three gates the script prints the would-be spec without calling
``create_training_job``.

Constraints
-----------
- ``[lane:solo]`` marker.
- ruff / mypy clean.
- NO LLM API.
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

#: PyTorch 2.1 GPU training image (cu121 ap-northeast-1).
TRAINING_IMAGE: Final[str] = (
    "763104351884.dkr.ecr.ap-northeast-1.amazonaws.com/"
    "pytorch-training:2.1.0-gpu-py310-cu121-ubuntu20.04-sagemaker"
)

MODELS: Final[tuple[str, ...]] = ("TransE", "RotatE", "ComplEx", "ConvE")

MODEL_PROFILES: Final[dict[str, dict[str, int | float]]] = {
    "TransE": {
        "embedding_dim": 500,
        "epochs": 200,
        "batch_size": 512,
        "negative_samples": 256,
        "learning_rate": 1e-3,
    },
    "RotatE": {
        "embedding_dim": 500,
        "epochs": 200,
        "batch_size": 512,
        "negative_samples": 256,
        "learning_rate": 1e-3,
    },
    "ComplEx": {
        "embedding_dim": 500,
        "epochs": 200,
        "batch_size": 512,
        "negative_samples": 256,
        "learning_rate": 1e-3,
    },
    "ConvE": {
        "embedding_dim": 200,
        "epochs": 200,
        "batch_size": 256,
        "negative_samples": 128,
        "learning_rate": 1e-3,
    },
}


def _boto3(service: str, region: str, profile: str) -> Any:
    import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]

    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client(service)


def preflight_cost(region: str, profile: str) -> float:
    """5-line hard-stop preflight (same envelope as M5 driver)."""

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


def _build_source_tar(entry: Path, requirements: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(str(entry), arcname=entry.name)
        if requirements.exists():
            tar.add(str(requirements), arcname="requirements.txt")
    return buf.getvalue()


def _spec(
    *,
    job_name: str,
    bucket: str,
    role_arn: str,
    region: str,
    train_uri: str,
    val_uri: str,
    test_uri: str,
    output_prefix: str,
    source_uri: str,
    model: str,
    embedding_dim: int,
    epochs: int,
    batch_size: int,
    negative_samples: int,
    learning_rate: float,
    max_runtime: int,
    instance_type: str,
) -> dict[str, Any]:
    return {
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
            {
                "ChannelName": "test",
                "DataSource": {
                    "S3DataSource": {
                        "S3DataType": "S3Prefix",
                        "S3Uri": test_uri,
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
            "sagemaker_program": "kg_completion_train_entry.py",
            "sagemaker_submit_directory": source_uri,
            "sagemaker_container_log_level": "20",
            "sagemaker_region": region,
            "model": model,
            "embedding-dim": str(embedding_dim),
            "epochs": str(epochs),
            "batch-size": str(batch_size),
            "negative-samples": str(negative_samples),
            "learning-rate": str(learning_rate),
        },
        "EnableManagedSpotTraining": False,
        "Tags": [
            {"Key": "lane", "Value": "solo"},
            {"Key": "wave", "Value": "M7"},
            {"Key": "model", "Value": model},
            {"Key": "purpose", "Value": "kg-completion-ensemble"},
        ],
    }


def _profiled_hyperparameters(
    *,
    model: str,
    embedding_dim: int,
    epochs: int,
    batch_size: int,
    negative_samples: int,
    learning_rate: float,
) -> dict[str, int | float]:
    """Apply conservative per-model caps before live submit."""

    profile = MODEL_PROFILES.get(model, {})
    dim_cap = int(profile.get("embedding_dim", embedding_dim))
    epochs_cap = int(profile.get("epochs", epochs))
    batch_cap = int(profile.get("batch_size", batch_size))
    neg_cap = int(profile.get("negative_samples", negative_samples))
    lr_cap = float(profile.get("learning_rate", learning_rate))
    return {
        "embedding_dim": min(embedding_dim, dim_cap),
        "epochs": min(epochs, epochs_cap),
        "batch_size": min(batch_size, batch_cap),
        "negative_samples": min(negative_samples, neg_cap),
        "learning_rate": min(learning_rate, lr_cap),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--role-arn", default=DEFAULT_ROLE_ARN)
    p.add_argument(
        "--run-id",
        default=dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ"),
        help="run identifier for job name suffix",
    )
    p.add_argument(
        "--train-uri",
        default=f"s3://{DEFAULT_BUCKET}/kg_corpus/train.jsonl",
    )
    p.add_argument(
        "--val-uri",
        default=f"s3://{DEFAULT_BUCKET}/kg_corpus/val.jsonl",
    )
    p.add_argument(
        "--test-uri",
        default=f"s3://{DEFAULT_BUCKET}/kg_corpus/test.jsonl",
    )
    p.add_argument(
        "--output-prefix",
        default="models/jpcite-kg-completion-v1",
    )
    p.add_argument(
        "--source-prefix",
        default="kg_corpus/source",
    )
    p.add_argument(
        "--entry-file",
        default=str(Path(__file__).parent / "kg_completion_train_entry.py"),
    )
    p.add_argument(
        "--requirements",
        default=str(Path(__file__).parent / "kg_completion_train_requirements.txt"),
    )
    p.add_argument(
        "--models",
        default=",".join(MODELS),
        help=f"comma-separated subset of {MODELS}",
    )
    p.add_argument(
        "--embedding-dim", "--embedding_dim", dest="embedding_dim", type=int, default=500
    )
    p.add_argument("--epochs", type=int, default=200)
    p.add_argument("--batch-size", "--batch_size", dest="batch_size", type=int, default=512)
    p.add_argument(
        "--negative-samples",
        "--negative_samples",
        dest="negative_samples",
        type=int,
        default=256,
    )
    p.add_argument(
        "--learning-rate", "--learning_rate", dest="learning_rate", type=float, default=1e-3
    )
    p.add_argument("--max-runtime", type=int, default=24 * 3600, help="seconds")
    p.add_argument("--instance-type", default="ml.g4dn.12xlarge")
    p.add_argument(
        "--parallel",
        action="store_true",
        help="submit all 4 jobs simultaneously (requires 256 vCPU quota)",
    )
    p.add_argument(
        "--commit",
        action="store_true",
        help="actually create training job (default: DRY_RUN)",
    )
    p.add_argument(
        "--unlock-live-aws-commands",
        action="store_true",
        help=(
            "operator token gate per Stream W concern-separation. "
            "REQUIRED in addition to --commit for any live side-effect."
        ),
    )
    p.add_argument(
        "--records-out",
        type=str,
        default="docs/_internal/sagemaker_kg_completion_2026_05_17_records.json",
    )
    return p.parse_args(argv)


def _resolve_dry_run(args: argparse.Namespace) -> bool:
    """Resolve dry-run state per Stream W operator-token gate."""

    env_dry_run = os.environ.get("DRY_RUN", "1") != "0"
    if not args.commit:
        return True
    if not args.unlock_live_aws_commands:
        return True
    return env_dry_run


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dry_run = _resolve_dry_run(args)

    mtd = preflight_cost(args.region, args.profile)
    print(f"[preflight] mtd_usd={mtd:.4f} < {HARD_STOP_USD}", file=sys.stderr)

    entry = Path(args.entry_file)
    req = Path(args.requirements)
    if not entry.exists():
        print(f"[FAIL] entry missing: {entry}", file=sys.stderr)
        return 2

    tar_body = _build_source_tar(entry, req)
    source_key = f"{args.source_prefix.rstrip('/')}/sourcedir-kg-completion-{args.run_id}.tar.gz"
    source_uri = f"s3://{args.bucket}/{source_key}"

    if dry_run:
        print(
            f"[DRY_RUN] would upload source tar ({len(tar_body):,} bytes) to {source_uri}",
            file=sys.stderr,
        )
    else:
        s3 = _boto3("s3", args.region, args.profile)
        s3.put_object(
            Bucket=args.bucket,
            Key=source_key,
            Body=tar_body,
            ContentType="application/x-tar",
        )
        print(f"[OK] uploaded {source_uri}", file=sys.stderr)

    selected_models = [m.strip() for m in args.models.split(",") if m.strip()]
    for m in selected_models:
        if m not in MODELS:
            print(f"[FAIL] unknown model {m!r}; expected one of {MODELS}", file=sys.stderr)
            return 2

    submitted: list[dict[str, Any]] = []
    sm = None if dry_run else _boto3("sagemaker", args.region, args.profile)

    for model in selected_models:
        job_name = f"jpcite-kg-{model.lower()}-{args.run_id}"
        profiled = _profiled_hyperparameters(
            model=model,
            embedding_dim=args.embedding_dim,
            epochs=args.epochs,
            batch_size=args.batch_size,
            negative_samples=args.negative_samples,
            learning_rate=args.learning_rate,
        )
        spec = _spec(
            job_name=job_name,
            bucket=args.bucket,
            role_arn=args.role_arn,
            region=args.region,
            train_uri=args.train_uri,
            val_uri=args.val_uri,
            test_uri=args.test_uri,
            output_prefix=f"{args.output_prefix}/{model.lower()}",
            source_uri=source_uri,
            model=model,
            embedding_dim=int(profiled["embedding_dim"]),
            epochs=int(profiled["epochs"]),
            batch_size=int(profiled["batch_size"]),
            negative_samples=int(profiled["negative_samples"]),
            learning_rate=float(profiled["learning_rate"]),
            max_runtime=args.max_runtime,
            instance_type=args.instance_type,
        )
        record: dict[str, Any] = {
            "job_name": job_name,
            "model": model,
            "spec_summary": {
                "instance_type": spec["ResourceConfig"]["InstanceType"],
                "max_runtime_seconds": spec["StoppingCondition"]["MaxRuntimeInSeconds"],
                "output": spec["OutputDataConfig"]["S3OutputPath"],
                "training_image": spec["AlgorithmSpecification"]["TrainingImage"],
                "hyperparameters": {
                    "embedding_dim": int(profiled["embedding_dim"]),
                    "epochs": int(profiled["epochs"]),
                    "batch_size": int(profiled["batch_size"]),
                    "negative_samples": int(profiled["negative_samples"]),
                    "learning_rate": float(profiled["learning_rate"]),
                },
            },
        }
        if dry_run:
            print(
                f"[DRY_RUN] {model:<8} would submit {job_name}",
                file=sys.stderr,
            )
            record["arn"] = "(dry-run)"
        else:
            assert sm is not None
            resp = sm.create_training_job(**spec)
            arn = resp.get("TrainingJobArn", "")
            print(f"[OK] {model:<8} {job_name}  {arn}", file=sys.stderr)
            record["arn"] = arn
        submitted.append(record)

        # Sequential mode: do NOT submit the next job — operator runs the
        # driver again after this one completes (or with --parallel).
        if not args.parallel and not dry_run:
            print(
                f"[seq] sequential mode: re-run driver after {job_name} completes",
                file=sys.stderr,
            )
            break

    ledger = {
        "run_id": args.run_id,
        "wave": "M7",
        "lane": "solo",
        "preflight_actual_usd": mtd,
        "dry_run": dry_run,
        "parallel": args.parallel,
        "source_uri": source_uri,
        "models_requested": selected_models,
        "submitted_count": len(submitted),
        "submitted": submitted,
        "hyperparameters": {
            "embedding_dim": args.embedding_dim,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "negative_samples": args.negative_samples,
            "learning_rate": args.learning_rate,
            "max_runtime_seconds": args.max_runtime,
            "instance_type": args.instance_type,
        },
        "model_profiles": MODEL_PROFILES,
    }
    out_path = Path(args.records_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))
    print(
        f"[ledger] {out_path}  ({len(submitted)}/{len(selected_models)} submitted; dry_run={dry_run})",
        file=sys.stderr,
    )
    print(json.dumps(ledger, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
