"""Shared core for the 5 HE-6 cohort ultra-deep + hand-off endpoints."""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from jpintel_mcp._jpcite_env_bridge import get_flag

from .._shared import DISCLAIMER, today_iso_utc
from .._shared_cohort import (
    COHORT_DEADLINES,
    COHORT_ESCALATION_FLOW,
    COHORT_FORMS,
    COHORT_IDS,
    COHORT_IMPLEMENTATION_WORKFLOW,
    COHORT_LABELS_JA,
    COHORT_PERSONA_STYLE,
    COHORT_PITFALLS,
    COHORT_PRACTICAL_STEPS,
    COHORT_REGULATED_ACTS,
    COHORT_RISK_REGISTER,
    cohort_terminology_hydrate,
    he6_cost_saving_footer,
)

logger = logging.getLogger("jpintel.mcp.moat_lane_tools.he6_cohort_ultra._core")

HE6_UNITS = 33
HE6_YEN = 100
HE6_LANE_ID = "HE6"
HE6_SCHEMA_VERSION = "moat.he6.v1"

HE6_SECTIONS: tuple[str, ...] = (
    "issue",
    "context",
    "cohort_law_citations",
    "practical_steps",
    "pitfalls",
    "forms",
    "deadlines",
    "cite_list",
    "extended_case_studies",
    "extended_law_chain",
    "implementation_workflow",
    "intermediate_checkpoints",
    "risk_register",
    "escalation_flow",
    "handoff_schema",
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
        logger.debug("HE6 autonomath.db open failed: %s", exc)
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
    return f"対象 cohort: {label}\nIssue (ultra-deep): {query}"


def _build_context(cohort: str, entity_id: str | None, context_token: str | None) -> str:
    label = COHORT_LABELS_JA.get(cohort, cohort)
    acts = "・".join(COHORT_REGULATED_ACTS.get(cohort, ()))
    persona = COHORT_PERSONA_STYLE.get(cohort, "")
    parts = [
        f"対象 cohort: {label} (HE-6 ultra-deep with implementation hand-off)",
        f"適用業法: {acts}",
        f"Persona orientation: {persona}",
    ]
    if entity_id:
        parts.append(f"対象法人 (entity_id): {entity_id}")
    if context_token:
        parts.append(f"context_token: {context_token[:16]}... (24h TTL)")
    parts.append(
        "本 response は cohort-specific ultra-deep retrieval bundle + "
        "implementation hand-off schema (workflow + checkpoint + risk + "
        "escalation) で、cohort 専用 corpus + cohort lexicon hydration + "
        "cohort persona styled 15-section 構造。"
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
                " LIMIT 30"
            ),
            (like, like),
        )
        for row in cur.fetchall():
            body = (row["body"] or "")[:600]
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
        logger.debug("HE6 law citation query failed: %s", exc)
        return (f"(law lookup failed: {exc})", [])
    if not structured:
        return (f"(関連 法令 verbatim 一致 0 件 — cohort={cohort})", [])
    label = COHORT_LABELS_JA.get(cohort, cohort)
    head = f"# {label} 向け 法令引用 (ultra-deep top {len(structured)})\n"
    body_text = "\n".join(
        f"- [{s['article_title']} {s['article_number'] or ''}] {s['body_excerpt']}"
        for s in structured
    )
    return (head + body_text, structured)


