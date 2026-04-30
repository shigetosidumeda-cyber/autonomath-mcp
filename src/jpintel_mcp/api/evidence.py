"""Evidence Packet REST surface.

Plan reference: ``docs/_internal/llm_resilient_business_plan_2026-04-30.md`` §6.

Endpoints
---------

* ``GET  /v1/evidence/packets/{subject_kind}/{subject_id}`` — single-record
  packet for ``program`` / ``houjin``. ``query`` mode is POST below.
* ``POST /v1/evidence/packets/query`` — multi-record packet for a query
  string + optional filters. Body required so the query stays out of the
  URL (length, escaping, no PII in access logs).

Pricing posture
---------------

¥3/req per packet (1 unit). Anonymous tier shares the 50/月 IP cap via
``AnonIpLimitDep`` on the router mount.

Response formats
----------------

``?format=json`` (default) | ``?format=csv`` | ``?format=md``.

CSV is the records[] flattened (header row + one row per record). MD is
human-readable.

NO LLM imports. Pure SQLite + Python via the composer.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings
from jpintel_mcp.services.evidence_packet import (
    MAX_RECORDS_PER_PACKET,
    EvidencePacketComposer,
)

logger = logging.getLogger("jpintel.api.evidence")

router = APIRouter(prefix="/v1/evidence", tags=["evidence"])


_composer: EvidencePacketComposer | None = None


def _get_composer() -> EvidencePacketComposer:
    global _composer
    if _composer is None:
        try:
            _composer = EvidencePacketComposer(
                jpintel_db=settings.db_path,
                autonomath_db=settings.autonomath_db_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "db_unavailable",
                    "message": (
                        "evidence_packet composer のデータソースが見つかりません: "
                        f"{exc}"
                    ),
                },
            ) from exc
    return _composer


def reset_composer() -> None:
    """Drop the cached composer. Tests call this after monkeypatching paths."""
    global _composer
    _composer = None


# ---------------------------------------------------------------------------
# Format dispatch
# ---------------------------------------------------------------------------


def _dispatch_format(
    envelope: dict[str, Any], fmt: str
) -> Response:
    if fmt == "csv":
        body = EvidencePacketComposer.to_csv(envelope)
        return PlainTextResponse(content=body, media_type="text/csv")
    if fmt == "md":
        body = EvidencePacketComposer.to_markdown(envelope)
        return PlainTextResponse(content=body, media_type="text/markdown")
    return JSONResponse(content=envelope)


# ---------------------------------------------------------------------------
# Single-subject GET (program / houjin)
# ---------------------------------------------------------------------------


@router.get(
    "/packets/{subject_kind}/{subject_id}",
    summary="Evidence Packet — single-subject composer (program / houjin)",
    description=(
        "1 packet = 1 billable unit (¥3 / 税込 ¥3.30). NO LLM. Bundles "
        "primary metadata + per-fact provenance + compat-matrix rule "
        "verdicts (program only) into a single envelope.\n\n"
        "**subject_kind** ∈ `program` / `houjin`. For multi-record query "
        "packets, POST /v1/evidence/packets/query.\n\n"
        "Response is fail-open: any upstream failure surfaces as a code "
        "in `quality.known_gaps[]`; the packet still renders."
    ),
)
def get_evidence_packet(
    subject_kind: Annotated[
        Literal["program", "houjin"],
        PathParam(description="Subject kind. `query` uses the POST endpoint."),
    ],
    subject_id: Annotated[
        str,
        PathParam(
            min_length=1,
            max_length=200,
            description=(
                "For `program`: a unified_id (UNI-...) or canonical_id "
                "(program:...). For `houjin`: a 13-digit 法人番号."
            ),
        ),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
    include_facts: Annotated[
        bool,
        Query(description="Include records[].facts[]. Default True."),
    ] = True,
    include_rules: Annotated[
        bool,
        Query(description="Include records[].rules[]. Default True."),
    ] = True,
    include_compression: Annotated[
        bool,
        Query(description="Surface compression hints. Default False."),
    ] = False,
    fields: Annotated[
        str,
        Query(description="Field projection level. `default` / `full`."),
    ] = "default",
    input_token_price_jpy_per_1m: Annotated[
        float | None,
        Query(
            description=(
                "Optional caller's input-token price (JPY per 1M tokens). "
                "Echoed back in the envelope so the customer can compare "
                "packet cost vs LLM-only ingest cost."
            ),
        ),
    ] = None,
    output_format: Annotated[
        Literal["json", "csv", "md"],
        Query(
            description=(
                "Output format. `json` (default) / `csv` / `md`. "
                "Sent as `?output_format=csv` (Python builtin name `format` "
                "is avoided so the StrictQueryMiddleware sees the "
                "declared alias)."
            ),
        ),
    ] = "json",
) -> Response:
    _t0 = time.perf_counter()
    composer = _get_composer()

    if subject_kind == "program":
        envelope = composer.compose_for_program(
            subject_id,
            include_facts=include_facts,
            include_rules=include_rules,
            include_compression=include_compression,
            fields=fields,
            input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
        )
    else:
        envelope = composer.compose_for_houjin(
            subject_id,
            include_facts=include_facts,
            include_rules=include_rules,
            include_compression=include_compression,
            fields=fields,
            input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
        )

    if envelope is None:
        log_usage(
            conn,
            ctx,
            "evidence.packet.get",
            status_code=status.HTTP_404_NOT_FOUND,
            params={
                "subject_kind": subject_kind,
                "subject_id": subject_id,
            },
        )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "detail": (
                    f"Unknown {subject_kind}_id. Pass either a unified_id "
                    "(UNI-...) or a canonical_id (program:...) for programs, "
                    "or a 13-digit 法人番号 for houjin."
                ),
                "subject_kind": subject_kind,
                "subject_id": subject_id,
            },
        )

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "evidence.packet.get",
        latency_ms=latency_ms,
        params={
            "subject_kind": subject_kind,
            "subject_id": subject_id,
            "format": output_format,
            "include_facts": include_facts,
            "include_rules": include_rules,
        },
    )
    # §17.D audit seal on paid JSON responses. CSV/MD outputs skip the
    # seal (the wire shape has no place to embed JSON inside flat text).
    if output_format == "json":
        attach_seal_to_body(
            envelope,
            endpoint="evidence.packet.get",
            request_params={
                "subject_kind": subject_kind,
                "subject_id": subject_id,
            },
            api_key_hash=ctx.key_hash,
            conn=conn,
        )
    return _dispatch_format(envelope, output_format)


# ---------------------------------------------------------------------------
# Multi-record POST (query)
# ---------------------------------------------------------------------------


class EvidencePacketQueryBody(BaseModel):
    query_text: Annotated[
        str,
        Field(
            min_length=1,
            max_length=500,
            description="Free-text query. Echoed into `query.user_intent`.",
        ),
    ]
    filters: Annotated[
        dict[str, Any] | None,
        Field(
            default=None,
            description=(
                "Optional structured filters (prefecture / tier). Echoed "
                "into `query.normalized_filters`."
            ),
        ),
    ] = None
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=MAX_RECORDS_PER_PACKET,
            description=(
                f"Cap on records[] length. Hard cap = {MAX_RECORDS_PER_PACKET}."
            ),
        ),
    ] = 10
    include_facts: bool = True
    include_rules: bool = False
    include_compression: bool = False
    fields: str = "default"
    input_token_price_jpy_per_1m: float | None = None


@router.post(
    "/packets/query",
    summary="Evidence Packet — multi-record query composer",
    description=(
        "1 packet = 1 billable unit (¥3 / 税込 ¥3.30). The packet bundles "
        "up to `limit` records (hard cap 500). Truncation surfaces "
        "`_warning=\"truncated\"`."
    ),
)
def post_evidence_packet_query(
    payload: EvidencePacketQueryBody,
    conn: DbDep,
    ctx: ApiContextDep,
    output_format: Annotated[
        Literal["json", "csv", "md"],
        Query(description="`json` (default) / `csv` / `md`."),
    ] = "json",
) -> Response:
    _t0 = time.perf_counter()
    composer = _get_composer()
    envelope = composer.compose_for_query(
        payload.query_text,
        payload.filters,
        limit=payload.limit,
        include_facts=payload.include_facts,
        include_rules=payload.include_rules,
        include_compression=payload.include_compression,
        fields=payload.fields,
        input_token_price_jpy_per_1m=payload.input_token_price_jpy_per_1m,
    )
    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "evidence.packet.query",
        latency_ms=latency_ms,
        params={
            "limit": payload.limit,
            "format": output_format,
            "filter_keys": (
                sorted(payload.filters.keys()) if payload.filters else []
            ),
        },
    )
    # §17.D audit seal — JSON only (see evidence.packet.get above).
    if output_format == "json":
        attach_seal_to_body(
            envelope,
            endpoint="evidence.packet.query",
            request_params={
                "query_text": payload.query_text,
                "limit": payload.limit,
                "filter_keys": (
                    sorted(payload.filters.keys()) if payload.filters else []
                ),
            },
            api_key_hash=ctx.key_hash,
            conn=conn,
        )
    return _dispatch_format(envelope, output_format)


__all__ = [
    "EvidencePacketQueryBody",
    "reset_composer",
    "router",
]
