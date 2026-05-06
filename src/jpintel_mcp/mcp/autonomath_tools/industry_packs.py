"""industry_packs — 3 cohort-specific MCP tool wrappers (Wave 23, 2026-04-29).

Three industry-specific wrappers (`pack_construction`, `pack_manufacturing`,
`pack_real_estate`) bundle the most relevant existing surfaces for the
3 highest-priority business cohorts identified in the cohort revenue model
audit. Each wrapper:

  * Pre-sets industry filter (JSIC major + name keyword union, NO LLM).
  * Wraps existing tools (search programs / find_saiketsu / cite_tsutatsu)
    via direct SQL — no recursive MCP self-calls, single ¥3/req billing.
  * Returns top 10 programs + up to 5 saiketsu citations + up to 3 通達
    references for the cohort.
  * Surfaces ``_disclaimer`` (§52 / §47条の2 envelope) on every response.
  * Emits ``_next_calls`` for the call-density compounding mechanism.

Cohort definitions
------------------

  pack_construction   JSIC D + 建設・建築・住宅・空き家・耐震・改修・リフォーム
                      keyword fence, biased toward 公共工事 + 改修 + 住宅政策.

  pack_manufacturing  JSIC E + ものづくり・製造・設備投資・省エネ・GX・
                      事業再構築・IT導入 keyword fence, biased toward
                      ものづくり補助金 + 事業再構築補助金 surface.

  pack_real_estate    JSIC K + 不動産・空き家・住宅・賃貸・改修 keyword fence,
                      biased toward 空き家対策 + 住宅政策 + 流通促進 surface.

NO Anthropic API self-call. All three tools are pure SQL / Python over
jpintel.db + autonomath.db. Each call = 1 metered request (the wrapper
runs N internal queries but bills as a single ¥3/req event).

Sensitive (§52 + §47条の2 fence) — every response carries a `_disclaimer`
declaring the output information retrieval, NOT 税務助言 / 申請代理 /
監査調書 / 経営判断.

Migration dependency: none. `am_industry_jsic` (35 rows) is the JSIC
mapping; `programs` (jpintel.db) is the search corpus; `nta_saiketsu` /
`nta_tsutatsu_index` (autonomath.db) are the citation corpora.
"""

from __future__ import annotations

import datetime
import logging
import os
import sqlite3
from typing import Annotated, Any, Literal

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error
from .snapshot_helper import attach_corpus_snapshot

logger = logging.getLogger("jpintel.mcp.autonomath.industry_packs")

# Env-gated registration (default on). Flip to "0" to roll back without redeploy.
_ENABLED = os.environ.get("AUTONOMATH_INDUSTRY_PACKS_ENABLED", "1") == "1"


# ---------------------------------------------------------------------------
# Cohort definitions — JSIC major + keyword fence + bias keywords.
# ---------------------------------------------------------------------------

_PackKey = Literal["construction", "manufacturing", "real_estate"]


_PACK_DEFINITIONS: dict[str, dict[str, Any]] = {
    "construction": {
        "jsic_major": "D",
        "jsic_name_ja": "建設業",
        "name_keywords": (
            "建設",
            "建築",
            "住宅",
            "空き家",
            "耐震",
            "改修",
            "リフォーム",
            "塗装",
            "工務",
            "土木",
            "解体",
            "リノベーション",
            "工事",
            "下請",
            "請負",
        ),
        "tax_types": ("法人税", "消費税"),
        "tsutatsu_prefixes": ("法基通", "消基通"),
        "industries_filter_label": "JSIC D 建設業 (建設・建築・住宅・耐震・改修・工事・下請)",
    },
    "manufacturing": {
        "jsic_major": "E",
        "jsic_name_ja": "製造業",
        "name_keywords": (
            "ものづくり",
            "製造",
            "設備投資",
            "省エネ",
            "GX",
            "脱炭素",
            "事業再構築",
            "IT導入",
            "DX",
            "工場",
            "生産",
            "技術開発",
        ),
        "tax_types": ("法人税", "所得税"),
        "tsutatsu_prefixes": ("法基通",),
        "industries_filter_label": "JSIC E 製造業 (ものづくり・設備投資・省エネ・GX・事業再構築)",
    },
    "real_estate": {
        "jsic_major": "K",
        "jsic_name_ja": "不動産業、物品賃貸業",
        "name_keywords": (
            "不動産",
            "空き家",
            "住宅",
            "賃貸",
            "改修",
            "流通",
            "リフォーム",
            "リノベーション",
            "耐震",
            "省エネ住宅",
            "既存住宅",
        ),
        "tax_types": ("所得税", "相続税", "法人税"),
        "tsutatsu_prefixes": ("所基通", "相基通"),
        "industries_filter_label": "JSIC K 不動産業 (不動産・空き家・住宅・賃貸)",
    },
}


