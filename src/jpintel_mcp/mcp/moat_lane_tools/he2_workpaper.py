"""HE-2 Heavy-Output endpoint — ``prepare_implementation_workpaper``.

One MCP call assembles a near-complete artifact workpaper draft by composing
six upstream moat lanes (N1 template + N2 portfolio + N3 reasoning + N4
filing window + N6 amendment alert + N9 placeholder resolver). The caller
provides ``houjin_bangou`` + ``artifact_type`` (+ optional segment / fiscal
year / auto_fill_level) and receives a fully fanned-out scaffold whose
placeholders are already resolved against the houjin's 360 view, the
deterministic reasoning corpus, the registered filing window, and the
upstream amendment-alert feed.

Hard constraints
----------------

* NO LLM inference — pure SQLite / dict composition.
* §52 / §47条の2 / §72 / §1 / §3 disclaimer envelope on every response.
* Auto-fill stays scaffold-only — the wrapper never claims a finished filing.
* 1 ¥3 billable unit per call (host MCP server counts).
* Read-only SQLite connection (URI mode ``ro``) via the upstream lane DBs.

Cost economics (vs. agent round-trip baseline)
---------------------------------------------

Agent baseline = 10-20 sequential MCP calls (template fetch → portfolio →
reasoning chains × 5 → window lookup → alerts → placeholder resolution
× 8 → manual merge). Each call carries the ¥3/req minimum plus the
agent's own LLM round-trip cost. HE-2 collapses the entire workflow into
1 ¥3/req call, returning the merged draft plus an ``agent_next_actions``
plan that the LLM can execute verbatim. Net savings: 90%+ on the API
side, ~95% on the LLM side because no orchestration prose is round-tripped.

Tool surface
------------

* ``prepare_implementation_workpaper(artifact_type, houjin_bangou,
  segment=None, fiscal_year=None, auto_fill_level="deep")`` — single
  heavy-output composition.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as _dt
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

logger = logging.getLogger("jpintel.mcp.moat_lane_tools.he2_workpaper")

_LANE_ID = "HE-2"
_SCHEMA_VERSION = "moat.he2.v1"
_UPSTREAM_MODULE = "jpintel_mcp.moat.he2_workpaper"

# Allowed segment whitelist (mirrors N1 catalog).
_SEGMENTS_JA: tuple[str, ...] = ("税理士", "会計士", "行政書士", "司法書士", "社労士")
_AUTO_FILL_LEVELS: tuple[str, ...] = ("skeleton", "partial", "deep")

# Segment → artifact_type prefix heuristic (used when segment is None).
_TYPE_TO_SEGMENT: dict[str, str] = {
    # 税理士
    "houjinzei_shinkoku": "税理士",
    "shouhizei_shinkoku": "税理士",
    "gessji_shiwake": "税理士",
    "nenmatsu_chosei": "税理士",
    "kifukin_koujo_shoumei": "税理士",
    "gensen_choushuubo": "税理士",
    "kyuyo_keisan": "税理士",
    "inshi_zei_shinkoku": "税理士",
    "shoukyaku_shisan_shinkoku": "税理士",
    "kaihaigyou_todoke": "税理士",
    # 会計士
    "kansa_chosho": "会計士",
    "kansa_iken": "会計士",
    "naibu_tousei_houkoku": "会計士",
    "kaikei_houshin_chuuki": "会計士",
    "taishoku_kyufu_keisan": "会計士",
    "tanaoroshi_hyouka": "会計士",
    "kinyu_shouhin_hyouka": "会計士",
    "lease_torihiki": "会計士",
    # 行政書士
    "hojokin_shinsei": "行政書士",
    "kyoninka_shinsei": "行政書士",
    # 司法書士
    "kaisha_setsuritsu_touki": "司法書士",
    "yakuin_henko_touki": "司法書士",
    # 社労士
    "shuugyou_kisoku": "社労士",
    "sanroku_kyoutei": "社労士",
    "36_kyotei": "社労士",
}

# Type → primary tax_category (used to walk N3 reasoning chains).
_TYPE_TO_CATEGORY: dict[str, str] = {
    "houjinzei_shinkoku": "corporate_tax",
    "shouhizei_shinkoku": "consumption_tax",
    "gessji_shiwake": "corporate_tax",
    "nenmatsu_chosei": "income_tax",
    "kyuyo_keisan": "income_tax",
    "gensen_choushuubo": "income_tax",
    "hojokin_shinsei": "subsidy",
    "kyoninka_shinsei": "commerce",
    "kaisha_setsuritsu_touki": "commerce",
    "yakuin_henko_touki": "commerce",
    "shuugyou_kisoku": "labor",
    "sanroku_kyoutei": "labor",
    "36_kyotei": "labor",
    "kansa_chosho": "corporate_tax",
    "kansa_iken": "corporate_tax",
}

# Type → recommended filing-window kind (N4).
_TYPE_TO_WINDOW_KIND: dict[str, str] = {
    "houjinzei_shinkoku": "tax_office",
    "shouhizei_shinkoku": "tax_office",
    "nenmatsu_chosei": "tax_office",
    "gensen_choushuubo": "tax_office",
    "inshi_zei_shinkoku": "tax_office",
    "shoukyaku_shisan_shinkoku": "tax_office",
    "kaihaigyou_todoke": "tax_office",
    "kifukin_koujo_shoumei": "tax_office",
    "hojokin_shinsei": "prefecture",
    "kyoninka_shinsei": "prefecture",
    "kaisha_setsuritsu_touki": "legal_affairs_bureau",
    "yakuin_henko_touki": "legal_affairs_bureau",
    "shuugyou_kisoku": "labour_bureau",
    "sanroku_kyoutei": "labour_bureau",
    "36_kyotei": "labour_bureau",
}

_TOKEN_RE = re.compile(r"\{\{([A-Z_][A-Z0-9_]*)\}\}")


def _autonomath_db_path() -> Path:
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
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


def _table_present(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def _parse_jsonb(raw: str | None) -> Any:
    if raw is None or raw == "":
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _infer_segment(artifact_type: str) -> str | None:
    return _TYPE_TO_SEGMENT.get(artifact_type)


def _today_iso() -> str:
    return _dt.datetime.now(_dt.UTC).date().isoformat()


def _compute_deadline(artifact_type: str, fiscal_year: int | None) -> str | None:
    """Deterministic deadline projection.

    Pure date arithmetic — no external lookup. The agent_next_actions step
    references the projected deadline; the verified deadline still requires
    the士業 to confirm against the live 公的 calendar.
    """
    today = _dt.date.today()
    year = fiscal_year if fiscal_year is not None else today.year
    if artifact_type == "houjinzei_shinkoku":
        # 法人税申告 = 事業年度末 + 2ヶ月
        return _dt.date(year + 1, 5, 31).isoformat()
    if artifact_type == "shouhizei_shinkoku":
        return _dt.date(year + 1, 3, 31).isoformat()
    if artifact_type == "nenmatsu_chosei":
        return _dt.date(year + 1, 1, 31).isoformat()
    if artifact_type == "shuugyou_kisoku":
        # 就業規則 has no statutory deadline — return a +90 day target.
        return (today + _dt.timedelta(days=90)).isoformat()
    if artifact_type in ("sanroku_kyoutei", "36_kyotei"):
        # 36協定 covers a 1y window from 4/1; surface FY start.
        return _dt.date(year, 3, 31).isoformat()
    if artifact_type == "hojokin_shinsei":
        return (today + _dt.timedelta(days=30)).isoformat()
    if artifact_type == "kaisha_setsuritsu_touki":
        # 設立登記 — 設立日 + 2 weeks per 商業登記法 §47
        return (today + _dt.timedelta(days=14)).isoformat()
    if artifact_type == "yakuin_henko_touki":
        return (today + _dt.timedelta(days=14)).isoformat()
    return None


# --------------------------------------------------------------------------- #
# DB-level slice fetchers (run concurrently via asyncio.gather)               #
# --------------------------------------------------------------------------- #


def _fetch_template_sync(segment: str, artifact_type: str) -> dict[str, Any] | None:
    conn = _open_ro()
    if conn is None:
        return None
    try:
        if not _table_present(conn, "am_artifact_templates"):
            return None
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
        return None
    return {
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
        "structure": _parse_jsonb(row["structure_jsonb"]) or {},
        "placeholders": _parse_jsonb(row["placeholders_jsonb"]) or [],
        "mcp_query_bindings": _parse_jsonb(row["mcp_query_bindings_jsonb"]) or {},
        "license": row["license"],
        "notes": row["notes"],
        "updated_at": row["updated_at"],
    }


def _fetch_alternative_templates_sync(segment: str, artifact_type: str) -> list[dict[str, Any]]:
    """Older version rows (revision history)."""
    conn = _open_ro()
    if conn is None:
        return []
    try:
        if not _table_present(conn, "am_artifact_templates"):
            return []
        rows = conn.execute(
            """
            SELECT template_id, version, quality_grade, updated_at
              FROM am_artifact_templates
             WHERE segment = ? AND artifact_type = ?
             ORDER BY version DESC
             LIMIT 5
            """,
            (segment, artifact_type),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "template_id": int(r["template_id"]),
            "version": r["version"],
            "quality_grade": r["quality_grade"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def _fetch_portfolio_sync(houjin_bangou: str) -> dict[str, Any]:
    conn = _open_ro()
    if conn is None:
        return {"portfolio": [], "summary": None}
    try:
        if not _table_present(conn, "am_houjin_program_portfolio"):
            return {"portfolio": [], "summary": None}
        try:
            rows = conn.execute(
                """
                SELECT program_id, applicability_score, applied_status,
                       deadline, priority_rank
                  FROM am_houjin_program_portfolio
                 WHERE houjin_bangou = ?
                 ORDER BY priority_rank ASC NULLS LAST, applicability_score DESC
                 LIMIT 20
                """,
                (houjin_bangou,),
            ).fetchall()
        except sqlite3.OperationalError:
            return {"portfolio": [], "summary": None}
    finally:
        conn.close()
    portfolio = [
        {
            "program_id": r["program_id"],
            "applicability_score": round(float(r["applicability_score"] or 0.0), 2),
            "applied_status": r["applied_status"],
            "deadline": r["deadline"],
            "priority_rank": r["priority_rank"],
        }
        for r in rows
    ]
    summary = None
    if portfolio:
        summary = {
            "total": len(portfolio),
            "applied": sum(1 for p in portfolio if p["applied_status"] == "applied"),
            "unapplied": sum(1 for p in portfolio if p["applied_status"] == "unapplied"),
            "top_score": portfolio[0]["applicability_score"],
        }
    return {"portfolio": portfolio, "summary": summary}


def _fetch_reasoning_chains_sync(artifact_type: str, limit: int = 5) -> list[dict[str, Any]]:
    """Pull top-N reasoning chains tied to the artifact's tax_category.

    Returns the deterministic 三段論法 envelope from N3.
    """
    category = _TYPE_TO_CATEGORY.get(artifact_type)
    conn = _open_ro()
    if conn is None:
        return []
    try:
        if not _table_present(conn, "am_legal_reasoning_chain"):
            return []
        if category:
            rows = conn.execute(
                """
                SELECT chain_id, topic_id, topic_label, tax_category,
                       conclusion_text, confidence, opposing_view_text,
                       citations
                  FROM am_legal_reasoning_chain
                 WHERE tax_category = ?
                 ORDER BY confidence DESC, chain_id
                 LIMIT ?
                """,
                (category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT chain_id, topic_id, topic_label, tax_category,
                       conclusion_text, confidence, opposing_view_text,
                       citations
                  FROM am_legal_reasoning_chain
                 ORDER BY confidence DESC, chain_id
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            citations = json.loads(r["citations"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            citations = {}
        out.append(
            {
                "chain_id": r["chain_id"],
                "topic_id": r["topic_id"],
                "topic_label": r["topic_label"],
                "tax_category": r["tax_category"],
                "conclusion_text": r["conclusion_text"],
                "confidence": float(r["confidence"] or 0.0),
                "opposing_view_text": r["opposing_view_text"],
                "citations": citations,
            }
        )
    return out


def _fetch_filing_window_sync(artifact_type: str, houjin_bangou: str) -> dict[str, Any]:
    """N4 window resolution via houjin registered address prefix."""
    kind = _TYPE_TO_WINDOW_KIND.get(artifact_type)
    conn = _open_ro()
    if conn is None:
        return {"matches": [], "kind": kind, "address": None}
    try:
        if not _table_present(conn, "am_window_directory"):
            return {"matches": [], "kind": kind, "address": None}
        address: str | None = None
        with contextlib.suppress(sqlite3.OperationalError):
            row = conn.execute(
                "SELECT canonical_id FROM am_entities "
                "WHERE record_kind='corporate_entity' AND canonical_id = ? LIMIT 1",
                (f"houjin:{houjin_bangou}",),
            ).fetchone()
            if row is not None:
                fact = conn.execute(
                    "SELECT value_text FROM am_entity_facts "
                    "WHERE entity_id=? AND field_name IN "
                    "('corp.registered_address','corp.location','corp.address') "
                    "LIMIT 1",
                    (row["canonical_id"],),
                ).fetchone()
                if fact is not None:
                    address = str(fact["value_text"])
        matches: list[dict[str, Any]] = []
        if kind and address:
            with contextlib.suppress(sqlite3.OperationalError):
                window_rows = conn.execute(
                    """
                    SELECT window_id, jurisdiction_kind, name, postal_address,
                           tel, url, source_url, jurisdiction_region_code
                      FROM am_window_directory
                     WHERE jurisdiction_kind = ?
                       AND jurisdiction_houjin_filter_regex IS NOT NULL
                       AND ? LIKE jurisdiction_houjin_filter_regex || '%'
                     LIMIT 3
                    """,
                    (kind, address),
                ).fetchall()
                matches = [dict(r) for r in window_rows]
    finally:
        conn.close()
    return {"matches": matches, "kind": kind, "address": address}


def _fetch_amendment_alerts_sync(
    houjin_bangou: str, horizon_days: int = 90
) -> list[dict[str, Any]]:
    """N6 amendment alerts relevant to the houjin (pending fan-out only)."""
    conn = _open_ro()
    if conn is None:
        return []
    try:
        if not _table_present(conn, "am_amendment_alert_impact"):
            return []
        try:
            rows = conn.execute(
                """
                SELECT alert_id, amendment_diff_id, impact_score,
                       impacted_program_ids, impacted_tax_rule_ids,
                       detected_at, notified_at
                  FROM am_amendment_alert_impact
                 WHERE houjin_bangou = ?
                   AND datetime(detected_at) >= datetime('now', ?)
                 ORDER BY impact_score DESC, detected_at DESC
                 LIMIT 10
                """,
                (houjin_bangou, f"-{int(horizon_days)} days"),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            programs = json.loads(r["impacted_program_ids"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            programs = []
        try:
            tax_rules = json.loads(r["impacted_tax_rule_ids"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            tax_rules = []
        out.append(
            {
                "alert_id": int(r["alert_id"]),
                "amendment_diff_id": int(r["amendment_diff_id"]),
                "impact_score": int(r["impact_score"]),
                "impacted_program_ids": [str(p) for p in programs],
                "impacted_tax_rule_ids": [str(t) for t in tax_rules],
                "detected_at": r["detected_at"],
                "notified_at": r["notified_at"],
            }
        )
    return out


def _fetch_placeholder_map_sync(keys: list[str]) -> dict[str, dict[str, Any]]:
    """Bulk lookup the placeholder → MCP-call schema for every requested key.

    Returns a dict ``{ "{{HOUJIN_BANGOU}}": <mapping row dict>, ... }`` so the
    composition layer can resolve placeholders without an extra N9 round trip.
    Missing keys are simply absent from the returned map.
    """
    if not keys:
        return {}
    canonical = [k if k.startswith("{{") else f"{{{{{k}}}}}" for k in keys]
    conn = _open_ro()
    if conn is None:
        return {}
    try:
        if not _table_present(conn, "am_placeholder_mapping"):
            return {}
        placeholders = ",".join("?" for _ in canonical)
        rows = conn.execute(
            f"""
            SELECT placeholder_name, mcp_tool_name, args_template,
                   output_path, fallback_value, value_kind,
                   description, is_sensitive, license
              FROM am_placeholder_mapping
             WHERE placeholder_name IN ({placeholders})
            """,
            canonical,
        ).fetchall()
    finally:
        conn.close()
    return {
        r["placeholder_name"]: {
            "mcp_tool_name": r["mcp_tool_name"],
            "args_template": r["args_template"],
            "output_path": r["output_path"],
            "fallback_value": r["fallback_value"],
            "value_kind": r["value_kind"],
            "description": r["description"],
            "is_sensitive": bool(r["is_sensitive"]),
            "license": r["license"],
        }
        for r in rows
    }


# --------------------------------------------------------------------------- #
# Placeholder resolution chain                                                #
# --------------------------------------------------------------------------- #


def _resolve_one_placeholder(
    key: str,
    placeholder_meta: dict[str, Any],
    *,
    context: dict[str, Any],
    placeholder_map: dict[str, dict[str, Any]],
    auto_fill_level: str,
) -> tuple[str | None, str]:
    """Resolve a single placeholder to a literal value or fallback.

    Returns ``(resolved_value, source_kind)`` where ``source_kind`` is one of
    ``"session" / "alias" / "mcp_bound" / "fallback" / "manual"``. The
    composition layer collapses ``"manual"`` keys into ``manual_input_required``.
    """
    # Direct context hit by raw key.
    if key in context and context[key] not in (None, ""):
        return str(context[key]), "session"

    canonical = f"{{{{{key}}}}}"
    mapping = placeholder_map.get(canonical)

    # Skeleton mode does not auto-fill anything from MCP / fallback.
    if auto_fill_level == "skeleton":
        return None, "manual"

    if mapping is not None:
        tool = (mapping.get("mcp_tool_name") or "").strip()
        # ``context`` tool means the value is expected in the caller-supplied
        # context_dict — already covered above; fall through to fallback.
        if tool == "computed":
            # Deterministic computed placeholders (CURRENT_DATE / OPERATOR_NAME).
            if key == "CURRENT_DATE":
                return _today_iso(), "alias"
            if key == "FISCAL_YEAR" and context.get("FISCAL_YEAR"):
                return str(context["FISCAL_YEAR"]), "session"
        elif tool and tool != "context":
            # MCP-bound resolution: the wrapper does NOT actually call the
            # tool synchronously inside this hot path (we already fetched
            # houjin / window / reasoning concurrently above). Instead we
            # surface the binding so the agent can execute it post-hoc when
            # auto_fill_level is "partial". On "deep" we attempt to read the
            # value out of the pre-fetched context bag.
            ctx_hit = context.get(key)
            if ctx_hit not in (None, ""):
                return str(ctx_hit), "mcp_bound"
            if auto_fill_level == "deep":
                fallback = mapping.get("fallback_value")
                if fallback not in (None, ""):
                    return str(fallback), "fallback"
            return None, "manual"

    # No mapping row — try placeholder_meta.fallback (template-level fallback)
    fallback = placeholder_meta.get("fallback") or placeholder_meta.get("fallback_value")
    if fallback not in (None, ""):
        return str(fallback), "fallback"
    return None, "manual"


def _substitute_paragraph(
    paragraph: str,
    resolved: dict[str, str | None],
) -> str:
    """Replace ``{{KEY}}`` tokens in ``paragraph`` with resolved values.

    Unresolved tokens are left in place so the agent can see what is missing.
    """

    def _repl(match: re.Match[str]) -> str:
        key = match.group(1)
        val = resolved.get(key)
        if val is None or val == "":
            return match.group(0)
        return str(val)

    return _TOKEN_RE.sub(_repl, paragraph)


def _compose_filled_sections(
    template: dict[str, Any],
    placeholder_map: dict[str, dict[str, Any]],
    *,
    context: dict[str, Any],
    auto_fill_level: str,
) -> tuple[list[dict[str, Any]], int, int]:
    """Run the placeholder resolution chain over every section paragraph.

    Returns ``(filled_sections, total_placeholders, resolved_placeholders)``
    so the caller can compute ``estimated_completion_pct``.
    """
    sections = template.get("structure", {}).get("sections", []) or []
    template_placeholders = template.get("placeholders", []) or []
    placeholder_meta_by_key: dict[str, dict[str, Any]] = {}
    for p in template_placeholders:
        if isinstance(p, dict) and "key" in p:
            placeholder_meta_by_key[p["key"]] = p

    # Determine every key referenced in any paragraph + every key declared in
    # template_placeholders (some templates declare placeholders without
    # actually inserting them — surface them all for completeness).
    all_keys: set[str] = set(placeholder_meta_by_key.keys())
    for section in sections:
        if not isinstance(section, dict):
            continue
        for paragraph in section.get("paragraphs", []) or []:
            if isinstance(paragraph, str):
                all_keys.update(_TOKEN_RE.findall(paragraph))

    resolved: dict[str, str | None] = {}
    source_kind: dict[str, str] = {}
    for key in sorted(all_keys):
        meta = placeholder_meta_by_key.get(key, {})
        value, kind = _resolve_one_placeholder(
            key,
            meta,
            context=context,
            placeholder_map=placeholder_map,
            auto_fill_level=auto_fill_level,
        )
        resolved[key] = value
        source_kind[key] = kind

    filled_sections: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_id = section.get("id", "")
        section_title = section.get("title", "")
        paragraphs = section.get("paragraphs", []) or []
        filled_paragraphs: list[str] = []
        placeholders_resolved: list[str] = []
        unresolved_placeholders: list[str] = []
        for paragraph in paragraphs:
            if not isinstance(paragraph, str):
                continue
            keys = _TOKEN_RE.findall(paragraph)
            filled_paragraphs.append(_substitute_paragraph(paragraph, resolved))
            for key in keys:
                if resolved.get(key) not in (None, ""):
                    if key not in placeholders_resolved:
                        placeholders_resolved.append(key)
                else:
                    if key not in unresolved_placeholders:
                        unresolved_placeholders.append(key)
        manual_input_required = [
            k for k in unresolved_placeholders if source_kind.get(k) == "manual"
        ]
        filled_sections.append(
            {
                "section_id": section_id,
                "section_name": section_title,
                "content_filled": "\n".join(filled_paragraphs),
                "placeholders_resolved": placeholders_resolved,
                "unresolved_placeholders": unresolved_placeholders,
                "manual_input_required": manual_input_required,
            }
        )

    total_placeholders = len(all_keys)
    resolved_count = sum(1 for v in resolved.values() if v not in (None, ""))
    return filled_sections, total_placeholders, resolved_count


# --------------------------------------------------------------------------- #
# Legal basis projection                                                      #
# --------------------------------------------------------------------------- #


def _fetch_legal_basis_sync(template: dict[str, Any]) -> dict[str, Any]:
    """Surface law_articles / tsutatsu / judgments tied to the template.

    Pure SQLite SELECT — no LLM. We anchor on the template's ``authority``
    field (e.g. ``"法人税法 §22"``) and walk the reasoning chains for
    citations of kind ``law`` / ``tsutatsu`` / ``hanrei`` / ``saiketsu``.
    """
    authority = (template.get("authority") or "").strip()
    artifact_type = template.get("artifact_type", "")
    out: dict[str, list[dict[str, Any]]] = {
        "law_articles": [],
        "tsutatsu": [],
        "judgment_examples": [],
    }
    chains = _fetch_reasoning_chains_sync(artifact_type, limit=5)
    seen_law: set[str] = set()
    seen_tsu: set[str] = set()
    seen_han: set[str] = set()
    for chain in chains:
        citations = chain.get("citations") or {}
        if not isinstance(citations, dict):
            continue
        for entry in citations.get("law", []) or []:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("source_url") or entry.get("unified_id") or "")
            if not key or key in seen_law:
                continue
            seen_law.add(key)
            out["law_articles"].append(entry)
        for entry in citations.get("tsutatsu", []) or []:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("source_url") or entry.get("unified_id") or "")
            if not key or key in seen_tsu:
                continue
            seen_tsu.add(key)
            out["tsutatsu"].append(entry)
        for kind in ("hanrei", "saiketsu"):
            for entry in citations.get(kind, []) or []:
                if not isinstance(entry, dict):
                    continue
                key = str(entry.get("source_url") or entry.get("unified_id") or "")
                if not key or key in seen_han:
                    continue
                seen_han.add(key)
                out["judgment_examples"].append({**entry, "kind": kind})
    if not out["law_articles"] and authority:
        # Template-level authority fallback so the response always carries at
        # least one anchor.
        out["law_articles"].append({"authority_text": authority, "source": "template"})
    out["law_articles"] = out["law_articles"][:10]
    out["tsutatsu"] = out["tsutatsu"][:10]
    out["judgment_examples"] = out["judgment_examples"][:5]
    return out


# --------------------------------------------------------------------------- #
# Agent next-actions planner                                                  #
# --------------------------------------------------------------------------- #


def _agent_next_actions(
    template: dict[str, Any],
    *,
    filled_sections: list[dict[str, Any]],
    filing_window: dict[str, Any],
    deadline: str | None,
) -> list[dict[str, Any]]:
    """Deterministic 3-step next-action plan."""
    manual = [k for section in filled_sections for k in section.get("manual_input_required", [])]
    via = "online" if filing_window.get("matches") else "post"
    actions: list[dict[str, Any]] = [
        {
            "step": "fill manual_input",
            "items": sorted(set(manual)),
            "rationale": "Placeholders flagged manual_input_required must be supplied by the operator.",
        },
        {
            "step": f"verify with {template.get('segment')}",
            "items": [],
            "rationale": (
                f"§52 / §47条の2 / §72 / §1 / §3 — scaffold-only draft. "
                f"{template.get('segment')} review is statutory before submission."
            ),
        },
        {
            "step": "submit to filing_window",
            "items": [m.get("name") for m in filing_window.get("matches", [])][:3],
            "rationale": (
                f"Window kind = {filing_window.get('kind')}; deadline = {deadline}. "
                "Always confirm via the source_url 1st-party page."
            ),
            "via": via,
        },
    ]
    return actions


# --------------------------------------------------------------------------- #
# Empty / error envelope helpers                                              #
# --------------------------------------------------------------------------- #


def _empty_envelope(
    *,
    primary_input: dict[str, Any],
    rationale: str,
    status: str = "empty",
) -> dict[str, Any]:
    return {
        "tool_name": "prepare_implementation_workpaper",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": status,
            "lane_id": _LANE_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "rationale": rationale,
        },
        "artifact_type": primary_input.get("artifact_type"),
        "template": None,
        "filled_sections": [],
        "legal_basis": {"law_articles": [], "tsutatsu": [], "judgment_examples": []},
        "filing_window": {"matches": [], "kind": None, "address": None},
        "deadline": None,
        "estimated_completion_pct": 0.0,
        "agent_next_actions": [],
        "reasoning_chains": [],
        "amendment_alerts_relevant": [],
        "alternative_templates": [],
        "billing": {"unit": 1, "yen": 3, "auto_fill_level": primary_input.get("auto_fill_level")},
        "results": [],
        "total": 0,
        "limit": 0,
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_he2_workpaper",
            "observed_at": today_iso_utc(),
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
        "_citation_envelope": {"law_articles": 0, "tsutatsu": 0, "judgment_examples": 0},
        "_provenance": {
            "lane_id": _LANE_ID,
            "composed_lanes": ["N1", "N2", "N3", "N4", "N6", "N9"],
            "observed_at": today_iso_utc(),
        },
    }


# --------------------------------------------------------------------------- #
# Public async tool                                                            #
# --------------------------------------------------------------------------- #


@mcp.tool(annotations=_READ_ONLY)
async def prepare_implementation_workpaper(
    artifact_type: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            description=(
                "Artifact type slug, e.g. 'houjinzei_shinkoku' / 'shuugyou_kisoku' / "
                "'kaisha_setsuritsu_touki'. Must match a row in am_artifact_templates."
            ),
        ),
    ],
    houjin_bangou: Annotated[
        str,
        Field(
            min_length=0,
            max_length=13,
            description=(
                "13-digit corporate number. Empty string is allowed for skeleton mode "
                "(template fetch + placeholder enumeration only, no houjin-specific fill)."
            ),
        ),
    ] = "",
    segment: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional segment override (税理士 / 会計士 / 行政書士 / 司法書士 / 社労士). "
                "If omitted the segment is inferred from artifact_type."
            ),
        ),
    ] = None,
    fiscal_year: Annotated[
        int | None,
        Field(
            default=None,
            ge=2000,
            le=2100,
            description=(
                "Optional fiscal year (e.g. 2026). Used by the deadline projector "
                "for 法人税申告 / 消費税申告 / 36協定 cohorts."
            ),
        ),
    ] = None,
    auto_fill_level: Annotated[
        str,
        Field(
            default="deep",
            pattern=r"^(skeleton|partial|deep)$",
            description=(
                "How aggressively to auto-fill placeholders: "
                "'skeleton' = template + placeholder enumeration only; "
                "'partial' = surface MCP bindings without invoking them; "
                "'deep' = fill via context + fallback chain + alias resolution."
            ),
        ),
    ] = "deep",
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1/§3] HE-2 Heavy-Output endpoint.

    Composes the N1 template + N2 portfolio + N3 reasoning + N4 filing
    window + N6 amendment alerts + N9 placeholder map into one fully-filled
    workpaper draft. NO LLM inference — pure SQLite + dict composition.

    Returns the canonical HE-2 envelope (template / filled_sections /
    legal_basis / filing_window / deadline / estimated_completion_pct /
    agent_next_actions / reasoning_chains / amendment_alerts_relevant /
    alternative_templates / billing / _disclaimer / _citation_envelope /
    _provenance). Always emits the §-aware disclaimer even on empty paths.
    1 ¥3 billable unit per call.
    """
    primary_input = {
        "artifact_type": artifact_type,
        "houjin_bangou": houjin_bangou,
        "segment": segment,
        "fiscal_year": fiscal_year,
        "auto_fill_level": auto_fill_level,
    }

    if auto_fill_level not in _AUTO_FILL_LEVELS:
        return _empty_envelope(
            primary_input=primary_input,
            rationale=f"auto_fill_level must be one of {list(_AUTO_FILL_LEVELS)}",
        )

    effective_segment = segment or _infer_segment(artifact_type)
    if effective_segment is None:
        return _empty_envelope(
            primary_input=primary_input,
            rationale=(
                f"Cannot infer segment for artifact_type={artifact_type!r}. "
                f"Pass segment explicitly (one of {list(_SEGMENTS_JA)})."
            ),
        )
    if effective_segment not in _SEGMENTS_JA:
        return _empty_envelope(
            primary_input=primary_input,
            rationale=f"segment must be one of {list(_SEGMENTS_JA)}",
        )

    # Skeleton mode without houjin_bangou is the documented agent path
    # for "show me what this workpaper looks like before I bind a client".
    is_skeleton = auto_fill_level == "skeleton" or not houjin_bangou

    loop = asyncio.get_event_loop()
    template_task = loop.run_in_executor(
        None, _fetch_template_sync, effective_segment, artifact_type
    )
    alt_task = loop.run_in_executor(
        None, _fetch_alternative_templates_sync, effective_segment, artifact_type
    )
    if not is_skeleton:
        portfolio_task = loop.run_in_executor(None, _fetch_portfolio_sync, houjin_bangou)
        reasoning_task = loop.run_in_executor(None, _fetch_reasoning_chains_sync, artifact_type, 5)
        window_task = loop.run_in_executor(
            None, _fetch_filing_window_sync, artifact_type, houjin_bangou
        )
        alerts_task = loop.run_in_executor(None, _fetch_amendment_alerts_sync, houjin_bangou, 90)
        (
            template,
            alt_templates,
            portfolio_payload,
            reasoning_chains,
            filing_window,
            amendment_alerts,
        ) = await asyncio.gather(
            template_task,
            alt_task,
            portfolio_task,
            reasoning_task,
            window_task,
            alerts_task,
        )
    else:
        template, alt_templates = await asyncio.gather(template_task, alt_task)
        portfolio_payload = {"portfolio": [], "summary": None}
        reasoning_chains = []
        filing_window = {
            "matches": [],
            "kind": _TYPE_TO_WINDOW_KIND.get(artifact_type),
            "address": None,
        }
        amendment_alerts = []

    if template is None:
        return _empty_envelope(
            primary_input=primary_input,
            rationale=(
                f"No template found for segment={effective_segment!r} "
                f"artifact_type={artifact_type!r} (am_artifact_templates lookup empty)."
            ),
            status="template_missing",
        )

    # Enumerate placeholder keys referenced in the template, then bulk-load
    # the N9 mapping rows in a single SELECT.
    placeholder_keys: set[str] = set()
    for p in template.get("placeholders", []) or []:
        if isinstance(p, dict) and "key" in p:
            placeholder_keys.add(p["key"])
    for section in template.get("structure", {}).get("sections", []) or []:
        if not isinstance(section, dict):
            continue
        for paragraph in section.get("paragraphs", []) or []:
            if isinstance(paragraph, str):
                placeholder_keys.update(_TOKEN_RE.findall(paragraph))

    placeholder_map = await loop.run_in_executor(
        None, _fetch_placeholder_map_sync, sorted(placeholder_keys)
    )

    # Build the resolution context bag. Session-supplied values + houjin +
    # fiscal_year + the deterministic CURRENT_DATE.
    context: dict[str, Any] = {
        "HOUJIN_BANGOU": houjin_bangou,
        "CURRENT_DATE": _today_iso(),
    }
    if fiscal_year is not None:
        context["FISCAL_YEAR"] = str(fiscal_year)

    filled_sections, total_placeholders, resolved_count = _compose_filled_sections(
        template,
        placeholder_map,
        context=context,
        auto_fill_level=auto_fill_level,
    )

    legal_basis = (
        _fetch_legal_basis_sync(template)
        if not is_skeleton
        else {
            "law_articles": [{"authority_text": template.get("authority"), "source": "template"}],
            "tsutatsu": [],
            "judgment_examples": [],
        }
    )

    deadline = _compute_deadline(artifact_type, fiscal_year)
    completion_pct = 0.0
    if total_placeholders > 0:
        completion_pct = round(resolved_count / total_placeholders, 2)

    next_actions = _agent_next_actions(
        template,
        filled_sections=filled_sections,
        filing_window=filing_window,
        deadline=deadline,
    )

    citation_envelope = {
        "law_articles": len(legal_basis["law_articles"]),
        "tsutatsu": len(legal_basis["tsutatsu"]),
        "judgment_examples": len(legal_basis["judgment_examples"]),
    }

    return {
        "tool_name": "prepare_implementation_workpaper",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "ok",
            "lane_id": _LANE_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "segment": effective_segment,
            "artifact_name_ja": template.get("artifact_name_ja"),
            "completion_pct": completion_pct,
            "is_skeleton": is_skeleton,
        },
        "artifact_type": artifact_type,
        "template": template,
        "filled_sections": filled_sections,
        "legal_basis": legal_basis,
        "filing_window": filing_window,
        "deadline": deadline,
        "estimated_completion_pct": completion_pct,
        "agent_next_actions": next_actions,
        "reasoning_chains": reasoning_chains,
        "amendment_alerts_relevant": amendment_alerts,
        "alternative_templates": alt_templates,
        "portfolio_context": portfolio_payload,
        "billing": {"unit": 1, "yen": 3, "auto_fill_level": auto_fill_level},
        "results": filled_sections,
        "total": len(filled_sections),
        "limit": len(filled_sections),
        "offset": 0,
        "citations": legal_basis["law_articles"][:5],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_he2_workpaper",
            "observed_at": today_iso_utc(),
            "composed_lanes": ["N1", "N2", "N3", "N4", "N6", "N9"],
            "total_placeholders": total_placeholders,
            "resolved_placeholders": resolved_count,
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
        "_citation_envelope": citation_envelope,
        "_provenance": {
            "lane_id": _LANE_ID,
            "composed_lanes": ["N1", "N2", "N3", "N4", "N6", "N9"],
            "template_id": template.get("template_id"),
            "template_version": template.get("version"),
            "observed_at": today_iso_utc(),
        },
    }


__all__ = ["prepare_implementation_workpaper"]


# Module-level sanity: the segment whitelist must match N1's whitelist.
assert set(_SEGMENTS_JA) == {"税理士", "会計士", "行政書士", "司法書士", "社労士"}
assert set(_AUTO_FILL_LEVELS) == {"skeleton", "partial", "deep"}
