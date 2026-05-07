"""REST handlers for the geographic dimension API: 47都道府県 × 1,724市区町村
program hit-map.

Background — R8 GEO REGION API (2026-05-07)
-------------------------------------------
The corpus carries 14,472 ``programs`` rows (11,601 surfaceable post-tier
filter), of which ~8,461 carry ``programs.prefecture`` and ~3,122 carry
``programs.municipality`` after B13 partial backfill. Locality coverage
on the data side is the long-pole; on the *query* side, however, callers
have repeatedly asked the same question: **「私 (法人) の所在地で使える
制度全部」instant lookup** — given a 5-digit 全国地方公共団体コード,
return every program that applies to that region (自治体 → 都道府県 → 国
hierarchy).

Three endpoints implement that surface:

* ``GET /v1/programs/by_region/{region_code}`` — given a 5-digit region
  code, return programs hierarchically split by level (国 / 都道府県 /
  市区町村). Designated wards (区) roll up to the parent designated city.
* ``GET /v1/regions/{region_code}/coverage`` — hit count per level + a
  ``coverage_gap`` flag indicating whether *any* program is mapped to the
  region (used by the operator UI to surface ingest-未着手 自治体).
* ``GET /v1/regions/search?q=文京区`` — fuzzy 自治体 name lookup. Used by
  the AI-consumer onboarding flow to map a free-text 法人所在地 string to
  a canonical 5-digit code.

Data model
----------
``am_region`` lives in **autonomath.db** (5,990 rows: 1 nation + 47
prefectures + 20 designated cities + 171 wards + 1,727 municipalities).
``programs`` lives in **jpintel.db** with text-typed ``prefecture`` /
``municipality`` columns matching ``am_region.name_ja``. There is no
ATTACH between the two DBs (db/session.py authorizer enforces the split),
so this module opens both connections and joins in Python.

Constraints
-----------
* Read-only; no LLM calls; pure SQLite + Python.
* Designated-ward resolution: a ward's parent_code points to the
  designated city, NOT directly to the prefecture; we walk one extra hop.
* National-level rollup: any program with ``authority_level IN
  ('national','国')`` is included for every region (国レベル applies
  uniformly).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot, snapshot_headers
from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES, ErrorEnvelope
from jpintel_mcp.api.deps import (
    ApiContextDep,
    DbDep,
    log_usage,
)

logger = logging.getLogger("jpintel.api.regions")

router = APIRouter(tags=["regions"])

# R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): /v1/programs/by_region は 補助金 + 融資 +
# 税優遇 を含む programs corpus を 5 桁地方公共団体コードで列挙する surface な
# ため、税理士法 §52 (税務代理) ・行政書士法 §1 (申請代理) ・中小企業診断士の経営助言
# の代替ではないことを明示する。/v1/regions/{code}/coverage と /v1/regions/search は
# 純粋な metadata 解決 (operator 用) であり業法 fence の対象外。
_DISCLAIMER_BY_REGION = (
    "本 by_region surface は am_region (5,990 行) で resolve した 5 桁"
    "地方公共団体コードに対し、jpintel programs corpus を national / "
    "prefecture / municipality 階層で列挙した機械的 hit-map です。"
    "税理士法 §52 (税務代理) ・行政書士法 §1 (申請代理) ・中小企業診断士の経営助言の"
    "代替ではなく、個別案件の適用可否は各 official_url の一次情報を必ずご確認ください。"
)

# ---------------------------------------------------------------------------
# autonomath.db opener — am_region only.
# ---------------------------------------------------------------------------

# Hierarchy levels emitted in by_region responses, in display order
# (broadest first). Must match am_region.region_level CHECK constraint
# (excluding designated_city/designated_ward which roll up).
_LEVEL_ORDER: tuple[str, ...] = ("nation", "prefecture", "municipality")

_RegionLevel = Literal["nation", "prefecture", "designated_city", "designated_ward", "municipality"]


def _autonomath_db_path() -> Path:
    """Resolve autonomath.db path from env or repo root.

    Mirrors the resolver used by mcp/autonomath_tools/db.py so REST and
    MCP layers see the same bytes. The connection is opened read-only
    URI-style; this path is also the single place to override for tests
    (set ``AUTONOMATH_DB_PATH``).
    """
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "autonomath.db"


def _open_am() -> sqlite3.Connection | None:
    """Open autonomath.db read-only. Returns None if file missing."""
    path = _autonomath_db_path()
    if not path.exists():
        logger.warning("autonomath.db missing: %s", path)
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        logger.warning("autonomath.db open failed: %s", exc)
        return None


def _resolve_region(am_conn: sqlite3.Connection, region_code: str) -> dict[str, Any] | None:
    """Look up am_region row for ``region_code`` + walk to the prefecture.

    Returns a dict with keys ``region_code``, ``region_level``, ``name_ja``,
    ``parent_code``, ``prefecture_code``, ``prefecture_name``. Designated
    wards walk one extra hop (ward → designated_city → prefecture).
    Returns None if the code is unknown.
    """
    row = am_conn.execute(
        "SELECT region_code, region_level, name_ja, parent_code "
        "FROM am_region WHERE region_code = ?",
        (region_code,),
    ).fetchone()
    if row is None:
        return None
    pref_code: str | None = None
    pref_name: str | None = None
    level: str = row["region_level"]
    parent: str | None = row["parent_code"]
    if level == "prefecture":
        pref_code = row["region_code"]
        pref_name = row["name_ja"]
    elif level == "nation":
        pref_code = None
        pref_name = None
    elif level == "designated_ward":
        # ward.parent = designated_city; that city's parent is the prefecture.
        if parent:
            city_row = am_conn.execute(
                "SELECT region_code, name_ja, parent_code FROM am_region WHERE region_code = ?",
                (parent,),
            ).fetchone()
            if city_row is not None and city_row["parent_code"]:
                pref_row = am_conn.execute(
                    "SELECT region_code, name_ja FROM am_region WHERE region_code = ?",
                    (city_row["parent_code"],),
                ).fetchone()
                if pref_row is not None:
                    pref_code = pref_row["region_code"]
                    pref_name = pref_row["name_ja"]
    elif parent:
        # municipality / designated_city → parent is the prefecture row.
        pref_row = am_conn.execute(
            "SELECT region_code, name_ja FROM am_region WHERE region_code = ?",
            (parent,),
        ).fetchone()
        if pref_row is not None and pref_row["region_code"] != "00000":
            pref_code = pref_row["region_code"]
            pref_name = pref_row["name_ja"]
    return {
        "region_code": row["region_code"],
        "region_level": level,
        "name_ja": row["name_ja"],
        "parent_code": parent,
        "prefecture_code": pref_code,
        "prefecture_name": pref_name,
    }


# ---------------------------------------------------------------------------
# Query helpers — programs side.
# ---------------------------------------------------------------------------

# Authority-level synonyms recognised by jpintel.db. The ingest pipeline
# uses both English ('national') and Japanese ('国') tags; a row tagged
# with either qualifies as a national-level program for our rollup.
_NATIONAL_AUTHORITY = ("national", "国")


def _select_columns() -> str:
    return (
        "unified_id, primary_name, authority_level, authority_name, "
        "prefecture, municipality, program_kind, official_url, "
        "amount_max_man_yen, amount_min_man_yen, tier"
    )


def _row_to_program(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "unified_id": row["unified_id"],
        "primary_name": row["primary_name"],
        "authority_level": row["authority_level"],
        "authority_name": row["authority_name"],
        "prefecture": row["prefecture"],
        "municipality": row["municipality"],
        "program_kind": row["program_kind"],
        "official_url": row["official_url"],
        "amount_max_man_yen": row["amount_max_man_yen"],
        "amount_min_man_yen": row["amount_min_man_yen"],
        "tier": row["tier"],
    }


def _fetch_national(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    placeholders = ",".join("?" * len(_NATIONAL_AUTHORITY))
    sql = (  # nosec B608
        f"SELECT {_select_columns()} FROM programs "
        f"WHERE authority_level IN ({placeholders}) "
        "AND COALESCE(excluded, 0) = 0 "
        "AND tier IN ('S','A','B','C') "
        "ORDER BY CASE tier WHEN 'S' THEN 1 WHEN 'A' THEN 2 "
        "WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END, primary_name "
        "LIMIT ?"
    )
    rows = conn.execute(sql, (*_NATIONAL_AUTHORITY, limit)).fetchall()
    return [_row_to_program(r) for r in rows]


def _fetch_prefecture(
    conn: sqlite3.Connection,
    pref_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    placeholders = ",".join("?" * len(_NATIONAL_AUTHORITY))
    sql = (  # nosec B608
        f"SELECT {_select_columns()} FROM programs "
        "WHERE prefecture = ? "
        # exclude programs that are also national-level — they appear in
        # the nation bucket already, no double-counting in by_region.
        f"AND COALESCE(authority_level, '') NOT IN ({placeholders}) "
        "AND COALESCE(excluded, 0) = 0 "
        "AND tier IN ('S','A','B','C') "
        "AND COALESCE(TRIM(municipality), '') = '' "
        "ORDER BY CASE tier WHEN 'S' THEN 1 WHEN 'A' THEN 2 "
        "WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END, primary_name "
        "LIMIT ?"
    )
    rows = conn.execute(sql, (pref_name, *_NATIONAL_AUTHORITY, limit)).fetchall()
    return [_row_to_program(r) for r in rows]


def _fetch_municipality(
    conn: sqlite3.Connection,
    pref_name: str | None,
    muni_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    if pref_name:
        sql = (  # nosec B608
            f"SELECT {_select_columns()} FROM programs "
            "WHERE prefecture = ? AND municipality = ? "
            "AND COALESCE(excluded, 0) = 0 "
            "AND tier IN ('S','A','B','C') "
            "ORDER BY CASE tier WHEN 'S' THEN 1 WHEN 'A' THEN 2 "
            "WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END, primary_name "
            "LIMIT ?"
        )
        rows = conn.execute(sql, (pref_name, muni_name, limit)).fetchall()
    else:
        sql = (  # nosec B608
            f"SELECT {_select_columns()} FROM programs "
            "WHERE municipality = ? "
            "AND COALESCE(excluded, 0) = 0 "
            "AND tier IN ('S','A','B','C') "
            "ORDER BY CASE tier WHEN 'S' THEN 1 WHEN 'A' THEN 2 "
            "WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END, primary_name "
            "LIMIT ?"
        )
        rows = conn.execute(sql, (muni_name, limit)).fetchall()
    return [_row_to_program(r) for r in rows]


def _count_national(conn: sqlite3.Connection) -> int:
    placeholders = ",".join("?" * len(_NATIONAL_AUTHORITY))
    sql = (  # nosec B608
        f"SELECT COUNT(*) AS n FROM programs "
        f"WHERE authority_level IN ({placeholders}) "
        "AND COALESCE(excluded, 0) = 0 "
        "AND tier IN ('S','A','B','C')"
    )
    row = conn.execute(sql, _NATIONAL_AUTHORITY).fetchone()
    return int(row["n"]) if row else 0


def _count_prefecture(conn: sqlite3.Connection, pref_name: str) -> int:
    placeholders = ",".join("?" * len(_NATIONAL_AUTHORITY))
    sql = (  # nosec B608
        f"SELECT COUNT(*) AS n FROM programs "
        "WHERE prefecture = ? "
        f"AND COALESCE(authority_level, '') NOT IN ({placeholders}) "
        "AND COALESCE(excluded, 0) = 0 "
        "AND tier IN ('S','A','B','C') "
        "AND COALESCE(TRIM(municipality), '') = ''"
    )
    row = conn.execute(sql, (pref_name, *_NATIONAL_AUTHORITY)).fetchone()
    return int(row["n"]) if row else 0


def _count_municipality(
    conn: sqlite3.Connection,
    pref_name: str | None,
    muni_name: str,
) -> int:
    if pref_name:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM programs "
            "WHERE prefecture = ? AND municipality = ? "
            "AND COALESCE(excluded, 0) = 0 "
            "AND tier IN ('S','A','B','C')",
            (pref_name, muni_name),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM programs "
            "WHERE municipality = ? "
            "AND COALESCE(excluded, 0) = 0 "
            "AND tier IN ('S','A','B','C')",
            (muni_name,),
        ).fetchone()
    return int(row["n"]) if row else 0


# ---------------------------------------------------------------------------
# Endpoints.
# ---------------------------------------------------------------------------


@router.get(
    "/v1/programs/by_region/{region_code}",
    summary="Programs hit-map for a 5-digit 全国地方公共団体コード",
    description=(
        "Given a 5-digit 全国地方公共団体コード (e.g. `13105` for 文京区, "
        "`13000` for 東京都, `00000` for 全国), return every applicable "
        "program split into three buckets:\n\n"
        "- `national` — programs with `authority_level IN ('national','国')`. "
        "  Always included (国レベル applies uniformly).\n"
        "- `prefecture` — programs whose `prefecture` matches the region's "
        "  parent prefecture, with empty `municipality` (i.e. true 都道府県 "
        "  programs, not 市区町村-level rolled up by mistake).\n"
        "- `municipality` — programs whose `municipality` matches the region "
        "  (only populated when the region itself is a 自治体).\n\n"
        "Designated wards (e.g. 札幌市中央区 = `01101`) walk one hop up: "
        "ward → designated_city → prefecture, so 文京区's prefecture bucket "
        "is 東京都's prefecture-level rows.\n\n"
        "Tier filter: only S/A/B/C; quarantined (X) and excluded rows skipped. "
        "Limit per bucket capped at 100."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": (
                "Hierarchical program list grouped by `national` / `prefecture` "
                "/ `municipality`, with the resolved region metadata."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "region": {
                            "region_code": "13105",
                            "region_level": "municipality",
                            "name_ja": "文京区",
                            "prefecture_code": "13000",
                            "prefecture_name": "東京都",
                        },
                        "national": [],
                        "prefecture": [],
                        "municipality": [],
                        "totals": {"national": 2868, "prefecture": 30, "municipality": 1},
                    }
                }
            },
        },
        404: {
            "model": ErrorEnvelope,
            "description": "region_code unknown — `error.code='no_matching_records'`.",
        },
    },
)
def programs_by_region(
    region_code: str,
    conn: DbDep,
    ctx: ApiContextDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    if not region_code or len(region_code) != 5 or not region_code.isdigit():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "region_code must be a 5-digit 全国地方公共団体コード",
        )
    am = _open_am()
    if am is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "am_region table unavailable")
    try:
        region = _resolve_region(am, region_code)
    finally:
        am.close()
    if region is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"region not found: {region_code}")

    national = _fetch_national(conn, limit)
    prefecture: list[dict[str, Any]] = []
    municipality: list[dict[str, Any]] = []

    pref_name = region["prefecture_name"]
    if pref_name and region["region_level"] == "prefecture":
        prefecture = _fetch_prefecture(conn, pref_name, limit)
    elif pref_name:
        prefecture = _fetch_prefecture(conn, pref_name, limit)
        if region["region_level"] in (
            "municipality",
            "designated_city",
            "designated_ward",
        ):
            municipality = _fetch_municipality(conn, pref_name, region["name_ja"], limit)
    elif region["region_level"] == "nation":
        # Whole-country rollup has no prefecture/municipality bucket beyond the
        # national list.
        pass

    totals = {
        "national": _count_national(conn),
        "prefecture": _count_prefecture(conn, pref_name) if pref_name else 0,
        "municipality": (
            _count_municipality(conn, pref_name, region["name_ja"])
            if region["region_level"] in ("municipality", "designated_city", "designated_ward")
            else 0
        ),
    }

    body: dict[str, Any] = {
        "region": region,
        "national": national,
        "prefecture": prefecture,
        "municipality": municipality,
        "totals": totals,
        "limit": limit,
        # R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): 業法 fence — programs_by_region
        # surfaces 補助金 / 融資 / 税優遇 を hit-map 化するため、§52 / §1 fence
        # を envelope に明示する。/coverage + /search は operator metadata 用で
        # fence 対象外。
        "_disclaimer": _DISCLAIMER_BY_REGION,
    }
    log_usage(
        conn,
        ctx,
        "programs.by_region",
        params={"region_code": region_code, "limit": limit},
        strict_metering=True,
    )
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body, headers=snapshot_headers(conn))


@router.get(
    "/v1/regions/{region_code}/coverage",
    summary="Program-coverage gap detection for a region",
    description=(
        "Return the per-level program hit count for a region plus a "
        "`coverage_gap` boolean flagging ingest 未着手 自治体 (defined as "
        "`prefecture==0 AND municipality==0` for non-nation regions). The "
        "`national` bucket is always nonzero in production and is intended "
        "as a sanity baseline.\n\n"
        "Used by the operator data-quality dashboard to surface "
        "市区町村 with no jpintel.db rows mapped — those are the 自治体 to "
        "prioritise in the next ingest pass."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        404: {
            "model": ErrorEnvelope,
            "description": "region_code unknown.",
        },
    },
)
def region_coverage(
    region_code: str,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    if not region_code or len(region_code) != 5 or not region_code.isdigit():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "region_code must be a 5-digit 全国地方公共団体コード",
        )
    am = _open_am()
    if am is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "am_region table unavailable")
    try:
        region = _resolve_region(am, region_code)
    finally:
        am.close()
    if region is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"region not found: {region_code}")

    pref_name = region["prefecture_name"]
    counts = {
        "national": _count_national(conn),
        "prefecture": _count_prefecture(conn, pref_name) if pref_name else 0,
        "municipality": (
            _count_municipality(conn, pref_name, region["name_ja"])
            if region["region_level"] in ("municipality", "designated_city", "designated_ward")
            else 0
        ),
    }
    is_self_region = region["region_level"] != "nation"
    gap = is_self_region and counts["prefecture"] == 0 and counts["municipality"] == 0
    body: dict[str, Any] = {
        "region": region,
        "counts": counts,
        "coverage_gap": gap,
    }
    log_usage(
        conn,
        ctx,
        "regions.coverage",
        params={"region_code": region_code},
        strict_metering=True,
    )
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body, headers=snapshot_headers(conn))


@router.get(
    "/v1/regions/search",
    summary="Free-text search over am_region (自治体名 lookup)",
    description=(
        "Fuzzy substring search over `am_region.name_ja` so consumers can "
        "map a free-text 法人所在地 string (e.g. '文京区') to a canonical "
        "5-digit 全国地方公共団体コード. Default limit 20, max 100.\n\n"
        "Filter by `level` to restrict to one of `nation` / `prefecture` / "
        "`designated_city` / `designated_ward` / `municipality`.\n\n"
        "Sort: exact match first, then prefix match, then substring match, "
        "all alphabetical within a tier."
    ),
)
def regions_search(
    conn: DbDep,
    ctx: ApiContextDep,
    q: Annotated[str, Query(min_length=1, max_length=80)],
    level: Annotated[_RegionLevel | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    am = _open_am()
    if am is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "am_region table unavailable")
    try:
        clauses: list[str] = ["name_ja LIKE ?"]
        params: list[Any] = [f"%{q}%"]
        if level:
            clauses.append("region_level = ?")
            params.append(level)
        where = " AND ".join(clauses)
        # Exact > prefix > substring tier so '北区' lookup ranks 北区 above
        # 札幌市北区/さいたま市北区 (which match as substring only).
        sql = (  # nosec B608
            "SELECT region_code, region_level, name_ja, parent_code, "
            "  CASE "
            "    WHEN name_ja = ? THEN 0 "
            "    WHEN name_ja LIKE ? THEN 1 "
            "    ELSE 2 "
            "  END AS rank "
            f"FROM am_region WHERE {where} "
            "ORDER BY rank, name_ja LIMIT ?"
        )
        rows = am.execute(
            sql,
            (q, f"{q}%", *params, limit),
        ).fetchall()
    finally:
        am.close()
    results = [
        {
            "region_code": r["region_code"],
            "region_level": r["region_level"],
            "name_ja": r["name_ja"],
            "parent_code": r["parent_code"],
        }
        for r in rows
    ]
    body: dict[str, Any] = {
        "q": q,
        "level": level,
        "results": results,
        "total": len(results),
        "limit": limit,
    }
    log_usage(
        conn,
        ctx,
        "regions.search",
        params={"q": q, "level": level, "limit": limit},
        strict_metering=True,
    )
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body, headers=snapshot_headers(conn))


__all__ = ["router", "_LEVEL_ORDER", "_resolve_region", "_open_am", "_autonomath_db_path"]
