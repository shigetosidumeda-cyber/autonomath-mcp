"""Moat N2 — Houjin portfolio MCP wrappers (2 tools).

Surfaces the upstream N2 portfolio lane:

* ``get_houjin_portfolio`` — fetch the program portfolio for a houjin.
* ``find_gap_programs`` — programs the houjin should consider but is missing.

Backed by ``am_houjin_program_portfolio`` (migration
``wave24_201_am_houjin_program_portfolio.sql``) populated by
``scripts/etl/compute_portfolio_2026_05_17.py``. NO LLM inference — pure
SQLite index lookup.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import DISCLAIMER, today_iso_utc

_SCHEMA_VERSION = "moat.n2.v1"
_LANE_ID = "N2"
_UPSTREAM_MODULE = "jpintel_mcp.moat.n2_portfolio"


def _pending_envelope(
    *,
    tool_name: str,
    primary_input: dict[str, Any],
) -> dict[str, Any]:
    """Return the canonical PENDING envelope when the upstream DB is missing.

    Inlined here (not imported from ``_shared``) so the file remains
    standalone if the shared helper module is reshuffled.
    """
    return {
        "tool_name": tool_name,
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "pending_upstream_lane",
            "lane_id": _LANE_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "rationale": (
                "autonomath.db is not present at the configured path. "
                "N2 wrap returns a PENDING envelope until the DB is provisioned."
            ),
        },
        "results": [],
        "total": 0,
        "limit": 0,
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_n2_wrap",
            "observed_at": today_iso_utc(),
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
        "_pending_marker": f"PENDING {_LANE_ID}",
    }


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "program_id": row["program_id"],
        "applicability_score": round(float(row["applicability_score"]), 2),
        "score_breakdown": {
            "industry": round(float(row["score_industry"]), 2),
            "size": round(float(row["score_size"]), 2),
            "region": round(float(row["score_region"]), 2),
            "sector": round(float(row["score_sector"]), 2),
            "target_form": round(float(row["score_target_form"]), 2),
        },
        "applied_status": row["applied_status"],
        "applied_at": row["applied_at"],
        "deadline": row["deadline"],
        "deadline_kind": row["deadline_kind"],
        "priority_rank": row["priority_rank"],
        "computed_at": row["computed_at"],
    }


def _empty_envelope(
    *,
    tool_name: str,
    primary_input: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "no_portfolio_rows",
            "lane_id": _LANE_ID,
            "primary_input": primary_input,
            "rationale": reason,
        },
        "results": [],
        "total": 0,
        "limit": 0,
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "table": "am_houjin_program_portfolio",
            "observed_at": today_iso_utc(),
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }


@mcp.tool(annotations=_READ_ONLY)
def get_houjin_portfolio(
    houjin_bangou: Annotated[
        str,
        Field(min_length=13, max_length=13, description="13-digit houjin bangou."),
    ],
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE - §52/§47条の2/§72/§1] Moat N2 fetch the program portfolio
    for a houjin from the precomputed ``am_houjin_program_portfolio`` table.
    Returns the per-houjin top-N programs (priority_rank ASC) with their
    deterministic 5-axis applicability score, applied_status and deadline.
    NO LLM. Pure index lookup.
    """
    primary_input = {"houjin_bangou": houjin_bangou}
    try:
        conn = connect_autonomath("ro")
    except FileNotFoundError:
        return _pending_envelope(tool_name="get_houjin_portfolio", primary_input=primary_input)

    try:
        rows = conn.execute(
            """
            SELECT program_id, applicability_score,
                   score_industry, score_size, score_region, score_sector,
                   score_target_form, applied_status, applied_at, deadline,
                   deadline_kind, priority_rank, computed_at
              FROM am_houjin_program_portfolio
             WHERE houjin_bangou = ?
             ORDER BY priority_rank ASC NULLS LAST, applicability_score DESC
            """,
            (houjin_bangou,),
        ).fetchall()
    except sqlite3.OperationalError:
        return _pending_envelope(tool_name="get_houjin_portfolio", primary_input=primary_input)

    if not rows:
        return _empty_envelope(
            tool_name="get_houjin_portfolio",
            primary_input=primary_input,
            reason=(
                "No am_houjin_program_portfolio rows for this houjin_bangou. "
                "Either outside the precomputed cohort or ETL has not landed yet."
            ),
        )

    results = [_row_to_dict(r) for r in rows]
    applied_count = sum(1 for r in results if r["applied_status"] == "applied")
    unapplied_count = sum(1 for r in results if r["applied_status"] == "unapplied")
    unknown_count = sum(1 for r in results if r["applied_status"] == "unknown")

    return {
        "tool_name": "get_houjin_portfolio",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "ok",
            "lane_id": _LANE_ID,
            "primary_input": primary_input,
            "houjin_bangou": houjin_bangou,
            "summary": {
                "total": len(results),
                "applied": applied_count,
                "unapplied": unapplied_count,
                "unknown": unknown_count,
                "top_score": results[0]["applicability_score"] if results else None,
            },
        },
        "results": results,
        "total": len(results),
        "limit": len(results),
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "table": "am_houjin_program_portfolio",
            "method": "lane_n2_deterministic_v1",
            "observed_at": today_iso_utc(),
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }


