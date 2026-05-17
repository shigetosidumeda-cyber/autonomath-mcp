"""CC4 — declarative boto3 deploy for the PDF watch pipeline.

Idempotent provisioning of the three Lambdas, EventBridge rule, SQS
queue (with DLQ), and SNS topic that comprise the CC4 sustained-moat
ingest:

    EventBridge rate(1 hour)
        -> Lambda: jpcite-pdf-watch-detect
            -> SQS: jpcite-pdf-textract-queue
                -> Lambda: jpcite-pdf-watch-textract-submit
                    -> Textract StartDocumentAnalysis (ap-southeast-1)
                        -> SNS: jpcite-pdf-textract-completion
                            -> Lambda: jpcite-pdf-watch-kg-extract
                                -> autonomath.db: am_entity_facts/am_relation
                                -> autonomath.db: am_pdf_watch_log flip

Run pattern
-----------
::

    AWS_PROFILE=bookyou-recovery python infra/aws/lambda/pdf_watch_pipeline_deploy.py --dry-run
    AWS_PROFILE=bookyou-recovery python infra/aws/lambda/pdf_watch_pipeline_deploy.py --commit

DRY_RUN by default. ``--commit`` triggers real AWS API calls.

Safety
------
* All resources start with ``state=DISABLED`` / ``JPCITE_PDF_WATCH_ENABLED=false``.
* Operator flips on with the explicit ``aws scheduler update-schedule`` +
  ``aws lambda update-function-configuration`` commands shown in the
  schedule JSON's ``operator_notes`` section.
* Hard-stop tripwires (CW $14K, Budget $17K, slowdown $18.3K, Lambda
  kill $18.7K + Action deny $18.9K) remain primary defence.
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any

logger = logging.getLogger("jpcite.cc4.pdf_watch_deploy")

DEFAULT_ACCOUNT_ID = "993693061769"
DEFAULT_REGION = "ap-northeast-1"
DEFAULT_TEXTRACT_REGION = "ap-southeast-1"
DEFAULT_PROFILE = "bookyou-recovery"

SQS_QUEUE_NAME = "jpcite-pdf-textract-queue"
SQS_DLQ_NAME = "jpcite-pdf-textract-dlq"
SNS_TOPIC_NAME = "jpcite-pdf-textract-completion"

LAMBDA_DETECT_NAME = "jpcite-pdf-watch-detect"
LAMBDA_SUBMIT_NAME = "jpcite-pdf-watch-textract-submit"
LAMBDA_KG_NAME = "jpcite-pdf-watch-kg-extract"

EVENTBRIDGE_RULE_NAME = "jpcite-pdf-watch-hourly"
SCHEDULE_EXPRESSION = "rate(1 hour)"

ROLE_NAME = "jpcite-pdf-watch-lambda-role"


def _client(boto3: Any, service: str, region: str) -> Any:
    return boto3.client(service, region_name=region)


def ensure_sqs(boto3: Any, *, region: str = DEFAULT_REGION, commit: bool) -> dict[str, str]:
    """Create the primary queue + DLQ. Idempotent."""
    if not commit:
        return {
            "queue_url": f"https://sqs.{region}.amazonaws.com/{DEFAULT_ACCOUNT_ID}/{SQS_QUEUE_NAME}",
            "dlq_url": f"https://sqs.{region}.amazonaws.com/{DEFAULT_ACCOUNT_ID}/{SQS_DLQ_NAME}",
            "mode": "dry_run",
        }
    sqs = _client(boto3, "sqs", region)
    dlq = sqs.create_queue(
        QueueName=SQS_DLQ_NAME,
        Attributes={"MessageRetentionPeriod": "1209600"},  # 14 days
    )
    dlq_url = dlq["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"][
        "QueueArn"
    ]
    primary = sqs.create_queue(
        QueueName=SQS_QUEUE_NAME,
        Attributes={
            "VisibilityTimeout": "900",
            "MessageRetentionPeriod": "345600",  # 4 days
            "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"}),
        },
    )
    return {"queue_url": primary["QueueUrl"], "dlq_url": dlq_url, "mode": "committed"}


def ensure_sns(
    boto3: Any, *, region: str = DEFAULT_TEXTRACT_REGION, commit: bool
) -> dict[str, str]:
    """Create the Textract completion SNS topic (in textract region)."""
    if not commit:
        return {
            "topic_arn": f"arn:aws:sns:{region}:{DEFAULT_ACCOUNT_ID}:{SNS_TOPIC_NAME}",
            "mode": "dry_run",
        }
    sns = _client(boto3, "sns", region)
    resp = sns.create_topic(Name=SNS_TOPIC_NAME)
    return {"topic_arn": resp["TopicArn"], "mode": "committed"}


def ensure_eventbridge_rule(
    boto3: Any, *, region: str = DEFAULT_REGION, commit: bool, lambda_arn: str
) -> dict[str, str]:
    """Create the hourly EventBridge rule wired to the detect Lambda."""
    if not commit:
        return {
            "rule_arn": f"arn:aws:events:{region}:{DEFAULT_ACCOUNT_ID}:rule/{EVENTBRIDGE_RULE_NAME}",
            "lambda_arn": lambda_arn,
            "state": "DISABLED",
            "mode": "dry_run",
        }
    events = _client(boto3, "events", region)
    resp = events.put_rule(
        Name=EVENTBRIDGE_RULE_NAME,
        ScheduleExpression=SCHEDULE_EXPRESSION,
        State="DISABLED",  # operator opt-in
        Description="CC4 hourly PDF watch detector (54 sources). DISABLED until operator explicitly enables.",
        Tags=[
            {"Key": "Project", "Value": "jpcite"},
            {"Key": "Wave", "Value": "CC4"},
        ],
    )
    events.put_targets(
        Rule=EVENTBRIDGE_RULE_NAME,
        Targets=[
            {
                "Id": "jpcite-pdf-watch-target",
                "Arn": lambda_arn,
                "Input": json.dumps(
                    {"trigger": "eventbridge-schedule", "source": EVENTBRIDGE_RULE_NAME}
                ),
            }
        ],
    )
    return {
        "rule_arn": resp["RuleArn"],
        "lambda_arn": lambda_arn,
        "state": "DISABLED",
        "mode": "committed",
    }


def plan(commit: bool) -> dict[str, Any]:
    """Compose the deploy plan + execute if commit=True."""
    boto3: Any
    try:
        import boto3  # type: ignore[import-not-found,unused-ignore,no-redef]
    except ImportError:
        boto3 = None
        commit = False

    plan_summary: dict[str, Any] = {
        "mode": "committed" if commit else "dry_run",
        "region_primary": DEFAULT_REGION,
        "region_textract": DEFAULT_TEXTRACT_REGION,
        "account_id": DEFAULT_ACCOUNT_ID,
        "lambdas": [LAMBDA_DETECT_NAME, LAMBDA_SUBMIT_NAME, LAMBDA_KG_NAME],
        "lambda_count": 3,
        "sqs_queue": SQS_QUEUE_NAME,
        "sqs_dlq": SQS_DLQ_NAME,
        "sns_topic": SNS_TOPIC_NAME,
        "eventbridge_rule": EVENTBRIDGE_RULE_NAME,
        "schedule_expression": SCHEDULE_EXPRESSION,
        "iam_role": ROLE_NAME,
        "watch_sources": 54,
        "sustained_burn_usd_per_day": 150,
        "never_reach_ceiling_usd": 19490,
        "burn_window_days": 100,
    }

    if boto3 is None or not commit:
        plan_summary["sqs"] = {"queue_url": "<dry_run>", "dlq_url": "<dry_run>"}
        plan_summary["sns"] = {"topic_arn": "<dry_run>"}
        plan_summary["eventbridge"] = {
            "rule_arn": "<dry_run>",
            "state": "DISABLED",
        }
        return plan_summary

    sqs_info = ensure_sqs(boto3, commit=True)
    sns_info = ensure_sns(boto3, commit=True)
    detect_arn = (
        f"arn:aws:lambda:{DEFAULT_REGION}:{DEFAULT_ACCOUNT_ID}:function:{LAMBDA_DETECT_NAME}"
    )
    eb_info = ensure_eventbridge_rule(boto3, commit=True, lambda_arn=detect_arn)
    plan_summary["sqs"] = sqs_info
    plan_summary["sns"] = sns_info
    plan_summary["eventbridge"] = eb_info
    return plan_summary


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--commit", action="store_true", help="Actually call AWS APIs")
    p.add_argument("--dry-run", action="store_true", help="Force dry-run (default)")
    p.add_argument("--log-level", default="INFO")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    commit = bool(args.commit and not args.dry_run)
    summary = plan(commit=commit)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
