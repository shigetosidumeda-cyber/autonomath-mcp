"""REST handlers for 行政処分 市町村 / 都道府県 layer (Wave 43.1.9, mig 255).

Backed by `am_enforcement_municipality` on autonomath.db. 1,815+ rows
target. Read-only. ¥3/req metered, NO LLM.
"""
from __future__ import annotations
import os, sqlite3
from pathlib import Path
from typing import Annotated, Any
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from jpintel_mcp.api.deps import ApiContextDep, log_usage
from jpintel_mcp.config import settings

router = APIRouter(prefix="/v1/enforcement/municipality", tags=["enforcement-municipality"])


def _autonomath_db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return settings.autonomath_db_path


def _open_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_autonomath_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


class EnforcementMunicipality(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enforcement_id: int
    unified_id: str
    municipality_code: str | None = None
    prefecture_code: str
    prefecture_name: str
    municipality_name: str | None = None
    agency_type: str
    agency_name: str | None = None
    action_type: str
    action_date: str
    action_period_start: str | None = None
    action_period_end: str | None = None
    respondent_name_anonymized: str
    respondent_houjin_bangou: str | None = None
    industry_jsic: str | None = None
    body_text_excerpt: str | None = None
    action_summary: str | None = None
    source_url: str
    source_host: str
    license: str
    ingested_at: str


class EnforcementMunicipalitySearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total: int
    limit: int
    offset: int
    source_table: str = "am_enforcement_municipality"
    no_live_fetch: bool = True
    results: list[EnforcementMunicipality] = Field(default_factory=list)


def _row_to_model(row: sqlite3.Row) -> EnforcementMunicipality:
    return EnforcementMunicipality(
        enforcement_id=row["enforcement_id"], unified_id=row["unified_id"],
        municipality_code=row["municipality_code"],
        prefecture_code=row["prefecture_code"], prefecture_name=row["prefecture_name"],
        municipality_name=row["municipality_name"], agency_type=row["agency_type"],
        agency_name=row["agency_name"], action_type=row["action_type"],
        action_date=row["action_date"], action_period_start=row["action_period_start"],
        action_period_end=row["action_period_end"],
        respondent_name_anonymized=row["respondent_name_anonymized"],
        respondent_houjin_bangou=row["respondent_houjin_bangou"],
        industry_jsic=row["industry_jsic"], body_text_excerpt=row["body_text_excerpt"],
        action_summary=row["action_summary"], source_url=row["source_url"],
        source_host=row["source_host"], license=row["license"],
        ingested_at=row["ingested_at"],
    )


@router.get("/search", response_model=EnforcementMunicipalitySearchResponse,
            summary="Search 行政処分 市町村 + 都道府県 (1,815+ rows, Wave 43.1.9)")
def search_enforcement_municipality(
    ctx: ApiContextDep,
    prefecture_code: Annotated[str | None, Query(pattern=r"^\d{2}$")] = None,
    municipality_code: Annotated[str | None, Query(pattern=r"^\d{5}$")] = None,
    agency_type: Annotated[str | None, Query(max_length=20)] = None,
    action_type: Annotated[str | None, Query(max_length=40)] = None,
    industry_jsic: Annotated[str | None, Query(pattern=r"^[A-T]$")] = None,
    action_from: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
    action_to: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EnforcementMunicipalitySearchResponse:
    where: list[str] = []
    params: list[Any] = []
    if prefecture_code:
        where.append("prefecture_code = ?"); params.append(prefecture_code)
    if municipality_code:
        where.append("municipality_code = ?"); params.append(municipality_code)
    if agency_type:
        where.append("agency_type = ?"); params.append(agency_type)
    if action_type:
        where.append("action_type = ?"); params.append(action_type)
    if industry_jsic:
        where.append("industry_jsic = ?"); params.append(industry_jsic)
    if action_from:
        where.append("action_date >= ?"); params.append(action_from)
    if action_to:
        where.append("action_date <= ?"); params.append(action_to)
    if q:
        like = f"%{q}%"
        where.append("(COALESCE(action_summary,'') LIKE ? OR COALESCE(body_text_excerpt,'') LIKE ? OR COALESCE(agency_name,'') LIKE ?)")
        params.extend([like, like, like])
    where_sql = " AND ".join(where) if where else "1=1"
    conn = _open_conn()
    try:
        try:
            (total,) = conn.execute(f"SELECT COUNT(*) FROM v_enforcement_municipality_public WHERE {where_sql}", params).fetchone()
        except sqlite3.OperationalError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"am_enforcement_municipality not available: {exc}")
        rows = conn.execute(
            f"SELECT * FROM v_enforcement_municipality_public WHERE {where_sql} ORDER BY action_date DESC, enforcement_id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        log_usage(None, ctx, "enforcement_municipality.search",
                  params={"prefecture_code": prefecture_code, "municipality_code": municipality_code,
                          "agency_type": agency_type, "action_type": action_type,
                          "industry_jsic": industry_jsic, "action_from": action_from,
                          "action_to": action_to, "q": q}, strict_metering=True)
        return EnforcementMunicipalitySearchResponse(
            total=total, limit=limit, offset=offset,
            results=[_row_to_model(r) for r in rows])
    finally:
        conn.close()


@router.get("/{unified_id}", response_model=EnforcementMunicipality)
def get_enforcement_municipality(unified_id: str, ctx: ApiContextDep) -> EnforcementMunicipality:
    conn = _open_conn()
    try:
        try:
            row = conn.execute("SELECT * FROM v_enforcement_municipality_public WHERE unified_id = ?",
                               (unified_id,)).fetchone()
        except sqlite3.OperationalError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"am_enforcement_municipality not available: {exc}")
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"enforcement municipality not found: {unified_id}")
        log_usage(None, ctx, "enforcement_municipality.get",
                  params={"unified_id": unified_id}, strict_metering=True)
        return _row_to_model(row)
    finally:
        conn.close()
