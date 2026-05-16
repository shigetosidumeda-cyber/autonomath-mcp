"""Thin Textract wrapper for the J06 ministry/municipality PDF extraction job.

This module is **structured OCR only**. It calls ``AnalyzeDocument``
(synchronous) for short PDFs and ``StartDocumentAnalysis`` +
``GetDocumentAnalysis`` (asynchronous) for larger PDFs that exceed the
sync 5-page hard limit. It deliberately does **not** call any Bedrock
endpoint, does not summarize, does not post-process via an LLM. The
output is the raw structured ``Block`` list plus a small set of
derived projections (``extracted_text``, ``tables``, ``forms``) that
downstream JPCIR receipt assembly can consume without re-walking the
raw blocks.

Design references:

* ``docs/_internal/aws_credit_review_05_ocr_bedrock_opensearch.md`` —
  Textract scope + pilot budget + stop conditions.
* ``data/aws_credit_jobs/J06_ministry_municipality_pdf_extraction.json``
  — job manifest (target URLs, output prefix, license boundary,
  required notice, etc.).
* ``src/jpintel_mcp/agent_runtime/contracts.py`` — JPCIR
  ``Evidence`` + ``SourceReceipt`` envelope that wraps the result.

Non-negotiable invariants:

* ``request_time_llm_call_performed=false`` on every emitted result.
* Only the four AWS APIs listed in the IAM policy
  (``infra/aws/iam/jpcite_batch_job_role_textract_policy.json``).
* Feature types restricted to ``TABLES`` and ``FORMS`` — Queries +
  Signatures + Layout are deliberately excluded to keep per-page cost
  bounded and to keep the surface within review-09 USD 150 pilot cap.
* ``AnalyzeExpense`` and ``AnalyzeID`` are **never** called from this
  module — they are receipt / ID-card APIs out of jpcite scope.
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Canonical AWS region for the J06 PDF extraction job. Matches the
#: ``output_prefix`` in ``data/aws_credit_jobs/J06_ministry_municipality_pdf_extraction.json``
#: (S3 bucket ``jpcite-credit-993693061769-202605-raw`` lives in
#: ap-northeast-1, so Textract must run there to avoid cross-region S3
#: egress charges and Athena read-side region drift).
DEFAULT_REGION: Final[str] = "ap-northeast-1"

#: Textract ``AnalyzeDocument`` (synchronous) hard-caps inputs at 5
#: pages. PDFs larger than this MUST go through the asynchronous
#: ``StartDocumentAnalysis`` + ``GetDocumentAnalysis`` poll loop. The
#: AWS limit is documented at
#: https://docs.aws.amazon.com/textract/latest/dg/limits-document.html
#: — do not raise this without checking the current quota.
SYNC_PAGE_LIMIT: Final[int] = 5

#: How often to poll ``GetDocumentAnalysis`` while a job is IN_PROGRESS.
#: Textract jobs on small ministry PDFs typically complete in
#: 10-60 seconds; 5 s polling keeps tail latency reasonable without
#: hammering the API.
_DEFAULT_POLL_INTERVAL_SECONDS: Final[float] = 5.0

#: Absolute ceiling on how long ``analyze_document`` waits for an async
#: job. ``J06_ministry_municipality_pdf_extraction.json`` caps
#: ``max_runtime_seconds`` at 14_400 (4 h) for the whole batch, so a
#: single PDF that takes more than 15 minutes is almost certainly
#: pathological and should be quarantined.
_DEFAULT_POLL_TIMEOUT_SECONDS: Final[float] = 900.0


class AnalyzeFeatureType(StrEnum):
    """Subset of Textract ``FeatureTypes`` enabled for the J06 job.

    Only the two features that produce structured output relevant to the
    receipt fields (締切 / 対象者 / 除外条件 / 必要書類 / 問い合わせ先)
    are enabled. ``QUERIES`` is excluded because the J06 job extracts
    via known templates rather than free-form NL queries (and Queries
    bill at a higher per-page rate). ``SIGNATURES`` and ``LAYOUT`` are
    excluded because they are not receipt-relevant and would double the
    per-page cost without producing reviewable facts.
    """

    TABLES = "TABLES"
    FORMS = "FORMS"


class TextractClientError(RuntimeError):
    """Raised when the Textract client surface signals an unrecoverable error.

    Wrapped errors include: invalid request payload, ``Status=FAILED``
    on the asynchronous path, poll timeout, and boto3 import failures.
    The error message is deliberately user-readable because it lands in
    ``pdf_parse_failures.jsonl`` (one of the J06 output artifacts).
    """


class TextractRequest(BaseModel):
    """Request envelope for a single PDF analysis.

    The PDF is always referenced by ``s3_bucket`` + ``s3_key`` (no
    raw-bytes payload) because the J06 job stages every PDF into S3
    before invoking Textract. This keeps the request small, makes the
    invocation idempotent against retries, and produces a reusable S3
    URI that the JPCIR ``SourceReceipt`` can pin to.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    s3_bucket: str = Field(min_length=3, max_length=63)
    s3_key: str = Field(min_length=1)
    feature_types: tuple[AnalyzeFeatureType, ...] = Field(
        default=(AnalyzeFeatureType.TABLES, AnalyzeFeatureType.FORMS),
        min_length=1,
    )
    region: str = Field(default=DEFAULT_REGION, min_length=1)
    estimated_page_count: int | None = Field(default=None, ge=1, le=3000)
    poll_interval_seconds: float = Field(
        default=_DEFAULT_POLL_INTERVAL_SECONDS, gt=0.0
    )
    poll_timeout_seconds: float = Field(
        default=_DEFAULT_POLL_TIMEOUT_SECONDS, gt=0.0
    )

    @field_validator("s3_bucket")
    @classmethod
    def _validate_bucket(cls, value: str) -> str:
        # AWS S3 bucket naming: lowercase letters, digits, dots, hyphens.
        # We deliberately do not validate dots/hyphens deeply — boto3
        # will reject anything truly malformed — but we forbid uppercase
        # to catch the most common typo before paying for an API call.
        if value != value.lower():
            msg = f"s3_bucket must be lowercase: {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("s3_key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        if value.startswith("/"):
            msg = f"s3_key must not start with '/': {value!r}"
            raise ValueError(msg)
        return value