def _build_extended_case_studies(
    conn: sqlite3.Connection | None,
    query: str,
) -> tuple[str, list[dict[str, Any]]]:
    structured: list[dict[str, Any]] = []
    text_blocks: list[str] = []
    if conn is None:
        return ("(autonomath.db unavailable)", [])
    like = f"%{_safe_like_token(query)}%"
    if _table_present(conn, "court_decisions"):
        try:
            cur = conn.execute(
                (
                    "SELECT decision_id, case_name, court_name, decision_date, "
                    "       key_ruling, source_url "
                    "  FROM court_decisions "
                    " WHERE (case_name LIKE ? ESCAPE '\\' "
                    "        OR key_ruling LIKE ? ESCAPE '\\') "
                    " ORDER BY decision_date DESC "
                    " LIMIT 3"
                ),
                (like, like),
            )
            for row in cur.fetchall():
                ruling = (row["key_ruling"] or "")[:320]
                text_blocks.append(
                    f"[{row['court_name'] or '裁判所'} {row['decision_date'] or ''}] "
                    f"{row['case_name'] or row['decision_id']}: {ruling}"
                )
                structured.append(
                    {
                        "kind": "judgment",
                        "decision_id": row["decision_id"],
                        "court_name": row["court_name"],
                        "decision_date": row["decision_date"],
                        "case_name": row["case_name"],
                        "key_ruling_excerpt": ruling,
                        "source_url": row["source_url"],
                    }
                )
        except sqlite3.Error as exc:
            logger.debug("HE6 court_decisions query failed: %s", exc)
    if _table_present(conn, "nta_saiketsu") and len(structured) < 3:
        try:
            cur = conn.execute(
                (
                    "SELECT saiketsu_id, title, decision_date, decision_summary, "
                    "       source_url "
                    "  FROM nta_saiketsu "
                    " WHERE (title LIKE ? ESCAPE '\\' "
                    "        OR decision_summary LIKE ? ESCAPE '\\') "
                    " ORDER BY decision_date DESC "
                    " LIMIT ?"
                ),
                (like, like, 3 - len(structured)),
            )
            for row in cur.fetchall():
                summary = (row["decision_summary"] or "")[:320]
                text_blocks.append(
                    f"[国税不服審判所 裁決 {row['decision_date'] or ''}] "
                    f"{row['title'] or row['saiketsu_id']}: {summary}"
                )
                structured.append(
                    {
                        "kind": "saiketsu",
                        "saiketsu_id": row["saiketsu_id"],
                        "decision_date": row["decision_date"],
                        "title": row["title"],
                        "summary_excerpt": summary,
                        "source_url": row["source_url"],
                    }
                )
        except sqlite3.Error as exc:
            logger.debug("HE6 nta_saiketsu query failed: %s", exc)
    if not text_blocks:
        return ("(関連 判例 / 採決 0 件)", [])
    return ("\n\n".join(text_blocks), structured)


def _build_extended_law_chain(
    conn: sqlite3.Connection | None,
    query: str,
) -> tuple[str, list[dict[str, Any]]]:
    chains: list[dict[str, Any]] = []
    if conn is None or not _table_present(conn, "am_legal_reasoning_chain"):
        return ("(autonomath.db / am_legal_reasoning_chain unavailable)", [])
    like = f"%{_safe_like_token(query)}%"
    try:
        cur = conn.execute(
            (
                "SELECT chain_id, topic_label, conclusion_text, confidence, "
                "       opposing_view_text "
                "  FROM am_legal_reasoning_chain "
                " WHERE (topic_label LIKE ? ESCAPE '\\' "
                "        OR conclusion_text LIKE ? ESCAPE '\\') "
                "   AND confidence >= 0.55 "
                " ORDER BY confidence DESC "
                " LIMIT 3"
            ),
            (like, like),
        )
        for row in cur.fetchall():
            chains.append(
                {
                    "chain_id": row["chain_id"],
                    "topic_label": row["topic_label"],
                    "conclusion": (row["conclusion_text"] or "")[:600],
                    "confidence": float(row["confidence"] or 0.0),
                    "opposing_view": (row["opposing_view_text"] or "")[:400],
                }
            )
    except sqlite3.Error as exc:
        logger.debug("HE6 reasoning_chain query failed: %s", exc)
        return (f"(reasoning_chain lookup failed: {exc})", [])
    if not chains:
        return ("(関連 reasoning_chain 0 件)", [])
    text = "\n\n".join(
        f"({c['confidence']:.2f}) {c['topic_label']}: {c['conclusion']}\n"
        f"  対立論点: {c['opposing_view'] or '(なし)'}"
        for c in chains
    )
    return (text, chains)


def _build_intermediate_checkpoints(cohort: str) -> tuple[str, list[dict[str, Any]]]:
    flows = COHORT_IMPLEMENTATION_WORKFLOW.get(cohort, ())
    checkpoints: list[dict[str, Any]] = []
    for i, flow in enumerate(flows, 1):
        checkpoints.append(
            {
                "checkpoint_id": f"{cohort.upper()[:3]}-CP{i}",
                "stage": flow.split(":", 1)[0].strip(),
                "objective": flow.split(":", 1)[1].strip() if ":" in flow else flow,
                "status": "pending",
                "review_cadence": "stage-completion-gated",
                "evidence_required": ["primary_source_url", "operator_signoff"],
            }
        )
    text = "\n".join(
        f"- [{c['checkpoint_id']}] {c['stage']}: {c['objective']} "
        f"(status={c['status']}, cadence={c['review_cadence']})"
        for c in checkpoints
    )
    return (text, checkpoints)


def _build_risk_register(cohort: str) -> tuple[str, list[dict[str, str]]]:
    risks = COHORT_RISK_REGISTER.get(cohort, ())
    risks_list = list(risks)
    text = "\n".join(f"- [{r['id']}] {r['risk']} → 対策: {r['mitigation']}" for r in risks_list)
    return (text, risks_list)


def _build_handoff_schema(
    *,
    cohort: str,
    entity_id: str | None,
    context_token: str | None,
    checkpoints: list[dict[str, Any]],
    risks: list[dict[str, str]],
) -> tuple[str, dict[str, Any]]:
    schema = {
        "schema_version": HE6_SCHEMA_VERSION,
        "cohort": cohort,
        "cohort_label_ja": COHORT_LABELS_JA.get(cohort, cohort),
        "entity_id": entity_id,
        "context_token_present": bool(context_token),
        "context_token_ttl_seconds": 86400 if context_token else None,
        "regulated_acts": list(COHORT_REGULATED_ACTS.get(cohort, ())),
        "checkpoints": checkpoints,
        "risk_register": risks,
        "next_action_hint": (
            "1. Confirm checkpoints with operator. 2. Re-call HE-6 with "
            "context_token after each completed checkpoint. 3. Escalate "
            "per the cohort escalation_flow if any checkpoint is blocked."
        ),
        "machine_readable": True,
        "no_llm": True,
        "issued_at": today_iso_utc(),
    }
    body = json.dumps(schema, ensure_ascii=False, indent=2)
    return (f"```json\n{body}\n```", schema)


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


