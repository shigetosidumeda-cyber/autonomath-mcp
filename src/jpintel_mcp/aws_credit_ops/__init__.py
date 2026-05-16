"""AWS credit-run operational clients for the J01..J07 acquisition jobs.

This subpackage holds thin, deterministic wrappers around AWS service
clients used during the AWS credit consumption window. None of the
wrappers here perform LLM inference: Textract is **structured OCR / form
+ table extraction**, not generative text. The reusable JPCIR contract
(``Evidence`` + ``SourceReceipt``) is emitted by callers, not by these
clients — the clients only surface raw structured output + bookkeeping
metadata (``page_count``, ``confidence_per_field``) so the receipt can
be assembled deterministically.

Non-negotiable invariants enforced across this subpackage:

* No Bedrock / LLM imports anywhere in this tree.
* No ``AnalyzeExpense`` / ``AnalyzeID`` calls (out of jpcite scope —
  those are receipt / ID-card APIs that have nothing to do with the
  ministry / municipality public PDF surface).
* Region pinned to ``ap-northeast-1`` (Tokyo) for the J06 job. Cross-
  region drift breaks Athena queries on the resulting S3 prefix.
* ``request_time_llm_call_performed=false`` on every emitted result
  envelope — this is the canonical JPCIR marker that distinguishes
  OCR / structured extraction from LLM inference.
"""

from __future__ import annotations

from jpintel_mcp.aws_credit_ops.textract_client import (
    DEFAULT_REGION,
    SYNC_PAGE_LIMIT,
    AnalyzeFeatureType,
    TextractClientError,
    TextractRequest,
    TextractResult,
    analyze_document,
)

__all__ = [
    "DEFAULT_REGION",
    "SYNC_PAGE_LIMIT",
    "AnalyzeFeatureType",
    "TextractClientError",
    "TextractRequest",
    "TextractResult",
    "analyze_document",
]