class TextractTableCell(BaseModel):
    """One cell of a recovered table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    row_index: int = Field(ge=1)
    column_index: int = Field(ge=1)
    text: str = ""
    confidence: float = Field(ge=0.0, le=100.0)


class TextractTable(BaseModel):
    """One reconstructed table from a Textract response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    table_index: int = Field(ge=0)
    page: int = Field(ge=1)
    cells: tuple[TextractTableCell, ...] = ()


class TextractFormField(BaseModel):
    """One key/value pair recovered from a FORMS feature pass."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page: int = Field(ge=1)
    key: str = ""
    value: str = ""
    key_confidence: float = Field(ge=0.0, le=100.0)
    value_confidence: float = Field(ge=0.0, le=100.0)


class TextractResult(BaseModel):
    """Result envelope for a completed Textract analysis.

    ``raw_blocks`` is intentionally typed as ``tuple[dict[str, Any], ...]``
    rather than a typed Pydantic model because Textract returns a deep
    recursive ``Block`` schema with mixed unions (LINE / WORD / TABLE /
    CELL / KEY_VALUE_SET / SELECTION_ELEMENT / PAGE / etc.). Forcing a
    typed model here would force every reader to handle every variant;
    instead we materialise the projections that the J06 receipt
    assembly actually needs (``extracted_text``, ``tables``, ``forms``)
    and keep the raw blocks for forensic replay.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    s3_bucket: str
    s3_key: str
    page_count: int = Field(ge=0)
    raw_blocks: tuple[dict[str, Any], ...] = ()
    extracted_text: str = ""
    tables: tuple[TextractTable, ...] = ()
    forms: tuple[TextractFormField, ...] = ()
    confidence_per_field: dict[str, float] = Field(default_factory=dict)
    request_time_llm_call_performed: Literal[False] = False


