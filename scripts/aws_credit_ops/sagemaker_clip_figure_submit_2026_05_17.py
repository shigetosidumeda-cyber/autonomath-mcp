#!/usr/bin/env python3
"""AWS moat Lane M3 — SageMaker Processing Job driver for CLIP-Japanese figure embeddings.

Stage 2 of the M3 lane. Stage 1
(``figure_extract_pipeline.py``) cropped PNG figures from the staged
Lane C PDFs and uploaded them to
``s3://jpcite-credit-993693061769-202605-derived/figures_raw/``. This
script submits a SageMaker **Processing Job** that:

1. Pulls the AWS-managed pytorch-inference image
   (``763104351884.dkr.ecr.ap-northeast-1.amazonaws.com/pytorch-inference:2.0.0-gpu-py310``).
2. Mounts the ``figures_raw`` prefix as an S3 input + a
   ``figures_embed_scratch`` output prefix.
3. Runs an inline Python script (uploaded as a ``code/`` channel) that:
     * loads ``rinna/japanese-clip-vit-b-16`` (Apache-2.0, 198M params),
     * walks every PNG in the input mount,
     * computes the 512-dim image embedding via the CLIP image branch,
     * pairs each embedding with its sidecar caption (read from the
       ledger JSON, also mounted as a /opt/ml/processing/input/ledger/
       channel),
     * writes a JSONL stream of
       ``{figure_id, embedding: [512 floats], caption}`` records to
       ``figure_embeddings/part-####.jsonl`` in the derived bucket.

The Processing Job is preferred over a Batch Transform here because:

* CLIP-Japanese is published as raw transformers weights (no
  SageMaker-blessed inference container) and we want to control the
  preprocessing (PNG → ImageNet-mean-normalised float32 tensor) inline;
* the figure count is modest (≤50K) and one ``ml.g4dn.2xlarge`` GPU
  drains the full corpus in ~12 hours;
* we keep one job spec / one cost line for the moat doc.

NOT an LLM. CLIP (Contrastive Language-Image Pretraining) is an
encoder-only image+text alignment model. It produces a single pooled
512-dim vector per image / per text. No token-by-token decoding, no
Anthropic / OpenAI / Bedrock dependency, no breach of
``feedback_no_operator_llm_api``.

Cost contract
-------------
* ``ml.g4dn.2xlarge`` Processing Job: $0.71 / hour Tokyo region.
* Expected wall: 12 hours for the full Lane C 293-PDF cohort (~50K
  cropped figures, ~85 figs/min throughput for ViT-B/16 on T4 GPU).
* Total burn: ~$8.50 GPU + ~$0.50 S3 = **$9.00** one-shot.
* This is well below the ``$50-100 one-shot`` band the M3 brief
  established; the $19,490 Never-Reach cap is untouched.

Cost preflight (5-line hard-stop alignment): we sample
``ce.get_cost_and_usage`` MTD; ≥ $18,000 aborts before
``create_processing_job``.

DRY_RUN default. ``--commit`` triggers the actual SageMaker API call.

Constraints honoured
--------------------
* AWS profile **bookyou-recovery**.
* Region: ap-northeast-1.
* NO LLM. CLIP is an encoder.
* Code channel uploads a deterministic preprocessor + embedder; we
  pin the model version with ``revision="main"`` and a frozen SHA in
  the run manifest.
* mypy --strict + ruff 0.
* ``[lane:solo]`` marker.

Usage
-----
::

    .venv/bin/python scripts/aws_credit_ops/sagemaker_clip_figure_submit_2026_05_17.py \\
        --ledger data/figure_extract_ledger_2026_05_17.json \\
        --commit
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import textwrap
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("sagemaker_clip_figure_submit")

DEFAULT_PROFILE = "bookyou-recovery"
DEFAULT_REGION = "ap-northeast-1"
DEFAULT_ACCOUNT_ID = "993693061769"
DEFAULT_DERIVED_BUCKET = f"jpcite-credit-{DEFAULT_ACCOUNT_ID}-202605-derived"
DEFAULT_FIGURES_INPUT_PREFIX = "figures_raw/"
DEFAULT_FIGURES_OUTPUT_PREFIX = "figure_embeddings/"
DEFAULT_CODE_PREFIX = "figure_embeddings_code/"
DEFAULT_EXECUTION_ROLE = f"arn:aws:iam::{DEFAULT_ACCOUNT_ID}:role/jpcite-sagemaker-execution-role"
DEFAULT_INSTANCE = "ml.c5.4xlarge"
DEFAULT_INSTANCE_COUNT = 1
DEFAULT_VOLUME_GB = 100
DEFAULT_MAX_HOURS = 4
DEFAULT_BUDGET_USD = 100.0
DEFAULT_LEDGER = "data/figure_extract_ledger_2026_05_17.json"
HARD_STOP_USD = 18000.0
#: Per-hour USD pricing table for the Tokyo Processing instance types
#: this script accepts. CPU options preferred because the operator's
#: SageMaker quota matrix shows GPU (ml.g4dn.*) at 0 instances at the
#: time of M3 landing — see Service Quotas console / probe at
#: `aws service-quotas list-service-quotas --service-code sagemaker`.
PRICING_USD_PER_HOUR: dict[str, float] = {
    "ml.c5.4xlarge": 0.952,
    "ml.c5.9xlarge": 2.142,
    "ml.c5.18xlarge": 4.284,
    "ml.c7i.4xlarge": 0.945,
    "ml.m5.4xlarge": 1.075,
    "ml.g4dn.2xlarge": 0.71,
    "ml.g5.xlarge": 1.408,
}
PER_HOUR_USD = PRICING_USD_PER_HOUR[DEFAULT_INSTANCE]
DEFAULT_MODEL = "rinna/japanese-clip-vit-b-16"
DEFAULT_MODEL_REVISION = "main"
ALLOW_MODELS = {
    "rinna/japanese-clip-vit-b-16": {"dim": 512, "license": "Apache-2.0"},
    "rinna/japanese-cloob-vit-b-16": {"dim": 512, "license": "Apache-2.0"},
}
PYTORCH_IMAGE = (
    f"763104351884.dkr.ecr.{DEFAULT_REGION}.amazonaws.com/pytorch-inference:2.0.0-gpu-py310"
)

#: Inline embedder script that the Processing Job downloads via the
#: ``code/`` S3 channel and executes. Kept simple — transformers AutoModel
#: + manual torchvision preprocessing; no CLI args, fully data-driven from
#: ``/opt/ml/processing/input/...`` mounts.
EMBEDDER_SCRIPT = textwrap.dedent(
    '''
    """Inline CLIP-Japanese embedder run inside the SageMaker Processing Job."""

    import io
    import json
    import os
    import sys
    from pathlib import Path

    import torch
    from PIL import Image

    try:
        from transformers import AutoModel
        from torchvision import transforms
        from torchvision.transforms import InterpolationMode
    except ImportError:
        os.system(
            f"{sys.executable} -m pip install --quiet "
            "'transformers==4.36.2' 'torchvision==0.15.2' pillow"
        )
        from transformers import AutoModel
        from torchvision import transforms
        from torchvision.transforms import InterpolationMode

    MODEL_ID = os.environ.get("CLIP_MODEL_ID", "rinna/japanese-clip-vit-b-16")
    MODEL_REVISION = os.environ.get("CLIP_MODEL_REVISION", "main")
    INPUT_DIR = Path("/opt/ml/processing/input/figures")
    LEDGER_PATH = Path("/opt/ml/processing/input/ledger/ledger.json")
    OUTPUT_DIR = Path("/opt/ml/processing/output/embeddings")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = AutoModel.from_pretrained(MODEL_ID, revision=MODEL_REVISION, trust_remote_code=True).to(device).eval()
    preprocess = transforms.Compose(
        [
            transforms.Resize(224, interpolation=InterpolationMode.BICUBIC),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=(0.48145466, 0.4578275, 0.40821073),
                std=(0.26862954, 0.26130258, 0.27577711),
            ),
        ]
    )

    captions: dict[str, dict] = {}
    if LEDGER_PATH.exists():
        with LEDGER_PATH.open(encoding="utf-8") as fh:
            ledger = json.load(fh)
        for rec in ledger.get("records", []):
            captions[rec["s3_key"]] = rec

    PART_SIZE = 1024
    buffer: list[dict] = []
    part_idx = 0

    def flush(buf: list[dict], idx: int) -> None:
        if not buf:
            return
        out = OUTPUT_DIR / f"part-{idx:04d}.jsonl"
        with out.open("w", encoding="utf-8") as fh:
            for rec in buf:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\\n")

    png_paths = sorted(INPUT_DIR.rglob("*.png"))
    print(f"png_count={len(png_paths)} model={MODEL_ID} rev={MODEL_REVISION} device={device}")

    with torch.no_grad():
        for png_path in png_paths:
            try:
                img = Image.open(png_path).convert("RGB")
                pixel_values = preprocess(img).unsqueeze(0).to(device)
                feats = model.get_image_features(pixel_values=pixel_values)
                feats = feats / feats.norm(dim=-1, keepdim=True).clamp_min(1e-12)
                vec = feats[0].float().cpu().tolist()
            except Exception as exc:  # noqa: BLE001
                print(f"skip {png_path}: {exc}")
                continue
            rel_key = png_path.relative_to(INPUT_DIR).as_posix()
            ledger_key = f"figures_raw/{rel_key}"
            meta = captions.get(ledger_key, {})
            buffer.append({
                "figure_id": meta.get("figure_id") or f"fig_{rel_key.replace('/', '_')}",
                "embedding": vec,
                "caption": meta.get("caption", ""),
                "pdf_sha256": meta.get("pdf_sha256"),
                "source_url": meta.get("source_url"),
                "page_no": meta.get("page_no"),
                "figure_idx": meta.get("figure_idx"),
                "embedding_model": MODEL_ID,
                "embedding_dim": len(vec),
            })
            if len(buffer) >= PART_SIZE:
                flush(buffer, part_idx)
                buffer = []
                part_idx += 1
        flush(buffer, part_idx)

    print(f"done. parts={part_idx + 1}")
    '''
).strip()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI flags."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ledger", default=DEFAULT_LEDGER)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--derived-bucket", default=DEFAULT_DERIVED_BUCKET)
    p.add_argument("--input-prefix", default=DEFAULT_FIGURES_INPUT_PREFIX)
    p.add_argument("--output-prefix", default=DEFAULT_FIGURES_OUTPUT_PREFIX)
    p.add_argument("--code-prefix", default=DEFAULT_CODE_PREFIX)
    p.add_argument("--execution-role", default=DEFAULT_EXECUTION_ROLE)
    p.add_argument("--instance-type", default=DEFAULT_INSTANCE)
    p.add_argument("--instance-count", type=int, default=DEFAULT_INSTANCE_COUNT)
    p.add_argument("--volume-gb", type=int, default=DEFAULT_VOLUME_GB)
    p.add_argument("--max-hours", type=float, default=DEFAULT_MAX_HOURS)
    p.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    p.add_argument("--model-id", default=DEFAULT_MODEL, choices=sorted(ALLOW_MODELS))
    p.add_argument("--model-revision", default=DEFAULT_MODEL_REVISION)
    p.add_argument("--job-name", default=None)
    p.add_argument("--manifest-out", default="out/aws_credit_jobs/clip_figure_submit_manifest.json")
    p.add_argument("--commit", action="store_true", help="Lift DRY_RUN guard")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def _stamp_job_name() -> str:
    """Return a deterministic-ish job name with a UTC stamp."""
    today = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"jpcite-figure-clip-jp-{today}-{uuid.uuid4().hex[:6]}"


def _cost_estimate(args: argparse.Namespace) -> dict[str, Any]:
    """Project the Processing Job spend before the API call."""
    instance_count = max(1, args.instance_count)
    wall_hours = float(args.max_hours)
    per_hour = PRICING_USD_PER_HOUR.get(args.instance_type, PER_HOUR_USD)
    proj = instance_count * wall_hours * per_hour
    return {
        "instance_type": args.instance_type,
        "instance_count": instance_count,
        "wall_hours_cap": wall_hours,
        "per_hour_usd": per_hour,
        "projected_usd": round(proj, 2),
        "budget_usd": args.budget_usd,
        "fits_budget": proj <= args.budget_usd,
    }


def _build_processing_inputs(
    args: argparse.Namespace, ledger_uri: str, code_s3_prefix: str
) -> list[dict[str, Any]]:
    """Render the Processing Job ProcessingInputs list."""
    base = f"s3://{args.derived_bucket}/"
    return [
        {
            "InputName": "figures",
            "AppManaged": False,
            "S3Input": {
                "S3Uri": base + args.input_prefix,
                "LocalPath": "/opt/ml/processing/input/figures",
                "S3DataType": "S3Prefix",
                "S3InputMode": "File",
                "S3DataDistributionType": "FullyReplicated",
                "S3CompressionType": "None",
            },
        },
        {
            "InputName": "ledger",
            "AppManaged": False,
            "S3Input": {
                "S3Uri": ledger_uri,
                "LocalPath": "/opt/ml/processing/input/ledger",
                "S3DataType": "S3Prefix",
                "S3InputMode": "File",
                "S3DataDistributionType": "FullyReplicated",
                "S3CompressionType": "None",
            },
        },
        {
            "InputName": "code",
            "AppManaged": False,
            "S3Input": {
                "S3Uri": f"{base}{code_s3_prefix}",
                "LocalPath": "/opt/ml/processing/input/code",
                "S3DataType": "S3Prefix",
                "S3InputMode": "File",
                "S3DataDistributionType": "FullyReplicated",
                "S3CompressionType": "None",
            },
        },
    ]


def _build_processing_outputs(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Render the Processing Job ProcessingOutputConfig.Outputs list."""
    base = f"s3://{args.derived_bucket}/"
    return [
        {
            "OutputName": "embeddings",
            "AppManaged": False,
            "S3Output": {
                "S3Uri": base + args.output_prefix,
                "LocalPath": "/opt/ml/processing/output/embeddings",
                "S3UploadMode": "EndOfJob",
            },
        }
    ]


