"""Moat P3 — Pre-computed FAQ answer bank MCP tools (2 tools, DB-backed).

Surfaces ~5,000 pre-composed answers (5 cohort × ~1,000 FAQ) stored in
``am_precomputed_answer`` (migration ``wave24_207_am_precomputed_answer.sql``,
target_db = autonomath). Composed offline by
``scripts/aws_credit_ops/precompute_answer_composer_2026_05_17.py`` and
expanded 10x by ``precompute_answer_composer_expand_2026_05_17.py`` (GG2).
NO LLM at compose time, NO LLM at serve time.

Pre-computed answer bank: 5,000 query × 5 cohort = 25K covered scenarios.

Cohorts (5):

* ``tax``              — 税理士
* ``audit``            — 公認会計士
* ``gyousei``          — 行政書士
* ``shihoshoshi``      — 司法書士
* ``chusho_keieisha``  — 中小経営者

Tools (2)
---------

* ``search_precomputed_answers(query, cohort, limit=10)`` — FTS5 trigram
  MATCH over ``question_text + question_variants`` (+ answer_text fallback).
  Returns ranked pre-composed answers with citations + provenance.
* ``get_precomputed_answer(cohort, faq_slug)`` — O(1) fetch of a single
  pre-composed answer by ``(cohort, faq_slug)`` (or by ``question_id``).

Hard constraints
----------------

* NO LLM inference. Pure SQLite + Python.
* Every response carries the canonical §52 / §47条の2 / §72 / §1 / §3 /
  社労士法 / 行政書士法 disclaimer envelope.
* ``is_scaffold_only = 1`` and ``requires_professional_review = 1`` are
  surfaced verbatim on every result.
* Read-only SQLite connection (URI ``mode=ro``).
* Gated by ``JPCITE_MOAT_LANES_ENABLED`` (lane N10 master flag, default ON).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import DISCLAIMER, today_iso_utc

logger = logging.getLogger("jpintel.mcp.moat_lane_tools.moat_p3_precomputed_answer")

_LANE_ID = "P3"
_SCHEMA_VERSION = "moat.p3.v1"
_UPSTREAM_MODULE = "jpintel_mcp.moat.p3_precomputed_answer"

_COHORTS: tuple[str, ...] = ("tax", "audit", "gyousei", "shihoshoshi", "chusho_keieisha")
_COHORT_PATTERN = r"^(tax|audit|gyousei|shihoshoshi|chusho_keieisha|all)$"

# Allowed FTS query chars (avoid SQL/FTS injection). We strip operators / quotes
# and keep alnum + CJK + space; double quote the resulting token for phrase
# match.
_FTS_DROP = re.compile(r'[\\"*\'\\^()<>;:?!]')


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
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='am_precomputed_answer' LIMIT 1"
    ).fetchone()
    return row is not None


def _fts_present(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='am_precomputed_answer_fts' LIMIT 1"
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
            "wrap_kind": "moat_lane_p3_precomputed_answer_db",
            "observed_at": today_iso_utc(),
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }


def _safe_fts_query(query: str) -> str:
    """Sanitize free-text query for FTS5 MATCH (trigram tokenizer).

    Strips dangerous operators, splits on whitespace, wraps each token in
    double quotes for phrase match, then joins with ``OR`` for recall.
    """
    cleaned = _FTS_DROP.sub(" ", query)
    parts = [t for t in cleaned.split() if t.strip()]
    if not parts:
        return ""
    # Wrap each as phrase; tokens are kanji-heavy so trigram does the rest.
    quoted = ['"' + t.replace('"', "") + '"' for t in parts[:8]]
    return " OR ".join(quoted)


def _parse_json_array(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(decoded, list):
        return list(decoded)
    return []


def _parse_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if isinstance(decoded, dict):
        return dict(decoded)
    return {}


def _row_to_result(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "answer_id": int(row["answer_id"]),
        "cohort": row["cohort"],
        "faq_slug": row["faq_slug"],
        "question_id": row["question_id"],
        "question_text": row["question_text"],
        "question_variants": _parse_json_array(row["question_variants"]),
        "answer_text": row["answer_text"],
        "answer_md": row["answer_md"],
        "sections": _parse_json_array(row["sections_jsonb"]),
        "composed_from": _parse_json_object(row["composed_from"]),
        "citation_ids": _parse_json_array(row["citation_ids"]),
        "citation_urls": _parse_json_array(row["citation_urls"]),
        "source_citations": _parse_json_array(row["source_citations"]),
        "citation_count": int(row["citation_count"]),
        "depth_level": int(row["depth_level"]),
        "composer_version": row["composer_version"],
        "freshness_state": row["freshness_state"],
        "composed_at": row["composed_at"],
        "last_composed_at": row["last_composed_at"],
        "version_seq": int(row["version_seq"]),
        "is_scaffold_only": int(row["is_scaffold_only"]),
        "requires_professional_review": int(row["requires_professional_review"]),
        "uses_llm": int(row["uses_llm"]),
        "license": row["license"],
        "opus_baseline_jpy": int(row["opus_baseline_jpy"]),
        "jpcite_actual_jpy": int(row["jpcite_actual_jpy"]),
        "_savings_per_call_jpy": (int(row["opus_baseline_jpy"]) - int(row["jpcite_actual_jpy"])),
    }


_SELECT_COLS = """
    p.answer_id, p.cohort, p.faq_slug, p.question_id,
    p.question_text, p.question_variants, p.answer_text, p.answer_md,
    p.sections_jsonb, p.composed_from, p.citation_ids, p.citation_urls,
    p.source_citations, p.citation_count, p.depth_level, p.composer_version,
    p.freshness_state, p.composed_at, p.last_composed_at, p.version_seq,
    p.is_scaffold_only, p.requires_professional_review, p.uses_llm,
    p.license, p.opus_baseline_jpy, p.jpcite_actual_jpy
