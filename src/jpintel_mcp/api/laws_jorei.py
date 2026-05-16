"""REST surface for 都道府県条例 (`am_law_jorei_pref`, migration 252).

Wave 43.1.5 — 47 都道府県 × ~100 ordinances corpus. Read-only; ETL
writes via `scripts/etl/fill_laws_jorei_47pref_2x.py`.

Endpoints (mounted at /v1/laws_jorei_pref):

  GET /v1/laws_jorei_pref/search       - free-text + prefecture filter
  GET /v1/laws_jorei_pref/{canonical_id} - single row by canonical id
  GET /v1/laws_jorei_pref/stats        - per-prefecture density snapshot

No LLM, pure SELECT against autonomath.db. AnonIpLimitDep applied at
include. 都道府県条例 is `gov_public` license (条例 = 公文書 + 著作物性
不在 per 著作権法 §13) — relay source_url honestly.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/laws_jorei_pref", tags=["laws_jorei_pref"])


def _autonomath_conn() -> sqlite3.Connection:
    return connect_autonomath()


AutonomathDbDep = Annotated[sqlite3.Connection, Depends(_autonomath_conn)]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class JoreiPrefRow(BaseModel):
    canonical_id: str
    law_id: str | None = None
    prefecture_code: str
    prefecture_name: str
    jorei_number: str | None = None
    jorei_title: str
    jorei_kind: str
    enacted_date: str | None = None
    last_revised: str | None = None
    body_text_excerpt: str | None = None
    source_url: str
    license: str
    fetched_at: str
    confidence: float


class JoreiPrefSearchResponse(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[JoreiPrefRow]


class JoreiPrefStatsRow(BaseModel):
    prefecture_code: str
    prefecture_name: str
    row_count: int
    most_recent_enacted: str | None = None
    most_recent_fetch: str | None = None


class JoreiPrefStatsResponse(BaseModel):
    total_rows: int
    prefectures_covered: int
    by_prefecture: list[JoreiPrefStatsRow]
    note: str = Field(
        default=(
            "都道府県条例 corpus (Wave 43.1.5). 一次資料 = 47 都道府県の "
            "*.pref.{slug}.lg.jp 例規データベース. 著作権法 §13 により "
            "条例本文は再配布 OK。aggregator URL は ETL で refused."
        )
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_model(row: sqlite3.Row) -> JoreiPrefRow:
    return JoreiPrefRow(
        canonical_id=row["canonical_id"],
        law_id=row["law_id"],
        prefecture_code=row["prefecture_code"],
        prefecture_name=row["prefecture_name"],
        jorei_number=row["jorei_number"],
        jorei_title=row["jorei_title"],
        jorei_kind=row["jorei_kind"],
        enacted_date=row["enacted_date"],
        last_revised=row["last_revised"],
        body_text_excerpt=row["body_text_excerpt"],
        source_url=row["source_url"],
        license=row["license"],
        fetched_at=row["fetched_at"],
        confidence=float(row["confidence"]),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/search",
    response_model=JoreiPrefSearchResponse,
    summary="Search 都道府県条例 corpus",
    description=(
        "Search the 47-都道府県 条例 corpus by free-text + prefecture "
        "code + 条例 kind. Backed by `am_law_jorei_pref` + FTS5 trigram. "
        "Source = each 都道府県's 公式 例規データベース (*.pref.{slug}.lg.jp). "
        "License = gov_public (著作権法 §13: 公文書非著作物). Aggregators "
        "are refused at ETL ingest time."
    ),
)
def search_jorei(
    conn: AutonomathDbDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    prefecture_code: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    jorei_kind: Annotated[str | None, Query()] = None,
    enacted_from: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
    enacted_to: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JoreiPrefSearchResponse:
    """Search 都道府県条例 corpus."""
    if jorei_kind and jorei_kind not in (
        "jorei",
        "kisoku",
        "kunrei",
        "kokuji",
        "youkou",
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="jorei_kind must be one of: jorei|kisoku|kunrei|kokuji|youkou",
        )

    where: list[str] = []
    params: list[Any] = []
    join_fts = False

    if q:
        q_clean = q.strip()
        if len(q_clean) >= 3:
            join_fts = True
            params.append(q_clean)
        else:
            # Single/double kanji fallback to LIKE on title
            where.append("jorei_title LIKE ?")
            params.append(f"%{q_clean}%")

    if prefecture_code:
        where.append("prefecture_code = ?")
        params.append(prefecture_code)
    if jorei_kind:
        where.append("jorei_kind = ?")
        params.append(jorei_kind)
    if enacted_from:
        where.append("enacted_date >= ?")
        params.append(enacted_from)
    if enacted_to:
        where.append("enacted_date <= ?")
        params.append(enacted_to)

    if join_fts:
        base_from = "am_law_jorei_pref_fts JOIN am_law_jorei_pref USING(canonical_id)"
        where_clause = "am_law_jorei_pref_fts MATCH ?"
        if where:
            where_clause += " AND " + " AND ".join(where)
    else:
        base_from = "am_law_jorei_pref"
        where_clause = " AND ".join(where) if where else "1=1"

    try:
        count_sql = f"SELECT COUNT(*) FROM {base_from} WHERE {where_clause}"
        (total,) = conn.execute(count_sql, params).fetchone()

        order_sql = "ORDER BY COALESCE(enacted_date, fetched_at) DESC, canonical_id ASC"
        select_sql = (
            f"SELECT am_law_jorei_pref.* FROM {base_from} "
            f"WHERE {where_clause} {order_sql} LIMIT ? OFFSET ?"
        )
        rows = conn.execute(select_sql, [*params, limit, offset]).fetchall()
    except sqlite3.OperationalError as exc:
        LOG.warning("search_jorei query failed: %s", exc)
        # Schema not present yet (migration 252 not applied) — surface
        # an honest empty response so callers can detect via 200 + zero.
        return JoreiPrefSearchResponse(total=0, limit=limit, offset=offset, results=[])

    return JoreiPrefSearchResponse(
        total=int(total),
        limit=limit,
        offset=offset,
        results=[_row_to_model(r) for r in rows],
    )


@router.get(
    "/stats",
    response_model=JoreiPrefStatsResponse,
    summary="都道府県条例 corpus density per prefecture",
    description=(
        "Snapshot of per-prefecture row counts + most-recent enactment / "
        "fetch timestamps. Useful for ETL coverage audits."
    ),
)
def jorei_stats(conn: AutonomathDbDep) -> JoreiPrefStatsResponse:
    try:
        rows = conn.execute(
            "SELECT prefecture_code, prefecture_name, row_count, "
            "most_recent_enacted, most_recent_fetch "
            "FROM v_law_jorei_pref_density"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        LOG.warning("jorei_stats view missing: %s", exc)
        rows = []

    by_pref = [
        JoreiPrefStatsRow(
            prefecture_code=r["prefecture_code"],
            prefecture_name=r["prefecture_name"],
            row_count=int(r["row_count"]),
            most_recent_enacted=r["most_recent_enacted"],
            most_recent_fetch=r["most_recent_fetch"],
        )
        for r in rows
    ]
    total_rows = sum(p.row_count for p in by_pref)
    return JoreiPrefStatsResponse(
        total_rows=total_rows,
        prefectures_covered=len(by_pref),
        by_prefecture=by_pref,
    )


@router.get(
    "/{canonical_id}",
    response_model=JoreiPrefRow,
    summary="Single 都道府県条例 row by canonical id",
)
def get_jorei(canonical_id: str, conn: AutonomathDbDep) -> JoreiPrefRow:
    try:
        row = conn.execute(
            "SELECT * FROM am_law_jorei_pref WHERE canonical_id = ?",
            (canonical_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        LOG.warning("get_jorei query failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="jorei pref table not initialized (migration 252 pending)",
        ) from exc
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"jorei row not found: {canonical_id}",
        )
    return _row_to_model(row)
