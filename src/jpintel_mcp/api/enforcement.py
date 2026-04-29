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
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot, snapshot_headers
from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES, ErrorEnvelope
from jpintel_mcp.api.deps import (
    ApiContextDep,
    DbDep,
    log_empty_search,
    log_usage,
)
from jpintel_mcp.api.vocab import _normalize_prefecture
from jpintel_mcp.models import (
    EnforcementCase,
    EnforcementCaseSearchResponse,
)

router = APIRouter(prefix="/v1/enforcement-cases", tags=["enforcement-cases"])


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
                "source_title (LIKE, case-insensitive)."
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