"""


@mcp.tool(annotations=_READ_ONLY)
def search_precomputed_answers(
    query: Annotated[
        str,
        Field(
            min_length=1,
            max_length=512,
            description=(
                "Free-text agent query (Japanese OK). Matched against the "
                "~5,000-row pre-composed answer bank (GG2 expansion) via "
                "FTS5 trigram. 5,000 query × 5 cohort = 25K covered scenarios."
            ),
        ),
    ],
    cohort: Annotated[
        str,
        Field(
            pattern=_COHORT_PATTERN,
            description=(
                "士業 cohort filter — 'tax' (税理士) / 'audit' (公認会計士) / "
                "'gyousei' (行政書士) / 'shihoshoshi' (司法書士) / "
                "'chusho_keieisha' (中小経営者) / 'all'."
            ),
        ),
    ] = "all",
    limit: Annotated[
        int,
        Field(ge=1, le=50, description="Max results."),
    ] = 10,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1/§3] Moat P3 search 500-row
    pre-composed FAQ answer bank by free-text agent query. Pure rule-based
    composition (NO LLM at compose or serve time). Every result carries
    citation_ids + citation_urls + source_citations + freshness_state +
    the canonical §-aware disclaimer. Returns top-N MATCH-ranked rows.
    """
    primary_input = {"query": query, "cohort": cohort, "limit": limit}
    conn = _open_ro()
    if conn is None:
        return _empty_envelope(
            tool_name="search_precomputed_answers",
            primary_input=primary_input,
            rationale="autonomath.db unreachable",
        )
    try:
        if not _table_present(conn):
            return _empty_envelope(
                tool_name="search_precomputed_answers",
                primary_input=primary_input,
                rationale=(
                    "am_precomputed_answer table missing (migration wave24_207 not applied)."
                ),
            )

        fts_q = _safe_fts_query(query)
        rows: list[sqlite3.Row] = []
        if fts_q and _fts_present(conn):
            params: list[Any] = [fts_q]
            cohort_clause = ""
            if cohort != "all":
                cohort_clause = " AND p.cohort = ?"
                params.append(cohort)
            params.append(limit)
            sql = f"""
                SELECT {_SELECT_COLS}, fts.rank AS _fts_rank
                  FROM am_precomputed_answer_fts AS fts
                  JOIN am_precomputed_answer AS p
                    ON p.answer_id = fts.answer_id
                 WHERE am_precomputed_answer_fts MATCH ?
                   {cohort_clause}
                 ORDER BY fts.rank
                 LIMIT ?
            """
            try:
                rows = list(conn.execute(sql, params).fetchall())
            except sqlite3.Error as exc:
                logger.warning("fts5 match failed (%s): %s", fts_q, exc)
                rows = []
        if not rows:
            # Fallback: LIKE on question_text + variants.
            tokens = [t for t in re.split(r"\s+", query.strip()) if t]
            if not tokens:
                return _empty_envelope(
                    tool_name="search_precomputed_answers",
                    primary_input=primary_input,
                    rationale="query token empty after sanitize",
                )
            like_clauses = " OR ".join(
                ["question_text LIKE ?", "question_variants LIKE ?", "answer_text LIKE ?"]
            )
            params2: list[Any] = []
            for t in tokens[:3]:
                params2.extend([f"%{t}%", f"%{t}%", f"%{t}%"])
            sql2 = f"""
                SELECT {_SELECT_COLS}
                  FROM am_precomputed_answer AS p
                 WHERE ({" OR ".join(["(" + like_clauses.replace("question_text", "p.question_text").replace("question_variants", "p.question_variants").replace("answer_text", "p.answer_text") + ")"] * min(3, len(tokens)))})
            """
            if cohort != "all":
                sql2 += " AND p.cohort = ?"
                params2.append(cohort)
            sql2 += " ORDER BY p.citation_count DESC, p.composed_at DESC LIMIT ?"
            params2.append(limit)
            try:
                rows = list(conn.execute(sql2, params2).fetchall())
            except sqlite3.Error as exc:
                logger.warning("like fallback failed: %s", exc)
                rows = []
    finally:
        conn.close()

    results = [_row_to_result(r) for r in rows]
    citations: list[dict[str, Any]] = []
    seen_url: set[str] = set()
    for r in results:
        for c in r["source_citations"]:
            url = c.get("source_url") if isinstance(c, dict) else None
            if url and url not in seen_url:
                seen_url.add(url)
                citations.append(c)
    return {
        "tool_name": "search_precomputed_answers",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "ok" if results else "empty",
            "lane_id": _LANE_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "rationale": "ok" if results else "no match in pre-composed answer bank",
        },
        "results": results,
        "total": len(results),
        "limit": limit,
        "offset": 0,
        "citations": citations,
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_p3_precomputed_answer_db",
            "observed_at": today_iso_utc(),
            "fts_query": fts_q if "fts_q" in locals() else "",
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }


@mcp.tool(annotations=_READ_ONLY)
def get_precomputed_answer(
    cohort: Annotated[
        str,
        Field(
            pattern=_COHORT_PATTERN,
            description=(
                "士業 cohort — 'tax' / 'audit' / 'gyousei' / 'shihoshoshi' / "
                "'chusho_keieisha' / 'all'."
            ),
        ),
    ],
    faq_slug: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            description=(
                "Canonical faq slug (e.g. 'zeirishi_q001'). Also accepted as "
                "the question_id from the originating P1 yaml."
            ),
        ),
    ],
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1/§3] Moat P3 fetch a single
    pre-composed answer by ``(cohort, faq_slug)`` (or ``question_id``).
    Returns the same envelope shape as ``search_precomputed_answers``.
    NO LLM inference. Pure SQLite read.
    """
    primary_input = {"cohort": cohort, "faq_slug": faq_slug}
    conn = _open_ro()
    if conn is None:
        return _empty_envelope(
            tool_name="get_precomputed_answer",
            primary_input=primary_input,
            rationale="autonomath.db unreachable",
        )
    try:
        if not _table_present(conn):
            return _empty_envelope(
                tool_name="get_precomputed_answer",
                primary_input=primary_input,
                rationale=(
                    "am_precomputed_answer table missing (migration wave24_207 not applied)."
                ),
            )
        params: list[Any] = []
        cohort_clause = ""
        if cohort != "all":
            cohort_clause = " AND p.cohort = ?"
            params.append(cohort)
        sql = f"""
            SELECT {_SELECT_COLS}
              FROM am_precomputed_answer AS p
             WHERE (p.faq_slug = ? OR p.question_id = ?)
                   {cohort_clause}
             ORDER BY p.version_seq DESC
             LIMIT 1
        """
        full_params = [faq_slug, faq_slug] + params
        try:
            row = conn.execute(sql, full_params).fetchone()
        except sqlite3.Error as exc:
            logger.warning("get_precomputed_answer query failed: %s", exc)
            row = None
    finally:
        conn.close()
    if row is None:
        return _empty_envelope(
            tool_name="get_precomputed_answer",
            primary_input=primary_input,
            rationale=f"no pre-composed answer for cohort={cohort} faq_slug={faq_slug}",
        )
    result = _row_to_result(row)
    return {
        "tool_name": "get_precomputed_answer",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "ok",
            "lane_id": _LANE_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "rationale": "ok",
        },
        "results": [result],
        "total": 1,
        "limit": 1,
        "offset": 0,
        "citations": result["source_citations"],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_p3_precomputed_answer_db",
            "observed_at": today_iso_utc(),
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }
