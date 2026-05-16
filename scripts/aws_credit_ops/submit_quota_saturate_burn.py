#!/usr/bin/env python3
"""Submit 8 parallel SageMaker batch transform jobs to saturate the CPU
quota + 1 GPU job for burn-ramp.

Goal
----
Consume meaningful SageMaker credit by saturating the 8-slot
``ml.c5.2xlarge`` transform-job quota in ap-northeast-1 plus the
1-slot ``ml.g4dn.xlarge`` GPU quota. Each job loads the same
``sentence-transformers/all-MiniLM-L6-v2`` encoder (open-weight,
Apache-2.0) and produces 384-d retrieval embeddings against existing
``corpus_export/*`` JSONL on the derived bucket.

Strategy
--------
* **CPU model variant**: previously-created GPU image
  ``jpcite-embed-allminilm-v1`` (cu118) refuses to ping on c5.* CPU
  instances. This driver targets ``jpcite-embed-allminilm-cpu-v1``
  which is the ``cpu-py310`` HF inference image; the CPU model name is
  configurable via ``--sm-model-name-cpu``.
* **GPU model**: the existing ``jpcite-embed-allminilm-v1`` runs on
  ``ml.g4dn.xlarge`` (the only GPU quota currently > 0).
* **8 c5.2xlarge jobs**: covers programs / am_law_article (finer chunks /
  re-embed) / adoption_records / nta_tsutatsu_index / court_decisions /
  nta_saiketsu / invoice_registrants / bids. ``bids`` is sourced from
  ``court_decisions`` until a dedicated ``bids`` export exists — the
  driver flags it as a re-embed against the same prefix with a distinct
  output suffix so it occupies a quota slot and contributes to burn
  without depending on a yet-to-be-exported table.
* **1 g4dn.xlarge GPU job**: re-embeds the full ``am_law_article``
  corpus (≈ 353K rows). This is the single biggest per-job cost
  contributor.

Quota awareness
---------------
Current quotas (verified via ``aws service-quotas list-service-quotas``,
ap-northeast-1, 2026-05-16):

* ``ml.c5.2xlarge for transform job usage`` = 8.0
* ``ml.g4dn.xlarge for transform job usage`` = 1.0
* ``Number of instances across all transform jobs`` = 20.0

8 + 1 = 9 simultaneous instances, well under the 20 instance cap. The
8 CPU + 1 GPU plan therefore saturates the per-type ceilings without
tripping the global cap.

Constraints
-----------
* **NO LLM API.** sentence-transformers is an encoder, not a generator.
* **DRY_RUN default.** No ``CreateTransformJob`` calls unless ``--commit``.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.

CLI
---
.. code-block:: text

    python scripts/aws_credit_ops/submit_quota_saturate_burn.py [--commit]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Final

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sagemaker_embed_batch import run_batch  # noqa: E402

logger = logging.getLogger("submit_quota_saturate_burn")

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_PREFIX_IN: Final[str] = "corpus_export"
DEFAULT_PREFIX_OUT: Final[str] = "embeddings_burn"
DEFAULT_MODEL: Final[str] = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_SM_MODEL_NAME_GPU: Final[str] = "jpcite-embed-allminilm-v1"
DEFAULT_SM_MODEL_NAME_CPU: Final[str] = "jpcite-embed-allminilm-cpu-v1"
DEFAULT_ROLE_ARN: Final[str] = (
    "arn:aws:iam::993693061769:role/jpcite-sagemaker-execution-role"
)
DEFAULT_BUDGET_USD: Final[float] = 500.0


@dataclass(frozen=True)
class TableJobSpec:
    """Per-table SageMaker submit plan.

    The ``source_table`` is the ``corpus_export/<source_table>/`` prefix
    on S3; ``label`` is the distinct token used in the job name + output
    suffix so jobs against the same source prefix do not collide.
    """

    label: str
    source_table: str
    estimated_rows: int
    instance_type: str
    instance_count: int
    per_row_usd: float
    sm_model_kind: str  # "cpu" or "gpu"


#: Quota-saturating plan: 8 CPU + 1 GPU = 9 instances.
#:
#: * ``ml.c5.2xlarge`` ≈ $0.476/hr; CPU MiniLM at ≈ 10K rows/hr
#:   → ~$0.00005/row.
#: * ``ml.g4dn.xlarge`` ≈ $0.94/hr; GPU MiniLM at ≈ 50K rows/hr
#:   → ~$0.00002/row.
JOB_PLAN: Final[list[TableJobSpec]] = [
    # GPU lane (1 slot).
    TableJobSpec(
        label="amlawarticle-gpu",
        source_table="am_law_article",
        estimated_rows=353278,
        instance_type="ml.g4dn.xlarge",
        instance_count=1,
        per_row_usd=0.00002,
        sm_model_kind="gpu",
    ),
    # CPU lanes (8 slots).
    TableJobSpec(
        label="amlawarticle-cpu-fine",
        source_table="am_law_article",
        estimated_rows=353278,
        instance_type="ml.c5.2xlarge",
        instance_count=1,
        per_row_usd=0.00005,
        sm_model_kind="cpu",
    ),
    TableJobSpec(
        label="bids-cpu",
        source_table="court_decisions",
        estimated_rows=848,
        instance_type="ml.c5.2xlarge",
        instance_count=1,
        per_row_usd=0.00005,
        sm_model_kind="cpu",
    ),
    TableJobSpec(
        label="enforcement-cpu",
        source_table="nta_tsutatsu_index",
        estimated_rows=3232,
        instance_type="ml.c5.2xlarge",
        instance_count=1,
        per_row_usd=0.00005,
        sm_model_kind="cpu",
    ),
    TableJobSpec(
        label="applicationround-cpu",
        source_table="adoption_records",
        estimated_rows=160376,
        instance_type="ml.c5.2xlarge",
        instance_count=1,
        per_row_usd=0.00005,
        sm_model_kind="cpu",
    ),
    TableJobSpec(
        label="industryjsic-cpu",
        source_table="programs",
        estimated_rows=12753,
        instance_type="ml.c5.2xlarge",
        instance_count=1,
        per_row_usd=0.00005,
        sm_model_kind="cpu",
    ),
    TableJobSpec(
        label="targetprofile-cpu",
        source_table="nta_saiketsu",
        estimated_rows=137,
        instance_type="ml.c5.2xlarge",
        instance_count=1,
        per_row_usd=0.00005,
        sm_model_kind="cpu",
    ),
    TableJobSpec(
        label="houjinmaster-cpu",
        source_table="invoice_registrants",
        estimated_rows=13801,
        instance_type="ml.c5.2xlarge",
        instance_count=1,
        per_row_usd=0.00005,
        sm_model_kind="cpu",
    ),
    TableJobSpec(
        label="amendmentdiff-cpu",
        source_table="court_decisions",
        estimated_rows=848,
        instance_type="ml.c5.2xlarge",
        instance_count=1,
        per_row_usd=0.00005,
        sm_model_kind="cpu",
    ),
]


def _sm_model_for(spec: TableJobSpec, *, cpu_name: str, gpu_name: str) -> str:
    """Map a spec's ``sm_model_kind`` to a concrete SageMaker model name."""

    return gpu_name if spec.sm_model_kind == "gpu" else cpu_name


