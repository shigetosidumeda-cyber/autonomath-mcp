"""GET /v1/facts/{fact_id}/agreement — Wave 43.2.9 Dim I cross-source agreement score.

Returns the precomputed per-fact agreement signal materialized by
``scripts/cron/cross_source_agreement_check.py`` into table
``am_fact_source_agreement`` (migration 265, target_db: autonomath).

The endpoint joins the row against view ``v_fact_source_agreement`` so
the read carries the derived ``confidence_band`` ('high' | 'medium' |
'low' | 'unknown') without re-deriving it client-side.

Hard constraints
----------------
* NO LLM call. Pure SQLite SELECT + Python dict shaping.
* Cross-DB safe: this surface only touches autonomath.db; jpintel.db
  remains untouched so callers can hit the endpoint without warming the
  primary registry cache.
* Sensitive surface — disclaim that agreement does NOT imply correctness
  ("3-source agree" can still be 3 sources echoing one upstream draft).
  Always cross-check the canonical first-party source URL.
* ``_billing_unit: 1`` (¥3/req × 1 unit = 税込 ¥3.30) — single keyed
  lookup, no FTS, no JOIN across DBs.

Endpoint shape
--------------
    GET /v1/facts/{fact_id}/agreement

    200 OK ->
        {
          "fact_id": 123,
          "entity_id": "NTA-...",
          "field_name": "tax_rate_pct",
          "agreement_ratio": 0.66,
          "sources_total": 3,
          "sources_agree": 2,
          "canonical_value": "10",
          "confidence_band": "medium",
          "source_breakdown": {"egov": 1, "nta": 1, "meti": 1},
          "per_source_values": {
              "egov": "10", "nta": "10", "meti": "10.5", "other": null
          },
          "computed_at": "2026-05-12T...",
          "_billing_unit": 1,
          "_disclaimer": "..."
        }

    404 -> fact_id not yet scored (cron has not landed it).
    422 -> fact_id format invalid.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse

from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.api.cross_source_score_v2")

router = APIRouter(prefix="/v1/facts", tags=["cross-source-agreement"])


_FACT_ID_RE = re.compile(r"^[0-9]{1,18}$")


_DISCLAIMER = (
    "本 agreement_ratio は autonomath.am_fact_source_agreement (migration "
    "265) が一次資料 (e-Gov / 国税庁 / 経済産業省 等) 由来の confirming_"
    "source_count + 値一致率を機械的に集計したシグナルで、複数 source が"
    "一致しても「上流ドラフトの孫引きが揃った」事例を含むため、確定判断は"
    "必ず canonical_value と各 source の一次資料 URL で原典確認を行って"
    "ください。本 API は弁護士法 §72 / 行政書士法 §1の2 / 税理士法 §52 の"
    "いずれの士業役務にも該当しません。"
)


def _open_autonomath_ro() -> sqlite3.Connection:
    """Open autonomath.db. Reads via view ``v_fact_source_agreement``."""
    path = os.environ.get("AUTONOMATH_DB_PATH", str(settings.autonomath_db_path))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_agreement_row(
    conn: sqlite3.Connection, fact_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT fact_id, entity_id, field_name,
                  agreement_ratio, sources_total, sources_agree,
                  canonical_value, source_breakdown,
                  egov_value, nta_value, meti_value, other_value,
                  computed_at, confidence_band
             FROM v_fact_source_agreement
            WHERE fact_id = ?""",
        (int(fact_id),),
    ).fetchone()


def _shape_response(row: sqlite3.Row) -> dict[str, Any]:
    try:
        breakdown = json.loads(row["source_breakdown"] or "{}")
        if not isinstance(breakdown, dict):
            breakdown = {}
    except (json.JSONDecodeError, TypeError):
        breakdown = {}

    per_source: dict[str, Any] = {
        "egov": row["egov_value"],
        "nta": row["nta_value"],
        "meti": row["meti_value"],
        "other": row["other_value"],
    }

    body: dict[str, Any] = {
        "fact_id": int(row["fact_id"]),
        "entity_id": row["entity_id"],
        "field_name": row["field_name"],
        "agreement_ratio": float(row["agreement_ratio"] or 0.0),
        "sources_total": int(row["sources_total"] or 0),
        "sources_agree": int(row["sources_agree"] or 0),
        "canonical_value": row["canonical_value"],
        "confidence_band": row["confidence_band"],
        "source_breakdown": {
            k: int(v) for k, v in breakdown.items()
            if isinstance(v, (int, float))
        },
        "per_source_values": per_source,
        "computed_at": row["computed_at"],
        "_billing_unit": 1,
        "_disclaimer": _DISCLAIMER,
    }
    return body


@router.get("/{fact_id}/agreement")
async def get_fact_agreement(
    fact_id: Annotated[
        str,
        PathParam(description="fact_id (numeric, am_entity_facts.id)"),
    ],
) -> JSONResponse:
    """Per-fact cross-source agreement score. ¥3/req metered, NO LLM."""
    if not _FACT_ID_RE.match(fact_id):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_fact_id",
                "message": "fact_id must be a non-negative integer (<=18 digits)",
                "field": "fact_id",
            },
        )

    try:
        fid = int(fact_id)
    except ValueError as exc:  # defense in depth
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    conn = _open_autonomath_ro()
    try:
        row = _fetch_agreement_row(conn, fid)
    except sqlite3.Error as exc:
        logger.warning("agreement read failed fact_id=%s err=%s", fid, exc)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "agreement_store_unavailable",
                "message": "autonomath agreement store is not available",
            },
        ) from exc
    finally:
        conn.close()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "fact_not_scored",
                "message": (
                    "fact_id has not been scored by the cross-source cron yet."
                    " Either the fact does not exist or the next hourly pass"
                    " has not landed it. See scripts/cron/cross_source_"
                    "agreement_check.py."
                ),
                "fact_id": fid,
            },
        )

    return JSONResponse(content=_shape_response(row))


__all__ = ["router"]
