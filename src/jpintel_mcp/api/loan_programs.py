"""REST handlers for loan_programs (公庫 / 自治体融資 / 信金 等).

Backed by migration 010's `loan_programs` table, widened by 013 to carry
three independent risk axes (collateral / personal guarantor /
third-party guarantor). 108 rows as of 2026-04-23.

Rationale — user feedback 2026-04-23: 無担保・無保証 vs. 担保あり・
保証人あり は別のリスクプロファイルであり、単一 `security_required`
free-text では機械フィルタが不可能だった。三軸に分けたのでこの API は
三軸受けで検索できる (例: `collateral=not_required&third_party_guarantor=
not_required` → 無担保・無保証人 の抽出)。

Scope: read-only.
"""

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
from jpintel_mcp.models import LoanProgram, LoanProgramSearchResponse

router = APIRouter(prefix="/v1/loan-programs", tags=["loan-programs"])

_RISK_VALUES = ("required", "not_required", "negotiable", "unknown")


def _row_to_loan(row: sqlite3.Row) -> LoanProgram:
    return LoanProgram(
        id=row["id"],
        program_name=row["program_name"],
        provider=row["provider"],
        loan_type=row["loan_type"],
        amount_max_yen=row["amount_max_yen"],
        loan_period_years_max=row["loan_period_years_max"],
        grace_period_years_max=row["grace_period_years_max"],
        interest_rate_base_annual=row["interest_rate_base_annual"],
        interest_rate_special_annual=row["interest_rate_special_annual"],
        rate_names=row["rate_names"],
        security_required=row["security_required"],
        target_conditions=row["target_conditions"],
        official_url=row["official_url"],
        source_excerpt=row["source_excerpt"],
        fetched_at=row["fetched_at"],
        confidence=row["confidence"],
        collateral_required=row["collateral_required"],
        personal_guarantor_required=row["personal_guarantor_required"],
        third_party_guarantor_required=row["third_party_guarantor_required"],
        security_notes=row["security_notes"],
    )


@router.get(
    "/search",
    response_model=LoanProgramSearchResponse,
    summary="Search loan programs (公庫 / 商工中金 / 自治体) — 3-axis risk filter",
    description=(
        "Search the 108-row `loan_programs` table by free-text + lender + "
        "interest-rate + amount + 3-axis risk independently. The three "
        "guarantor axes were split in migration 013 because '要相談' "
        "free-text muddles the question 'is 経営者保証 actually waivable?' "
        "— each axis is now a discrete enum (`required` / `not_required` "
        "/ `negotiable` / `unknown`).\n\n"
        "**Risk axes:**\n"
        "- `collateral_required` — 物的担保 (real-estate / inventory)\n"
        "- `personal_guarantor_required` — 代表者保証 / 役員保証 / 家族保証\n"
        "- `third_party_guarantor_required` — 第三者保証\n\n"
        "**When to use this vs `/v1/am/loans`:** this endpoint is the "
        "legacy public REST surface (jpintel.db). For richer entity "
        "provenance + cross-domain joins, prefer `/v1/am/loans` "
        "(autonomath.db, unified)."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": (
                "Three-axis loan search. Filter on collateral / personal_guarantor / "
                "third_party_guarantor independently — see migration 013 for the "
                "axis split."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "total": 1,
                        "limit": 20,
                        "offset": 0,
                        "results": [
                            {
                                "id": 12,
                                "program_name": "新規開業資金（女性、若者/シニア起業家支援関連）",
                                "provider": "日本政策金融公庫",
                                "loan_type": "国民生活事業",
                                "amount_max_yen": 72000000,
                                "loan_period_years_max": 20,
                                "grace_period_years_max": 2,
                                "interest_rate_base_annual": 1.50,
                                "interest_rate_special_annual": 0.95,
                                "rate_names": "基準利率/特別利率A",
                                "collateral_required": "negotiable",
                                "personal_guarantor_required": "negotiable",
                                "third_party_guarantor_required": "not_required",
                                "security_notes": "代表者保証は希望に応じて. 第三者保証人は原則不要.",
                                "official_url": "https://www.jfc.go.jp/n/finance/search/02_kaigyou_m.html",
                                "fetched_at": "2026-04-22T08:11:00Z",
                                "confidence": 0.95,
                            }
                        ],
                    }
                }
            },
        },
    },
)
def search_loan_programs(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    q: Annotated[
        str | None,
        Query(
            description=("Free-text search over program_name + provider + target_conditions."),
            max_length=200,
        ),
    ] = None,
    provider: Annotated[str | None, Query(max_length=200)] = None,
    loan_type: Annotated[str | None, Query(max_length=80)] = None,
    collateral_required: Annotated[
        str | None,
        Query(
            description=(
                "Risk axis 1 (物的担保). One of: required | not_required | negotiable | unknown."
            ),
            max_length=20,
        ),
    ] = None,
    personal_guarantor_required: Annotated[
        str | None,
        Query(
            description=(
                "Risk axis 2 (代表者/役員/家族保証). One of: required | "
                "not_required | negotiable | unknown."
            ),
            max_length=20,
        ),
    ] = None,
    third_party_guarantor_required: Annotated[
        str | None,
        Query(
            description=(
                "Risk axis 3 (第三者保証). One of: required | not_required | negotiable | unknown."
            ),
            max_length=20,
        ),
    ] = None,
    min_amount_yen: Annotated[int | None, Query(ge=0)] = None,
    max_amount_yen: Annotated[int | None, Query(ge=0)] = None,
    max_interest_rate: Annotated[
        float | None,
        Query(
            ge=0.0,
            description=("Upper bound on interest_rate_base_annual (e.g. 0.015 for 1.5%)."),
        ),
    ] = None,
    min_loan_period_years: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LoanProgramSearchResponse:
    """Search loan programs with three-axis risk filters."""
    _t0 = time.perf_counter()

    where: list[str] = []
    params: list[Any] = []

    if q:
        like = f"%{q}%"
        where.append(
            "(COALESCE(program_name,'') LIKE ? "
            "OR COALESCE(provider,'') LIKE ? "
            "OR COALESCE(target_conditions,'') LIKE ?)"
        )
        params.extend([like, like, like])
    if provider:
        where.append("provider = ?")
        params.append(provider)
    if loan_type:
        where.append("loan_type = ?")
        params.append(loan_type)
    for col, val in (
        ("collateral_required", collateral_required),
        ("personal_guarantor_required", personal_guarantor_required),
        ("third_party_guarantor_required", third_party_guarantor_required),
    ):
        if val is None:
            continue
        if val not in _RISK_VALUES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{col} must be one of {_RISK_VALUES}, got {val!r}",
            )
        where.append(f"{col} = ?")
        params.append(val)
    if min_amount_yen is not None:
        where.append("amount_max_yen >= ?")
        params.append(min_amount_yen)
    if max_amount_yen is not None:
        where.append("amount_max_yen <= ?")
        params.append(max_amount_yen)
    if max_interest_rate is not None:
        where.append("interest_rate_base_annual <= ?")
        params.append(max_interest_rate)
    if min_loan_period_years is not None:
        where.append("loan_period_years_max >= ?")
        params.append(min_loan_period_years)

    where_sql = " AND ".join(where) if where else "1=1"

    (total,) = conn.execute(
        f"SELECT COUNT(*) FROM loan_programs WHERE {where_sql}", params
    ).fetchone()

    rows = conn.execute(
        f"""SELECT * FROM loan_programs
            WHERE {where_sql}
            ORDER BY
                COALESCE(amount_max_yen, 0) DESC,
                id
            LIMIT ? OFFSET ?""",
        [*params, limit, offset],
    ).fetchall()

    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "loan_programs.search",
        latency_ms=_latency_ms,
        result_count=total,
        strict_metering=True,
    )

    if total == 0 and q is not None:
        _q_clean = q.strip()
        if len(_q_clean) > 1:
            log_empty_search(
                conn,
                query=_q_clean,
                endpoint="search_loan_programs",
                filters={
                    "provider": provider,
                    "loan_type": loan_type,
                    "collateral_required": collateral_required,
                    "personal_guarantor_required": personal_guarantor_required,
                    "third_party_guarantor_required": third_party_guarantor_required,
                    "min_amount_yen": min_amount_yen,
                    "max_amount_yen": max_amount_yen,
                    "max_interest_rate": max_interest_rate,
                    "min_loan_period_years": min_loan_period_years,
                },
                ip=request.client.host if request.client else None,
            )

    return LoanProgramSearchResponse(
        total=total,
        limit=limit,
        offset=offset,
        results=[_row_to_loan(r) for r in rows],
    )


@router.get(
    "/{loan_id}",
    response_model=LoanProgram,
    summary="Get a single loan program by integer id",
    description=(
        "Look up one loan product by its integer `id` (the autoincrement "
        "PK on `loan_programs`). Returns full lender / amount band / "
        "interest rate / 3-axis risk / target conditions / source lineage "
        "(`official_url`, `fetched_at`, `confidence`).\n\n"
        "Discovery flow: call `GET /v1/loan-programs/search` first, then "
        "follow up on each `id` with this endpoint. For unified "
        "entity-id-based lookups (cross-program), use `/v1/am/loans`."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": "Single LoanProgram row.",
            "content": {
                "application/json": {
                    "example": {
                        "id": 1,
                        "program_name": "新規開業・スタートアップ支援資金",
                        "provider": "日本政策金融公庫 国民生活事業",
                        "loan_type": "special_rate",
                        "amount_max_yen": 72000000,
                        "loan_period_years_max": 20,
                        "grace_period_years_max": 5,
                        "interest_rate_base_annual": 0.041,
                        "rate_names": "基準利率,特別利率",
                        "collateral_required": "negotiable",
                        "personal_guarantor_required": "negotiable",
                        "third_party_guarantor_required": "negotiable",
                        "security_notes": "要相談（担保・保証）",
                        "official_url": "https://www.jfc.go.jp/n/finance/search/01_sinkikaigyou_m.html",
                        "fetched_at": "2026-04-23T04:32:55Z",
                        "confidence": 0.9,
                    }
                }
            },
        },
        404: {
            "model": ErrorEnvelope,
            "description": "loan program not found — `error.code='no_matching_records'`.",
        },
    },
)
def get_loan_program(
    loan_id: int,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Return one loan program with corpus snapshot fields.

    The response includes `corpus_snapshot_id` + `corpus_checksum` so callers
    can reproduce the lookup later and detect whether the corpus changed.
    """
    row = conn.execute("SELECT * FROM loan_programs WHERE id = ?", (loan_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"loan program not found: {loan_id}")

    log_usage(conn, ctx, "loan_programs.get", strict_metering=True)
    body = _row_to_loan(row).model_dump(mode="json")
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body, headers=snapshot_headers(conn))