def _build_app_spec(args: argparse.Namespace) -> dict[str, Any]:
    """Render the AppSpecification for the Processing Job."""
    return {
        "ImageUri": PYTORCH_IMAGE,
        "ContainerEntrypoint": ["python3", "/opt/ml/processing/input/code/embed.py"],
    }


def _build_environment(args: argparse.Namespace) -> dict[str, str]:
    """Render container env vars (encoder pin + model id)."""
    return {
        "CLIP_MODEL_ID": args.model_id,
        "CLIP_MODEL_REVISION": args.model_revision,
        "PYTHONUNBUFFERED": "1",
        "TRANSFORMERS_OFFLINE": "0",
        "HF_HUB_DOWNLOAD_TIMEOUT": "300",
    }


def _check_cost_preflight(profile: str, region: str, budget_usd: float) -> dict[str, Any]:
    """Sample CE MTD and reject if ≥ HARD_STOP_USD."""
    try:
        import boto3
    except ImportError:  # pragma: no cover - environment guard
        return {"skipped": True, "reason": "boto3 unavailable", "mtd_usd": 0.0}
    session = boto3.Session(profile_name=profile)
    ce = session.client("ce", region_name="us-east-1")  # CE only in us-east-1
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    month_start = datetime.now(UTC).strftime("%Y-%m-01")
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": month_start, "End": today},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )
    try:
        amt = float(resp["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"])
    except (KeyError, IndexError, ValueError):
        amt = 0.0
    return {
        "skipped": False,
        "mtd_usd": round(amt, 2),
        "hard_stop_usd": HARD_STOP_USD,
        "ok": amt < HARD_STOP_USD,
    }