_DISCLAIMER_INDUSTRY_PACK = (
    "本 response は jpintel programs + nta_saiketsu + nta_tsutatsu_index 一次資料の "
    "industry-fence aggregation で、税務助言 (税理士法 §52) ・監査調書 (公認会計士法 §47条の2) "
    "・申請代理 (行政書士法 §1) ・経営判断 (中小企業診断士の経営助言) の代替ではありません。"
    "業種マッピングは JSIC 大分類 + 名称キーワード fence による heuristic で、各 program の "
    "適合可否は申請要領を一次資料 (source_url) で必ずご確認ください。"
    "裁決事例・通達は公表時点の解釈であり、改正により現在の取扱が変更されている可能性があります。"
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _open_autonomath() -> sqlite3.Connection | dict[str, Any]:
    """Open autonomath.db read-only, returning either a conn or error envelope."""
    try:
        return connect_autonomath()
    except FileNotFoundError as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {exc}",
            hint="Ensure autonomath.db is present at the repo root or AUTONOMATH_DB_PATH.",
            retry_with=["search_programs"],
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
            retry_with=["search_programs"],
        )


def _open_jpintel_ro() -> sqlite3.Connection | dict[str, Any]:
    """Open jpintel.db read-only via file URI."""
    db_path = os.environ.get("JPINTEL_DB_PATH", "data/jpintel.db")
    try:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=10.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db open failed: {exc}",
            retry_with=["search_programs"],
        )


def _today_iso() -> str:
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()


# ---------------------------------------------------------------------------
# Top-N programs for the cohort (jpintel.db)
# ---------------------------------------------------------------------------


