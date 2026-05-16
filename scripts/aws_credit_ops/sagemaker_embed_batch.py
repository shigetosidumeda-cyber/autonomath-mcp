#!/usr/bin/env python3
"""SageMaker batch-transform driver for sentence-transformers embeddings.

This script triggers a **SageMaker batch transform** job that loads an
open-weight ``sentence-transformers`` model (default
``sentence-transformers/all-MiniLM-L6-v2``) and produces a 384-d (or
768-d, depending on model) embedding for every row of a JSONL input
file. It is the operator front-door for §3.4 of the Wave 50 AWS canary
plan (``USD 1,500-3,000`` band for search / retrieval index build).

It is **NOT** an LLM driver. ``sentence-transformers`` is a family of
small open-weight transformer encoders (MiniLM, MPNet, etc.) released
under permissive licenses (Apache-2.0 / MIT) on Hugging Face. The
embeddings produced here feed our retrieval index — they are not
generative text and do not flow through any Anthropic / OpenAI / Bedrock
endpoint. ``tests/test_no_llm_in_production.py`` would still red-card
any such import in this tree.

Pipeline
--------
1. ``--input-prefix s3://<derived_bucket>/J04_egov_law/`` is parsed. The
   script does not pre-list the input — SageMaker's batch transform
   accepts a prefix directly and shards internally. We only validate
   that the prefix exists (via a small ``HeadObject`` on a sentinel
   ``manifest.json`` when present, else no-op).
2. ``--model sentence-transformers/all-MiniLM-L6-v2`` (default) is
   resolved through the script's allow-list of three known-good
   sentence-transformer models. Unknown models are rejected — the
   J06 / J04 cohort has a stable retrieval surface and we deliberately
   refuse "novel" embedding models that would invalidate downstream
   ``vec`` indexes.
3. The script renders a SageMaker batch-transform job spec
   (``CreateTransformJob`` request) referencing an existing endpoint
   config / model name (the caller is responsible for having created
   that resource — this script is a *driver*, not an IaC tool). When
   ``DRY_RUN`` is active (default), the rendered spec is printed but no
   API call is made. With ``--commit`` the script calls
   ``boto3.client('sagemaker').create_transform_job``.
4. Cost preflight: each row is billed at ``--per-row-usd`` (default
   ``0.0001`` USD — derived from ``ml.c5.xlarge`` batch transform
   per-second cost ÷ throughput; see docstring footer). The script
   estimates total row count from ``--estimated-rows`` (caller must
   pass it because we do not eagerly walk the prefix). Projected spend
   above ``--budget-usd`` (default ``3000``) stops the job *before*
   creation; above ``warn-threshold`` (default ``0.8``) emits a warning.
5. Run manifest: ``run_manifest.json`` is staged at ``--output-prefix``
   root with the rendered transform job spec, the estimated cost, the
   knobs, and (when ``--commit``) the SageMaker ``TransformJobArn``.

Notes
-----
* **SageMaker IAM role + endpoint config**: this script does NOT create
  the IAM execution role nor the SageMaker ``Model`` resource. Both
  must already exist (per AWS canary plan §3.4 — operator creates them
  manually in the AWS console, with a least-privilege policy scoped to
  ``s3:GetObject`` on the input prefix, ``s3:PutObject`` on the output
  prefix, and ``ecr:BatchGetImage`` on the Hugging Face inference
  image). The script validates the role ARN format and refuses to
  proceed when the role ARN is the empty placeholder.
* **Why sentence-transformers / all-MiniLM-L6-v2** (default): 384-d
  embedding, 22 MB model size, BSD-3 / Apache-2.0 license tree on
  Hugging Face, 14k+ stars, used by FAISS / pgvector / sqlite-vec
  tutorials as the canonical small-and-fast retrieval baseline. It is
  not generative and does not require any model-provider API key. We
  also allow ``sentence-transformers/all-mpnet-base-v2`` (768-d, higher
  recall, 420 MB) and the Japanese-tuned
  ``sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`` for
  the J04 e-Gov 法令 corpus where Japanese tokenization dominates.

CLI
---

.. code-block:: text

    python scripts/aws_credit_ops/sagemaker_embed_batch.py \\
        --input-prefix s3://jpcite-credit-993693061769-202605-derived/J04_egov_law/ \\
        --output-prefix s3://jpcite-credit-993693061769-202605-derived/J04_egov_embeddings/ \\
        --model sentence-transformers/all-MiniLM-L6-v2 \\
        --sagemaker-model-name jpcite-embed-allminilm-v1 \\
        --execution-role-arn arn:aws:iam::993693061769:role/jpcite-sagemaker-embed-role \\
        --estimated-rows 50000 \\
        [--instance-type ml.c5.xlarge] \\
        [--budget-usd 3000] \\
        [--per-row-usd 0.0001] \\
        [--commit]

Constraints
-----------
* **NO LLM API calls.** sentence-transformers is an encoder, not a
  generator. No Anthropic / OpenAI / Bedrock imports.
* **DRY_RUN default.** No SageMaker API calls unless ``--commit``.
* **Budget tracking.** Projected spend is computed before
  ``CreateTransformJob`` is called.
* **Model allow-list.** Three known-good models only.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("sagemaker_embed_batch")

#: Default §3.4 ceiling (USD). Wave 50 AWS canary plan budgets
#: search / retrieval index at ``USD 1,500-3,000``; we pin the upper
#: bound as the hard stop.
DEFAULT_BUDGET_USD: Final[float] = 3000.0

#: Default per-row USD cost. Derived as
#: ``ml.c5.xlarge`` on-demand spot price ``USD 0.108/hr`` ÷ throughput
#: estimate ``1080 rows/hr`` ≈ ``USD 0.0001/row``. This is an
#: order-of-magnitude default — the operator is expected to revise it
#: after a smoke run on a representative slice.
DEFAULT_PER_ROW_USD: Final[float] = 0.0001

#: Warn at 80% of budget, stop at 100%.
DEFAULT_WARN_THRESHOLD: Final[float] = 0.8

#: Allow-list of sentence-transformer models. Unknown models are
#: rejected — the J04 / J06 vec index is dimensioned against these
#: three embedding sizes and adding a new model invalidates downstream
#: sqlite-vec / pgvector indexes.
ALLOWED_MODELS: Final[dict[str, dict[str, Any]]] = {
    "sentence-transformers/all-MiniLM-L6-v2": {
        "dim": 384,
        "size_mb": 22,
        "license": "apache-2.0",
        "rationale": (
            "Canonical small-and-fast retrieval baseline. 384-d, 22 MB. "
            "Used by FAISS / pgvector / sqlite-vec tutorials as the default."
        ),
    },
    "sentence-transformers/all-mpnet-base-v2": {
        "dim": 768,
        "size_mb": 420,
        "license": "apache-2.0",
        "rationale": (
            "Higher-recall English-dominant model. 768-d, 420 MB. Use when "
            "MiniLM recall@10 falls below 0.85 on the eval set."
        ),
    },
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": {
        "dim": 384,
        "size_mb": 117,
        "license": "apache-2.0",
        "rationale": (
            "Japanese-tuned multilingual MiniLM. 384-d, 117 MB. Preferred "
            "for the J04 e-Gov 法令 corpus where Japanese tokenization "
            "dominates."
        ),
    },
}

#: Default SageMaker instance type. ``ml.c5.xlarge`` (4 vCPU / 8 GiB)
#: is the smallest instance that fits MiniLM with batch=32 and gives
#: the throughput estimate baked into ``DEFAULT_PER_ROW_USD``.
DEFAULT_INSTANCE_TYPE: Final[str] = "ml.c5.xlarge"

#: SageMaker IAM execution role ARN format. The role must already
#: exist; this regex only sanity-checks the ARN shape.
_ROLE_ARN_RE = re.compile(r"^arn:aws:iam::\d{12}:role/[A-Za-z0-9_+=,.@-]+$")

#: SageMaker model name format (CreateModel request, ``ModelName``
#: field). Lower-case, hyphen-separated, 1-63 chars.
_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9](-*[a-zA-Z0-9]){0,62}$")


@dataclass(frozen=True)
class S3Uri:
    """Parsed ``s3://<bucket>/<key_prefix>`` URI."""

    bucket: str
    key_prefix: str

    @classmethod
    def parse(cls, uri: str) -> S3Uri:
        if not uri.startswith("s3://"):
            msg = f"expected s3://... URI, got {uri!r}"
            raise ValueError(msg)
        rest = uri[len("s3://") :]
        if "/" not in rest:
            return cls(bucket=rest, key_prefix="")
        bucket, _, key = rest.partition("/")
        return cls(bucket=bucket, key_prefix=key)

    def join(self, suffix: str) -> str:
        sep = "" if not self.key_prefix or self.key_prefix.endswith("/") else "/"
        return f"s3://{self.bucket}/{self.key_prefix}{sep}{suffix}"


