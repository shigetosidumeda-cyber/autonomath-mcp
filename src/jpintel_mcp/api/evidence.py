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

Each packet is one billable unit. Current public pricing and anonymous
limits are published on the pricing page. Anonymous tier shares the IP cap
via ``AnonIpLimitDep`` on the router mount.

Response formats
----------------

``?format=json`` (default) | ``?format=csv`` | ``?format=md``.

CSV is the records[] flattened (header row + one row per record). MD is
human-readable.

NO LLM imports. Pure SQLite + Python via the composer.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._license_gate import (
    REDISTRIBUTABLE_LICENSES,
    annotate_attribution,
    filter_redistributable,
)
from jpintel_mcp.api._response_models import (
    EVIDENCE_PACKET_EXAMPLE,
    EvidencePacketEnvelope,
)
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings
from jpintel_mcp.services.evidence_packet import (
    MAX_RECORDS_PER_PACKET,
    EvidencePacketComposer,
)

logger = logging.getLogger("jpintel.api.evidence")

router = APIRouter(prefix="/v1/evidence", tags=["evidence"])


_composer: EvidencePacketComposer | None = None
_composer_paths: tuple[str, str] | None = None


def _current_composer_paths() -> tuple[str, str]:
    jpintel_db = Path(os.environ.get("JPINTEL_DB_PATH") or settings.db_path)
    autonomath_db = Path(os.environ.get("AUTONOMATH_DB_PATH") or settings.autonomath_db_path)
    return (str(jpintel_db), str(autonomath_db))


def _get_composer() -> EvidencePacketComposer:
    global _composer, _composer_paths
    paths = _current_composer_paths()
    if _composer is None or _composer_paths != paths:
        jpintel_db, autonomath_db = (Path(p) for p in paths)
        try:
            _composer = EvidencePacketComposer(
                jpintel_db=jpintel_db,
                autonomath_db=autonomath_db,
            )
            _composer_paths = paths
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "db_unavailable",
                    "message": (f"evidence_packet composer のデータソースが見つかりません: {exc}"),
                },
            ) from exc
    return _composer


def _validate_compression_baseline(
    source_tokens_basis: Literal["unknown", "pdf_pages", "token_count"],
    source_token_count: int | None,
) -> None:
    """Reject incomplete caller-supplied token baselines."""
    if source_tokens_basis == "token_count" and source_token_count is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=("source_token_count is required when source_tokens_basis=token_count."),
        )


def reset_composer() -> None:
    """Drop the cached composer. Tests call this after monkeypatching paths."""
    global _composer, _composer_paths
    _composer = None
    _composer_paths = None


# ---------------------------------------------------------------------------
# Format dispatch
# ---------------------------------------------------------------------------


def _record_license_tuple(rec: dict[str, Any]) -> dict[str, Any]:
    """Derive (license, publisher, source_url, fetched_at) for a packet record.

    Evidence Packet records carry their primary license on
    ``record.facts[*].source.license`` (one license per fact source). For
    the export gate we lift a representative license up onto the record
    so `filter_redistributable` can decide allow/block at the row level.

    Selection policy:

      * If ANY fact source carries a license value in
        `REDISTRIBUTABLE_LICENSES`, the record's license is set to that
        allowed value (most-common allowed license wins; ties broken
        lexically). Rationale: a record whose provenance includes at
        least one redistributable source CAN be redistributed under
        that source's terms — the export carries the matching
        attribution line per CC-BY 4.0 §3 / PDL v1.0.
      * Else, fall back to the most-common license seen on the facts
        (which will be a non-allow-listed value — `gov_standard_v2.0`,
        `proprietary`, etc. — and the gate will correctly block).
      * If no facts have a `source.license` at all, the record's license
        is ``"unknown"`` (safe-block default).

    The returned dict is suitable as input to `filter_redistributable` /
    `annotate_attribution`. We do NOT mutate `rec`.
    """
    facts = rec.get("facts") or []
    licenses: dict[str, int] = {}
    publisher: str | None = None
    source_url: str | None = rec.get("source_url")
    fetched_at: str | None = None
    # Track per-license publisher / url / fetched_at so attribution
    # reflects the WINNING license source, not a random earlier source.
    per_license_meta: dict[str, dict[str, Any]] = {}
    for f in facts:
        src = f.get("source") or {}
        lic = src.get("license")
        if isinstance(lic, str) and lic:
            licenses[lic] = licenses.get(lic, 0) + 1
            meta = per_license_meta.setdefault(lic, {})
            if "publisher" not in meta and src.get("publisher"):
                meta["publisher"] = src.get("publisher")
            if "url" not in meta and src.get("url"):
                meta["url"] = src.get("url")
            if "fetched_at" not in meta and src.get("fetched_at"):
                meta["fetched_at"] = src.get("fetched_at")
        if publisher is None and src.get("publisher"):
            publisher = src.get("publisher")
        if fetched_at is None and src.get("fetched_at"):
            fetched_at = src.get("fetched_at")
        if source_url is None and src.get("url"):
            source_url = src.get("url")

    chosen: str = "unknown"
    if licenses:
        # Prefer redistributable licenses. If any allowed license appears
        # on the facts, pick the most-common allowed one (ties lexical).
        allowed_present = {k: v for k, v in licenses.items() if k in REDISTRIBUTABLE_LICENSES}
        if allowed_present:
            chosen = sorted(
                allowed_present.items(),
                key=lambda kv: (-kv[1], kv[0]),
            )[0][0]
        else:
            chosen = sorted(
                licenses.items(),
                key=lambda kv: (-kv[1], kv[0]),
            )[0][0]
    # Prefer the chosen-license's own attribution metadata when we have it.
    chosen_meta = per_license_meta.get(chosen) or {}
    return {
        "entity_id": rec.get("entity_id"),
        "license": chosen,
        "publisher": chosen_meta.get("publisher") or publisher,
        "source_url": chosen_meta.get("url") or source_url,
        "fetched_at": chosen_meta.get("fetched_at") or fetched_at,
    }


