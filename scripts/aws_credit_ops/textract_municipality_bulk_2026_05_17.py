"""DD2 — Municipality subsidy PDF Textract bulk runner (2026-05-17).

Drains the PDFs that ``scripts/etl/crawl_municipality_subsidy_2026_05_17.py``
staged in the Tokyo derived bucket under ``municipality_pdf_raw/`` through
AWS Textract ``start_document_analysis`` (TABLES + FORMS), captures the
``JobId`` + structured blocks, and writes results to::

    s3://jpcite-credit-993693061769-202605-derived/municipality_ocr/
        <municipality_code>/<sha256_prefix>.json

Region geography
----------------

Textract is **NOT** offered in Tokyo (``ap-northeast-1``) — the Singapore
region (``ap-southeast-1``) is the closest endpoint, and ``start_document_
analysis`` requires the input bucket to live in the same region. We
follow ``j16_textract_apse1.py`` / ``textract_bulk_submit_2026_05_17.py``
and stage into the Singapore bucket ``jpcite-credit-textract-apse1-202605``
under ``dd2_in/<sha[:2]>/<sha>.pdf`` before invoking Textract.

Cost contract
-------------

* ``$0.05`` per page (AnalyzeDocument TABLES + FORMS).
* DD2 manifest 1,714 自治体 × 3-5 PDF avg × 15 pages = ~6,000 PDF, $4,500
  worst case.
* Hard ``--budget-usd 4500`` ceiling, warn at 80%.
* DRY_RUN default. ``--commit`` lifts the guard (operator UNLOCK required
  upstream — this script is invoked as part of the DD2 Geo expansion lane).
* Each Textract call is logged so partial-success outputs are still
  captured if the budget cap trips mid-run.

Constraints
-----------

* NO LLM calls. Pure boto3 + S3 + Textract + Python regex.
* DRY_RUN default — ``--commit`` required to bill anything.
* mypy --strict clean. Lazy ``boto3`` import via ``_aws.py``.
* ``[lane:solo]`` marker — same-file refactor protection.

Usage
-----

::

    # Dry-run (no AWS calls, just enumerate).
    .venv/bin/python scripts/aws_credit_ops/textract_municipality_bulk_2026_05_17.py \\
        --dry-run --max-pdfs 200

    # Wet run (operator-authorised, $4,500 budget cap).
    .venv/bin/python scripts/aws_credit_ops/textract_municipality_bulk_2026_05_17.py \\
        --raw-bucket jpcite-credit-993693061769-202605-derived \\
        --raw-prefix municipality_pdf_raw/ \\
        --stage-bucket jpcite-credit-textract-apse1-202605 \\
        --out-bucket  jpcite-credit-993693061769-202605-derived \\
        --out-prefix  municipality_ocr/ \\
        --budget-usd 4500 \\
        --max-pdfs 6500 \\
        --commit

Exit codes
----------
0  success or budget-cap hit cleanly
1  fatal (manifest missing, AWS unreachable, budget cap exceeded mid-job)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("jpcite.aws.dd2_textract_municipality_bulk")

_REPO_ROOT = Path(__file__).resolve().parents[2]

_DEFAULT_RAW_BUCKET = "jpcite-credit-993693061769-202605-derived"
_DEFAULT_RAW_PREFIX = "municipality_pdf_raw/"
_DEFAULT_STAGE_BUCKET = "jpcite-credit-textract-apse1-202605"
_DEFAULT_STAGE_PREFIX = "dd2_in/"
_DEFAULT_OUT_BUCKET = "jpcite-credit-993693061769-202605-derived"
_DEFAULT_OUT_PREFIX = "municipality_ocr/"
_DEFAULT_TEXTRACT_REGION = "ap-southeast-1"
_DEFAULT_RAW_REGION = "ap-northeast-1"
_DEFAULT_PER_PAGE_USD = 0.05
_DEFAULT_BUDGET_USD = 4500.0
_DEFAULT_MAX_PDFS = 6500
_DEFAULT_WARN_THRESHOLD = 0.80
_DEFAULT_POLL_INTERVAL_SECONDS = 5.0
_DEFAULT_POLL_TIMEOUT_SECONDS = 600.0
_DEFAULT_USER_AGENT = "Bookyou-jpcite-dd2-textract/2026.05.17 (+https://jpcite.ai; ops@bookyou.net)"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-bucket", default=_DEFAULT_RAW_BUCKET)
    parser.add_argument("--raw-prefix", default=_DEFAULT_RAW_PREFIX)
    parser.add_argument("--raw-region", default=_DEFAULT_RAW_REGION)
    parser.add_argument("--stage-bucket", default=_DEFAULT_STAGE_BUCKET)
    parser.add_argument("--stage-prefix", default=_DEFAULT_STAGE_PREFIX)
    parser.add_argument("--out-bucket", default=_DEFAULT_OUT_BUCKET)
    parser.add_argument("--out-prefix", default=_DEFAULT_OUT_PREFIX)
    parser.add_argument("--textract-region", default=_DEFAULT_TEXTRACT_REGION)
    parser.add_argument("--per-page-usd", type=float, default=_DEFAULT_PER_PAGE_USD)
    parser.add_argument("--budget-usd", type=float, default=_DEFAULT_BUDGET_USD)
    parser.add_argument("--max-pdfs", type=int, default=_DEFAULT_MAX_PDFS)
    parser.add_argument("--warn-threshold", type=float, default=_DEFAULT_WARN_THRESHOLD)
    parser.add_argument("--poll-interval", type=float, default=_DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--poll-timeout", type=float, default=_DEFAULT_POLL_TIMEOUT_SECONDS)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Lift DRY_RUN — actually invoke Textract and bill the AWS account.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run (default if --commit absent).",
    )
    parser.add_argument(
        "--per-page-pages",
        type=int,
        default=15,
        help="Page-count assumption per PDF for budget guard (default 15).",
    )
    return parser.parse_args(argv)


def _list_raw_pdfs(
    s3_client: Any,
    *,
    bucket: str,
    prefix: str,
    limit: int,
) -> list[dict[str, str]]:
    """Enumerate PDFs under the Tokyo raw bucket prefix.

    Returns ``[{"key": str, "municipality_code": str, "sha_prefix": str}, ...]``.
    """
    out: list[dict[str, str]] = []
    token: str | None = None
    while len(out) < limit:
        kwargs: dict[str, Any] = {
            "Bucket": bucket,
            "Prefix": prefix,
            "MaxKeys": min(1000, limit - len(out)),
        }
        if token:
            kwargs["ContinuationToken"] = token
        resp = s3_client.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".pdf"):
                continue
            # Key shape: {prefix}{municipality_code}/{sha16}.pdf
            tail = key[len(prefix.rstrip("/")) :].lstrip("/")
            parts = tail.split("/")
            if len(parts) < 2:
                continue
            out.append(
                {
                    "key": key,
                    "municipality_code": parts[0],
                    "sha_prefix": Path(parts[-1]).stem,
                }
            )
            if len(out) >= limit:
                break
        token = resp.get("NextContinuationToken") if resp.get("IsTruncated") else None
        if not token:
            break
    return out


def _copy_to_singapore(
    *,
    s3_tokyo: Any,
    s3_singapore: Any,
    src_bucket: str,
    src_key: str,
    dst_bucket: str,
    dst_key: str,
) -> int:
    """Copy a single PDF from Tokyo bucket → Singapore staging.

    Returns the byte size of the copied object.
    """
    head = s3_tokyo.head_object(Bucket=src_bucket, Key=src_key)
    size = int(head.get("ContentLength") or 0)
    # boto3 copy_object can do cross-region copies if the IAM role allows
    # cross-region GetObject from src bucket. The simpler path is to GET
    # the bytes in Tokyo and PUT them in Singapore — small PDFs (avg <2 MB).
    body = s3_tokyo.get_object(Bucket=src_bucket, Key=src_key)["Body"].read()
    s3_singapore.put_object(
        Bucket=dst_bucket,
        Key=dst_key,
        Body=body,
        ContentType="application/pdf",
        Metadata={
            "source_bucket": src_bucket,
            "source_key": src_key[:1024],
            "copied_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    return size


def _submit_textract(
    textract_client: Any,
    *,
    stage_bucket: str,
    stage_key: str,
    out_bucket: str,
    out_prefix: str,
) -> str:
    """Submit ``start_document_analysis`` and return the JobId."""
    out_prefix_path = f"{out_prefix.rstrip('/')}/{Path(stage_key).stem}/"
    resp = textract_client.start_document_analysis(
        DocumentLocation={"S3Object": {"Bucket": stage_bucket, "Name": stage_key}},
        FeatureTypes=["TABLES", "FORMS"],
        OutputConfig={"S3Bucket": out_bucket, "S3Prefix": out_prefix_path},
    )
    return str(resp["JobId"])


def _poll_textract(
    textract_client: Any,
    *,
    job_id: str,
    interval: float,
    timeout: float,
) -> tuple[str, int, float]:
    """Poll a Textract job until done or timeout.

    Returns ``(status, page_count, mean_confidence)``.
    """
    start = time.monotonic()
    while True:
        resp = textract_client.get_document_analysis(JobId=job_id, MaxResults=1)
        status = str(resp.get("JobStatus", "UNKNOWN"))
        if status in ("SUCCEEDED", "FAILED", "PARTIAL_SUCCESS"):
            meta = resp.get("DocumentMetadata", {}) or {}
            page_count = int(meta.get("Pages") or 0)
            blocks = resp.get("Blocks", []) or []
            confidences = [
                float(b["Confidence"]) for b in blocks if isinstance(b, dict) and "Confidence" in b
            ]
            mean_conf = sum(confidences) / len(confidences) / 100.0 if confidences else 0.0
            return status, page_count, mean_conf
        if time.monotonic() - start > timeout:
            return "TIMEOUT", 0, 0.0
        time.sleep(interval)


def _run(args: argparse.Namespace) -> int:
    """Main driver — DRY_RUN by default, --commit lifts the guard."""
    commit = bool(args.commit) and not bool(args.dry_run)
    logger.info(
        "DD2 textract start commit=%s raw=%s/%s stage=%s/%s out=%s/%s region=%s",
        commit,
        args.raw_bucket,
        args.raw_prefix,
        args.stage_bucket,
        args.stage_prefix,
        args.out_bucket,
        args.out_prefix,
        args.textract_region,
    )

    # Pre-flight budget guard: do not even start if budget already <= 0.
    if args.budget_usd <= 0:
        sys.stderr.write("FATAL: --budget-usd must be > 0\n")
        return 1

    from scripts.aws_credit_ops._aws import get_client
    from scripts.aws_credit_ops._aws import s3_client as _s3_factory
    from scripts.aws_credit_ops._aws import textract_client as _textract_factory

    s3_tokyo = _s3_factory(region_name=args.raw_region)
    s3_singapore = get_client("s3", region_name=args.textract_region)
    textract = _textract_factory(region_name=args.textract_region)

    pdfs = _list_raw_pdfs(
        s3_tokyo,
        bucket=args.raw_bucket,
        prefix=args.raw_prefix,
        limit=args.max_pdfs,
    )
    logger.info("DD2 textract: enumerated %d PDFs", len(pdfs))

    # Budget envelope.
    spent_usd = 0.0
    pages_processed = 0
    jobs_submitted = 0
    jobs_succeeded = 0
    jobs_failed = 0
    jobs_skipped_dryrun = 0

    ledger: list[dict[str, Any]] = []

    for idx, pdf in enumerate(pdfs):
        stage_key = (
            f"{args.stage_prefix.rstrip('/')}/{pdf['sha_prefix'][:2]}/{pdf['sha_prefix']}.pdf"
        )

        # Budget projection: stop if next job would exceed the cap.
        projected_next_cost = args.per_page_usd * float(args.per_page_pages)
        if spent_usd + projected_next_cost > args.budget_usd:
            logger.warning(
                "DD2 textract: budget cap reached spent=$%.2f cap=$%.2f — stopping",
                spent_usd,
                args.budget_usd,
            )
            break

        ledger_row: dict[str, Any] = {
            "municipality_code": pdf["municipality_code"],
            "sha_prefix": pdf["sha_prefix"],
            "raw_key": pdf["key"],
            "stage_key": stage_key,
            "commit": commit,
            "submitted_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        if not commit:
            jobs_skipped_dryrun += 1
            ledger_row["status"] = "DRY_RUN"
            ledger.append(ledger_row)
            continue

        # 1) Copy to Singapore staging bucket.
        try:
            byte_size = _copy_to_singapore(
                s3_tokyo=s3_tokyo,
                s3_singapore=s3_singapore,
                src_bucket=args.raw_bucket,
                src_key=pdf["key"],
                dst_bucket=args.stage_bucket,
                dst_key=stage_key,
            )
            ledger_row["byte_size"] = byte_size
        except Exception as exc:  # noqa: BLE001
            jobs_failed += 1
            ledger_row["status"] = f"COPY_ERROR:{exc.__class__.__name__}"
            ledger.append(ledger_row)
            continue

        # 2) Submit Textract job.
        try:
            job_id = _submit_textract(
                textract,
                stage_bucket=args.stage_bucket,
                stage_key=stage_key,
                out_bucket=args.out_bucket,
                out_prefix=args.out_prefix,
            )
            jobs_submitted += 1
            ledger_row["job_id"] = job_id
        except Exception as exc:  # noqa: BLE001
            jobs_failed += 1
            ledger_row["status"] = f"SUBMIT_ERROR:{exc.__class__.__name__}"
            ledger.append(ledger_row)
            continue

        # 3) Poll until done.
        status, page_count, mean_conf = _poll_textract(
            textract,
            job_id=job_id,
            interval=args.poll_interval,
            timeout=args.poll_timeout,
        )
        ledger_row["status"] = status
        ledger_row["page_count"] = page_count
        ledger_row["mean_confidence"] = mean_conf
        ledger.append(ledger_row)

        if status == "SUCCEEDED" or status == "PARTIAL_SUCCESS":
            jobs_succeeded += 1
        else:
            jobs_failed += 1

        cost_this_job = args.per_page_usd * float(page_count or args.per_page_pages)
        spent_usd += cost_this_job
        pages_processed += page_count

        if spent_usd >= args.budget_usd * args.warn_threshold:
            logger.warning(
                "DD2 textract: %d%% of budget spent ($%.2f / $%.2f)",
                int(100 * spent_usd / args.budget_usd),
                spent_usd,
                args.budget_usd,
            )

        if (idx + 1) % 50 == 0:
            logger.info(
                "DD2 progress: %d/%d done, $%.2f spent, %d pages",
                idx + 1,
                len(pdfs),
                spent_usd,
                pages_processed,
            )

    summary = {
        "commit": commit,
        "pdfs_enumerated": len(pdfs),
        "jobs_submitted": jobs_submitted,
        "jobs_succeeded": jobs_succeeded,
        "jobs_failed": jobs_failed,
        "jobs_skipped_dryrun": jobs_skipped_dryrun,
        "pages_processed": pages_processed,
        "spent_usd": round(spent_usd, 4),
        "budget_usd": args.budget_usd,
        "finished_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    # Persist the ledger alongside the manifest so a follow-up structured
    # ingest step can resume from JobIds without re-running OCR.
    ledger_path = _REPO_ROOT / "data" / "textract_municipality_bulk_2026_05_17_ledger.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps(
            {"summary": summary, "rows": ledger},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("DD2 textract summary %s", summary)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entrypoint."""
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return _run(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