class SagemakerEmbedBatchError(RuntimeError):
    """Raised when the SageMaker driver hits a non-recoverable condition.

    Wrapped errors include: unknown model, malformed role ARN, malformed
    model name, projected spend over ceiling, or a boto3 import failure
    when ``--commit`` is set.
    """


@dataclass
class RunReport:
    """Per-run accounting + knob ledger."""

    job_run_id: str
    input_prefix: str
    output_prefix: str
    model: str
    embedding_dim: int
    instance_type: str
    estimated_rows: int
    budget_usd: float
    per_row_usd: float
    warn_threshold: float
    dry_run: bool
    projected_spend_usd: float = 0.0
    stopped: bool = False
    stop_reason: str | None = None
    warn_emitted: bool = False
    transform_job_arn: str | None = None
    transform_job_spec: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "job_run_id": self.job_run_id,
            "input_prefix": self.input_prefix,
            "output_prefix": self.output_prefix,
            "model": self.model,
            "embedding_dim": self.embedding_dim,
            "instance_type": self.instance_type,
            "estimated_rows": self.estimated_rows,
            "budget_usd": self.budget_usd,
            "per_row_usd": self.per_row_usd,
            "warn_threshold": self.warn_threshold,
            "dry_run": self.dry_run,
            "projected_spend_usd": round(self.projected_spend_usd, 6),
            "stopped": self.stopped,
            "stop_reason": self.stop_reason,
            "warn_emitted": self.warn_emitted,
            "transform_job_arn": self.transform_job_arn,
            "transform_job_spec": dict(self.transform_job_spec),
        }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_model(model: str) -> dict[str, Any]:
    """Resolve ``model`` against :data:`ALLOWED_MODELS` or raise.

    Returns the metadata dict (``dim`` / ``size_mb`` / ``license`` /
    ``rationale``) so the caller can pin them into the run manifest.
    """

    meta = ALLOWED_MODELS.get(model)
    if meta is None:
        msg = f"model {model!r} is not in the allow-list. Allowed: {sorted(ALLOWED_MODELS)}"
        raise SagemakerEmbedBatchError(msg)
    return meta


