"""Wave-8 #1 MCP tool stub: search_acceptance_stats.

This file is a *proposed* addition to
`src/jpintel_mcp/mcp/server.py`. It is NOT wired into production — the
Wave-8 brief explicitly forbids touching production files. To apply:

    1.  Merge the `from jpintel_mcp.db.session import connect` import if not
        present (it already is in server.py).
    2.  Append the decorated function below just before the `def run() -> None`
        block near the bottom of server.py.
    3.  Run `scripts/mcp_smoke.py` + `pytest tests/mcp/` to confirm.

The tool is read-only, queries the am_acceptance_stat table that
ingest/acceptance_stats_fetch.py populates (PK = program_entity_id, round_label),
and accepts either a primary_name (fuzzy) or a unified_id.

Canonical return keys:
    program_entity_id, program_name, round_label, application_date,
    applied_count, accepted_count, acceptance_rate_pct, total_budget_yen,
    source_url, source_fetched_at
"""
from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import mcp, _READ_ONLY


@mcp.tool(annotations=_READ_ONLY)  # type: ignore[misc]
def search_acceptance_stats(
    program_name_or_id: Annotated[
        str,
        Field(
            description=(
                "Either a unified_id (UNI-… or synthetic UNI-ext-…) from "
                "search_programs, or a free-text primary_name fragment "
                "(例 '事業再構築', 'ものづくり', 'IT導入'). "
                "Free-text uses LIKE %q% against primary_name."
            ),
        ),
    ],
    round: Annotated[  # noqa: A002 — MCP surface uses "round"
        str | None,
        Field(
            description=(
                "Optional exact round label filter "
                "(例 '第12回', 'IT2024_通常_4次', 'R3_第11回'). "
                "Omit to return all rounds ordered by application_date DESC."
            ),
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, le=50, description="Max rows (default 5, max 50)."),
    ] = 5,
) -> dict[str, Any]:
    """STAT: 特定補助金の採択率 (applied / accepted / rate_pct) を round 単位で返す.

    Use when the user asks:
      - "事業再構築補助金 第12回 の採択率は?"
      - "ものづくり補助金 直近3回の採択率推移"
      - "IT導入補助金 2024 の倍率"

    Data source: am_acceptance_stat table, back-filled from official 事務局
    公募結果 PDF / HTML (source_url + source_fetched_at on every row).
    Aggregator / blog figures are intentionally excluded.

    Empty-list return = no row in table yet.  Tell the user the round has not
    been back-filled; do NOT guess.

    CHAIN:
      → get_program(unified_id) for the program metadata itself.
      → search_case_studies(program_used=primary_name) for who got accepted.
    """
    # Late import keeps this module portable when extracted for review.
    from jpintel_mcp.db.session import connect

    conn = connect()
    try:
        cur = conn.cursor()
        # Resolve program_entity_id.
        if program_name_or_id.startswith("UNI-"):
            cur.execute(
                "SELECT unified_id, primary_name FROM programs WHERE unified_id = ?",
                (program_name_or_id,),
            )
            row = cur.fetchone()
            if row is None:
                return {"program_entity_id": None, "rows": [], "not_found": True}
            uid, name = row[0], row[1]
        else:
            cur.execute(
                "SELECT p.unified_id, p.primary_name "
                "FROM programs p "
                "INNER JOIN am_acceptance_stat a ON a.program_entity_id = p.unified_id "
                "WHERE p.primary_name LIKE ? "
                "GROUP BY p.unified_id, p.primary_name "
                "ORDER BY LENGTH(p.primary_name) ASC LIMIT 1",
                (f"%{program_name_or_id}%",),
            )
            row = cur.fetchone()
            if row is None:
                return {"program_entity_id": None, "rows": [], "not_found": True}
            uid, name = row[0], row[1]

        # Fetch rounds.
        if round:
            cur.execute(
                "SELECT round_label, application_date, applied_count, "
                "accepted_count, acceptance_rate_pct, total_budget_yen, "
                "source_url, source_fetched_at "
                "FROM am_acceptance_stat "
                "WHERE program_entity_id = ? AND round_label = ? "
                "LIMIT ?",
                (uid, round, limit),
            )
        else:
            cur.execute(
                "SELECT round_label, application_date, applied_count, "
                "accepted_count, acceptance_rate_pct, total_budget_yen, "
                "source_url, source_fetched_at "
                "FROM am_acceptance_stat "
                "WHERE program_entity_id = ? "
                "ORDER BY application_date DESC LIMIT ?",
                (uid, limit),
            )
        rows = [
            {
                "round_label": r[0],
                "application_date": r[1],
                "applied_count": r[2],
                "accepted_count": r[3],
                "acceptance_rate_pct": r[4],
                "total_budget_yen": r[5],
                "source_url": r[6],
                "source_fetched_at": r[7],
            }
            for r in cur.fetchall()
        ]
        return {
            "program_entity_id": uid,
            "program_name": name,
            "rows": rows,
            "count": len(rows),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Integration patch for mcp_new/tools.py
# ---------------------------------------------------------------------------
# If the project adopts the split layout (mcp_new/tools.py aggregator), paste
# the block below into that module's `register_tools(mcp)` helper:
#
#     from .acceptance_stats_tool import search_acceptance_stats  # noqa: F401
#     # search_acceptance_stats is already decorated at import time via the
#     # injected `mcp` handle, so a single import is all that is required.
#
# No production file is modified by this stub.