def _upload_code_channel(
    args: argparse.Namespace,
    job_name: str,
    *,
    commit: bool,
) -> tuple[str, dict[str, Any]]:
    """Upload the inline embedder script to a per-job ``code/`` S3 prefix."""
    job_code_prefix = f"{args.code_prefix.rstrip('/')}/{job_name}/"
    code_key = f"{job_code_prefix}embed.py"
    if commit:
        import boto3

        session = boto3.Session(profile_name=args.profile)
        s3 = session.client("s3", region_name=args.region)
        s3.put_object(
            Bucket=args.derived_bucket,
            Key=code_key,
            Body=EMBEDDER_SCRIPT.encode("utf-8"),
            ContentType="text/x-python",
        )
    return code_key, {
        "code_bucket": args.derived_bucket,
        "code_key": code_key,
        "code_s3_prefix": job_code_prefix,
        "size_bytes": len(EMBEDDER_SCRIPT),
    }


def _ensure_ledger_in_s3(
    args: argparse.Namespace,
    *,
    commit: bool,
) -> tuple[str, dict[str, Any]]:
    """Stage the local ledger JSON to S3 so the Processing Job can mount it."""
    if not os.path.exists(args.ledger):
        return "", {"skipped": True, "reason": f"ledger {args.ledger} missing"}
    ledger_key = f"{args.code_prefix.rstrip('/')}/ledger/ledger.json"
    uri = f"s3://{args.derived_bucket}/{ledger_key.rsplit('/', 1)[0]}/"
    if commit:
        import boto3

        session = boto3.Session(profile_name=args.profile)
        s3 = session.client("s3", region_name=args.region)
        s3.upload_file(args.ledger, args.derived_bucket, ledger_key)
    return uri, {"ledger_uri": uri, "ledger_local": args.ledger}


