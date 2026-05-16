"""J16 canonical PDF corpus Textract runner (Singapore region).

J06's ``textract_batch.py`` defaults to ``ap-northeast-1`` (Tokyo) for
the Textract endpoint, but AWS Textract is **not** offered in Tokyo —
the closest available region is ``ap-southeast-1`` (Singapore). The
``start_document_analysis`` API requires the S3 bucket holding the
input PDF to live in the same region as the Textract endpoint, so this
runner stages the PDFs into a Singapore S3 bucket before invoking
Textract.

Cost contract
-------------
* ``$0.05`` per page (AnalyzeDocument with TABLES + FORMS).
* Hard ``--budget-usd 500`` ceiling, warn at 80%.
* Each PDF is treated as one billable unit; we drain the JobId
  pagination so partial-success outputs are still captured.

No LLM calls — Textract is pure OCR + layout reconstruction, the
``request_time_llm_call_performed`` envelope field stays ``False``.

Usage
-----
::

    python scripts/aws_credit_ops/j16_textract_apse1.py \\
        --bucket jpcite-credit-textract-apse1-202605 \\
        --in-prefix J16/in/ \\
        --out-prefix J16/out/ \\
        --budget-usd 500.0 \\
        --per-page-usd 0.05

The input prefix must already contain PDFs with ``.pdf`` suffix and
``ContentType: application/pdf`` metadata; the operator typically
copies them from the Tokyo raw bucket via ``aws s3 sync``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from typing import Any

from scripts.aws_credit_ops._aws import get_session

DEFAULT_PROFILE = "bookyou-recovery"
DEFAULT_REGION = "ap-southeast-1"
DEFAULT_BUDGET_USD = 500.0
DEFAULT_PER_PAGE_USD = 0.05
DEFAULT_WARN_THRESHOLD = 0.80
POLL_INTERVAL_SECONDS = 5.0
POLL_TIMEOUT_SECONDS = 600.0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Stage J16 canonical PDFs into a Singapore S3 bucket and run "
            "Textract AnalyzeDocument (TABLES + FORMS) with a hard budget cap."
        )
    )
    parser.add_argument("--bucket", required=True, help="Singapore S3 bucket name")
    parser.add_argument("--in-prefix", required=True, help="S3 key prefix for input PDFs")
    parser.add_argument("--out-prefix", required=True, help="S3 key prefix for Textract output")
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--per-page-usd", type=float, default=DEFAULT_PER_PAGE_USD)
    parser.add_argument("--warn-threshold", type=float, default=DEFAULT_WARN_THRESHOLD)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--commit", action="store_true", help="Lift DRY_RUN guard")
    return parser.parse_args(argv)


def _list_input_pdfs(s3: Any, bucket: str, prefix: str) -> list[str]:
    """Return the list of ``.pdf`` keys under ``s3://bucket/prefix``."""

    keys: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token is not None:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        for obj in page.get("Contents", []) or []:
            key = obj.get("Key")
            if isinstance(key, str) and key.lower().endswith(".pdf"):
                keys.append(key)
        if not page.get("IsTruncated"):
            break
        token = page.get("NextContinuationToken")
        if not token:
            break
    return keys


def _drain_textract(textract: Any, job_id: str) -> tuple[int, list[dict[str, Any]]]:
    """Poll Textract until the job is done and drain all pages.

    Returns ``(page_count, blocks)`` where ``blocks`` is the union of
    every ``Blocks`` payload across the paginated GET responses.
    """

    deadline = time.time() + POLL_TIMEOUT_SECONDS
    status: str | None = None
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
        resp = textract.get_document_analysis(JobId=job_id)
        status = resp.get("JobStatus")
        if status in ("SUCCEEDED", "FAILED", "PARTIAL_SUCCESS"):
            break
    if status not in ("SUCCEEDED", "PARTIAL_SUCCESS"):
        return 0, []

    blocks: list[dict[str, Any]] = []
    token: str | None = None
    page_count = 0
    while True:
        kwargs: dict[str, Any] = {"JobId": job_id}
        if token:
            kwargs["NextToken"] = token
        resp = textract.get_document_analysis(**kwargs)
        blocks.extend(resp.get("Blocks", []))
        page_count = max(page_count, resp.get("DocumentMetadata", {}).get("Pages", 0))
        token = resp.get("NextToken")
        if not token:
            break
    return page_count, blocks


