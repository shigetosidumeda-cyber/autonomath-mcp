"""Moat N4 - Filing window MCP wrappers (2 tools, LIVE 2026-05-17).

Surfaces the N4 window directory lane backed by am_window_directory
(~4,700 1次資料-backed rows from 法務省/国税庁/47都道府県/1727市区町村/
jcci/shokokai/JFC/信金界).

* find_filing_window(program_id_or_kind, houjin_bangou) -> 5 best
  windows matched by houjin registered_address prefix.
* list_windows(jurisdiction_kind, region_code=None, limit=50) ->
  windows by kind + optional 5-digit region_code filter.

NO LLM, NO HTTP. Pure SQLite. 1 ¥3/req billing event each.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

logger = logging.getLogger("jpintel.mcp.moat_lane_tools.moat_n4_window")

_VALID_KINDS: tuple[str, ...] = (
    "legal_affairs_bureau",
    "tax_office",
    "prefecture",
    "municipality",
    "chamber_of_commerce",
    "commerce_society",
    "jfc_branch",
    "shinkin",
    "credit_union",
    "labour_bureau",
    "pension_office",
    "other",
)

_KIND_ALIASES: dict[str, tuple[str, ...]] = {
    "tax": ("tax_office",),
    "tax_office": ("tax_office",),
    "register": ("legal_affairs_bureau",),
    "registry": ("legal_affairs_bureau",),
    "legal_affairs_bureau": ("legal_affairs_bureau",),
    "prefecture": ("prefecture",),
    "municipal": ("municipality",),
    "municipality": ("municipality",),
    "chamber": ("chamber_of_commerce", "commerce_society"),
    "loan": ("jfc_branch", "shinkin"),
    "jfc": ("jfc_branch",),
    "shinkin": ("shinkin",),
    "credit_union": ("credit_union",),
}

_DISCLAIMER = (
    "am_window_directory (~4,700 rows) prefix match. May misfire on "
    "boundary towns or multi-jurisdiction corps. Always confirm via "
    "the source_url 1st-party page."
)


def _autonomath_db_path() -> Path:
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[4] / "autonomath.db"


def _open_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def _lookup_houjin_address(am_conn: sqlite3.Connection, houjin_bangou: str) -> str | None:
    bangou = houjin_bangou.strip()
    if not bangou:
        return None
    row = am_conn.execute(
        "SELECT canonical_id FROM am_entities "
        "WHERE record_kind='corporate_entity' AND canonical_id = ? LIMIT 1",
        (f"houjin:{bangou}",),
    ).fetchone()
    if row is None:
        return None
    fact = am_conn.execute(
        "SELECT value_text FROM am_entity_facts "
        "WHERE entity_id=? AND field_name IN "
        "('corp.registered_address','corp.location','corp.address') "
        "LIMIT 1",
        (row["canonical_id"],),
    ).fetchone()
    if fact is None:
        return None
    return str(fact["value_text"])


def _find_windows_by_address(
    am_conn: sqlite3.Connection,
    address: str,
    kinds: tuple[str, ...],
    limit: int = 5,
) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in kinds)
    rows = am_conn.execute(
        f"SELECT window_id, jurisdiction_kind, name, postal_address, "
        f"       tel, url, jurisdiction_houjin_filter_regex, "
        f"       jurisdiction_region_code, source_url, license "
        f"  FROM am_window_directory "
        f" WHERE jurisdiction_kind IN ({placeholders}) "
        f"   AND jurisdiction_houjin_filter_regex IS NOT NULL "
        f"   AND ? LIKE jurisdiction_houjin_filter_regex || '%'",
        (*kinds, address),
    ).fetchall()
    return [dict(r) for r in rows[:limit]]


@mcp.tool(annotations=_READ_ONLY)
def find_filing_window(
    program_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            description=(
                "Program/window kind. High-level alias "
                "(tax/register/prefecture/municipal/chamber/loan/jfc/shinkin) "
                "or raw jurisdiction_kind."
            ),
        ),
    ],
    houjin_bangou: Annotated[
        str,
        Field(min_length=13, max_length=13, description="13-digit houjin bangou."),
    ],
) -> dict[str, Any]:
    """[AUDIT] Moat N4 - Resolve filing window for (program, houjin).

    Reads am_window_directory (~4,700 rows). NO LLM. Single 3 JPY/req.
    """
    program_or_kind = program_id.strip()
    kinds = _KIND_ALIASES.get(program_or_kind.lower())
    if kinds is None:
        if program_or_kind in _VALID_KINDS:
            kinds = (program_or_kind,)
        else:
            return {
                "error": {
                    "code": "invalid_argument",
                    "message": (
                        f"program_id={program_or_kind!r} not recognized. "
                        f"Use one of {list(_KIND_ALIASES.keys())} or "
                        f"{list(_VALID_KINDS)}."
                    ),
                },
                "tool_name": "find_filing_window",
                "lane_id": "N4",
                "schema_version": "moat.n4.v1",
                "_billing_unit": 1,
                "no_llm": True,
                "results": [],
            }

    path = _autonomath_db_path()
    if not path.exists():
        return {
            "error": {
                "code": "db_unavailable",
                "message": f"autonomath.db missing at {path}",
            },
            "tool_name": "find_filing_window",
            "lane_id": "N4",
            "schema_version": "moat.n4.v1",
            "_billing_unit": 1,
            "no_llm": True,
            "results": [],
        }

    conn = _open_ro(path)
    try:
        address = _lookup_houjin_address(conn, houjin_bangou)
        matches: list[dict[str, Any]] = []
        if address:
            matches = _find_windows_by_address(conn, address, kinds, limit=5)
    finally:
        conn.close()

    return {
        "tool_name": "find_filing_window",
        "lane_id": "N4",
        "schema_version": "moat.n4.v1",
        "_billing_unit": 1,
        "_disclaimer": _DISCLAIMER,
        "no_llm": True,
        "primary_input": {"program_id": program_id, "houjin_bangou": houjin_bangou},
        "resolved_kinds": list(kinds),
        "houjin_address": address,
        "matches": matches,
        "total_matches": len(matches),
        "results": matches,
    }


@mcp.tool(annotations=_READ_ONLY)
def list_windows(
    horizon_days: Annotated[
        int,
        Field(
            ge=1,
            le=365,
            description=(
                "Lookahead horizon - retained for forward compat. "
                "Not used in N4 window directory; pass any value."
            ),
        ),
    ] = 90,
    limit: Annotated[
        int,
        Field(ge=1, le=200, description="Max windows."),
    ] = 50,
    jurisdiction_kind: Annotated[
        str,
        Field(
            description=(
                f"One of: {', '.join(_VALID_KINDS)}. Default 'tax_office' for back-compat."
            ),
        ),
    ] = "tax_office",
    region_code: Annotated[
        str | None,
        Field(
            description=("Optional 5-digit national municipal code (13000=Tokyo, 27100=Osaka)."),
            max_length=8,
        ),
    ] = None,
) -> dict[str, Any]:
    """[AUDIT] Moat N4 - Enumerate windows by jurisdiction_kind.

    Reads am_window_directory (~4,700 rows). NO LLM. Single 3 JPY/req.
    """
    if jurisdiction_kind not in _VALID_KINDS:
        return {
            "error": {
                "code": "invalid_argument",
                "message": (
                    f"jurisdiction_kind={jurisdiction_kind!r} not in {list(_VALID_KINDS)}."
                ),
            },
            "tool_name": "list_windows",
            "lane_id": "N4",
            "schema_version": "moat.n4.v1",
            "_billing_unit": 1,
            "no_llm": True,
            "results": [],
        }

    limit = max(1, min(200, int(limit)))
    path = _autonomath_db_path()
    if not path.exists():
        return {
            "error": {
                "code": "db_unavailable",
                "message": f"autonomath.db missing at {path}",
            },
            "tool_name": "list_windows",
            "lane_id": "N4",
            "schema_version": "moat.n4.v1",
            "_billing_unit": 1,
            "no_llm": True,
            "results": [],
        }

    conn = _open_ro(path)
    try:
        if region_code:
            rows = conn.execute(
                "SELECT window_id, jurisdiction_kind, name, postal_address, "
                "       tel, url, jurisdiction_region_code, source_url, license "
                "  FROM am_window_directory "
                " WHERE jurisdiction_kind=? AND jurisdiction_region_code=? "
                " ORDER BY name LIMIT ?",
                (jurisdiction_kind, region_code, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT window_id, jurisdiction_kind, name, postal_address, "
                "       tel, url, jurisdiction_region_code, source_url, license "
                "  FROM am_window_directory "
                " WHERE jurisdiction_kind=? "
                " ORDER BY name LIMIT ?",
                (jurisdiction_kind, limit),
            ).fetchall()
        result_rows = [dict(r) for r in rows]
        total = conn.execute(
            "SELECT COUNT(*) FROM am_window_directory WHERE jurisdiction_kind=?",
            (jurisdiction_kind,),
        ).fetchone()[0]
    finally:
        conn.close()

    return {
        "tool_name": "list_windows",
        "lane_id": "N4",
        "schema_version": "moat.n4.v1",
        "_billing_unit": 1,
        "no_llm": True,
        "primary_input": {
            "horizon_days": horizon_days,
            "limit": limit,
            "jurisdiction_kind": jurisdiction_kind,
            "region_code": region_code,
        },
        "jurisdiction_kind": jurisdiction_kind,
        "region_code": region_code,
        "returned": len(result_rows),
        "total_kind_count": int(total),
        "results": result_rows,
    }