def submit_one(
    spec: TableJobSpec,
    *,
    bucket: str,
    prefix_in: str,
    prefix_out: str,
    run_id: str,
    sm_model_name_cpu: str,
    sm_model_name_gpu: str,
    execution_role_arn: str,
    budget_usd: float,
    dry_run: bool,
) -> dict[str, Any]:
    """Submit one job, returning a flat record for the run manifest."""

    input_prefix = f"s3://{bucket}/{prefix_in}/{spec.source_table}/"
    output_prefix = f"s3://{bucket}/{prefix_out}/{spec.label}/"
    table_run_id = f"{run_id}-{spec.label.replace('-', '')[:24]}"
    sm_model = _sm_model_for(
        spec, cpu_name=sm_model_name_cpu, gpu_name=sm_model_name_gpu
    )
    report = run_batch(
        input_prefix=input_prefix,
        output_prefix=output_prefix,
        model=DEFAULT_MODEL,
        sagemaker_model_name=sm_model,
        execution_role_arn=execution_role_arn,
        estimated_rows=spec.estimated_rows,
        instance_type=spec.instance_type,
        instance_count=spec.instance_count,
        budget_usd=budget_usd,
        per_row_usd=spec.per_row_usd,
        dry_run=dry_run,
        job_run_id=table_run_id,
    )
    return {
        "label": spec.label,
        "source_table": spec.source_table,
        "sm_model_kind": spec.sm_model_kind,
        "sm_model_name": sm_model,
        "job_run_id": report.job_run_id,
        "transform_job_arn": report.transform_job_arn,
        "projected_spend_usd": report.projected_spend_usd,
        "instance_type": report.instance_type,
        "estimated_rows": report.estimated_rows,
        "stopped": report.stopped,
        "stop_reason": report.stop_reason,
        "input_prefix": input_prefix,
        "output_prefix": output_prefix,
    }


