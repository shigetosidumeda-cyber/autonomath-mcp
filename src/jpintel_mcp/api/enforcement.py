"""REST handlers for enforcement_cases (会計検査院 findings).

Backed by migration 011's `enforcement_cases` table. 1,185 rows as of
2026-04-23; each is a historical instance of improper subsidy handling
(over-payment, diversion, eligibility failure, etc.). Consumers use this
surface for compliance / DD: "has this program triggered a clawback?",
"how much has this ministry over-distributed?", "is this recipient
under scrutiny?".

Scope boundary — this router is read-only. Case records are curated
externally (via ingest_external_data.py) and never mutated here.
"""
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot, snapshot_headers
from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES, ErrorEnvelope
from jpintel_mcp.api.deps import (
    ApiContextDep,
    DbDep,
    log_empty_search,
    log_usage,
)
from jpintel_mcp.api.vocab import _normalize_prefecture
from jpintel_mcp.config import settings
from jpintel_mcp.models import (
    EnforcementCase,
    EnforcementCaseSearchResponse,
)

router = APIRouter(prefix="/v1/enforcement-cases", tags=["enforcement-cases"])

EnforcementKind = Literal[
    "subsidy_exclude",
    "grant_refund",
    "contract_suspend",
    "business_improvement",
    "license_revoke",
    "fine",
    "investigation",
    "other",
]

_ENFORCEMENT_DETAIL_COVERAGE_NOTE = (
    "Local normalized mirror of public administrative enforcement records. "
    "No live web fetch is performed; absence of a match is not legal clearance."
)


class EnforcementDetail(BaseModel):
    """Normalized administrative enforcement row from autonomath.db."""

    model_config = ConfigDict(extra="forbid")

    enforcement_id: int
    entity_id: str
    houjin_bangou: str | None = None
    target_name: str | None = None
    enforcement_kind: EnforcementKind | None = None
    issuing_authority: str | None = None
    issuance_date: str
    exclusion_start: str | None = None
    exclusion_end: str | None = None
    active_on_requested_date: bool | None = None
    reason_summary: str | None = None
    related_law_ref: str | None = None
    amount_yen: int | None = None
    source_url: str | None = None
    source_fetched_at: str | None = None


class EnforcementDetailSearchResponse(BaseModel):
    """Paginated administrative enforcement detail search response."""

    model_config = ConfigDict(extra="forbid")

    total: int
    limit: int
    offset: int
    source_table: str = "am_enforcement_detail"
    no_live_fetch: bool = True
    coverage_note: str = Field(default=_ENFORCEMENT_DETAIL_COVERAGE_NOTE)
    results: list[EnforcementDetail] = Field(default_factory=list)


def _autonomath_db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return settings.autonomath_db_path


def _open_autonomath_ro() -> sqlite3.Connection | None:
    path = _autonomath_db_path()
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def _normalize_houjin_bangou(raw: str) -> str | None:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 13:
        return None
    return digits


def _row_to_case(row: sqlite3.Row) -> EnforcementCase:
    fy_raw = row["occurred_fiscal_years_json"]
    fy: list[int] = []
    if fy_raw:
        try:
            parsed = json.loads(fy_raw)
            if isinstance(parsed, list):
                fy = [int(x) for x in parsed if isinstance(x, (int, str)) and str(x).lstrip("-").isdigit()]
        except (json.JSONDecodeError, ValueError):
            fy = []

    sole = row["is_sole_proprietor"]
    is_sole: bool | None = None if sole is None else bool(sole)

    return EnforcementCase(
        case_id=row["case_id"],
        event_type=row["event_type"],
        program_name_hint=row["program_name_hint"],
        recipient_name=row["recipient_name"],
        recipient_kind=row["recipient_kind"],
        recipient_houjin_bangou=row["recipient_houjin_bangou"],
        is_sole_proprietor=is_sole,
        bureau=row["bureau"],
        intermediate_recipient=row["intermediate_recipient"],
        prefecture=row["prefecture"],
        ministry=row["ministry"],
        occurred_fiscal_years=fy,
        amount_yen=row["amount_yen"],
        amount_project_cost_yen=row["amount_project_cost_yen"],
        amount_grant_paid_yen=row["amount_grant_paid_yen"],
        amount_improper_grant_yen=row["amount_improper_grant_yen"],
        amount_improper_project_cost_yen=row["amount_improper_project_cost_yen"],
        reason_excerpt=row["reason_excerpt"],
        legal_basis=row["legal_basis"],
        source_url=row["source_url"],
        source_section=row["source_section"],
        source_title=row["source_title"],
        disclosed_date=row["disclosed_date"],
        disclosed_until=row["disclosed_until"],
        fetched_at=row["fetched_at"],
        confidence=row["confidence"],
    )


