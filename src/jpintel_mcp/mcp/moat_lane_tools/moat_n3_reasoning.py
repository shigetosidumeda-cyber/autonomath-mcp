"""Moat N3 — Legal reasoning chain MCP wrappers (2 tools, DB-backed).

Surfaces the upstream N3 legal reasoning chain lane (160 topics × 5 viewpoint
slices = 800 chains, deterministic rule-engine composition, NO LLM):

* ``get_reasoning_chain`` — fetch one or more deterministic reasoning chains
  by ``topic_id`` (full LRC-* id or topic slug). Returns the 三段論法
  (大前提 = 法令条文 + 通達, 小前提 = 判例 + 採決, 結論 = 学説 + 実務)
  with confidence + opposing-view text + citation triple.
* ``walk_reasoning_chain`` — keyword-driven walk over the chain corpus
  bound by topic category. Pure SQLite SELECT.

Backed by ``autonomath.db :: am_legal_reasoning_chain`` (migration
``wave24_202_am_legal_reasoning_chain.sql``). Pure logic, no LLM inference,
no HTTP. §52 / §47条の2 / §72 / §1 / §3 sensitive surface — every response
carries the canonical disclaimer envelope.

Cost posture: 1 ¥3 billable unit per call, pure SQLite, zero AWS side-effect.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import DISCLAIMER, today_iso_utc

if TYPE_CHECKING:
    from collections.abc import Iterable

_SCHEMA_VERSION = "moat.n3.v1"
_LANE_ID = "N3"
_UPSTREAM_MODULE = "jpintel_mcp.moat.n3_reasoning"

# Closed taxonomy of allowed tax_category values (mirrors the migration's
# CHECK constraint).
_ALLOWED_CATEGORIES: frozenset[str] = frozenset(
    {
        "corporate_tax",
        "consumption_tax",
        "income_tax",
        "subsidy",
        "labor",
        "commerce",
        "other",
    }
)


def _autonomath_db_path() -> Path:
    """Return the canonical path to autonomath.db.

    Production reads from the repo-root path (see CLAUDE.md note about
    ``data/autonomath.db`` being a 0-byte placeholder); the settings field is
    the authoritative knob.
    """
    return Path(settings.autonomath_db_path)


def _open_ro_conn() -> sqlite3.Connection:
    """Open a read-only connection to autonomath.db.

    Uses the URI form so the file is opened with ``mode=ro`` — defense in
    depth against accidental writes from the MCP read-only tool surface.
    """
    db_path = _autonomath_db_path().resolve()
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_chain(row: sqlite3.Row) -> dict[str, Any]:
    """Materialize one ``am_legal_reasoning_chain`` row into the response shape."""
    try:
        premise_law_article_ids = json.loads(row["premise_law_article_ids"] or "[]")
    except (json.JSONDecodeError, TypeError):
        premise_law_article_ids = []
    try:
        premise_tsutatsu_ids = json.loads(row["premise_tsutatsu_ids"] or "[]")
    except (json.JSONDecodeError, TypeError):
        premise_tsutatsu_ids = []
    try:
        minor_premise_judgment_ids = json.loads(row["minor_premise_judgment_ids"] or "[]")
    except (json.JSONDecodeError, TypeError):
        minor_premise_judgment_ids = []
    try:
        citations = json.loads(row["citations"] or "{}")
    except (json.JSONDecodeError, TypeError):
        citations = {}
    return {
        "chain_id": row["chain_id"],
        "topic_id": row["topic_id"],
        "topic_label": row["topic_label"],
        "tax_category": row["tax_category"],
        "premise_law_article_ids": premise_law_article_ids,
        "premise_tsutatsu_ids": premise_tsutatsu_ids,
        "minor_premise_judgment_ids": minor_premise_judgment_ids,
        "conclusion_text": row["conclusion_text"],
        "confidence": float(row["confidence"] or 0.0),
        "opposing_view_text": row["opposing_view_text"],
        "citations": citations,
        "computed_by_model": row["computed_by_model"],
        "computed_at": row["computed_at"],
    }


def _aggregate_citations(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten the per-chain citation envelopes into a single citation list."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for chain in rows:
        cites = chain.get("citations", {})
        if not isinstance(cites, dict):
            continue
        for kind in ("law", "tsutatsu", "hanrei", "saiketsu"):
            entries = cites.get(kind, []) or []
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                source_url = entry.get("source_url") or entry.get("unified_id") or ""
                key = (kind, str(source_url) or json.dumps(entry, sort_keys=True))
                if key in seen:
                    continue
                seen.add(key)
                out.append({"kind": kind, **entry})
    return out


def _build_envelope(
    *,
    tool_name: str,
    primary_input: dict[str, Any],
    rows: list[dict[str, Any]],
    total_available: int,
) -> dict[str, Any]:
    """Common envelope for both N3 MCP wrappers."""
    return {
        "tool_name": tool_name,
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "ok" if rows else "no_match",
            "lane_id": _LANE_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "chains": rows,
        },
        "results": rows,
        "total": total_available,
        "limit": len(rows),
        "offset": 0,
        "citations": _aggregate_citations(rows),
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_n10_wrap",
            "observed_at": today_iso_utc(),
            "computed_by_model": "rule_engine_v1",
            "db_table": "am_legal_reasoning_chain",
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }


@mcp.tool(annotations=_READ_ONLY)
def get_reasoning_chain(
    topic: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            description=(
                "Either a full ``LRC-<10 hex>`` chain id (returns 1 chain) or "
                "a canonical topic slug like ``corporate_tax:yakuin_hosyu`` / "
                "``consumption_tax:shiire_kojo`` / "
                "``subsidy:keizai_gouriseii`` / ``labor:rodo_jikan`` / "
                "``commerce:yakuin_sennin`` (returns all 5 viewpoint slices)."
            ),
        ),
    ],
    limit: Annotated[
        int,
        Field(ge=1, le=50, description="Max chains to return."),
    ] = 10,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1/§3] Moat N3 fetch deterministic
    reasoning chains by topic_id or chain_id (rule tree + premise + conclusion).
    NO LLM inference — chains are precomputed by a pure-Python rule engine over
    法令 + 通達 + 判例 + 採決. 160 topics × 5 viewpoint slices = 800 chains.
    """
    primary_input = {"topic": topic, "limit": limit}
    try:
        with _open_ro_conn() as conn:
            cur = conn.cursor()
            if topic.startswith("LRC-"):
                cur.execute(
                    """
                    SELECT chain_id, topic_id, topic_label, tax_category,
                           premise_law_article_ids, premise_tsutatsu_ids,
                           minor_premise_judgment_ids, conclusion_text,
                           confidence, opposing_view_text, citations,
                           computed_by_model, computed_at
                      FROM am_legal_reasoning_chain
                     WHERE chain_id = ?
                     LIMIT 1
                    """,
                    (topic,),
                )
                rows = [_row_to_chain(r) for r in cur.fetchall()]
                total = len(rows)
            else:
                cur.execute(
                    """
                    SELECT chain_id, topic_id, topic_label, tax_category,
                           premise_law_article_ids, premise_tsutatsu_ids,
                           minor_premise_judgment_ids, conclusion_text,
                           confidence, opposing_view_text, citations,
                           computed_by_model, computed_at
                      FROM am_legal_reasoning_chain
                     WHERE topic_id = ?
                     ORDER BY confidence DESC, chain_id
                     LIMIT ?
                    """,
                    (topic, limit),
                )
                rows = [_row_to_chain(r) for r in cur.fetchall()]
                cur.execute(
                    ("SELECT COUNT(*) AS n FROM am_legal_reasoning_chain WHERE topic_id = ?"),
                    (topic,),
                )
                total_row = cur.fetchone()
                total = int(total_row["n"] if total_row else len(rows))
        return _build_envelope(
            tool_name="get_reasoning_chain",
            primary_input=primary_input,
            rows=rows,
            total_available=total,
        )
    except sqlite3.Error as exc:
        return _build_envelope(
            tool_name="get_reasoning_chain",
            primary_input={**primary_input, "error": str(exc)},
            rows=[],
            total_available=0,
        )


