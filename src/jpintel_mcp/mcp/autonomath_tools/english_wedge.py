"""english_wedge — 5 MCP tools for the foreign-investor cohort (English wedge).

Five English-first MCP tools that surface the existing English-corpus
substrate (migration 090 `am_law_article.body_en`, migration 091
`am_tax_treaty`, migration 092 `am_subsidy_rule.foreign_capital_eligibility`)
to the foreign FDI / cross-border M&A / FATCA SaaS cohort identified in the
cohort revenue model (cohort #4: Foreign FDI).

Tools shipped here
------------------

  search_laws_en
      Keyword search restricted to ``am_law_article`` rows where
      ``body_en IS NOT NULL`` (the e-Gov 日本法令外国語訳 corpus, CC-BY 4.0).
      Returns hits with English title + EN body excerpt + source_url.
      Sensitive (国際課税 / 弁護士法 §72 fence).

  get_law_article_en
      Exact (law_id, article_no) lookup, returning the EN translation when
      present and a graceful JP fallback warning when not. Mirrors
      ``law_article_tool.get_law_article(lang='en')`` but is a foreign-cohort
      first-class entry point. Sensitive.

  get_tax_treaty
      Bilateral DTA lookup over ``am_tax_treaty`` (33 rows live, schema
      seeds ~80 jurisdictions). Returns withholding-tax rates (dividend /
      interest / royalty / parent-sub dividend), PE threshold, info-exchange
      status, and the MoF / NTA primary-source URL. country_b defaults to
      ``"JPN"`` since every am_tax_treaty row is bilateral with Japan.
      Sensitive (国際課税 / 税理士法 §52 fence).

  check_foreign_capital_eligibility
      For a given houjin (法人番号 or NULL = "any foreign-invested KK") and a
      program canonical_id, return the
      ``am_subsidy_rule.foreign_capital_eligibility`` flag (eligible /
      eligible_with_caveat / excluded / silent / case_by_case). Default
      'silent' = "Japanese statutory presumption is permissive". Sensitive
      (FDI 規制 / 行政書士法 §1).

  find_fdi_friendly_subsidies
      Cohort discovery: filters programs by industry (JSIC major) AND
      foreign_capital_eligibility != 'excluded'. Optional ``foreign_pct``
      argument is informational only — the database has no per-program
      foreign-equity threshold; we surface the input back so the caller
      can record the assumption that fed the lookup. Sensitive (FDI 規制).

Design choices
--------------

- **NO LLM call.** Every tool is pure SQL / Python over autonomath.db.
  English text comes from migration 090 ``body_en`` column (e-Gov CC-BY 4.0),
  not on-the-fly translation. Translation is a separate offline ETL wave.
- **¥3/req metered only.** Single billing event per call (mirrors REST + the
  ¥10/req SaaS-pricing instinct is explicitly REJECTED — solo + zero-touch
  + tier-less pricing is the operator constraint, see CLAUDE.md).
- **Aggregator ban.** Every row cites e-Gov / MoF / NTA primary source URLs;
  no JETRO compilation, no second-hand FATCA SaaS feed.
- **Disclaimer envelope.** All five tools surface ``_disclaimer`` declaring
  the response 税理士法 §52 / 国際課税 / 弁護士法 §72 / FDI 規制 fenced —
  output is information retrieval, not advice.
- **Compound multiplier.** Every response carries ``_next_calls`` so the
  customer LLM can chain to ``get_evidence_packet`` / ``get_houjin_360_am``
  / ``find_fdi_friendly_subsidies`` for follow-up.

Migration deps: 090 (body_en) + 091 (am_tax_treaty) + 092
(foreign_capital_eligibility). Idempotent — tool simply reads.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error
from .snapshot_helper import attach_corpus_snapshot

logger = logging.getLogger("jpintel.mcp.autonomath.english_wedge")

# Env-gated registration (default ON). Flip to "0" for one-flag rollback.
_ENABLED = get_flag("JPCITE_ENGLISH_WEDGE_ENABLED", "AUTONOMATH_ENGLISH_WEDGE_ENABLED", "1") == "1"


# ---------------------------------------------------------------------------
# Disclaimers — every tool surfaces a fence string. Foreign-cohort surface
# touches 税理士法 §52 (international tax) + 国際課税 (cross-border tax) +
# 弁護士法 §72 (legal advice) + 行政書士法 §1 (FDI 申請 代理).
# ---------------------------------------------------------------------------

_DISCLAIMER_LAW_EN = (
    "The English text returned here is a courtesy translation sourced from the "
    "Ministry of Justice e-Gov 日本法令外国語訳 (japaneselawtranslation.go.jp) "
    "under CC-BY 4.0. The Japanese-language original is the only legally "
    "authoritative version. This response is information retrieval, NOT legal "
    "advice (弁護士法 §72) or tax advice (税理士法 §52). For binding "
    "interpretation consult a Japanese qualified attorney / 税理士. jpcite "
    "assumes no liability for downstream legal or tax decisions."
)

_DISCLAIMER_TAX_TREATY = (
    "本 response は am_tax_treaty (国税庁・財務省 一次資料 ~80 国 schema, 現在 33 国 "
    "hand-curated) の lookup で、税務助言ではありません。WHT rates are treaty rates, "
    "not statutory — actual application requires Form 17 (Application Form for "
    "Income Tax Convention) filing and possibly LOB (Limitation on Benefits) "
    "checks. International tax 個別判断は資格を有する税理士・国際税務士に必ずご相談 "
    "ください。Information from primary government sources (MoF / NTA) only — "
    "no aggregator. 税理士法 §52 / 国際課税 fence."
)

_DISCLAIMER_FOREIGN_CAPITAL = (
    "本 response は am_subsidy_rule.foreign_capital_eligibility (heuristic 抽出 + "
    "operator 手動 curation) の lookup で、申請可否確定判断・FDI 規制助言 "
    "(外為法 / 行政書士法 §1) ではありません。'silent' (default) は 'Japanese "
    "statutory presumption is permissive — most programs do not exclude "
    "foreign-owned KKs unless stated' を意味し、自動承認ではありません。"
    "経営管理 visa / 事業所登記 / 外為法 30-day prior notification 等の個別確認は "
    "資格を有する行政書士・弁護士に必ずご相談ください。"
)

_DISCLAIMER_FDI_SUBSIDIES = (
    "本 response は jpi_program × am_subsidy_rule × am_industry_jsic の "
    "industry-fence + foreign-capital-eligibility filter で、申請代理・経営助言・"
    "外為法届出助言 (行政書士法 §1 / 弁護士法 §72) の代替ではありません。"
    "foreign_pct は input echo 用 (DB は per-program 外資比率 threshold を持たない); "
    "適合可否は申請要領 + 公募要領 + 外為法 prior notification 要件を一次資料で "
    "必ずご確認ください。FDI 規制 / 行政書士法 §1 / 国際課税 fence."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_autonomath() -> sqlite3.Connection | dict[str, Any]:
    """Open autonomath.db read-only, returning conn or error envelope."""
    try:
        return connect_autonomath()
    except FileNotFoundError as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {exc}",
            hint="Ensure autonomath.db exists at the repo root or AUTONOMATH_DB_PATH.",
            retry_with=["search_laws", "get_law_article_am"],
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
            retry_with=["search_laws"],
        )


def _today_iso() -> str:
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()


def _normalize_country(code: str | None) -> str | None:
    """Normalize country input. Accepts ISO alpha-2 (US / GB / SG) or
    a 'JPN' / 'JP' Japan sentinel. Returns uppercase alpha-2, or 'JP' for
    Japan, or None if input is empty.
    """
    if not code:
        return None
    c = code.strip().upper()
    # Accept 'JPN' (alpha-3) → 'JP', and other alpha-3s pass through unchanged
    # (am_tax_treaty uses alpha-2, the lookup will simply miss).
    if c == "JPN":
        return "JP"
    return c


# ---------------------------------------------------------------------------
# Tool 1: search_laws_en
# ---------------------------------------------------------------------------


def _search_laws_en_impl(q: str, limit: int = 10) -> dict[str, Any]:
    """Keyword search restricted to am_law_article rows with body_en NOT NULL."""
    if not q or not q.strip():
        return attach_corpus_snapshot(
            make_error(
                code="missing_required_arg",
                message="q is required.",
                hint="Pass a 2+ char English keyword (e.g. 'corporate tax', 'subsidy').",
                field="q",
            )
        )
    q = q.strip()
    limit = max(1, min(50, int(limit)))

    conn_or_err = _open_autonomath()
    if isinstance(conn_or_err, dict):
        return attach_corpus_snapshot(conn_or_err)
    conn = conn_or_err

    needle = f"%{q}%"
    try:
        rows = conn.execute(
            """
            SELECT a.law_canonical_id, a.article_number, a.title, a.body_en,
                   a.body_en_source_url, a.body_en_fetched_at, a.body_en_license,
                   l.canonical_name AS law_name_ja
              FROM am_law_article AS a
              LEFT JOIN am_law AS l ON l.canonical_id = a.law_canonical_id
             WHERE a.body_en IS NOT NULL
               AND (a.body_en LIKE ? OR a.title LIKE ?)
             ORDER BY a.law_canonical_id, a.article_number_sort
             LIMIT ?
            """,
            (needle, needle, limit),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("search_laws_en: sql failure %s", exc)
        return attach_corpus_snapshot(
            make_error(
                code="db_unavailable",
                message=f"search_laws_en query failed: {exc}",
                retry_with=["search_laws"],
            )
        )

    results: list[dict[str, Any]] = []
    for r in rows:
        body_en = r["body_en"] or ""
        results.append(
            {
                "law_canonical_id": r["law_canonical_id"],
                "law_name_ja": r["law_name_ja"],
                "article_number": r["article_number"],
                "title": r["title"],
                "body_en_excerpt": body_en[:400],
                "body_en_source_url": r["body_en_source_url"],
                "body_en_fetched_at": r["body_en_fetched_at"],
                "body_en_license": r["body_en_license"] or "cc_by_4.0",
                "lang": "en",
            }
        )

    next_calls: list[dict[str, Any]] = []
    if results:
        first = results[0]
        next_calls.append(
            {
                "tool": "get_law_article_en",
                "args": {
                    "law_id": first["law_canonical_id"],
                    "article_no": first["article_number"],
                },
                "rationale": "Drill into a single article's full English body.",
                "compound_mult": 1.5,
            }
        )
    next_calls.append(
        {
            "tool": "search_laws",
            "args": {"q": q, "limit": limit},
            "rationale": (
                "Fall back to the JP-only law catalog (9,484 stubs) when the "
                "EN translation corpus is thin."
            ),
            "compound_mult": 1.3,
        }
    )

    return attach_corpus_snapshot(
        {
            "query": q,
            "lang": "en",
            "total": len(results),
            "limit": limit,
            "offset": 0,
            "results": results,
            "as_of_jst": _today_iso(),
            "_disclaimer": _DISCLAIMER_LAW_EN,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# Tool 2: get_law_article_en
# ---------------------------------------------------------------------------


def _get_law_article_en_impl(law_id: str, article_no: str) -> dict[str, Any]:
    """Exact (law_id, article_no) lookup. Delegates to law_article_tool with lang='en'."""
    if not law_id:
        return attach_corpus_snapshot(
            make_error(
                code="missing_required_arg",
                message="law_id is required.",
                hint="Pass a canonical_id (e.g. 'law:corporate-tax') or law name.",
                field="law_id",
            )
        )
    if not article_no:
        return attach_corpus_snapshot(
            make_error(
                code="missing_required_arg",
                message="article_no is required.",
                hint="Pass an article number (e.g. '第41条の19' or '41-19').",
                field="article_no",
            )
        )

    # Delegate to the canonical law_article_tool with lang='en' so we share
    # the article-number normalisation + EN fallback warning logic exactly.
    from .law_article_tool import get_law_article

    payload = get_law_article(
        law_name_or_canonical_id=law_id,
        article_number=article_no,
        lang="en",
    )

    next_calls: list[dict[str, Any]] = [
        {
            "tool": "search_laws_en",
            "args": {"q": (payload.get("title") or article_no)[:30], "limit": 10},
            "rationale": "Find sibling articles within the EN corpus.",
            "compound_mult": 1.5,
        },
    ]

    payload.setdefault("_disclaimer", _DISCLAIMER_LAW_EN)
    payload.setdefault("_billing_unit", 1)
    payload["_next_calls"] = next_calls
    return attach_corpus_snapshot(payload)


# ---------------------------------------------------------------------------
# Tool 3: get_tax_treaty
# ---------------------------------------------------------------------------


def _get_tax_treaty_impl(country_a: str, country_b: str = "JPN") -> dict[str, Any]:
    """Bilateral DTA lookup over am_tax_treaty (always counterparty-vs-Japan)."""
    if not country_a:
        return attach_corpus_snapshot(
            make_error(
                code="missing_required_arg",
                message="country_a is required.",
                hint="Pass an ISO 3166-1 alpha-2 (e.g. 'US', 'GB', 'SG') or 'JPN'.",
                field="country_a",
            )
        )

    a = _normalize_country(country_a) or ""
    b = _normalize_country(country_b) or "JP"

    # am_tax_treaty rows are always (counterparty, Japan). If either side is
    # JP, use the other as the lookup key. If neither is JP, this dataset
    # cannot answer (third-country bilateral) — return seed_not_found.
    if a == "JP" and b == "JP":
        return attach_corpus_snapshot(
            make_error(
                code="invalid_enum",
                message="country_a and country_b cannot both be JP.",
                hint="am_tax_treaty rows are bilateral with Japan; pass at least one non-JP country.",
                field="country_a",
            )
        )
    if a == "JP":
        lookup_iso = b
    elif b == "JP":
        lookup_iso = a
    else:
        return attach_corpus_snapshot(
            make_error(
                code="seed_not_found",
                message=(
                    f"am_tax_treaty only stores bilateral treaties with Japan; "
                    f"third-country pair ({a}, {b}) is out of scope."
                ),
                hint="Pass country_b='JPN' (default) and a non-JP country_a.",
                field="country_b",
                extra={"queried": {"country_a": a, "country_b": b}},
            )
        )

    conn_or_err = _open_autonomath()
    if isinstance(conn_or_err, dict):
        return attach_corpus_snapshot(conn_or_err)
    conn = conn_or_err

    try:
        row = conn.execute(
            """
            SELECT country_iso, country_name_ja, country_name_en, treaty_kind,
                   dta_signed_date, dta_in_force_date,
                   wht_dividend_pct, wht_dividend_parent_pct,
                   wht_interest_pct, wht_royalty_pct,
                   pe_days_threshold, info_exchange, moaa_arbitration,
                   notes, source_url, source_fetched_at, license
              FROM am_tax_treaty
             WHERE country_iso = ?
             LIMIT 1
            """,
            (lookup_iso,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("get_tax_treaty sql failure: %s", exc)
        return attach_corpus_snapshot(
            make_error(
                code="db_unavailable",
                message=f"get_tax_treaty query failed: {exc}",
            )
        )

    if not row:
        return attach_corpus_snapshot(
            make_error(
                code="seed_not_found",
                message=(
                    f"No am_tax_treaty row for country_iso={lookup_iso!r}. "
                    f"33 of ~80 rows are hand-curated; this jurisdiction is "
                    f"pending."
                ),
                hint=(
                    "Check the MoF list at "
                    "https://www.mof.go.jp/tax_policy/summary/international/"
                    "tax_convention/tax_convetion_list_jp.html for treaty status."
                ),
                field="country_a",
                extra={"queried": {"country_a": a, "country_b": b}},
            )
        )

    treaty = {
        "country_a": a,
        "country_b": b,
        "country_iso": row["country_iso"],
        "country_name_ja": row["country_name_ja"],
        "country_name_en": row["country_name_en"],
        "treaty_kind": row["treaty_kind"],
        "dta_signed_date": row["dta_signed_date"],
        "dta_in_force_date": row["dta_in_force_date"],
        "withholding_tax_pct": {
            "dividend_general": row["wht_dividend_pct"],
            "dividend_parent_subsidiary": row["wht_dividend_parent_pct"],
            "interest": row["wht_interest_pct"],
            "royalty": row["wht_royalty_pct"],
        },
        "pe_days_threshold": row["pe_days_threshold"],
        "info_exchange": row["info_exchange"],
        "moaa_arbitration": bool(row["moaa_arbitration"]),
        "notes": row["notes"],
        "source_url": row["source_url"],
        "source_fetched_at": row["source_fetched_at"],
        "license": row["license"],
    }

    next_calls = [
        {
            "tool": "get_evidence_packet",
            "args": {"subject_kind": "program", "subject_id": "law:income-tax-act"},
            "rationale": (
                "Bundle the treaty with related Japanese tax statute extracts "
                "(法人税法 / 所得税法) for a complete cross-border package."
            ),
            "compound_mult": 1.6,
        },
        {
            "tool": "find_fdi_friendly_subsidies",
            "args": {"industry_jsic": "E", "foreign_pct": 100},
            "rationale": (
                "After WHT rates, surface FDI-eligible subsidies for the same "
                "counterparty's planned industry."
            ),
            "compound_mult": 1.4,
        },
    ]

    return attach_corpus_snapshot(
        {
            "found": True,
            "results": [treaty],
            "total": 1,
            "limit": 1,
            "offset": 0,
            "treaty": treaty,
            "as_of_jst": _today_iso(),
            "_disclaimer": _DISCLAIMER_TAX_TREATY,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# Tool 4: check_foreign_capital_eligibility
# ---------------------------------------------------------------------------


_ELIGIBILITY_VALUES = (
    "eligible",
    "eligible_with_caveat",
    "excluded",
    "silent",
    "case_by_case",
)


def _check_foreign_capital_eligibility_impl(
    houjin_bangou: str,
    program_id: str,
) -> dict[str, Any]:
    """Per-(houjin, program) foreign-capital eligibility flag lookup.

    The houjin_bangou is currently only used as input echo + future hook —
    the FDI flag lives on am_subsidy_rule (per-program), not per-corp. We
    keep the houjin parameter so the tool surface composes cleanly with
    get_houjin_360_am downstream.
    """
    if not program_id:
        return attach_corpus_snapshot(
            make_error(
                code="missing_required_arg",
                message="program_id is required.",
                hint="Pass a canonical_id (program:...) or jpintel unified_id (UNI-...).",
                field="program_id",
            )
        )

    conn_or_err = _open_autonomath()
    if isinstance(conn_or_err, dict):
        return attach_corpus_snapshot(conn_or_err)
    conn = conn_or_err

    try:
        rows = conn.execute(
            """
            SELECT s.program_entity_id, s.rule_type, s.foreign_capital_eligibility,
                   s.eligibility_cond_json, s.source_url, s.source_fetched_at,
                   e.primary_name
              FROM am_subsidy_rule AS s
              LEFT JOIN am_entities AS e ON e.canonical_id = s.program_entity_id
             WHERE s.program_entity_id = ?
            """,
            (program_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("check_foreign_capital_eligibility sql failure: %s", exc)
        return attach_corpus_snapshot(
            make_error(
                code="db_unavailable",
                message=f"check_foreign_capital_eligibility query failed: {exc}",
            )
        )

    if not rows:
        return attach_corpus_snapshot(
            make_error(
                code="seed_not_found",
                message=f"No am_subsidy_rule for program_id={program_id!r}.",
                hint=(
                    "Verify the program canonical_id via search_programs / "
                    "get_program; rule rows may not exist for very new programs."
                ),
                field="program_id",
                extra={"queried": {"program_id": program_id, "houjin_bangou": houjin_bangou}},
            )
        )

    # Aggregate across rule_types — if ANY rule says 'excluded', surface
    # excluded. Otherwise prefer the most restrictive: excluded > case_by_case
    # > eligible_with_caveat > eligible > silent. This mirrors how a 申請
    # eligibility check behaves in practice (one excluding rule wins).
    severity = {
        "excluded": 4,
        "case_by_case": 3,
        "eligible_with_caveat": 2,
        "eligible": 1,
        "silent": 0,
    }
    rule_results: list[dict[str, Any]] = []
    most_restrictive = "silent"
    most_restrictive_rank = -1
    program_name: str | None = None
    for r in rows:
        flag = r["foreign_capital_eligibility"] or "silent"
        rank = severity.get(flag, 0)
        if rank > most_restrictive_rank:
            most_restrictive_rank = rank
            most_restrictive = flag
        program_name = r["primary_name"] or program_name
        rule_results.append(
            {
                "rule_type": r["rule_type"],
                "foreign_capital_eligibility": flag,
                "source_url": r["source_url"],
                "source_fetched_at": r["source_fetched_at"],
            }
        )

    decision_explanations = {
        "eligible": "Program text explicitly confirms foreign-capital OK.",
        "eligible_with_caveat": (
            "Eligible but extra documentation (経営管理 visa / 事業所登記 / J-visa) is required."
        ),
        "excluded": "Program text explicitly excludes 外資系 / 外国法人.",
        "silent": (
            "Program text does not mention foreign capital. Japanese statutory "
            "presumption is permissive — most national programs do NOT exclude "
            "foreign-owned KKs unless stated. Verify with program office."
        ),
        "case_by_case": (
            "Program text says '個別協議' / '事務局判断'. Outcome depends on case-"
            "specific review by the program office."
        ),
    }

    next_calls = [
        {
            "tool": "get_evidence_packet",
            "args": {"subject_kind": "program", "subject_id": program_id},
            "rationale": (
                "Pull the full Evidence Packet (rules + facts + provenance) "
                "for the program before decisioning."
            ),
            "compound_mult": 1.6,
        },
        {
            "tool": "find_fdi_friendly_subsidies",
            "args": {"industry_jsic": "E", "foreign_pct": 100},
            "rationale": "Surface alternative FDI-friendly programs in the same industry.",
            "compound_mult": 1.4,
        },
    ]

    return attach_corpus_snapshot(
        {
            "found": True,
            "program_id": program_id,
            "program_name": program_name,
            "houjin_bangou": houjin_bangou or None,
            "decision": most_restrictive,
            "decision_explanation": decision_explanations.get(
                most_restrictive,
                decision_explanations["silent"],
            ),
            "rules": rule_results,
            "total": len(rule_results),
            "limit": len(rule_results),
            "offset": 0,
            "results": rule_results,
            "as_of_jst": _today_iso(),
            "_disclaimer": _DISCLAIMER_FOREIGN_CAPITAL,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# Tool 5: find_fdi_friendly_subsidies
# ---------------------------------------------------------------------------


def _find_fdi_friendly_subsidies_impl(
    industry_jsic: str,
    foreign_pct: int = 100,
    limit: int = 20,
) -> dict[str, Any]:
    """Filter programs by industry JSIC + foreign_capital_eligibility != 'excluded'."""
    if not industry_jsic:
        return attach_corpus_snapshot(
            make_error(
                code="missing_required_arg",
                message="industry_jsic is required.",
                hint="Pass a JSIC major code (A-T) or numeric medium/minor.",
                field="industry_jsic",
            )
        )
    if foreign_pct is None:
        foreign_pct = 100
    foreign_pct = max(0, min(100, int(foreign_pct)))
    limit = max(1, min(50, int(limit)))

    conn_or_err = _open_autonomath()
    if isinstance(conn_or_err, dict):
        return attach_corpus_snapshot(conn_or_err)
    conn = conn_or_err

    # The autonomath corpus has industry tags via am_relation
    # (program → industry edges) OR via primary_name keyword fence. Use the
    # latter since am_industry_jsic only carries 50 JSIC stubs (no per-program
    # mapping). We still surface the raw industry_jsic input back so the
    # caller can attribute the choice.
    industry_jsic = industry_jsic.strip().upper()

    # Pull jsic_name_ja for the filter label and to use as a fallback keyword.
    try:
        jrow = conn.execute(
            "SELECT jsic_name_ja, jsic_name_en FROM am_industry_jsic WHERE jsic_code = ? LIMIT 1",
            (industry_jsic,),
        ).fetchone()
    except sqlite3.Error:
        jrow = None
    jsic_name_ja = jrow["jsic_name_ja"] if jrow else None
    jsic_name_en = jrow["jsic_name_en"] if jrow else None

    # Build keyword fence — fall back to the jsic_name_ja itself if known.
    keywords: list[str] = []
    if jsic_name_ja:
        keywords.append(jsic_name_ja)

    try:
        if keywords:
            kw = f"%{keywords[0]}%"
            rows = conn.execute(
                """
                SELECT e.canonical_id, e.primary_name,
                       s.foreign_capital_eligibility, s.rule_type,
                       s.source_url, s.source_fetched_at
                  FROM am_entities AS e
                  JOIN am_subsidy_rule AS s
                    ON s.program_entity_id = e.canonical_id
                 WHERE e.record_kind = 'program'
                   AND e.primary_name LIKE ?
                   AND s.foreign_capital_eligibility != 'excluded'
                 ORDER BY
                   CASE s.foreign_capital_eligibility
                     WHEN 'eligible' THEN 0
                     WHEN 'eligible_with_caveat' THEN 1
                     WHEN 'case_by_case' THEN 2
                     WHEN 'silent' THEN 3
                     ELSE 4
                   END,
                   e.primary_name
                 LIMIT ?
                """,
                (kw, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT e.canonical_id, e.primary_name,
                       s.foreign_capital_eligibility, s.rule_type,
                       s.source_url, s.source_fetched_at
                  FROM am_entities AS e
                  JOIN am_subsidy_rule AS s
                    ON s.program_entity_id = e.canonical_id
                 WHERE e.record_kind = 'program'
                   AND s.foreign_capital_eligibility != 'excluded'
                 ORDER BY e.primary_name
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("find_fdi_friendly_subsidies sql failure: %s", exc)
        return attach_corpus_snapshot(
            make_error(
                code="db_unavailable",
                message=f"find_fdi_friendly_subsidies query failed: {exc}",
            )
        )

    results: list[dict[str, Any]] = []
    for r in rows:
        results.append(
            {
                "program_id": r["canonical_id"],
                "primary_name": r["primary_name"],
                "rule_type": r["rule_type"],
                "foreign_capital_eligibility": r["foreign_capital_eligibility"],
                "source_url": r["source_url"],
                "source_fetched_at": r["source_fetched_at"],
            }
        )

    next_calls: list[dict[str, Any]] = []
    if results:
        first = results[0]
        next_calls.append(
            {
                "tool": "check_foreign_capital_eligibility",
                "args": {
                    "houjin_bangou": "",
                    "program_id": first["program_id"],
                },
                "rationale": "Drill into a single program's per-rule FDI flag.",
                "compound_mult": 1.5,
            }
        )
    next_calls.append(
        {
            "tool": "get_tax_treaty",
            "args": {"country_a": "US", "country_b": "JPN"},
            "rationale": (
                "Pair the FDI-friendly subsidies with the relevant DTA so the "
                "investor sees both tax + grant context in one walk."
            ),
            "compound_mult": 1.4,
        }
    )

    return attach_corpus_snapshot(
        {
            "industry_jsic": industry_jsic,
            "industry_label_ja": jsic_name_ja,
            "industry_label_en": jsic_name_en,
            "foreign_pct_input_echo": foreign_pct,
            "total": len(results),
            "limit": limit,
            "offset": 0,
            "results": results,
            "as_of_jst": _today_iso(),
            "_disclaimer": _DISCLAIMER_FDI_SUBSIDIES,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# MCP tool registration — gated by AUTONOMATH_ENGLISH_WEDGE_ENABLED
# (default ON) and AUTONOMATH_ENABLED.
# ---------------------------------------------------------------------------

if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def search_laws_en(
        q: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description=(
                    "English keyword (2+ chars). Matches against am_law_article.body_en + "
                    "title for rows with non-NULL e-Gov 英訳 corpus."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(ge=1, le=50, description="Max results (1..50). Default 10."),
        ] = 10,
    ) -> dict[str, Any]:
        """[ENGLISH-WEDGE] Keyword search restricted to am_law_article rows where body_en (e-Gov 日本法令外国語訳, CC-BY 4.0) is present. Returns EN excerpt + source_url. Foreign-investor cohort entry point. NO LLM, single ¥3/req. 弁護士法 §72 / 国際課税 fence — disclaimer envelope mandatory."""
        return _search_laws_en_impl(q=q, limit=limit)

    @mcp.tool(annotations=_READ_ONLY)
    def get_law_article_en(
        law_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description=(
                    "Canonical law id (e.g. 'law:corporate-tax') or law name "
                    "('法人税法' / 'Corporate Tax Act' if alias exists)."
                ),
            ),
        ],
        article_no: Annotated[
            str,
            Field(
                min_length=1,
                max_length=50,
                description="Article number (e.g. '第41条の19', '41-19').",
            ),
        ],
    ) -> dict[str, Any]:
        """[ENGLISH-WEDGE] Exact (law_id, article_no) lookup returning the e-Gov 英訳 EN body. Falls back to JP body with a warning when no EN translation exists. JP version remains the only legally authoritative text. Foreign-investor cohort. NO LLM, single ¥3/req. 弁護士法 §72 fence — disclaimer envelope mandatory."""
        return _get_law_article_en_impl(law_id=law_id, article_no=article_no)

    @mcp.tool(annotations=_READ_ONLY)
    def get_tax_treaty(
        country_a: Annotated[
            str,
            Field(
                min_length=2,
                max_length=3,
                description=(
                    "ISO 3166-1 alpha-2 country code (e.g. 'US', 'GB', 'SG'). "
                    "'JPN' / 'JP' accepted as the Japan sentinel."
                ),
            ),
        ],
        country_b: Annotated[
            str,
            Field(
                min_length=2,
                max_length=3,
                description=(
                    "Counterparty country (default 'JPN'). am_tax_treaty rows are "
                    "always bilateral with Japan, so country_b='JPN' is the only "
                    "supported pairing."
                ),
            ),
        ] = "JPN",
    ) -> dict[str, Any]:
        """[ENGLISH-WEDGE] Bilateral tax-treaty lookup over am_tax_treaty (33 rows live, schema seeds ~80). Returns WHT rates (dividend / interest / royalty / parent-sub), PE threshold, info-exchange status, MoAA arbitration flag, MoF source URL. NO LLM, single ¥3/req. 税理士法 §52 / 国際課税 fence — disclaimer envelope mandatory."""
        return _get_tax_treaty_impl(country_a=country_a, country_b=country_b)

    @mcp.tool(annotations=_READ_ONLY)
    def check_foreign_capital_eligibility(
        houjin_bangou: Annotated[
            str,
            Field(
                max_length=13,
                description=(
                    "13-digit 法人番号. Empty string accepted (treated as "
                    "'any foreign-invested KK' — flag is per-program, not per-corp)."
                ),
            ),
        ],
        program_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Program canonical_id (program:...) or unified_id (UNI-...).",
            ),
        ],
    ) -> dict[str, Any]:
        """[ENGLISH-WEDGE] Per-program foreign-capital eligibility flag lookup over am_subsidy_rule.foreign_capital_eligibility (migration 092). Returns most-restrictive of {eligible / eligible_with_caveat / case_by_case / excluded / silent}. NO LLM, single ¥3/req. 行政書士法 §1 / FDI 規制 fence — disclaimer envelope mandatory."""
        return _check_foreign_capital_eligibility_impl(
            houjin_bangou=houjin_bangou,
            program_id=program_id,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def find_fdi_friendly_subsidies(
        industry_jsic: Annotated[
            str,
            Field(
                min_length=1,
                max_length=10,
                description="JSIC code (major A-T or numeric medium/minor).",
            ),
        ],
        foreign_pct: Annotated[
            int,
            Field(
                ge=0,
                le=100,
                description=(
                    "Foreign-equity percentage of the applicant (0..100). "
                    "Input echo only — DB has no per-program threshold."
                ),
            ),
        ] = 100,
        limit: Annotated[
            int,
            Field(ge=1, le=50, description="Max results. Default 20."),
        ] = 20,
    ) -> dict[str, Any]:
        """[ENGLISH-WEDGE] Find Japanese subsidy programs filtered by industry JSIC + foreign_capital_eligibility != 'excluded'. Ranks eligible > eligible_with_caveat > case_by_case > silent. NO LLM, single ¥3/req. 行政書士法 §1 / FDI 規制 fence — disclaimer envelope mandatory."""
        return _find_fdi_friendly_subsidies_impl(
            industry_jsic=industry_jsic,
            foreign_pct=foreign_pct,
            limit=limit,
        )


__all__ = [
    "_search_laws_en_impl",
    "_get_law_article_en_impl",
    "_get_tax_treaty_impl",
    "_check_foreign_capital_eligibility_impl",
    "_find_fdi_friendly_subsidies_impl",
    "_DISCLAIMER_LAW_EN",
    "_DISCLAIMER_TAX_TREATY",
    "_DISCLAIMER_FOREIGN_CAPITAL",
    "_DISCLAIMER_FDI_SUBSIDIES",
]
