"""Shared core for the 5 HE-5 cohort-specific deep-research endpoints."""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from pathlib import Path
from typing import Any

from jpintel_mcp._jpcite_env_bridge import get_flag

from .._shared import DISCLAIMER, today_iso_utc
from .._shared_cohort import (
    COHORT_DEADLINES,
    COHORT_FORMS,
    COHORT_IDS,
    COHORT_LABELS_JA,
    COHORT_PERSONA_STYLE,
    COHORT_PITFALLS,
    COHORT_PRACTICAL_STEPS,
    COHORT_REGULATED_ACTS,
    cohort_terminology_hydrate,
    he5_cost_saving_footer,
)

logger = logging.getLogger("jpintel.mcp.moat_lane_tools.he5_cohort_deep._core")

HE5_UNITS = 10
HE5_YEN = 30
HE5_LANE_ID = "HE5"
HE5_SCHEMA_VERSION = "moat.he5.v1"

HE5_SECTIONS: tuple[str, ...] = (
    "issue",
    "context",
    "cohort_law_citations",
    "practical_steps",
    "pitfalls",
    "forms",
    "deadlines",
    "cite_list",
)


def _autonomath_db_path() -> Path:
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[5] / "autonomath.db"


def _open_ro() -> sqlite3.Connection | None:
    path = _autonomath_db_path()
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        logger.debug("HE5 autonomath.db open failed: %s", exc)
        return None


def _table_present(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (name,),
    )
    return cur.fetchone() is not None


def _safe_like_token(query: str) -> str:
    return query.replace("%", "\\%").replace("_", "\\_")


def _build_issue(cohort: str, query: str) -> str:
    label = COHORT_LABELS_JA.get(cohort, cohort)
    return f"対象 cohort: {label}\nIssue: {query}"


def _build_context(cohort: str, entity_id: str | None, context_token: str | None) -> str:
    label = COHORT_LABELS_JA.get(cohort, cohort)
    acts = "・".join(COHORT_REGULATED_ACTS.get(cohort, ()))
    persona = COHORT_PERSONA_STYLE.get(cohort, "")
    parts = [
        f"対象 cohort: {label}",
        f"適用業法: {acts}",
        f"Persona orientation: {persona}",
    ]
    if entity_id:
        parts.append(f"対象法人 (entity_id): {entity_id}")
    if context_token:
        parts.append(f"context_token: {context_token[:16]}... (24h TTL)")
    parts.append(
        "本 response は cohort-specific deep retrieval bundle で、cohort 専用 corpus "
        "+ cohort lexicon hydration + cohort persona styled response 構造。"
        "確定判断は士業へ、primary source 確認必須。"
    )
    return "\n".join(parts)


def _build_cohort_law_citations(
    conn: sqlite3.Connection | None,
    cohort: str,
    query: str,
) -> tuple[str, list[dict[str, Any]]]:
    if conn is None or not _table_present(conn, "am_law_article"):
        return ("(autonomath.db / am_law_article unavailable)", [])
    like = f"%{_safe_like_token(query)}%"
    structured: list[dict[str, Any]] = []
    try:
        cur = conn.execute(
            (
                "SELECT law_canonical_id, article_id, article_number, article_title, "
                "       body, source_url "
                "  FROM am_law_article "
                " WHERE (article_title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\') "
                "   AND body IS NOT NULL AND length(body) >= 16 "
                " ORDER BY length(body) DESC "
                " LIMIT 20"
            ),
            (like, like),
        )
        for row in cur.fetchall():
            body = (row["body"] or "")[:480]
            structured.append(
                {
                    "law_canonical_id": row["law_canonical_id"],
                    "article_id": row["article_id"],
                    "article_number": row["article_number"],
                    "article_title": row["article_title"],
                    "body_excerpt": body,
                    "source_url": row["source_url"],
                }
            )
    except sqlite3.Error as exc:
        logger.debug("HE5 law citation query failed: %s", exc)
        return (f"(law lookup failed: {exc})", [])
    if not structured:
        return (f"(関連 法令 verbatim 一致 0 件 — cohort={cohort})", [])
    label = COHORT_LABELS_JA.get(cohort, cohort)
    head = f"# {label} 向け 法令引用 (top {len(structured)})\n"
    body_text = "\n".join(
        f"- [{s['article_title']} {s['article_number'] or ''}] {s['body_excerpt']}"
        for s in structured
    )
    return (head + body_text, structured)


def _build_practical_steps(cohort: str) -> str:
    return "\n".join(COHORT_PRACTICAL_STEPS.get(cohort, ()))


def _build_pitfalls(cohort: str) -> str:
    return "\n".join(f"- {p}" for p in COHORT_PITFALLS.get(cohort, ()))