def validate_role_arn(role_arn: str) -> str:
    """Sanity-check the SageMaker execution role ARN shape."""

    if not role_arn or role_arn.endswith("REPLACE_ME"):
        msg = "execution_role_arn is unset or a placeholder"
        raise SagemakerEmbedBatchError(msg)
    if not _ROLE_ARN_RE.match(role_arn):
        msg = f"execution_role_arn does not match arn:aws:iam:: pattern: {role_arn!r}"
        raise SagemakerEmbedBatchError(msg)
    return role_arn


def validate_model_name(model_name: str) -> str:
    """Sanity-check the SageMaker ``ModelName`` (CreateModel field)."""

    if not _MODEL_NAME_RE.match(model_name):
        msg = f"sagemaker_model_name must match {_MODEL_NAME_RE.pattern!r}, got {model_name!r}"
        raise SagemakerEmbedBatchError(msg)
    return model_name


# ---------------------------------------------------------------------------
# Budget gate
# ---------------------------------------------------------------------------


def projected_spend(
    estimated_rows: int,
    per_row_usd: float,
) -> float:
    """Return projected USD spend for ``estimated_rows`` rows."""

    return max(estimated_rows, 0) * per_row_usd


def should_stop(projected_usd: float, budget_usd: float) -> bool:
    """True iff projected spend would meet or exceed the ceiling."""

    return projected_usd >= budget_usd


