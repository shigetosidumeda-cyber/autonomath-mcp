"""GET /v1/programs/{program_id}/full_context — cross-reference deep link bundle.

R8 / 2026-05-07 — bundles the *full primary-source context* of a program in
one GET so a customer LLM can answer "tell me everything about this 制度" in
a single call. The composite differs from sibling intel composites by being
*program-prefix native* (lives at /v1/programs/.../full_context, not at
/v1/intel/...) and by stitching `case_studies` (via JSIC) +
`court_decisions` (via shared LAW-* ids) + `enforcement_cases` (via
program-name hint) + `exclusion_rules` — none of which are joined in
`intel_program_full` or `intel_regulatory_context`.

Sections returned (in this order — keep the wire shape stable for downstream
agents that ``include_sections=...``-filter):

  * ``program``               primary metadata row (programs)
  * ``law_basis``             法令根拠 + 改正履歴 + 関連 article ranges
                              (program_law_refs ⨝ laws + am_amendment_diff
                              over LAW-* ids)
  * ``court_decisions``       関連判例 — court_decisions whose
                              ``related_law_ids_json`` overlaps the program's
                              law_unified_ids
  * ``case_studies``          同業 採択事例 — JSIC-prefix narrowed (dominant
                              from program if known; explicit
                              ``industry_jsic`` query overrides)
  * ``enforcement_cases``     関連 行政処分 — joined by ``program_name_hint``
                              + ``legal_basis`` LAW-* contains program's
                              authority refs
  * ``exclusion_rules``       排他 / prerequisite rules where this program
                              participates as A or B

NO LLM call. Pure SQLite SELECT + Python join across:

  - jpintel.db: programs / laws / program_law_refs / court_decisions /
    case_studies / enforcement_cases / exclusion_rules
  - autonomath.db (best-effort): am_amendment_diff (改正履歴 stream — soft
    fail when the volume is missing the table on a fresh fixture)

Hard constraints (memory ``feedback_no_operator_llm_api`` +
``feedback_destruction_free_organization``):

  * NO Anthropic API self-call. The customer LLM is the consumer.
  * Pure read. No writes to either DB.
  * Section-additive — adding sections to the response is safe; renaming
    or dropping is destructive and is forbidden.
  * Single ¥3 / call billing event regardless of section count.
  * §52 / §1 / §72 disclaimer envelope on every 200.

Mounted in ``api/main.py`` behind ``AUTONOMATH_EXPERIMENTAL_API_ENABLED`` so
the public OpenAPI export stays stable until R8 graduates.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._compact_envelope import to_compact, wants_compact
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.programs_full_context")

router = APIRouter(prefix="/v1/programs", tags=["programs"])
laws_cross_router = APIRouter(prefix="/v1/laws", tags=["laws"])
cases_cross_router = APIRouter(prefix="/v1/cases", tags=["case-studies"])

# ---------------------------------------------------------------------------
# Section enumeration. Keep stable — order is wire-stable for callers using
# ``include_sections=...&include_sections=...``.
# ---------------------------------------------------------------------------

_ALLOWED_SECTIONS: frozenset[str] = frozenset(
    {
        "program",
        "law_basis",
        "court_decisions",
        "case_studies",
        "enforcement_cases",
        "exclusion_rules",
    }
)
_DEFAULT_SECTIONS: tuple[str, ...] = (
    "program",
    "law_basis",
    "court_decisions",
    "case_studies",
    "enforcement_cases",
    "exclusion_rules",
)


# Sensitive disclaimer — full_context cuts across 法令解釈 / 税務助言 /
# 申請判断 / 行政処分 / 排他判定 territory; the bundle MUST carry the fence
# so the customer LLM never relays it as professional advice.
_FULL_CONTEXT_DISCLAIMER = (
    "本 response は jpcite の単一 program に対する複数 corpus (programs / laws / "
    "program_law_refs / am_amendment_diff / court_decisions / case_studies / "
    "enforcement_cases / exclusion_rules) の機械的 cross-join で、"
    "弁護士法 §72 (法令解釈) ・税理士法 §52 (税務助言) ・行政書士法 §1 (申請判断) "
    "・社労士法 §27 (労務助言) の代替ではありません。"
    "判例 / 行政処分 / 採択事例 は 1次資料の検索結果のみを surface しており、"
    "事実認定・適用判断は資格を有する弁護士・税理士・行政書士・診断士に "
    "primary source 確認の上ご相談ください。"
)


# Sentinel used by the legacy_intel-style ``citations.law`` shape so the
# downstream consumer can reliably enumerate the keyset.
_EMPTY_LIST: list[Any] = []


# ---------------------------------------------------------------------------
# Helpers — DB connection / table existence / parsing
# ---------------------------------------------------------------------------


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Best-effort read-only handle to autonomath.db.

    Returns None when the volume is missing (fresh test fixture) so the
    endpoint can degrade to jpintel-only sections instead of raising.
    """
    try:
        from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

        return connect_autonomath()
    except Exception as exc:  # noqa: BLE001 — never let DB open break the call
        logger.debug("autonomath.db unavailable: %s", exc)
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _json_list(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(x) for x in parsed if x is not None]


