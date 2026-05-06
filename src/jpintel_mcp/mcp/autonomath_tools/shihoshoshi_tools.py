"""shihoshoshi_tools — DEEP-30 司法書士 cohort dedicated MCP tool (1 tool, 2026-05-07).

One compound MCP tool dedicated to the 司法書士 (judicial scrivener) cohort
that the DEEP-30 spec identifies as the only 業法 sensitive cohort still
missing a capture surface. The tool unifies four DEEP-30 use cases into
one ¥3/req call:

  1. 商業登記前 houjin 360°  — jpi_houjin_master + am_entity_facts (corp.*)
  2. 不動産登記前 cross_check_jurisdiction — registered vs invoice vs operational
  3. 反社相当 enforcement 履歴 — am_enforcement_detail (fine / grant_refund / subsidy_exclude)
  4. 業務 boundary 警告 — am_enforcement_detail with §52 / §72 / §1 keyword fences

Tool shipped here
-----------------

  shihoshoshi_dd_pack_am
      Given 13-digit 法人番号, returns unified envelope:
        {commercial_registration, jurisdiction_check, enforcement_history,
         boundary_warnings, _disclaimer, _next_calls,
         corpus_snapshot_id, corpus_checksum}
      Pure SQLite reads, NO LLM. §3 fence (司法書士法) + §52 (税理士法) +
      §72 (弁護士法) + §1 (行政書士法) all carried in `_disclaimer`.

The §3 fence is non-negotiable: jpcite NEVER performs 登記 / 供託 / 簡裁
訴訟代理, and every response surfaces this in `_disclaimer`. The tool
provides scaffold + 一次資料 URL only; final decisions are 司法書士 turf.

NO Anthropic API self-call — pure SQL / Python over autonomath.db.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .corporate_layer_tools import (
    _compute_corpus_snapshot,
    _normalize_houjin,
    _open_db,
)
from .error_envelope import make_error
from .wave22_tools import _cross_check_jurisdiction_impl

logger = logging.getLogger("jpintel.mcp.autonomath.shihoshoshi")

# Env-gated registration (default ON). Flip "0" for one-flag rollback.
_ENABLED = os.environ.get("AUTONOMATH_SHIHOSHOSHI_PACK_ENABLED", "1") == "1"


# ---------------------------------------------------------------------------
# §3 fence + §52 / §72 / §1 disclaimer — must surface in every response.
# ---------------------------------------------------------------------------

_DISCLAIMER_SHIHOSHOSHI = (
    "本サービスは情報検索 (scaffold + 一次資料 URL 提供) です。登記・供託・"
    "簡裁訴訟代理は司法書士法 §3 司法書士独占業務であり、jpcite は代行を一切"
    "行いません。税務代理 (税理士法 §52)・法律判断 (弁護士法 §72)・官公署提出"
    "書類作成 (行政書士法 §1) も同様、有資格者の業務範囲を侵しません。"
    "申請書面の generation は提供せず、確定判断 (訴額・代理可否・登記申請先 等) "
    "は司法書士本人が行ってください。個人信用情報・反社 DB は対象外で、surface "
    "するのは公表 行政処分 corpus のみです。"
)


# ---------------------------------------------------------------------------
# 業法 keyword fence for boundary warnings — match against reason_summary +
# related_law_ref. We do NOT use a `description` column (it does not exist
# on am_enforcement_detail; the DEEP-30 spec used it as a placeholder).
# ---------------------------------------------------------------------------

_BOUNDARY_KEYWORDS: tuple[tuple[str, str, str], ...] = (
    # (keyword, fence_label, severity)
    ("税理士法", "tax_attorney_act_§52", "high"),
    ("弁護士法", "attorney_act_§72", "high"),
    ("行政書士法", "administrative_scrivener_act_§1", "high"),
    ("司法書士法", "judicial_scrivener_act_§3", "critical"),
    ("税務代理", "tax_attorney_act_§52", "medium"),
    ("無資格", "license_violation", "medium"),
)


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


def _commercial_registration(conn: sqlite3.Connection, hb: str) -> dict[str, Any]:
    """Read 商業登記情報 from jpi_houjin_master + am_entity_facts(corp.*).

    Returns a dict with master fields + the corp.* fact slice (役員 / 資本金 /
    JSIC / 設立年月日 等). When the houjin_bangou is unknown, returns an
    empty scaffold so the caller can detect the miss without a hard error.
    """
    out: dict[str, Any] = {
        "houjin_bangou": hb,
        "master": None,
        "corp_facts": [],
        "fact_field_count": 0,
        "source": "jpi_houjin_master + am_entity_facts (corp.*)",
    }

    # Master row -----------------------------------------------------------
    try:
        master_row = conn.execute(
            """
            SELECT houjin_bangou, normalized_name, corporation_type,
                   established_date, close_date, address_normalized,
                   prefecture, municipality, last_updated_nta, fetched_at
              FROM jpi_houjin_master
             WHERE houjin_bangou = ?
            """,
            (hb,),
        ).fetchone()
    except sqlite3.Error:
        master_row = None

    if master_row is not None:
        out["master"] = {
            "houjin_bangou": master_row["houjin_bangou"],
            "normalized_name": master_row["normalized_name"],
            "corporation_type": master_row["corporation_type"],
            "established_date": master_row["established_date"],
            "close_date": master_row["close_date"],
            "address_normalized": master_row["address_normalized"],
            "prefecture": master_row["prefecture"],
            "municipality": master_row["municipality"],
            "last_updated_nta": master_row["last_updated_nta"],
            "fetched_at": master_row["fetched_at"],
        }

    # corp.* facts (capital / JSIC / 役員 等) -------------------------------
    # am_entity_facts EAV is keyed by entity_canonical_id, and the corporate
    # entity's canonical_id mirrors a houjin_bangou-based shape — we resolve
    # via am_entities first, then fan out the corp.* facts.
    try:
        ent_row = conn.execute(
            """
            SELECT canonical_id FROM am_entities
             WHERE record_kind = 'corporate_entity'
               AND raw_json LIKE ?
             LIMIT 1
            """,
            (f'%"houjin_bangou":"{hb}"%',),
        ).fetchone()
    except sqlite3.Error:
        ent_row = None

    if ent_row is not None:
        try:
            fact_rows = conn.execute(
                """
                SELECT field_name, value, valid_from, valid_to, source_id
                  FROM am_entity_facts
                 WHERE entity_canonical_id = ?
                   AND field_name LIKE 'corp.%'
                 ORDER BY field_name
                 LIMIT 200
                """,
                (ent_row["canonical_id"],),
            ).fetchall()
        except sqlite3.Error:
            fact_rows = []

        for r in fact_rows:
            out["corp_facts"].append(
                {
                    "field_name": r["field_name"],
                    "value": r["value"],
                    "valid_from": r["valid_from"],
                    "valid_to": r["valid_to"],
                    "source_id": r["source_id"],
                }
            )
        out["fact_field_count"] = len(out["corp_facts"])
        out["entity_canonical_id"] = ent_row["canonical_id"]

    return out


def _enforcement_history(conn: sqlite3.Connection, hb: str) -> dict[str, Any]:
    """Read 反社相当 enforcement history (fine / grant_refund / subsidy_exclude)
    + 5y full timeline. Mirrors the DEEP-30 spec SQL skeleton (c).
    """
    out: dict[str, Any] = {
        "houjin_bangou": hb,
        "fine_grant_refund_exclude": [],
        "recent_5y": [],
        "all_count": 0,
        "scope_note": (
            "公表 行政処分 corpus のみ (1,185 行 + 補助金返還 / 排除措置)。"
            "個人信用情報・反社 DB・帝国データバンクは対象外。"
        ),
    }

    try:
        rows = conn.execute(
            """
            SELECT enforcement_id, enforcement_kind, amount_yen,
                   issuance_date, exclusion_start, exclusion_end,
                   issuing_authority, reason_summary, source_url
              FROM am_enforcement_detail
             WHERE houjin_bangou = ?
               AND enforcement_kind IN ('fine','grant_refund','subsidy_exclude')
             ORDER BY issuance_date DESC
             LIMIT 50
            """,
            (hb,),
        ).fetchall()
        out["fine_grant_refund_exclude"] = [
            {
                "enforcement_id": r["enforcement_id"],
                "kind": r["enforcement_kind"],
                "amount_yen": r["amount_yen"],
                "issuance_date": r["issuance_date"],
                "exclusion_start": r["exclusion_start"],
                "exclusion_end": r["exclusion_end"],
                "issuing_authority": r["issuing_authority"],
                "reason_summary": r["reason_summary"],
                "source_url": r["source_url"],
            }
            for r in rows
        ]
    except sqlite3.Error:
        pass

    try:
        rows_5y = conn.execute(
            """
            SELECT enforcement_id, enforcement_kind, amount_yen,
                   issuance_date, issuing_authority, reason_summary, source_url
              FROM am_enforcement_detail
             WHERE houjin_bangou = ?
               AND issuance_date >= date('now', '-5 years')
             ORDER BY issuance_date DESC
             LIMIT 50
            """,
            (hb,),
        ).fetchall()
        out["recent_5y"] = [
            {
                "enforcement_id": r["enforcement_id"],
                "kind": r["enforcement_kind"],
                "amount_yen": r["amount_yen"],
                "issuance_date": r["issuance_date"],
                "issuing_authority": r["issuing_authority"],
                "reason_summary": r["reason_summary"],
                "source_url": r["source_url"],
            }
            for r in rows_5y
        ]
    except sqlite3.Error:
        pass

    try:
        cnt = conn.execute(
            "SELECT COUNT(*) AS n FROM am_enforcement_detail WHERE houjin_bangou = ?",
            (hb,),
        ).fetchone()
        out["all_count"] = cnt["n"] if cnt else 0
    except sqlite3.Error:
        pass

    return out


def _boundary_warnings(conn: sqlite3.Connection, hb: str) -> dict[str, Any]:
    """Detect 業法 抵触 risk fines via reason_summary / related_law_ref keyword
    match. Surfaces 税理士法 §52 / 弁護士法 §72 / 行政書士法 §1 / 司法書士法 §3
    flags so 司法書士 onboarding can route the candidate to the right cohort.
    """
    out: dict[str, Any] = {
        "houjin_bangou": hb,
        "warnings": [],
        "fence_hits": {},
        "method": "keyword_match (reason_summary + related_law_ref)",
    }

    try:
        rows = conn.execute(
            """
            SELECT enforcement_id, enforcement_kind, issuance_date,
                   issuing_authority, reason_summary, related_law_ref,
                   amount_yen, source_url
              FROM am_enforcement_detail
             WHERE houjin_bangou = ?
               AND (reason_summary IS NOT NULL OR related_law_ref IS NOT NULL)
             LIMIT 200
            """,
            (hb,),
        ).fetchall()
    except sqlite3.Error:
        rows = []

    for r in rows:
        haystack = " ".join(
            filter(
                None,
                [
                    r["reason_summary"] or "",
                    r["related_law_ref"] or "",
                ],
            )
        )
        for kw, fence_label, severity in _BOUNDARY_KEYWORDS:
            if kw in haystack:
                out["warnings"].append(
                    {
                        "enforcement_id": r["enforcement_id"],
                        "kind": r["enforcement_kind"],
                        "matched_keyword": kw,
                        "fence_label": fence_label,
                        "severity": severity,
                        "issuance_date": r["issuance_date"],
                        "issuing_authority": r["issuing_authority"],
                        "amount_yen": r["amount_yen"],
                        "reason_summary": r["reason_summary"],
                        "related_law_ref": r["related_law_ref"],
                        "source_url": r["source_url"],
                    }
                )
                out["fence_hits"][fence_label] = out["fence_hits"].get(fence_label, 0) + 1

    return out


def _shihoshoshi_dd_pack_impl(houjin_bangou: str) -> dict[str, Any]:
    """1-call DEEP-30 司法書士 DD pack — pure SQLite, NO LLM."""
    if not houjin_bangou or not isinstance(houjin_bangou, str):
        return make_error(
            code="missing_required_arg",
            message="houjin_bangou is required (13-digit 法人番号 with or without 'T' prefix).",
            field="houjin_bangou",
        )
    hb = _normalize_houjin(houjin_bangou)
    if not (hb.isdigit() and len(hb) == 13):
        return make_error(
            code="invalid_enum",
            message=f"houjin_bangou must be 13 digits (got {hb!r}).",
            field="houjin_bangou",
            hint="国税庁 法人番号公表サイトの 13 桁 (チェックディジット含む) を渡してください.",
        )

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    # --- Compose 4 sections (commercial / jurisdiction / enforcement /
    # boundary_warnings). The jurisdiction sub-call reuses Wave 22's
    # cross_check_jurisdiction_impl so behavior stays identical to the
    # standalone tool.
    commercial_registration = _commercial_registration(conn, hb)
    enforcement_history = _enforcement_history(conn, hb)
    boundary_warnings = _boundary_warnings(conn, hb)

    # cross_check_jurisdiction returns its own envelope (with results /
    # data_quality / _disclaimer); we strip the outer wrappers and embed
    # only the substantive payload here so this tool's envelope stays
    # single-layered.
    jc_full = _cross_check_jurisdiction_impl(houjin_bangou=hb)
    jurisdiction_check = {
        "registered": jc_full.get("registered"),
        "invoice_jurisdiction": jc_full.get("invoice_jurisdiction"),
        "operational": jc_full.get("operational"),
        "mismatches": jc_full.get("results", []),
        "mismatch_count": jc_full.get("mismatch_count", 0),
        "houjin_resolved": jc_full.get("data_quality", {}).get("houjin_resolved", True),
    }

    # results envelope shape: surface section summary so the consumer
    # knows the rollup at a glance.
    results = [
        {"kind": "commercial_registration", "found": commercial_registration["master"] is not None},
        {"kind": "jurisdiction_check", "mismatch_count": jurisdiction_check["mismatch_count"]},
        {"kind": "enforcement_history", "all_count": enforcement_history["all_count"]},
        {"kind": "boundary_warnings", "warning_count": len(boundary_warnings["warnings"])},
    ]

    snapshot_id, checksum = _compute_corpus_snapshot(conn)
    out: dict[str, Any] = {
        "houjin_bangou": hb,
        "results": results,
        "total": len(results),
        "limit": len(results),
        "offset": 0,
        "commercial_registration": commercial_registration,
        "jurisdiction_check": jurisdiction_check,
        "enforcement_history": enforcement_history,
        "boundary_warnings": boundary_warnings,
        "data_quality": {
            "method": "1-call compound (4 sub-queries: master / cross_check / enforcement / boundary)",
            "llm_calls_made": 0,
            "houjin_resolved": commercial_registration["master"] is not None,
            "enforcement_corpus_total": 22258,
            "houjin_corpus_total": 166765,
            "caveat": (
                "本 tool は 司法書士 cohort 専用の DEEP-30 unified envelope。"
                "登記申請・供託・簡裁訴訟代理は §3 司法書士独占業務であり、本 "
                "tool は scaffold + 一次資料 URL のみ surface します。"
            ),
            "official_lookup_url": "https://www.houjin-bangou.nta.go.jp/",
        },
        "_disclaimer": _DISCLAIMER_SHIHOSHOSHI,
        "_next_calls": [
            {
                "tool": "intel_houjin_full",
                "args": {"houjin_id": hb},
                "rationale": (
                    "DD pack rollup を出した後、intel_houjin_full で "
                    "EDINET / 採択 / 行政処分 / 関連 program の full picture "
                    "を取り、登記前 360 view を完結させる。"
                ),
                "compound_mult": 1.6,
            },
            {
                "tool": "check_enforcement_am",
                "args": {"houjin_bangou": hb, "as_of_date": "today"},
                "rationale": (
                    "受任候補が現時点で補助金排除中か (currently_excluded) を "
                    "確認 — 登記受任前の sanity check。"
                ),
                "compound_mult": 1.4,
            },
            {
                "tool": "list_edinet_disclosures",
                "args": {"houjin_bangou": hb},
                "rationale": (
                    "上場法人の場合、EDINET 開示書類で最新 株主構成 / 大量保有 "
                    "の confirm — 不動産登記前の jurisdiction sanity check と pair。"
                ),
                "compound_mult": 1.3,
            },
        ],
        "corpus_snapshot_id": snapshot_id,
        "corpus_checksum": checksum,
        "_billing_unit": 1,
    }
    return out


# ---------------------------------------------------------------------------
# MCP tool registration. Gated by AUTONOMATH_SHIHOSHOSHI_PACK_ENABLED + the
# global AUTONOMATH_ENABLED. Docstring ≤ 400 chars per Wave 21+ convention.
# ---------------------------------------------------------------------------
if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def shihoshoshi_dd_pack_am(
        houjin_bangou: Annotated[
            str,
            Field(description="13-digit 法人番号 (with or without 'T' prefix)."),
        ],
    ) -> dict[str, Any]:
        """[DEEP-30 司法書士] 司法書士 cohort dedicated DD pack — 1-call で 商業登記前 360° (jpi_houjin_master + corp.* facts) + 不動産登記前 cross_check_jurisdiction + 反社相当 enforcement (fine/grant_refund/subsidy_exclude) + 業務 boundary 警告 (§52/§72/§1 keyword fence) を unified envelope で返す。NO LLM。§3 fence 厳守 — 登記・供託・簡裁訴訟代理は司法書士独占業務、jpcite は scaffold のみ。"""
        return _shihoshoshi_dd_pack_impl(houjin_bangou=houjin_bangou)


# ---------------------------------------------------------------------------
# Self-test harness (not part of the MCP surface).
#
#   .venv/bin/python -m jpintel_mcp.mcp.autonomath_tools.shihoshoshi_tools
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import pprint

    print("\n=== shihoshoshi_dd_pack_am ===")
    res = _shihoshoshi_dd_pack_impl(houjin_bangou="3450001000777")
    pprint.pprint(
        {
            "total": res.get("total"),
            "commercial_master_found": (res.get("commercial_registration") or {}).get("master")
            is not None,
            "fact_field_count": (res.get("commercial_registration") or {}).get("fact_field_count"),
            "jurisdiction_mismatches": (res.get("jurisdiction_check") or {}).get("mismatch_count"),
            "enforcement_total": (res.get("enforcement_history") or {}).get("all_count"),
            "boundary_warnings": len((res.get("boundary_warnings") or {}).get("warnings", [])),
            "next_calls_count": len(res.get("_next_calls", [])),
            "disclaimer_present": "_disclaimer" in res,
            "snapshot_id": res.get("corpus_snapshot_id"),
        }
    )