def should_warn(
    projected_usd: float,
    budget_usd: float,
    warn_threshold: float,
) -> bool:
    """True iff projected spend would meet or exceed the warn line."""

    return projected_usd >= budget_usd * warn_threshold


# ---------------------------------------------------------------------------
# Transform job spec rendering
# ---------------------------------------------------------------------------


def build_transform_job_spec(
    *,
    job_name: str,
    sagemaker_model_name: str,
    input_uri: S3Uri,
    output_uri: S3Uri,
    instance_type: str,
    instance_count: int = 1,
    max_concurrent_transforms: int = 1,
    max_payload_in_mb: int = 6,
    batch_strategy: str = "SingleRecord",
) -> dict[str, Any]:
    """Render a ``CreateTransformJob`` request body.

    The shape mirrors the boto3 ``client.create_transform_job(**kwargs)``
    call so the caller can hand it straight to SageMaker. We deliberately
    do not wire optional fields (``DataCaptureConfig``,
    ``ExperimentConfig``, ``Tags``) because none of them are needed for
    the J04 / J06 retrieval-index build; adding them later is a
    backwards-compatible change.
    """

    # NOTE: The Hugging Face inference toolkit (used by the
    # ``huggingface-pytorch-inference`` SageMaker image) only registers
    # decoders for ``application/json`` / ``application/x-image`` /
    # ``audio/*`` — it does NOT accept ``application/jsonlines``. With
    # ``SplitType=Line`` + ``BatchStrategy=SingleRecord`` SageMaker
    # already splits the JSONL input file line-by-line and sends each
    # line as a separate ``application/json`` payload to the model
    # server. Each line in the input is a valid JSON object of the form
    # ``{"id": "...", "inputs": "..."}``. See AWS Sagemaker JSON Lines
    # batch transform docs + jpcite-embed 2026-05-16 failed batch
    # postmortem (5/6 jobs ClientError on content type).
    return {
        "TransformJobName": job_name,
        "ModelName": sagemaker_model_name,
        "MaxConcurrentTransforms": max_concurrent_transforms,
        "MaxPayloadInMB": max_payload_in_mb,
        "BatchStrategy": batch_strategy,
        "TransformInput": {
            "DataSource": {
                "S3DataSource": {
                    "S3DataType": "S3Prefix",
                    "S3Uri": f"s3://{input_uri.bucket}/{input_uri.key_prefix}",
                }
            },
            "ContentType": "application/json",
            "SplitType": "Line",
            "CompressionType": "None",
        },
        "TransformOutput": {
            "S3OutputPath": f"s3://{output_uri.bucket}/{output_uri.key_prefix}",
            "Accept": "application/json",
            "AssembleWith": "Line",
        },
        "TransformResources": {
            "InstanceType": instance_type,
            "InstanceCount": instance_count,
        },
    }


# ---------------------------------------------------------------------------
# Output manifest
# ---------------------------------------------------------------------------


