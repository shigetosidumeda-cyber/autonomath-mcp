"""REST handlers for invoice_registrants (適格請求書発行事業者 master).

Backed by migration 019's `invoice_registrants` table. Primary source:
国税庁 適格請求書発行事業者公表サイト bulk download
(https://www.invoice-kohyo.nta.go.jp/download/). Published under
公共データ利用規約 第1.0版 (PDL v1.0): commercial redistribution + downstream
API exposure are permitted provided each response carries (a) 出典明記 and
(b) 編集・加工注記. The `attribution` block on every 2xx response is the
enforcement point for both requirements.

# CHAIN: invoice_registrants ─(houjin_bangou soft-FK)→ houjin_master.
#        No hard FK — a large slice of sole_proprietor rows lack a
#        houjin_bangou, and forcing a FK would drop them (same precedent
#        as migration 011's external-data soft refs).
# WHEN NOT: do NOT expose a raw bulk CSV of individuals, do NOT call the
#        invoice-kohyo Web-API (separate TOS bans scraping), do NOT add
#        synthetic name-matching on top of the 事業者名 field. Individual
#        sole-proprietor rows are only present because the ingest layer
#        already filtered to rows matching NTA's consent model; this
#        router passes them through verbatim.

Scope boundary — read-only. Rows are written by
scripts/ingest/ingest_invoice_registrants.py (monthly full + daily delta);
this handler never mutates.

Search strategy — migration 019 does NOT ship a `_fts` virtual table for
the 4M-row master (trigram FTS5 on a 4M-row name column would roughly
double the disk footprint for a search surface we intentionally keep
narrow under the PDL privacy guardrail). We fall back to prefix LIKE on
`normalized_name` instead, which is the index-eligible path via
idx_invoice_registrants_name. If a future migration adds
`invoice_registrants_fts`, swap to `_build_fts_match` and the programs.py
FTS pattern — the handler shape is already compatible.

Privacy & pagination — `limit` caps at 100 (default 50), pagination via
offset. No wildcard export endpoint. Empty `q` + empty filters still
requires at least a paging window (returns `total` + first page, just
like other routers) but the 100-row hard cap plus the PDL attribution
in every response is what keeps this a lookup tool, not a scrape target.
"""
import re
import sqlite3
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot, snapshot_headers
from jpintel_mcp.api.deps import (
    ApiContextDep,
    DbDep,
    log_empty_search,
    log_usage,
)
from jpintel_mcp.api.vocab import _normalize_prefecture

router = APIRouter(prefix="/v1/invoice_registrants", tags=["invoice_registrants"])


# ---------------------------------------------------------------------------
# PDL v1.0 attribution block — MANDATORY on every 2xx response.
#
# Enforced per migration 019's header: 出典明記 + 編集・加工注記 must appear
# on every surface that renders any invoice_registrants field. The strings
# below are the exact form the migration prescribes; do NOT soften the
# wording (e.g. do NOT claim "最終更新" — the ingest path only sets
# fetched_at, and the user-facing copy must call that "出典取得", matching
# the source_fetched_at semantic honesty rule in CLAUDE.md).
# ---------------------------------------------------------------------------


_ATTRIBUTION: dict[str, Any] = {
    "source": "国税庁適格請求書発行事業者公表サイト（国税庁）",
    "source_url": "https://www.invoice-kohyo.nta.go.jp/",
    "license": "公共データ利用規約 第1.0版 (PDL v1.0)",
    "edited": True,
    "notice": (
        "本データは国税庁公表データを編集加工したものであり、原データと完全には一致しません。"
        "公表データは本API経由ではなく、発行元サイトで最新のものを確認してください。"
    ),
}


# 'T' + 13 digits, 14 chars total. The DB CHECK constraint enforces this
# on write; we mirror it here so an invalid GET path 404s cleanly without
# touching SQLite.
_REG_NUMBER_RE = re.compile(r"^T\d{13}$")

# Order-of-magnitude reference for the full 適格請求書発行事業者 population.
# Used in the 404 body so callers can tell "this T-number didn't match"
# apart from "we only mirror a partial snapshot today". We intentionally
# round to a stable string ("4M+") rather than a precise figure: the NTA
# total drifts week-to-week and a precise number would invite the
# 最終更新-style currency claim that CLAUDE.md's data-honesty rule bans.
_FULL_POPULATION_ESTIMATE = "4,000,000+"

# Public-facing pointer to NTA's own canonical lookup. Kept in sync with
# `_ATTRIBUTION["source_url"]` (same root domain, deeper path). When a
# T-number isn't in our snapshot, this is what the caller should hit.
_NTA_OFFICIAL_LOOKUP = "https://www.invoice-kohyo.nta.go.jp/regno-search/"

# Calendar guidance for the post-launch monthly bulk refresh. Kept as a
# coarse string ("post-launch monthly") rather than a hard date so the
# launch-day deploy doesn't need a code change to bump it; the precise
# schedule lives in docs/_internal/invoice_registrants_bulk_runbook.md.
_NEXT_BULK_REFRESH_HINT = "post-launch monthly (see operator runbook)"

RegistrantKind = Literal["corporation", "sole_proprietor", "other"]

# Public-facing `kind` filter. Accepts 'corporate' / 'individual' per the
# spec, mapped internally to the DB enum (registrant_kind column).
# 'other' is not exposed as a public kind filter — callers that want it
# can query without `kind`.
_KIND_ALIASES: dict[str, RegistrantKind] = {
    "corporate": "corporation",
    "corporation": "corporation",
    "individual": "sole_proprietor",
    "sole_proprietor": "sole_proprietor",
}

# Cap at 100 rows per page: PDL v1.0 permits redistribution but the
# privacy guardrail for sole-proprietor rows (NTA's own consent model)
# dictates we do not offer wildcard export. 50 default / 100 hard cap
# mirrors the other search endpoints in this service.
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 100


class AttributionBlock(BaseModel):
    """PDL v1.0 attribution (出典明記 + 編集・加工注記)."""

    model_config = ConfigDict(extra="forbid")

    source: str
    source_url: str
    license: str
    edited: bool
    notice: str


class InvoiceRegistrantOut(BaseModel):
    """Single 適格請求書発行事業者 row. Columns map 1:1 onto
    019_invoice_registrants.sql's `invoice_registrants` table."""

    model_config = ConfigDict(extra="forbid")

    invoice_registration_number: str = Field(
        ..., description="'T' + 13 digits (14 chars total). Primary key."
    )
    houjin_bangou: str | None = Field(
        default=None,
        description=(
            "13-digit 法人番号. NULL for sole proprietors / 'other'. "
            "Soft reference to houjin_master (no hard FK)."
        ),
    )
    normalized_name: str = Field(
        ...,
        description=(
            "Registered business name (事業者名 / 公表名称) — as published by NTA."
        ),
    )
    address_normalized: str | None = Field(
        default=None,
        description=(
            "Normalized registered address (所在地). May be NULL when NTA "
            "withholds it (sole proprietors who declined disclosure)."
        ),
    )
    prefecture: str | None = Field(
        default=None,
        description="Prefecture (都道府県) — full-suffix kanji form, e.g. 東京都.",
    )
    registered_date: str = Field(
        ..., description="Registration date / 登録日 (ISO 8601 YYYY-MM-DD)."
    )
    revoked_date: str | None = Field(
        default=None,
        description=(
            "Revocation date / 取消日 (ISO 8601). NULL = not revoked (未取消)."
        ),
    )
    expired_date: str | None = Field(
        default=None,
        description=(
            "Expiration date / 失効日 (ISO 8601). NULL = not expired (未失効)."
        ),
    )
    registrant_kind: RegistrantKind = Field(
        ...,
        description=(
            "corporation (法人) | sole_proprietor (個人事業主) | other"
        ),
    )
    trade_name: str | None = Field(
        default=None, description="屋号等 (may be NULL)"
    )
    last_updated_nta: str | None = Field(
        default=None, description="NTA's timestamp on this record"
    )
    source_url: str = Field(
        ...,
        description=(
            "primary source URL "
            "(https://www.invoice-kohyo.nta.go.jp/download/...)"
        ),
    )
    source_checksum: str | None = Field(
        default=None, description="optional SHA-256 of raw bulk file"
    )
    confidence: float = Field(..., description="0..1 lineage confidence")
    fetched_at: str = Field(
        ...,
        description=(
            "ISO 8601 UTC when we last successfully fetched this row. "
            "Rendered as '出典取得' on public surfaces (not '最終更新')."
        ),
    )
    updated_at: str = Field(
        ..., description="ISO 8601 UTC of last row write in our DB"
    )


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    limit: int
    offset: int
    results: list[InvoiceRegistrantOut]
    attribution: AttributionBlock


class GetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: InvoiceRegistrantOut
    attribution: AttributionBlock


def _row_to_registrant(row: sqlite3.Row) -> InvoiceRegistrantOut:
    return InvoiceRegistrantOut(
        invoice_registration_number=row["invoice_registration_number"],
        houjin_bangou=row["houjin_bangou"],
        normalized_name=row["normalized_name"],
        address_normalized=row["address_normalized"],
        prefecture=row["prefecture"],
        registered_date=row["registered_date"],
        revoked_date=row["revoked_date"],
        expired_date=row["expired_date"],
        registrant_kind=row["registrant_kind"],
        trade_name=row["trade_name"],
        last_updated_nta=row["last_updated_nta"],
        source_url=row["source_url"],
        source_checksum=row["source_checksum"],
        confidence=row["confidence"],
        fetched_at=row["fetched_at"],
        updated_at=row["updated_at"],
    )


@router.get(
    "/search",
    summary="Search 適格請求書発行事業者 (NTA invoice registrants)",
    description=(
        "Look up registered Japanese 適格請求書発行事業者 (qualified invoice "
        "issuers under the インボイス制度 / 消費税仕入税額控除 regime) by "
        "name prefix, 法人番号, prefecture, or registration date window. "
        "Mirror of NTA's official 適格請求書発行事業者公表サイト bulk "
        "(13,801 delta rows live; full 4M-row monthly bulk lands "
        "post-launch).\n\n"
        "**When to use:** verify whether a counterparty has issued a "
        "valid T-prefixed invoice number before claiming 仕入税額控除. "
        "For exact T-number lookup (T + 13 digits), prefer "
        "`GET /v1/invoice_registrants/{invoice_registration_number}`.\n\n"
        "**Limits:** `q` requires 2+ chars and uses prefix name matching. "
        "Bulk dump is intentionally not "
        "supported; for full snapshots use NTA's official download URL "
        "in the `attribution.source_url`.\n\n"
        "**License:** every 2xx body carries a PDL v1.0 `attribution` "
        "block — 公共データ利用規約 第1.0版 (出典明記 + 編集・加工注記). "
        "Do NOT strip on relay."
    ),
    responses={
        200: {
            "description": (
                "SearchResponse. Every 2xx body carries a PDL v1.0 "
                "`attribution` block — required by 公共データ利用規約 第1.0版."
            ),
            "model": SearchResponse,
            "content": {
                "application/json": {
                    "example": {
                        "total": 1,
                        "limit": 50,
                        "offset": 0,
                        "results": [
                            {
                                "invoice_registration_number": "T1234567890123",
                                "houjin_bangou": "1234567890123",
                                "normalized_name": "株式会社サンプル",
                                "address_normalized": "東京都千代田区丸の内1-1-1",
                                "prefecture": "東京都",
                                "registered_date": "2024-04-01",
                                "registrant_kind": "corporation",
                                "trade_name": None,
                                "revoked_date": None,
                                "expired_date": None,
                                "last_updated_nta": "2025-05-13",
                                "source_url": "https://www.invoice-kohyo.nta.go.jp/regno-search/download",
                                "source_checksum": "0e5e54184ed778eb2fd797dc7f100b80cb7e892b15134de629d860ae76546398",
                                "confidence": 0.98,
                                "fetched_at": "2026-04-25T03:30:00Z",
                                "updated_at": "2026-04-25T03:30:00Z",
                            }
                        ],
                        "attribution": {
                            "source": "国税庁適格請求書発行事業者公表サイト（国税庁）",
                            "source_url": "https://www.invoice-kohyo.nta.go.jp/",
                            "license": "公共データ利用規約 第1.0版 (PDL v1.0)",
                            "edited": True,
                            "notice": (
                                "本データは国税庁公表データを編集加工したものであり、"
                                "原データと完全には一致しません。"
                                "公表データは本API経由ではなく、"
                                "発行元サイトで最新のものを確認してください。"
                            ),
                        },
                    }
                }
            },
        }
    },
)
def search_invoice_registrants(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    q: Annotated[
        str | None,
        Query(
            description=(
                "Prefix match on 事業者名 (normalized_name). Short queries "
                "(< 2 chars) are rejected to "
                "keep the match selective."
            ),
            max_length=200,
        ),
    ] = None,
    houjin_bangou: Annotated[
        str | None,
        Query(
            description=(
                "Exact 13-digit 法人番号 filter. Returns only rows where "
                "houjin_bangou matches (sole-proprietor rows excluded)."
            ),
            pattern=r"^\d{13}$",
        ),
    ] = None,
    kind: Annotated[
        Literal["corporate", "individual"] | None,
        Query(
            description=(
                "corporate = 法人 (registrant_kind='corporation'); "
                "individual = 個人事業主 (registrant_kind='sole_proprietor'). "
                "Omit to include both plus 'other'."
            ),
        ),
    ] = None,
    prefecture: Annotated[
        str | None,
        Query(
            description=(
                "Prefecture name. Canonical = full-suffix kanji ('東京都'); "
                "short form ('東京') and romaji also accepted."
            ),
            max_length=20,
        ),
    ] = None,
    registered_after: Annotated[
        str | None,
        Query(
            description="ISO date (YYYY-MM-DD) — inclusive lower bound on registered_date.",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
    registered_before: Annotated[
        str | None,
        Query(
            description="ISO date (YYYY-MM-DD) — inclusive upper bound on registered_date.",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
    active_only: Annotated[
        bool,
        Query(
            description=(
                "When true (default), excludes revoked (revoked_date IS NOT NULL) "
                "and expired (expired_date IS NOT NULL) rows. Flip to false for "
                "historical/audit research."
            ),
        ),
    ] = True,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=_MAX_LIMIT,
            description=(
                f"Page size. Default {_DEFAULT_LIMIT}, hard cap {_MAX_LIMIT}. "
                "No wildcard bulk export — point consumers at NTA's own "
                "download URL for full snapshots."
            ),
        ),
    ] = _DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """Search 適格請求書発行事業者 by name / 法人番号 / location / status.

    This endpoint is lookup-only. Bulk-style queries (empty q + empty
    filters paging through the full table) work but return exactly one
    page at a time; the PDL v1.0 attribution is repeated on every page to
    keep 出典明記 + 編集・加工注記 visible across paginated reads.
    """
    _t0 = time.perf_counter()

    where: list[str] = []
    params: list[Any] = []

    if q is not None:
        q_clean = q.strip()
        if q_clean and len(q_clean) < 2:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "q must be at least 2 characters",
            )
        if q_clean:
            # Prefix LIKE — index-eligible on idx_invoice_registrants_name.
            # We do NOT synthesize kana variants here: ingest normalizes
            # to the NTA-published form and consumers are expected to pass
            # that form (the MCP tool layer handles reading-expansion if
            # it becomes a felt need).
            where.append("normalized_name LIKE ?")
            params.append(f"{q_clean}%")

    if houjin_bangou:
        where.append("houjin_bangou = ?")
        params.append(houjin_bangou)

    if kind:
        where.append("registrant_kind = ?")
        params.append(_KIND_ALIASES[kind])

    prefecture_norm = _normalize_prefecture(prefecture)
    if prefecture_norm:
        where.append("prefecture = ?")
        params.append(prefecture_norm)

    if registered_after:
        where.append("registered_date >= ?")
        params.append(registered_after)

    if registered_before:
        where.append("registered_date <= ?")
        params.append(registered_before)

    if active_only:
        where.append("revoked_date IS NULL")
        where.append("expired_date IS NULL")

    where_clause = " AND ".join(where) if where else "1=1"

    count_sql = f"SELECT COUNT(*) FROM invoice_registrants WHERE {where_clause}"
    (total,) = conn.execute(count_sql, params).fetchone()

    # Order: most-recent registered first (freshness bias for the common
    # "who registered last month?" query), then invoice_registration_number
    # for stable pagination.
    select_sql = (
        f"SELECT * FROM invoice_registrants WHERE {where_clause} "
        f"ORDER BY registered_date DESC, invoice_registration_number ASC "
        f"LIMIT ? OFFSET ?"
    )
    rows = conn.execute(select_sql, [*params, limit, offset]).fetchall()

    results = [_row_to_registrant(r).model_dump() for r in rows]

    # Intentionally pass minimal params to log_usage: endpoint is NOT in
    # the params_digest whitelist in deps.py, so the digest is stored as
    # NULL regardless. Individual-sole-proprietor queries must not be
    # aggregated into a weekly digest bucket.
    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "invoice_registrants.search",
        params={
            "kind": kind,
            "prefecture": prefecture_norm,
            "active_only": active_only,
        },
        latency_ms=_latency_ms,
        result_count=total,
    )

    if total == 0 and q is not None:
        _q_clean = q.strip()
        if len(_q_clean) > 1:
            log_empty_search(
                conn,
                query=_q_clean,
                endpoint="search_invoice_registrants",
                filters={
                    "houjin_bangou": houjin_bangou,
                    "kind": kind,
                    "prefecture": prefecture_norm,
                    "registered_after": registered_after,
                    "registered_before": registered_before,
                    "active_only": active_only,
                },
                ip=request.client.host if request.client else None,
            )

    return JSONResponse(
        content={
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": results,
            "attribution": _ATTRIBUTION,
        }
    )


@router.get(
    "/{invoice_registration_number}",
    summary="Lookup adequate-invoice (適格請求書) registrant by T-number",
    description=(
        "Exact lookup by 適格請求書発行事業者登録番号 (`^T\\d{13}$`). Returns "
        "the registrant's name, address, prefecture, registered_date, "
        "and revocation/expiry status (NULL = active).\n\n"
        "**404 semantics:** the 4M-row 適格事業者 population only lands "
        "in the mirror at the post-launch monthly bulk refresh. A "
        "launch-week miss frequently means 'your T-number is real, we "
        "just haven't ingested it yet' — NOT 'this T-number is "
        "invalid'. The 404 body therefore carries `snapshot_size`, "
        "`full_population_estimate`, `next_bulk_refresh`, and an "
        "`alternative` URL pointing at NTA's authoritative lookup so "
        "the caller can distinguish the two cases.\n\n"
        "**License:** PDL v1.0 attribution block on every 2xx + 404 "
        "response (公共データ利用規約 第1.0版 / 出典明記 + 編集・加工注記)."
    ),
    responses={
        200: {
            "description": (
                "GetResponse. Every 2xx body carries a PDL v1.0 "
                "`attribution` block — required by 公共データ利用規約 第1.0版."
            ),
            "model": GetResponse,
            "content": {
                "application/json": {
                    "example": {
                        "result": {
                            "invoice_registration_number": "T1234567890123",
                            "houjin_bangou": "1234567890123",
                            "normalized_name": "株式会社サンプル",
                            "address_normalized": "東京都千代田区丸の内1-1-1",
                            "prefecture": "東京都",
                            "registered_date": "2024-04-01",
                            "registrant_kind": "corporation",
                            "trade_name": None,
                            "revoked_date": None,
                            "expired_date": None,
                            "last_updated_nta": "2025-05-13",
                            "source_url": "https://www.invoice-kohyo.nta.go.jp/regno-search/download",
                            "confidence": 0.98,
                            "fetched_at": "2026-04-25T03:30:00Z",
                            "updated_at": "2026-04-25T03:30:00Z",
                        },
                        "attribution": {
                            "source": "国税庁適格請求書発行事業者公表サイト（国税庁）",
                            "source_url": "https://www.invoice-kohyo.nta.go.jp/",
                            "license": "公共データ利用規約 第1.0版 (PDL v1.0)",
                            "edited": True,
                            "notice": (
                                "本データは国税庁公表データを編集加工したものであり、"
                                "原データと完全には一致しません。"
                                "公表データは本API経由ではなく、"
                                "発行元サイトで最新のものを確認してください。"
                            ),
                        },
                    }
                }
            },
        },
        404: {
            "description": (
                "registrant not found in the current snapshot. The 404 body "
                "is structured (not a bare `detail` string): it reports "
                "`snapshot_size` of the partial mirror we currently serve, "
                "the `full_population_estimate` for context, an "
                "`alternative` URL pointing at NTA's official lookup, plus "
                "the same PDL v1.0 `attribution` block carried by 2xx "
                "responses so 出典明記 + 編集・加工注記 stay attached even "
                "on miss. This shape is contractual — see "
                "tests/test_invoice_registrants_404.py."
            )
        },
        422: {"description": "invoice_registration_number malformed (must match '^T\\d{13}$')"},
    },
)
def get_invoice_registrant(
    invoice_registration_number: str,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Exact lookup by 適格請求書発行事業者登録番号 ('T' + 13 digits).

    On miss we do NOT raise a bare 404. The 4M-row 適格事業者 population
    only lands in our mirror at the post-launch monthly bulk refresh, so
    a launch-week miss frequently means "your T-number is real, we just
    haven't ingested it yet" — not "this T-number is invalid". The
    enriched 404 body distinguishes the two cases for the caller and
    points them at NTA's authoritative lookup as the immediate fallback.
    """
    if not _REG_NUMBER_RE.match(invoice_registration_number):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invoice_registration_number must match '^T\\d{13}$'",
        )

    row = conn.execute(
        "SELECT * FROM invoice_registrants WHERE invoice_registration_number = ?",
        (invoice_registration_number,),
    ).fetchone()
    if row is None:
        # Compute snapshot_size live so the 404 body stays honest as the
        # mirror grows (delta-only today, full bulk at T+30d). COUNT(*) on
        # a 14k-row table with PK is sub-millisecond; no need to cache.
        (snapshot_size,) = conn.execute(
            "SELECT COUNT(*) FROM invoice_registrants"
        ).fetchone()

        log_usage(
            conn,
            ctx,
            "invoice_registrants.get",
            status_code=status.HTTP_404_NOT_FOUND,
            # Path-param T-numbers are PII-adjacent (they identify a
            # specific business) — keep them out of params_digest. Status
            # is what we actually need for the 404-rate dashboard.
            params={"miss": True},
        )

        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "detail": "Not found in current registrant snapshot.",
                "registration_number": invoice_registration_number,
                "snapshot_size": snapshot_size,
                "full_population_estimate": _FULL_POPULATION_ESTIMATE,
                "snapshot_attribution": (
                    f"{_ATTRIBUTION['source']} ({_ATTRIBUTION['license']})"
                ),
                "next_bulk_refresh": _NEXT_BULK_REFRESH_HINT,
                "alternative": (
                    f"公式 lookup: {_NTA_OFFICIAL_LOOKUP}"
                ),
                # Repeat the full attribution block so the PDL v1.0
                # 出典明記 + 編集・加工注記 requirement holds on miss too.
                # Migration 019's contract is "every surface that renders
                # any invoice_registrants field" — `snapshot_size` counts.
                "attribution": _ATTRIBUTION,
            },
        )

    log_usage(
        conn,
        ctx,
        "invoice_registrants.get",
        params={"invoice_registration_number": invoice_registration_number},
    )

    body: dict[str, Any] = {
        "result": _row_to_registrant(row).model_dump(),
        "attribution": _ATTRIBUTION,
    }
    # Audit trail (会計士 work-paper, added 2026-04-29): top-level snapshot
    # fields so an auditor citing this T-number in a work-paper can reproduce
    # the lookup later and detect whether the corpus mutated.
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body, headers=snapshot_headers(conn))