@mcp.tool(annotations=_READ_ONLY)
def walk_reasoning_chain(
    query: Annotated[
        str,
        Field(
            min_length=1,
            max_length=256,
            description=(
                "Free-text keyword(s) — searched against topic_label / "
                "conclusion_text / opposing_view_text via LIKE. Case-insensitive."
            ),
        ),
    ],
    category: Annotated[
        str,
        Field(
            pattern=(
                "^(corporate_tax|consumption_tax|income_tax|subsidy|labor|commerce|other|all)$"
            ),
            description=(
                "Restrict the walk to one tax_category, or ``all`` to span every category."
            ),
        ),
    ] = "all",
    min_confidence: Annotated[
        float,
        Field(ge=0.0, le=1.0, description="Min confidence threshold."),
    ] = 0.6,
    limit: Annotated[
        int,
        Field(ge=1, le=50, description="Max chains to return."),
    ] = 10,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1/§3] Moat N3 walk the reasoning
    chain corpus by keyword + optional category filter. Pure SQLite SELECT, NO
    LLM. Returns chains ranked by confidence DESC.
    """
    primary_input = {
        "query": query,
        "category": category,
        "min_confidence": min_confidence,
        "limit": limit,
    }
    pattern = f"%{query}%"
    try:
        with _open_ro_conn() as conn:
            cur = conn.cursor()
            select_clause = """
                SELECT chain_id, topic_id, topic_label, tax_category,
                       premise_law_article_ids, premise_tsutatsu_ids,
                       minor_premise_judgment_ids, conclusion_text,
                       confidence, opposing_view_text, citations,
                       computed_by_model, computed_at
            """
            count_clause = "SELECT COUNT(*) AS n"
            where_clause = """
                  FROM am_legal_reasoning_chain
                 WHERE (
                       topic_label LIKE ? COLLATE NOCASE
                    OR conclusion_text LIKE ? COLLATE NOCASE
                    OR (opposing_view_text IS NOT NULL
                        AND opposing_view_text LIKE ? COLLATE NOCASE)
                    OR topic_id LIKE ? COLLATE NOCASE
                 )
                   AND confidence >= ?
            """
            params: list[Any] = [pattern, pattern, pattern, pattern, min_confidence]
            if category != "all" and category in _ALLOWED_CATEGORIES:
                where_clause += " AND tax_category = ?"
                params.append(category)
            # SELECT rows
            select_sql = (
                select_clause + where_clause + " ORDER BY confidence DESC, chain_id LIMIT ?"
            )
            select_params = [*params, limit]
            cur.execute(select_sql, select_params)
            rows = [_row_to_chain(r) for r in cur.fetchall()]
            # COUNT (no LIMIT)
            count_sql = count_clause + where_clause
            cur.execute(count_sql, params)
            total_row = cur.fetchone()
            total = int(total_row["n"] if total_row else len(rows))
        return _build_envelope(
            tool_name="walk_reasoning_chain",
            primary_input=primary_input,
            rows=rows,
            total_available=total,
        )
    except sqlite3.Error as exc:
        return _build_envelope(
            tool_name="walk_reasoning_chain",
            primary_input={**primary_input, "error": str(exc)},
            rows=[],
            total_available=0,
        )