def _import_boto3() -> Any:  # pragma: no cover - trivial import shim
    """Lazy boto3 import to keep the package importable without the SDK.

    boto3 is not a runtime dependency of jpcite (the only places it's
    used are operator-side cron / ETL / aws_credit_ops). Lazy importing
    here keeps the test surface mockable without forcing boto3 into the
    distribution wheel.
    """

    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:
        msg = (
            "boto3 is not installed. Install it in the operator environment "
            "(pip install boto3) before calling Textract."
        )
        raise TextractClientError(msg) from exc
    return boto3


def _build_client(region: str, *, client_factory: Any | None = None) -> Any:
    """Construct a Textract client.

    ``client_factory`` is a seam for tests: pass a callable that returns
    a fake client and the real ``boto3.client('textract', ...)`` call is
    skipped entirely. In production this argument is ``None`` and we go
    through the lazy ``boto3`` import.
    """

    if client_factory is not None:
        return client_factory(region)
    boto3 = _import_boto3()
    return boto3.client("textract", region_name=region)


def _project_text(blocks: tuple[dict[str, Any], ...]) -> str:
    """Concatenate ``LINE`` blocks into a single readable string.

    Order is preserved as the Textract API returns it. We do **not**
    re-sort by bounding box or page because the J06 receipt assembly
    relies on the API's natural reading order — re-sorting here would
    produce silent drift between runs.
    """

    parts: list[str] = []
    for block in blocks:
        if block.get("BlockType") == "LINE":
            text = block.get("Text", "")
            if isinstance(text, str) and text:
                parts.append(text)
    return "\n".join(parts)


def _project_tables(blocks: tuple[dict[str, Any], ...]) -> tuple[TextractTable, ...]:
    """Project ``TABLE`` + ``CELL`` blocks into typed table records.

    We index blocks by ``Id`` once, then for each ``TABLE`` block walk
    its ``CELL`` children and resolve each cell's ``WORD`` content from
    the same index. This is the canonical Textract reconstruction
    recipe — see
    https://docs.aws.amazon.com/textract/latest/dg/how-it-works-tables.html
    for the upstream description.
    """

    by_id: dict[str, dict[str, Any]] = {}
    for block in blocks:
        block_id = block.get("Id")
        if isinstance(block_id, str):
            by_id[block_id] = block

    def _cell_text(cell: dict[str, Any]) -> str:
        words: list[str] = []
        for rel in cell.get("Relationships", []) or []:
            if rel.get("Type") != "CHILD":
                continue
            for child_id in rel.get("Ids", []) or []:
                child = by_id.get(child_id, {})
                if child.get("BlockType") == "WORD":
                    text = child.get("Text", "")
                    if isinstance(text, str) and text:
                        words.append(text)
        return " ".join(words)

    tables: list[TextractTable] = []
    table_index = 0
    for block in blocks:
        if block.get("BlockType") != "TABLE":
            continue
        page = int(block.get("Page", 1) or 1)
        cells: list[TextractTableCell] = []
        for rel in block.get("Relationships", []) or []:
            if rel.get("Type") != "CHILD":
                continue
            for child_id in rel.get("Ids", []) or []:
                cell_block = by_id.get(child_id, {})
                if cell_block.get("BlockType") != "CELL":
                    continue
                row = int(cell_block.get("RowIndex", 0) or 0)
                col = int(cell_block.get("ColumnIndex", 0) or 0)
                conf = float(cell_block.get("Confidence", 0.0) or 0.0)
                if row < 1 or col < 1:
                    continue
                cells.append(
                    TextractTableCell(
                        row_index=row,
                        column_index=col,
                        text=_cell_text(cell_block),
                        confidence=conf,
                    )
                )
        tables.append(
            TextractTable(table_index=table_index, page=page, cells=tuple(cells))
        )
        table_index += 1
    return tuple(tables)


