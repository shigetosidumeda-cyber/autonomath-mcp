"""Lambda handler — live AWS canary attestation emitter for jpcite credit run.

Wired into the Step Functions orchestrator as a Pass-After-Job hook so that
**after each execution batch** the orchestrator invokes this Lambda, which
in turn polls Batch / Cost Explorer / S3 and writes an attestation JSON to
the reports bucket. The local-write path is handled by the operator-side
CLI; the Lambda only writes to S3 (read/write to ``site/releases/current/``
is not available from a Lambda execution context).

Safety model
============
- ``JPCITE_CANARY_ATTESTATION_ENABLED`` env var defaults to ``"false"``.
- ``JPCITE_CANARY_LIVE_UPLOAD`` env var defaults to ``"false"``. Even when
  ``JPCITE_CANARY_ATTESTATION_ENABLED=true``, the S3 PutObject only fires
  when ``JPCITE_CANARY_LIVE_UPLOAD=true`` — mirrors the Stream W concern
  separation pattern (Wave 50 tick 8).
- The handler module is intentionally self-contained: the deploy script
  zips this single file alongside the runtime copy of
  ``scripts/aws_credit_ops/emit_canary_attestation.py``.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final, cast

import boto3

# ----------------------------------------------------------------------------
# Resolve the shared emit_canary_attestation module. The deploy script copies
# both files to the Lambda zip root so they sit side-by-side at runtime.
# ----------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import emit_canary_attestation  # type: ignore[import-not-found] # noqa: E402

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION: Final[str] = os.environ.get("AWS_REGION", "ap-northeast-1")
BATCH_REGION: Final[str] = os.environ.get(
    "JPCITE_BATCH_REGION", emit_canary_attestation.DEFAULT_BATCH_REGION
)
S3_REGION: Final[str] = os.environ.get(
    "JPCITE_S3_REGION", emit_canary_attestation.DEFAULT_S3_REGION
)
CE_REGION: Final[str] = os.environ.get(
    "JPCITE_CE_REGION", emit_canary_attestation.DEFAULT_CE_REGION
)
JOB_QUEUE: Final[str] = os.environ.get(
    "JPCITE_CANARY_BATCH_QUEUE_ARN",
    "arn:aws:batch:ap-northeast-1:993693061769:job-queue/jpcite-credit-fargate-spot-short-queue",
)
JOB_PREFIX: Final[str] = os.environ.get(
    "JPCITE_CANARY_BATCH_JOB_PREFIX", emit_canary_attestation.DEFAULT_BATCH_JOB_PREFIX
)
RAW_BUCKET: Final[str] = os.environ.get(
    "JPCITE_CANARY_RAW_BUCKET", emit_canary_attestation.DEFAULT_RAW_BUCKET
)
DERIVED_BUCKET: Final[str] = os.environ.get(
    "JPCITE_CANARY_DERIVED_BUCKET", emit_canary_attestation.DEFAULT_DERIVED_BUCKET
)
ATTESTATION_BUCKET: Final[str] = os.environ.get(
    "JPCITE_CANARY_ATTESTATION_BUCKET", emit_canary_attestation.DEFAULT_REPORTS_BUCKET
)


def _enabled() -> bool:
    return (
        os.environ.get("JPCITE_CANARY_ATTESTATION_ENABLED", "false").strip().lower() == "true"
    )


def _live_upload() -> bool:
    return os.environ.get("JPCITE_CANARY_LIVE_UPLOAD", "false").strip().lower() == "true"


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    """Step Functions / EventBridge entry point.

    Accepted event keys (all optional):
      - run_id        — Step Functions execution name, falls through to ISO now.
      - started_at    — ISO-8601 canary run start, falls through to now-30min.
      - current_status — one of PRE_RUN / IN_PROGRESS / RAMP / STEADY / COOLDOWN
                         / COMPLETED / FAILED.
    """

    started_invoke = time.time()
    enabled = _enabled()
    live_upload = enabled and _live_upload()
    mode = "live" if live_upload else ("env_enabled_local_only" if enabled else "dry_run")

    run_id = str(
        event.get("run_id")
        or os.environ.get("JPCITE_CANARY_RUN_ID")
        or dt.datetime.now(dt.UTC).strftime("canary-%Y%m%dT%H%M%SZ")
    )
    current_status = str(event.get("current_status") or "IN_PROGRESS")
    started_at_str = str(event.get("started_at") or "")
    if started_at_str:
        try:
            started_at = dt.datetime.fromisoformat(started_at_str)
        except ValueError:
            started_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=30)
    else:
        started_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=30)

    batch_client = boto3.client("batch", region_name=BATCH_REGION)
    ce_client = boto3.client("ce", region_name=CE_REGION)
    s3_client = boto3.client("s3", region_name=S3_REGION)

    try:
        jobs = emit_canary_attestation.poll_batch_jobs(
            cast("Any", batch_client),
            job_queue=JOB_QUEUE,
            job_name_prefix=JOB_PREFIX,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("batch poll failed: %s", exc)
        jobs = emit_canary_attestation.BatchJobsRollup.empty()

    try:
        cost = emit_canary_attestation.poll_cost_explorer(cast("Any", ce_client))
    except Exception as exc:  # noqa: BLE001
        logger.warning("ce poll failed: %s", exc)
        cost = (0.0, "", "")

    try:
        artifacts = emit_canary_attestation.poll_artifact_counts(
            cast("Any", s3_client),
            raw_bucket=RAW_BUCKET,
            derived_bucket=DERIVED_BUCKET,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("s3 poll failed: %s", exc)
        artifacts = emit_canary_attestation.ArtifactCounts(
            raw_objects=0,
            derived_objects=0,
            raw_bucket=RAW_BUCKET,
            derived_bucket=DERIVED_BUCKET,
            sampled=False,
        )

    attestation = emit_canary_attestation.build_attestation(
        run_id=run_id,
        started_at=started_at,
        jobs=jobs,
        cost=cost,
        artifacts=artifacts,
        batch_region=BATCH_REGION,
        s3_region=S3_REGION,
        ce_region=CE_REGION,
        current_status=current_status,
        live_aws_commands_executed=live_upload,
    )

    upload_log = emit_canary_attestation.upload_attestation(
        attestation,
        s3_client=cast("Any", s3_client),
        bucket=ATTESTATION_BUCKET,
        live=live_upload,
    )

    duration_s = round(time.time() - started_invoke, 3)
    payload: dict[str, Any] = {
        "lambda": "jpcite-credit-canary-attestation-emitter",
        "mode": mode,
        "duration_s": duration_s,
        "run_id": run_id,
        "current_status": current_status,
        "succeeded": jobs.succeeded,
        "failed": jobs.failed,
        "running": jobs.running,
        "cost_usd": cost[0],
        "raw_objects": artifacts.raw_objects,
        "derived_objects": artifacts.derived_objects,
        "attestation": asdict(attestation),
        "upload_action": upload_log,
        "safety_env": {
            "JPCITE_CANARY_ATTESTATION_ENABLED": os.environ.get(
                "JPCITE_CANARY_ATTESTATION_ENABLED", "false"
            ),
            "JPCITE_CANARY_LIVE_UPLOAD": os.environ.get(
                "JPCITE_CANARY_LIVE_UPLOAD", "false"
            ),
        },
    }
    logger.info(
        "canary-attestation mode=%s run_id=%s succeeded=%d failed=%d running=%d cost=%.2f",
        mode,
        run_id,
        jobs.succeeded,
        jobs.failed,
        jobs.running,
        cost[0],
    )
    logger.info("attestation_payload=%s", json.dumps(payload, default=str, ensure_ascii=False))
    return payload