def _fetch_industry_programs(
    pack_key: str,
    prefecture: str | None,
    employee_count: int | None,
    revenue_yen: int | None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Pull top programs filtered by industry name-keyword fence.

    Filtering strategy
    ------------------
    1. ``tier IN ('S','A','B','C')`` — quarantine excluded.
    2. ``excluded = 0``.
    3. Name keyword union (LIKE OR) — matches primary_name OR target_types_json.
    4. Optional prefecture filter (matches prefecture column or NULL = national).

    Ranking: tier S → A → B → C, then primary_name asc.
    """
    pack = _PACK_DEFINITIONS[pack_key]
    keywords: tuple[str, ...] = pack["name_keywords"]

    conn_or_err = _open_jpintel_ro()
    if isinstance(conn_or_err, dict):
        return []
    conn = conn_or_err

    # Build keyword OR clause.
    keyword_clauses: list[str] = []
    params: list[Any] = []
    for kw in keywords:
        keyword_clauses.append("(primary_name LIKE ? OR COALESCE(target_types_json,'') LIKE ?)")
        params.append(f"%{kw}%")
        params.append(f"%{kw}%")

    pref_clause = ""
    if prefecture:
        pref_clause = " AND (prefecture = ? OR prefecture IS NULL OR prefecture = '')"
        params.append(prefecture)

    # `keyword_clauses` is built from a hardcoded `_PACK_DEFINITIONS` dict (no
    # user input). The f-string interpolation is bandit-safe.
    keyword_or = " OR ".join(keyword_clauses)
    sql = (  # nosec B608
        "SELECT unified_id, primary_name, prefecture, authority_level, authority_name, "
        "       program_kind, official_url, source_url, amount_max_man_yen, "
        "       amount_min_man_yen, subsidy_rate, tier, application_window_json "
        "  FROM programs "
        " WHERE tier IN ('S','A','B','C') "
        "   AND excluded = 0 "
        f"  AND ({keyword_or}) "
        f"  {pref_clause} "
        " ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END, "
        "          primary_name "
        " LIMIT ? "
    )
    params.append(int(limit))

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("industry_packs program fetch failed for %s: %s", pack_key, exc)
        rows = []
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "unified_id": r["unified_id"],
                "primary_name": r["primary_name"],
                "prefecture": r["prefecture"],
                "authority_level": r["authority_level"],
                "authority_name": r["authority_name"],
                "program_kind": r["program_kind"],
                "official_url": r["official_url"],
                "source_url": r["source_url"],
                "amount_max_man_yen": r["amount_max_man_yen"],
                "amount_min_man_yen": r["amount_min_man_yen"],
                "subsidy_rate": r["subsidy_rate"],
                "tier": r["tier"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Saiketsu citations (autonomath.db / nta_saiketsu)
# ---------------------------------------------------------------------------


def _fetch_industry_saiketsu(
    pack_key: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Pull up to N 裁決事例 most relevant to the cohort.

    Uses keyword union against title + decision_summary (LIKE), restricted to
    pack-relevant 税目 (e.g. 法人税 + 消費税 for construction/manufacturing,
    所得税 + 相続税 for real_estate).
    """
    pack = _PACK_DEFINITIONS[pack_key]
    keywords: tuple[str, ...] = pack["name_keywords"]
    tax_types: tuple[str, ...] = pack["tax_types"]

    conn_or_err = _open_autonomath()
    if isinstance(conn_or_err, dict):
        return []
    conn = conn_or_err

    keyword_clauses: list[str] = []
    params: list[Any] = []
    for kw in keywords:
        keyword_clauses.append(
            "(COALESCE(title,'') LIKE ? OR COALESCE(decision_summary,'') LIKE ?)"
        )
        params.append(f"%{kw}%")
        params.append(f"%{kw}%")

    tax_placeholders = ",".join("?" * len(tax_types))
    params.extend(tax_types)
    params.append(int(limit))

    # `keyword_clauses` + `tax_placeholders` are built from hardcoded
    # `_PACK_DEFINITIONS` values (no user input). The f-string is bandit-safe.
    keyword_or = " OR ".join(keyword_clauses)
    sql = (  # nosec B608
        "SELECT volume_no, case_no, decision_date, tax_type, "
        "       title, decision_summary, source_url, license "
        "  FROM nta_saiketsu "
        f" WHERE ({keyword_or}) "
        f"   AND tax_type IN ({tax_placeholders}) "
        " ORDER BY decision_date DESC NULLS LAST, volume_no DESC, case_no "
        " LIMIT ? "
    )
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        # NULLS LAST is sqlite >=3.30. Fall back to simpler ordering.
        logger.debug("saiketsu fetch with NULLS LAST failed (%s); retrying simple order", exc)
        sql = sql.replace(" NULLS LAST", "")
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc2:
            logger.warning("industry_packs saiketsu fetch failed: %s", exc2)
            rows = []

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "volume_no": r["volume_no"],
                "case_no": r["case_no"],
                "decision_date": r["decision_date"],
                "tax_type": r["tax_type"],
                "title": r["title"],
                "decision_summary": (r["decision_summary"] or "")[:300],
                "source_url": r["source_url"],
                "license": r["license"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Tsutatsu references (autonomath.db / nta_tsutatsu_index)
# ---------------------------------------------------------------------------


def _fetch_industry_tsutatsu(
    pack_key: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Pull up to N 通達 most relevant to the cohort.

    Uses pack-specific code prefix filter (e.g. 法基通 for construction,
    所基通 + 相基通 for real_estate).
    """
    pack = _PACK_DEFINITIONS[pack_key]
    keywords: tuple[str, ...] = pack["name_keywords"]
    prefixes: tuple[str, ...] = pack["tsutatsu_prefixes"]

    conn_or_err = _open_autonomath()
    if isinstance(conn_or_err, dict):
        return []
    conn = conn_or_err

    # Code prefix OR clause
    prefix_clauses = ["code LIKE ?" for _ in prefixes]
    params: list[Any] = [f"{p}%" for p in prefixes]

    # Keyword OR clause on title / body_excerpt
    keyword_clauses: list[str] = []
    for kw in keywords:
        keyword_clauses.append("(COALESCE(title,'') LIKE ? OR COALESCE(body_excerpt,'') LIKE ?)")
        params.append(f"%{kw}%")
        params.append(f"%{kw}%")

    params.append(int(limit))

    # `prefix_clauses` + `keyword_clauses` are built from hardcoded
    # `_PACK_DEFINITIONS` values (no user input). The f-string is bandit-safe.
    prefix_or = " OR ".join(prefix_clauses)
    keyword_or = " OR ".join(keyword_clauses)
    sql = (  # nosec B608
        "SELECT code, law_canonical_id, article_number, title, body_excerpt, "
        "       source_url, last_amended "
        "  FROM nta_tsutatsu_index "
        f" WHERE ({prefix_or}) "
        f"   AND ({keyword_or}) "
        " ORDER BY code "
        " LIMIT ? "
    )
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("industry_packs tsutatsu fetch failed: %s", exc)
        rows = []

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "code": r["code"],
                "law_canonical_id": r["law_canonical_id"],
                "article_number": r["article_number"],
                "title": r["title"],
                "body_excerpt": (r["body_excerpt"] or "")[:300],
                "source_url": r["source_url"],
                "last_amended": r["last_amended"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Pack assembly — single function, dispatched by pack_key
# ---------------------------------------------------------------------------


def _assemble_pack(
    pack_key: _PackKey,
    prefecture: str | None,
    employee_count: int | None,
    revenue_yen: int | None,
) -> dict[str, Any]:
    """Compose the pack response. Single billing event."""
    if pack_key not in _PACK_DEFINITIONS:
        return make_error(
            code="invalid_enum",
            message=f"pack_key must be one of {list(_PACK_DEFINITIONS)}, got {pack_key!r}.",
            field="pack_key",
        )
    pack = _PACK_DEFINITIONS[pack_key]

    programs = _fetch_industry_programs(
        pack_key=pack_key,
        prefecture=prefecture,
        employee_count=employee_count,
        revenue_yen=revenue_yen,
        limit=10,
    )
    saiketsu = _fetch_industry_saiketsu(pack_key=pack_key, limit=5)
    tsutatsu = _fetch_industry_tsutatsu(pack_key=pack_key, limit=3)

    next_calls = [
        {
            "tool": "search_programs",
            "args": {
                "q": pack["name_keywords"][0],
                "prefecture": prefecture,
                "limit": 30,
            },
            "rationale": (
                f"Drill into the {pack['jsic_name_ja']} corpus deeper — pack returns "
                "top 10 only. Use search_programs for the full list."
            ),
            "compound_mult": 1.5,
        },
        {
            "tool": "find_saiketsu",
            "args": {
                "query": pack["name_keywords"][0],
                "tax_type": pack["tax_types"][0],
            },
            "rationale": (
                "Pack surfaces 5 most-relevant decisions; find_saiketsu allows "
                "free-text query against the 3,221 裁決事例 corpus."
            ),
            "compound_mult": 1.4,
        },
        {
            "tool": "subsidy_combo_finder",
            "args": {
                "industry": pack["jsic_name_ja"],
                "prefecture": prefecture,
            },
            "rationale": (
                "Compound: identify which 2-3 programs in this pack stack legally "
                "(exclusion / prerequisite checks)."
            ),
            "compound_mult": 1.6,
        },
    ]

    # MASTER_PLAN_v1 §10.7/10.8 canonical envelope: every MCP tool MUST
    # surface `total / limit / offset / results` so generic envelope walkers
    # (paging, audit, billing) can iterate the rows without knowing the
    # cohort-specific 3-list shape. Each row carries a `kind` discriminator
    # so the legacy 3 lists are recoverable via filter.
    flat_results: list[dict[str, Any]] = []
    for p in programs:
        row = {"kind": "program", **p}
        flat_results.append(row)
    for s in saiketsu:
        row = {"kind": "saiketsu_citation", **s}
        flat_results.append(row)
    for t in tsutatsu:
        row = {"kind": "tsutatsu_reference", **t}
        flat_results.append(row)

    body: dict[str, Any] = {
        "pack_key": pack_key,
        "industry_label": pack["industries_filter_label"],
        "jsic_major": pack["jsic_major"],
        "input": {
            "prefecture": prefecture,
            "employee_count": employee_count,
            "revenue_yen": revenue_yen,
        },
        # --- Canonical §10.7/10.8 envelope ---
        "results": flat_results,
        "total": len(flat_results),
        "limit": len(flat_results),
        "offset": 0,
        # --- Legacy 3-list back-compat (test_industry_packs.py) ---
        "programs": programs,
        "saiketsu_citations": saiketsu,
        "tsutatsu_references": tsutatsu,
        "totals": {
            "programs": len(programs),
            "saiketsu_citations": len(saiketsu),
            "tsutatsu_references": len(tsutatsu),
        },
        "as_of_jst": _today_iso(),
        "_disclaimer": _DISCLAIMER_INDUSTRY_PACK,
        "_next_calls": next_calls,
        # Billing pipeline (Wave22/24) greps the envelope for `_billing_unit`
        # and counts the int as the metered request unit. Default 1 = 1 req/3¥.
        "_billing_unit": 1,
    }
    # W3-13: every customer-facing envelope MUST carry the corpus_snapshot_id
    # + corpus_checksum auditor reproducibility pair (公認会計士法 §47条の2).
    attach_corpus_snapshot(body)
    return body


# Public impl entry points (test-importable; do NOT remove the underscore
# prefix — the tests import these by name, not via the @mcp.tool decorator).


def _pack_construction_impl(
    prefecture: str | None = None,
    employee_count: int | None = None,
    revenue_yen: int | None = None,
) -> dict[str, Any]:
    return _assemble_pack(
        pack_key="construction",
        prefecture=prefecture,
        employee_count=employee_count,
        revenue_yen=revenue_yen,
    )


def _pack_manufacturing_impl(
    prefecture: str | None = None,
    employee_count: int | None = None,
    revenue_yen: int | None = None,
) -> dict[str, Any]:
    return _assemble_pack(
        pack_key="manufacturing",
        prefecture=prefecture,
        employee_count=employee_count,
        revenue_yen=revenue_yen,
    )


def _pack_real_estate_impl(
    prefecture: str | None = None,
    employee_count: int | None = None,
    revenue_yen: int | None = None,
) -> dict[str, Any]:
    return _assemble_pack(
        pack_key="real_estate",
        prefecture=prefecture,
        employee_count=employee_count,
        revenue_yen=revenue_yen,
    )


# ---------------------------------------------------------------------------
# MCP tool registration — gated by AUTONOMATH_INDUSTRY_PACKS_ENABLED +
# AUTONOMATH_ENABLED. Each docstring ≤ 400 chars per Wave 21 spec.
# ---------------------------------------------------------------------------

if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def pack_construction(
        prefecture: Annotated[
            str | None,
            Field(
                description=(
                    "都道府県名 (e.g. '東京都'). Optional — None matches "
                    "national + all prefectures."
                ),
            ),
        ] = None,
        employee_count: Annotated[
            int | None,
            Field(
                ge=0,
                description="従業員数 (人). Optional, used for downstream eligibility chaining only.",
            ),
        ] = None,
        revenue_yen: Annotated[
            int | None,
            Field(
                ge=0,
                description="年間売上高 (円). Optional, used for downstream eligibility chaining only.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[INDUSTRY-PACK] 建設業 (JSIC D) cohort pack: top 10 programs (建設・住宅・耐震・改修 fence) + up to 5 国税不服審判所 裁決事例 (法人税・消費税) + up to 3 通達 references (法基通・消基通). Single ¥3/req. NO LLM. §52/§47条の2 sensitive — information retrieval, not 税務助言. Compounds via _next_calls."""
        return _pack_construction_impl(
            prefecture=prefecture,
            employee_count=employee_count,
            revenue_yen=revenue_yen,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def pack_manufacturing(
        prefecture: Annotated[
            str | None,
            Field(
                description=(
                    "都道府県名 (e.g. '愛知県'). Optional — None matches "
                    "national + all prefectures."
                ),
            ),
        ] = None,
        employee_count: Annotated[
            int | None,
            Field(
                ge=0,
                description="従業員数 (人). Optional, used for downstream eligibility chaining only.",
            ),
        ] = None,
        revenue_yen: Annotated[
            int | None,
            Field(
                ge=0,
                description="年間売上高 (円). Optional, used for downstream eligibility chaining only.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[INDUSTRY-PACK] 製造業 (JSIC E) cohort pack: top 10 programs (ものづくり・設備投資・省エネ・GX・事業再構築 fence) + up to 5 国税不服審判所 裁決事例 (法人税・所得税) + up to 3 通達 references (法基通). Single ¥3/req. NO LLM. §52/§47条の2 sensitive — information retrieval, not 税務助言."""
        return _pack_manufacturing_impl(
            prefecture=prefecture,
            employee_count=employee_count,
            revenue_yen=revenue_yen,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def pack_real_estate(
        prefecture: Annotated[
            str | None,
            Field(
                description=(
                    "都道府県名 (e.g. '大阪府'). Optional — None matches "
                    "national + all prefectures."
                ),
            ),
        ] = None,
        employee_count: Annotated[
            int | None,
            Field(
                ge=0,
                description="従業員数 (人). Optional, used for downstream eligibility chaining only.",
            ),
        ] = None,
        revenue_yen: Annotated[
            int | None,
            Field(
                ge=0,
                description="年間売上高 (円). Optional, used for downstream eligibility chaining only.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[INDUSTRY-PACK] 不動産業 (JSIC K) cohort pack: top 10 programs (不動産・空き家・住宅・賃貸 fence) + up to 5 国税不服審判所 裁決事例 (所得税・相続税・法人税) + up to 3 通達 references (所基通・相基通). Single ¥3/req. NO LLM. §52/§47条の2 sensitive — information retrieval, not 税務助言."""
        return _pack_real_estate_impl(
            prefecture=prefecture,
            employee_count=employee_count,
            revenue_yen=revenue_yen,
        )


# ---------------------------------------------------------------------------
# Self-test harness (not part of the MCP surface).
#
#   .venv/bin/python -m jpintel_mcp.mcp.autonomath_tools.industry_packs
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import pprint

    for fn, label in (
        (_pack_construction_impl, "construction"),
        (_pack_manufacturing_impl, "manufacturing"),
        (_pack_real_estate_impl, "real_estate"),
    ):
        print(f"\n=== pack_{label} ===")
        res = fn(prefecture="東京都", employee_count=30, revenue_yen=100_000_000)
        pprint.pprint(
            {
                "pack_key": res.get("pack_key"),
                "totals": res.get("totals"),
                "first_program": (res.get("programs") or [{}])[0].get("primary_name"),
                "first_saiketsu": (res.get("saiketsu_citations") or [{}])[0].get("title"),
                "first_tsutatsu": (res.get("tsutatsu_references") or [{}])[0].get("code"),
                "next_calls": len(res.get("_next_calls") or []),
            }
        )
