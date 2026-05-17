"""CC4 Lambda — drain SQS, submit Textract StartDocumentAnalysis.

Triggered by ``jpcite-pdf-textract-queue`` SQS messages produced by
``scripts/cron/pdf_watch_detect_2026_05_17.py``. For each message the
handler:

    1. Downloads the PDF from its public ``source_url`` (HTTP GET).
    2. Stages bytes to s3://jpcite-credit-textract-apse1-202605/in/<sha[:2]>/<sha>.pdf
    3. Calls Textract ``start_document_analysis`` (TABLES + FORMS) in
       ``ap-southeast-1`` (Textract is not offered in ``ap-northeast-1``).
    4. Updates ``am_pdf_watch_log`` row: textract_status='submitted',
       textract_job_id=<job>, s3_input_key=<key>.
    5. Textract emits SNS on completion; a separate collector Lambda
       drains that.

Cost contract (sustained moat)
------------------------------
- 100 PDF/day x ~30 pages x $0.05 / page = $150/day.
- The 4 hard-stop tripwires (CW $14K / Budget $17K / slowdown $18.3K /
  Lambda kill $18.7K + Action deny $18.9K) remain primary defence.

SAFETY model
============
- ``JPCITE_PDF_WATCH_ENABLED`` env var gates every side effect. Default
  ``"false"`` — operator opts in explicitly with the deploy script.
- Dry-run logs the *would-submit* envelope and returns ``mode='dry_run'``.
- LLM call budget: 0.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any, Final

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DEFAULT_USER_AGENT: Final[str] = (
    "Bookyou-jpcite-pdf-watch/2026.05.17 (+https://jpcite.com; ops@bookyou.net)"
)
DEFAULT_STAGE_BUCKET: Final[str] = os.environ.get(
    "JPCITE_PDF_WATCH_STAGE_BUCKET", "jpcite-credit-textract-apse1-202605"
)
DEFAULT_TEXTRACT_REGION: Final[str] = os.environ.get("JPCITE_TEXTRACT_REGION", "ap-southeast-1")
DEFAULT_DB_PATH: Final[str] = os.environ.get("JPCITE_AUTONOMATH_DB", "/var/task/autonomath.db")
DEFAULT_SNS_TOPIC_ARN: Final[str] = os.environ.get("JPCITE_TEXTRACT_COMPLETION_TOPIC_ARN", "")
DEFAULT_TEXTRACT_ROLE_ARN: Final[str] = os.environ.get("JPCITE_TEXTRACT_ROLE_ARN", "")


def _enabled() -> bool:
    return os.environ.get("JPCITE_PDF_WATCH_ENABLED", "false").lower() == "true"


def _is_government_host(host: str) -> bool:
    """See ``scripts/cron/pdf_watch_detect_2026_05_17._is_government_host``."""
    if host.endswith(".go.jp") or host.endswith(".lg.jp"):
        return True
    if host.startswith("www.pref.") and host.endswith(".jp"):
        return True
    return bool(host.startswith("web.pref.") and host.endswith(".jp"))


def _http_get_pdf(url: str, *, timeout: float = 30.0) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"refuse non-https: {url!r}")
    host = parsed.hostname or ""
    if not _is_government_host(host):
        raise ValueError(f"refuse non-gov host: {host!r}")
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  # nosec B310 — https-only + gov-domain whitelist enforced above
        body: bytes = resp.read()
    return body


def _s3_input_key(content_hash: str) -> str:
    return f"in/{content_hash[:2]}/{content_hash}.pdf"


def _process_record(
    record: dict[str, Any],
    *,
    boto3: Any | None,
    stage_bucket: str = DEFAULT_STAGE_BUCKET,
    textract_region: str = DEFAULT_TEXTRACT_REGION,
    sns_topic_arn: str = DEFAULT_SNS_TOPIC_ARN,
    textract_role_arn: str = DEFAULT_TEXTRACT_ROLE_ARN,
    db_path: str = DEFAULT_DB_PATH,
    commit_mode: bool = False,
) -> dict[str, Any]:
    """Process a single SQS record. Pure-function with boto3 injected."""
    body = (
        json.loads(record["body"])
        if isinstance(record.get("body"), str)
        else record.get("body", {})
    )
    watch_id = int(body["watch_id"])
    source_url = str(body["source_url"])
    content_hash = str(body["content_hash"])
    source_kind = str(body.get("source_kind", "unknown"))

    s3_key = _s3_input_key(content_hash)
    envelope: dict[str, Any] = {
        "watch_id": watch_id,
        "source_kind": source_kind,
        "source_url": source_url,
        "content_hash": content_hash,
        "s3_input_key": s3_key,
        "stage_bucket": stage_bucket,
        "submitted_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if not commit_mode or boto3 is None:
        envelope["mode"] = "dry_run"
        logger.info("textract_submit_dry_run %s", json.dumps(envelope, ensure_ascii=False))
        return envelope

    pdf_bytes = _http_get_pdf(source_url)
    actual_hash = hashlib.sha256(pdf_bytes).hexdigest()
    if actual_hash != content_hash:
        logger.warning(
            "content_hash_mismatch expected=%s actual=%s url=%s",
            content_hash,
            actual_hash,
            source_url,
        )

    s3 = boto3.client("s3", region_name=textract_region)
    s3.put_object(
        Bucket=stage_bucket,
        Key=s3_key,
        Body=pdf_bytes,
        ContentType="application/pdf",
    )
    textract = boto3.client("textract", region_name=textract_region)
    start_kwargs: dict[str, Any] = {
        "DocumentLocation": {
            "S3Object": {"Bucket": stage_bucket, "Name": s3_key},
        },
        "FeatureTypes": ["TABLES", "FORMS"],
        "OutputConfig": {
            "S3Bucket": stage_bucket,
            "S3Prefix": f"out/{content_hash[:2]}/{content_hash}/",
        },
        "JobTag": f"jpcite-pdf-watch-{watch_id}",
    }
    if sns_topic_arn and textract_role_arn:
        start_kwargs["NotificationChannel"] = {
            "SNSTopicArn": sns_topic_arn,
            "RoleArn": textract_role_arn,
        }
    resp = textract.start_document_analysis(**start_kwargs)
    job_id = resp.get("JobId", "")

    # Best-effort status flip in DB (Lambda's ephemeral sqlite — in
    # production the DB is mounted via EFS or a separate sync worker).
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        try:
            conn.execute(
                """
                UPDATE am_pdf_watch_log
                   SET textract_status = 'submitted',
                       textract_job_id = ?,
                       s3_input_key    = ?,
                       updated_at      = strftime('%Y-%m-%dT%H:%M:%SZ','now')
                 WHERE watch_id = ?
                   AND textract_status = 'pending'
                """,
                (job_id, s3_key, watch_id),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.warning("db_update_skipped watch_id=%s err=%s", watch_id, e)

    envelope["mode"] = "committed"
    envelope["textract_job_id"] = job_id
    logger.info("textract_submit_ok %s", json.dumps(envelope, ensure_ascii=False))
    return envelope


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """SQS-triggered Lambda entry. Iterates ``event['Records']``."""
    boto3: Any
    try:
        import boto3  # type: ignore[import-not-found,unused-ignore,no-redef]
    except ImportError:
        boto3 = None
    commit_mode = _enabled() and boto3 is not None
    summaries: list[dict[str, Any]] = []
    for rec in event.get("Records", []):
        try:
            summaries.append(_process_record(rec, boto3=boto3, commit_mode=commit_mode))
        except Exception as e:  # noqa: BLE001
            logger.exception("record_failed err=%s", e)
            summaries.append({"mode": "failed", "error": str(e)})
    return {
        "tick_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "processed": len(summaries),
        "mode": "committed" if commit_mode else "dry_run",
        "summaries": summaries,
    }
