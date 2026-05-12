"""foreign_fdi_mcp — Wave 46 dim 19 EJ booster (2026-05-12)

Dim J FDI 80-country MCP wrapper over the existing REST surface at
``GET /v1/foreign_fdi/v2/countries`` and
``GET /v1/foreign_fdi/v2/country/{country_iso}``
(api/foreign_fdi_v2.py, Wave 43.2.10).

Two tools registered at import time when both
``AUTONOMATH_FOREIGN_FDI_MCP_ENABLED`` (default ON) and
``settings.autonomath_enabled`` are truthy:

  * ``foreign_fdi_list_am``     filter the 80-country cohort by region /
                                G7 / OECD / ASEAN / EU / DTA flag.
  * ``foreign_fdi_country_am``  single-country FDI entry detail by
                                ISO 3166-1 alpha-2 code.

Both delegate to lightweight SQL helpers in ``api/foreign_fdi_v2.py``
(``_open_autonomath_ro`` / ``_build_list_query`` / ``_row_to_dict``)
so the MCP surface and REST surface stay byte-stable.

Hard constraints (CLAUDE.md):

  * NO LLM call. Pure SQLite SELECT against ``v_fdi_country_public``.
  * NO HTTP. Single-process delegation to the api module.
  * 1 ¥3/req billing unit per call.
  * 弁護士法 §72 / 行政書士法 §1 / 出入国管理及び難民認定法 関連の役務
    (申請取次行政書士等) 非代替 disclaimer envelope.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.foreign_fdi_mcp")

_ENABLED = os.environ.get("AUTONOMATH_FOREIGN_FDI_MCP_ENABLED", "1") == "1"

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
    "jetro_source_url) で必ず確認してください。本 MCP tool は弁護士法 §72 / 行政書士法 §1 / "
    "出入国管理及び難民認定法 関連の役務 (申請取次行政書士等) には該当しません。"
)


def _foreign_fdi_list_am_impl(
    region: str | None = None,
    is_g7: int | None = None,
    is_oecd: int | None = None,
    is_asean: int | None = None,
    is_eu: int | None = None,
    has_dta: int | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """List 80-country FDI cohort. Mirrors REST GET /v1/foreign_fdi/v2/countries."""
    if region is not None and region not in _ALLOWED_REGIONS:
        return make_error(
            code="invalid_input",
            message=f"region must be one of {sorted(_ALLOWED_REGIONS)}",
            field="region",
        )
    if not 1 <= int(limit) <= _MAX_LIMIT:
        return make_error(
            code="invalid_input",
            message=f"limit must be in [1, {_MAX_LIMIT}]",
            field="limit",
        )

    from jpintel_mcp.api.foreign_fdi_v2 import (
        _build_list_query,
        _open_autonomath_ro,
        _row_to_dict,
    )

    sql, args = _build_list_query(region, is_g7, is_oecd, is_asean, is_eu, has_dta)
    args.append(int(limit))

    conn = _open_autonomath_ro()
    try:
        rows = conn.execute(sql, args).fetchall()
    except sqlite3.Error as exc:
        logger.warning("foreign_fdi_list_am sql failure: %s", exc)
        return make_error(
            code="subsystem_unavailable",
            message=f"autonomath FDI store is not available: {exc}",
        )
    finally:
        conn.close()

    items = [_row_to_dict(r) for r in rows]
    return {
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


def _foreign_fdi_country_am_impl(country_iso: str) -> dict[str, Any]:
    """Single-country FDI detail. Mirrors REST GET /v1/foreign_fdi/v2/country/{iso}."""
    iso_norm = (country_iso or "").upper().strip()
    if not _ISO_RE.match(iso_norm):
        return make_error(
            code="invalid_input",
            message="country_iso must be 2 uppercase letters (ISO 3166-1 alpha-2)",
            field="country_iso",
        )

    from jpintel_mcp.api.foreign_fdi_v2 import _open_autonomath_ro, _row_to_dict

    conn = _open_autonomath_ro()
    try:
        row = conn.execute(
            "SELECT * FROM v_fdi_country_public WHERE country_iso = ?",
            (iso_norm,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("foreign_fdi_country_am sql failure iso=%s: %s", iso_norm, exc)
        return make_error(
            code="subsystem_unavailable",
            message=f"autonomath FDI store is not available: {exc}",
        )
    finally:
        conn.close()

    if row is None:
        return make_error(
            code="not_found",
            message=(
                "country_iso not found in 80-country cohort. The cohort is "
                "seeded by migration 266 (G7 + G20 + ASEAN + EU + EFTA + "
                "priority Africa/GCC/LATAM)."
            ),
            field="country_iso",
        )

    body = _row_to_dict(row)
    body["_billing_unit"] = 1
    body["_disclaimer"] = _DISCLAIMER
    return body


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def foreign_fdi_list_am(
        region: Annotated[
            str | None,
            Field(
                description=(
                    "Region filter (asia_pacific / eu / north_america / latam / "
                    "mideast_africa / oceania / other). None で全 region 対象。"
                ),
            ),
        ] = None,
        is_g7: Annotated[
            int | None,
            Field(ge=0, le=1, description="1 で G7 7 か国 (US/UK/DE/FR/IT/CA/JP) のみ"),
        ] = None,
        is_oecd: Annotated[
            int | None,
            Field(ge=0, le=1, description="1 で OECD 加盟国のみ"),
        ] = None,
        is_asean: Annotated[
            int | None,
            Field(ge=0, le=1, description="1 で ASEAN 10 か国のみ"),
        ] = None,
        is_eu: Annotated[
            int | None,
            Field(ge=0, le=1, description="1 で EU 加盟国のみ"),
        ] = None,
        has_dta: Annotated[
            int | None,
            Field(
                ge=0,
                le=1,
                description="1 で 日本との二重課税回避条約 (DTA) 締結国のみ",
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=_MAX_LIMIT,
                description=f"返す件数 (1..{_MAX_LIMIT})。デフォルト {_DEFAULT_LIMIT}。",
            ),
        ] = _DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        """いつ使う: 海外法人 (FDI) 日本進出 entry condition を 80 か国 cohort から filter — region / G7 / OECD / ASEAN / EU / DTA flag の任意組み合わせ. 入力: region (optional enum), is_g7/is_oecd/is_asean/is_eu/has_dta (optional 0|1), limit (1-200). 出力: items (FDI 国情報 list w/ visa_keiei_kanri / min_capital_yen / restricted_sectors / promotion_program / mofa+jetro source_url), total, filters, _billing_unit=1, _disclaimer (§72/§1/出入国管理). エラー: invalid_input (region/limit), subsystem_unavailable. REST companion at GET /v1/foreign_fdi/v2/countries."""
        return _foreign_fdi_list_am_impl(
            region=region,
            is_g7=is_g7,
            is_oecd=is_oecd,
            is_asean=is_asean,
            is_eu=is_eu,
            has_dta=has_dta,
            limit=limit,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def foreign_fdi_country_am(
        country_iso: Annotated[
            str,
            Field(
                description=(
                    "ISO 3166-1 alpha-2 country code (例 'US', 'JP', 'DE'). "
                    "case-insensitive — 自動的に upper-case 化される。"
                ),
                min_length=2,
                max_length=2,
            ),
        ],
    ) -> dict[str, Any]:
        """いつ使う: 1 か国の FDI 進出 entry condition 詳細 — visa keiei-kanri / 最低資本金 / 業種制限 / DTA+BIT presence / MOFA+JETRO 一次資料 source_url. 入力: country_iso (ISO 3166-1 alpha-2, 2-letter uppercase). 出力: country_name_ja+en, region, OECD/G7/G20/ASEAN/EU 旗, visa_keiei_kanri, min_capital_yen, restricted_sectors, promotion_program, mofa_source_url, jetro_source_url, license, _billing_unit=1, _disclaimer (§72/§1/出入国管理). エラー: invalid_input (ISO regex), not_found (cohort 外), subsystem_unavailable. REST companion at GET /v1/foreign_fdi/v2/country/{country_iso}."""
        return _foreign_fdi_country_am_impl(country_iso=country_iso)


__all__ = [
    "_foreign_fdi_list_am_impl",
    "_foreign_fdi_country_am_impl",
]
