"""MOAT N4 - window / filing office lookup MCP tools (2026-05-17).

Two MCP tools surfacing am_window_directory (~4,700 rows) so an agent
can answer 'where to file' given houjin_bangou + program_or_kind.

* find_filing_window(houjin_bangou, program_or_kind)
* list_windows(jurisdiction_kind, region_code=None, limit=50)
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.mcp.server import mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.window_n4")

_ENABLED = (
    get_flag(
        "JPCITE_WINDOW_DIRECTORY_ENABLED",
        "AUTONOMATH_WINDOW_DIRECTORY_ENABLED",
        "1",
    )
    == "1"
)

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

_DISCLAIMER_FILING = (
    "am_window_directory (~4,700 rows) prefix match. May misfire on "
    "boundary towns or multi-jurisdiction corps. Always confirm via "
    "the source_url 1st-party page."
)


def _autonomath_db_path() -> Path:
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[4] / "autonomath.db"


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
        return make_error(
            code="db_unavailable",
            message=f"sqlite open failed: {exc}",
        )


def _lookup_houjin_address(am_conn: sqlite3.Connection, houjin_bangou: str) -> str | None:
    bangou = houjin_bangou.strip()
    if not bangou:
        return None
    row = am_conn.execute(
        "SELECT canonical_id, primary_name FROM am_entities "
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


def _list_windows_by_region(
    am_conn: sqlite3.Connection,
    kind: str,
    region_code: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    if region_code:
        rows = am_conn.execute(
            "SELECT window_id, jurisdiction_kind, name, postal_address, "
            "       tel, url, jurisdiction_region_code, source_url, license "
            "  FROM am_window_directory "
            " WHERE jurisdiction_kind=? AND jurisdiction_region_code=? "
            " ORDER BY name LIMIT ?",
            (kind, region_code, limit),
        ).fetchall()
    else:
        rows = am_conn.execute(
            "SELECT window_id, jurisdiction_kind, name, postal_address, "
            "       tel, url, jurisdiction_region_code, source_url, license "
            "  FROM am_window_directory "
            " WHERE jurisdiction_kind=? "
            " ORDER BY name LIMIT ?",
            (kind, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def _find_filing_window_impl(
    houjin_bangou: str,
    program_or_kind: str,
) -> dict[str, Any]:
    program_or_kind = program_or_kind.strip()
    kinds = _KIND_ALIASES.get(program_or_kind.lower())
    if kinds is None:
        if program_or_kind in _VALID_KINDS:
            kinds = (program_or_kind,)
        else:
            return make_error(
                code="invalid_argument",
                message=(
                    f"program_or_kind={program_or_kind!r} not recognized. "
                    f"Use one of: {list(_KIND_ALIASES.keys())} or "
                    f"{list(_VALID_KINDS)}."
                ),
            )

    path = _autonomath_db_path()
    conn_or_err = _open_ro(path)
    if isinstance(conn_or_err, dict):
        return conn_or_err
    conn = conn_or_err
    try:
        address = _lookup_houjin_address(conn, houjin_bangou)
        if not address:
            return {
                "houjin_bangou": houjin_bangou,
                "program_or_kind": program_or_kind,
                "resolved_kinds": list(kinds),
                "houjin_address": None,
                "matches": [],
                "note": (
                    "houjin_bangou unknown in am_entities - "
                    "use list_windows(kind, region_code) directly."
                ),
                "no_llm": True,
                "_disclaimer": _DISCLAIMER_FILING,
            }
        matches = _find_windows_by_address(conn, address, kinds, limit=5)
    finally:
        conn.close()

    return {
        "houjin_bangou": houjin_bangou,
        "program_or_kind": program_or_kind,
        "resolved_kinds": list(kinds),
        "houjin_address": address,
        "matches": matches,
        "total_matches": len(matches),
        "no_llm": True,
        "_disclaimer": _DISCLAIMER_FILING,
    }


def _list_windows_impl(
    jurisdiction_kind: str,
    region_code: str | None,
    limit: int,
) -> dict[str, Any]:
    if jurisdiction_kind not in _VALID_KINDS:
        return make_error(
            code="invalid_argument",
            message=(f"jurisdiction_kind={jurisdiction_kind!r} not in {list(_VALID_KINDS)}."),
        )
    limit = max(1, min(200, int(limit)))

    path = _autonomath_db_path()
    conn_or_err = _open_ro(path)
    if isinstance(conn_or_err, dict):
        return conn_or_err
    conn = conn_or_err
    try:
        rows = _list_windows_by_region(conn, jurisdiction_kind, region_code, limit)
        total = conn.execute(
            "SELECT COUNT(*) FROM am_window_directory WHERE jurisdiction_kind=?",
            (jurisdiction_kind,),
        ).fetchone()[0]
    finally:
        conn.close()

    return {
        "jurisdiction_kind": jurisdiction_kind,
        "region_code": region_code,
        "results": rows,
        "returned": len(rows),
        "total_kind_count": int(total),
        "no_llm": True,
    }


if _ENABLED:

    @mcp.tool(
        description=(
            "MOAT N4 - Resolve filing window for a corp + program. "
            "Reads am_window_directory (~4,700 rows). "
            "program_or_kind enum: tax/register/prefecture/municipal"
            "/chamber/loan/jfc/shinkin or raw jurisdiction_kind. "
            "Single 3 JPY/req. NO LLM."
        )
    )
    def find_filing_window(
        houjin_bangou: Annotated[
            str,
            Field(
                description="13-digit Japanese corporate number.",
                min_length=1,
                max_length=32,
            ),
        ],
        program_or_kind: Annotated[
            str,
            Field(
                description=("High-level kind alias OR raw jurisdiction_kind."),
                min_length=1,
                max_length=64,
            ),
        ],
    ) -> dict[str, Any]:
        return _find_filing_window_impl(houjin_bangou, program_or_kind)

    @mcp.tool(
        description=(
            "MOAT N4 - Enumerate windows by jurisdiction_kind, optionally "
            "filtered to 5-digit region_code. "
            "Single 3 JPY/req. NO LLM."
        )
    )
    def list_windows(
        jurisdiction_kind: Annotated[
            str,
            Field(
                description=f"One of: {', '.join(_VALID_KINDS)}.",
                min_length=1,
                max_length=64,
            ),
        ],
        region_code: Annotated[
            str | None,
            Field(
                description=(
                    "Optional 5-digit national municipal code (13000=Tokyo, 27100=Osaka, etc)."
                ),
                max_length=8,
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                description="Max rows to return (1..200, default 50).",
                ge=1,
                le=200,
            ),
        ] = 50,
    ) -> dict[str, Any]:
        return _list_windows_impl(jurisdiction_kind, region_code, limit)
