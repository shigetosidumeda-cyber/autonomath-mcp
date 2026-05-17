"""Lambda handler — lightweight high-TPS canary attestation emitter.

Companion to ``jpcite_credit_canary_attestation.py`` (the heavy Step-Functions
Pass-After-Job hook). The lite variant exists specifically for **mass
invocation** burn lanes (Lane G, 2026-05-17), where the goal is sustained
~11K req/sec invocation rate at 128MB / 100ms to drive Lambda spend toward
the $300/day target while still producing a real audit-log moat.

Design constraints
==================
- **Hot path is sub-100ms.** No boto3 client construction outside module
  load. No CE / Batch / S3 ListObjectsV2 in the hot path.
- **Audit moat = CloudWatch Logs.** Every invoke emits one structured JSON
  log line containing run_id / batch_index / invocation_id / lane / ts.
  CloudWatch Logs retention (default 30 days) + periodic S3 export gives
  the auditor an append-only trail without per-invoke S3 PutObject cost.
- **Sample S3 writes.** ~0.1% of invocations (configurable via
  ``JPCITE_CANARY_LITE_S3_SAMPLE_RATE``) write a compact JSON to the
  attestation bucket so a rolling sample of attestations is queryable
  via Athena / S3 Select for the moat artifact. Defaults to 0 in
  dry-run; flipping ``JPCITE_CANARY_LITE_S3_ENABLED=true`` enables it.
- **No external deps**, no module-level Batch/CE/S3 polls.

Event shape (all optional)::

    {
      "run_id": "lane-g-2026-05-17T07-30Z",
      "lane": "G",
      "batch_index": 1234,
      "invocation_id": "uuid-or-counter",
      "client_tag": "lambda-burn-driver"
    }

Response shape::

    {
      "lambda": "jpcite-credit-canary-attestation-lite",
      "mode": "live" | "dry",
      "run_id": ...,
      "lane": ...,
      "duration_ms": float,
      "s3_sampled": bool,
      "audit_log_line": str  # the JSON we just logged
    }
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import random
import time
import uuid
from typing import Any, Final

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION: Final[str] = os.environ.get("AWS_REGION", "ap-northeast-1")
ATTESTATION_BUCKET: Final[str] = os.environ.get(
    "JPCITE_CANARY_ATTESTATION_BUCKET",
    "jpcite-credit-993693061769-202605-reports",
)
LITE_S3_ENABLED_RAW: Final[str] = os.environ.get("JPCITE_CANARY_LITE_S3_ENABLED", "false")
LITE_S3_SAMPLE_RATE_RAW: Final[str] = os.environ.get(
    "JPCITE_CANARY_LITE_S3_SAMPLE_RATE",
    "0.001",  # 0.1%
)

try:
    LITE_S3_SAMPLE_RATE: Final[float] = max(0.0, min(1.0, float(LITE_S3_SAMPLE_RATE_RAW)))
except ValueError:
    LITE_S3_SAMPLE_RATE = 0.001  # type: ignore[misc]


def _lite_s3_enabled() -> bool:
    return LITE_S3_ENABLED_RAW.strip().lower() == "true"


# Module-load: construct boto3 S3 client once. Reused across warm invocations.
_S3_CLIENT = boto3.client("s3", region_name=REGION)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    started = time.time()
    now = dt.datetime.now(dt.UTC)

    run_id = str(event.get("run_id") or now.strftime("lane-g-%Y%m%dT%H%M%SZ"))
    lane = str(event.get("lane") or "G")
    batch_index = int(event.get("batch_index") or 0)
    invocation_id = str(event.get("invocation_id") or uuid.uuid4().hex)
    client_tag = str(event.get("client_tag") or "lambda-burn-driver")

    audit_record: dict[str, Any] = {
        "schema": "jpcite.canary_attestation_lite.v1",
        "lambda": "jpcite-credit-canary-attestation-lite",
        "ts": now.isoformat(),
        "run_id": run_id,
        "lane": lane,
        "batch_index": batch_index,
        "invocation_id": invocation_id,
        "client_tag": client_tag,
        "region": REGION,
    }
    audit_line = json.dumps(audit_record, ensure_ascii=False)
    # Single JSON log line per invocation — CloudWatch Logs is the canonical
    # audit moat. Standard logger emits to /aws/lambda/<fn> log group.
    logger.info("CANARY_ATTESTATION_LITE %s", audit_line)

    s3_sampled = False
    s3_enabled = _lite_s3_enabled()
    if s3_enabled and random.random() < LITE_S3_SAMPLE_RATE:
        s3_key = (
            f"canary-attestation-lite/{now.strftime('%Y/%m/%d/%H')}/"
            f"lane={lane}/{invocation_id}.json"
        )
        try:
            _S3_CLIENT.put_object(
                Bucket=ATTESTATION_BUCKET,
                Key=s3_key,
                Body=audit_line.encode("utf-8"),
                ContentType="application/json",
            )
            s3_sampled = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("s3 sample upload failed: %s", exc)

    duration_ms = round((time.time() - started) * 1000, 2)
    payload: dict[str, Any] = {
        "lambda": "jpcite-credit-canary-attestation-lite",
        "mode": "live" if s3_enabled else "dry",
        "run_id": run_id,
        "lane": lane,
        "batch_index": batch_index,
        "invocation_id": invocation_id,
        "duration_ms": duration_ms,
        "s3_sampled": s3_sampled,
        "audit_log_line": audit_line,
    }
    return payload
