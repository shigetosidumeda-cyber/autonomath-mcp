"""GET /v1/foreign_fdi/v2/* — Wave 43.2.10 Dim J FDI 80-country surface.

Returns FDI entry conditions (visa, capital threshold, restricted sectors,
gov bilateral promotion vehicles) for 80 hand-curated countries (G7 + G20 +
ASEAN + EU + EFTA + priority Africa / GCC / LATAM) materialized by
migration 266 into ``am_fdi_country`` (target_db: autonomath).

This surface is intentionally separate from ``api/foreign_treaties.py``
(33-country DTA cohort, migration 091): DTAs cover double-tax mechanics,
``am_fdi_country`` covers ENTRY conditions. The two are joined by ISO
3166-1 alpha-2 ``country_iso`` for callers that need both.

Hard constraints
----------------
* NO LLM call. NO auto-translate. ``country_name_ja`` / ``country_name_en``
  are hand-curated from MOFA / JETRO public materials.
* Reads ``v_fdi_country_public`` (redistribute_ok = 1 only).
* ¥3/req metered (税込 ¥3.30) per call. Two routes:
    - GET /v1/foreign_fdi/v2/countries[?region=...&is_g7=1&is_oecd=1...]
        list with optional filters (max 200 rows).
    - GET /v1/foreign_fdi/v2/country/{country_iso}
        single-country detail (404 on missing).

License posture
---------------
政府標準利用規約 v2.0 (gov_standard) — each row carries the explicit
``license`` field so downstream chunkers can re-emit ``redistribute_ok``
flag verbatim.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse

from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.api.foreign_fdi_v2")

router = APIRouter(prefix="/v1/foreign_fdi/v2", tags=["foreign-fdi"])


_ISO_RE = re.compile(r"^[A-Z]{2}$")
_ALLOWED_REGIONS: frozenset[str] = frozenset(
    {
        "asia_pacific",
        "eu",
        "north_america",
        "latam",
        "mideast_africa",
        "oceania",
        "other",
    }
)

_MAX_LIMIT = 200
_DEFAULT_LIMIT = 80


_DISCLAIMER = (
    "本 FDI 国別データは外務省 国・地域別公開情報 + JETRO 公式 source を"
    "政府標準利用規約 v2.0 のもとで autonomath.am_fdi_country (migration 266) "
    "に集約したもので、visa / 最低資本要件 / 業種制限 / 二国間促進プログラム は"
    "公表時点情報です。最新かつ確定的な要件は各 source_url の原典 (mofa_source_url / "
    "jetro_source_url) で必ず確認してください。本 API は弁護士法 §72 / 行政書士法 §1 / "
    "出入国管理及び難民認定法 関連の役務 (申請取次行政書士等) には該当しません。"
)


def _open_autonomath_ro() -> sqlite3.Connection:
    path = os.environ.get("AUTONOMATH_DB_PATH", str(settings.autonomath_db_path))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "country_iso": row["country_iso"],
        "country_name_ja": row["country_name_ja"],
        "country_name_en": row["country_name_en"],
        "region": row["region"],
        "is_oecd": bool(row["is_oecd"]),
        "is_g7": bool(row["is_g7"]),
        "is_g20": bool(row["is_g20"]),
        "is_asean": bool(row["is_asean"]),
        "is_eu": bool(row["is_eu"]),
        "has_dta": bool(row["has_dta"]),
        "has_bit": bool(row["has_bit"]),
        "visa_keiei_kanri": row["visa_keiei_kanri"],
        "min_capital_yen": row["min_capital_yen"],
        "restricted_sectors": row["restricted_sectors"],
        "promotion_program": row["promotion_program"],
        "mofa_source_url": row["mofa_source_url"],
        "jetro_source_url": row["jetro_source_url"],
        "source_url": row["source_url"],
        "source_fetched_at": row["source_fetched_at"],
        "license": row["license"],
        "updated_at": row["updated_at"],
    }


def _build_list_query(
    region: str | None,
    is_g7: int | None,
    is_oecd: int | None,
    is_asean: int | None,
    is_eu: int | None,
    has_dta: int | None,
) -> tuple[str, list[Any]]:
    wheres: list[str] = []
    args: list[Any] = []
    if region is not None:
        wheres.append("region = ?")
        args.append(region)
    if is_g7 is not None:
        wheres.append("is_g7 = ?")
        args.append(int(is_g7))
    if is_oecd is not None:
        wheres.append("is_oecd = ?")
        args.append(int(is_oecd))
    if is_asean is not None:
        wheres.append("is_asean = ?")
        args.append(int(is_asean))
    if is_eu is not None:
        wheres.append("is_eu = ?")
        args.append(int(is_eu))
    if has_dta is not None:
        wheres.append("has_dta = ?")
        args.append(int(has_dta))
    sql = "SELECT * FROM v_fdi_country_public"
    if wheres:
        sql += " WHERE " + " AND ".join(wheres)
    sql += " ORDER BY country_iso ASC LIMIT ?"
    return sql, args


@router.get("/countries")
async def list_countries(
    region: Annotated[
        str | None,
        Query(description="region filter (asia_pacific / eu / north_america / latam / mideast_africa / oceania / other)"),
    ] = None,
    is_g7: Annotated[int | None, Query(ge=0, le=1, description="1=G7 members only")] = None,
    is_oecd: Annotated[int | None, Query(ge=0, le=1, description="1=OECD members only")] = None,
    is_asean: Annotated[int | None, Query(ge=0, le=1, description="1=ASEAN members only")] = None,
    is_eu: Annotated[int | None, Query(ge=0, le=1, description="1=EU members only")] = None,
    has_dta: Annotated[int | None, Query(ge=0, le=1, description="1=double-tax treaty with Japan present")] = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT, description=f"max rows (cap {_MAX_LIMIT})")] = _DEFAULT_LIMIT,
) -> JSONResponse:
    """List 80-country FDI cohort with optional region / membership filters."""
    if region is not None and region not in _ALLOWED_REGIONS:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_region",
                "message": f"region must be one of {sorted(_ALLOWED_REGIONS)}",
                "field": "region",
            },
        )

    sql, args = _build_list_query(region, is_g7, is_oecd, is_asean, is_eu, has_dta)
    args.append(int(limit))

    conn = _open_autonomath_ro()
    try:
        rows = conn.execute(sql, args).fetchall()
    except sqlite3.Error as exc:
        logger.warning("foreign_fdi list failed err=%s", exc)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "fdi_store_unavailable",
                "message": "autonomath FDI store is not available",
            },
        ) from exc
    finally:
        conn.close()

    items = [_row_to_dict(r) for r in rows]
    return JSONResponse(
        content={
            "items": items,
            "total": len(items),
            "limit": int(limit),
            "filters": {
                "region": region,
                "is_g7": is_g7,
                "is_oecd": is_oecd,
                "is_asean": is_asean,
                "is_eu": is_eu,
                "has_dta": has_dta,
            },
            "_billing_unit": 1,
            "_disclaimer": _DISCLAIMER,
        }
    )


@router.get("/country/{country_iso}")
async def get_country(
    country_iso: Annotated[
        str,
        PathParam(description="ISO 3166-1 alpha-2 country code (uppercase, e.g. 'US', 'JP')"),
    ],
) -> JSONResponse:
    """Single-country FDI detail. ¥3/req metered, NO LLM."""
    iso_norm = country_iso.upper().strip()
    if not _ISO_RE.match(iso_norm):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_country_iso",
                "message": "country_iso must be 2 uppercase letters (ISO 3166-1 alpha-2)",
                "field": "country_iso",
            },
        )

    conn = _open_autonomath_ro()
    try:
        row = conn.execute(
            "SELECT * FROM v_fdi_country_public WHERE country_iso = ?",
            (iso_norm,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("foreign_fdi detail failed iso=%s err=%s", iso_norm, exc)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "fdi_store_unavailable",
                "message": "autonomath FDI store is not available",
            },
        ) from exc
    finally:
        conn.close()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "country_not_found",
                "message": (
                    "country_iso not found in 80-country cohort. The cohort"
                    " is seeded by migration 266 (G7 + G20 + ASEAN + EU + EFTA"
                    " + priority Africa/GCC/LATAM). Submit a request to expand"
                    " coverage via support."
                ),
                "country_iso": iso_norm,
            },
        )

    body = _row_to_dict(row)
    body["_billing_unit"] = 1
    body["_disclaimer"] = _DISCLAIMER
    return JSONResponse(content=body)


__all__ = ["router"]
