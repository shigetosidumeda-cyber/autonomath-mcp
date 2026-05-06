"""Evidence Packet bulk REST surface.

Plan reference: ``docs/_internal/llm_resilient_business_plan_2026-04-30.md`` §6
+ ergonomics extension (Wave 25 / Bulk lookup, 2026-05-05).

Endpoint
--------

``POST /v1/evidence/packets/batch`` — resolves up to 100 ``{kind, id}`` lookups
through the same :class:`EvidencePacketComposer` used by the single-record
``/v1/evidence/packets/{kind}/{id}`` endpoint and returns one envelope wrapping
``[Evidence Packet, ...]`` with a per-lookup outcome rollup.

Pricing posture
---------------

Each successful lookup is 1 billable unit (¥3 each). 100 lookups = ¥300.
Failures (404 ``not_found`` etc.) are NOT counted toward ``_billing_unit``
and do not produce a Stripe usage record — same posture as
:func:`deps.log_usage` "do not bill failures" and the customer_cap final
guard. The batch counter only advances by ``successful``.

Authentication
--------------

Paid metered API key required (no anonymous access). The batch surface
multiplies cost by N, so we require an explicit metered tier upfront via
:func:`require_metered_api_key` rather than letting an anonymous IP
exhaust 100 lookups against the 3/day allowance.

NO LLM imports. Pure SQLite + Python via the composer + license gate.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from jpintel_mcp.api.cost_cap_guard import require_cost_cap
from jpintel_mcp.api.deps import (
    ApiContextDep,
    DbDep,
    log_usage,
    require_metered_api_key,
)
from jpintel_mcp.api.evidence import (
    _gate_evidence_envelope,
    _get_composer,
)
from jpintel_mcp.api.middleware.cost_cap import record_cost_cap_spend
from jpintel_mcp.api.middleware.customer_cap import (
    projected_monthly_cap_response,
)
from jpintel_mcp.services.evidence_packet import _DISCLAIMER

logger = logging.getLogger("jpintel.api.evidence_batch")

router = APIRouter(prefix="/v1/evidence", tags=["evidence"])

#: Hard cap on lookups per batch request. 101+ → 422 (one ¥3 unit ceiling
#: that maps cleanly to ¥300 / req for invoice-line readability).
MAX_BATCH_LOOKUPS: int = 100

#: Endpoint label for usage_events / log_usage.
ENDPOINT_LABEL: str = "evidence.packet.batch"


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class EvidencePacketLookup(BaseModel):
    """One ``{kind, id}`` lookup inside a batch."""

    kind: Annotated[
        Literal["program", "houjin"],
        Field(
            description=(
                "Subject kind. Closed enum: `program` / `houjin`. Multi-record "
                "query lookups remain on the existing POST /v1/evidence/packets/query "
                "endpoint and are not accepted in the batch surface."
            ),
        ),
    ]
    id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=200,
            description=(
                "For `program`: a unified_id (UNI-...) or canonical_id "
                "(program:...). For `houjin`: a 13-digit 法人番号."
            ),
        ),
    ]


class EvidencePacketBatchBody(BaseModel):
    """Bulk lookup request body."""

    lookups: Annotated[
        list[EvidencePacketLookup],
        Field(
            min_length=1,
            max_length=MAX_BATCH_LOOKUPS,
            description=(
                f"Up to {MAX_BATCH_LOOKUPS} `{{kind, id}}` lookups. 1 lookup = "
                "1 billable unit (¥3 each); a 100-lookup batch is ¥300 total. "
                "Failures (404 not_found etc.) are NOT billed. 101+ entries → 422."
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/packets/batch",
    summary="Evidence Packet — bulk lookup composer (up to 100 lookups / req)",
    description=(
        "Resolves up to 100 `{kind, id}` lookups through the same "
        "EvidencePacketComposer used by the single-record endpoint and returns "
        "one envelope wrapping `[Evidence Packet, ...]` with per-lookup outcome "
        "rollup. 1 successful lookup = 1 ¥3 billable unit; failures are NOT "
        "billed. 101+ lookups → 422. Authenticated paid tier only.\n\n"
        "Use this surface when an agent needs to fetch evidence for many "
        "subjects in one round-trip — preserves the wire/audit/billing contract "
        "of the single-record endpoint while reducing 100 round-trips to one."
    ),
)
def post_evidence_packet_batch(
    payload: EvidencePacketBatchBody,
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    x_cost_cap_jpy: Annotated[
        str | None,
        Header(
            alias="X-Cost-Cap-JPY",
            description=(
                "JPY request budget for paid batch calls. Required before "
                "composing; predicted cost is 3 JPY x lookup count."
            ),
        ),
    ] = None,
    _idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=("Required for paid batch calls to prevent duplicate billing on retries."),
        ),
    ] = None,
) -> JSONResponse:
    require_metered_api_key(ctx, "evidence.packet.batch")

    _t0 = time.perf_counter()
    n_total = len(payload.lookups)
    if n_total > MAX_BATCH_LOOKUPS:
        # pydantic max_length already covers this; defensive for direct-call paths.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "batch_too_large",
                "message": (
                    f"lookups[] must contain at most {MAX_BATCH_LOOKUPS} entries; got {n_total}."
                ),
                "max_lookups": MAX_BATCH_LOOKUPS,
            },
        )
    require_cost_cap(
        predicted_yen=n_total * 3,
        header_value=x_cost_cap_jpy,
    )

    # Pre-flight customer monthly cap. The batch can charge up to N units;
    # the per-request middleware only sees one. We use the worst-case
    # estimate (N successful lookups) to fail fast before composing —
    # downstream `successful` may be lower, in which case we bill fewer
    # units and the cap is naturally under-shot.
    cap_response = projected_monthly_cap_response(conn, ctx.key_hash, n_total)
    if cap_response is not None:
        return cap_response

    composer = _get_composer()

    results: list[dict[str, Any] | None] = []
    errors: list[dict[str, Any]] = []
    corpus_snapshot_id: str | None = None
    successful = 0

    for idx, lookup in enumerate(payload.lookups):
        try:
            if lookup.kind == "program":
                envelope = composer.compose_for_program(lookup.id)
            else:
                envelope = composer.compose_for_houjin(lookup.id)
        except Exception as exc:  # noqa: BLE001 — keep batch alive on per-row failures
            logger.warning(
                "evidence_batch composer raised idx=%s kind=%s id=%s err=%s",
                idx,
                lookup.kind,
                lookup.id,
                exc,
            )
            envelope = None
            errors.append(
                {
                    "index": idx,
                    "lookup": {"kind": lookup.kind, "id": lookup.id},
                    "error": "composer_failure",
                }
            )
            results.append(None)
            continue

        if envelope is None:
            errors.append(
                {
                    "index": idx,
                    "lookup": {"kind": lookup.kind, "id": lookup.id},
                    "error": "not_found",
                }
            )
            results.append(None)
            continue

        gated, _gate_summary = _gate_evidence_envelope(envelope)
        # Capture the first non-empty corpus_snapshot_id so the envelope
        # surfaces the corpus moment used for the batch. All lookups share
        # the same composer + cache so the value is identical across rows
        # in practice; we read the first non-empty just to be defensive.
        if corpus_snapshot_id is None:
            sid = gated.get("corpus_snapshot_id")
            if isinstance(sid, str) and sid:
                corpus_snapshot_id = sid
        results.append(gated)
        successful += 1

    # Drop None placeholders from results[] — failures are surfaced via
    # errors[] only, so the array index of `results` no longer maps 1:1
    # to the request lookups[]. Callers reconstruct (lookup, packet) pairs
    # via errors[].index for the failures and `results` for the successes.
    successful_results = [r for r in results if r is not None]

    failed = n_total - successful
    billing_unit = successful  # 1 billable unit per successful lookup

    body: dict[str, Any] = {
        "results": successful_results,
        "total": n_total,
        "successful": successful,
        "failed": failed,
        "errors": errors,
        "_billing_unit": billing_unit,
        "_next_calls": _build_next_calls(payload.lookups, errors),
        "_disclaimer": _DISCLAIMER,
        "corpus_snapshot_id": corpus_snapshot_id or "",
    }

    latency_ms = int((time.perf_counter() - _t0) * 1000)

    # Bill ¥3 × successful only. Same pattern as bulk_evaluate: ONE
    # log_usage call with quantity=successful → ONE usage_events row +
    # ONE Stripe usage_record. quantity=0 is coerced to 1 by log_usage —
    # but only if there was at least one successful lookup; if the entire
    # batch failed, we skip log_usage entirely so no Stripe row is filed
    # and no usage_event row is written for a 0-bill batch.
    if successful > 0:
        audit_seal = log_usage(
            conn,
            ctx,
            ENDPOINT_LABEL,
            latency_ms=latency_ms,
            params={
                "total": n_total,
                "successful": successful,
                "failed": failed,
                "kinds": sorted({lk.kind for lk in payload.lookups}),
            },
            quantity=successful,
            result_count=successful,
            response_body=body,
            issue_audit_seal=ctx.key_hash is not None,
            strict_metering=True,
            strict_audit_seal=True,
        )
        if audit_seal is not None:
            body["audit_seal"] = audit_seal
            if audit_seal.get("hmac"):
                body["audit_seal_hmac"] = f"hmac_{audit_seal['hmac']}"
        record_cost_cap_spend(request, successful * 3)
    else:
        # All-failed batch: log a free audit row so operators can see the
        # all-fail signal in the dashboard, but pass quantity=1 with
        # status_code=200 metered=0 semantics — actually the simplest path
        # is to emit a 200-status NON-metered audit row by skipping
        # log_usage entirely (it's keyed on api_keys.metered=paid). The
        # batch is delivered to the caller; no charge.
        pass

    response = JSONResponse(content=body)
    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_next_calls(
    lookups: list[EvidencePacketLookup],
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Suggest follow-up calls. For batch responses we surface:

    * For each `not_found` error: a single-record GET URL the agent can
      call to confirm the miss. (No new lookup invented from corpus.)
    * If the batch resolved at least one program: a hint to use
      `/v1/evidence/packets/query` for free-text exploration.
    """
    out: list[dict[str, Any]] = []
    failed_lookups = {(e.get("index"), e.get("error")) for e in errors}
    for idx, lk in enumerate(lookups):
        if (idx, "not_found") in failed_lookups:
            out.append(
                {
                    "tool": "get_evidence_packet",
                    "endpoint": f"/v1/evidence/packets/{lk.kind}/{lk.id}",
                    "reason": "verify_not_found",
                }
            )
            if len(out) >= 5:
                break
    if any(lk.kind == "program" for lk in lookups):
        out.append(
            {
                "tool": "post_evidence_packet_query",
                "endpoint": "/v1/evidence/packets/query",
                "reason": "free_text_exploration",
            }
        )
    return out


__all__ = [
    "ENDPOINT_LABEL",
    "EvidencePacketBatchBody",
    "EvidencePacketLookup",
    "MAX_BATCH_LOOKUPS",
    "post_evidence_packet_batch",
    "router",
]