def _project_forms(
    blocks: tuple[dict[str, Any], ...],
) -> tuple[TextractFormField, ...]:
    """Project ``KEY_VALUE_SET`` blocks into typed form-field records.

    A KEY_VALUE_SET appears twice per form pair: once with
    ``EntityTypes=["KEY"]`` and once with ``EntityTypes=["VALUE"]``.
    The KEY block carries a CHILD relationship to its WORD content and
    a VALUE relationship pointing at the matching VALUE block, which in
    turn has its own CHILD relationship to its WORD content. We resolve
    both sides here.
    """

    by_id: dict[str, dict[str, Any]] = {}
    for block in blocks:
        block_id = block.get("Id")
        if isinstance(block_id, str):
            by_id[block_id] = block

    def _words_for(block: dict[str, Any]) -> tuple[str, float]:
        words: list[str] = []
        confidences: list[float] = []
        for rel in block.get("Relationships", []) or []:
            if rel.get("Type") != "CHILD":
                continue
            for child_id in rel.get("Ids", []) or []:
                child = by_id.get(child_id, {})
                if child.get("BlockType") == "WORD":
                    text = child.get("Text", "")
                    conf = float(child.get("Confidence", 0.0) or 0.0)
                    if isinstance(text, str) and text:
                        words.append(text)
                        confidences.append(conf)
        if not confidences:
            return " ".join(words), 0.0
        return " ".join(words), sum(confidences) / len(confidences)

    forms: list[TextractFormField] = []
    for block in blocks:
        if block.get("BlockType") != "KEY_VALUE_SET":
            continue
        entity_types = block.get("EntityTypes", []) or []
        if "KEY" not in entity_types:
            continue
        page = int(block.get("Page", 1) or 1)
        key_text, key_conf = _words_for(block)
        value_text = ""
        value_conf = 0.0
        for rel in block.get("Relationships", []) or []:
            if rel.get("Type") != "VALUE":
                continue
            for value_id in rel.get("Ids", []) or []:
                value_block = by_id.get(value_id, {})
                value_text, value_conf = _words_for(value_block)
        forms.append(
            TextractFormField(
                page=page,
                key=key_text,
                value=value_text,
                key_confidence=key_conf,
                value_confidence=value_conf,
            )
        )
    return tuple(forms)


def _count_pages(blocks: tuple[dict[str, Any], ...]) -> int:
    """Return the number of unique ``Page`` indices observed in ``blocks``."""

    pages: set[int] = set()
    for block in blocks:
        page = block.get("Page")
        if isinstance(page, int):
            pages.add(page)
        elif page is not None:
            try:
                pages.add(int(page))
            except (TypeError, ValueError):
                continue
    return len(pages)


def _build_confidence_map(
    text: str, tables: tuple[TextractTable, ...], forms: tuple[TextractFormField, ...]
) -> dict[str, float]:
    """Roll up confidence numbers into a small named map.

    Used by the J06 quarantine logic: anything with avg confidence
    below the threshold in
    ``aws_credit_review_05_ocr_bedrock_opensearch.md`` §4.2 goes onto
    the review queue instead of the receipt-candidate parquet.
    """

    text_avg = 100.0 if text else 0.0
    table_conf_values = [c.confidence for tbl in tables for c in tbl.cells]
    table_avg = (
        sum(table_conf_values) / len(table_conf_values) if table_conf_values else 0.0
    )
    form_conf_values: list[float] = []
    for f in forms:
        form_conf_values.extend([f.key_confidence, f.value_confidence])
    form_avg = (
        sum(form_conf_values) / len(form_conf_values) if form_conf_values else 0.0
    )
    return {
        "extracted_text_present": text_avg,
        "tables_avg": table_avg,
        "forms_avg": form_avg,
    }


def _result_from_blocks(req: TextractRequest, blocks: list[dict[str, Any]]) -> TextractResult:
    """Assemble a :class:`TextractResult` from a raw boto3 block list."""

    raw = tuple(blocks)
    text = _project_text(raw)
    tables = _project_tables(raw)
    forms = _project_forms(raw)
    return TextractResult(
        s3_bucket=req.s3_bucket,
        s3_key=req.s3_key,
        page_count=_count_pages(raw),
        raw_blocks=raw,
        extracted_text=text,
        tables=tables,
        forms=forms,
        confidence_per_field=_build_confidence_map(text, tables, forms),
    )


