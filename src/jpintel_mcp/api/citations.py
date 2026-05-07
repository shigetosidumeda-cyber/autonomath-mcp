"""Citation Verifier REST surface.

Endpoint:
    POST /v1/citations/verify

Spec source: ``docs/_internal/value_maximization_plan_no_llm_api.md`` §8.2 +
§28.2 envelope + §28.9 No-Go #1.

Pricing posture:
    Authenticated metered ¥3/req per CALL (not per citation). The verifier
    fetches up to 10 URLs synchronously inside one request — that is the
    ¥3 unit. Anonymous callers are NOT supported on this surface because
    each fetch can take up to ``PER_FETCH_TIMEOUT_SEC`` seconds and the
    anon path has no way to push back on abuse beyond the standard IP
    quota; we want a key on the request so a runaway caller is visible
    in usage_events for triage.

Auth:
    Requires an API key (any tier). No tier gating beyond that.

Algorithm: see ``services/citation_verifier.py`` for the deterministic
substring + Japanese-numeric-form match logic. This module is pure
glue — request validation, fan-out to the verifier, response assembly.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from jpintel_mcp.api.deps import (  # noqa: TC001 — runtime resolution by FastAPI
    ApiContextDep,
    DbDep,
    log_usage,
)
from jpintel_mcp.services.citation_verifier import (
    MAX_CITATIONS_PER_CALL,
    MAX_EXCERPT_LEN,
    PER_FETCH_TIMEOUT_SEC,
    CitationVerifier,
)

logger = logging.getLogger("jpintel.api.citations")

router = APIRouter(prefix="/v1/citations", tags=["citations"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Total wall-clock budget for one /verify call. The brief asks for 30s.
# Per-citation cap is PER_FETCH_TIMEOUT_SEC (5s); 10 × 5s = 50s in the
# absolute worst case, but typical p95 is much lower because fetches
# overlap with verifier work. We enforce 30s as a soft fence: once the
# wall clock crosses it, remaining citations short-circuit to ``unknown``
# with ``error="overall_timeout"`` rather than raising.
TOTAL_TIMEOUT_SEC = 30
ENDPOINT_LABEL = "citations.verify"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CitationInput(BaseModel):
    """One citation to verify.

    At least one of ``excerpt`` / ``field_value`` MUST be present and
    non-null; otherwise the verifier returns ``unknown`` (not an error,
    just an honest "no signal"). The pydantic schema does NOT enforce
    that here so callers can send a permissive batch and let per-row
    verdicts drive their UI.
    """

    source_url: Annotated[
        str | None,
        Field(
            default=None,
            max_length=2048,
            description=(
                "Primary source URL. Fetched live (5s cap each, cached "
                "1h). NULL = caller wants to verify against a body they "
                "supply via source_text instead."
            ),
        ),
    ] = None
    entity_id: Annotated[
        str | None,
        Field(
            default=None,
            max_length=256,
            description=(
                "Optional jpcite entity_id this citation belongs to. When "
                "entity_id and source_url are both present, the verdict is "
                "best-effort persisted for future Evidence Packet citation "
                "status joins."
            ),
        ),
    ] = None
    source_text: Annotated[
        str | None,
        Field(
            default=None,
            max_length=5_000_000,
            description=(
                "Optional pre-fetched body. When present, source_url is "
                "ignored (no live fetch). Useful for offline replay / "
                "load-test runs where you don't want to hit the upstream."
            ),
        ),
    ] = None
    excerpt: Annotated[
        str | None,
        Field(
            default=None,
            max_length=MAX_EXCERPT_LEN,
            description=(
                "Substring claim. Must appear verbatim (post-NFKC, "
                f"post-whitespace-collapse) in the source. ≤{MAX_EXCERPT_LEN} chars."
            ),
        ),
    ] = None
    field_value: Annotated[
        Any,
        Field(
            default=None,
            description=(
                "Numeric claim (int/str/float). Verified by checking ALL "
                "Japanese-style spellings ('5,000,000円', '500万円', "
                "'5百万円', '5000000') against the source body."
            ),
        ),
    ] = None


class VerifyRequest(BaseModel):
    citations: Annotated[
        list[CitationInput],
        Field(
            min_length=1,
            description=(
                f"List of citations to verify. Cap = {MAX_CITATIONS_PER_CALL}; "
                f"longer payloads → 422."
            ),
        ),
    ]


class VerificationOutput(BaseModel):
    """Per-citation verdict.

    Mirrors the verifier's TypedDict but adds ``citation_index`` so
    callers can re-attach verdicts to their input array even when some
    citations were skipped.
    """

    citation_index: int
    verification_status: str
    matched_form: str | None = None
    source_checksum: str | None = None
    normalized_source_length: int = 0
    verification_basis: Literal["live_fetch", "caller_supplied_source_text", "none"] = "none"
    source_url_fetched: bool = False
    error: str | None = None


class VerifyResponse(BaseModel):
    verifications: list[VerificationOutput]
    verified_count: int
    inferred_count: int
    stale_count: int = 0
    caller_text_matched_count: int = 0
    unknown_count: int


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/verify",
    response_model=VerifyResponse,
)
def verify_citations(
    payload: VerifyRequest,
    bg: BackgroundTasks,
    conn: DbDep,
    ctx: ApiContextDep,
) -> VerifyResponse:
    """Verify a batch of up to 10 citations against their primary sources.

    Per call:
      * 1 billable unit (¥3) — billed regardless of per-citation verdict.
      * Up to 30 seconds wall clock.
      * Up to 10 citations.

    Per citation:
      * Up to 5 seconds for the URL fetch.
      * Verdict ∈ {verified, inferred, stale, unknown}. (``stale`` is
        reserved for future drift detection — current pipeline returns
        verified/inferred/unknown only.)

    Errors:
      * 401 if the API key header is missing or invalid.
      * 422 if more than 10 citations OR if an ``excerpt`` exceeds 500
        chars. The validation message identifies the offending index so
        the developer can fix the call without binary-searching the batch.
    """
    # Auth fence — anonymous callers (key_hash=None) cannot reach the
    # verifier. Mirrors the bulk_evaluate posture.
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "verify_citations requires an authenticated API key",
        )

    # 422-fence: explicit, friendly, indexed.
    if len(payload.citations) > MAX_CITATIONS_PER_CALL:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "too_many_citations",
                "max_per_call": MAX_CITATIONS_PER_CALL,
                "received": len(payload.citations),
                "developer_message": (
                    f"POST /v1/citations/verify accepts ≤ {MAX_CITATIONS_PER_CALL} "
                    "citations per call. Split larger batches across multiple "
                    "calls — each call is one ¥3 billable unit."
                ),
            },
        )

    # Pre-flight excerpt-length check: pydantic already rejects via
    # max_length when the pyantic v2 model is constructed, but we double-
    # check here so the error envelope identifies WHICH citation index
    # broke the cap (pydantic errors are bulk; ours is precise).
    for idx, c in enumerate(payload.citations):
        if c.excerpt is not None and len(c.excerpt) > MAX_EXCERPT_LEN:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "excerpt_too_long",
                    "citation_index": idx,
                    "max_length": MAX_EXCERPT_LEN,
                    "received_length": len(c.excerpt),
                    "developer_message": (
                        f"citations[{idx}].excerpt is {len(c.excerpt)} chars; "
                        f"cap = {MAX_EXCERPT_LEN}. Truncate to a quote that "
                        f"actually appears in the cited page."
                    ),
                },
            )

    started = time.monotonic()
    verifier = CitationVerifier()
    outputs: list[VerificationOutput] = []
    persist_rows: list[tuple[str, str, str, str | None, str | None, str, str]] = []

    for idx, c in enumerate(payload.citations):
        elapsed = time.monotonic() - started
        if elapsed >= TOTAL_TIMEOUT_SEC:
            outputs.append(
                VerificationOutput(
                    citation_index=idx,
                    verification_status="unknown",
                    matched_form=None,
                    source_checksum=None,
                    normalized_source_length=0,
                    verification_basis="none",
                    source_url_fetched=False,
                    error="overall_timeout",
                )
            )
            continue

        # Fetch path: use caller-supplied body if present (offline replay),
        # else live-fetch the URL with the per-fetch cap. Either path may
        # produce None body → unknown.
        body: str | None
        verification_basis: Literal["live_fetch", "caller_supplied_source_text", "none"]
        if c.source_text is not None:
            body = c.source_text
            verification_basis = "caller_supplied_source_text"
            source_url_fetched = False
        elif c.source_url:
            # Per-fetch timeout cap, capped further by remaining wall clock.
            remaining = max(1, int(TOTAL_TIMEOUT_SEC - elapsed))
            per_fetch = min(PER_FETCH_TIMEOUT_SEC, remaining)
            body = verifier.fetch_source(c.source_url, timeout=per_fetch)
            verification_basis = "live_fetch"
            source_url_fetched = body is not None
        else:
            body = None
            verification_basis = "none"
            source_url_fetched = False

        if body is None:
            outputs.append(
                VerificationOutput(
                    citation_index=idx,
                    verification_status="unknown",
                    matched_form=None,
                    source_checksum=None,
                    normalized_source_length=0,
                    verification_basis=verification_basis,
                    source_url_fetched=source_url_fetched,
                    error="source_unreachable",
                )
            )
            continue

        verdict = verifier.verify(
            citation={
                "excerpt": c.excerpt,
                "field_value": c.field_value,
            },
            source_text=body,
        )
        output = VerificationOutput(
            citation_index=idx,
            verification_status=verdict["verification_status"],
            matched_form=verdict.get("matched_form"),
            source_checksum=verdict.get("source_checksum"),
            normalized_source_length=verdict.get("normalized_source_length", 0),
            verification_basis=verification_basis,
            source_url_fetched=source_url_fetched,
            error=verdict.get("error"),
        )
        outputs.append(output)
        if c.entity_id and c.source_url:
            persist_rows.append(
                (
                    c.entity_id,
                    c.source_url,
                    output.verification_status,
                    output.matched_form,
                    output.source_checksum,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                    output.verification_basis,
                )
            )

    verified = sum(1 for o in outputs if o.verification_status == "verified")
    inferred = sum(1 for o in outputs if o.verification_status == "inferred")
    stale = sum(1 for o in outputs if o.verification_status == "stale")
    caller_text_matched = sum(
        1
        for o in outputs
        if o.verification_basis == "caller_supplied_source_text"
        and o.verification_status in {"verified", "inferred"}
    )
    unknown = sum(1 for o in outputs if o.verification_status == "unknown")

    if persist_rows:
        try:
            conn.executemany(
                """
                INSERT INTO citation_verification(
                    entity_id, source_url, verification_status, matched_form,
                    source_checksum, verified_at, verification_basis
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                persist_rows,
            )
            conn.commit()
        except sqlite3.Error:
            logger.warning("citation verification persistence skipped", exc_info=True)

    # Bill ONE unit per call (the verifier work, not per citation). Mirrors
    # the §28.2 ``billable_units`` envelope. Strict metering keeps the paid
    # response fail-closed if the final cap check or usage row write fails.
    try:
        log_usage(
            conn=conn,
            ctx=ctx,
            endpoint=ENDPOINT_LABEL,
            status_code=200,
            params={
                "citation_count": len(payload.citations),
                "verified": verified,
                "inferred": inferred,
                "caller_text_matched": caller_text_matched,
                "unknown": unknown,
            },
            quantity=1,
            result_count=len(outputs),
            background_tasks=bg,
            strict_metering=True,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("citation verify billing row failed", exc_info=True)
        if ctx.metered:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "billing_metering_failed",
                    "message": (
                        "This paid response was not delivered because usage "
                        "metering could not be confirmed."
                    ),
                },
            ) from exc

    return VerifyResponse(
        verifications=outputs,
        verified_count=verified,
        inferred_count=inferred,
        stale_count=stale,
        caller_text_matched_count=caller_text_matched,
        unknown_count=unknown,
    )


# Re-export so ``ValidationError`` is accessible to callers that want to
# handle field-level validation errors uniformly across the API surface.
__all__ = ["router", "ValidationError"]