def _apply_license_gate(envelope: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Filter the envelope's records[] through the license export gate.

    Implements `docs/_internal/value_maximization_plan_no_llm_api.md` §24
    + §28.9 No-Go #5 — `license in ('proprietary','unknown')` MUST NOT
    leave the operator's perimeter, even via CSV/MD/JSON exports.

    Per-record license is derived via `_record_license_tuple` (lifts the
    dominant fact-level license up to the record level) and then passed
    through `filter_redistributable` (allow-list policy). Allowed records
    keep their place in the new envelope; blocked records are dropped
    and surface only via the rollup in `envelope["license_gate"]`.

    Each allowed record gains a top-level `_attribution` line via
    `annotate_attribution` so downstream auditors can preserve CC-BY 4.0
    §3 attribution when redistributing.

    Returns (gated_envelope, gate_summary) where `gated_envelope` is a
    fresh dict (the input is not mutated) and `gate_summary` carries
    allowed_count / blocked_count / blocked_reasons / redistributable
    licenses for response-header / body-mirror surfacing.
    """
    records = envelope.get("records") or []
    # Build (proxy, original) pairs so we can map allow-list verdicts
    # back to the originals.
    proxies = [_record_license_tuple(r) for r in records]
    allowed_proxies, blocked_proxies = filter_redistributable(proxies)
    allowed_ids = {p.get("entity_id") for p in allowed_proxies}

    blocked_reasons: dict[str, int] = {}
    for p in blocked_proxies:
        v = p.get("license")
        key = v if isinstance(v, str) and v else "unknown"
        blocked_reasons[key] = blocked_reasons.get(key, 0) + 1

    gate_summary: dict[str, Any] = {
        "allowed_count": len(allowed_proxies),
        "blocked_count": len(blocked_proxies),
        "blocked_reasons": blocked_reasons,
        "redistributable_licenses": sorted(REDISTRIBUTABLE_LICENSES),
    }

    # Re-build records[] with attribution annotations on the allowed set.
    # Lookup by entity_id; fall back to positional match for records
    # missing entity_id (defensive — records always carry it in practice).
    proxy_by_id = {p.get("entity_id"): p for p in proxies if p.get("entity_id")}
    new_records: list[dict[str, Any]] = []
    for r in records:
        eid = r.get("entity_id")
        if eid not in allowed_ids:
            continue
        proxy = proxy_by_id.get(eid) or {}
        ann = annotate_attribution(proxy)
        out = dict(r)
        out["_attribution"] = ann.get("_attribution")
        out["license"] = proxy.get("license")
        new_records.append(out)

    gated_envelope = dict(envelope)
    gated_envelope["records"] = new_records
    gated_envelope["license_gate"] = gate_summary
    return gated_envelope, gate_summary


def _dispatch_format(envelope: dict[str, Any], fmt: str) -> Response:
    """Serialize the packet envelope; gate CSV/MD redistribution paths.

    JSON responses are the per-request conversational surface — paid
    customers see the full envelope as composed (license info is already
    inline on every fact via `facts[].source.license`, and the customer
    is bound by the API ToS not to redistribute the per-request body).

    CSV and MD exports, by contrast, are bulk-redistribution shapes that
    leave the operator's perimeter as a self-contained file the customer
    can hand to a third party. Per
    `docs/_internal/value_maximization_plan_no_llm_api.md` §24 + §28.9
    No-Go #5 these paths funnel records[] through `filter_redistributable`
    (allow-list policy on `REDISTRIBUTABLE_LICENSES`) so any record whose
    dominant fact-source license is `proprietary` / `unknown` / a
    non-allow-listed value (e.g. `gov_standard_v2.0` while the constant
    is the canonical `gov_standard`) is dropped from the output bytes.
    Allowed records each gain an `_attribution` line via
    `annotate_attribution` so downstream auditors preserve CC-BY 4.0 §3.

    Both gated responses surface the gate rollup via the
    `X-License-Gate-Allowed` / `X-License-Gate-Blocked` headers (mirrors
    `api/ma_dd.py` audit-bundle export semantics).

    The textual reference to `filter_redistributable` is also what
    `tests/test_license_gate_no_bypass.py` asserts to keep this function
    in the "wired" set — the AST scanner walks every export-shaped
    function under `api/` and fails CI if the gate token is absent.
    """
    if fmt in ("csv", "md"):
        gated, gate_summary = _apply_license_gate(envelope)

        # Defense-in-depth post-condition: re-run `filter_redistributable`
        # over the gated records[] using the lifted top-level `license`
        # field that `_apply_license_gate` injected. ANY non-empty
        # `_blocked` here means the gate's allow-list logic regressed —
        # fail closed by dropping the offending rows from the output. In
        # practice this is always a no-op (the upstream gate already
        # filtered) but keeps the invariant local + auditable in the
        # export path itself.
        _allowed, _blocked = filter_redistributable(gated.get("records") or [])
        if _blocked:
            gated["records"] = _allowed
            gate_summary["allowed_count"] = len(_allowed)
            gate_summary["blocked_count"] = gate_summary.get("blocked_count", 0) + len(_blocked)

        headers = {
            "X-License-Gate-Allowed": str(gate_summary["allowed_count"]),
            "X-License-Gate-Blocked": str(gate_summary["blocked_count"]),
        }
        if fmt == "csv":
            body = EvidencePacketComposer.to_csv(gated)
            return PlainTextResponse(
                content=body,
                media_type="text/csv",
                headers=headers,
            )
        body = EvidencePacketComposer.to_markdown(gated)
        return PlainTextResponse(
            content=body,
            media_type="text/markdown",
            headers=headers,
        )
    return JSONResponse(content=envelope)


# ---------------------------------------------------------------------------
# Single-subject GET (program / houjin)
# ---------------------------------------------------------------------------


@router.get(
    "/packets/{subject_kind}/{subject_id}",
    summary="Evidence Packet — single-subject composer (program / houjin)",
    description=(
        "Source-linked evidence prefetch for GPT, Claude, Cursor, or RAG "
        "answer generation. 1 packet = 1 billable unit; see the pricing "
        "page for current public price and anonymous limits. "
        "NO LLM call. Bundles primary metadata + per-fact provenance + "
        "compat-matrix rule verdicts (program only) into a compact envelope.\n\n"
        "**subject_kind** ∈ `program` / `houjin`. For multi-record query "
        "packets, POST /v1/evidence/packets/query.\n\n"
        "Response is fail-open: any upstream failure surfaces as a code "
        "in `quality.known_gaps[]`; the packet still renders. Optional "
        "compression fields are input-context estimates, not external "
        "provider billing guarantees."
    ),
    responses={
        200: {
            "model": EvidencePacketEnvelope,
            "content": {"application/json": {"example": EVIDENCE_PACKET_EXAMPLE}},
        }
    },
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
                "Echoed back only as an optional reference comparison hint; "
                "no token, cost, or savings reduction is guaranteed."
            ),
        ),
    ] = None,
    source_tokens_basis: Annotated[
        Literal["unknown", "pdf_pages", "token_count"],
        Query(
            description=(
                "Optional caller-supplied baseline for context comparison. "
                "`unknown` (default) returns packet size only. `pdf_pages` "
                "uses source_pdf_pages * 700 tokens/page as an estimate. "
                "`token_count` uses source_token_count exactly as supplied. "
                "This is input-context estimation only, not a savings guarantee."
            ),
        ),
    ] = "unknown",
    source_pdf_pages: Annotated[
        int | None,
        Query(
            ge=1,
            le=1000,
            description=(
                "PDF page count the caller would otherwise paste/fetch into "
                "the LLM. Used only when source_tokens_basis=pdf_pages."
            ),
        ),
    ] = None,
    source_token_count: Annotated[
        int | None,
        Query(
            ge=1,
            le=50_000_000,
            description=(
                "Caller-measured token count for the source context the LLM "
                "would otherwise read. Used only when "
                "source_tokens_basis=token_count."
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
    _validate_compression_baseline(source_tokens_basis, source_token_count)
    composer = _get_composer()

    if subject_kind == "program":
        envelope = composer.compose_for_program(
            subject_id,
            include_facts=include_facts,
            include_rules=include_rules,
            include_compression=include_compression,
            fields=fields,
            input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
            source_tokens_basis=source_tokens_basis,
            source_pdf_pages=source_pdf_pages,
            source_token_count=source_token_count,
        )
    else:
        envelope = composer.compose_for_houjin(
            subject_id,
            include_facts=include_facts,
            include_rules=include_rules,
            include_compression=include_compression,
            fields=fields,
            input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
            source_tokens_basis=source_tokens_basis,
            source_pdf_pages=source_pdf_pages,
            source_token_count=source_token_count,
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
            "source_tokens_basis": source_tokens_basis,
            "source_pdf_pages": source_pdf_pages,
            "source_token_count": source_token_count,
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
                "source_tokens_basis": source_tokens_basis,
                "source_pdf_pages": source_pdf_pages,
                "source_token_count": source_token_count,
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
            description=(f"Cap on records[] length. Hard cap = {MAX_RECORDS_PER_PACKET}."),
        ),
    ] = 10
    include_facts: Annotated[
        bool,
        Field(description="Include records[].facts[] source-linked fact rows."),
    ] = True
    include_rules: Annotated[
        bool,
        Field(description="Include records[].rules[] compatibility/exclusion rules."),
    ] = False
    include_compression: Annotated[
        bool,
        Field(
            description=(
                "Include input-context size estimates. Estimates compare the "
                "packet against a caller-supplied source baseline; they are "
                "not provider billing guarantees."
            ),
        ),
    ] = False
    fields: Annotated[
        str,
        Field(description="Field projection level. `default` / `full`."),
    ] = "default"
    input_token_price_jpy_per_1m: Annotated[
        float | None,
        Field(
            description=(
                "Optional caller-supplied input-token price in JPY per 1M "
                "tokens. Used only for an input-context break-even reference; "
                "not a total provider bill estimate."
            ),
        ),
    ] = None
    source_tokens_basis: Annotated[
        Literal["unknown", "pdf_pages", "token_count"],
        Field(
            description=(
                "Caller-supplied baseline for context comparison. `unknown` "
                "returns packet size only. `pdf_pages` uses source_pdf_pages "
                "* 700 tokens/page as an estimate. `token_count` uses "
                "source_token_count exactly as supplied by the caller."
            ),
        ),
    ] = "unknown"
    source_pdf_pages: Annotated[
        int | None,
        Field(
            ge=1,
            le=1000,
            description=(
                "PDF page count the caller would otherwise paste/fetch into "
                "the LLM. Used only when source_tokens_basis=pdf_pages."
            ),
        ),
    ] = None
    source_token_count: Annotated[
        int | None,
        Field(
            ge=1,
            le=50_000_000,
            description=(
                "Caller-measured token count for the source context the LLM "
                "would otherwise read. Used only when "
                "source_tokens_basis=token_count."
            ),
        ),
    ] = None


@router.post(
    "/packets/query",
    summary="Evidence Packet — multi-record query composer",
    description=(
        "Use this endpoint as source-linked evidence prefetch before GPT, "
        "Claude, Cursor, or RAG answer generation. It returns a compact "
        "Evidence Packet instead of a final narrative answer, so callers can "
        "avoid pasting long PDFs, official pages, or search snippets into "
        "the model. 1 packet = 1 billable unit; see the pricing page for "
        "current public price and anonymous limits. The packet bundles up "
        "to `limit` records (hard cap 500). Truncation surfaces "
        '`_warning="truncated"`. Optional compression fields are '
        "input-context estimates, not external provider billing guarantees."
    ),
    responses={
        200: {
            "model": EvidencePacketEnvelope,
            "content": {"application/json": {"example": EVIDENCE_PACKET_EXAMPLE}},
        }
    },
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
    _validate_compression_baseline(
        payload.source_tokens_basis,
        payload.source_token_count,
    )
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
        source_tokens_basis=payload.source_tokens_basis,
        source_pdf_pages=payload.source_pdf_pages,
        source_token_count=payload.source_token_count,
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
            "filter_keys": (sorted(payload.filters.keys()) if payload.filters else []),
            "source_tokens_basis": payload.source_tokens_basis,
            "source_pdf_pages": payload.source_pdf_pages,
            "source_token_count": payload.source_token_count,
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
                "filter_keys": (sorted(payload.filters.keys()) if payload.filters else []),
                "source_tokens_basis": payload.source_tokens_basis,
                "source_pdf_pages": payload.source_pdf_pages,
                "source_token_count": payload.source_token_count,
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
