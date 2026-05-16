"""Auto-stop Lambda for the jpcite credit run.

Triggered by SNS notifications from:
- AWS Budgets (USD 17000 / 18300 / 18900 breach thresholds)
- CloudWatch billing alarms (same SNS topic)

On invocation, the handler parses the SNS payload, then disables all
``jpcite-credit-*`` AWS Batch resources:

1. ``update-job-queue --state DISABLED`` on every matching queue.
2. ``cancel-job`` on every SUBMITTED / PENDING / RUNNABLE job.
3. ``terminate-job`` on every RUNNING job.
4. ``update-compute-environment --state DISABLED`` on every matching CE.

After the mutation pass, an attestation event is published back to the
originating SNS topic so the operator has a single audit trail.

SAFETY model
============
- The ``JPCITE_AUTO_STOP_ENABLED`` environment variable gates *every*
  mutating API call. When it is anything other than the literal string
  ``"true"`` (case-insensitive), the handler logs the intent and returns
  ``mode="dry_run"`` without touching any resource.
- Default value is ``"false"`` — the operator must opt in explicitly.
- The dry-run code path still walks the queues / CEs and lists jobs so
  the attestation contains the exact set of resources that *would have*
  been stopped. This makes manual review possible before flipping the
  switch live.

Per ``docs/_internal/aws_credit_review_16_incident_stop.md``, the stop
flow is the single most critical safety control of the credit run. The
manual ``scripts/aws_credit_ops/stop_drill.sh`` remains the primary
path; this Lambda is the automated backup so an operator-absent breach
still drains the queues within seconds of the budget alarm firing.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Final, cast

import boto3  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from mypy_boto3_batch import BatchClient  # type: ignore[import-not-found]
    from mypy_boto3_sns import SNSClient  # type: ignore[import-not-found]

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION: Final[str] = os.environ.get("AWS_REGION", "us-east-1")
BATCH_REGION: Final[str] = os.environ.get("JPCITE_BATCH_REGION", "ap-northeast-1")
SNS_TOPIC_ARN: Final[str] = os.environ.get(
    "JPCITE_ATTESTATION_TOPIC_ARN",
    "arn:aws:sns:us-east-1:993693061769:jpcite-credit-cost-alerts",
)
QUEUE_PREFIX: Final[str] = os.environ.get("JPCITE_QUEUE_PREFIX", "jpcite-credit-")
CE_PREFIX: Final[str] = os.environ.get("JPCITE_CE_PREFIX", "jpcite-credit-")

PENDING_STATUSES: Final[tuple[str, ...]] = ("SUBMITTED", "PENDING", "RUNNABLE")


def _enabled() -> bool:
    """Return True only when the SAFETY env var is explicitly set to ``true``."""
    value = os.environ.get("JPCITE_AUTO_STOP_ENABLED", "false").strip().lower()
    return value == "true"


def _parse_sns_records(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract SNS records from a Lambda event. Returns [] for direct invokes."""
    records = event.get("Records") or []
    parsed: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        sns = record.get("Sns")
        if not isinstance(sns, dict):
            continue
        message_raw = sns.get("Message", "")
        try:
            message = json.loads(message_raw) if message_raw else {}
        except (json.JSONDecodeError, TypeError):
            message = {"raw": message_raw}
        parsed.append(
            {
                "subject": sns.get("Subject"),
                "timestamp": sns.get("Timestamp"),
                "message": message,
                "topic_arn": sns.get("TopicArn"),
            }
        )
    return parsed


ATTESTATION_SUBJECT: Final[str] = "jpcite-credit-auto-stop attestation"


