"""Moat N1 — Artifact template bank MCP tools (2 tools, real DB-backed).

Surfaces the implementation成果物テンプレート bank stored in
``am_artifact_templates`` (migration ``wave24_200_am_artifact_templates.sql``,
target_db = autonomath). 50 templates across 5 士業 × 10 種類:

* 税理士 / 会計士 / 行政書士 / 司法書士 / 社労士 segments
* Each segment carries 10 distinct artifact_type rows

Tools
-----

* ``get_artifact_template(segment, artifact_type)`` — fetch one template
  (sections / placeholders / mcp_query_bindings) by segment +
  artifact_type. Picks the latest version row.
* ``list_artifact_templates(segment="all")`` — enumerate available
  template summaries (segment / artifact_type / artifact_name_ja /
  authority / sensitive_act / quality_grade). Filter by segment, or
  ``"all"`` for every segment.

Hard constraints
----------------

* NO LLM inference. Pure SQLite + Python.
* Every response carries a ``_disclaimer`` envelope referencing the
  five regulated 士業 (§52 / §47条の2 / §72 / §1 / §3 / 社労士法 / 行政書士法)
  because the templates are scaffolds, not legally certified deliverables.
* Templates are ``is_scaffold_only = 1`` + ``requires_professional_review = 1``
  by construction; the tool surfaces those flags so agents cannot mistake
  the response for a finished filing.
* Read-only SQLite connection (URI mode ``ro``).
* Gated by the lane N10 master flag ``JPCITE_MOAT_LANES_ENABLED`` (default ON).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import DISCLAIMER, today_iso_utc

logger = logging.getLogger("jpintel.mcp.moat_lane_tools.moat_n1_artifact")

_SEGMENTS_JA = ("税理士", "会計士", "行政書士", "司法書士", "社労士")
_SEGMENT_PATTERN = r"^(税理士|会計士|行政書士|司法書士|社労士|all)$"
_LANE_ID = "N1"
_SCHEMA_VERSION = "moat.n1.v1"
_UPSTREAM_MODULE = "jpintel_mcp.moat.n1_artifact"


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
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='am_artifact_templates' LIMIT 1"
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
            "wrap_kind": "moat_lane_n1_artifact_db",
            "observed_at": today_iso_utc(),
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }


def _parse_jsonb(raw: str | None) -> Any:
    if raw is None or raw == "":
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        logger.warning("artifact_template jsonb parse failed: %s", exc)
        return None


@mcp.tool(annotations=_READ_ONLY)
def get_artifact_template(
    segment: Annotated[
        str,
        Field(
            pattern=_SEGMENT_PATTERN,
            description=("士業 segment (税理士 / 会計士 / 行政書士 / 司法書士 / 社労士)."),
        ),
    ],
    artifact_type: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            description=("artifact type slug, e.g. 'gessji_shiwake' / 'shuugyou_kisoku'."),
        ),
    ],
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1/§3] Moat N1 fetch a single
    artifact-template scaffold by segment + artifact_type. Returns the latest
    version row from ``am_artifact_templates`` with structure / placeholders /
    mcp_query_bindings hydrated. Scaffold-only — every response carries
    ``is_scaffold_only=1`` + ``requires_professional_review=1`` flags and the
    canonical 士業 disclaimer. NO LLM inference.
    """
    primary_input = {"segment": segment, "artifact_type": artifact_type}
    if segment == "all":
        return _empty_envelope(
            tool_name="get_artifact_template",
            primary_input=primary_input,
            rationale="get_artifact_template requires a concrete segment; 'all' is reserved for list_artifact_templates.",
        )
    conn = _open_ro()
    if conn is None:
        return _empty_envelope(
            tool_name="get_artifact_template",
            primary_input=primary_input,
            rationale="autonomath.db unreachable",
        )
    try:
        if not _table_present(conn):
            return _empty_envelope(
                tool_name="get_artifact_template",
                primary_input=primary_input,
                rationale="am_artifact_templates table missing (migration wave24_200 not applied).",
            )
        row = conn.execute(
            """
            SELECT template_id, segment, artifact_type, artifact_name_ja,
                   version, authority, sensitive_act,
                   is_scaffold_only, requires_professional_review,
                   uses_llm, quality_grade,
                   structure_jsonb, placeholders_jsonb, mcp_query_bindings_jsonb,
                   license, notes, updated_at
              FROM am_artifact_templates
             WHERE segment = ? AND artifact_type = ?
             ORDER BY version DESC
             LIMIT 1
            """,
            (segment, artifact_type),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return _empty_envelope(
            tool_name="get_artifact_template",
            primary_input=primary_input,
            rationale=(f"no template found for segment={segment} artifact_type={artifact_type}"),
        )
    template = {
        "template_id": int(row["template_id"]),
        "segment": row["segment"],
        "artifact_type": row["artifact_type"],
        "artifact_name_ja": row["artifact_name_ja"],
        "version": row["version"],
        "authority": row["authority"],
        "sensitive_act": row["sensitive_act"],
        "is_scaffold_only": bool(row["is_scaffold_only"]),
        "requires_professional_review": bool(row["requires_professional_review"]),
        "uses_llm": bool(row["uses_llm"]),
        "quality_grade": row["quality_grade"],
        "structure": _parse_jsonb(row["structure_jsonb"]),
        "placeholders": _parse_jsonb(row["placeholders_jsonb"]),
        "mcp_query_bindings": _parse_jsonb(row["mcp_query_bindings_jsonb"]),
        "license": row["license"],
        "notes": row["notes"],
        "updated_at": row["updated_at"],
    }
    return {
        "tool_name": "get_artifact_template",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": template,
        "results": [template],
        "total": 1,
        "limit": 1,
        "offset": 0,
        "citations": [
            {
                "kind": "authority",
                "text": row["authority"],
            },
            {
                "kind": "sensitive_act",
                "text": row["sensitive_act"],
            },
        ],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_n1_artifact_db",
            "observed_at": today_iso_utc(),
            "row_count": 1,
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }


@mcp.tool(annotations=_READ_ONLY)
def list_artifact_templates(
    segment: Annotated[
        str,
        Field(
            pattern=_SEGMENT_PATTERN,
            description=("Segment filter (税理士 / 会計士 / 行政書士 / 司法書士 / 社労士 / all)."),
        ),
    ] = "all",
    limit: Annotated[
        int,
        Field(ge=1, le=100, description="Max template summaries to return."),
    ] = 50,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1/§3] Moat N1 enumerate artifact
    templates by segment. Returns lightweight summaries (segment / artifact_type
    / artifact_name_ja / authority / sensitive_act / quality_grade / version /
    updated_at). Filter by 士業 segment or pass ``"all"`` for the full catalog.
    Scaffold-only catalog — sections / placeholders payload available via
    ``get_artifact_template``.
    """
    primary_input = {"segment": segment, "limit": limit}
    conn = _open_ro()
    if conn is None:
        return _empty_envelope(
            tool_name="list_artifact_templates",
            primary_input=primary_input,
            rationale="autonomath.db unreachable",
        )
    try:
        if not _table_present(conn):
            return _empty_envelope(
                tool_name="list_artifact_templates",
                primary_input=primary_input,
                rationale="am_artifact_templates table missing (migration wave24_200 not applied).",
            )
        if segment == "all":
            cursor = conn.execute(
                """
                SELECT template_id, segment, artifact_type, artifact_name_ja,
                       version, authority, sensitive_act, quality_grade,
                       is_scaffold_only, requires_professional_review,
                       updated_at
                  FROM am_artifact_templates
                 ORDER BY segment ASC, artifact_type ASC
                 LIMIT ?
                """,
                (limit,),
            )
        else:
            cursor = conn.execute(
                """
                SELECT template_id, segment, artifact_type, artifact_name_ja,
                       version, authority, sensitive_act, quality_grade,
                       is_scaffold_only, requires_professional_review,
                       updated_at
                  FROM am_artifact_templates
                 WHERE segment = ?
                 ORDER BY artifact_type ASC
                 LIMIT ?
                """,
                (segment, limit),
            )
        rows = cursor.fetchall()
    finally:
        conn.close()
    summaries: list[dict[str, Any]] = [
        {
            "template_id": int(r["template_id"]),
            "segment": r["segment"],
            "artifact_type": r["artifact_type"],
            "artifact_name_ja": r["artifact_name_ja"],
            "version": r["version"],
            "authority": r["authority"],
            "sensitive_act": r["sensitive_act"],
            "quality_grade": r["quality_grade"],
            "is_scaffold_only": bool(r["is_scaffold_only"]),
            "requires_professional_review": bool(r["requires_professional_review"]),
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]
    return {
        "tool_name": "list_artifact_templates",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "segment": segment,
            "count": len(summaries),
        },
        "results": summaries,
        "total": len(summaries),
        "limit": limit,
        "offset": 0,
        "citations": [
            {
                "kind": "lane_catalog",
                "text": "5 士業 × 10 種類 = 50 scaffold templates",
            }
        ],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_n1_artifact_db",
            "observed_at": today_iso_utc(),
            "row_count": len(summaries),
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }


__all__ = [
    "get_artifact_template",
    "list_artifact_templates",
]


# Module-level sanity probe: assert that the segment whitelist mirrors the
# 5 士業 cohort exactly (catches accidental drift in future patches).
assert set(_SEGMENTS_JA) == {"税理士", "会計士", "行政書士", "司法書士", "社労士"}