def build_he6_payload(
    *,
    cohort: str,
    query: str,
    entity_id: str | None,
    context_token: str | None,
) -> dict[str, Any]:
    """Build the canonical 15-section HE-6 payload for ``cohort``."""
    if cohort not in COHORT_IDS:
        return {
            "tool_name": f"agent_cohort_ultra_{cohort}",
            "schema_version": HE6_SCHEMA_VERSION,
            "lane_id": HE6_LANE_ID,
            "primary_result": {
                "status": "error",
                "lane_id": HE6_LANE_ID,
                "rationale": (f"Unknown cohort: {cohort!r}. Expected one of {COHORT_IDS}."),
            },
            "billing": {
                "billable_units": HE6_UNITS,
                "unit_price_jpy_taxed": 3.30,
                "unit_price_jpy": 3,
                "total_jpy_taxed": HE6_UNITS * 3.30,
                "total_jpy": HE6_YEN,
                "model": "per_call_d_plus_tier",
            },
            "_billing_unit": HE6_UNITS,
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
        steps_text = "\n".join(COHORT_PRACTICAL_STEPS.get(cohort, ()))
        pitfalls_text = "\n".join(f"- {p}" for p in COHORT_PITFALLS.get(cohort, ()))
        forms_text = "\n".join(f"- {f}" for f in COHORT_FORMS.get(cohort, ()))
        deadlines_text = "\n".join(f"- {d}" for d in COHORT_DEADLINES.get(cohort, ()))
        cite_text = _build_cite_list(law_struct)
        cases_text, cases_struct = _build_extended_case_studies(conn, q)
        chain_text, chain_struct = _build_extended_law_chain(conn, q)
        workflow_text = "\n".join(f"- {f}" for f in COHORT_IMPLEMENTATION_WORKFLOW.get(cohort, ()))
        cp_text, cp_struct = _build_intermediate_checkpoints(cohort)
        risk_text, risk_struct = _build_risk_register(cohort)
        escalation_text = "\n".join(COHORT_ESCALATION_FLOW.get(cohort, ()))
        handoff_text, handoff_struct = _build_handoff_schema(
            cohort=cohort,
            entity_id=entity_id,
            context_token=context_token,
            checkpoints=cp_struct,
            risks=risk_struct,
        )
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
        {"section": "extended_case_studies", "content": cases_text},
        {"section": "extended_law_chain", "content": chain_text},
        {"section": "implementation_workflow", "content": workflow_text},
        {"section": "intermediate_checkpoints", "content": cp_text},
        {"section": "risk_register", "content": risk_text},
        {"section": "escalation_flow", "content": escalation_text},
        {"section": "handoff_schema", "content": handoff_text},
    ]

    hydration_body = law_text + steps_text + workflow_text + cp_text + risk_text + chain_text
    hydration = cohort_terminology_hydrate(cohort, hydration_body)

    return {
        "tool_name": f"agent_cohort_ultra_{cohort}",
        "schema_version": HE6_SCHEMA_VERSION,
        "primary_result": {
            "status": "ok",
            "lane_id": HE6_LANE_ID,
            "cohort": cohort,
            "cohort_label_ja": COHORT_LABELS_JA.get(cohort, cohort),
            "primary_input": primary_input,
            "sections_n": len(sections),
            "law_rows_n": len(law_struct),
            "case_rows_n": len(cases_struct),
            "chain_rows_n": len(chain_struct),
            "checkpoint_n": len(cp_struct),
            "risk_n": len(risk_struct),
        },
        "sections": sections,
        "structured_payload": {
            "cohort_law_citations": law_struct,
            "extended_case_studies": cases_struct,
            "extended_law_chain": chain_struct,
            "intermediate_checkpoints": cp_struct,
            "risk_register": risk_struct,
            "handoff_schema": handoff_struct,
        },
        "cohort_terminology_hydration": hydration,
        "billing": {
            "billable_units": HE6_UNITS,
            "unit_price_jpy_taxed": 3.30,
            "unit_price_jpy": 3,
            "total_jpy_taxed": HE6_UNITS * 3.30,
            "total_jpy": HE6_YEN,
            "model": "per_call_d_plus_tier",
        },
        "cost_saving_narrative": he6_cost_saving_footer(cohort),
        "_billing_unit": HE6_UNITS,
        "_disclaimer": DISCLAIMER,
        "_provenance": {
            "source_module": (
                f"jpintel_mcp.mcp.moat_lane_tools.he6_cohort_ultra.he6_{cohort}_ultra"
            ),
            "lane_id": HE6_LANE_ID,
            "observed_at": today_iso_utc(),
            "schema_version": HE6_SCHEMA_VERSION,
            "cohort": cohort,
            "no_llm": True,
        },
    }


__all__ = [
    "HE6_LANE_ID",
    "HE6_SCHEMA_VERSION",
    "HE6_SECTIONS",
    "HE6_UNITS",
    "HE6_YEN",
    "build_he6_payload",
]
