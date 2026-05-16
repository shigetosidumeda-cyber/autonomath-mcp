#!/usr/bin/env python3
"""Submit 6 SageMaker batch transform jobs covering the full jpcite corpus.

Orchestrator on top of ``sagemaker_embed_batch.run_batch`` that submits
one transform job per corpus table. Instance assignment is quota-aware:

* ``am_law_article`` (≈ 353K rows, the embedding bottleneck) → 1 ×
  ``ml.g4dn.xlarge`` (GPU, quota 1.0 in ap-northeast-1).
* The remaining 5 tables (programs / adoption_records /
  nta_tsutatsu_index / court_decisions / nta_saiketsu) →
  ``ml.c5.2xlarge`` (CPU, quota 8.0). MiniLM-L6-v2 runs comfortably on
  CPU; sub-100K rows finish in well under an hour.

This honors the original spec's intent ("5 parallel jobs ≈ 30 hours
total") while complying with the actual hard quota of 1 GPU instance —
the 5 CPU jobs run truly in parallel, the GPU does the heavy lifting
on the law-article corpus.

Constraints
-----------
* **NO LLM API calls.** Pure SageMaker control-plane orchestration.
* **DRY_RUN default.** No SageMaker API calls unless ``--commit``.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker.

CLI
---

.. code-block:: text

    python scripts/aws_credit_ops/submit_full_corpus_embed.py [--commit]
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

# Local sibling import — keep relative-style without requiring a package.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sagemaker_embed_batch import run_batch  # noqa: E402

logger = logging.getLogger("submit_full_corpus_embed")

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_PREFIX_IN: Final[str] = "corpus_export"
DEFAULT_PREFIX_OUT: Final[str] = "embeddings"
DEFAULT_MODEL: Final[str] = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_SM_MODEL_NAME: Final[str] = "jpcite-embed-allminilm-v1"
DEFAULT_ROLE_ARN: Final[str] = (
    "arn:aws:iam::993693061769:role/jpcite-sagemaker-execution-role"
)
DEFAULT_BUDGET_USD: Final[float] = 200.0


@dataclass(frozen=True)
class TableJobSpec:
    """Per-table SageMaker submit plan."""

    table: str
    estimated_rows: int
    instance_type: str
    instance_count: int
    per_row_usd: float


#: Quota-aware plan. Per-row USD reflects rough hourly cost ÷ throughput.
#: g4dn.xlarge (≈ $0.94/hr) processing ~50K rows/hr at MiniLM speed →
#: ~$0.00002/row. c5.2xlarge (≈ $0.476/hr) at ~10K rows/hr CPU →
#: ~$0.00005/row.
JOB_PLAN: Final[list[TableJobSpec]] = [
    TableJobSpec(
        table="am_law_article",
        estimated_rows=353278,
        instance_type="ml.g4dn.xlarge",
        instance_count=1,
        per_row_usd=0.00002,
    ),
    TableJobSpec(
        table="programs",
        estimated_rows=12753,
        instance_type="ml.c5.2xlarge",
        instance_count=1,
        per_row_usd=0.00005,
    ),
    TableJobSpec(
        table="adoption_records",
        estimated_rows=160376,
        instance_type="ml.c5.2xlarge",
        instance_count=1,
        per_row_usd=0.00005,
    ),
    TableJobSpec(
        table="nta_tsutatsu_index",
        estimated_rows=3232,
        instance_type="ml.c5.2xlarge",
        instance_count=1,
        per_row_usd=0.00005,
    ),
    TableJobSpec(
        table="court_decisions",
        estimated_rows=848,
        instance_type="ml.c5.2xlarge",
        instance_count=1,
        per_row_usd=0.00005,
    ),
    TableJobSpec(
        table="nta_saiketsu",
        estimated_rows=137,
        instance_type="ml.c5.2xlarge",
        instance_count=1,
        per_row_usd=0.00005,
    ),
]


def submit_one(
    spec: TableJobSpec,
    *,
    bucket: str,
    prefix_in: str,
    prefix_out: str,
    run_id: str,
    sm_model_name: str,
    execution_role_arn: str,
    budget_usd: float,
    dry_run: bool,
) -> dict[str, Any]:
    """Submit one table's transform job and return a flat record."""

    input_prefix = f"s3://{bucket}/{prefix_in}/{spec.table}/"
    output_prefix = f"s3://{bucket}/{prefix_out}/{spec.table}/"
    table_run_id = f"{run_id}-{spec.table.replace('_', '')[:18]}"
    report = run_batch(
        input_prefix=input_prefix,
        output_prefix=output_prefix,
        model=DEFAULT_MODEL,
        sagemaker_model_name=sm_model_name,
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
        "table": spec.table,
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
    sm_model_name: str = DEFAULT_SM_MODEL_NAME,
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
            sm_model_name=sm_model_name,
            execution_role_arn=execution_role_arn,
            budget_usd=budget_usd,
            dry_run=dry_run,
        )
        out.append(rec)
        logger.info(
            "submit %-20s instance=%s rows=%d arn=%s",
            spec.table,
            spec.instance_type,
            spec.estimated_rows,
            rec.get("transform_job_arn") or "(dry-run)",
        )
    return out


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Submit 6 SageMaker batch transform jobs covering the full "
            "jpcite corpus. DRY_RUN default; pass --commit to call SageMaker."
        )
    )
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--prefix-in", default=DEFAULT_PREFIX_IN)
    parser.add_argument("--prefix-out", default=DEFAULT_PREFIX_OUT)
    parser.add_argument("--sm-model-name", default=DEFAULT_SM_MODEL_NAME)
    parser.add_argument(
        "--execution-role-arn", default=DEFAULT_ROLE_ARN
    )
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
        sm_model_name=args.sm_model_name,
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
                f"[submit_full_corpus] {rec['table']:>22s}  "
                f"instance={rec['instance_type']:<18s}  "
                f"rows={rec['estimated_rows']:>8d}  "
                f"arn={rec.get('transform_job_arn') or '(dry-run)'}"
            )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