def _project(blocks: list[dict[str, Any]]) -> tuple[list[str], int, int]:
    """Project Textract blocks into ``(line_text, table_count, form_count)``."""

    lines: list[str] = []
    table_count = 0
    form_count = 0
    for b in blocks:
        bt = b.get("BlockType")
        if bt == "LINE":
            text = b.get("Text", "")
            if isinstance(text, str) and text:
                lines.append(text)
        elif bt == "TABLE":
            table_count += 1
        elif bt == "KEY_VALUE_SET":
            entity_types = b.get("EntityTypes") or []
            if "KEY" in entity_types:
                form_count += 1
    return lines, table_count, form_count


def run(args: argparse.Namespace) -> int:
    sess = get_session(region_name=args.region, profile_name=args.profile)
    s3 = sess.client("s3")
    textract = sess.client("textract")

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    print(
        f"[j16_textract] run_id={run_id} region={args.region} bucket={args.bucket} "
        f"commit={args.commit} budget=${args.budget_usd:.2f}"
    )

    keys = _list_input_pdfs(s3, args.bucket, args.in_prefix)
    print(f"[j16_textract] listed {len(keys)} PDFs under s3://{args.bucket}/{args.in_prefix}")
    if not keys:
        print("[j16_textract] EMPTY input — abort")
        return 2
    if not args.commit:
        projected = len(keys) * 5 * args.per_page_usd
        print(
            f"[j16_textract] DRY_RUN: {len(keys)} PDFs × 5 pg avg × ${args.per_page_usd} "
            f"= ${projected:.2f} projected. Pass --commit to run live."
        )
        return 0

    total_pages = 0
    total_spend = 0.0
    results: list[dict[str, Any]] = []
    stop_reason: str | None = None

    for i, key in enumerate(keys, 1):
        print(f"[j16_textract] [{i}/{len(keys)}] start {key}")
        try:
            start = textract.start_document_analysis(
                DocumentLocation={"S3Object": {"Bucket": args.bucket, "Name": key}},
                FeatureTypes=["TABLES", "FORMS"],
            )
        except Exception as exc:  # noqa: BLE001 - live AWS path
            print(f"[j16_textract] [{i}] start FAIL: {type(exc).__name__}: {exc}")
            results.append({"key": key, "status": "start_failed", "error": str(exc)[:200]})
            continue
        job_id = start["JobId"]
        print(f"[j16_textract] [{i}] job_id={job_id} polling...")
        page_count, blocks = _drain_textract(textract, job_id)
        if not blocks:
            print(f"[j16_textract] [{i}] no blocks returned, skip")
            results.append({"key": key, "status": "no_blocks", "job_id": job_id})
            continue

        lines, table_count, form_count = _project(blocks)
        spend = page_count * args.per_page_usd
        total_pages += page_count
        total_spend += spend
        print(
            f"[j16_textract] [{i}] SUCCESS pages={page_count} lines={len(lines)} "
            f"tables={table_count} forms={form_count} spend=${spend:.2f} "
            f"total=${total_spend:.2f}"
        )

        out_key = f"{args.out_prefix}{run_id}/{key.split('/')[-1].replace('.pdf', '.json')}"
        body = json.dumps(
            {
                "source_key": key,
                "job_id": job_id,
                "page_count": page_count,
                "extracted_text": "\n".join(lines),
                "table_count": table_count,
                "form_count": form_count,
                "block_count": len(blocks),
                "request_time_llm_call_performed": False,
            },
            ensure_ascii=False,
        )
        s3.put_object(
            Bucket=args.bucket,
            Key=out_key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )
        results.append(
            {
                "key": key,
                "status": "succeeded",
                "page_count": page_count,
                "spend_usd": spend,
                "output_key": out_key,
            }
        )

        if total_spend >= args.budget_usd:
            stop_reason = f"budget_exceeded after pdf {i}"
            print(f"[j16_textract] STOP: {stop_reason}")
            break
        if total_spend >= args.budget_usd * args.warn_threshold:
            print(f"[j16_textract] WARN: crossed 80% of budget at pdf {i}")

    manifest = {
        "run_id": run_id,
        "region": args.region,
        "bucket": args.bucket,
        "input_prefix": args.in_prefix,
        "output_prefix": args.out_prefix,
        "pdf_count_listed": len(keys),
        "pdf_count_analyzed": sum(1 for r in results if r["status"] == "succeeded"),
        "page_count_total": total_pages,
        "spend_usd": total_spend,
        "budget_usd": args.budget_usd,
        "per_page_usd": args.per_page_usd,
        "stop_reason": stop_reason,
        "results": results,
        "request_time_llm_call_performed": False,
    }
    manifest_key = f"{args.out_prefix}{run_id}/run_manifest.json"
    s3.put_object(
        Bucket=args.bucket,
        Key=manifest_key,
        Body=json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    print(f"[j16_textract] manifest -> s3://{args.bucket}/{manifest_key}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if stop_reason is None else 2


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return run(args)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