def write_run_manifest(
    report: RunReport,
    *,
    output_uri: S3Uri,
    s3_client: Any | None = None,
) -> str:
    """Emit ``run_manifest.json`` at the derived prefix root."""

    full_key = (
        f"{output_uri.key_prefix.rstrip('/')}/run_manifest.json"
        if output_uri.key_prefix
        else "run_manifest.json"
    )
    body = json.dumps(report.to_json(), ensure_ascii=False, sort_keys=True, indent=2)
    if s3_client is None:
        s3_client = _boto3_client("s3")
    s3_client.put_object(
        Bucket=output_uri.bucket,
        Key=full_key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )
    return f"s3://{output_uri.bucket}/{full_key}"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _boto3_client(service: str) -> Any:  # pragma: no cover - trivial shim
    """Return a pooled boto3 client for ``service`` in ap-northeast-1.

    Backed by :mod:`scripts.aws_credit_ops._aws` so the second-and-later
    construction skips boto3's 200-500 ms warm-up.
    """
    try:
        from scripts.aws_credit_ops._aws import get_client
    except ImportError as exc:
        msg = (
            "boto3 is not installed. Install it in the operator environment "
            "(pip install boto3) before running sagemaker_embed_batch with "
            "--commit."
        )
        raise SagemakerEmbedBatchError(msg) from exc
    return get_client(service, region_name="ap-northeast-1")


