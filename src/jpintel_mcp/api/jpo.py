"""JPO 特許/実用新案 REST surface.

Endpoints
---------
    GET /v1/jpo/patents?houjin_bangou={n}&limit={k}&offset={o}
    GET /v1/jpo/patents/{application_no}
    GET /v1/jpo/utility_models?houjin_bangou={n}&limit={k}&offset={o}
    GET /v1/jpo/utility_models/{application_no}

Wave 31 Axis 1b. Backed by `am_jpo_patents` and `am_jpo_utility_models`
(migration 226, target_db=autonomath).

Pricing posture
---------------
    Authenticated metered ¥3/req per CALL. List + detail are both single
    billable units. Anonymous tier (AnonIpLimitDep at app wiring time)
    receives the standard 3/day per IP cap.

Auth
----
    Authenticated callers get full N-row pagination. Anonymous fall through
    the IP rate-limit fence at app-level dependency injection.

LLM call count: 0. Pure SQLite + Pydantic. Pure ¥3/req metered surface.
"""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger("jpintel.api.jpo")

router = APIRouter(prefix="/v1/jpo", tags=["jpo"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENDPOINT_PATENTS_LIST = "jpo.patents.list"
ENDPOINT_PATENTS_GET = "jpo.patents.get"
ENDPOINT_UM_LIST = "jpo.utility_models.list"
ENDPOINT_UM_GET = "jpo.utility_models.get"

MAX_LIMIT = 100
DEFAULT_LIMIT = 20


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class JpoRecord(BaseModel):
    """One JPO 特許 or 実用新案 row."""

    application_no: str
    registration_no: str | None = None
    title: str
    applicant_name: str
    applicant_houjin_bangou: str | None = None
    ipc_classification: str
    application_date: str
    registration_date: str | None = None
    status: str
    source_url: str
    body: str = Field(default="")
    applicants: list[str] = Field(default_factory=list)
    ipc_codes: list[str] = Field(default_factory=list)


class JpoListResponse(BaseModel):
    items: list[JpoRecord]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_record(row: sqlite3.Row) -> JpoRecord:
    """Convert a DB row to a JpoRecord, deserializing JSON columns."""
    columns = set(row.keys())
    raw_applicants = row["applicants_json"] if "applicants_json" in columns else "[]"
    raw_ipc = row["ipc_codes_json"] if "ipc_codes_json" in columns else "[]"
    try:
        applicants = json.loads(raw_applicants or "[]")
    except (TypeError, ValueError):
        applicants = []
    try:
        ipc_codes = json.loads(raw_ipc or "[]")
    except (TypeError, ValueError):
        ipc_codes = []
    return JpoRecord(
        application_no=row["application_no"],
        registration_no=row["registration_no"],
        title=row["title"],
        applicant_name=row["applicant_name"],
        applicant_houjin_bangou=row["applicant_houjin_bangou"],
        ipc_classification=row["ipc_classification"],
        application_date=row["application_date"],
        registration_date=row["registration_date"],
        status=row["status"],
        source_url=row["source_url"],
        body=row["body"] if "body" in columns else "",
        applicants=applicants,
        ipc_codes=ipc_codes,
    )


def _list_table(
    conn: sqlite3.Connection,
    table: str,
    *,
    houjin_bangou: str | None,
    limit: int,
    offset: int,
) -> tuple[list[JpoRecord], int]:
    """Run a houjin-filtered listing against `table`."""
    where = ""
    params: list[Any] = []
    if houjin_bangou:
        where = "WHERE applicant_houjin_bangou = ?"
        params.append(houjin_bangou)

    total_row = conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()
    total = int(total_row["c"] if total_row else 0)

    rows = conn.execute(
        f"""SELECT application_no, registration_no, title, body, applicant_name,
                   applicant_houjin_bangou, ipc_classification, application_date,
                   registration_date, status, source_url, applicants_json, ipc_codes_json
              FROM {table}
              {where}
             ORDER BY application_date DESC, application_no DESC
             LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    items = [_row_to_record(r) for r in rows]
    return items, total


def _get_table(
    conn: sqlite3.Connection,
    table: str,
    application_no: str,
) -> JpoRecord | None:
    """Fetch one row by application_no."""
    row = conn.execute(
        f"""SELECT application_no, registration_no, title, body, applicant_name,
                   applicant_houjin_bangou, ipc_classification, application_date,
                   registration_date, status, source_url, applicants_json, ipc_codes_json
              FROM {table}
             WHERE application_no = ?""",
        (application_no,),
    ).fetchone()
    return _row_to_record(row) if row else None


# ---------------------------------------------------------------------------
# Endpoints — Patents
# ---------------------------------------------------------------------------


@router.get(
    "/patents",
    response_model=JpoListResponse,
    summary="List 特許 (J-PlatPat) filings",
)
def list_patents(
    bg: BackgroundTasks,
    conn: DbDep,
    ctx: ApiContextDep,
    houjin_bangou: Annotated[
        str | None,
        Query(
            min_length=13,
            max_length=13,
            description="13-digit 法人番号 to filter by applicant.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JpoListResponse:
    """Return 特許 rows filed by the requested 法人 (if any)."""
    if houjin_bangou and not houjin_bangou.isdigit():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="houjin_bangou must be 13 digits.",
        )
    items, total = _list_table(
        conn,
        "am_jpo_patents",
        houjin_bangou=houjin_bangou,
        limit=limit,
        offset=offset,
    )
    log_usage(
        conn,
        ctx,
        ENDPOINT_PATENTS_LIST,
        status_code=200,
        result_count=len(items),
        background_tasks=bg,
        strict_metering=True,
    )
    return JpoListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/patents/{application_no}",
    response_model=JpoRecord,
    summary="Get a 特許 by application_no",
)
def get_patent(
    bg: BackgroundTasks,
    conn: DbDep,
    ctx: ApiContextDep,
    application_no: Annotated[
        str,
        Path(min_length=4, max_length=64),
    ],
) -> JpoRecord:
    """Detail surface for a single 特許 entry."""
    record = _get_table(conn, "am_jpo_patents", application_no)
    if record is None:
        log_usage(
            conn,
            ctx,
            ENDPOINT_PATENTS_GET,
            status_code=404,
            result_count=0,
            background_tasks=bg,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"patent not found: {application_no}",
        )
    log_usage(
        conn,
        ctx,
        ENDPOINT_PATENTS_GET,
        status_code=200,
        result_count=1,
        background_tasks=bg,
        strict_metering=True,
    )
    return record


# ---------------------------------------------------------------------------
# Endpoints — Utility models
# ---------------------------------------------------------------------------


@router.get(
    "/utility_models",
    response_model=JpoListResponse,
    summary="List 実用新案 (J-PlatPat) filings",
)
def list_utility_models(
    bg: BackgroundTasks,
    conn: DbDep,
    ctx: ApiContextDep,
    houjin_bangou: Annotated[
        str | None,
        Query(
            min_length=13,
            max_length=13,
            description="13-digit 法人番号 to filter by applicant.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JpoListResponse:
    """Return 実用新案 rows filed by the requested 法人 (if any)."""
    if houjin_bangou and not houjin_bangou.isdigit():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="houjin_bangou must be 13 digits.",
        )
    items, total = _list_table(
        conn,
        "am_jpo_utility_models",
        houjin_bangou=houjin_bangou,
        limit=limit,
        offset=offset,
    )
    log_usage(
        conn,
        ctx,
        ENDPOINT_UM_LIST,
        status_code=200,
        result_count=len(items),
        background_tasks=bg,
        strict_metering=True,
    )
    return JpoListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/utility_models/{application_no}",
    response_model=JpoRecord,
    summary="Get a 実用新案 by application_no",
)
def get_utility_model(
    bg: BackgroundTasks,
    conn: DbDep,
    ctx: ApiContextDep,
    application_no: Annotated[
        str,
        Path(min_length=4, max_length=64),
    ],
) -> JpoRecord:
    """Detail surface for a single 実用新案 entry."""
    record = _get_table(conn, "am_jpo_utility_models", application_no)
    if record is None:
        log_usage(
            conn,
            ctx,
            ENDPOINT_UM_GET,
            status_code=404,
            result_count=0,
            background_tasks=bg,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"utility model not found: {application_no}",
        )
    log_usage(
        conn,
        ctx,
        ENDPOINT_UM_GET,
        status_code=200,
        result_count=1,
        background_tasks=bg,
        strict_metering=True,
    )
    return record
