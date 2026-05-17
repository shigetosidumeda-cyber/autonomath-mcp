"""Moat N5 - Synonym / alias resolver MCP wrapper (1 tool, LIVE 2026-05-17).

Surfaces am_alias (~433K rows) as a deterministic
surface_text -> canonical_id_list resolver. Two stages: exact + NFKC.

NO LLM, NO HTTP, sub-millisecond btree lookup.
"""

from __future__ import annotations

import logging
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

logger = logging.getLogger("jpintel.mcp.moat_lane_tools.moat_n5_synonym")

_VALID_ENTITY_TABLES: tuple[str, ...] = (
    "am_entities",
    "am_authority",
    "am_law",
    "am_industry_jsic",
    "am_region",
    "am_target_profile",
)

# UI kinds -> backing entity_table filter
_KIND_TO_ENTITY_TABLES: dict[str, tuple[str, ...]] = {
    "all": _VALID_ENTITY_TABLES,
    "program": ("am_entities",),
    "law": ("am_law",),
    "case": ("am_entities",),
    "houjin": ("am_entities",),
}

_MAX_LIMIT = 50
_DISCLAIMER = (
    "am_alias (~433K rows) exact + NFKC resolver. NOT legal advice. "
    "Returns canonical_id list; downstream tools (search_by_law / "
    "get_law_article_am etc.) supply the body."
)


def _autonomath_db_path() -> Path:
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[4] / "autonomath.db"


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


@mcp.tool(annotations=_READ_ONLY)
def resolve_alias(
    surface: Annotated[
        str,
        Field(min_length=1, max_length=256, description="Surface alias text."),
    ],
    kind: Annotated[
        str,
        Field(
            pattern="^(program|law|case|houjin|all)$",
            description="Entity kind filter.",
        ),
    ] = "all",
) -> dict[str, Any]:
    """[AUDIT] Moat N5 - Resolve surface text to canonical_id[].

    Uses am_alias (~433K rows). Two-stage: exact -> NFKC. NO LLM.
    """
    started = time.perf_counter()
    text = surface.strip()
    if not text:
        return {
            "error": {
                "code": "invalid_argument",
                "message": "surface must be non-empty after strip().",
            },
            "tool_name": "resolve_alias",
            "lane_id": "N5",
            "schema_version": "moat.n5.v1",
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
            "tool_name": "resolve_alias",
            "lane_id": "N5",
            "schema_version": "moat.n5.v1",
            "_billing_unit": 1,
            "no_llm": True,
            "results": [],
        }

    tables = _KIND_TO_ENTITY_TABLES.get(kind, _VALID_ENTITY_TABLES)
    normalized = _normalize(text)
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in tables)
        # Stage 1: exact match
        cursor = conn.execute(
            f"SELECT entity_table, canonical_id, alias, alias_kind, language "
            f"FROM am_alias "
            f"WHERE alias = ? AND entity_table IN ({placeholders}) LIMIT ?",
            (text, *tables, _MAX_LIMIT),
        )
        for row in cursor:
            key = (str(row["entity_table"]), str(row["canonical_id"]), str(row["alias"]))
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "entity_table": str(row["entity_table"]),
                    "canonical_id": str(row["canonical_id"]),
                    "alias_hit": str(row["alias"]),
                    "alias_kind": str(row["alias_kind"]),
                    "language": str(row["language"]) if row["language"] else "ja",
                    "confidence": 1.0,
                    "match_stage": "exact",
                }
            )

        # Stage 2: NFKC fallback
        if len(results) < _MAX_LIMIT and normalized != text:
            remaining = _MAX_LIMIT - len(results)
            cursor = conn.execute(
                f"SELECT entity_table, canonical_id, alias, alias_kind, language "
                f"FROM am_alias "
                f"WHERE alias = ? AND entity_table IN ({placeholders}) LIMIT ?",
                (normalized, *tables, remaining),
            )
            for row in cursor:
                key = (str(row["entity_table"]), str(row["canonical_id"]), str(row["alias"]))
                if key in seen:
                    continue
                seen.add(key)
                results.append(
                    {
                        "entity_table": str(row["entity_table"]),
                        "canonical_id": str(row["canonical_id"]),
                        "alias_hit": str(row["alias"]),
                        "alias_kind": str(row["alias_kind"]),
                        "language": str(row["language"]) if row["language"] else "ja",
                        "confidence": 0.9,
                        "match_stage": "nfkc",
                    }
                )
    finally:
        conn.close()

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "tool_name": "resolve_alias",
        "lane_id": "N5",
        "schema_version": "moat.n5.v1",
        "_billing_unit": 1,
        "_disclaimer": _DISCLAIMER,
        "no_llm": True,
        "primary_input": {"surface": surface[:128], "kind": kind},
        "query": text,
        "normalized": normalized,
        "results": results,
        "total": len(results),
        "elapsed_ms": round(elapsed_ms, 2),
    }