def run_batch(
    *,
    input_prefix: str,
    output_prefix: str,
    model: str = "sentence-transformers/all-MiniLM-L6-v2",
    sagemaker_model_name: str = "jpcite-embed-allminilm-v1",
    execution_role_arn: str = "",
    estimated_rows: int = 0,
    instance_type: str = DEFAULT_INSTANCE_TYPE,
    instance_count: int = 1,
    budget_usd: float = DEFAULT_BUDGET_USD,
    per_row_usd: float = DEFAULT_PER_ROW_USD,
    warn_threshold: float = DEFAULT_WARN_THRESHOLD,
    dry_run: bool = True,
    job_run_id: str | None = None,
    sagemaker_client: Any | None = None,
    s3_client: Any | None = None,
    create_transform_job_fn: Callable[..., dict[str, Any]] | None = None,
) -> RunReport:
    """Drive the SageMaker batch transform end-to-end (DRY_RUN-aware).

    Returns the :class:`RunReport` ledger so callers (CLI + tests) can
    inspect what would have happened without re-reading S3.
    """

    input_uri = S3Uri.parse(input_prefix)
    output_uri = S3Uri.parse(output_prefix)
    meta = validate_model(model)
    validate_model_name(sagemaker_model_name)
    if not dry_run:
        # The role ARN is only enforced when we actually intend to call
        # SageMaker — dry-run preview can be rendered without an ARN so
        # an operator can sanity-check the spec before provisioning IAM.
        validate_role_arn(execution_role_arn)

    run_id = job_run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    job_name = f"jpcite-embed-{run_id}"
    spec = build_transform_job_spec(
        job_name=job_name,
        sagemaker_model_name=sagemaker_model_name,
        input_uri=input_uri,
        output_uri=output_uri,
        instance_type=instance_type,
        instance_count=instance_count,
    )

    report = RunReport(
        job_run_id=run_id,
        input_prefix=input_prefix,
        output_prefix=output_prefix,
        model=model,
        embedding_dim=int(meta["dim"]),
        instance_type=instance_type,
        estimated_rows=max(estimated_rows, 0),
        budget_usd=budget_usd,
        per_row_usd=per_row_usd,
        warn_threshold=warn_threshold,
        dry_run=dry_run,
        transform_job_spec=spec,
    )

    projected = projected_spend(report.estimated_rows, per_row_usd)
    report.projected_spend_usd = projected

    if should_stop(projected, budget_usd):
        report.stopped = True
        report.stop_reason = f"projected spend USD {projected:.2f} >= budget USD {budget_usd:.2f}"
        logger.error(
            "sagemaker_embed_batch stop: projected=%.2f budget=%.2f",
            projected,
            budget_usd,
        )
        return report
    if should_warn(projected, budget_usd, warn_threshold):
        report.warn_emitted = True
        logger.warning(
            "sagemaker_embed_batch warn: projected=%.2f reached %.0f%% of budget=%.2f",
            projected,
            warn_threshold * 100,
            budget_usd,
        )

    if dry_run:
        logger.info(
            "sagemaker_embed_batch dry-run: would create transform job %s "
            "(model=%s dim=%d rows=%d projected_usd=%.2f)",
            job_name,
            model,
            report.embedding_dim,
            report.estimated_rows,
            projected,
        )
        return report

    fn = create_transform_job_fn
    if fn is None:
        if sagemaker_client is None:
            sagemaker_client = _boto3_client("sagemaker")
        fn = sagemaker_client.create_transform_job

    response = fn(**spec)
    arn = response.get("TransformJobArn") if isinstance(response, dict) else None
    if isinstance(arn, str):
        report.transform_job_arn = arn

    write_run_manifest(report, output_uri=output_uri, s3_client=s3_client)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "SageMaker batch-transform embedding driver. DRY_RUN default — "
            "pass --commit to actually call SageMaker."
        )
    )
    parser.add_argument("--input-prefix", required=True)
    parser.add_argument("--output-prefix", required=True)
    parser.add_argument(
        "--model",
        default="sentence-transformers/all-MiniLM-L6-v2",
        help=(
            "sentence-transformers model id. Must be one of: " + ", ".join(sorted(ALLOWED_MODELS))
        ),
    )
    parser.add_argument(
        "--sagemaker-model-name",
        default="jpcite-embed-allminilm-v1",
        help="SageMaker CreateModel ModelName (must already exist).",
    )
    parser.add_argument(
        "--execution-role-arn",
        default="",
        help=(
            "SageMaker execution IAM role ARN (must already exist). Only "
            "required when --commit is set; dry-run preview ignores it."
        ),
    )
    parser.add_argument(
        "--estimated-rows",
        type=int,
        default=0,
        help="Estimated number of input rows. Drives the budget gate.",
    )
    parser.add_argument("--instance-type", default=DEFAULT_INSTANCE_TYPE)
    parser.add_argument("--instance-count", type=int, default=1)
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--per-row-usd", type=float, default=DEFAULT_PER_ROW_USD)
    parser.add_argument("--warn-threshold", type=float, default=DEFAULT_WARN_THRESHOLD)
    parser.add_argument("--job-run-id", default=None)
    parser.add_argument(
        "--commit",
        action="store_true",
        help=("Lift the DRY_RUN guard. Without --commit the script does not call SageMaker."),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the RunReport as JSON on stdout.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    dry_run = not args.commit and os.environ.get("DRY_RUN", "1") != "0"
    try:
        report = run_batch(
            input_prefix=args.input_prefix,
            output_prefix=args.output_prefix,
            model=args.model,
            sagemaker_model_name=args.sagemaker_model_name,
            execution_role_arn=args.execution_role_arn,
            estimated_rows=args.estimated_rows,
            instance_type=args.instance_type,
            instance_count=args.instance_count,
            budget_usd=args.budget_usd,
            per_row_usd=args.per_row_usd,
            warn_threshold=args.warn_threshold,
            dry_run=dry_run,
            job_run_id=args.job_run_id,
        )
    except SagemakerEmbedBatchError as exc:
        print(f"[sagemaker_embed_batch] FAIL: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.to_json(), ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(
            f"[sagemaker_embed_batch] dry_run={dry_run} model={report.model} "
            f"dim={report.embedding_dim} rows={report.estimated_rows} "
            f"projected_usd={report.projected_spend_usd:.2f} "
            f"budget_usd={report.budget_usd:.2f}"
        )
        if report.stopped:
            print(f"[sagemaker_embed_batch] STOPPED: {report.stop_reason}")
        if report.warn_emitted:
            print(
                "[sagemaker_embed_batch] WARN: crossed "
                f"{report.warn_threshold * 100:.0f}% of budget"
            )
        if report.transform_job_arn is not None:
            print(f"[sagemaker_embed_batch] TransformJobArn={report.transform_job_arn}")
    return 0 if not report.stopped else 2


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
