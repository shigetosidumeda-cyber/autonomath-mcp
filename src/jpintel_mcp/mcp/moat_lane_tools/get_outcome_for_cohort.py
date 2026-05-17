"""GG7 — get_outcome_for_cohort MCP tool (Tier A ¥3, DB-backed).

Surfaces one cohort-specific variant of a Wave 60-94 outcome from the
2,160-row ``am_outcome_cohort_variant`` table (migration
``wave24_221_am_outcome_cohort_variant.sql``, target_db = autonomath).
The fan-out is composed offline by
``scripts/aws_credit_ops/generate_cohort_outcome_variants_2026_05_17.py``;
no LLM at compose time, no LLM at serve time.

Tool surface
------------

* ``get_outcome_for_cohort(outcome_id, cohort)`` — O(1) fetch of a single
  cohort-specific outcome variant. Returns the gloss + next_step +
  cohort_saving_yen_per_query envelope.

Cohorts (5):

* ``zeirishi``         — 税理士
* ``kaikeishi``        — 会計士
* ``gyouseishoshi``    — 行政書士
* ``shihoshoshi``      — 司法書士
* ``chusho_keieisha``  — 中小経営者

Hard constraints
----------------

* Tier A (¥3). Pure SQLite + indexed PK lookup.
* NO LLM inference. NO HTTP. NO mutation.
* Every response carries the canonical §52 / §47条の2 / §72 / §1 / §3 /
  社労士法 disclaimer envelope.
* Read-only SQLite connection (URI ``mode=ro``).
* Gated by ``JPCITE_MOAT_LANES_ENABLED`` (lane master flag, default ON).

Description footer (FF2 narrative)
----------------------------------

Cohort-specific outcome variant: ¥3 vs ~¥300 Opus 4.7 cohort persona reasoning.
Saving: 1/100.

Registration
------------

This module is discovered by the moat-lane fragment loader
(``_fragments.load_fragments``); the YAML manifest in
``_register_fragments.yaml`` lists this module so the import
side-effect lands without editing ``__init__.py`` directly.
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

logger = logging.getLogger("jpintel.mcp.moat_lane_tools.get_outcome_for_cohort")

_LANE_ID = "GG7"
_SCHEMA_VERSION = "moat.gg7.v1"
_UPSTREAM_MODULE = "jpintel_mcp.moat.gg7_outcome_cohort_variant"
_WRAP_KIND = "moat_lane_gg7_outcome_cohort_variant_db"

# Canonical cohort enum (must match the migration CHECK constraint).
_COHORTS: tuple[str, ...] = (
    "zeirishi",
    "kaikeishi",
    "gyouseishoshi",
    "shihoshoshi",
    "chusho_keieisha",
)
_COHORT_PATTERN = r"^(zeirishi|kaikeishi|gyouseishoshi|shihoshoshi|chusho_keieisha)$"

# Wave 60-94 outcome catalog size (FF1 SOT § Wave 60-94).
_OUTCOME_ID_MAX = 432

# Cohort -> Japanese label for citations.
_COHORT_LABEL_JA: dict[str, str] = {
    "zeirishi": "税理士",
    "kaikeishi": "会計士",
    "gyouseishoshi": "行政書士",
    "shihoshoshi": "司法書士",
    "chusho_keieisha": "中小経営者",
}


def _autonomath_db_path() -> Path:
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    # moat_lane_tools/ -> mcp/ -> jpintel_mcp/ -> src/ -> repo root.
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
        "WHERE type='table' AND name='am_outcome_cohort_variant' LIMIT 1"
    ).fetchone()
    return row is not None


def _empty_envelope(
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
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }


def _row_to_result(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "variant_id": int(row["variant_id"]),
        "outcome_id": int(row["outcome_id"]),
        "cohort": str(row["cohort"]),
        "gloss": str(row["gloss"]),
        "next_step": str(row["next_step"]),
        "cohort_saving_yen_per_query": int(row["cohort_saving_yen_per_query"]),
        "computed_at": str(row["computed_at"]),
    }


@mcp.tool(annotations=_READ_ONLY)
def get_outcome_for_cohort(
    outcome_id: Annotated[
        int,
        Field(
            ge=1,
            le=_OUTCOME_ID_MAX,
            description=(
                "Wave 60-94 outcome catalog id (1..432). The catalog is "
                "published at "
                "site/releases/rc1-p0-bootstrap/outcome_catalog.json "
                "and expanded to 432 entries by the Wave 60-94 fan-out."
            ),
        ),
    ],
    cohort: Annotated[
        str,
        Field(
            pattern=_COHORT_PATTERN,
            description=(
                "士業 cohort — 'zeirishi' (税理士) / 'kaikeishi' (会計士) / "
                "'gyouseishoshi' (行政書士) / 'shihoshoshi' (司法書士) / "
                "'chusho_keieisha' (中小経営者)."
            ),
        ),
    ],
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE - SS52/SS47-2/SS72/SS1/SS3] Moat GG7 fetch one
    cohort-specific variant of a Wave 60-94 outcome. Returns the
    cohort-specific gloss (1-2 sentence viewpoint), next_step (1-2
    sentence workflow integration hint), and cohort_saving_yen_per_query
    (¥ saving / query, derived from FF1 SOT tier table). NO LLM
    inference at compose or serve time.

    Cohort-specific outcome variant: ¥3 vs ~¥300 Opus 4.7 cohort persona reasoning.
    Saving: 1/100.
    """
    primary_input = {"outcome_id": outcome_id, "cohort": cohort}
    if cohort not in _COHORTS:
        return _empty_envelope(
            tool_name="get_outcome_for_cohort",
            primary_input=primary_input,
            rationale=f"unknown cohort: {cohort}; expected one of {sorted(_COHORTS)}",
        )
    conn = _open_ro()
    if conn is None:
        return _empty_envelope(
            tool_name="get_outcome_for_cohort",
            primary_input=primary_input,
            rationale="autonomath.db unreachable",
        )
    try:
        if not _table_present(conn):
            return _empty_envelope(
                tool_name="get_outcome_for_cohort",
                primary_input=primary_input,
                rationale=(
                    "am_outcome_cohort_variant table missing (migration wave24_221 not applied)."
                ),
            )
        row = conn.execute(
            "SELECT variant_id, outcome_id, cohort, gloss, next_step, "
            "       cohort_saving_yen_per_query, computed_at "
            "  FROM am_outcome_cohort_variant "
            " WHERE outcome_id = ? AND cohort = ? "
            " LIMIT 1",
            (outcome_id, cohort),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return _empty_envelope(
            tool_name="get_outcome_for_cohort",
            primary_input=primary_input,
            rationale=(
                f"no variant for (outcome_id={outcome_id}, cohort={cohort}); "
                "run scripts/aws_credit_ops/generate_cohort_outcome_variants_2026_05_17.py"
                " to populate."
            ),
        )

    result = _row_to_result(row)
    return {
        "tool_name": "get_outcome_for_cohort",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": result,
        "results": [result],
        "total": 1,
        "limit": 1,
        "offset": 0,
        "citations": [
            {
                "kind": "cohort_label",
                "text": _COHORT_LABEL_JA.get(cohort, cohort),
            },
            {
                "kind": "outcome_id",
                "text": f"Wave 60-94 outcome #{outcome_id}",
            },
        ],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": _WRAP_KIND,
            "observed_at": today_iso_utc(),
            "computed_at": result["computed_at"],
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }


__all__ = ["get_outcome_for_cohort"]