@mcp.tool(annotations=_READ_ONLY)
def find_gap_programs(
    houjin_bangou: Annotated[
        str,
        Field(min_length=13, max_length=13, description="13-digit houjin bangou."),
    ],
    top_n: Annotated[
        int,
        Field(ge=1, le=50, description="Max gap programs to return."),
    ] = 20,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE - §52/§47条の2/§72/§1] Moat N2 surface gap programs - programs
    that match the houjin's industry / region / size profile but are NOT yet
    applied (applied_status='unapplied'). Returns the top-N by priority_rank.
    NO LLM. Pure index lookup.
    """
    primary_input = {"houjin_bangou": houjin_bangou, "top_n": top_n}
    try:
        conn = connect_autonomath("ro")
    except FileNotFoundError:
        return _pending_envelope(tool_name="find_gap_programs", primary_input=primary_input)

    try:
        rows = conn.execute(
            """
            SELECT program_id, applicability_score,
                   score_industry, score_size, score_region, score_sector,
                   score_target_form, applied_status, applied_at, deadline,
                   deadline_kind, priority_rank, computed_at
              FROM am_houjin_program_portfolio
             WHERE houjin_bangou = ?
               AND applied_status = 'unapplied'
             ORDER BY priority_rank ASC NULLS LAST, applicability_score DESC
             LIMIT ?
            """,
            (houjin_bangou, top_n),
        ).fetchall()
    except sqlite3.OperationalError:
        return _pending_envelope(tool_name="find_gap_programs", primary_input=primary_input)

    if not rows:
        return _empty_envelope(
            tool_name="find_gap_programs",
            primary_input=primary_input,
            reason=(
                "No unapplied gap programs in am_houjin_program_portfolio. "
                "Either outside cohort, all eligible already applied, or no adoption history."
            ),
        )

    results = [_row_to_dict(r) for r in rows]

    return {
        "tool_name": "find_gap_programs",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "ok",
            "lane_id": _LANE_ID,
            "primary_input": primary_input,
            "houjin_bangou": houjin_bangou,
            "summary": {
                "total_gap_programs": len(results),
                "top_score": results[0]["applicability_score"] if results else None,
                "earliest_deadline": next((r["deadline"] for r in results if r["deadline"]), None),
            },
        },
        "results": results,
        "total": len(results),
        "limit": top_n,
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "table": "am_houjin_program_portfolio",
            "method": "lane_n2_deterministic_v1",
            "observed_at": today_iso_utc(),
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }
