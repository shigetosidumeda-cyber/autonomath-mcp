"""region_tools — R8 GEO REGION API MCP tool surface (3 tools, 2026-05-07).

Three MCP tools that mirror the REST endpoints in
``src/jpintel_mcp/api/regions.py`` so MCP-only clients (Claude Desktop /
DXT / external agents) get the same 47都道府県 × 1,724市区町村 hit-map.

* ``programs_by_region_am(region_code, limit=20)`` — for a 5-digit 全国
  地方公共団体コード return programs split by 国 / 都道府県 / 市区町村.
* ``region_coverage_am(region_code)`` — per-level counts + coverage_gap
  flag for ingest-未着手 自治体 detection.
* ``search_regions_am(q, level=None, limit=20)`` — free-text 自治体名
  lookup (fuzzy substring + exact/prefix/substring rank).

Constraints
-----------
* Read-only; no LLM calls. Pure SQLite + Python.
* Each call is a single ¥3/req billing event handled at the MCP envelope
  layer (server.py::_safe_tool); these wrappers do NOT meter directly.
* No ``_disclaimer`` envelope — the data is public-domain 全国地方公共
  団体コード (総務省 公開) + jpintel.db program counts; not §52/§47条の2
  /§72 sensitive.
* Gated by ``AUTONOMATH_REGION_API_ENABLED`` (default ON). Flip to "0"
  for one-flag rollback if a downstream consumer breaks.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.region_tools")

_ENABLED = os.environ.get("AUTONOMATH_REGION_API_ENABLED", "1") == "1"

# Mirrors api/regions.py — keep in sync.
_NATIONAL_AUTHORITY = ("national", "国")
_LEVEL_ORDER = ("nation", "prefecture", "municipality")


def _autonomath_db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    # autonomath_tools/region_tools.py → autonomath_tools/ → mcp/ →
    # jpintel_mcp/ → src/ → repo root
    return Path(__file__).resolve().parents[4] / "autonomath.db"


def _jpintel_db_path() -> Path:
    raw = os.environ.get("JPINTEL_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[5] / "data" / "jpintel.db"


def _open_ro(path: Path) -> sqlite3.Connection | dict[str, Any]:
    if not path.exists():
        return make_error(
            code="db_unavailable",
            message=f"sqlite file missing: {path}",
        )
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        return make_error(code="db_unavailable", message=f"sqlite open failed: {exc}")


def _resolve_region(am_conn: sqlite3.Connection, region_code: str) -> dict[str, Any] | None:
    row = am_conn.execute(
        "SELECT region_code, region_level, name_ja, parent_code "
        "FROM am_region WHERE region_code = ?",
        (region_code,),
    ).fetchone()
    if row is None:
        return None
    pref_code: str | None = None
    pref_name: str | None = None
    level = row["region_level"]
    parent = row["parent_code"]
    if level == "prefecture":
        pref_code = row["region_code"]
        pref_name = row["name_ja"]
    elif level == "designated_ward" and parent:
        city = am_conn.execute(
            "SELECT region_code, name_ja, parent_code FROM am_region WHERE region_code = ?",
            (parent,),
        ).fetchone()
        if city is not None and city["parent_code"]:
            pref = am_conn.execute(
                "SELECT region_code, name_ja FROM am_region WHERE region_code = ?",
                (city["parent_code"],),
            ).fetchone()
            if pref is not None:
                pref_code = pref["region_code"]
                pref_name = pref["name_ja"]
    elif parent and level != "nation":
        pref = am_conn.execute(
            "SELECT region_code, name_ja FROM am_region WHERE region_code = ?",
            (parent,),
        ).fetchone()
        if pref is not None and pref["region_code"] != "00000":
            pref_code = pref["region_code"]
            pref_name = pref["name_ja"]
    return {
        "region_code": row["region_code"],
        "region_level": level,
        "name_ja": row["name_ja"],
        "parent_code": parent,
        "prefecture_code": pref_code,
        "prefecture_name": pref_name,
    }


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


def _select_cols() -> str:
    return (
        "unified_id, primary_name, authority_level, authority_name, "
        "prefecture, municipality, program_kind, official_url, "
        "amount_max_man_yen, amount_min_man_yen, tier"
    )


def _fetch_national(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    placeholders = ",".join("?" * len(_NATIONAL_AUTHORITY))
    sql = (  # nosec B608
        f"SELECT {_select_cols()} FROM programs "
        f"WHERE authority_level IN ({placeholders}) "
        "AND COALESCE(excluded, 0) = 0 "
        "AND tier IN ('S','A','B','C') "
        "ORDER BY CASE tier WHEN 'S' THEN 1 WHEN 'A' THEN 2 "
        "WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END, primary_name "
        "LIMIT ?"
    )
    return [_row_to_program(r) for r in conn.execute(sql, (*_NATIONAL_AUTHORITY, limit)).fetchall()]


def _fetch_prefecture(conn: sqlite3.Connection, pref_name: str, limit: int) -> list[dict[str, Any]]:
    placeholders = ",".join("?" * len(_NATIONAL_AUTHORITY))
    sql = (  # nosec B608
        f"SELECT {_select_cols()} FROM programs "
        "WHERE prefecture = ? "
        f"AND COALESCE(authority_level, '') NOT IN ({placeholders}) "
        "AND COALESCE(excluded, 0) = 0 "
        "AND tier IN ('S','A','B','C') "
        "AND COALESCE(TRIM(municipality), '') = '' "
        "ORDER BY CASE tier WHEN 'S' THEN 1 WHEN 'A' THEN 2 "
        "WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END, primary_name "
        "LIMIT ?"
    )
    return [
        _row_to_program(r)
        for r in conn.execute(sql, (pref_name, *_NATIONAL_AUTHORITY, limit)).fetchall()
    ]


def _fetch_municipality(
    conn: sqlite3.Connection,
    pref_name: str | None,
    muni_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    if pref_name:
        sql = (  # nosec B608
            f"SELECT {_select_cols()} FROM programs "
            "WHERE prefecture = ? AND municipality = ? "
            "AND COALESCE(excluded, 0) = 0 "
            "AND tier IN ('S','A','B','C') "
            "ORDER BY CASE tier WHEN 'S' THEN 1 WHEN 'A' THEN 2 "
            "WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END, primary_name "
            "LIMIT ?"
        )
        return [
            _row_to_program(r) for r in conn.execute(sql, (pref_name, muni_name, limit)).fetchall()
        ]
    sql = (  # nosec B608
        f"SELECT {_select_cols()} FROM programs "
        "WHERE municipality = ? "
        "AND COALESCE(excluded, 0) = 0 "
        "AND tier IN ('S','A','B','C') "
        "ORDER BY CASE tier WHEN 'S' THEN 1 WHEN 'A' THEN 2 "
        "WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END, primary_name "
        "LIMIT ?"
    )
    return [_row_to_program(r) for r in conn.execute(sql, (muni_name, limit)).fetchall()]


def _count_national(conn: sqlite3.Connection) -> int:
    placeholders = ",".join("?" * len(_NATIONAL_AUTHORITY))
    sql = (  # nosec B608
        "SELECT COUNT(*) AS n FROM programs "
        f"WHERE authority_level IN ({placeholders}) "
        "AND COALESCE(excluded, 0) = 0 "
        "AND tier IN ('S','A','B','C')"
    )
    row = conn.execute(sql, _NATIONAL_AUTHORITY).fetchone()
    return int(row["n"]) if row else 0


def _count_prefecture(conn: sqlite3.Connection, pref_name: str) -> int:
    placeholders = ",".join("?" * len(_NATIONAL_AUTHORITY))
    sql = (  # nosec B608
        "SELECT COUNT(*) AS n FROM programs "
        "WHERE prefecture = ? "
        f"AND COALESCE(authority_level, '') NOT IN ({placeholders}) "
        "AND COALESCE(excluded, 0) = 0 "
        "AND tier IN ('S','A','B','C') "
        "AND COALESCE(TRIM(municipality), '') = ''"
    )
    row = conn.execute(sql, (pref_name, *_NATIONAL_AUTHORITY)).fetchone()
    return int(row["n"]) if row else 0


def _count_municipality(conn: sqlite3.Connection, pref_name: str | None, muni_name: str) -> int:
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
# Pure-Python implementations (testable without MCP plumbing).
# ---------------------------------------------------------------------------


def _impl_programs_by_region(region_code: str, limit: int = 20) -> dict[str, Any]:
    if not isinstance(region_code, str) or len(region_code) != 5 or not region_code.isdigit():
        return make_error(
            code="missing_required_arg",
            message="region_code must be a 5-digit 全国地方公共団体コード",
            field="region_code",
        )
    limit = max(1, min(int(limit), 100))
    am = _open_ro(_autonomath_db_path())
    if isinstance(am, dict):
        return am
    try:
        region = _resolve_region(am, region_code)
    finally:
        am.close()
    if region is None:
        return make_error(
            code="no_matching_records",
            message=f"region not found: {region_code}",
        )
    db = _open_ro(_jpintel_db_path())
    if isinstance(db, dict):
        return db
    try:
        national = _fetch_national(db, limit)
        pref_name = region["prefecture_name"]
        prefecture: list[dict[str, Any]] = (
            _fetch_prefecture(db, pref_name, limit) if pref_name else []
        )
        municipality: list[dict[str, Any]] = []
        if pref_name and region["region_level"] in (
            "municipality",
            "designated_city",
            "designated_ward",
        ):
            municipality = _fetch_municipality(db, pref_name, region["name_ja"], limit)
        totals = {
            "national": _count_national(db),
            "prefecture": _count_prefecture(db, pref_name) if pref_name else 0,
            "municipality": (
                _count_municipality(db, pref_name, region["name_ja"])
                if region["region_level"] in ("municipality", "designated_city", "designated_ward")
                else 0
            ),
        }
    finally:
        db.close()
    return {
        "region": region,
        "national": national,
        "prefecture": prefecture,
        "municipality": municipality,
        "totals": totals,
        "limit": limit,
    }


def _impl_region_coverage(region_code: str) -> dict[str, Any]:
    if not isinstance(region_code, str) or len(region_code) != 5 or not region_code.isdigit():
        return make_error(
            code="missing_required_arg",
            message="region_code must be a 5-digit 全国地方公共団体コード",
            field="region_code",
        )
    am = _open_ro(_autonomath_db_path())
    if isinstance(am, dict):
        return am
    try:
        region = _resolve_region(am, region_code)
    finally:
        am.close()
    if region is None:
        return make_error(
            code="no_matching_records",
            message=f"region not found: {region_code}",
        )
    db = _open_ro(_jpintel_db_path())
    if isinstance(db, dict):
        return db
    try:
        pref_name = region["prefecture_name"]
        counts = {
            "national": _count_national(db),
            "prefecture": _count_prefecture(db, pref_name) if pref_name else 0,
            "municipality": (
                _count_municipality(db, pref_name, region["name_ja"])
                if region["region_level"] in ("municipality", "designated_city", "designated_ward")
                else 0
            ),
        }
    finally:
        db.close()
    is_self = region["region_level"] != "nation"
    gap = is_self and counts["prefecture"] == 0 and counts["municipality"] == 0
    return {"region": region, "counts": counts, "coverage_gap": gap}


def _impl_search_regions(q: str, level: str | None = None, limit: int = 20) -> dict[str, Any]:
    if not isinstance(q, str) or not q.strip():
        return make_error(
            code="missing_required_arg", message="q must be a non-empty string", field="q"
        )
    q = q.strip()
    limit = max(1, min(int(limit), 100))
    valid_levels = {
        None,
        "nation",
        "prefecture",
        "designated_city",
        "designated_ward",
        "municipality",
    }
    if level is not None and level not in valid_levels:
        return make_error(
            code="invalid_enum",
            message=f"level must be one of {sorted(v for v in valid_levels if v)}",
            field="level",
        )
    am = _open_ro(_autonomath_db_path())
    if isinstance(am, dict):
        return am
    try:
        clauses: list[str] = ["name_ja LIKE ?"]
        params: list[Any] = [f"%{q}%"]
        if level:
            clauses.append("region_level = ?")
            params.append(level)
        where = " AND ".join(clauses)
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
        rows = am.execute(sql, (q, f"{q}%", *params, limit)).fetchall()
    finally:
        am.close()
    return {
        "q": q,
        "level": level,
        "results": [
            {
                "region_code": r["region_code"],
                "region_level": r["region_level"],
                "name_ja": r["name_ja"],
                "parent_code": r["parent_code"],
            }
            for r in rows
        ],
        "total": len(rows),
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# MCP tool registration (gated).
# ---------------------------------------------------------------------------


if _ENABLED:

    @mcp.tool(annotations=_READ_ONLY)
    def programs_by_region_am(
        region_code: Annotated[
            str,
            Field(
                description=(
                    "5-digit 全国地方公共団体コード. e.g. '13105' for 文京区, "
                    "'13000' for 東京都, '00000' for 全国."
                ),
                min_length=5,
                max_length=5,
                pattern=r"^\d{5}$",
            ),
        ],
        limit: Annotated[
            int,
            Field(
                default=20,
                description="Per-bucket cap (national / prefecture / municipality).",
                ge=1,
                le=100,
            ),
        ] = 20,
    ) -> dict[str, Any]:
        """Programs hit-map for a 5-digit region code.

        Returns programs split by `national` / `prefecture` / `municipality`
        with per-bucket totals. Designated wards walk one hop up
        (ward → designated_city → prefecture). Tier filter S/A/B/C only.
        """
        return _impl_programs_by_region(region_code=region_code, limit=limit)

    @mcp.tool(annotations=_READ_ONLY)
    def region_coverage_am(
        region_code: Annotated[
            str,
            Field(
                description="5-digit 全国地方公共団体コード.",
                min_length=5,
                max_length=5,
                pattern=r"^\d{5}$",
            ),
        ],
    ) -> dict[str, Any]:
        """Per-level program hit count + coverage_gap flag for a region.

        coverage_gap is True when the region is non-national AND has zero
        rows mapped to its prefecture-level OR municipality-level bucket
        (used to surface ingest 未着手 自治体 to the operator).
        """
        return _impl_region_coverage(region_code=region_code)

    @mcp.tool(annotations=_READ_ONLY)
    def search_regions_am(
        q: Annotated[
            str,
            Field(
                description="Free-text 自治体名 (substring fuzzy match on am_region.name_ja).",
                min_length=1,
                max_length=80,
            ),
        ],
        level: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Optional region_level filter. One of nation / prefecture / "
                    "designated_city / designated_ward / municipality."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(default=20, ge=1, le=100, description="Result cap."),
        ] = 20,
    ) -> dict[str, Any]:
        """Free-text search over am_region (1,966 rows). Exact > prefix > substring rank."""
        return _impl_search_regions(q=q, level=level, limit=limit)


__all__ = [
    "_impl_programs_by_region",
    "_impl_region_coverage",
    "_impl_search_regions",
]