def _truncate(text: Any, limit: int) -> str | None:
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _section_program(
    conn: sqlite3.Connection,
    *,
    program_id: str,
    missing: list[str],
) -> dict[str, Any] | None:
    """Pull the program metadata row from `programs`.

    Returns None when the program is absent — drives the 404 path.
    """
    if not _table_exists(conn, "programs"):
        missing.append("programs")
        return None
    try:
        row = conn.execute(
            "SELECT unified_id, primary_name, tier, prefecture, municipality, "
            "       authority_level, authority_name, program_kind, "
            "       official_url, source_url, "
            "       amount_max_man_yen, amount_min_man_yen, subsidy_rate, "
            "       target_types_json, funding_purpose_json, "
            "       application_window_json, excluded, exclusion_reason, "
            "       updated_at "
            "  FROM programs "
            " WHERE unified_id = ? LIMIT 1",
            (program_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("programs lookup failed: %s", exc)
        return None
    if row is None:
        return None
    primary_url = row["source_url"] or row["official_url"]
    amax = row["amount_max_man_yen"]
    amin = row["amount_min_man_yen"]
    return {
        "program_id": row["unified_id"],
        "primary_name": row["primary_name"],
        "tier": row["tier"],
        "prefecture": row["prefecture"],
        "municipality": row["municipality"],
        "authority_level": row["authority_level"],
        "authority_name": row["authority_name"],
        "program_kind": row["program_kind"],
        "primary_url": primary_url,
        "expected_amount_max_yen": int(amax * 10000) if amax is not None else None,
        "expected_amount_min_yen": int(amin * 10000) if amin is not None else None,
        "subsidy_rate": row["subsidy_rate"],
        "target_types": _json_list(row["target_types_json"]),
        "funding_purpose": _json_list(row["funding_purpose_json"]),
        "application_window_json": row["application_window_json"],
        "excluded": bool(row["excluded"]),
        "exclusion_reason": row["exclusion_reason"],
        "updated_at": row["updated_at"],
    }


def _section_law_basis(
    conn: sqlite3.Connection,
    am_conn: sqlite3.Connection | None,
    *,
    program_id: str,
    max_per_section: int,
    missing: list[str],
) -> dict[str, Any] | None:
    """法令根拠 + 改正履歴.

    Walks ``program_law_refs`` ⨝ ``laws`` for the program, then for each
    LAW-* id pulls the recent ``am_amendment_diff`` rows so the LLM gets
    a single bundle of "this is the 根拠条文 and this is how it has changed".

    Returns None only when ``program_law_refs`` is missing entirely.
    """
    if not _table_exists(conn, "program_law_refs"):
        missing.append("program_law_refs")
        return None
    if not _table_exists(conn, "laws"):
        missing.append("laws")
        # Still surface the refs without name enrichment.

    try:
        rows = conn.execute(
            "SELECT plr.law_unified_id      AS law_unified_id, "
            "       plr.ref_kind            AS ref_kind, "
            "       plr.article_citation    AS article_citation, "
            "       plr.source_url          AS plr_source_url, "
            "       plr.confidence          AS confidence, "
            "       plr.fetched_at          AS fetched_at, "
            "       l.law_title             AS law_title, "
            "       l.law_number            AS law_number, "
            "       l.law_type              AS law_type, "
            "       l.ministry              AS ministry, "
            "       l.last_amended_date     AS last_amended_date, "
            "       l.revision_status       AS revision_status, "
            "       l.superseded_by_law_id  AS superseded_by_law_id, "
            "       l.full_text_url         AS full_text_url "
            "  FROM program_law_refs plr "
            "  LEFT JOIN laws l ON l.unified_id = plr.law_unified_id "
            " WHERE plr.program_unified_id = ? "
            " ORDER BY CASE plr.ref_kind "
            "             WHEN 'authority'   THEN 0 "
            "             WHEN 'eligibility' THEN 1 "
            "             WHEN 'exclusion'   THEN 2 "
            "             WHEN 'penalty'     THEN 3 "
            "             WHEN 'reference'   THEN 4 "
            "             ELSE 5 END, "
            "          plr.confidence DESC, "
            "          plr.law_unified_id ASC "
            " LIMIT ?",
            (program_id, max_per_section),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("law_basis query failed: %s", exc)
        return None

    laws_out: list[dict[str, Any]] = []
    law_ids: list[str] = []
    for r in rows:
        law_id = r["law_unified_id"]
        if law_id and law_id not in law_ids:
            law_ids.append(law_id)
        laws_out.append(
            {
                "law_unified_id": law_id,
                "law_title": r["law_title"],
                "law_number": r["law_number"],
                "law_type": r["law_type"],
                "ministry": r["ministry"],
                "ref_kind": r["ref_kind"],
                "article_citation": r["article_citation"],
                "last_amended_date": r["last_amended_date"],
                "revision_status": r["revision_status"],
                "superseded_by_law_id": r["superseded_by_law_id"],
                "full_text_url": r["full_text_url"],
                "confidence": r["confidence"],
                "fetched_at": r["fetched_at"],
                "source_url": r["plr_source_url"],
            }
        )

    # 改正履歴: scan am_amendment_diff for each LAW-* id (entity_id keyed).
    amendments: list[dict[str, Any]] = []
    if am_conn is not None and law_ids and _table_exists(am_conn, "am_amendment_diff"):
        placeholders = ",".join("?" for _ in law_ids)
        try:
            arows = am_conn.execute(
                f"SELECT entity_id, field_name, prev_value, new_value, "
                f"       detected_at, source_url "
                f"  FROM am_amendment_diff "
                f" WHERE entity_id IN ({placeholders}) "
                f"    OR entity_id = ? "
                f" ORDER BY detected_at DESC "
                f" LIMIT ?",
                (*law_ids, program_id, max_per_section),
            ).fetchall()
            for r in arows:
                prev = r["prev_value"]
                new = r["new_value"]
                if prev is None and new is not None:
                    change_type = "created"
                elif new is None and prev is not None:
                    change_type = "removed"
                else:
                    change_type = "modified"
                amendments.append(
                    {
                        "entity_id": r["entity_id"],
                        "field_name": r["field_name"],
                        "change_type": change_type,
                        "prev_value": _truncate(prev, 200),
                        "new_value": _truncate(new, 200),
                        "detected_at": r["detected_at"],
                        "evidence_url": r["source_url"],
                    }
                )
        except sqlite3.Error as exc:
            logger.warning("am_amendment_diff query failed: %s", exc)
    elif am_conn is None:
        missing.append("autonomath_db")
    elif not _table_exists(am_conn, "am_amendment_diff"):
        missing.append("am_amendment_diff")

    return {
        "laws": laws_out,
        "amendment_history": amendments,
        "law_unified_ids": law_ids,
    }


def _section_court_decisions(
    conn: sqlite3.Connection,
    *,
    law_unified_ids: list[str],
    max_per_section: int,
    missing: list[str],
) -> list[dict[str, Any]] | None:
    """関連判例.

    Find court_decisions whose related_law_ids_json overlaps the program's
    law refs. Uses LIKE on the JSON text — same shape as the existing
    /v1/court-decisions/by-law endpoint. Pre-filtering by index hits via
    ``idx_court_decisions_subject_area`` is not possible because the
    overlap key lives in JSON. Fall back to a single LIKE per law_id and
    union the result; cap by ``max_per_section`` total.
    """
    if not _table_exists(conn, "court_decisions"):
        missing.append("court_decisions")
        return None
    if not law_unified_ids:
        return []

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for law_id in law_unified_ids:
        if len(out) >= max_per_section:
            break
        try:
            rows = conn.execute(
                "SELECT unified_id, case_name, case_number, court, court_level, "
                "       decision_date, decision_type, subject_area, "
                "       related_law_ids_json, key_ruling, impact_on_business, "
                "       precedent_weight, full_text_url, source_url, "
                "       source_excerpt, confidence "
                "  FROM court_decisions "
                " WHERE COALESCE(related_law_ids_json, '') LIKE ? "
                " ORDER BY CASE precedent_weight "
                "             WHEN 'binding'       THEN 0 "
                "             WHEN 'persuasive'    THEN 1 "
                "             WHEN 'informational' THEN 2 "
                "             ELSE 3 END, "
                "          decision_date DESC NULLS LAST, "
                "          unified_id ASC "
                " LIMIT ?",
                (f"%{law_id}%", max_per_section),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("court_decisions query failed for %s: %s", law_id, exc)
            continue
        for r in rows:
            uid = r["unified_id"]
            if uid in seen:
                continue
            seen.add(uid)
            out.append(
                {
                    "unified_id": uid,
                    "case_name": r["case_name"],
                    "case_number": r["case_number"],
                    "court": r["court"],
                    "court_level": r["court_level"],
                    "decision_date": r["decision_date"],
                    "decision_type": r["decision_type"],
                    "subject_area": r["subject_area"],
                    "related_law_ids": _json_list(r["related_law_ids_json"]),
                    "key_ruling": _truncate(r["key_ruling"], 400),
                    "impact_on_business": _truncate(r["impact_on_business"], 400),
                    "precedent_weight": r["precedent_weight"],
                    "primary_url": r["full_text_url"] or r["source_url"],
                    "source_excerpt": _truncate(r["source_excerpt"], 200),
                    "confidence": r["confidence"],
                }
            )
            if len(out) >= max_per_section:
                break
    return out


def _section_case_studies(
    conn: sqlite3.Connection,
    *,
    program_meta: dict[str, Any] | None,
    industry_jsic: str | None,
    prefecture: str | None,
    max_per_section: int,
    missing: list[str],
) -> list[dict[str, Any]] | None:
    """同業 採択事例.

    Narrow case_studies by JSIC industry + optional prefecture. The
    explicit query parameters override; otherwise we infer JSIC + prefecture
    from the program metadata if they are populated. When both are unknown,
    fall back to a programs_used_json LIKE search for the program's
    primary_name (best-effort linkage; ~17% of case_studies rows carry the
    program name in the json list).
    """
    if not _table_exists(conn, "case_studies"):
        missing.append("case_studies")
        return None

    where: list[str] = []
    params: list[Any] = []
    if industry_jsic:
        where.append("industry_jsic LIKE ?")
        params.append(f"{industry_jsic}%")
    if prefecture:
        where.append("prefecture = ?")
        params.append(prefecture)

    # Always also try matching by program_name in programs_used_json so the
    # caller gets program-anchored hits even when JSIC is unknown.
    program_name = program_meta.get("primary_name") if program_meta else None

    rows: list[sqlite3.Row] = []
    try:
        if where:
            sql = (
                "SELECT case_id, company_name, houjin_bangou, is_sole_proprietor, "
                "       prefecture, municipality, industry_jsic, industry_name, "
                "       employees, founded_year, capital_yen, "
                "       case_title, case_summary, programs_used_json, "
                "       total_subsidy_received_yen, outcomes_json, patterns_json, "
                "       publication_date, source_url, source_excerpt, "
                "       fetched_at, confidence "
                "  FROM case_studies "
                f" WHERE {' AND '.join(where)} "
                " ORDER BY publication_date DESC NULLS LAST, case_id ASC "
                " LIMIT ?"
            )
            rows = list(conn.execute(sql, (*params, max_per_section)).fetchall())
        if program_name and len(rows) < max_per_section:
            extra_limit = max_per_section - len(rows)
            seen = {r["case_id"] for r in rows}
            extra_sql = (
                "SELECT case_id, company_name, houjin_bangou, is_sole_proprietor, "
                "       prefecture, municipality, industry_jsic, industry_name, "
                "       employees, founded_year, capital_yen, "
                "       case_title, case_summary, programs_used_json, "
                "       total_subsidy_received_yen, outcomes_json, patterns_json, "
                "       publication_date, source_url, source_excerpt, "
                "       fetched_at, confidence "
                "  FROM case_studies "
                " WHERE COALESCE(programs_used_json, '') LIKE ? "
                " ORDER BY publication_date DESC NULLS LAST, case_id ASC "
                " LIMIT ?"
            )
            for r in conn.execute(extra_sql, (f"%{program_name}%", extra_limit)).fetchall():
                if r["case_id"] in seen:
                    continue
                rows.append(r)
                seen.add(r["case_id"])
                if len(rows) >= max_per_section:
                    break
    except sqlite3.Error as exc:
        logger.warning("case_studies query failed: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        sole = r["is_sole_proprietor"]
        out.append(
            {
                "case_id": r["case_id"],
                "company_name": r["company_name"],
                "houjin_bangou": r["houjin_bangou"],
                "is_sole_proprietor": None if sole is None else bool(sole),
                "prefecture": r["prefecture"],
                "municipality": r["municipality"],
                "industry_jsic": r["industry_jsic"],
                "industry_name": r["industry_name"],
                "employees": r["employees"],
                "founded_year": r["founded_year"],
                "capital_yen": r["capital_yen"],
                "case_title": r["case_title"],
                "case_summary": _truncate(r["case_summary"], 400),
                "programs_used": _json_list(r["programs_used_json"]),
                "total_subsidy_received_yen": r["total_subsidy_received_yen"],
                "publication_date": r["publication_date"],
                "source_url": r["source_url"],
                "source_excerpt": _truncate(r["source_excerpt"], 200),
                "confidence": r["confidence"],
            }
        )
    return out


def _section_enforcement(
    conn: sqlite3.Connection,
    *,
    program_meta: dict[str, Any] | None,
    law_unified_ids: list[str],
    max_per_section: int,
    missing: list[str],
) -> list[dict[str, Any]] | None:
    """関連 行政処分.

    Two predicates joined by UNION-then-dedupe:
      1. ``program_name_hint`` LIKE the program's primary_name
      2. ``legal_basis`` LIKE any of the program's authority law refs
    Either signal is sufficient; rows are de-duped on case_id.
    """
    if not _table_exists(conn, "enforcement_cases"):
        missing.append("enforcement_cases")
        return None

    program_name = program_meta.get("primary_name") if program_meta else None
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    def _emit_rows(rows: list[sqlite3.Row]) -> None:
        for r in rows:
            cid = r["case_id"]
            if cid in seen:
                continue
            seen.add(cid)
            sole = r["is_sole_proprietor"]
            out.append(
                {
                    "case_id": cid,
                    "event_type": r["event_type"],
                    "program_name_hint": r["program_name_hint"],
                    "recipient_name": r["recipient_name"],
                    "recipient_houjin_bangou": r["recipient_houjin_bangou"],
                    "is_sole_proprietor": None if sole is None else bool(sole),
                    "prefecture": r["prefecture"],
                    "ministry": r["ministry"],
                    "amount_yen": r["amount_yen"],
                    "amount_improper_grant_yen": r["amount_improper_grant_yen"],
                    "reason_excerpt": _truncate(r["reason_excerpt"], 300),
                    "legal_basis": r["legal_basis"],
                    "source_url": r["source_url"],
                    "disclosed_date": r["disclosed_date"],
                    "confidence": r["confidence"],
                }
            )

    try:
        if program_name:
            rows = conn.execute(
                "SELECT case_id, event_type, program_name_hint, recipient_name, "
                "       recipient_houjin_bangou, is_sole_proprietor, prefecture, "
                "       ministry, amount_yen, amount_improper_grant_yen, "
                "       reason_excerpt, legal_basis, source_url, disclosed_date, "
                "       confidence "
                "  FROM enforcement_cases "
                " WHERE COALESCE(program_name_hint,'') LIKE ? "
                " ORDER BY disclosed_date DESC NULLS LAST, case_id ASC "
                " LIMIT ?",
                (f"%{program_name}%", max_per_section),
            ).fetchall()
            _emit_rows(rows)
        for law_id in law_unified_ids:
            if len(out) >= max_per_section:
                break
            rows = conn.execute(
                "SELECT case_id, event_type, program_name_hint, recipient_name, "
                "       recipient_houjin_bangou, is_sole_proprietor, prefecture, "
                "       ministry, amount_yen, amount_improper_grant_yen, "
                "       reason_excerpt, legal_basis, source_url, disclosed_date, "
                "       confidence "
                "  FROM enforcement_cases "
                " WHERE COALESCE(legal_basis,'') LIKE ? "
                " ORDER BY disclosed_date DESC NULLS LAST, case_id ASC "
                " LIMIT ?",
                (f"%{law_id}%", max_per_section - len(out)),
            ).fetchall()
            _emit_rows(rows)
    except sqlite3.Error as exc:
        logger.warning("enforcement_cases query failed: %s", exc)
        return out

    return out[:max_per_section]


def _section_exclusions(
    conn: sqlite3.Connection,
    *,
    program_meta: dict[str, Any] | None,
    program_id: str,
    max_per_section: int,
    missing: list[str],
) -> list[dict[str, Any]] | None:
    """排他ルール — exclusion_rules where the program participates as A or B.

    The table keys on ``program_a`` / ``program_b`` (free-text primary_name
    historically; migration 051 added ``program_a_uid`` / ``program_b_uid``
    so we walk both axes). Returns rows that mention the program by either
    unified_id or primary_name.
    """
    if not _table_exists(conn, "exclusion_rules"):
        missing.append("exclusion_rules")
        return None

    name = program_meta.get("primary_name") if program_meta else None
    params: list[Any] = [program_id, program_id]
    where = (
        "(COALESCE(program_a_uid, '') = ? OR COALESCE(program_b_uid, '') = ?"
    )
    if name:
        where += " OR program_a = ? OR program_b = ?"
        params.extend([name, name])
    where += ")"
    try:
        rows = conn.execute(
            "SELECT rule_id, kind, severity, program_a, program_b, "
            "       program_a_uid, program_b_uid, "
            "       program_b_group_json, description, "
            "       source_notes, source_urls_json, extra_json "
            "  FROM exclusion_rules "
            f" WHERE {where} "
            " ORDER BY CASE severity "
            "             WHEN 'critical' THEN 0 "
            "             WHEN 'high'     THEN 1 "
            "             WHEN 'medium'   THEN 2 "
            "             WHEN 'low'      THEN 3 "
            "             ELSE 4 END, "
            "          rule_id ASC "
            " LIMIT ?",
            (*params, max_per_section),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("exclusion_rules query failed: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "rule_id": r["rule_id"],
                "kind": r["kind"],
                "severity": r["severity"],
                "program_a": r["program_a"],
                "program_b": r["program_b"],
                "program_a_uid": r["program_a_uid"],
                "program_b_uid": r["program_b_uid"],
                "program_b_group": _json_list(r["program_b_group_json"]),
                "description": _truncate(r["description"], 300),
                "source_notes": _truncate(r["source_notes"], 200),
                "source_urls": _json_list(r["source_urls_json"]),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Composite assembly
# ---------------------------------------------------------------------------


def _build_full_context(
    conn: sqlite3.Connection,
    *,
    program_id: str,
    include_sections: tuple[str, ...],
    max_per_section: int,
    industry_jsic: str | None,
    prefecture: str | None,
) -> tuple[dict[str, Any], list[str], bool]:
    """Build the cross-reference envelope.

    Returns (body_dict, missing_tables, program_found).
    """
    missing: list[str] = []
    body: dict[str, Any] = {
        "program_id": program_id,
        "include_sections": list(include_sections),
        "max_per_section": max_per_section,
        "industry_jsic": industry_jsic,
        "prefecture": prefecture,
    }

    # Always run program meta first to drive 404 + as input to other sections.
    program_meta = _section_program(conn, program_id=program_id, missing=missing)
    program_found = program_meta is not None
    if "program" in include_sections:
        body["program"] = program_meta

    am_conn = _open_autonomath_ro()
    try:
        law_basis: dict[str, Any] | None = None
        law_unified_ids: list[str] = []
        if "law_basis" in include_sections or "court_decisions" in include_sections \
           or "enforcement_cases" in include_sections:
            law_basis = _section_law_basis(
                conn,
                am_conn,
                program_id=program_id,
                max_per_section=max_per_section,
                missing=missing,
            )
            if law_basis:
                law_unified_ids = list(law_basis.get("law_unified_ids") or [])
        if "law_basis" in include_sections:
            body["law_basis"] = law_basis

        if "court_decisions" in include_sections:
            body["court_decisions"] = _section_court_decisions(
                conn,
                law_unified_ids=law_unified_ids,
                max_per_section=max_per_section,
                missing=missing,
            )

        if "case_studies" in include_sections:
            body["case_studies"] = _section_case_studies(
                conn,
                program_meta=program_meta,
                industry_jsic=industry_jsic,
                prefecture=prefecture,
                max_per_section=max_per_section,
                missing=missing,
            )

        if "enforcement_cases" in include_sections:
            body["enforcement_cases"] = _section_enforcement(
                conn,
                program_meta=program_meta,
                law_unified_ids=law_unified_ids,
                max_per_section=max_per_section,
                missing=missing,
            )

        if "exclusion_rules" in include_sections:
            body["exclusion_rules"] = _section_exclusions(
                conn,
                program_meta=program_meta,
                program_id=program_id,
                max_per_section=max_per_section,
                missing=missing,
            )
    finally:
        if am_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                am_conn.close()

    body["data_quality"] = {"missing_tables": sorted(set(missing))}
    return body, missing, program_found


# ---------------------------------------------------------------------------
# Endpoint 1 — /v1/programs/{program_id}/full_context
# ---------------------------------------------------------------------------


@router.get(
    "/{program_id}/full_context",
    summary="Cross-reference deep link bundle — program → 法令根拠 → 改正履歴 → 関連判例 → 同業 採択事例 → 行政処分 → 排他ルール",
    description=(
        "Bundles the full primary-source context of a program in 1 call. "
        "Returns `program` metadata + `law_basis` (法令根拠 + 改正履歴) + "
        "`court_decisions` (関連判例 via shared LAW-* ids) + `case_studies` "
        "(同業 採択事例 narrowed by JSIC + prefecture) + `enforcement_cases` "
        "(関連 行政処分 via program_name_hint or legal_basis) + "
        "`exclusion_rules` (排他 + prerequisite). Sections are individually "
        "selectable via `?include_sections=...&include_sections=...`.\n\n"
        "**Pricing:** ¥3 / call (1 unit) regardless of section count.\n\n"
        "**Sensitive:** §72 / §52 / §1 / §27 disclaimer envelope. NO LLM call. "
        "Pure SQLite + Python over jpintel (programs / laws / "
        "program_law_refs / court_decisions / case_studies / "
        "enforcement_cases / exclusion_rules) and best-effort autonomath "
        "(am_amendment_diff for 改正履歴).\n\n"
        "**Why this endpoint:** the existing /v1/intel/program/{id}/full "
        "composite returns intel-anchored sections (eligibility / adoptions "
        "/ similar) but does NOT join case_studies / court_decisions / "
        "enforcement_cases / exclusion_rules to the program. This endpoint "
        "is the cross-reference walk a customer LLM needs for "
        "「制度の全文脈」 in a single GET."
    ),
    responses={
        200: {"description": "Cross-reference envelope."},
        404: {
            "description": (
                "Program not found in jpintel programs. Verify via "
                "/v1/programs/search."
            )
        },
        422: {"description": "Invalid include_sections / max_per_section."},
    },
)
def get_program_full_context(
    program_id: Annotated[
        str,
        PathParam(
            description=(
                "Program canonical id (UNI-... form on jpintel.programs)."
            ),
            min_length=1,
            max_length=200,
        ),
    ],
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    include_sections: Annotated[
        list[str] | None,
        Query(
            description=(
                "Sections to include. Repeat the param to multi-select. "
                "Allowed: program, law_basis, court_decisions, "
                "case_studies, enforcement_cases, exclusion_rules. "
                "Defaults to all 6."
            ),
        ),
    ] = None,
    max_per_section: Annotated[
        int,
        Query(
            ge=1,
            le=50,
            description=(
                "Per-section row cap (1..50, default 10). Applies to every "
                "list-shaped section."
            ),
        ),
    ] = 10,
    industry_jsic: Annotated[
        str | None,
        Query(
            description=(
                "JSIC industry code prefix (e.g. 'A' / '05' / '0111') used to "
                "narrow case_studies. Overrides the program-derived JSIC. "
                "Pass empty to disable JSIC narrowing."
            ),
            max_length=10,
        ),
    ] = None,
    prefecture: Annotated[
        str | None,
        Query(
            description=(
                "Prefecture filter for case_studies (e.g. '東京都'). "
                "Overrides the program-derived prefecture."
            ),
            max_length=10,
        ),
    ] = None,
) -> JSONResponse:
    _t0 = time.perf_counter()

    pid = (program_id or "").strip()
    if not pid:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_program_id",
                "field": "program_id",
                "message": "program_id must be a non-empty unified_id (UNI-...).",
            },
        )

    requested = tuple(include_sections) if include_sections else _DEFAULT_SECTIONS
    bad = [s for s in requested if s not in _ALLOWED_SECTIONS]
    if bad:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_include_sections",
                "field": "include_sections",
                "message": (
                    f"include_sections contains unknown values: {bad}. "
                    f"Allowed: {sorted(_ALLOWED_SECTIONS)}."
                ),
            },
        )
    seen: list[str] = []
    for s in requested:
        if s not in seen:
            seen.append(s)
    sections_tuple = tuple(seen)

    body, _missing, program_found = _build_full_context(
        conn,
        program_id=pid,
        include_sections=sections_tuple,
        max_per_section=max_per_section,
        industry_jsic=industry_jsic,
        prefecture=prefecture,
    )

    if "program" in sections_tuple and not program_found:
        raise HTTPException(
            status_code=404,
            detail=(
                f"program_id={pid!r} not found in jpintel programs. "
                "Verify via /v1/programs/search."
            ),
        )

    body["_disclaimer"] = _FULL_CONTEXT_DISCLAIMER
    body["_billing_unit"] = 1
    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "programs.full_context",
        latency_ms=latency_ms,
        result_count=1 if program_found else 0,
        params={
            "program_id": pid,
            "include_sections": list(sections_tuple),
            "max_per_section": max_per_section,
            "industry_jsic": industry_jsic,
            "prefecture": prefecture,
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="programs.full_context",
        request_params={
            "program_id": pid,
            "include_sections": list(sections_tuple),
            "max_per_section": max_per_section,
            "industry_jsic": industry_jsic,
            "prefecture": prefecture,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )

    if wants_compact(request):
        body = to_compact(body)

    return JSONResponse(content=body)


# ---------------------------------------------------------------------------
# Endpoint 2 — /v1/laws/{law_id}/related_programs (cross-program reverse lookup)
#
# Distinct from the existing /v1/laws/{unified_id}/related-programs (hyphen
# form). The hyphen endpoint surfaces the direct program_law_refs edge
# only. This underscore endpoint additionally exposes:
#   * the law metadata header
#   * a per-ref_kind bucket count (authority / eligibility / exclusion / ...)
#   * the law_unified_ids in scope (single LAW-* + any superseded chain)
# so a customer LLM can answer "every program that cites this statute or
# its predecessors" in a single call.
# ---------------------------------------------------------------------------


@laws_cross_router.get(
    "/{law_id}/related_programs",
    summary="Reverse lookup — every program citing this law (cross-revision walk + ref_kind buckets)",
    description=(
        "Reverse lookup of programs citing a law. Surfaces the law header "
        "+ ref_kind histogram + every program that cites the law (or any "
        "superseded predecessor in the revision chain). Distinct from "
        "/v1/laws/{unified_id}/related-programs (the hyphen form returns "
        "the bare program_law_refs edge); this underscore form adds the "
        "header + histogram + cross-revision walk so a customer LLM can "
        "trace the full reverse program graph in 1 call.\n\n"
        "**Pricing:** ¥3 / call. NO LLM. Pure SQLite over laws + "
        "program_law_refs."
    ),
    responses={
        200: {"description": "Law metadata + ref_kind buckets + program list."},
        404: {"description": "law_id not found."},
        422: {"description": "Invalid query parameter."},
    },
)
def get_law_related_programs(
    law_id: Annotated[
        str,
        PathParam(
            description="Law canonical id (LAW-... form on jpintel.laws).",
            min_length=1,
            max_length=200,
        ),
    ],
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    include_superseded: Annotated[
        bool,
        Query(
            description=(
                "Walk superseded_by_law_id chain (both directions) and "
                "include refs against any law in the chain. Default true "
                "so the customer LLM gets the full historical surface."
            ),
        ),
    ] = True,
    ref_kind: Annotated[
        str | None,
        Query(
            description=(
                "Filter by citation kind (authority / eligibility / "
                "exclusion / reference / penalty). Omit for all kinds."
            ),
            max_length=20,
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    _t0 = time.perf_counter()

    if not _table_exists(conn, "laws"):
        raise HTTPException(
            status_code=503,
            detail="laws table missing on this volume.",
        )

    law_row = conn.execute(
        "SELECT unified_id, law_title, law_number, law_type, ministry, "
        "       last_amended_date, revision_status, superseded_by_law_id, "
        "       full_text_url, source_url "
        "  FROM laws WHERE unified_id = ? LIMIT 1",
        (law_id,),
    ).fetchone()
    if law_row is None:
        raise HTTPException(status_code=404, detail=f"law not found: {law_id}")

    allowed_kinds = {"authority", "eligibility", "exclusion", "reference", "penalty"}
    if ref_kind is not None and ref_kind not in allowed_kinds:
        raise HTTPException(
            status_code=422,
            detail=(
                f"ref_kind must be one of {sorted(allowed_kinds)}, "
                f"got {ref_kind!r}"
            ),
        )

    # Walk supersession chain both ways. We stop at depth 16 to bound
    # pathological cycles (none exist in production but the test fixture
    # could in principle).
    chain_ids: list[str] = [law_id]
    visited: set[str] = {law_id}
    if include_superseded:
        # Forward walk: superseded_by_law_id chain.
        cur = law_row["superseded_by_law_id"]
        steps = 0
        while cur and cur not in visited and steps < 16:
            chain_ids.append(cur)
            visited.add(cur)
            steps += 1
            try:
                nrow = conn.execute(
                    "SELECT superseded_by_law_id FROM laws WHERE unified_id = ?",
                    (cur,),
                ).fetchone()
            except sqlite3.Error:
                break
            cur = nrow["superseded_by_law_id"] if nrow else None
        # Reverse walk: laws that supersede the original id.
        try:
            rows = conn.execute(
                "SELECT unified_id FROM laws WHERE superseded_by_law_id = ?",
                (law_id,),
            ).fetchall()
            for r in rows:
                if r["unified_id"] and r["unified_id"] not in visited:
                    chain_ids.append(r["unified_id"])
                    visited.add(r["unified_id"])
        except sqlite3.Error:
            pass

    placeholders = ",".join("?" for _ in chain_ids)
    where_parts = [f"plr.law_unified_id IN ({placeholders})"]
    params: list[Any] = list(chain_ids)
    if ref_kind is not None:
        where_parts.append("plr.ref_kind = ?")
        params.append(ref_kind)
    where_sql = " AND ".join(where_parts)

    histogram: dict[str, int] = {k: 0 for k in allowed_kinds}
    try:
        for r in conn.execute(
            f"SELECT plr.ref_kind, COUNT(*) AS n "
            f"  FROM program_law_refs plr "
            f" WHERE plr.law_unified_id IN ({placeholders}) "
            f" GROUP BY plr.ref_kind",
            tuple(chain_ids),
        ).fetchall():
            histogram[r["ref_kind"]] = int(r["n"])
    except sqlite3.Error as exc:
        logger.warning("histogram query failed: %s", exc)

    try:
        (total,) = conn.execute(
            f"SELECT COUNT(*) FROM program_law_refs plr WHERE {where_sql}",
            tuple(params),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("count query failed: %s", exc)
        total = 0

    try:
        rows = conn.execute(
            f"SELECT plr.program_unified_id AS program_unified_id, "
            f"       plr.law_unified_id     AS law_unified_id, "
            f"       plr.ref_kind           AS ref_kind, "
            f"       plr.article_citation   AS article_citation, "
            f"       plr.source_url         AS source_url, "
            f"       plr.fetched_at         AS fetched_at, "
            f"       plr.confidence         AS confidence, "
            f"       p.primary_name         AS program_name, "
            f"       p.tier                 AS tier, "
            f"       p.prefecture           AS prefecture, "
            f"       p.authority_level      AS authority_level, "
            f"       p.program_kind         AS program_kind "
            f"  FROM program_law_refs plr "
            f"  LEFT JOIN programs p ON p.unified_id = plr.program_unified_id "
            f" WHERE {where_sql} "
            f" ORDER BY CASE plr.ref_kind "
            f"             WHEN 'authority'   THEN 0 "
            f"             WHEN 'eligibility' THEN 1 "
            f"             WHEN 'exclusion'   THEN 2 "
            f"             WHEN 'penalty'     THEN 3 "
            f"             WHEN 'reference'   THEN 4 "
            f"             ELSE 5 END, "
            f"          plr.confidence DESC, "
            f"          plr.program_unified_id ASC "
            f" LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("related programs query failed: %s", exc)
        rows = []

    results: list[dict[str, Any]] = []
    for r in rows:
        results.append(
            {
                "program_unified_id": r["program_unified_id"],
                "program_name": r["program_name"],
                "law_unified_id": r["law_unified_id"],
                "ref_kind": r["ref_kind"],
                "article_citation": r["article_citation"],
                "source_url": r["source_url"],
                "fetched_at": r["fetched_at"],
                "confidence": r["confidence"],
                "tier": r["tier"],
                "prefecture": r["prefecture"],
                "authority_level": r["authority_level"],
                "program_kind": r["program_kind"],
            }
        )

    body: dict[str, Any] = {
        "law": {
            "law_unified_id": law_row["unified_id"],
            "law_title": law_row["law_title"],
            "law_number": law_row["law_number"],
            "law_type": law_row["law_type"],
            "ministry": law_row["ministry"],
            "last_amended_date": law_row["last_amended_date"],
            "revision_status": law_row["revision_status"],
            "superseded_by_law_id": law_row["superseded_by_law_id"],
            "primary_url": law_row["full_text_url"] or law_row["source_url"],
        },
        "chain_law_unified_ids": chain_ids,
        "ref_kind_histogram": histogram,
        "include_superseded": include_superseded,
        "ref_kind_filter": ref_kind,
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "results": results,
        "_disclaimer": _FULL_CONTEXT_DISCLAIMER,
        "_billing_unit": 1,
    }
    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "laws.related_programs_cross",
        latency_ms=latency_ms,
        result_count=len(results),
        params={
            "law_id": law_id,
            "include_superseded": include_superseded,
            "ref_kind": ref_kind,
            "limit": limit,
            "offset": offset,
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="laws.related_programs_cross",
        request_params={
            "law_id": law_id,
            "include_superseded": include_superseded,
            "ref_kind": ref_kind,
            "limit": limit,
            "offset": offset,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )

    if wants_compact(request):
        body = to_compact(body)

    return JSONResponse(content=body)


# ---------------------------------------------------------------------------
# Endpoint 3 — /v1/cases/by_industry_size_pref (cross-axis case_studies narrow)
# ---------------------------------------------------------------------------


@cases_cross_router.get(
    "/by_industry_size_pref",
    summary="採択事例 narrow — 業種 (JSIC) × 規模 (employees / capital) × 都道府県 1 call",
    description=(
        "Surface 採択事例 (case_studies) narrowed by 3-axis intersection: "
        "JSIC industry prefix + employees / capital band + prefecture. "
        "Use to answer 「うちと同業 × 同規模 × 同地域 で実際に取れた事例」 "
        "in 1 call. Pure SQLite over the 2,286-row case_studies corpus.\n\n"
        "**Pricing:** ¥3 / call. NO LLM."
    ),
    responses={
        200: {"description": "Paginated narrow case_studies result."},
        422: {"description": "Invalid query parameter."},
    },
)
def get_cases_by_industry_size_pref(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    industry_jsic: Annotated[
        str | None,
        Query(
            description=(
                "JSIC industry code prefix (e.g. 'A' / '05' / '0111'). "
                "Matches with LIKE '<prefix>%'."
            ),
            max_length=10,
        ),
    ] = None,
    prefecture: Annotated[
        str | None,
        Query(
            description="Prefecture exact match (e.g. '東京都').",
            max_length=10,
        ),
    ] = None,
    min_employees: Annotated[
        int | None,
        Query(ge=0, le=1_000_000, description="Minimum employee count."),
    ] = None,
    max_employees: Annotated[
        int | None,
        Query(ge=0, le=1_000_000, description="Maximum employee count."),
    ] = None,
    min_capital_yen: Annotated[
        int | None,
        Query(ge=0, le=10**14, description="Minimum capital_yen."),
    ] = None,
    max_capital_yen: Annotated[
        int | None,
        Query(ge=0, le=10**14, description="Maximum capital_yen."),
    ] = None,
    is_sole_proprietor: Annotated[
        bool | None,
        Query(
            description=(
                "Filter to (or exclude) 個人事業主 rows. None = ignore."
            ),
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    _t0 = time.perf_counter()

    if not _table_exists(conn, "case_studies"):
        raise HTTPException(status_code=503, detail="case_studies table missing.")

    if (
        min_employees is not None
        and max_employees is not None
        and min_employees > max_employees
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"min_employees ({min_employees}) > max_employees ({max_employees})."
            ),
        )
    if (
        min_capital_yen is not None
        and max_capital_yen is not None
        and min_capital_yen > max_capital_yen
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"min_capital_yen ({min_capital_yen}) > max_capital_yen "
                f"({max_capital_yen})."
            ),
        )

    where: list[str] = []
    params: list[Any] = []
    if industry_jsic:
        where.append("industry_jsic LIKE ?")
        params.append(f"{industry_jsic}%")
    if prefecture:
        where.append("prefecture = ?")
        params.append(prefecture)
    if min_employees is not None:
        where.append("COALESCE(employees, -1) >= ?")
        params.append(min_employees)
    if max_employees is not None:
        where.append("COALESCE(employees, 99999999) <= ?")
        params.append(max_employees)
    if min_capital_yen is not None:
        where.append("COALESCE(capital_yen, -1) >= ?")
        params.append(min_capital_yen)
    if max_capital_yen is not None:
        where.append("COALESCE(capital_yen, " + str(10**18) + ") <= ?")
        params.append(max_capital_yen)
    if is_sole_proprietor is not None:
        where.append("COALESCE(is_sole_proprietor, 0) = ?")
        params.append(1 if is_sole_proprietor else 0)

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    try:
        (total,) = conn.execute(
            f"SELECT COUNT(*) FROM case_studies{where_sql}",
            tuple(params),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("case_studies count failed: %s", exc)
        total = 0

    try:
        rows = conn.execute(
            "SELECT case_id, company_name, houjin_bangou, is_sole_proprietor, "
            "       prefecture, municipality, industry_jsic, industry_name, "
            "       employees, founded_year, capital_yen, "
            "       case_title, case_summary, programs_used_json, "
            "       total_subsidy_received_yen, outcomes_json, patterns_json, "
            "       publication_date, source_url, source_excerpt, "
            "       fetched_at, confidence "
            f"  FROM case_studies{where_sql} "
            " ORDER BY publication_date DESC NULLS LAST, case_id ASC "
            " LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("case_studies select failed: %s", exc)
        rows = []

    results: list[dict[str, Any]] = []
    for r in rows:
        sole = r["is_sole_proprietor"]
        results.append(
            {
                "case_id": r["case_id"],
                "company_name": r["company_name"],
                "houjin_bangou": r["houjin_bangou"],
                "is_sole_proprietor": None if sole is None else bool(sole),
                "prefecture": r["prefecture"],
                "municipality": r["municipality"],
                "industry_jsic": r["industry_jsic"],
                "industry_name": r["industry_name"],
                "employees": r["employees"],
                "founded_year": r["founded_year"],
                "capital_yen": r["capital_yen"],
                "case_title": r["case_title"],
                "case_summary": _truncate(r["case_summary"], 400),
                "programs_used": _json_list(r["programs_used_json"]),
                "total_subsidy_received_yen": r["total_subsidy_received_yen"],
                "publication_date": r["publication_date"],
                "source_url": r["source_url"],
                "source_excerpt": _truncate(r["source_excerpt"], 200),
                "confidence": r["confidence"],
            }
        )

    body: dict[str, Any] = {
        "filters": {
            "industry_jsic": industry_jsic,
            "prefecture": prefecture,
            "min_employees": min_employees,
            "max_employees": max_employees,
            "min_capital_yen": min_capital_yen,
            "max_capital_yen": max_capital_yen,
            "is_sole_proprietor": is_sole_proprietor,
        },
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "results": results,
        "_disclaimer": _FULL_CONTEXT_DISCLAIMER,
        "_billing_unit": 1,
    }
    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "cases.by_industry_size_pref",
        latency_ms=latency_ms,
        result_count=len(results),
        params={
            "industry_jsic": industry_jsic,
            "prefecture": prefecture,
            "min_employees": min_employees,
            "max_employees": max_employees,
            "min_capital_yen": min_capital_yen,
            "max_capital_yen": max_capital_yen,
            "is_sole_proprietor": is_sole_proprietor,
            "limit": limit,
            "offset": offset,
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="cases.by_industry_size_pref",
        request_params={
            "industry_jsic": industry_jsic,
            "prefecture": prefecture,
            "min_employees": min_employees,
            "max_employees": max_employees,
            "min_capital_yen": min_capital_yen,
            "max_capital_yen": max_capital_yen,
            "is_sole_proprietor": is_sole_proprietor,
            "limit": limit,
            "offset": offset,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )

    if wants_compact(request):
        body = to_compact(body)

    return JSONResponse(content=body)


__all__ = [
    "router",
    "laws_cross_router",
    "cases_cross_router",
]
