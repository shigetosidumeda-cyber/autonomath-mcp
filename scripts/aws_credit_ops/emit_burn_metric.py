#!/usr/bin/env python3
"""Real-time burn-metric emitter for the jpcite 2026-05 credit run.

Runs every 5 minutes (EventBridge schedule when deployed as Lambda, or
``--once`` from a local cron / GHA job). On each invocation it:

1. Queries AWS Cost Explorer for **month-to-date UnblendedCost** in the
   ``us-east-1`` global endpoint (Cost Explorer is region-agnostic but
   only has a single endpoint).
2. Computes an **hourly burn rate** by dividing the consumed amount by
   the hours that have elapsed since the first instant of the current
   UTC month.
3. Classifies the burn rate against fixed thresholds:

   * ``RAMP``      — consumed < 85% of ``--target`` (default ``$18,300``)
   * ``SLOWDOWN``  — 85% ≤ consumed < 95%
   * ``STOP``      — consumed ≥ 95% **or** hourly burn ≥ ``--hourly-stop``
     (default ``$500/hr``)

4. Emits two CloudWatch ``PutMetricData`` calls under the
   ``jpcite/credit`` namespace:

   * ``GrossSpendUSD`` (Unit=``None``, stat: scalar gauge)
   * ``HourlyBurnRate`` (Unit=``None``, stat: scalar gauge)

   Both metrics carry a single ``Classification`` dimension with the
   value computed in step 3 so the dashboard widget can colour-code or
   filter on it.

5. Optionally publishes an SNS alert when the hourly burn rate breaches
   the ``--hourly-alert`` threshold (default ``$500/hr``).

Safety model
============
- **DRY_RUN by default.** The actual ``PutMetricData`` + ``sns.publish``
  calls only fire when ``JPCITE_BURN_METRIC_ENABLED`` is the literal
  string ``"true"`` (case-insensitive). The Lambda env var is set to
  ``"false"`` at deploy time so the EventBridge rule can fire on
  schedule without writing any side effect — the operator opts in
  explicitly when ready to plot real-time burn.
- The dry-run code path still walks Cost Explorer (a read-only API) and
  prints the would-emit payload so the operator can review the
  classification and threshold logic before flipping the switch live.
- The script is reusable from a shell (``scripts/aws_credit_ops/emit_burn_metric.py``)
  or a Lambda handler (``infra/aws/lambda/jpcite_credit_burn_metric.py``).
  Both share the same ``build_emission`` + ``emit`` entry points.

CLI usage::

    $ ./scripts/aws_credit_ops/emit_burn_metric.py --once
    $ JPCITE_BURN_METRIC_ENABLED=true ./scripts/aws_credit_ops/emit_burn_metric.py --once

Lambda env vars::

    JPCITE_BURN_METRIC_ENABLED   "true" to emit (default "false" — dry run)
    JPCITE_CREDIT_TARGET_USD     monthly target (default "18300")
    JPCITE_HOURLY_STOP_USD       hourly burn STOP line (default "500")
    JPCITE_HOURLY_ALERT_USD      hourly burn SNS alert line (default "500")
    JPCITE_BURN_METRIC_NAMESPACE CloudWatch namespace (default "jpcite/credit")
    JPCITE_BURN_METRIC_REGION    CloudWatch region (default "ap-northeast-1")
    JPCITE_CE_REGION             Cost Explorer endpoint (default "us-east-1")
    JPCITE_ATTESTATION_TOPIC_ARN SNS topic for hourly-burn breach
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol, cast

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ----------------------------------------------------------------------------
# Defaults sourced from the 2026-05 credit run launch CLI plan.
# These mirror the values baked into burn_target.py + the auto-stop Lambda
# so the four scripts converge on the same RAMP/SLOWDOWN/STOP semantics.
# ----------------------------------------------------------------------------

DEFAULT_TARGET_USD: Final[float] = 18_300.0
DEFAULT_HOURLY_STOP_USD: Final[float] = 500.0
DEFAULT_HOURLY_ALERT_USD: Final[float] = 500.0
DEFAULT_NAMESPACE: Final[str] = "jpcite/credit"
DEFAULT_METRIC_REGION: Final[str] = "ap-northeast-1"
DEFAULT_CE_REGION: Final[str] = "us-east-1"
DEFAULT_SNS_TOPIC_ARN: Final[str] = (
    "arn:aws:sns:us-east-1:993693061769:jpcite-credit-cost-alerts"
)

SLOWDOWN_RATIO: Final[float] = 0.85
STOP_RATIO: Final[float] = 0.95

CLASSIFICATION_RAMP: Final[str] = "RAMP"
CLASSIFICATION_SLOWDOWN: Final[str] = "SLOWDOWN"
CLASSIFICATION_STOP: Final[str] = "STOP"


if TYPE_CHECKING:
    from mypy_boto3_ce import CostExplorerClient  # type: ignore[import-not-found]
    from mypy_boto3_cloudwatch import CloudWatchClient  # type: ignore[import-not-found]
    from mypy_boto3_sns import SNSClient  # type: ignore[import-not-found]


class _CostExplorerLike(Protocol):
    """Subset of the Cost Explorer client surface this module uses."""

    def get_cost_and_usage(self, **kwargs: Any) -> dict[str, Any]:  # noqa: D401
        ...


class _CloudWatchLike(Protocol):
    def put_metric_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: D401
        ...


class _SNSLike(Protocol):
    def publish(self, **kwargs: Any) -> dict[str, Any]:  # noqa: D401
        ...


# ----------------------------------------------------------------------------
# Pure helpers — no boto3 import at module level so unit tests stay fast.
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class BurnEmission:
    """The data envelope that ``build_emission`` produces."""

    consumed_usd: float
    target_usd: float
    remaining_usd: float
    hours_elapsed: float
    hourly_burn_usd: float
    hourly_stop_usd: float
    hourly_alert_usd: float
    classification: str
    breached_hourly_alert: bool
    breached_hourly_stop: bool
    namespace: str
    metric_region: str
    ce_region: str
    timestamp: str  # ISO-8601 UTC
    period_start: str
    period_end: str

    def metric_payloads(self) -> list[dict[str, Any]]:
        """Two ``MetricData`` rows for ``PutMetricData``."""

        return [
            {
                "MetricName": "GrossSpendUSD",
                "Dimensions": [{"Name": "Classification", "Value": self.classification}],
                "Value": float(self.consumed_usd),
                "Unit": "None",
                "Timestamp": self.timestamp,
            },
            {
                "MetricName": "HourlyBurnRate",
                "Dimensions": [{"Name": "Classification", "Value": self.classification}],
                "Value": float(self.hourly_burn_usd),
                "Unit": "None",
                "Timestamp": self.timestamp,
            },
        ]


def _month_window(now: dt.datetime) -> tuple[str, str, float]:
    """Return ``(period_start_iso_date, period_end_iso_date, hours_elapsed)``.

    Cost Explorer ``TimePeriod`` is *inclusive start, exclusive end*, so
    ``end`` is set to one day past *today* in UTC.
    """

    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    hours_elapsed = max((now - start).total_seconds() / 3600.0, 1.0 / 60.0)
    return (
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
        round(hours_elapsed, 4),
    )


def _classify(consumed: float, target: float, hourly: float, hourly_stop: float) -> str:
    """Map ``(consumed, target, hourly_burn)`` to a 3-tier classification."""

    if target <= 0:
        return CLASSIFICATION_STOP if consumed > 0 else CLASSIFICATION_RAMP
    if hourly >= hourly_stop and hourly_stop > 0:
        return CLASSIFICATION_STOP
    ratio = consumed / target
    if ratio >= STOP_RATIO:
        return CLASSIFICATION_STOP
    if ratio >= SLOWDOWN_RATIO:
        return CLASSIFICATION_SLOWDOWN
    return CLASSIFICATION_RAMP


def _parse_ce_response(response: dict[str, Any]) -> float:
    """Pull ``UnblendedCost.Amount`` out of a CE month-to-date response.

    Tolerant to the various shapes CE returns — empty ``ResultsByTime``,
    missing ``UnblendedCost`` key, and float-vs-string ``Amount``.
    """

    results = response.get("ResultsByTime") or []
    if not results:
        return 0.0
    first = results[0]
    total = first.get("Total") or {}
    metric = total.get("UnblendedCost") or total.get("BlendedCost") or {}
    amount = metric.get("Amount", "0")
    try:
        return float(amount)
    except (TypeError, ValueError):
        return 0.0


def build_emission(
    ce_client: _CostExplorerLike,
    *,
    now: dt.datetime | None = None,
    target_usd: float = DEFAULT_TARGET_USD,
    hourly_stop_usd: float = DEFAULT_HOURLY_STOP_USD,
    hourly_alert_usd: float = DEFAULT_HOURLY_ALERT_USD,
    namespace: str = DEFAULT_NAMESPACE,
    metric_region: str = DEFAULT_METRIC_REGION,
    ce_region: str = DEFAULT_CE_REGION,
) -> BurnEmission:
    """Query CE + compute classification. Pure-ish — only the CE call has I/O."""

    now = now or dt.datetime.now(dt.UTC)
    start, end, hours_elapsed = _month_window(now)
    response = ce_client.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )
    consumed = _parse_ce_response(response)
    hourly = consumed / hours_elapsed if hours_elapsed > 0 else 0.0
    classification = _classify(consumed, target_usd, hourly, hourly_stop_usd)
    breached_alert = hourly_alert_usd > 0 and hourly >= hourly_alert_usd
    breached_stop = hourly_stop_usd > 0 and hourly >= hourly_stop_usd
    return BurnEmission(
        consumed_usd=round(consumed, 4),
        target_usd=round(target_usd, 4),
        remaining_usd=round(max(target_usd - consumed, 0.0), 4),
        hours_elapsed=hours_elapsed,
        hourly_burn_usd=round(hourly, 4),
        hourly_stop_usd=round(hourly_stop_usd, 4),
        hourly_alert_usd=round(hourly_alert_usd, 4),
        classification=classification,
        breached_hourly_alert=breached_alert,
        breached_hourly_stop=breached_stop,
        namespace=namespace,
        metric_region=metric_region,
        ce_region=ce_region,
        timestamp=now.replace(microsecond=0).isoformat(),
        period_start=start,
        period_end=end,
    )


def emit(
    emission: BurnEmission,
    *,
    cw_client: _CloudWatchLike | None,
    sns_client: _SNSLike | None,
    sns_topic_arn: str | None,
    live: bool,
) -> dict[str, Any]:
    """Write to CloudWatch + optionally SNS. Returns the action log.

    ``live=False`` short-circuits BOTH the ``PutMetricData`` and the SNS
    publish call but still records the *would-have* action in the
    returned log so the dry-run output is faithful to live-mode shape.
    """

    actions: list[dict[str, Any]] = []
    payloads = emission.metric_payloads()
    if live and cw_client is not None:
        cw_client.put_metric_data(Namespace=emission.namespace, MetricData=payloads)
        actions.append(
            {"action": "put_metric_data", "namespace": emission.namespace, "count": len(payloads), "live": True}
        )
    else:
        actions.append(
            {"action": "put_metric_data", "namespace": emission.namespace, "count": len(payloads), "live": False}
        )

    if emission.breached_hourly_alert and sns_topic_arn:
        message = json.dumps(
            {
                "alert": "jpcite-credit hourly burn breach",
                "hourly_burn_usd": emission.hourly_burn_usd,
                "hourly_alert_usd": emission.hourly_alert_usd,
                "classification": emission.classification,
                "consumed_usd": emission.consumed_usd,
                "target_usd": emission.target_usd,
                "timestamp": emission.timestamp,
            },
            ensure_ascii=False,
        )
        if live and sns_client is not None:
            sns_client.publish(
                TopicArn=sns_topic_arn,
                Subject="jpcite-credit-burn-metric alert",
                Message=message,
            )
            actions.append({"action": "sns_publish", "topic_arn": sns_topic_arn, "live": True})
        else:
            actions.append({"action": "sns_publish", "topic_arn": sns_topic_arn, "live": False})

    return {
        "emission": asdict(emission),
        "actions": actions,
        "actions_count": len(actions),
        "live": live,
    }


# ----------------------------------------------------------------------------
# Environment + CLI glue
# ----------------------------------------------------------------------------


def _enabled() -> bool:
    """``JPCITE_BURN_METRIC_ENABLED=true`` is the only way to fire side effects."""

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


def _build_boto3_clients(
    metric_region: str, ce_region: str
) -> tuple[_CloudWatchLike, _CostExplorerLike, _SNSLike]:
    """Import boto3 lazily — keeps unit tests cheap."""

    import boto3  # type: ignore[import-not-found]

    cw = cast("CloudWatchClient", boto3.client("cloudwatch", region_name=metric_region))
    ce = cast("CostExplorerClient", boto3.client("ce", region_name=ce_region))
    sns = cast("SNSClient", boto3.client("sns", region_name=ce_region))
    return cw, ce, sns


def run_once(argv: list[str] | None = None) -> dict[str, Any]:
    """End-to-end one-shot. Used by both the CLI and the Lambda handler."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=float, default=_env_float("JPCITE_CREDIT_TARGET_USD", DEFAULT_TARGET_USD))
    parser.add_argument(
        "--hourly-stop",
        type=float,
        default=_env_float("JPCITE_HOURLY_STOP_USD", DEFAULT_HOURLY_STOP_USD),
    )
    parser.add_argument(
        "--hourly-alert",
        type=float,
        default=_env_float("JPCITE_HOURLY_ALERT_USD", DEFAULT_HOURLY_ALERT_USD),
    )
    parser.add_argument(
        "--namespace",
        default=os.environ.get("JPCITE_BURN_METRIC_NAMESPACE", DEFAULT_NAMESPACE),
    )
    parser.add_argument(
        "--metric-region",
        default=os.environ.get("JPCITE_BURN_METRIC_REGION", DEFAULT_METRIC_REGION),
    )
    parser.add_argument(
        "--ce-region",
        default=os.environ.get("JPCITE_CE_REGION", DEFAULT_CE_REGION),
    )
    parser.add_argument(
        "--sns-topic-arn",
        default=os.environ.get("JPCITE_ATTESTATION_TOPIC_ARN", DEFAULT_SNS_TOPIC_ARN),
    )
    parser.add_argument("--once", action="store_true", help="(accepted, default behaviour)")
    parser.add_argument("--dry-run", action="store_true", help="force dry-run regardless of env")
    args = parser.parse_args(argv)

    live = _enabled() and not args.dry_run
    cw_client: _CloudWatchLike | None = None
    ce_client: _CostExplorerLike
    sns_client: _SNSLike | None = None

    if live:
        cw_client, ce_client, sns_client = _build_boto3_clients(args.metric_region, args.ce_region)
    else:
        # In dry-run we still need to *query* CE if boto3 is importable, otherwise
        # we emit a synthetic zero-spend envelope so the operator can verify the
        # classification + payload shape end-to-end.
        try:
            _, ce_client, _ = _build_boto3_clients(args.metric_region, args.ce_region)
        except Exception as exc:  # noqa: BLE001 — local-dev path, boto3 might be absent
            logger.warning("boto3 unavailable (%s); using synthetic CE response", exc)
            ce_client = _SyntheticCEClient()

    emission = build_emission(
        ce_client,
        target_usd=args.target,
        hourly_stop_usd=args.hourly_stop,
        hourly_alert_usd=args.hourly_alert,
        namespace=args.namespace,
        metric_region=args.metric_region,
        ce_region=args.ce_region,
    )

    result = emit(
        emission,
        cw_client=cw_client,
        sns_client=sns_client,
        sns_topic_arn=args.sns_topic_arn,
        live=live,
    )
    logger.info(
        "burn-metric mode=%s classification=%s consumed=%.2f hourly=%.2f",
        "live" if live else "dry_run",
        emission.classification,
        emission.consumed_usd,
        emission.hourly_burn_usd,
    )
    return result


class _SyntheticCEClient:
    """Used when boto3 isn't installed locally and the operator runs ``--dry-run``."""

    def get_cost_and_usage(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "ResultsByTime": [
                {
                    "Total": {
                        "UnblendedCost": {"Amount": "0.0000", "Unit": "USD"},
                    },
                    "TimePeriod": {"Start": _kwargs.get("TimePeriod", {}).get("Start", "")},
                }
            ]
        }


def main() -> int:
    result = run_once()
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")
    classification = result.get("emission", {}).get("classification")
    if classification == CLASSIFICATION_STOP:
        return 1
    if classification == CLASSIFICATION_SLOWDOWN:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
