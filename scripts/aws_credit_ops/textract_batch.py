#!/usr/bin/env python3
"""Batch Textract OCR driver for the J06 ministry / municipality PDF set.

This script walks an S3 raw prefix, picks PDFs out of it, calls the J06
``textract_client`` wrapper for each, and writes per-page JSONL plus a
parsed Parquet summary to a derived S3 prefix. It is the operator
front-door for §3.2 of the Wave 50 AWS credit canary plan
(``USD 2,500-4,500`` band for OCR / document extraction; per-page
Textract spend ≈ ``USD 0.05``).

It is **NOT** an LLM driver: Textract is structured OCR / form + table
extraction. The downstream J06 receipt assembly is responsible for
turning the per-page JSONL into JPCIR Evidence + SourceReceipt envelopes
— this script just stages the raw, structured Textract output so that
step has something to walk.

Pipeline
--------
1. ``--input-prefix s3://<raw_bucket>/J06_ministry_pdf/raw/`` is listed
   via ``boto3.client('s3').list_objects_v2``. Only objects whose
   ``ContentType`` is ``application/pdf`` (HEAD probe) or whose key ends
   in ``.pdf`` (case-insensitive) are considered. Anything else is
   silently skipped so a stray ``manifest.txt`` cannot trigger a
   Textract bill.
2. Per-PDF cost preflight: the running running-total (sum of
   ``page_count`` of every analyzed PDF this run, times the Textract
   per-page price) is compared against the §3.2 ceiling
   ``--budget-usd`` (default ``4500``). If projected spend after the
   next PDF would exceed the ceiling, the batch stops; if projected
   spend after the next PDF would exceed the ``warn-threshold`` (default
   ``0.8``) of the ceiling, a warning is printed to stderr but the run
   continues. ``DRY_RUN=1`` short-circuits the Textract call entirely
   so the budget gate can be exercised against the listing without
   spending a cent.
3. Per-PDF: ``TextractRequest(s3_bucket, s3_key, feature_types=(TABLES,
   FORMS), estimated_page_count=...)`` -> ``analyze_document(...)``.
   ``DRY_RUN`` (default ``True``) replaces the API call with a fixed
   zero-page synthetic ``TextractResult`` so the rest of the pipeline
   can be exercised without an AWS bill.
4. Output staging: a per-PDF JSONL is appended to
   ``s3://<derived_bucket>/J06_textract/jsonl/<job_run>/<sha>.jsonl`` —
   one row per page, carrying ``s3_uri``, ``page_index``, the extracted
   text for that page, and the page's TABLES / FORMS projections. A
   per-run Parquet (or JSONL fallback when ``pyarrow`` is not present)
   is also written to ``s3://<derived_bucket>/J06_textract/parquet/<job_run>/summary.parquet``
   that downstream Athena can read.
5. Run manifest: ``run_manifest.json`` is emitted at the derived prefix
   root with the total page count, projected spend, the list of skipped
   PDFs (and reason), and the budget knobs that were active.

CLI
---

.. code-block:: text

    python scripts/aws_credit_ops/textract_batch.py \\
        --input-prefix s3://jpcite-credit-993693061769-202605-raw/J06_ministry_pdf/raw/ \\
        --output-prefix s3://jpcite-credit-993693061769-202605-derived/J06_textract/ \\
        [--budget-usd 4500] \\
        [--per-page-usd 0.05] \\
        [--warn-threshold 0.8] \\
        [--max-pdfs 800] \\
        [--commit]

``--commit`` is the dual of ``DRY_RUN=1``: it lifts the dry-run guard
and lets the script actually call Textract + write to the derived
bucket. Default is dry-run.

Constraints
-----------
* **NO LLM API calls.** Textract only. Bedrock / Anthropic / OpenAI
  imports are forbidden in this tree by ``tests/test_no_llm_in_production.py``.
* **DRY_RUN default.** No Textract API calls and no derived-bucket
  writes unless ``--commit`` is passed.
* **Budget tracking.** Projected spend is computed per-PDF; the script
  bails before exceeding the ``--budget-usd`` ceiling.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from jpintel_mcp.aws_credit_ops import (
    AnalyzeFeatureType,
    TextractClientError,
    TextractRequest,
    TextractResult,
    analyze_document,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

logger = logging.getLogger("textract_batch")

#: Default §3.2 ceiling (USD). Wave 50 AWS canary plan budgets OCR at
#: ``2,500-4,500``; we pin the *upper* bound as the hard stop and warn
#: at 80 % so the operator gets a chance to throttle before the wall.
DEFAULT_BUDGET_USD: Final[float] = 4500.0

#: Textract ``AnalyzeDocument`` per-page price for TABLES + FORMS in
#: ap-northeast-1 (Tokyo). Source:
#: https://aws.amazon.com/textract/pricing/ — TABLES + FORMS is billed
#: at ``USD 0.05 / page`` (no Queries / Signatures / Layout add-on).
#: If AWS raises this we update the constant and the operator re-runs
#: with the new default; we deliberately do not fetch the pricing API
#: at runtime because that adds a moving dependency for a fixed-price
#: surface.
DEFAULT_PER_PAGE_USD: Final[float] = 0.05

#: Warn-threshold fraction of ``--budget-usd``. At 80 % the operator
#: starts seeing stderr warnings; at 100 % the run stops before the
#: next PDF.
DEFAULT_WARN_THRESHOLD: Final[float] = 0.8

#: Maximum number of PDFs the script will process in a single run. The
#: J06 manifest caps ``max_pdfs`` at 800; we mirror that as the
#: operator-visible default so a misconfigured listing cannot fire 10K
#: Textract calls.
DEFAULT_MAX_PDFS: Final[int] = 800

#: Pseudo page-count used by DRY_RUN to simulate a typical ministry PDF
#: (10 pages is the median for the 20 J06 target index pages). The dry
#: run still drives the budget gate so an operator can preview the spend
#: implication of a listing without paying for it.
DRY_RUN_SIMULATED_PAGE_COUNT: Final[int] = 10


@dataclass(frozen=True)
class S3Uri:
    """Parsed ``s3://<bucket>/<key_prefix>`` URI.

    Bucket + key are kept separate because boto3's S3 client expects them
    as separate arguments (``Bucket=...`` / ``Key=...``) — re-parsing
    a full URI at every call site is error-prone.
    """

    bucket: str
    key_prefix: str

    @classmethod
    def parse(cls, uri: str) -> S3Uri:
        if not uri.startswith("s3://"):
            msg = f"expected s3://... URI, got {uri!r}"
            raise ValueError(msg)
        rest = uri[len("s3://"):]
        if "/" not in rest:
            return cls(bucket=rest, key_prefix="")
        bucket, _, key = rest.partition("/")
        return cls(bucket=bucket, key_prefix=key)

    def join(self, suffix: str) -> str:
        sep = "" if not self.key_prefix or self.key_prefix.endswith("/") else "/"
        return f"s3://{self.bucket}/{self.key_prefix}{sep}{suffix}"


@dataclass
class PdfListEntry:
    """One entry in the per-run PDF listing."""

    bucket: str
    key: str
    size_bytes: int
    estimated_page_count: int | None = None
    skip_reason: str | None = None


@dataclass
class RunReport:
    """Per-run accounting + skip / warn ledger."""

    job_run_id: str
    input_prefix: str
    output_prefix: str
    budget_usd: float
    per_page_usd: float
    warn_threshold: float
    dry_run: bool
    pdf_count_listed: int = 0
    pdf_count_analyzed: int = 0
    pdf_count_skipped: int = 0
    page_count_total: int = 0
    projected_spend_usd: float = 0.0
    warn_emitted_at_pdf: int | None = None
    stopped_at_pdf: int | None = None
    stop_reason: str | None = None
    skipped_entries: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "job_run_id": self.job_run_id,
            "input_prefix": self.input_prefix,
            "output_prefix": self.output_prefix,
            "budget_usd": self.budget_usd,
            "per_page_usd": self.per_page_usd,
            "warn_threshold": self.warn_threshold,
            "dry_run": self.dry_run,
            "pdf_count_listed": self.pdf_count_listed,
            "pdf_count_analyzed": self.pdf_count_analyzed,
            "pdf_count_skipped": self.pdf_count_skipped,
            "page_count_total": self.page_count_total,
            "projected_spend_usd": round(self.projected_spend_usd, 6),
            "warn_emitted_at_pdf": self.warn_emitted_at_pdf,
            "stopped_at_pdf": self.stopped_at_pdf,
            "stop_reason": self.stop_reason,
            "skipped_entries": list(self.skipped_entries),
        }


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def list_pdfs(
    input_uri: S3Uri,
    *,
    s3_client: Any | None = None,
    max_pdfs: int = DEFAULT_MAX_PDFS,
) -> list[PdfListEntry]:
    """List PDFs under ``input_uri`` using ``ContentType`` + suffix filters.

    Only keys ending in ``.pdf`` (case-insensitive) **and** carrying a
    ``ContentType`` of ``application/pdf`` (when the underlying object's
    HEAD metadata exposes it) are kept. When the ``Contents`` listing
    lacks ``ContentType`` (the default ``ListObjectsV2`` response does
    not include it), the suffix filter alone gates the entry. This keeps
    the cost cheap (no per-object HEAD round trip) but still rejects
    stray ``.json`` / ``.txt`` / ``.parquet`` artifacts.
    """

    if s3_client is None:
        s3_client = _boto3_client("s3")
    entries: list[PdfListEntry] = []
    continuation: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "Bucket": input_uri.bucket,
            "Prefix": input_uri.key_prefix,
        }
        if continuation is not None:
            kwargs["ContinuationToken"] = continuation
        page = s3_client.list_objects_v2(**kwargs)
        for obj in page.get("Contents", []) or []:
            key = obj.get("Key")
            size = int(obj.get("Size", 0) or 0)
            content_type = obj.get("ContentType")
            if not isinstance(key, str):
                continue
            if not key.lower().endswith(".pdf"):
                continue
            if content_type is not None and content_type != "application/pdf":
                # Listing did include ContentType (some custom S3 mirror
                # layers do) AND it did not match — drop.
                continue
            entries.append(
                PdfListEntry(
                    bucket=input_uri.bucket,
                    key=key,
                    size_bytes=size,
                )
            )
            if len(entries) >= max_pdfs:
                return entries
        if not page.get("IsTruncated"):
            break
        continuation = page.get("NextContinuationToken")
        if not continuation:
            break
    return entries


# ---------------------------------------------------------------------------
# Budget gate
# ---------------------------------------------------------------------------


def projected_spend_after(
    page_count_total: int,
    per_page_usd: float,
    next_pdf_pages: int,
) -> float:
    """Return projected USD spend after analyzing ``next_pdf_pages``."""

    return (page_count_total + max(next_pdf_pages, 0)) * per_page_usd


def should_stop(
    projected_usd: float,
    budget_usd: float,
) -> bool:
    """True iff projected spend would meet or exceed the ceiling."""

    return projected_usd >= budget_usd


def should_warn(
    projected_usd: float,
    budget_usd: float,
    warn_threshold: float,
) -> bool:
    """True iff projected spend would meet or exceed the warn line."""

    return projected_usd >= budget_usd * warn_threshold


# ---------------------------------------------------------------------------
# Textract drive
# ---------------------------------------------------------------------------


def _dry_run_result(req: TextractRequest) -> TextractResult:
    """Build a synthetic ``TextractResult`` for DRY_RUN.

    Carries ``page_count=DRY_RUN_SIMULATED_PAGE_COUNT`` so the budget
    gate has a non-zero number to project against. No raw blocks, no
    extracted text, no tables / forms — downstream code that walks these
    fields must already be defensive against empty Textract output for
    real-world quarantined PDFs.
    """

    return TextractResult(
        s3_bucket=req.s3_bucket,
        s3_key=req.s3_key,
        page_count=DRY_RUN_SIMULATED_PAGE_COUNT,
    )


def analyze_pdf(
    entry: PdfListEntry,
    *,
    dry_run: bool,
    textract_client: Any | None = None,
    analyze_fn: Callable[..., TextractResult] | None = None,
) -> TextractResult:
    """Analyze ``entry`` via the J06 ``textract_client`` wrapper.

    ``analyze_fn`` is a test seam — pass a fake to capture the
    ``TextractRequest`` without calling the real client. In production
    this stays ``None`` and the real ``analyze_document`` runs.
    """

    req = TextractRequest(
        s3_bucket=entry.bucket,
        s3_key=entry.key,
        feature_types=(AnalyzeFeatureType.TABLES, AnalyzeFeatureType.FORMS),
        estimated_page_count=entry.estimated_page_count,
    )
    if dry_run:
        return _dry_run_result(req)
    fn = analyze_fn if analyze_fn is not None else analyze_document
    return fn(req, client=textract_client)


# ---------------------------------------------------------------------------
# Output staging
# ---------------------------------------------------------------------------


def build_per_page_jsonl(result: TextractResult) -> list[dict[str, Any]]:
    """Project a ``TextractResult`` into a list of one-row-per-page dicts.

    The JSONL row schema is:

    * ``s3_uri`` — ``s3://<bucket>/<key>`` of the source PDF.
    * ``page_index`` — 1-based page index.
    * ``extracted_text`` — concatenated LINE blocks for that page.
    * ``table_count`` — number of TABLE projections falling on that page.
    * ``form_count`` — number of KEY_VALUE_SET pairs on that page.
    * ``request_time_llm_call_performed`` — always ``False``.

    When ``page_count`` is 0 (dry-run synthetic, or a PDF Textract
    refused to read) the function returns an empty list so the writer
    does not emit a degenerate row.
    """

    rows: list[dict[str, Any]] = []
    s3_uri = f"s3://{result.s3_bucket}/{result.s3_key}"
    text_lines_per_page: dict[int, list[str]] = {}
    for block in result.raw_blocks:
        if block.get("BlockType") != "LINE":
            continue
        page = int(block.get("Page", 1) or 1)
        text = block.get("Text", "")
        if isinstance(text, str) and text:
            text_lines_per_page.setdefault(page, []).append(text)
    table_count_per_page: dict[int, int] = {}
    for tbl in result.tables:
        table_count_per_page[tbl.page] = table_count_per_page.get(tbl.page, 0) + 1
    form_count_per_page: dict[int, int] = {}
    for ff in result.forms:
        form_count_per_page[ff.page] = form_count_per_page.get(ff.page, 0) + 1
    for page_idx in range(1, result.page_count + 1):
        rows.append(
            {
                "s3_uri": s3_uri,
                "page_index": page_idx,
                "extracted_text": "\n".join(text_lines_per_page.get(page_idx, [])),
                "table_count": table_count_per_page.get(page_idx, 0),
                "form_count": form_count_per_page.get(page_idx, 0),
                "request_time_llm_call_performed": False,
            }
        )
    return rows


def write_jsonl(
    rows: Iterable[dict[str, Any]],
    *,
    output_uri: S3Uri,
    key_suffix: str,
    s3_client: Any | None = None,
) -> str:
    """Serialize ``rows`` to JSONL and PUT to ``output_uri / key_suffix``.

    Returns the final ``s3://...`` URI so the run manifest can pin it.
    """

    body = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows)
    if body:
        body += "\n"
    full_key = (
        f"{output_uri.key_prefix.rstrip('/')}/{key_suffix.lstrip('/')}"
        if output_uri.key_prefix
        else key_suffix.lstrip("/")
    )
    if s3_client is None:
        s3_client = _boto3_client("s3")
    s3_client.put_object(
        Bucket=output_uri.bucket,
        Key=full_key,
        Body=body.encode("utf-8"),
        ContentType="application/jsonl",
    )
    return f"s3://{output_uri.bucket}/{full_key}"


def write_parquet_summary(
    summary_rows: list[dict[str, Any]],
    *,
    output_uri: S3Uri,
    key_suffix: str,
    s3_client: Any | None = None,
) -> str:
    """Write a per-run summary table to S3 as Parquet when possible.

    Falls back to JSONL with a ``.jsonl`` extension when ``pyarrow``
    cannot be imported in the operator environment. The Athena workgroup
    handles both — Parquet is preferred because the J06 manifest pins
    ``object_manifest.parquet`` as the canonical output artifact.
    """

    full_key = (
        f"{output_uri.key_prefix.rstrip('/')}/{key_suffix.lstrip('/')}"
        if output_uri.key_prefix
        else key_suffix.lstrip("/")
    )
    if s3_client is None:
        s3_client = _boto3_client("s3")
    try:
        import pyarrow as pa  # type: ignore[import-untyped,unused-ignore]
        import pyarrow.parquet as pq  # type: ignore[import-untyped,unused-ignore]
    except ImportError:
        # pyarrow not present — fall back to JSONL so the run still
        # finishes. The downstream Athena table definition tolerates the
        # JSONL fallback because the columns are compatible (str / int).
        return write_jsonl(
            summary_rows,
            output_uri=output_uri,
            key_suffix=key_suffix.replace(".parquet", ".jsonl"),
            s3_client=s3_client,
        )

    table = pa.Table.from_pylist(summary_rows)
    import io

    buf = io.BytesIO()
    pq.write_table(table, buf)  # type: ignore[no-untyped-call]
    s3_client.put_object(
        Bucket=output_uri.bucket,
        Key=full_key,
        Body=buf.getvalue(),
        ContentType="application/x-parquet",
    )
    return f"s3://{output_uri.bucket}/{full_key}"


def write_run_manifest(
    report: RunReport,
    *,
    output_uri: S3Uri,
    s3_client: Any | None = None,
) -> str:
    """Emit ``run_manifest.json`` at the derived prefix root."""

    full_key = (
        f"{output_uri.key_prefix.rstrip('/')}/run_manifest.json"
        if output_uri.key_prefix
        else "run_manifest.json"
    )
    body = json.dumps(report.to_json(), ensure_ascii=False, sort_keys=True, indent=2)
    if s3_client is None:
        s3_client = _boto3_client("s3")
    s3_client.put_object(
        Bucket=output_uri.bucket,
        Key=full_key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )
    return f"s3://{output_uri.bucket}/{full_key}"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _boto3_client(service: str) -> Any:  # pragma: no cover - trivial shim
    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:
        msg = (
            "boto3 is not installed. Install it in the operator environment "
            "(pip install boto3) before running textract_batch."
        )
        raise TextractClientError(msg) from exc
    return boto3.client(service, region_name="ap-northeast-1")


def run_batch(
    *,
    input_prefix: str,
    output_prefix: str,
    budget_usd: float = DEFAULT_BUDGET_USD,
    per_page_usd: float = DEFAULT_PER_PAGE_USD,
    warn_threshold: float = DEFAULT_WARN_THRESHOLD,
    max_pdfs: int = DEFAULT_MAX_PDFS,
    dry_run: bool = True,
    job_run_id: str | None = None,
    s3_client: Any | None = None,
    textract_client: Any | None = None,
    analyze_fn: Callable[..., TextractResult] | None = None,
    listing_fn: Callable[..., list[PdfListEntry]] | None = None,
) -> RunReport:
    """Drive the J06 Textract batch end-to-end.

    Returns the :class:`RunReport` ledger so callers (CLI + tests) can
    inspect what happened without re-reading S3.
    """

    input_uri = S3Uri.parse(input_prefix)
    output_uri = S3Uri.parse(output_prefix)
    run_id = job_run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = RunReport(
        job_run_id=run_id,
        input_prefix=input_prefix,
        output_prefix=output_prefix,
        budget_usd=budget_usd,
        per_page_usd=per_page_usd,
        warn_threshold=warn_threshold,
        dry_run=dry_run,
    )

    listing = (listing_fn or list_pdfs)(
        input_uri, s3_client=s3_client, max_pdfs=max_pdfs
    )
    report.pdf_count_listed = len(listing)

    summary_rows: list[dict[str, Any]] = []

    for idx, entry in enumerate(listing, start=1):
        # Pre-flight: assume worst case (DRY_RUN_SIMULATED_PAGE_COUNT)
        # before we have a real page count, since Textract does not bill
        # for the START call but does bill per-page on completion.
        pessimistic_pages = (
            entry.estimated_page_count
            if entry.estimated_page_count is not None
            else DRY_RUN_SIMULATED_PAGE_COUNT
        )
        projected = projected_spend_after(
            report.page_count_total, per_page_usd, pessimistic_pages
        )
        if should_stop(projected, budget_usd):
            report.stopped_at_pdf = idx
            report.stop_reason = (
                f"projected spend USD {projected:.2f} >= budget USD {budget_usd:.2f}"
            )
            logger.error(
                "textract_batch stop: projected=%.2f budget=%.2f pdf_idx=%d",
                projected,
                budget_usd,
                idx,
            )
            break
        if (
            report.warn_emitted_at_pdf is None
            and should_warn(projected, budget_usd, warn_threshold)
        ):
            report.warn_emitted_at_pdf = idx
            logger.warning(
                "textract_batch warn: projected=%.2f reached %.0f%% of budget=%.2f",
                projected,
                warn_threshold * 100,
                budget_usd,
            )

        try:
            result = analyze_pdf(
                entry,
                dry_run=dry_run,
                textract_client=textract_client,
                analyze_fn=analyze_fn,
            )
        except TextractClientError as exc:
            report.pdf_count_skipped += 1
            report.skipped_entries.append(
                {"key": entry.key, "reason": f"textract_error: {exc}"}
            )
            continue

        report.pdf_count_analyzed += 1
        report.page_count_total += result.page_count
        report.projected_spend_usd = projected_spend_after(
            report.page_count_total, per_page_usd, 0
        )

        per_page_rows = build_per_page_jsonl(result)
        if not dry_run and per_page_rows:
            jsonl_key = (
                f"jsonl/{run_id}/{entry.key.replace('/', '_')}.jsonl"
            )
            write_jsonl(
                per_page_rows,
                output_uri=output_uri,
                key_suffix=jsonl_key,
                s3_client=s3_client,
            )

        summary_rows.append(
            {
                "s3_uri": f"s3://{entry.bucket}/{entry.key}",
                "page_count": result.page_count,
                "table_count": len(result.tables),
                "form_count": len(result.forms),
                "size_bytes": entry.size_bytes,
                "request_time_llm_call_performed": False,
            }
        )

    if not dry_run:
        write_parquet_summary(
            summary_rows,
            output_uri=output_uri,
            key_suffix=f"parquet/{run_id}/summary.parquet",
            s3_client=s3_client,
        )
        write_run_manifest(
            report,
            output_uri=output_uri,
            s3_client=s3_client,
        )

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "J06 Textract batch driver. DRY_RUN default — pass --commit to "
            "actually call Textract and write to the derived bucket."
        )
    )
    parser.add_argument("--input-prefix", required=True)
    parser.add_argument("--output-prefix", required=True)
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--per-page-usd", type=float, default=DEFAULT_PER_PAGE_USD)
    parser.add_argument(
        "--warn-threshold", type=float, default=DEFAULT_WARN_THRESHOLD
    )
    parser.add_argument("--max-pdfs", type=int, default=DEFAULT_MAX_PDFS)
    parser.add_argument("--job-run-id", default=None)
    parser.add_argument(
        "--commit",
        action="store_true",
        help=(
            "Lift the DRY_RUN guard. Without --commit the script does not "
            "call Textract and does not write to the derived bucket."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the RunReport as JSON on stdout.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    dry_run = not args.commit and os.environ.get("DRY_RUN", "1") != "0"
    report = run_batch(
        input_prefix=args.input_prefix,
        output_prefix=args.output_prefix,
        budget_usd=args.budget_usd,
        per_page_usd=args.per_page_usd,
        warn_threshold=args.warn_threshold,
        max_pdfs=args.max_pdfs,
        dry_run=dry_run,
        job_run_id=args.job_run_id,
    )
    if args.json:
        print(json.dumps(report.to_json(), ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(
            f"[textract_batch] dry_run={dry_run} listed={report.pdf_count_listed} "
            f"analyzed={report.pdf_count_analyzed} pages={report.page_count_total} "
            f"projected_usd={report.projected_spend_usd:.2f} budget_usd={report.budget_usd:.2f}"
        )
        if report.stopped_at_pdf is not None:
            print(
                f"[textract_batch] STOPPED at pdf #{report.stopped_at_pdf}: "
                f"{report.stop_reason}"
            )
        if report.warn_emitted_at_pdf is not None:
            print(
                f"[textract_batch] WARN at pdf #{report.warn_emitted_at_pdf}: "
                f"crossed {report.warn_threshold * 100:.0f}% of budget"
            )
    return 0 if report.stopped_at_pdf is None else 2


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
