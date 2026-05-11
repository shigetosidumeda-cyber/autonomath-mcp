"""REST handlers for 裁判所判例 v2 拡張 (Wave 43.1.10, mig 259, 17,935+ rows target)."""
from __future__ import annotations
import json, os, sqlite3
from pathlib import Path
from typing import Annotated, Any
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from jpintel_mcp.api.deps import ApiContextDep, log_usage
from jpintel_mcp.config import settings

router = APIRouter(prefix="/v1/court-decisions/v2", tags=["court-decisions-v2"])


def _autonomath_db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return settings.autonomath_db_path


def _open_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_autonomath_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


class CourtDecisionV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: int
    unified_id: str
    case_number: str | None = None
    court: str | None = None
    court_level: str
    court_level_canonical: str
    case_type: str
    case_name: str | None = None
    decision_date: str | None = None
    decision_date_start: str | None = None
    decision_date_end: str | None = None
    fiscal_year: int | None = None
    decision_type: str | None = None
    subject_area: str | None = None
    precedent_weight: str
    related_law_ids: list[str] = Field(default_factory=list)
    related_program_ids: list[str] = Field(default_factory=list)
    key_ruling_excerpt: str | None = None
    key_ruling_full: str | None = None
    parties_involved: str | None = None
    impact_on_business: str | None = None
    full_text_url: str | None = None
    pdf_url: str | None = None
    source_url: str
    source: str
    license: str
    confidence: float
    fetched_at: str


class CourtDecisionV2SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total: int
    limit: int
    offset: int
    source_table: str = "am_court_decisions_v2"
    no_live_fetch: bool = True
    results: list[CourtDecisionV2] = Field(default_factory=list)


def _row_to_model(row: sqlite3.Row) -> CourtDecisionV2:
    try:
        laws_parsed = json.loads(row["related_law_ids_json"] or "[]")
        related_law_ids = [str(x) for x in laws_parsed] if isinstance(laws_parsed, list) else []
    except json.JSONDecodeError:
        related_law_ids = []
    try:
        progs_parsed = json.loads(row["related_program_ids_json"] or "[]")
        related_program_ids = [str(x) for x in progs_parsed] if isinstance(progs_parsed, list) else []
    except json.JSONDecodeError:
        related_program_ids = []
    return CourtDecisionV2(
        case_id=row["case_id"], unified_id=row["unified_id"],
        case_number=row["case_number"], court=row["court"],
        court_level=row["court_level"], court_level_canonical=row["court_level_canonical"],
        case_type=row["case_type"], case_name=row["case_name"],
        decision_date=row["decision_date"],
        decision_date_start=row["decision_date_start"],
        decision_date_end=row["decision_date_end"],
        fiscal_year=row["fiscal_year"], decision_type=row["decision_type"],
        subject_area=row["subject_area"], precedent_weight=row["precedent_weight"],
        related_law_ids=related_law_ids, related_program_ids=related_program_ids,
        key_ruling_excerpt=row["key_ruling_excerpt"], key_ruling_full=row["key_ruling_full"],
        parties_involved=row["parties_involved"], impact_on_business=row["impact_on_business"],
        full_text_url=row["full_text_url"], pdf_url=None,
        source_url=row["source_url"], source=row["source"], license=row["license"],
        confidence=row["confidence"], fetched_at=row["fetched_at"],
    )


@router.get("/search", response_model=CourtDecisionV2SearchResponse,
            summary="Search 裁判所判例 v2 (17,935+ rows, Wave 43.1.10)")
def search_court_decisions_v2(
    ctx: ApiContextDep,
    court_level: Annotated[str | None, Query(max_length=20)] = None,
    case_type: Annotated[str | None, Query(max_length=20)] = None,
    precedent_weight: Annotated[str | None, Query(max_length=20)] = None,
    fiscal_year: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    decided_from: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
    decided_to: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
    source: Annotated[str | None, Query(max_length=20)] = None,
    references_law_id: Annotated[str | None, Query(pattern=r"^LAW-[0-9a-f]{10}$")] = None,
    references_program_id: Annotated[str | None, Query(max_length=80)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CourtDecisionV2SearchResponse:
    where: list[str] = []
    params: list[Any] = []
    if court_level:
        where.append("court_level_canonical = ?"); params.append(court_level)
    if case_type:
        where.append("case_type = ?"); params.append(case_type)
    if precedent_weight:
        where.append("precedent_weight = ?"); params.append(precedent_weight)
    if fiscal_year:
        where.append("fiscal_year = ?"); params.append(fiscal_year)
    if decided_from:
        where.append("decision_date >= ?"); params.append(decided_from)
    if decided_to:
        where.append("decision_date <= ?"); params.append(decided_to)
    if source:
        where.append("source = ?"); params.append(source)
    if references_law_id:
        where.append("COALESCE(related_law_ids_json,'') LIKE ?")
        params.append(f'%"{references_law_id}"%')
    if references_program_id:
        where.append("COALESCE(related_program_ids_json,'') LIKE ?")
        params.append(f'%"{references_program_id}"%')
    if q:
        like = f"%{q}%"
        where.append("(COALESCE(case_name,'') LIKE ? OR COALESCE(key_ruling_excerpt,'') LIKE ? OR COALESCE(subject_area,'') LIKE ?)")
        params.extend([like, like, like])
    where_sql = " AND ".join(where) if where else "1=1"
    weight_order = "CASE precedent_weight WHEN 'binding' THEN 0 WHEN 'persuasive' THEN 1 WHEN 'informational' THEN 2 ELSE 3 END"
    level_order = "CASE court_level_canonical WHEN 'supreme' THEN 0 WHEN 'high' THEN 1 WHEN 'district' THEN 2 WHEN 'summary' THEN 3 WHEN 'family' THEN 4 ELSE 5 END"
    conn = _open_conn()
    try:
        try:
            (total,) = conn.execute(f"SELECT COUNT(*) FROM v_am_court_decisions_v2_public WHERE {where_sql}", params).fetchone()
        except sqlite3.OperationalError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"am_court_decisions_v2 not available: {exc}")
        rows = conn.execute(
            (f"SELECT * FROM v_am_court_decisions_v2_public WHERE {where_sql} "
             f"ORDER BY {weight_order}, {level_order}, COALESCE(decision_date,'') DESC, case_id DESC LIMIT ? OFFSET ?"),
            [*params, limit, offset],
        ).fetchall()
        log_usage(None, ctx, "court_decisions_v2.search",
                  params={"court_level": court_level, "case_type": case_type,
                          "precedent_weight": precedent_weight, "fiscal_year": fiscal_year,
                          "decided_from": decided_from, "decided_to": decided_to,
                          "source": source, "references_law_id": references_law_id,
                          "references_program_id": references_program_id, "q": q},
                  strict_metering=True)
        return CourtDecisionV2SearchResponse(
            total=total, limit=limit, offset=offset,
            results=[_row_to_model(r) for r in rows])
    finally:
        conn.close()


@router.get("/{unified_id}", response_model=CourtDecisionV2)
def get_court_decision_v2(unified_id: str, ctx: ApiContextDep) -> CourtDecisionV2:
    conn = _open_conn()
    try:
        try:
            row = conn.execute("SELECT * FROM v_am_court_decisions_v2_public WHERE unified_id = ?",
                               (unified_id,)).fetchone()
        except sqlite3.OperationalError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"am_court_decisions_v2 not available: {exc}")
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"court decision v2 not found: {unified_id}")
        log_usage(None, ctx, "court_decisions_v2.get",
                  params={"unified_id": unified_id}, strict_metering=True)
        return _row_to_model(row)
    finally:
        conn.close()