def _classify_alert(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Best-effort classification of the SNS payload (budget vs alarm).

    Special case: if the payload originated from this Lambda's own attestation
    publish, classify it as ``self_attestation`` so the handler can short-
    circuit and avoid an infinite invocation loop on the shared SNS topic.
    """
    if not records:
        return {"kind": "manual_invoke", "threshold_usd": None, "source_subject": None}
    head = records[0]
    subject = (head.get("subject") or "").strip()
    message = head.get("message") or {}
    if subject == ATTESTATION_SUBJECT:
        return {
            "kind": "self_attestation",
            "threshold_usd": None,
            "source_subject": subject,
        }
    if isinstance(message, dict) and message.get("lambda") == "jpcite-credit-auto-stop":
        return {
            "kind": "self_attestation",
            "threshold_usd": None,
            "source_subject": subject,
        }
    subject_lower = subject.lower()
    kind = "unknown"
    threshold: float | None = None
    if isinstance(message, dict):
        if "AlarmName" in message:
            kind = "cloudwatch_alarm"
            metric = message.get("Trigger", {})
            if isinstance(metric, dict):
                value = metric.get("Threshold")
                if isinstance(value, (int, float)):
                    threshold = float(value)
        elif "BudgetName" in message or "budgetName" in message:
            kind = "aws_budget"
            for key in ("Threshold", "threshold", "ActualSpend", "actualSpend"):
                value = message.get(key)
                if isinstance(value, dict):
                    amount = value.get("amount") or value.get("Amount")
                    if isinstance(amount, (int, float, str)):
                        try:
                            threshold = float(amount)
                            break
                        except (TypeError, ValueError):
                            continue
                elif isinstance(value, (int, float)):
                    threshold = float(value)
                    break
    if kind == "unknown" and "budget" in subject_lower:
        kind = "aws_budget"
    if kind == "unknown" and "alarm" in subject_lower:
        kind = "cloudwatch_alarm"
    return {"kind": kind, "threshold_usd": threshold, "source_subject": subject}


def _list_matching_queues(batch: BatchClient) -> list[str]:
    paginator = batch.get_paginator("describe_job_queues")
    queues: list[str] = []
    for page in paginator.paginate():
        for queue in page.get("jobQueues", []):
            name = queue.get("jobQueueName", "")
            if name.startswith(QUEUE_PREFIX):
                queues.append(name)
    return queues


def _list_matching_ces(batch: BatchClient) -> list[str]:
    paginator = batch.get_paginator("describe_compute_environments")
    ces: list[str] = []
    for page in paginator.paginate():
        for env in page.get("computeEnvironments", []):
            name = env.get("computeEnvironmentName", "")
            if name.startswith(CE_PREFIX):
                ces.append(name)
    return ces


def _list_jobs(batch: BatchClient, queue: str, status: str) -> list[str]:
    paginator = batch.get_paginator("list_jobs")
    job_ids: list[str] = []
    try:
        for page in paginator.paginate(jobQueue=queue, jobStatus=status):
            for job in page.get("jobSummaryList", []):
                job_id = job.get("jobId")
                if job_id:
                    job_ids.append(job_id)
    except Exception as exc:  # noqa: BLE001 — Lambda must never crash on listing
        logger.warning("list_jobs failed queue=%s status=%s err=%s", queue, status, exc)
    return job_ids


def _disable_queue(batch: BatchClient, queue: str, live: bool) -> dict[str, Any]:
    if live:
        batch.update_job_queue(jobQueue=queue, state="DISABLED")
        logger.info("disabled queue=%s", queue)
    else:
        logger.info("DRY_RUN would disable queue=%s", queue)
    return {"queue": queue, "action": "disable_queue", "live": live}


def _cancel_job(batch: BatchClient, job_id: str, live: bool) -> dict[str, Any]:
    if live:
        batch.cancel_job(jobId=job_id, reason="jpcite_credit_auto_stop budget breach")
        logger.info("cancelled job=%s", job_id)
    else:
        logger.info("DRY_RUN would cancel job=%s", job_id)
    return {"job_id": job_id, "action": "cancel_job", "live": live}


def _terminate_job(batch: BatchClient, job_id: str, live: bool) -> dict[str, Any]:
    if live:
        batch.terminate_job(jobId=job_id, reason="jpcite_credit_auto_stop budget breach")
        logger.info("terminated job=%s", job_id)
    else:
        logger.info("DRY_RUN would terminate job=%s", job_id)
    return {"job_id": job_id, "action": "terminate_job", "live": live}


def _disable_ce(batch: BatchClient, ce: str, live: bool) -> dict[str, Any]:
    if live:
        batch.update_compute_environment(computeEnvironment=ce, state="DISABLED")
        logger.info("disabled ce=%s", ce)
    else:
        logger.info("DRY_RUN would disable ce=%s", ce)
    return {"ce": ce, "action": "disable_ce", "live": live}


def _emit_attestation(sns: SNSClient, payload: dict[str, Any]) -> str | None:
    if not SNS_TOPIC_ARN:
        logger.warning("no SNS topic configured; attestation skipped")
        return None
    try:
        response = sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject="jpcite-credit-auto-stop attestation",
            Message=json.dumps(payload, default=str, ensure_ascii=False),
        )
        message_id = response.get("MessageId")
        logger.info("attestation published message_id=%s", message_id)
        return cast("str | None", message_id)
    except Exception as exc:  # noqa: BLE001 — attestation failure must not break stop
        logger.error("attestation publish failed err=%s", exc)
        return None


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    """Entry point invoked by the SNS subscription."""
    started_at = time.time()
    live = _enabled()
    mode = "live" if live else "dry_run"
    logger.info(
        "jpcite_credit_auto_stop invoked mode=%s batch_region=%s",
        mode,
        BATCH_REGION,
    )

    records = _parse_sns_records(event)
    classification = _classify_alert(records)
    logger.info("alert classification=%s", classification)

    if classification["kind"] == "self_attestation":
        logger.info("self_attestation echo detected — skipping batch walk to break loop")
        return {
            "lambda": "jpcite-credit-auto-stop",
            "mode": mode,
            "started_at": started_at,
            "duration_s": round(time.time() - started_at, 3),
            "classification": classification,
            "batch_region": BATCH_REGION,
            "queues_matched": [],
            "ces_matched": [],
            "actions": [],
            "actions_count": 0,
            "skipped_reason": "self_attestation_echo",
        }

    batch = cast("BatchClient", boto3.client("batch", region_name=BATCH_REGION))
    sns = cast("SNSClient", boto3.client("sns", region_name=REGION))

    actions: list[dict[str, Any]] = []

    queues = _list_matching_queues(batch)
    logger.info("matched queues=%s", queues)
    for queue in queues:
        actions.append(_disable_queue(batch, queue, live))
        for status in PENDING_STATUSES:
            for job_id in _list_jobs(batch, queue, status):
                actions.append(_cancel_job(batch, job_id, live))
        for job_id in _list_jobs(batch, queue, "RUNNING"):
            actions.append(_terminate_job(batch, job_id, live))

    ces = _list_matching_ces(batch)
    logger.info("matched compute_environments=%s", ces)
    for ce in ces:
        actions.append(_disable_ce(batch, ce, live))

    payload: dict[str, Any] = {
        "lambda": "jpcite-credit-auto-stop",
        "mode": mode,
        "started_at": started_at,
        "duration_s": round(time.time() - started_at, 3),
        "classification": classification,
        "batch_region": BATCH_REGION,
        "queues_matched": queues,
        "ces_matched": ces,
        "actions": actions,
        "actions_count": len(actions),
        "safety_env": {
            "JPCITE_AUTO_STOP_ENABLED": os.environ.get(
                "JPCITE_AUTO_STOP_ENABLED", "false"
            ),
        },
    }
    payload["attestation_message_id"] = _emit_attestation(sns, payload)
    return payload