def _row_to_enforcement_detail(
    row: sqlite3.Row, *, active_on: str | None
) -> EnforcementDetail:
    active_on_requested_date: bool | None = None
    if active_on is not None:
        active_start = row["exclusion_start"] or row["issuance_date"]
        active_end = row["exclusion_end"] or "9999-12-31"
        active_on_requested_date = active_start <= active_on <= active_end

    return EnforcementDetail(
        enforcement_id=row["enforcement_id"],
        entity_id=row["entity_id"],
        houjin_bangou=row["houjin_bangou"],
        target_name=row["target_name"],
        enforcement_kind=row["enforcement_kind"],
        issuing_authority=row["issuing_authority"],
        issuance_date=row["issuance_date"],
        exclusion_start=row["exclusion_start"],
        exclusion_end=row["exclusion_end"],
        active_on_requested_date=active_on_requested_date,
        reason_summary=row["reason_summary"],
        related_law_ref=row["related_law_ref"],
        amount_yen=row["amount_yen"],
        source_url=row["source_url"],
        source_fetched_at=row["source_fetched_at"],
    )


@router.get(
    "/search",
    response_model=EnforcementCaseSearchResponse,
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": (
                "Paginated 行政処分 / 会計検査院 indications. Use this for "
                "compliance / due-diligence on a recipient or program."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "total": 1,
                        "limit": 20,
                        "offset": 0,
                        "results": [
                            {
                                "case_id": "ENF-jftc-2024-00045",
                                "event_type": "排除措置命令",
                                "program_name_hint": None,
                                "recipient_name": "株式会社サンプル建設",
                                "recipient_kind": "houjin",
                                "recipient_houjin_bangou": "9876543210987",
                                "ministry": "公正取引委員会",
                                "prefecture": "大阪府",
                                "amount_yen": 12500000,
                                "reason_excerpt": "公共工事入札談合の事実を認定。",
                                "source_url": "https://www.jftc.go.jp/houdou/pressrelease/2024/feb/...",
                                "source_title": "排除措置命令及び課徴金納付命令について",
                                "disclosed_date": "2024-02-15",
                                "fetched_at": "2026-04-22T08:11:00Z",
                                "confidence": 0.98,
                            }
                        ],
                    }
                }
            },
        },
    },
)
def search_enforcement_cases(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    q: Annotated[
        str | None,
        Query(
            description=(
                "Free-text search over program_name_hint + reason_excerpt + "
                "source_title (case-insensitive text match)."
            ),
            max_length=200,
        ),
    ] = None,
    event_type: Annotated[str | None, Query(max_length=80)] = None,
    ministry: Annotated[str | None, Query(max_length=120)] = None,
    prefecture: Annotated[str | None, Query(max_length=80)] = None,
    legal_basis: Annotated[str | None, Query(max_length=200)] = None,
    program_name_hint: Annotated[str | None, Query(max_length=200)] = None,
    recipient_houjin_bangou: Annotated[
        str | None,
        Query(
            max_length=13,
            description=(
                "13-digit 法人番号 filter. NOTE: this column is 100% NULL across all "
                "1,185 enforcement cases because 会計検査院 does not publish 法人番号. "
                "Filtering by this parameter will always return 0 rows. "
                "Use `q=<company_name>` or `q=<houjin_bangou_digits>` for substring search over "
                "source_title / reason_excerpt / program_name_hint instead."
            ),
        ),
    ] = None,
    min_improper_grant_yen: Annotated[int | None, Query(ge=0)] = None,
    max_improper_grant_yen: Annotated[int | None, Query(ge=0)] = None,
    disclosed_from: Annotated[
        str | None,
        Query(
            description="ISO date (YYYY-MM-DD) — inclusive lower bound on disclosed_date.",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
    disclosed_until: Annotated[
        str | None,
        Query(
            description="ISO date (YYYY-MM-DD) — inclusive upper bound on disclosed_date.",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EnforcementCaseSearchResponse:
    """Search enforcement cases for compliance / DD lookup."""
    _t0 = time.perf_counter()

    where: list[str] = []
    params: list[Any] = []

    if q:
        # SQLite LIKE is case-insensitive for ASCII but not for Japanese; we
        # accept that limitation since the bulk of the corpus is JP and all
        # case-folding candidates (ministry names etc.) are already normalised.
        like = f"%{q}%"
        where.append(
            "(program_name_hint LIKE ? OR reason_excerpt LIKE ? OR source_title LIKE ?)"
        )
        params.extend([like, like, like])

    if event_type:
        where.append("event_type = ?")
        params.append(event_type)
    if ministry:
        where.append("ministry = ?")
        params.append(ministry)
    prefecture = _normalize_prefecture(prefecture)
    if prefecture:
        where.append("prefecture = ?")
        params.append(prefecture)
    if legal_basis:
        where.append("legal_basis LIKE ?")
        params.append(f"%{legal_basis}%")
    if program_name_hint:
        where.append("program_name_hint LIKE ?")
        params.append(f"%{program_name_hint}%")
    if recipient_houjin_bangou:
        where.append("recipient_houjin_bangou = ?")
        params.append(recipient_houjin_bangou)
    if min_improper_grant_yen is not None:
        where.append("amount_improper_grant_yen >= ?")
        params.append(min_improper_grant_yen)
    if max_improper_grant_yen is not None:
        where.append("amount_improper_grant_yen <= ?")
        params.append(max_improper_grant_yen)
    if disclosed_from:
        where.append("disclosed_date >= ?")
        params.append(disclosed_from)
    if disclosed_until:
        where.append("disclosed_date <= ?")
        params.append(disclosed_until)

    where_sql = " AND ".join(where) if where else "1=1"

    (total,) = conn.execute(
        f"SELECT COUNT(*) FROM enforcement_cases WHERE {where_sql}", params
    ).fetchone()

    rows = conn.execute(
        f"""SELECT * FROM enforcement_cases
            WHERE {where_sql}
            ORDER BY
                COALESCE(disclosed_date, '') DESC,
                case_id
            LIMIT ? OFFSET ?""",
        [*params, limit, offset],
    ).fetchall()

    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "enforcement.search",
        latency_ms=_latency_ms,
        result_count=total,
    )

    if total == 0 and q is not None:
        _q_clean = q.strip()
        if len(_q_clean) > 1:
            log_empty_search(
                conn,
                query=_q_clean,
                endpoint="search_enforcement_cases",
                filters={
                    "event_type": event_type,
                    "ministry": ministry,
                    "prefecture": prefecture,
                    "legal_basis": legal_basis,
                    "program_name_hint": program_name_hint,
                    "recipient_houjin_bangou": recipient_houjin_bangou,
                    "min_improper_grant_yen": min_improper_grant_yen,
                    "max_improper_grant_yen": max_improper_grant_yen,
                    "disclosed_from": disclosed_from,
                    "disclosed_until": disclosed_until,
                },
                ip=request.client.host if request.client else None,
            )

    return EnforcementCaseSearchResponse(
        total=total,
        limit=limit,
        offset=offset,
        results=[_row_to_case(r) for r in rows],
    )


@router.get(
    "/details/search",
    response_model=EnforcementDetailSearchResponse,
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": (
                "Search normalized administrative enforcement details from "
                "the local public-source mirror. This is useful before an "
                "agent spends a long context window on compliance DD."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "total": 1,
                        "limit": 20,
                        "offset": 0,
                        "source_table": "am_enforcement_detail",
                        "no_live_fetch": True,
                        "coverage_note": _ENFORCEMENT_DETAIL_COVERAGE_NOTE,
                        "results": [
                            {
                                "enforcement_id": 42,
                                "entity_id": "houjin:1234567890123",
                                "houjin_bangou": "1234567890123",
                                "target_name": "株式会社サンプル建設",
                                "enforcement_kind": "business_improvement",
                                "issuing_authority": "国土交通省",
                                "issuance_date": "2026-04-15",
                                "exclusion_start": "2026-04-20",
                                "exclusion_end": "2026-06-20",
                                "active_on_requested_date": True,
                                "reason_summary": "監督処分の概要。",
                                "related_law_ref": "建設業法",
                                "amount_yen": None,
                                "source_url": "https://example.go.jp/source.pdf",
                                "source_fetched_at": "2026-04-30T00:00:00Z",
                            }
                        ],
                    }
                }
            },
        },
        503: {
            "model": ErrorEnvelope,
            "description": "normalized enforcement detail corpus unavailable.",
        },
    },
)
def search_enforcement_details(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    q: Annotated[
        str | None,
        Query(
            description=(
                "Free-text search over target_name, reason_summary, "
                "issuing_authority, and related_law_ref."
            ),
            max_length=200,
        ),
    ] = None,
    houjin_bangou: Annotated[
        str | None,
        Query(
            description="13-digit 法人番号 filter. Accepts optional T prefix/hyphens.",
            max_length=32,
        ),
    ] = None,
    target_name: Annotated[str | None, Query(max_length=200)] = None,
    enforcement_kind: Annotated[
        EnforcementKind | None,
        Query(description="Administrative enforcement category."),
    ] = None,
    issuing_authority: Annotated[str | None, Query(max_length=160)] = None,
    issued_from: Annotated[
        str | None,
        Query(
            description="ISO date (YYYY-MM-DD) inclusive lower bound on issuance_date.",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
    issued_until: Annotated[
        str | None,
        Query(
            description="ISO date (YYYY-MM-DD) inclusive upper bound on issuance_date.",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
    active_on: Annotated[
        str | None,
        Query(
            description=(
                "ISO date (YYYY-MM-DD). Returns rows whose exclusion/improvement "
                "window covers this date. If exclusion_start is missing, "
                "issuance_date is used as the start."
            ),
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
    include_future: Annotated[
        bool,
        Query(
            description=(
                "Include rows whose issuance_date is in the future. Default false "
                "keeps ordinary searches focused on already published/current rows."
            ),
        ),
    ] = False,
    min_amount_yen: Annotated[int | None, Query(ge=0)] = None,
    max_amount_yen: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EnforcementDetailSearchResponse:
    """Search normalized administrative enforcement details."""
    _t0 = time.perf_counter()

    if issued_from and issued_until and issued_from > issued_until:
        raise HTTPException(422, "issued_from after issued_until")
    if min_amount_yen is not None and max_amount_yen is not None and min_amount_yen > max_amount_yen:
        raise HTTPException(
            422,
            "min_amount_yen cannot exceed max_amount_yen",
        )

    where: list[str] = []
    params: list[Any] = []
    filter_keys: list[str] = []

    if q:
        like = f"%{q.strip()}%"
        where.append(
            "(target_name LIKE ? OR reason_summary LIKE ? OR issuing_authority LIKE ? OR related_law_ref LIKE ?)"
        )
        params.extend([like, like, like, like])
        filter_keys.append("q")

    if houjin_bangou:
        normalized_houjin = _normalize_houjin_bangou(houjin_bangou)
        if normalized_houjin is None:
            raise HTTPException(
                422,
                "houjin_bangou must contain exactly 13 digits",
            )
        where.append("houjin_bangou = ?")
        params.append(normalized_houjin)
        filter_keys.append("houjin_bangou")
    if target_name:
        where.append("target_name LIKE ?")
        params.append(f"%{target_name}%")
        filter_keys.append("target_name")
    if enforcement_kind:
        where.append("enforcement_kind = ?")
        params.append(enforcement_kind)
        filter_keys.append("enforcement_kind")
    if issuing_authority:
        where.append("issuing_authority LIKE ?")
        params.append(f"%{issuing_authority}%")
        filter_keys.append("issuing_authority")
    if issued_from:
        where.append("issuance_date >= ?")
        params.append(issued_from)
        filter_keys.append("issued_from")
    if issued_until:
        where.append("issuance_date <= ?")
        params.append(issued_until)
        filter_keys.append("issued_until")
    if active_on:
        where.append(
            "(COALESCE(exclusion_start, issuance_date) <= ? "
            "AND COALESCE(exclusion_end, '9999-12-31') >= ?)"
        )
        params.extend([active_on, active_on])
        filter_keys.append("active_on")
    if (
        not include_future
        and issued_from is None
        and issued_until is None
        and active_on is None
    ):
        where.append("issuance_date <= date('now')")
        filter_keys.append("default_past_or_current")
    if min_amount_yen is not None:
        where.append("amount_yen >= ?")
        params.append(min_amount_yen)
        filter_keys.append("min_amount_yen")
    if max_amount_yen is not None:
        where.append("amount_yen <= ?")
        params.append(max_amount_yen)
        filter_keys.append("max_amount_yen")

    where_sql = " AND ".join(where) if where else "1=1"

    am_conn = _open_autonomath_ro()
    if am_conn is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "normalized enforcement detail corpus unavailable",
        )

    try:
        (total,) = am_conn.execute(
            f"SELECT COUNT(*) FROM am_enforcement_detail WHERE {where_sql}", params
        ).fetchone()

        rows = am_conn.execute(
            f"""SELECT
                    enforcement_id,
                    entity_id,
                    houjin_bangou,
                    target_name,
                    enforcement_kind,
                    issuing_authority,
                    issuance_date,
                    exclusion_start,
                    exclusion_end,
                    reason_summary,
                    related_law_ref,
                    amount_yen,
                    source_url,
                    source_fetched_at
                FROM am_enforcement_detail
                WHERE {where_sql}
                ORDER BY
                    COALESCE(issuance_date, '') DESC,
                    enforcement_id DESC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "normalized enforcement detail corpus unavailable",
        ) from exc
    finally:
        am_conn.close()

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "enforcement.details.search",
        latency_ms=latency_ms,
        result_count=total,
        params={
            "filter_keys": filter_keys,
            "has_q": q is not None,
            "enforcement_kind": enforcement_kind,
            "include_future": include_future,
            "limit": limit,
            "offset": offset,
        },
        request=request,
    )

    return EnforcementDetailSearchResponse(
        total=total,
        limit=limit,
        offset=offset,
        results=[_row_to_enforcement_detail(row, active_on=active_on) for row in rows],
    )


@router.get(
    "/{case_id}",
    response_model=EnforcementCase,
    responses={
        **COMMON_ERROR_RESPONSES,
        404: {
            "model": ErrorEnvelope,
            "description": "case not found — `error.code='no_matching_records'`.",
        },
    },
)
def get_enforcement_case(
    case_id: str,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Return one enforcement case with audit-trail snapshot fields.

    Audit trail (会計士 work-paper, added 2026-04-29): the response includes
    `corpus_snapshot_id` + `corpus_checksum` so an auditor citing this
    行政処分 case in a work-paper can reproduce the lookup later and detect
    whether the corpus mutated. See docs/audit_trail.md.
    """
    row = conn.execute(
        "SELECT * FROM enforcement_cases WHERE case_id = ?", (case_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"case not found: {case_id}")

    log_usage(conn, ctx, "enforcement.get")
    body = _row_to_case(row).model_dump(mode="json")
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body, headers=snapshot_headers(conn))