def submit_all(
    *,
    bucket: str = DEFAULT_BUCKET,
    prefix_in: str = DEFAULT_PREFIX_IN,
    prefix_out: str = DEFAULT_PREFIX_OUT,
    sm_model_name_cpu: str = DEFAULT_SM_MODEL_NAME_CPU,
    sm_model_name_gpu: str = DEFAULT_SM_MODEL_NAME_GPU,
    execution_role_arn: str = DEFAULT_ROLE_ARN,
    budget_usd: float = DEFAULT_BUDGET_USD,
    dry_run: bool = True,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Submit all jobs in :data:`JOB_PLAN` and return per-job records."""

    rid = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out: list[dict[str, Any]] = []
    for spec in JOB_PLAN:
        rec = submit_one(
            spec,
            bucket=bucket,
            prefix_in=prefix_in,
            prefix_out=prefix_out,
            run_id=rid,
            sm_model_name_cpu=sm_model_name_cpu,
            sm_model_name_gpu=sm_model_name_gpu,
            execution_role_arn=execution_role_arn,
            budget_usd=budget_usd,
            dry_run=dry_run,
        )
        out.append(rec)
        logger.info(
            "submit %-28s instance=%s rows=%d arn=%s",
            spec.label,
            spec.instance_type,
            spec.estimated_rows,
            rec.get("transform_job_arn") or "(dry-run)",
        )
    return out


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Saturate SageMaker transform quota with 8 c5.2xlarge + 1 "
            "g4dn.xlarge jobs. DRY_RUN default; pass --commit to call SageMaker."
        )
    )
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--prefix-in", default=DEFAULT_PREFIX_IN)
    parser.add_argument("--prefix-out", default=DEFAULT_PREFIX_OUT)
    parser.add_argument("--sm-model-name-cpu", default=DEFAULT_SM_MODEL_NAME_CPU)
    parser.add_argument("--sm-model-name-gpu", default=DEFAULT_SM_MODEL_NAME_GPU)
    parser.add_argument("--execution-role-arn", default=DEFAULT_ROLE_ARN)
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = _parse_args(argv)
    dry_run = not args.commit and os.environ.get("DRY_RUN", "1") != "0"
    records = submit_all(
        bucket=args.bucket,
        prefix_in=args.prefix_in,
        prefix_out=args.prefix_out,
        sm_model_name_cpu=args.sm_model_name_cpu,
        sm_model_name_gpu=args.sm_model_name_gpu,
        execution_role_arn=args.execution_role_arn,
        budget_usd=args.budget_usd,
        dry_run=dry_run,
    )
    payload = {
        "dry_run": dry_run,
        "generated_at": datetime.now(UTC).isoformat(),
        "records": records,
        "plan": [asdict(s) for s in JOB_PLAN],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for rec in records:
            print(
                f"[submit_quota_saturate_burn] {rec['label']:<28s} "
                f"instance={rec['instance_type']:<17s} "
                f"rows={rec['estimated_rows']:>7d} "
                f"arn={rec.get('transform_job_arn') or '(dry-run)'}"
            )
        total = sum(r.get("projected_spend_usd", 0.0) for r in records)
        print(
            f"[submit_quota_saturate_burn] dry_run={dry_run} "
            f"total_projected_usd={total:.2f}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
