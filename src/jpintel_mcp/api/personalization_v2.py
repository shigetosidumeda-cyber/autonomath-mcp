"""Personalization recommendations (Wave 43.2.8 Dim H).

Top-N program recommendations per (consultant api_key_hash × client_id),
backed by `am_personalization_score` (mig 264, autonomath.db).

Endpoint:
    GET /v1/me/recommendations?client_id=NN&limit=10

Pricing: ¥3/req metered. NO LLM call — pure SQLite join. Scores refreshed
nightly by `scripts/cron/refresh_personalization_daily.py`.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import cast

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from jpintel_mcp.api.deps import (  # noqa: TC001 — runtime for FastAPI Depends
    ApiContextDep,
    DbDep,
)

logger = logging.getLogger("jpintel.personalization_v2")

router = APIRouter(prefix="/v1/me", tags=["personalization"])

DEFAULT_LIMIT = 10
MAX_LIMIT = 25


class ReasoningBlock(BaseModel):
    client_fit_reason: str = Field(
        description="Why the client_profiles axis contributed N points",
    )
    industry_pack: str | None = Field(default=None)
    saved_searches_matched: list[str] = Field(default_factory=list)


class RecommendationItem(BaseModel):
    program_id: str
    name: str
    tier: str | None = None
    prefecture: str | None = None
    program_kind: str | None = None
    source_url: str | None = None
    score: int = Field(ge=0, le=100)
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    reasoning: ReasoningBlock
    refreshed_at: str


class RecommendationsResponse(BaseModel):
    client_id: int
    client_label: str | None = None
    items: list[RecommendationItem]
    total: int
    refreshed_at: str | None = None
    disclaimer: str = Field(
        default=(
            "Personalization scores are precomputed heuristics — final eligibility "
            "must be confirmed against the program's primary source_url. NOT tax or "
            "legal advice (§52 / §72)."
        )
    )


def _resolve_am_conn() -> sqlite3.Connection:
    from jpintel_mcp.config import settings

    am_path = settings.autonomath_db_path
    conn = sqlite3.connect(str(am_path))
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_client_profile(
    jp_conn: sqlite3.Connection, key_hash: str, client_id: int
) -> sqlite3.Row | None:
    return cast(
        "sqlite3.Row | None",
        jp_conn.execute(
            """SELECT profile_id, name_label, jsic_major, prefecture,
                  employee_count, capital_yen
             FROM client_profiles
            WHERE profile_id = ? AND api_key_hash = ?""",
            (client_id, key_hash),
        ).fetchone(),
    )


def _fetch_program_rows(
    jp_conn: sqlite3.Connection, program_ids: list[str]
) -> dict[str, sqlite3.Row]:
    if not program_ids:
        return {}
    placeholders = ",".join(["?"] * len(program_ids))
    rows = jp_conn.execute(
        f"""SELECT unified_id, primary_name, tier, prefecture, program_kind,
                   source_url, official_url
              FROM programs
             WHERE unified_id IN ({placeholders})
               AND excluded = 0
               AND tier IN ('S','A','B','C')""",
        program_ids,
    ).fetchall()
    return {r["unified_id"]: r for r in rows}


@router.get("/recommendations", response_model=RecommendationsResponse)
async def get_recommendations(
    api_ctx: ApiContextDep,
    jp_conn: DbDep,
    client_id: int = Query(..., description="client_profiles.profile_id"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> RecommendationsResponse:
    """Top-N personalised recommendations for one 顧問先. ¥3/req metered."""
    key_hash = getattr(api_ctx, "api_key_hash", None) or getattr(api_ctx, "key_hash", None)
    if not key_hash:
        raise HTTPException(status_code=401, detail="api_key required")

    profile = _fetch_client_profile(jp_conn, str(key_hash), int(client_id))
    if profile is None:
        raise HTTPException(status_code=404, detail="client_id not found for this api_key")

    am_conn = _resolve_am_conn()
    try:
        score_rows = am_conn.execute(
            """SELECT program_id, score, score_breakdown_json, reasoning_json,
                      industry_pack, refreshed_at
                 FROM am_personalization_score
                WHERE api_key_hash = ? AND client_id = ? AND score > 0
             ORDER BY score DESC, refreshed_at DESC
                LIMIT ?""",
            (str(key_hash), int(client_id), int(limit)),
        ).fetchall()
    finally:
        am_conn.close()

    if not score_rows:
        return RecommendationsResponse(
            client_id=int(client_id),
            client_label=profile["name_label"] if profile else None,
            items=[],
            total=0,
            refreshed_at=None,
        )

    program_ids = [r["program_id"] for r in score_rows]
    program_map = _fetch_program_rows(jp_conn, program_ids)

    items: list[RecommendationItem] = []
    latest_refresh: str | None = None
    for r in score_rows:
        pid = r["program_id"]
        prog = program_map.get(pid)
        if prog is None:
            continue
        try:
            breakdown = json.loads(r["score_breakdown_json"] or "{}")
        except json.JSONDecodeError:
            breakdown = {}
        try:
            reasoning_raw = json.loads(r["reasoning_json"] or "{}")
        except json.JSONDecodeError:
            reasoning_raw = {}
        reasoning = ReasoningBlock(
            client_fit_reason=str(reasoning_raw.get("client_fit_reason", "")),
            industry_pack=r["industry_pack"],
            saved_searches_matched=list(reasoning_raw.get("saved_searches_matched", []) or []),
        )
        items.append(
            RecommendationItem(
                program_id=pid,
                name=prog["primary_name"],
                tier=prog["tier"],
                prefecture=prog["prefecture"],
                program_kind=prog["program_kind"],
                source_url=prog["source_url"] or prog["official_url"],
                score=int(r["score"] or 0),
                score_breakdown={
                    k: int(v) for k, v in breakdown.items() if isinstance(v, (int, float))
                },
                reasoning=reasoning,
                refreshed_at=r["refreshed_at"],
            )
        )
        if latest_refresh is None or (r["refreshed_at"] and r["refreshed_at"] > latest_refresh):
            latest_refresh = r["refreshed_at"]

    return RecommendationsResponse(
        client_id=int(client_id),
        client_label=profile["name_label"] if profile else None,
        items=items,
        total=len(items),
        refreshed_at=latest_refresh,
    )