def _build_forms(cohort: str) -> str:
    return "\n".join(f"- {f}" for f in COHORT_FORMS.get(cohort, ()))


def _build_deadlines(cohort: str) -> str:
    return "\n".join(f"- {d}" for d in COHORT_DEADLINES.get(cohort, ()))


def _build_cite_list(citations: list[dict[str, Any]]) -> str:
    if not citations:
        return "(関連 一次出典 0 件)"
    lines = []
    for i, c in enumerate(citations, 1):
        url = c.get("source_url") or ""
        title = c.get("article_title") or c.get("law_canonical_id") or "(unknown)"
        article_no = c.get("article_number") or ""
        lines.append(f"{i}. [{title} {article_no}] {url}")
    return "\n".join(lines)


def build_he5_payload(
    *,
    cohort: str,
    query: str,
    entity_id: str | None,
    context_token: str | None,
) -> dict[str, Any]:
    """Build the canonical 8-section HE-5 payload for ``cohort``."""
    if cohort not in COHORT_IDS:
        return {
            "tool_name": f"agent_cohort_deep_{cohort}",
            "schema_version": HE5_SCHEMA_VERSION,
            "lane_id": HE5_LANE_ID,
            "primary_result": {
                "status": "error",
                "lane_id": HE5_LANE_ID,
                "rationale": (f"Unknown cohort: {cohort!r}. Expected one of {COHORT_IDS}."),
            },
            "billing": {
                "billable_units": HE5_UNITS,
                "unit_price_jpy_taxed": 3.30,
                "unit_price_jpy": 3,
                "total_jpy_taxed": HE5_UNITS * 3.30,
                "total_jpy": HE5_YEN,
                "model": "per_call_d_tier",
            },
            "_billing_unit": HE5_UNITS,
            "_disclaimer": DISCLAIMER,
        }

    q = (query or "").strip()
    primary_input = {
        "cohort": cohort,
        "query": q,
        "entity_id": entity_id,
        "context_token_present": bool(context_token),
    }

    conn = _open_ro()
    try:
        issue_text = _build_issue(cohort, q)
        ctx_text = _build_context(cohort, entity_id, context_token)
        law_text, law_struct = _build_cohort_law_citations(conn, cohort, q)
        steps_text = _build_practical_steps(cohort)
        pitfalls_text = _build_pitfalls(cohort)
        forms_text = _build_forms(cohort)
        deadlines_text = _build_deadlines(cohort)
        cite_text = _build_cite_list(law_struct)
    finally:
        if conn is not None:
            with contextlib.suppress(sqlite3.Error):
                conn.close()

    sections: list[dict[str, str]] = [
        {"section": "issue", "content": issue_text},
        {"section": "context", "content": ctx_text},
        {"section": "cohort_law_citations", "content": law_text},
        {"section": "practical_steps", "content": steps_text},
        {"section": "pitfalls", "content": pitfalls_text},
        {"section": "forms", "content": forms_text},
        {"section": "deadlines", "content": deadlines_text},
        {"section": "cite_list", "content": cite_text},
    ]

    hydration = cohort_terminology_hydrate(cohort, law_text + steps_text)

    return {
        "tool_name": f"agent_cohort_deep_{cohort}",
        "schema_version": HE5_SCHEMA_VERSION,
        "primary_result": {
            "status": "ok",
            "lane_id": HE5_LANE_ID,
            "cohort": cohort,
            "cohort_label_ja": COHORT_LABELS_JA.get(cohort, cohort),
            "primary_input": primary_input,
            "sections_n": len(sections),
            "law_rows_n": len(law_struct),
        },
        "sections": sections,
        "structured_payload": {
            "cohort_law_citations": law_struct,
        },
        "cohort_terminology_hydration": hydration,
        "billing": {
            "billable_units": HE5_UNITS,
            "unit_price_jpy_taxed": 3.30,
            "unit_price_jpy": 3,
            "total_jpy_taxed": HE5_UNITS * 3.30,
            "total_jpy": HE5_YEN,
            "model": "per_call_d_tier",
        },
        "cost_saving_narrative": he5_cost_saving_footer(cohort),
        "_billing_unit": HE5_UNITS,
        "_disclaimer": DISCLAIMER,
        "_provenance": {
            "source_module": (f"jpintel_mcp.mcp.moat_lane_tools.he5_cohort_deep.he5_{cohort}_deep"),
            "lane_id": HE5_LANE_ID,
            "observed_at": today_iso_utc(),
            "schema_version": HE5_SCHEMA_VERSION,
            "cohort": cohort,
            "no_llm": True,
        },
    }


__all__ = [
    "HE5_LANE_ID",
    "HE5_SCHEMA_VERSION",
    "HE5_SECTIONS",
    "HE5_UNITS",
    "HE5_YEN",
    "build_he5_payload",
]
