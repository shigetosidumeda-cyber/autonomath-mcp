"""EDINET 提出書類 REST surface.

Endpoints
---------
    GET /v1/edinet/filings?houjin_bangou={n}&doc_type={t}&since={d}&limit={k}
    GET /v1/edinet/filings/{edinet_code}/full

Wave 31 Axis 1c. Backed by `am_edinet_filings` (migration 227,
target_db=autonomath), which carries body excerpt + R2 URL for the
full XBRL body.

Pricing posture
---------------
    Authenticated metered ¥3/req per CALL. List + detail are both single
    billable units. Anonymous tier (AnonIpLimitDep at app wiring time)
    receives the standard 3/day per IP cap.

Auth
----
    Detail surface gates behind an API key (no anonymous full-body read)
    because the R2 signed URL is short-lived and re-issuance is non-trivial.
    List surface is fine for the anonymous fence.

LLM call count: 0. Pure SQLite + Pydantic. ¥3/req metered surface.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Path, Query, status
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import sqlite3

from jpintel_mcp.api.deps import (  # noqa: TC001 — runtime resolution by FastAPI
    ApiContextDep,
    DbDep,
    log_usage,
)

logger = logging.getLogger("jpintel.api.edinet")

router = APIRouter(prefix="/v1/edinet", tags=["edinet"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENDPOINT_LIST = "edinet.filings.list"
ENDPOINT_FULL = "edinet.filings.full"

MAX_LIMIT = 100
DEFAULT_LIMIT = 20
MAX_SINCE_LOOKBACK_DAYS = 3650  # 10 年。EDINET 過去ログ最大窓。
SIGNED_URL_TTL_SECONDS = 600  # full_text_r2_url short-lived expiry


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class EdinetFiling(BaseModel):
    filing_id: str
    doc_id: str
    edinet_code: str
    security_code: str | None = None
    submit_date: str
    doc_type: str
    filer_houjin_bangou: str | None = None
    file_pdf_url: str | None = None
    file_xbrl_url: str | None = None
    body_text_excerpt: str = Field(default="")
    full_text_r2_url: str | None = None
    ingested_at: str


class EdinetListResponse(BaseModel):
    items: list[EdinetFiling]
    total: int
    limit: int
    offset: int


class EdinetFullResponse(BaseModel):
    """Full-body envelope.

    When `full_text_r2_url` is set, the caller is redirected to the R2
    signed URL. When NULL (e.g. early ingest before R2 link), the
    `body_text_excerpt` is the authoritative substrate the caller can use.
    """

    edinet_code: str
    doc_id: str
    submit_date: str
    doc_type: str
    full_text_r2_url: str | None = None
    body_text_excerpt: str
    signed_url_expires_at: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_filing(row: sqlite3.Row) -> EdinetFiling:
    return EdinetFiling(
        filing_id=row["filing_id"],
        doc_id=row["doc_id"],
        edinet_code=row["edinet_code"],
        security_code=row["security_code"],
        submit_date=row["submit_date"],
        doc_type=row["doc_type"],
        filer_houjin_bangou=row["filer_houjin_bangou"],
        file_pdf_url=row["file_pdf_url"],
        file_xbrl_url=row["file_xbrl_url"],
        body_text_excerpt=row["body_text_excerpt"] or "",
        full_text_r2_url=row["full_text_r2_url"],
        ingested_at=row["ingested_at"],
    )


def _list_filings(
    conn: sqlite3.Connection,
    *,
    houjin_bangou: str | None,
    doc_type: str | None,
    since: str | None,
    edinet_code: str | None,
    limit: int,
    offset: int,
) -> tuple[list[EdinetFiling], int]:
    """Run a filtered listing against am_edinet_filings."""
    clauses: list[str] = []
    params: list[Any] = []
    if houjin_bangou:
        clauses.append("filer_houjin_bangou = ?")
        params.append(houjin_bangou)
    if doc_type:
        clauses.append("doc_type = ?")
        params.append(doc_type)
    if since:
        clauses.append("submit_date >= ?")
        params.append(since)
    if edinet_code:
        clauses.append("edinet_code = ?")
        params.append(edinet_code)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    total_row = conn.execute(
        f"SELECT COUNT(*) AS c FROM am_edinet_filings {where}",
        params,
    ).fetchone()
    total = int(total_row["c"] if total_row else 0)

    rows = conn.execute(
        f"""SELECT filing_id, doc_id, edinet_code, security_code, submit_date,
                   doc_type, filer_houjin_bangou, file_pdf_url, file_xbrl_url,
                   body_text_excerpt, full_text_r2_url, ingested_at
              FROM am_edinet_filings
              {where}
             ORDER BY submit_date DESC, doc_id DESC
             LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    return [_row_to_filing(r) for r in rows], total


def _validate_since(since: str | None) -> str | None:
    if since is None:
        return None
    try:
        d = datetime.strptime(since, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"since must be YYYY-MM-DD ({exc})",
        ) from exc
    today = datetime.now(UTC).date()
    if d > today:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="since cannot be a future date.",
        )
    if (today - d).days > MAX_SINCE_LOOKBACK_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"since must be within {MAX_SINCE_LOOKBACK_DAYS} days.",
        )
    return since


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/filings",
    response_model=EdinetListResponse,
    summary="List EDINET filings",
)
def list_filings(
    bg: BackgroundTasks,
    conn: DbDep,
    ctx: ApiContextDep,
    houjin_bangou: Annotated[
        str | None,
        Query(
            min_length=13,
            max_length=13,
            description="13-digit 法人番号 filter.",
        ),
    ] = None,
    doc_type: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=16,
            description="EDINET docTypeCode filter (e.g. '120' = 有報, '350' = 大量保有).",
        ),
    ] = None,
    since: Annotated[
        str | None,
        Query(
            min_length=10,
            max_length=10,
            description="Inclusive lower bound submit_date (YYYY-MM-DD).",
        ),
    ] = None,
    edinet_code: Annotated[
        str | None,
        Query(
            min_length=6,
            max_length=12,
            description="EDINET code (E-prefix) filter.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EdinetListResponse:
    """Return EDINET filings filtered by houjin / doc_type / since / edinet_code."""
    if houjin_bangou and not houjin_bangou.isdigit():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="houjin_bangou must be 13 digits.",
        )
    if edinet_code:
        ec = edinet_code.strip().upper()
        if not ec.startswith("E"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="edinet_code must start with 'E'.",
            )
        edinet_code = ec
    since = _validate_since(since)

    items, total = _list_filings(
        conn,
        houjin_bangou=houjin_bangou,
        doc_type=doc_type,
        since=since,
        edinet_code=edinet_code,
        limit=limit,
        offset=offset,
    )
    log_usage(
        conn,
        ctx,
        ENDPOINT_LIST,
        status_code=200,
        result_count=len(items),
        background_tasks=bg,
        strict_metering=True,
    )
    return EdinetListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/filings/{edinet_code}/full",
    response_model=EdinetFullResponse,
    summary="Get latest full filing for an EDINET code",
)
def get_full_filing(
    bg: BackgroundTasks,
    conn: DbDep,
    ctx: ApiContextDep,
    edinet_code: Annotated[
        str,
        Path(min_length=6, max_length=12),
    ],
    doc_type: Annotated[
        str | None,
        Query(
            description="Optional EDINET docTypeCode to narrow ('120' = 有報).",
        ),
    ] = None,
) -> EdinetFullResponse:
    """Return the latest full-text envelope for an EDINET code.

    Requires API key (no anonymous full-body read; R2 signed URL is
    short-lived and re-issuance burns metering on us).
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required for /full surface.",
        )
    ec = edinet_code.strip().upper()
    if not ec.startswith("E"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="edinet_code must start with 'E'.",
        )

    where_parts = ["edinet_code = ?"]
    params: list[Any] = [ec]
    if doc_type:
        where_parts.append("doc_type = ?")
        params.append(doc_type)
    where = " AND ".join(where_parts)
    row = conn.execute(
        f"""SELECT filing_id, doc_id, edinet_code, submit_date, doc_type,
                   body_text_excerpt, full_text_r2_url, ingested_at
              FROM am_edinet_filings
             WHERE {where}
             ORDER BY submit_date DESC, doc_id DESC
             LIMIT 1""",
        params,
    ).fetchone()
    if row is None:
        log_usage(
            conn,
            ctx,
            ENDPOINT_FULL,
            status_code=404,
            result_count=0,
            background_tasks=bg,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no EDINET filing for {ec}",
        )

    expires_at = (
        (datetime.now(UTC) + timedelta(seconds=SIGNED_URL_TTL_SECONDS)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        if row["full_text_r2_url"]
        else None
    )
    log_usage(
        conn,
        ctx,
        ENDPOINT_FULL,
        status_code=200,
        result_count=1,
        background_tasks=bg,
        strict_metering=True,
    )
    return EdinetFullResponse(
        edinet_code=row["edinet_code"],
        doc_id=row["doc_id"],
        submit_date=row["submit_date"],
        doc_type=row["doc_type"],
        full_text_r2_url=row["full_text_r2_url"],
        body_text_excerpt=row["body_text_excerpt"] or "",
        signed_url_expires_at=expires_at,
    )
