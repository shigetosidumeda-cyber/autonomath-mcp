"""GG4 — Pre-mapped outcome → top-100 chunk MCP tool (1 tool, DB-backed).

Surfaces the 43,200-row pre-mapped retrieval cache stored in
``am_outcome_chunk_map`` (migration ``wave24_220_am_outcome_chunk_map.sql``).
The 432 Wave 60-94 outcomes × top-100 chunks were pre-computed offline by
``scripts/aws_credit_ops/pre_map_outcomes_to_top_chunks_2026_05_17.py``
(FAISS IVF+PQ nprobe=8 retrieve top-200 → OSS BERT cross-encoder rerank
→ keep top-100). At serve time we issue a single indexed SELECT keyed on
``(outcome_id, rank)`` — no FAISS call, no cross-encoder inference, no
LLM. Expected p95: 20 ms vs ~150 ms live (~7-8x speedup).

Tool (1)
--------

* ``get_outcome_chunks(outcome_id, limit=10)`` — return the
  pre-mapped top-``limit`` chunks for an outcome. NO FAISS call.

Pricing
-------

Tier A (¥3 / 1 billing unit). Same per-call price as the live FAISS
path; the win is TTFB (-50%) and Opus 4.7 chain replacement
(¥250 → ¥3, 1/56 saving).

Hard constraints
----------------

* NO LLM inference. Pure SQLite read.
* Every response carries the canonical §52 / §47条の2 / §72 / §1 / §3
  disclaimer envelope.
* Read-only SQLite connection (URI ``mode=ro``).
* Gated by ``JPCITE_MOAT_LANES_ENABLED`` (lane master flag, default ON).

Description footer (FF2 narrative)
----------------------------------

Pre-mapped retrieval: outcome → 100 chunks pre-computed.
Saves Opus 4.7 reasoning + FAISS 50 ms × 5 calls.
¥3/req vs ~¥250 Opus chain.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import DISCLAIMER, today_iso_utc

logger = logging.getLogger("jpintel.mcp.moat_lane_tools.get_outcome_with_chunks")

_LANE_ID = "GG4"
_SCHEMA_VERSION = "moat.gg4.v1"
_UPSTREAM_MODULE = "jpintel_mcp.moat.gg4_outcome_chunk_premap"
_WRAP_KIND = "moat_lane_gg4_outcome_chunk_map_db"

# Tier A pricing — same as the FAISS live path. The win is latency,
# not unit cost.
_BILLING_UNIT = 1


def _autonomath_db_path() -> Path:
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    # moat_lane_tools/ -> mcp/ -> jpintel_mcp/ -> src/ -> repo root
    return Path(__file__).resolve().parents[4] / "autonomath.db"


def _open_ro() -> sqlite3.Connection | None:
    path = _autonomath_db_path()
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        logger.warning("autonomath.db open failed: %s", exc)
        return None


def _table_present(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='am_outcome_chunk_map' LIMIT 1"
    ).fetchone()
    return row is not None


def _empty_envelope(
    *,
    tool_name: str,
    primary_input: dict[str, Any],
    rationale: str,
) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "empty",
            "lane_id": _LANE_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "rationale": rationale,
        },
        "results": [],
        "total": 0,
        "limit": 0,
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": _WRAP_KIND,
            "observed_at": today_iso_utc(),
            "premapped": True,
            "faiss_called": False,
            "rerank_called": False,
        },
        "_billing_unit": _BILLING_UNIT,
        "_disclaimer": DISCLAIMER,
        "_pricing_tier": "A",
        "_cost_saving_note": (
            "Pre-mapped retrieval: outcome → 100 chunks pre-computed. "
            "Saves Opus 4.7 reasoning + FAISS 50ms × 5 calls. "
            "¥3/req vs ~¥250 Opus chain."
        ),
    }


def _row_to_result(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "outcome_id": int(row["outcome_id"]),
        "rank": int(row["rank"]),
        "chunk_id": int(row["chunk_id"]),
        "score": float(row["score"]),
        "mapped_at": row["mapped_at"],
    }


@mcp.tool(annotations=_READ_ONLY)
def get_outcome_chunks(
    outcome_id: Annotated[
        int,
        Field(
            ge=1,
            le=10_000,
            description=(
                "Wave 60-94 outcome catalog id (1..432 in the canonical "
                "release). The pre-mapper stores rank 1..100 per outcome."
            ),
        ),
    ],
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description=(
                "Max chunks to return. Defaults to 10; capped at 100 "
                "because the pre-mapper persists exactly the top-100 per "
                "outcome."
            ),
        ),
    ] = 10,
) -> dict[str, Any]:
    """[AUDIT] Moat GG4 pre-mapped outcome → top-100 chunk retrieval.

    Pre-mapped retrieval: outcome → 100 chunks pre-computed.
    Saves Opus 4.7 reasoning + FAISS 50ms × 5 calls.
    ¥3/req vs ~¥250 Opus chain.

    Returns the pre-mapped top-``limit`` chunks for ``outcome_id`` in
    descending score order. NO FAISS call, NO cross-encoder inference,
    NO LLM. The 43,200-row cache (432 outcomes × 100 chunks each) is
    refreshed offline by
    ``scripts/aws_credit_ops/pre_map_outcomes_to_top_chunks_2026_05_17.py``.

    Empty envelope (status=empty) is returned when the DB is
    unreachable or the migration has not been applied — never raises.
    """
    primary_input = {"outcome_id": outcome_id, "limit": limit}
    conn = _open_ro()
    if conn is None:
        return _empty_envelope(
            tool_name="get_outcome_chunks",
            primary_input=primary_input,
            rationale="autonomath.db unreachable",
        )
    try:
        if not _table_present(conn):
            return _empty_envelope(
                tool_name="get_outcome_chunks",
                primary_input=primary_input,
                rationale=(
                    "am_outcome_chunk_map table missing "
                    "(migration wave24_220 not applied)."
                ),
            )
        try:
            rows = conn.execute(
                """
                SELECT outcome_id, rank, chunk_id, score, mapped_at
                  FROM am_outcome_chunk_map
                 WHERE outcome_id = ?
                 ORDER BY rank ASC
                 LIMIT ?
                """,
                (outcome_id, limit),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("get_outcome_chunks select failed: %s", exc)
            rows = []
    finally:
        conn.close()

    if not rows:
        return _empty_envelope(
            tool_name="get_outcome_chunks",
            primary_input=primary_input,
            rationale=f"no pre-mapped chunks for outcome_id={outcome_id}",
        )

    results = [_row_to_result(r) for r in rows]
    return {
        "tool_name": "get_outcome_chunks",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "ok",
            "lane_id": _LANE_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "rationale": "ok",
        },
        "results": results,
        "total": len(results),
        "limit": limit,
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": _WRAP_KIND,
            "observed_at": today_iso_utc(),
            "premapped": True,
            "faiss_called": False,
            "rerank_called": False,
        },
        "_billing_unit": _BILLING_UNIT,
        "_disclaimer": DISCLAIMER,
        "_pricing_tier": "A",
        "_cost_saving_note": (
            "Pre-mapped retrieval: outcome → 100 chunks pre-computed. "
            "Saves Opus 4.7 reasoning + FAISS 50ms × 5 calls. "
            "¥3/req vs ~¥250 Opus chain."
        ),
    }
