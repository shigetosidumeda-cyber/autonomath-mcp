"""REST handlers for Wave 33 Axis 2a/2b/2c precompute surfaces.

* POST /v1/cohort/5d/match — 5-axis cohort lookup (Axis 2a).
* GET  /v1/programs/{program_id}/risk — 4-axis program-risk score (Axis 2b).
* GET  /v1/supplier/chain/{houjin_bangou} — bipartite chain (Axis 2c).

Pure SELECT over am_cohort_5d / am_program_risk_4d / am_supplier_chain.
NO LLM. NO destructive write. NO full-scan op against the 9.7GB DB.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import suppress
from pathlib import Path as _Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

router = APIRouter(prefix="/v1", tags=["cohort", "risk", "supplier-chain"])


_DISCLAIMER = (
    "本レスポンスは jpcite が公開情報を機械的に整理した結果を返却するものであり、"
    "税理士法 §52 / 公認会計士法 §47条の2 / 行政書士法 §1 / 弁護士法 §72 に基づく"
    "個別具体的な税務助言・監査意見・申請書面作成・法律相談の代替ではありません。"
    "最終的な判断は資格を有する士業へご相談ください。"
)


def _autonomath_db_path() -> str:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return raw
    return str(_Path(__file__).resolve().parents[3] / "autonomath.db")


def _open_am_ro() -> sqlite3.Connection | None:
    path = _autonomath_db_path()
    try:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError:
        return None


class CohortMatch5DBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    jsic_major: str = Field(..., min_length=1, max_length=1, description="JSIC 大分類 1 char (A-T)")
    employee_band: str = Field(..., description="'1-9' / '10-99' / '100-999' / '1000+'")
    prefecture_code: str | None = Field(default=None, max_length=2, description="2-digit JIS pref code or null")


@router.post(
    "/cohort/5d/match",
    summary="5-axis cohort matcher (法人 × 業種 × 規模 × 地域 × 制度)",
    description="Returns top-20 eligible programs from am_cohort_5d precompute.",
    responses={**COMMON_ERROR_RESPONSES, 200: {"description": "Cohort envelope."}},
)
def cohort_5d_match(
    conn: DbDep,
    ctx: ApiContextDep,
    body: Annotated[CohortMatch5DBody, Body(description="5-axis filter")],
) -> JSONResponse:
    t0 = time.perf_counter()
    am = _open_am_ro()
    eligible: list[str] = []
    cohort_meta: dict[str, Any] = {}
    if am is not None:
        try:
            row = am.execute(
                "SELECT eligible_program_ids, eligible_count, last_refreshed_at "
                "FROM am_cohort_5d "
                "WHERE houjin_bangou IS NULL "
                "  AND jsic_major = ? AND employee_band = ? "
                "  AND COALESCE(prefecture_code, '_nationwide') = COALESCE(?, '_nationwide') "
                "LIMIT 1",
                (body.jsic_major, body.employee_band, body.prefecture_code),
            ).fetchone()
            if row:
                with suppress(json.JSONDecodeError, TypeError):
                    eligible = json.loads(row["eligible_program_ids"]) or []
                cohort_meta = {
                    "eligible_count": row["eligible_count"],
                    "last_refreshed_at": row["last_refreshed_at"],
                }
        except sqlite3.OperationalError:
            pass
        finally:
            with suppress(Exception):
                am.close()

    result = {
        "axes": {
            "jsic_major": body.jsic_major,
            "employee_band": body.employee_band,
            "prefecture_code": body.prefecture_code,
        },
        "eligible_program_ids": eligible[:20],
        "total": len(eligible),
        "limit": 20, "offset": 0,
        "results": [{"unified_id": p} for p in eligible[:20]],
        "cohort_meta": cohort_meta,
        "_disclaimer": _DISCLAIMER,
        "precompute_source": "am_cohort_5d (mig 231)",
    }
    log_usage(
        conn, ctx, "cohort_5d_match",
        latency_ms=int((time.perf_counter() - t0) * 1000),
        result_count=len(eligible[:20]),
        params={"jsic_major": body.jsic_major, "employee_band": body.employee_band,
                "prefecture_code": body.prefecture_code},
        strict_metering=True,
    )
    return JSONResponse(content=result, status_code=200)


@router.get(
    "/programs/{program_id}/risk",
    summary="4-axis program-risk score (制度 × 業法 × 行政処分 × 取消理由)",
    description="Returns top-scored row from am_program_risk_4d for program_id.",
    responses={**COMMON_ERROR_RESPONSES, 200: {"description": "Risk envelope."}},
)
def program_risk_4d(
    conn: DbDep,
    ctx: ApiContextDep,
    program_id: Annotated[str, Path(description="Program unified_id")],
) -> JSONResponse:
    t0 = time.perf_counter()
    am = _open_am_ro()
    top: dict[str, Any] = {}
    all_rows: list[dict[str, Any]] = []
    if am is not None:
        try:
            rows = am.execute(
                "SELECT gyouhou_id, enforcement_pattern_id, revocation_reason_id, "
                "       risk_score_0_100, evidence_json, last_refreshed_at "
                "FROM am_program_risk_4d WHERE program_id = ? "
                "ORDER BY risk_score_0_100 DESC LIMIT 10",
                (program_id,),
            ).fetchall()
            for r in rows:
                evidence: dict[str, Any] = {}
                with suppress(json.JSONDecodeError, TypeError):
                    evidence = json.loads(r["evidence_json"]) or {}
                all_rows.append({
                    "gyouhou_id": r["gyouhou_id"],
                    "enforcement_pattern_id": r["enforcement_pattern_id"],
                    "revocation_reason_id": r["revocation_reason_id"],
                    "risk_score_0_100": r["risk_score_0_100"],
                    "evidence": evidence,
                    "last_refreshed_at": r["last_refreshed_at"],
                })
            if all_rows:
                top = all_rows[0]
        except sqlite3.OperationalError:
            pass
        finally:
            with suppress(Exception):
                am.close()

    result = {
        "program_id": program_id, "top_risk": top, "all_axes": all_rows,
        "axis_count": len(all_rows),
        "weights": {"gyouhou": 0.5, "enforcement": 0.3, "tsutatsu": 0.2},
        "_disclaimer": _DISCLAIMER,
        "precompute_source": "am_program_risk_4d (mig 232)",
    }
    log_usage(
        conn, ctx, "program_risk_4d",
        latency_ms=int((time.perf_counter() - t0) * 1000),
        result_count=len(all_rows),
        params={"program_id": program_id},
        strict_metering=True,
    )
    return JSONResponse(content=result, status_code=200)


@router.get(
    "/supplier/chain/{houjin_bangou}",
    summary="Supplier-chain bipartite traversal (取引先 chain)",
    description="Returns am_supplier_chain rooted at houjin_bangou, up to max_hops.",
    responses={**COMMON_ERROR_RESPONSES, 200: {"description": "Chain tree."}},
)
def supplier_chain(
    conn: DbDep,
    ctx: ApiContextDep,
    houjin_bangou: Annotated[str, Path(min_length=13, max_length=13, description="13-digit anchor")],
    max_hops: int = 3,
) -> JSONResponse:
    t0 = time.perf_counter()
    max_hops = max(1, min(int(max_hops), 5))
    am = _open_am_ro()
    edges: list[dict[str, Any]] = []
    by_type: dict[str, int] = {}
    if am is not None:
        try:
            rows = am.execute(
                "SELECT partner_houjin_bangou, link_type, evidence_url, "
                "       evidence_date, hop_depth "
                "FROM am_supplier_chain "
                "WHERE anchor_houjin_bangou = ? AND hop_depth <= ? "
                "ORDER BY hop_depth ASC, partner_houjin_bangou ASC LIMIT 500",
                (houjin_bangou, max_hops),
            ).fetchall()
            for r in rows:
                lt = r["link_type"]
                by_type[lt] = by_type.get(lt, 0) + 1
                edges.append({
                    "partner": r["partner_houjin_bangou"],
                    "link_type": lt,
                    "evidence_url": r["evidence_url"],
                    "evidence_date": r["evidence_date"],
                    "hop_depth": r["hop_depth"],
                })
        except sqlite3.OperationalError:
            pass
        finally:
            with suppress(Exception):
                am.close()

    result = {
        "anchor_houjin_bangou": houjin_bangou, "max_hops": max_hops,
        "edges": edges, "edge_count": len(edges), "by_link_type": by_type,
        "_disclaimer": _DISCLAIMER,
        "precompute_source": "am_supplier_chain (mig 233)",
    }
    log_usage(
        conn, ctx, "supplier_chain",
        latency_ms=int((time.perf_counter() - t0) * 1000),
        result_count=len(edges),
        params={"houjin_bangou": houjin_bangou, "max_hops": max_hops},
        quantity=2, strict_metering=True,
    )
    return JSONResponse(content=result, status_code=200)


__all__ = ["router", "CohortMatch5DBody"]
