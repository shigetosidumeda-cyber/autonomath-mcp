"""Lambda handler — hourly burn rate monitor for jpcite credit run (Lane J).

Triggered every 1 hour by an EventBridge rule (``rate(1 hour)``).
On each invocation:

1. Polls Cost Explorer (``us-east-1`` endpoint) for:
   - 24h-rolling Usage records (RECORD_TYPE=Usage)
   - MTD Credit applied (RECORD_TYPE=Credit, negated)
   - MTD Usage records
2. Computes a 24h burn rate ($/day) and projects credit-exhaust date
   via linear extrapolation against the $19,490 Never-Reach line.
3. Classifies the tick:
   - ``ON_TARGET``    inside $2,000-$3,000/day band
   - ``OFF_TARGET``   outside $2,000-$3,000 but inside $1,500-$3,500
   - ``UNDER_PACE``   < $1,500/day (credit will not exhaust in 7 days)
   - ``OVER_BUDGET``  > $3,500/day (slow down ramp)
4. Emits two CloudWatch ``PutMetricData`` series under the
   ``jpcite/credit`` namespace:
   - ``BurnRateUSDPerDay``     (scalar, USD/day)
   - ``CreditRemainingUSD``    (scalar, USD)
   Both carry a single ``State`` dimension for dashboard colour-coding.
5. Publishes an SNS alert when the state is ``OVER_BUDGET`` or
   ``UNDER_PACE`` (operator review trigger).

This Lambda is **read-only** against AWS Usage data; the $19,490
Never-Reach line is structurally enforced by Budget Action $18,900 +
4-line CloudWatch alarms. The monitor is the cadence layer that
verifies pace, not a kill-switch.

SAFETY model
============
- The ``JPCITE_BURN_RATE_MONITOR_ENABLED`` env var gates every
  side-effecting API call (PutMetricData + SNS Publish). When it is
  anything other than the literal ``"true"`` (case-insensitive), the
  handler logs the *would-emit* envelope and returns ``mode="dry_run"``
  without touching CloudWatch or SNS.
- Default value is ``"false"`` — the operator opts in explicitly.
- The dry-run code path **still** queries Cost Explorer (read-only) so
  the attestation event contains the exact metric values that *would
  have* been emitted. This makes review possible before flipping live.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from typing import Any

import boto3
from botocore.config import Config

LOG = logging.getLogger("jpcite_credit_burn_rate_monitor")
LOG.setLevel(logging.INFO)

CE_REGION = os.environ.get("JPCITE_CE_REGION", "us-east-1")
METRIC_REGION = os.environ.get("JPCITE_BURN_METRIC_REGION", "ap-northeast-1")
NAMESPACE = os.environ.get("JPCITE_BURN_METRIC_NAMESPACE", "jpcite/credit")
SNS_TOPIC_ARN = os.environ.get("JPCITE_ATTESTATION_TOPIC_ARN", "")
ENABLED = os.environ.get("JPCITE_BURN_RATE_MONITOR_ENABLED", "false").strip().lower() == "true"

# Burn band — operator explicit target.
TARGET_LO = float(os.environ.get("JPCITE_BURN_TARGET_LO_USD_PER_DAY", "2000"))
TARGET_HI = float(os.environ.get("JPCITE_BURN_TARGET_HI_USD_PER_DAY", "3000"))
ALERT_LO = float(os.environ.get("JPCITE_BURN_ALERT_LO_USD_PER_DAY", "1500"))
ALERT_HI = float(os.environ.get("JPCITE_BURN_ALERT_HI_USD_PER_DAY", "3500"))
CREDIT_NEVER_REACH = float(os.environ.get("JPCITE_CREDIT_NEVER_REACH_USD", "19490"))
CREDIT_HARD_STOP = float(os.environ.get("JPCITE_CREDIT_HARD_STOP_USD", "18900"))

_BOTO_CFG = Config(retries={"max_attempts": 3, "mode": "standard"})


def _ce_client() -> Any:
    return boto3.client("ce", region_name=CE_REGION, config=_BOTO_CFG)


def _cw_client() -> Any:
    return boto3.client("cloudwatch", region_name=METRIC_REGION, config=_BOTO_CFG)


def _sns_client() -> Any:
    return boto3.client("sns", region_name=CE_REGION, config=_BOTO_CFG)


def _fetch_usage(ce: Any, start: str, end: str, granularity: str = "DAILY") -> float:
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity=granularity,
        Metrics=["UnblendedCost"],
        Filter={"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}},
    )
    total = 0.0
    for row in resp.get("ResultsByTime", []):
        amt = row.get("Total", {}).get("UnblendedCost", {}).get("Amount", "0")
        try:
            total += float(amt)
        except (TypeError, ValueError):
            continue
    return total


def _fetch_credit_applied(ce: Any, start: str, end: str) -> float:
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        Filter={"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit"]}},
    )
    total = 0.0
    for row in resp.get("ResultsByTime", []):
        amt = row.get("Total", {}).get("UnblendedCost", {}).get("Amount", "0")
        try:
            total += float(amt)
        except (TypeError, ValueError):
            continue
    # Credits are negative; flip sign.
    return -total


def _classify(burn_per_day: float) -> tuple[str, str]:
    if burn_per_day > ALERT_HI:
        return "OVER_BUDGET", f"burn ${burn_per_day:,.2f}/day > ${ALERT_HI:,.0f}/day"
    if burn_per_day < ALERT_LO:
        return "UNDER_PACE", f"burn ${burn_per_day:,.2f}/day < ${ALERT_LO:,.0f}/day"
    if burn_per_day > TARGET_HI or burn_per_day < TARGET_LO:
        return (
            "OFF_TARGET",
            f"burn ${burn_per_day:,.2f}/day outside ${TARGET_LO:,.0f}-${TARGET_HI:,.0f}",
        )
    return "ON_TARGET", f"burn ${burn_per_day:,.2f}/day inside target band"


def _project_exhaust(burn_per_day: float, credit_remaining: float, now: dt.datetime) -> str:
    if burn_per_day <= 0.0 or credit_remaining <= 0.0:
        return "never"
    days = credit_remaining / burn_per_day
    exhaust = now + dt.timedelta(days=days)
    return f"{exhaust.strftime('%Y-%m-%d')} (in {days:.1f}d)"


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    now = dt.datetime.now(dt.UTC)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    month_start = now.strftime("%Y-%m-01")
    tomorrow = (now + dt.timedelta(days=1)).strftime("%Y-%m-%d")

    ce = _ce_client()
    try:
        usage_24h = _fetch_usage(ce, yesterday, today)
        usage_mtd = _fetch_usage(ce, month_start, tomorrow)
        credit_applied = _fetch_credit_applied(ce, month_start, tomorrow)
    except Exception as exc:  # noqa: BLE001
        LOG.exception("CE fetch failed: %s", exc)
        return {"mode": "error", "error": str(exc)}

    credit_remaining = max(CREDIT_NEVER_REACH - credit_applied, 0.0)
    state, reason = _classify(usage_24h)
    exhaust = _project_exhaust(usage_24h, credit_remaining, now)

    envelope = {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "burn_per_day_usd": round(usage_24h, 2),
        "usage_mtd_usd": round(usage_mtd, 2),
        "credit_applied_mtd_usd": round(credit_applied, 2),
        "credit_remaining_usd": round(credit_remaining, 2),
        "state": state,
        "reason": reason,
        "projection_exhaust": exhaust,
        "credit_never_reach_usd": CREDIT_NEVER_REACH,
        "credit_hard_stop_usd": CREDIT_HARD_STOP,
        "burn_target_band": {"lo": TARGET_LO, "hi": TARGET_HI},
        "burn_alert_band": {"lo": ALERT_LO, "hi": ALERT_HI},
    }

    if not ENABLED:
        LOG.info("DRY_RUN tick: %s", json.dumps(envelope))
        envelope["mode"] = "dry_run"
        return envelope

    # Emit CloudWatch metrics.
    try:
        cw = _cw_client()
        cw.put_metric_data(
            Namespace=NAMESPACE,
            MetricData=[
                {
                    "MetricName": "BurnRateUSDPerDay",
                    "Value": float(envelope["burn_per_day_usd"]),
                    "Unit": "None",
                    "Dimensions": [{"Name": "State", "Value": state}],
                    "Timestamp": now,
                },
                {
                    "MetricName": "CreditRemainingUSD",
                    "Value": float(envelope["credit_remaining_usd"]),
                    "Unit": "None",
                    "Dimensions": [{"Name": "State", "Value": state}],
                    "Timestamp": now,
                },
            ],
        )
        envelope["cloudwatch_emit"] = "ok"
    except Exception as exc:  # noqa: BLE001
        LOG.exception("CloudWatch emit failed: %s", exc)
        envelope["cloudwatch_emit"] = f"error: {exc}"

    # Publish SNS alert when off-band (OVER_BUDGET / UNDER_PACE).
    if state in {"OVER_BUDGET", "UNDER_PACE"} and SNS_TOPIC_ARN:
        try:
            sns = _sns_client()
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=f"[jpcite burn-rate-monitor] {state}",
                Message=json.dumps(envelope, indent=2),
            )
            envelope["sns_publish"] = "ok"
        except Exception as exc:  # noqa: BLE001
            LOG.exception("SNS publish failed: %s", exc)
            envelope["sns_publish"] = f"error: {exc}"

    envelope["mode"] = "live"
    LOG.info("LIVE tick: %s", json.dumps(envelope))
    return envelope