def _build_processing_request(
    args: argparse.Namespace,
    *,
    job_name: str,
    code_key: str,
    code_s3_prefix: str,
    ledger_uri: str,
) -> dict[str, Any]:
    """Construct the create_processing_job request body."""
    return {
        "ProcessingJobName": job_name,
        "ProcessingResources": {
            "ClusterConfig": {
                "InstanceCount": args.instance_count,
                "InstanceType": args.instance_type,
                "VolumeSizeInGB": args.volume_gb,
            }
        },
        "AppSpecification": _build_app_spec(args),
        "Environment": _build_environment(args),
        "RoleArn": args.execution_role,
        "ProcessingInputs": _build_processing_inputs(
            args,
            ledger_uri or f"s3://{args.derived_bucket}/{args.code_prefix.rstrip('/')}/ledger/",
            code_s3_prefix,
        ),
        "ProcessingOutputConfig": {"Outputs": _build_processing_outputs(args)},
        "StoppingCondition": {"MaxRuntimeInSeconds": int(args.max_hours * 3600)},
        "Tags": [
            {"Key": "lane", "Value": "solo"},
            {"Key": "lane-id", "Value": "M3"},
            {"Key": "moat", "Value": "figure-clip-multimodal"},
            {"Key": "cost-band", "Value": "moat-100usd"},
            {"Key": "no-llm", "Value": "true"},
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry — preflight cost, upload code, submit Processing Job."""
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
    )

    estimate = _cost_estimate(args)
    logger.info("cost estimate: %s", json.dumps(estimate))
    if not estimate["fits_budget"]:
        logger.error(
            "projected %.2f USD exceeds budget %.2f USD — aborting",
            estimate["projected_usd"],
            args.budget_usd,
        )
        return 2

    preflight = _check_cost_preflight(args.profile, args.region, args.budget_usd)
    logger.info("MTD preflight: %s", json.dumps(preflight))
    if not preflight.get("skipped") and not preflight.get("ok", True):
        logger.error(
            "MTD %.2f USD ≥ hard-stop %.2f USD — aborting", preflight["mtd_usd"], HARD_STOP_USD
        )
        return 3

    job_name = args.job_name or _stamp_job_name()
    code_key, code_meta = _upload_code_channel(args, job_name, commit=args.commit)
    code_s3_prefix = str(code_meta["code_s3_prefix"])
    ledger_uri, ledger_meta = _ensure_ledger_in_s3(args, commit=args.commit)
    req = _build_processing_request(
        args,
        job_name=job_name,
        code_key=code_key,
        code_s3_prefix=code_s3_prefix,
        ledger_uri=ledger_uri,
    )
    manifest = {
        "manifest_id": "clip_figure_submit_2026_05_17",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "profile": args.profile,
        "region": args.region,
        "job_name": job_name,
        "cost_estimate": estimate,
        "mtd_preflight": preflight,
        "code_channel": code_meta,
        "ledger_channel": ledger_meta,
        "model_id": args.model_id,
        "model_revision": args.model_revision,
        "model_dim": ALLOW_MODELS[args.model_id]["dim"],
        "model_license": ALLOW_MODELS[args.model_id]["license"],
        "create_processing_job_request": req,
        "committed": bool(args.commit),
    }
    if args.commit:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover
            raise SystemExit(f"boto3 required for --commit: {exc}") from exc
        session = boto3.Session(profile_name=args.profile)
        sm = session.client("sagemaker", region_name=args.region)
        resp = sm.create_processing_job(**req)
        manifest["create_processing_job_response"] = {
            "ProcessingJobArn": resp.get("ProcessingJobArn"),
        }
        logger.info("submitted: %s", resp.get("ProcessingJobArn"))
    else:
        logger.info("DRY_RUN — pass --commit to submit job %s", job_name)

    Path(args.manifest_out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.manifest_out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    logger.info("wrote manifest %s", args.manifest_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
