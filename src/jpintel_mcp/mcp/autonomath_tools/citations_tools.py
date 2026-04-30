"""Citation Verifier MCP tool.

Tool: ``verify_citations``

Same algorithm as the REST endpoint at POST /v1/citations/verify (see
``src/jpintel_mcp/api/citations.py``). Pure no-LLM regex + checksum.
The customer's LLM uses this to substantiate ``verification_status="verified"``
claims emitted by upstream tools (search, programs.get, audit_seal, etc.)
that defaulted to ``inferred`` because they did not fetch the source URL.

Spec source: ``docs/_internal/value_maximization_plan_no_llm_api.md`` §8.2
+ §28.2 envelope + §28.9 No-Go #1 (no false-allow).

NO LLM API call. Pure stdlib + the local CitationVerifier.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp
from jpintel_mcp.services.citation_verifier import (
    MAX_CITATIONS_PER_CALL,
    MAX_EXCERPT_LEN,
    PER_FETCH_TIMEOUT_SEC,
    CitationVerifier,
)

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.am.citations")

# Env-gated registration. Default ON — the REST + MCP surfaces should
# move in lockstep so customer SDK and customer LLM see the same tool.
_ENABLED = os.environ.get("AUTONOMATH_CITATIONS_ENABLED", "1") == "1"

# Same total wall-clock budget as the REST endpoint.
_TOTAL_TIMEOUT_SEC = 30


def _verify_citations_impl(
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pure compute behind ``verify_citations``.

    Extracted for testability — tests import this directly so they don't
    have to spin up the FastMCP server to assert verdicts.
    """
    if not isinstance(citations, list):
        return make_error(
            "missing_required_arg",
            "citations must be a non-empty list[dict]",
            field="citations",
        )

    if len(citations) == 0:
        return make_error(
            "missing_required_arg",
            "citations must contain at least one item",
            field="citations",
        )

    if len(citations) > MAX_CITATIONS_PER_CALL:
        return make_error(
            "out_of_range",
            f"citations cap = {MAX_CITATIONS_PER_CALL}; received {len(citations)}",
            field="citations",
            extra={
                "max_per_call": MAX_CITATIONS_PER_CALL,
                "received": len(citations),
            },
        )

    # Excerpt-length pre-flight.
    for idx, c in enumerate(citations):
        if not isinstance(c, dict):
            return make_error(
                "missing_required_arg",
                f"citations[{idx}] must be a dict",
                field=f"citations[{idx}]",
            )
        excerpt = c.get("excerpt")
        if (
            isinstance(excerpt, str)
            and len(excerpt) > MAX_EXCERPT_LEN
        ):
            return make_error(
                "out_of_range",
                (
                    f"citations[{idx}].excerpt is {len(excerpt)} chars; "
                    f"cap = {MAX_EXCERPT_LEN}"
                ),
                field=f"citations[{idx}].excerpt",
                extra={
                    "citation_index": idx,
                    "max_length": MAX_EXCERPT_LEN,
                    "received_length": len(excerpt),
                },
            )

    started = time.monotonic()
    verifier = CitationVerifier()
    outputs: list[dict[str, Any]] = []

    for idx, c in enumerate(citations):
        elapsed = time.monotonic() - started
        if elapsed >= _TOTAL_TIMEOUT_SEC:
            outputs.append({
                "citation_index": idx,
                "verification_status": "unknown",
                "matched_form": None,
                "source_checksum": None,
                "normalized_source_length": 0,
                "error": "overall_timeout",
            })
            continue

        body: str | None
        if isinstance(c.get("source_text"), str):
            body = c["source_text"]
        elif isinstance(c.get("source_url"), str) and c["source_url"]:
            remaining = max(1, int(_TOTAL_TIMEOUT_SEC - elapsed))
            per_fetch = min(PER_FETCH_TIMEOUT_SEC, remaining)
            body = verifier.fetch_source(c["source_url"], timeout=per_fetch)
        else:
            body = None

        if body is None:
            outputs.append({
                "citation_index": idx,
                "verification_status": "unknown",
                "matched_form": None,
                "source_checksum": None,
                "normalized_source_length": 0,
                "error": "source_unreachable",
            })
            continue

        verdict = verifier.verify(
            citation={
                "excerpt": c.get("excerpt"),
                "field_value": c.get("field_value"),
            },
            source_text=body,
        )
        outputs.append({
            "citation_index": idx,
            "verification_status": verdict["verification_status"],
            "matched_form": verdict.get("matched_form"),
            "source_checksum": verdict.get("source_checksum"),
            "normalized_source_length": verdict.get("normalized_source_length", 0),
            "error": verdict.get("error"),
        })

    verified = sum(1 for o in outputs if o["verification_status"] == "verified")
    inferred = sum(1 for o in outputs if o["verification_status"] == "inferred")
    stale = sum(1 for o in outputs if o["verification_status"] == "stale")
    unknown = sum(1 for o in outputs if o["verification_status"] == "unknown")

    return {
        "verifications": outputs,
        "verified_count": verified,
        "inferred_count": inferred,
        "stale_count": stale,
        "unknown_count": unknown,
    }


# ---------------------------------------------------------------------------
# MCP tool registration. Same gate posture as composition_tools — env flag
# (default ON) AND the global AUTONOMATH_ENABLED.
# ---------------------------------------------------------------------------
if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def verify_citations(
        citations: Annotated[
            list[dict[str, Any]],
            Field(
                description=(
                    "List of citation dicts to verify. Each dict has "
                    "{source_url?, source_text?, excerpt?, field_value?}. "
                    f"Cap = {MAX_CITATIONS_PER_CALL}; longer batches → error."
                ),
                min_length=1,
                max_length=MAX_CITATIONS_PER_CALL,
            ),
        ],
    ) -> dict[str, Any]:
        """[CITATION-VERIFY] Substantiate verification_status="verified" by deterministic substring + Japanese numeric-form match against the cited primary source. Pure no-LLM. Per-citation verdict ∈ {verified, inferred, unknown}; SHA256 checksum returned for re-checks. Up to 10 citations / 30s wall clock.
        """
        return _verify_citations_impl(citations=citations)


__all__ = [
    "_verify_citations_impl",
]