def _analyze_sync(req: TextractRequest, client: Any) -> TextractResult:
    """Run the synchronous ``AnalyzeDocument`` path (≤5 pages)."""

    feature_types = [ft.value for ft in req.feature_types]
    response = client.analyze_document(
        Document={"S3Object": {"Bucket": req.s3_bucket, "Name": req.s3_key}},
        FeatureTypes=feature_types,
    )
    blocks = response.get("Blocks", []) or []
    return _result_from_blocks(req, blocks)


def _analyze_async(
    req: TextractRequest, client: Any, *, sleep: Any | None = None
) -> TextractResult:
    """Run the asynchronous path (>5 pages).

    ``sleep`` is a seam for tests so the poll loop can be exercised
    without actually sleeping. In production we use ``time.sleep``.
    """

    sleeper = sleep if sleep is not None else time.sleep
    feature_types = [ft.value for ft in req.feature_types]
    start = client.start_document_analysis(
        DocumentLocation={"S3Object": {"Bucket": req.s3_bucket, "Name": req.s3_key}},
        FeatureTypes=feature_types,
    )
    job_id = start.get("JobId")
    if not isinstance(job_id, str) or not job_id:
        msg = "Textract start_document_analysis returned no JobId"
        raise TextractClientError(msg)

    deadline = time.monotonic() + req.poll_timeout_seconds
    blocks: list[dict[str, Any]] = []
    next_token: str | None = None
    seen_succeeded = False
    while time.monotonic() < deadline:
        kwargs: dict[str, Any] = {"JobId": job_id}
        if next_token is not None:
            kwargs["NextToken"] = next_token
        page = client.get_document_analysis(**kwargs)
        status = page.get("JobStatus")
        if status == "FAILED":
            status_msg = page.get("StatusMessage", "")
            msg = f"Textract job {job_id} FAILED: {status_msg}"
            raise TextractClientError(msg)
        if status == "PARTIAL_SUCCESS":
            # PARTIAL_SUCCESS still surfaces blocks; we accept them but
            # let the caller decide whether to quarantine.
            blocks.extend(page.get("Blocks", []) or [])
            next_token = page.get("NextToken")
            if not next_token:
                break
            continue
        if status == "SUCCEEDED":
            blocks.extend(page.get("Blocks", []) or [])
            next_token = page.get("NextToken")
            seen_succeeded = True
            if not next_token:
                break
            continue
        # IN_PROGRESS or any other status — sleep and re-poll.
        sleeper(req.poll_interval_seconds)
    else:
        msg = (
            f"Textract job {job_id} did not finish within "
            f"{req.poll_timeout_seconds}s"
        )
        raise TextractClientError(msg)

    if not seen_succeeded and not blocks:
        msg = f"Textract job {job_id} returned no SUCCEEDED page"
        raise TextractClientError(msg)
    return _result_from_blocks(req, blocks)


def analyze_document(
    req: TextractRequest,
    *,
    client: Any | None = None,
    client_factory: Any | None = None,
    sleep: Any | None = None,
) -> TextractResult:
    """Analyze a PDF in S3 with Amazon Textract.

    Routes to the synchronous ``AnalyzeDocument`` API for PDFs with
    fewer than :data:`SYNC_PAGE_LIMIT` pages (default 5) and to the
    asynchronous ``StartDocumentAnalysis`` + poll loop for larger PDFs.
    The decision is made on ``req.estimated_page_count``; when that
    field is ``None``, the function defaults to the asynchronous path
    because we cannot prove the PDF is small enough for sync without
    paying for an extra HEAD round trip.

    Test seams:

    * ``client`` — a pre-built fake client whose ``analyze_document`` /
      ``start_document_analysis`` / ``get_document_analysis`` methods
      return canned responses.
    * ``client_factory`` — a callable ``(region) -> client`` used to
      synthesise a client lazily without touching boto3.
    * ``sleep`` — a stand-in for ``time.sleep`` so the async poll loop
      can be exercised without real wall-clock delay.

    The combination ``client=...`` wins over ``client_factory=...``
    which wins over the real boto3 import path.
    """

    if client is None:
        client = _build_client(req.region, client_factory=client_factory)

    if (
        req.estimated_page_count is not None
        and req.estimated_page_count <= SYNC_PAGE_LIMIT
    ):
        return _analyze_sync(req, client)
    return _analyze_async(req, client, sleep=sleep)
