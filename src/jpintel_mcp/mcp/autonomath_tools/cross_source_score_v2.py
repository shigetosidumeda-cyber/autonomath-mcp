"""cross_source_score_v2 — MCP wrapper for the per-fact agreement signal.

Wave 43.2.9 Dim I — exposes a single read-only MCP tool that consumer
LLMs can call to learn HOW STRONGLY a (entity_id, field_name) fact is
corroborated across first-party government sources (e-Gov / NTA / METI /
other).

Tool registered at import time when both
``AUTONOMATH_CROSS_SOURCE_SCORE_V2_ENABLED`` (default ON) and
``settings.autonomath_enabled`` are truthy:

  * ``cross_source_score_am``
      Returns the precomputed row from ``am_fact_source_agreement``
      (migration 265) via view ``v_fact_source_agreement``, joined with
      the canonical_value + per-source value breakdown and the derived
      ``confidence_band``.

Hard constraints:

  * NO LLM call. Pure SQLite SELECT (one-row keyed lookup) + Python
    dict shaping.
  * Single-DB: reads only autonomath.db; jpintel.db is not touched.
  * Sensitive — disclaim that agreement does NOT prove correctness.
  * 1 unit billing (¥3 / 3.30 incl tax).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error
from .snapshot_helper import attach_corpus_snapshot

logger = logging.getLogger("jpintel.mcp.autonomath.cross_source_score_v2")

_ENABLED = os.environ.get("AUTONOMATH_CROSS_SOURCE_SCORE_V2_ENABLED", "1") == "1"


_DISCLAIMER = (
    "本 agreement_ratio は autonomath.am_fact_source_agreement (migration "
    "265) の機械集計で、複数 source の値一致は必ずしも正しさを保証しません"
    "(上流ドラフトの孫引きが揃う事例を含む)。確定判断は canonical_value と"
    "各 source の一次資料 URL で必ず原典確認をお願いします。"
)


def _open_autonomath_safe() -> sqlite3.Connection | dict[str, Any]:
    """Open autonomath.db. Returns conn or error envelope on failure."""
    path = os.environ.get("AUTONOMATH_DB_PATH", str(settings.autonomath_db_path))
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
            retry_with=["list_open_programs"],
        )


def _validate_fact_id(fact_id: Any) -> int | dict[str, Any]:
    try:
        fid = int(fact_id)
    except (TypeError, ValueError):
        return make_error(
            code="invalid_input",
            message="fact_id must be a non-negative integer",
            field="fact_id",
        )
    if fid < 0 or fid > 10**18:
        return make_error(
            code="out_of_range",
            message="fact_id must be in [0, 10^18)",
            field="fact_id",
        )
    return fid


def _cross_source_score_am_impl(fact_id: Any) -> dict[str, Any]:
    """Compose the per-fact agreement bundle in-process. Pure SQLite."""
    parsed = _validate_fact_id(fact_id)
    if isinstance(parsed, dict):
        return parsed
    fid = parsed

    conn_or_err = _open_autonomath_safe()
    if isinstance(conn_or_err, dict):
        return conn_or_err
    conn = conn_or_err
    try:
        row = conn.execute(
            """SELECT fact_id, entity_id, field_name,
                      agreement_ratio, sources_total, sources_agree,
                      canonical_value, source_breakdown,
                      egov_value, nta_value, meti_value, other_value,
                      computed_at, confidence_band
                 FROM v_fact_source_agreement
                WHERE fact_id = ?""",
            (fid,),
        ).fetchone()
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"agreement query failed: {exc}",
            field="fact_id",
        )
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    if row is None:
        return make_error(
            code="not_found",
            message=(
                "fact_id has not been scored by the cross-source agreement"
                " cron yet. Either the fact does not exist or the next"
                " hourly pass has not landed it."
            ),
            field="fact_id",
        )

    try:
        breakdown = json.loads(row["source_breakdown"] or "{}")
        if not isinstance(breakdown, dict):
            breakdown = {}
    except (json.JSONDecodeError, TypeError):
        breakdown = {}

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
            k: int(v) for k, v in breakdown.items() if isinstance(v, (int, float))
        },
        "per_source_values": {
            "egov": row["egov_value"],
            "nta": row["nta_value"],
            "meti": row["meti_value"],
            "other": row["other_value"],
        },
        "computed_at": row["computed_at"],
        "_billing_unit": 1,
        "_disclaimer": _DISCLAIMER,
    }
    attach_corpus_snapshot(body)
    return body


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def cross_source_score_am(
        fact_id: Annotated[
            int,
            Field(
                description=(
                    "fact_id (am_entity_facts.id, numeric). Obtain from "
                    "`facts.search_*` tools or the `/v1/facts/...` REST "
                    "surface."
                ),
                ge=0,
                le=10**18,
            ),
        ],
    ) -> dict[str, Any]:
        """[CROSS-SOURCE] fact_id ごとの cross-source agreement score (0.0..1.0) を 1 call で返す。複数の一次資料 (e-Gov / NTA / METI / other) が同じ値を支持している割合 (agreement_ratio) + canonical_value + 各 source の値 (per_source_values) + 派生 confidence_band ('high'/'medium'/'low'/'unknown') を含む。NO LLM、純粋 SQLite。1 unit billing。出力 agreement_ratio が高くても上流ドラフトの孫引き集中の可能性があるため、最終判断は各 source_url の原典確認が必須。"""
        return _cross_source_score_am_impl(fact_id=fact_id)


__all__ = [
    "_cross_source_score_am_impl",
]
