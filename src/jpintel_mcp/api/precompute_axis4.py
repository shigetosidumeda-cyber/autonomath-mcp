"""REST surface for Wave 34 Axis 4 precomputed tables.

5 read-only endpoints (mounted at /v1):

  GET  /v1/portfolio/optimize?houjin_bangou={n}        -> top 8 program
  GET  /v1/houjin/{houjin_bangou}/risk                  -> 0-100 risk
  GET  /v1/programs/{program_unified_id}/forecast_30yr  -> 30-yr forecast
  GET  /v1/alliance/opportunities?houjin_bangou={n}     -> top 10 partner
  POST /v1/graph/vec_search                             -> top-k semantic

NO LLM, pure precomputed-table SELECT. AnonIpLimitDep applied at include.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import struct
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["axis4_precompute"])

_TAX_DISCLAIMER = (
    "本 response は public corpus + 法人 master + 採択 history + 行政処分 "
    "+ am_compat_matrix からの統計 signal です。"
    "税理士法 §52 / 行政書士法 §1の2 / 弁護士法 §72 上の助言ではありません。"
    "最終判断は専門家に相談してください。"
)


def _autonomath_conn() -> sqlite3.Connection:
    return connect_autonomath()


AutonomathDbDep = Annotated[sqlite3.Connection, Depends(_autonomath_conn)]


class PortfolioOptimizeItem(BaseModel):
    rank: int = Field(..., ge=1, le=8)
    program_unified_id: str
    program_primary_name: str | None = None
    score_0_100: int = Field(..., ge=0, le=100)
    tier: str | None = None
    program_amount_max_yen: int | None = None
    signals: dict[str, float] = Field(default_factory=dict)


class PortfolioOptimizeResponse(BaseModel):
    houjin_bangou: str
    refreshed_at: str | None = None
    items: list[PortfolioOptimizeItem]
    disclaimer: str = Field(default=_TAX_DISCLAIMER, alias="_disclaimer")


class HoujinRiskResponse(BaseModel):
    houjin_bangou: str
    risk_score_0_100: int = Field(..., ge=0, le=100)
    risk_bucket: str
    enforcement_subscore: int
    invoice_subscore: int
    adoption_subscore: int
    credit_age_subscore: int
    signals: dict[str, Any] = Field(default_factory=dict)
    refreshed_at: str | None = None
    disclaimer: str = Field(default=_TAX_DISCLAIMER, alias="_disclaimer")


class Forecast30yrItem(BaseModel):
    forecast_year_offset: int = Field(..., ge=0, le=29)
    horizon_month: int = Field(..., ge=0, le=11)
    state: str
    p_active: float
    p_paused: float
    p_sunset: float
    p_renewed: float
    expected_call_count: float


class Forecast30yrResponse(BaseModel):
    program_unified_id: str
    refreshed_at: str | None = None
    horizon: list[Forecast30yrItem]
    disclaimer: str = Field(default=_TAX_DISCLAIMER, alias="_disclaimer")


class AllianceOpportunityItem(BaseModel):
    rank: int = Field(..., ge=1, le=10)
    partner_houjin_bangou: str
    partner_primary_name: str | None = None
    alliance_score_0_100: int = Field(..., ge=0, le=100)
    co_adoption_count: int
    industry_chain_pair: str | None = None
    region_a: str | None = None
    region_b: str | None = None
    signals: dict[str, int] = Field(default_factory=dict)


class AllianceOpportunityResponse(BaseModel):
    houjin_bangou: str
    refreshed_at: str | None = None
    items: list[AllianceOpportunityItem]
    disclaimer: str = Field(default=_TAX_DISCLAIMER, alias="_disclaimer")


class VecSearchRequest(BaseModel):
    query_text: str = Field(..., min_length=1, max_length=1024)
    record_kinds: list[str] | None = None
    top_k: int = Field(default=10, ge=1, le=50)


class VecSearchHit(BaseModel):
    canonical_id: str
    record_kind: str
    primary_name: str | None = None
    distance: float


class VecSearchResponse(BaseModel):
    query_text: str
    embed_model: str
    embed_dim: int
    hits: list[VecSearchHit]
    disclaimer: str = Field(default=_TAX_DISCLAIMER, alias="_disclaimer")


def _select_rows(conn, sql, params):
    try:
        return list(conn.execute(sql, params).fetchall())
    except sqlite3.OperationalError as exc:
        LOG.warning("precompute_axis4 SELECT failed: %s", exc)
        return []


@router.get(
    "/portfolio/optimize",
    response_model=PortfolioOptimizeResponse,
    response_model_by_alias=True,
)
def get_portfolio_optimize(
    am_db: AutonomathDbDep,
    houjin_bangou: str = Query(..., min_length=4, max_length=20),
) -> PortfolioOptimizeResponse:
    rows = _select_rows(
        am_db,
        "SELECT rank, program_unified_id, program_primary_name, score_0_100, "
        " tier, program_amount_max_yen, reason_json, refreshed_at "
        "FROM am_portfolio_optimize WHERE houjin_bangou = ? ORDER BY rank",
        (houjin_bangou,),
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "portfolio_not_precomputed",
                    "message": f"houjin_bangou={houjin_bangou} not in am_portfolio_optimize."},
        )
    items = []
    refreshed_at = None
    for r in rows:
        refreshed_at = refreshed_at or r["refreshed_at"]
        signals = {}
        if r["reason_json"]:
            try:
                signals = json.loads(r["reason_json"]).get("signals", {})
            except (json.JSONDecodeError, TypeError):
                signals = {}
        items.append(PortfolioOptimizeItem(
            rank=r["rank"], program_unified_id=r["program_unified_id"],
            program_primary_name=r["program_primary_name"], score_0_100=r["score_0_100"],
            tier=r["tier"], program_amount_max_yen=r["program_amount_max_yen"],
            signals=signals,
        ))
    return PortfolioOptimizeResponse(houjin_bangou=houjin_bangou,
                                     refreshed_at=refreshed_at, items=items)


@router.get(
    "/houjin/{houjin_bangou}/risk",
    response_model=HoujinRiskResponse,
    response_model_by_alias=True,
)
def get_houjin_risk(houjin_bangou: str, am_db: AutonomathDbDep) -> HoujinRiskResponse:
    rows = _select_rows(
        am_db,
        "SELECT risk_score_0_100, risk_bucket, enforcement_subscore, invoice_subscore, "
        " adoption_subscore, credit_age_subscore, signals_json, refreshed_at "
        "FROM am_houjin_risk_score WHERE houjin_bangou = ?",
        (houjin_bangou,),
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "risk_not_precomputed",
                    "message": f"houjin_bangou={houjin_bangou} not in am_houjin_risk_score."},
        )
    r = rows[0]
    signals = {}
    if r["signals_json"]:
        try:
            signals = json.loads(r["signals_json"])
        except (json.JSONDecodeError, TypeError):
            signals = {}
    return HoujinRiskResponse(
        houjin_bangou=houjin_bangou, risk_score_0_100=r["risk_score_0_100"],
        risk_bucket=r["risk_bucket"], enforcement_subscore=r["enforcement_subscore"],
        invoice_subscore=r["invoice_subscore"], adoption_subscore=r["adoption_subscore"],
        credit_age_subscore=r["credit_age_subscore"], signals=signals,
        refreshed_at=r["refreshed_at"],
    )


@router.get(
    "/programs/{program_unified_id}/forecast_30yr",
    response_model=Forecast30yrResponse,
    response_model_by_alias=True,
)
def get_program_forecast_30yr(
    program_unified_id: str,
    am_db: AutonomathDbDep,
    year_offset_max: int = Query(default=30, ge=1, le=30),
) -> Forecast30yrResponse:
    rows = _select_rows(
        am_db,
        "SELECT forecast_year_offset, horizon_month, state, p_active, p_paused, "
        " p_sunset, p_renewed, expected_call_count, refreshed_at "
        "FROM am_subsidy_30yr_forecast "
        "WHERE program_unified_id = ? AND forecast_year_offset < ? "
        "ORDER BY forecast_year_offset, horizon_month",
        (program_unified_id, year_offset_max),
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "forecast_not_precomputed",
                    "message": f"program_unified_id={program_unified_id} not precomputed."},
        )
    items = [
        Forecast30yrItem(
            forecast_year_offset=r["forecast_year_offset"], horizon_month=r["horizon_month"],
            state=r["state"], p_active=r["p_active"], p_paused=r["p_paused"],
            p_sunset=r["p_sunset"], p_renewed=r["p_renewed"],
            expected_call_count=r["expected_call_count"],
        )
        for r in rows
    ]
    return Forecast30yrResponse(program_unified_id=program_unified_id,
                                refreshed_at=rows[0]["refreshed_at"], horizon=items)


@router.get(
    "/alliance/opportunities",
    response_model=AllianceOpportunityResponse,
    response_model_by_alias=True,
)
def get_alliance_opportunities(
    am_db: AutonomathDbDep,
    houjin_bangou: str = Query(..., min_length=4, max_length=20),
) -> AllianceOpportunityResponse:
    rows = _select_rows(
        am_db,
        "SELECT rank, partner_houjin_bangou, partner_primary_name, alliance_score_0_100, "
        " co_adoption_count, industry_chain_pair, region_a, region_b, reason_json, refreshed_at "
        "FROM am_alliance_opportunity WHERE houjin_bangou = ? ORDER BY rank",
        (houjin_bangou,),
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "alliance_not_precomputed",
                    "message": f"houjin_bangou={houjin_bangou} not in am_alliance_opportunity."},
        )
    items = []
    refreshed_at = None
    for r in rows:
        refreshed_at = refreshed_at or r["refreshed_at"]
        signals = {}
        if r["reason_json"]:
            try:
                signals = json.loads(r["reason_json"]).get("signals", {})
            except (json.JSONDecodeError, TypeError):
                signals = {}
        items.append(AllianceOpportunityItem(
            rank=r["rank"], partner_houjin_bangou=r["partner_houjin_bangou"],
            partner_primary_name=r["partner_primary_name"],
            alliance_score_0_100=r["alliance_score_0_100"],
            co_adoption_count=r["co_adoption_count"],
            industry_chain_pair=r["industry_chain_pair"],
            region_a=r["region_a"], region_b=r["region_b"], signals=signals,
        ))
    return AllianceOpportunityResponse(houjin_bangou=houjin_bangou,
                                       refreshed_at=refreshed_at, items=items)


@router.post(
    "/graph/vec_search",
    response_model=VecSearchResponse,
    response_model_by_alias=True,
)
def post_graph_vec_search(req: VecSearchRequest, am_db: AutonomathDbDep) -> VecSearchResponse:
    try:
        ledger = am_db.execute(
            "SELECT model_name, embed_dim FROM am_entities_vec_refresh_log "
            "WHERE finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        ledger = None
    model_id = (ledger["model_name"] if ledger else None) or "hash-fallback-v1"
    dim = int(ledger["embed_dim"]) if ledger and ledger["embed_dim"] else 384

    text = (req.query_text or "").strip() or " "
    seed = text.encode("utf-8")
    h = hashlib.sha256(seed).digest()
    qvec = []
    while len(qvec) < dim:
        qvec.extend((b - 127.5) / 127.5 for b in h)
        h = hashlib.sha256(h).digest()
    qvec = qvec[:dim]
    qbytes = struct.pack(f"{len(qvec)}f", *qvec)

    kind_to_table = {
        "program": "am_entities_vec_S", "case_study": "am_entities_vec_C",
        "court_decision": "am_entities_vec_J", "adoption": "am_entities_vec_A",
        "corporate_entity": "am_entities_vec_E", "statistic": "am_entities_vec_T",
        "tax_measure": "am_entities_vec_T", "enforcement": "am_entities_vec_F",
        "invoice_registrant": "am_entities_vec_I", "law": "am_entities_vec_L",
        "certification": "am_entities_vec_R", "authority": "am_entities_vec_R",
        "document": "am_entities_vec_R",
    }
    if req.record_kinds:
        target_tables = sorted({kind_to_table[k] for k in req.record_kinds if k in kind_to_table})
    else:
        target_tables = sorted(set(kind_to_table.values()))

    hits = []
    for table in target_tables:
        try:
            cur = am_db.execute(
                f"SELECT entity_id, distance FROM {table} "
                f"WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                (qbytes, req.top_k),
            )
            for row in cur:
                meta = am_db.execute(
                    "SELECT primary_name, record_kind FROM am_entities WHERE canonical_id = ?",
                    (row[0],),
                ).fetchone()
                hits.append(VecSearchHit(
                    canonical_id=row[0],
                    record_kind=(meta["record_kind"] if meta else "unknown"),
                    primary_name=(meta["primary_name"] if meta else None),
                    distance=float(row[1]),
                ))
        except sqlite3.OperationalError:
            continue
    hits.sort(key=lambda h: h.distance)
    hits = hits[: req.top_k]
    return VecSearchResponse(query_text=req.query_text, embed_model=model_id,
                             embed_dim=dim, hits=hits)
