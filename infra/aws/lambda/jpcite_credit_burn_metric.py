"""Lambda handler — real-time burn-metric emitter for jpcite credit run.

Triggered every 5 minutes by an EventBridge rule (``rate(5 minutes)``).
On each invocation:

1. Polls Cost Explorer (``us-east-1`` endpoint) for month-to-date
   ``UnblendedCost`` in USD.
2. Computes an hourly burn rate by dividing the consumed amount by the
   hours elapsed since the first instant of the current UTC month.
3. Classifies the burn into ``RAMP`` / ``SLOWDOWN`` / ``STOP`` using
   percentage-of-target thresholds (85% / 95%) **and** an absolute
   hourly STOP line (default ``$500/hr``).
4. Emits two CloudWatch ``PutMetricData`` series under the
   ``jpcite/credit`` namespace:

   - ``GrossSpendUSD``    (scalar, USD)
   - ``HourlyBurnRate``   (scalar, USD/hr)

   Both metrics carry a single ``Classification`` dimension so the
   dashboard widget can colour-code RAMP / SLOWDOWN / STOP.

5. Publishes an SNS alert when the hourly burn rate crosses the
   ``--hourly-alert`` threshold (default ``$500/hr``).

SAFETY model
============
- The ``JPCITE_BURN_METRIC_ENABLED`` env var gates every side-effecting
  API call. When it is anything other than the literal ``"true"``
  (case-insensitive), the handler logs the *would-emit* envelope and
  returns ``mode="dry_run"`` without touching CloudWatch or SNS.
- Default value is ``"false"`` — the operator opts in explicitly.
- The dry-run code path **still** queries Cost Explorer (read-only) so
  the attestation event contains the exact metric values that *would
  have* been emitted. This makes review possible before flipping live.

The handler module is intentionally self-contained: the deploy script
zips this single file alongside the runtime copy of
``scripts/aws_credit_ops/emit_burn_metric.py`` so the Lambda
``Handler`` can resolve as ``jpcite_credit_burn_metric.lambda_handler``
without any cross-package imports.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Final, cast

import boto3  # type: ignore[import-not-found]

# ----------------------------------------------------------------------------
# Resolve the shared emit_burn_metric module. The deploy script copies
# both files to the Lambda zip root so they sit side-by-side at runtime.
# ----------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import emit_burn_metric  # noqa: E402

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION: Final[str] = os.environ.get("AWS_REGION", "us-east-1")
METRIC_REGION: Final[str] = os.environ.get(
    "JPCITE_BURN_METRIC_REGION", emit_burn_metric.DEFAULT_METRIC_REGION
)
CE_REGION: Final[str] = os.environ.get("JPCITE_CE_REGION", emit_burn_metric.DEFAULT_CE_REGION)
SNS_TOPIC_ARN: Final[str] = os.environ.get(
    "JPCITE_ATTESTATION_TOPIC_ARN", emit_burn_metric.DEFAULT_SNS_TOPIC_ARN
)


def _enabled() -> bool:
    """Return True only when ``JPCITE_BURN_METRIC_ENABLED=true``."""

    return os.environ.get("JPCITE_BURN_METRIC_ENABLED", "false").strip().lower() == "true"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("invalid float env var %s=%r — using default %s", name, raw, default)
        return default


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    """EventBridge entry point. Receives a fixed-shape scheduled event."""

    started_at = time.time()
    live = _enabled()
    mode = "live" if live else "dry_run"
    logger.info(
        "jpcite_credit_burn_metric invoked mode=%s metric_region=%s ce_region=%s",
        mode,
        METRIC_REGION,
        CE_REGION,
    )

    target_usd = _env_float("JPCITE_CREDIT_TARGET_USD", emit_burn_metric.DEFAULT_TARGET_USD)
    hourly_stop_usd = _env_float(
        "JPCITE_HOURLY_STOP_USD", emit_burn_metric.DEFAULT_HOURLY_STOP_USD
    )
    hourly_alert_usd = _env_float(
        "JPCITE_HOURLY_ALERT_USD", emit_burn_metric.DEFAULT_HOURLY_ALERT_USD
    )
    namespace = os.environ.get("JPCITE_BURN_METRIC_NAMESPACE", emit_burn_metric.DEFAULT_NAMESPACE)

    ce_client = boto3.client("ce", region_name=CE_REGION)
    emission = emit_burn_metric.build_emission(
        ce_client,
        target_usd=target_usd,
        hourly_stop_usd=hourly_stop_usd,
        hourly_alert_usd=hourly_alert_usd,
        namespace=namespace,
        metric_region=METRIC_REGION,
        ce_region=CE_REGION,
    )

    cw_client = boto3.client("cloudwatch", region_name=METRIC_REGION) if live else None
    sns_client = boto3.client("sns", region_name=REGION) if live else None
    result = emit_burn_metric.emit(
        emission,
        cw_client=cast("Any", cw_client),
        sns_client=cast("Any", sns_client),
        sns_topic_arn=SNS_TOPIC_ARN,
        live=live,
    )

    duration_s = round(time.time() - started_at, 3)
    payload: dict[str, Any] = {
        "lambda": "jpcite-credit-burn-metric-emitter",
        "mode": mode,
        "started_at": started_at,
        "duration_s": duration_s,
        "metric_region": METRIC_REGION,
        "ce_region": CE_REGION,
        "namespace": namespace,
        "classification": emission.classification,
        "consumed_usd": emission.consumed_usd,
        "hourly_burn_usd": emission.hourly_burn_usd,
        "breached_hourly_alert": emission.breached_hourly_alert,
        "breached_hourly_stop": emission.breached_hourly_stop,
        "result": result,
        "safety_env": {
            "JPCITE_BURN_METRIC_ENABLED": os.environ.get(
                "JPCITE_BURN_METRIC_ENABLED", "false"
            ),
        },
    }
    logger.info(
        "burn-metric attestation classification=%s consumed=%.2f hourly=%.2f",
        emission.classification,
        emission.consumed_usd,
        emission.hourly_burn_usd,
    )
    # Best-effort one-shot log line so the CloudWatch console shows the full
    # envelope without enabling structured logging.
    logger.info("attestation_payload=%s", json.dumps(payload, default=str, ensure_ascii=False))
    return payload
