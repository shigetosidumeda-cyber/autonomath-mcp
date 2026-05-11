#!/usr/bin/env python3
"""Regenerate site/llms-full.en.txt — the English-language LLM crawler dump.

Mirrors `regen_llms_full.py` (the Japanese flagship), but the structural
sections (header / overview / pricing / audience / coverage / footer) are
written in English. Program names, law titles, and case-study fields stay
in Japanese — translating them mechanically would invent canonical names
that do not exist.

Why a separate file:
  - LLM crawlers (GPTBot, ClaudeBot, PerplexityBot, ...) handle multilingual
    corpora better when the framing prose is in their query language. The
    Japanese version (`llms-full.txt`) remains the canonical source for
    Japanese queries; this English version is the index for English queries
    that should still resolve to the underlying Japanese-named programs.
  - Splitting prevents zenkaku punctuation drift in tooling that assumes
    a single locale per file.

Inputs:
  - data/jpintel.db                 (programs / laws / case_studies tables)
  - data/jpintel.db / autonomath.db are NOT cross-joined (CLAUDE.md rule).

Output (atomic write, UTF-8, LF):
  - site/llms-full.en.txt

Sections, in order:
  1. Title + abstract (English)
  2. About jpcite (English)
  3. Pricing (English, ¥3/billable unit metered)
  4. Five canonical audiences (English)
  5. Coverage statistics (English, derived from live SQL counts)
  6. All Programs (compact, pipe-delimited, Japanese names preserved)
  7. All Laws (compact, pipe-delimited, Japanese law titles preserved)
  8. All Case Studies (compact, pipe-delimited, Japanese case_titles preserved)
  9. Footer (English attribution + license)

Compact program line format (UTF-8, LF):
  <unified_id> | <primary_name> | <program_kind> | <amount_max_man_yen> | <source_url> | <source_fetched_at>

Compact law line format:
  <unified_id> | <law_title> | <law_type> | <ministry> | <revision_status> | <full_text_url>

Compact case-study line format:
  <case_id> | <case_title> | <prefecture> | <industry_name> | <total_subsidy_received_yen> | <source_url>

Idempotent: the script always rewrites the entire file from scratch — it
does NOT preserve hand edits, because every row is sourced from the DB.
This is the deliberate difference from `regen_llms_full.py`, which
preserves the docs prefix above its `## All Programs` marker.

CLI:
    uv run python scripts/regen_llms_full_en.py
    uv run python scripts/regen_llms_full_en.py --db data/jpintel.db --out site/llms-full.en.txt
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    from static_bad_urls import load_static_bad_urls  # type: ignore
except ImportError:  # pragma: no cover

    def load_static_bad_urls() -> set[str]:
        return set()


_PUBLIC_ID_PREFIX_RE = re.compile(r"^(?:MUN-\d{2,6}-\d{3}|PREF-\d{2,6}-\d{3})[_\s]+")

# ---------------------------------------------------------------------------
# SQL — every query filters out non-public review rows and excluded rows.
# Same invariants as the Japanese flagship; see CLAUDE.md non-negotiables.
# ---------------------------------------------------------------------------
_BANNED_SOURCE_HOSTS = frozenset(
    {
        "smart-hojokin.jp",
        "noukaweb.jp",
        "noukaweb.com",
        "hojyokin-portal.jp",
        "hojokin-portal.jp",
        "biz.stayway.jp",
        "biz-stayway.jp",
        "stayway.jp",
        "subsidymap.jp",
        "navit-j.com",
        "hojyokin.jp",
        "hojokin.jp",
        "creabiz.co.jp",
        "yorisoi.jp",
        "aichihojokin.com",
        "activation-service.jp",
        "jsearch.jp",
        "judgit.net",
        "news.mynavi.jp",
        "news.yahoo.co.jp",
        "shien-39.jp",
        "tamemap.net",
        "tokyo-np.co.jp",
        "yayoi-kk.co.jp",
        "jiji.com",
    }
)

PROGRAMS_SQL = """
SELECT
    unified_id,
    primary_name,
    COALESCE(program_kind, '') AS program_kind,
    COALESCE(amount_max_man_yen, 0) AS amount_max_man_yen,
    COALESCE(source_url, '') AS source_url,
    COALESCE(source_fetched_at, '') AS source_fetched_at
FROM programs
WHERE excluded = 0
  AND tier IN ('S', 'A', 'B', 'C')
  AND COALESCE(source_url_status, '') NOT IN ('broken', 'dead')
  AND COALESCE(source_last_check_status, 0) NOT IN (403, 404, 410)
ORDER BY tier, primary_name
LIMIT 20000
"""

LAWS_SQL = """
SELECT
    unified_id,
    law_title,
    COALESCE(law_type, '') AS law_type,
    COALESCE(ministry, '') AS ministry,
    COALESCE(revision_status, '') AS revision_status,
    COALESCE(full_text_url, '') AS full_text_url
FROM laws
ORDER BY revision_status, law_type, law_title
LIMIT 15000
"""

CASES_SQL = """
SELECT
    case_id,
    COALESCE(case_title, '') AS case_title,
    COALESCE(prefecture, '') AS prefecture,
    COALESCE(industry_name, '') AS industry_name,
    COALESCE(total_subsidy_received_yen, 0) AS total_subsidy_received_yen,
    COALESCE(source_url, '') AS source_url
FROM case_studies
ORDER BY prefecture, case_title
LIMIT 5000
"""

PROGRAMS_COUNT_SQL = (
    "SELECT COUNT(*) FROM programs "
    "WHERE excluded = 0 AND tier IN ('S','A','B','C') "
    "AND COALESCE(source_url_status, '') NOT IN ('broken', 'dead') "
    "AND COALESCE(source_last_check_status, 0) NOT IN (403, 404, 410)"
)
LAWS_COUNT_SQL = "SELECT COUNT(*) FROM laws"
CASES_COUNT_SQL = "SELECT COUNT(*) FROM case_studies"


# ---------------------------------------------------------------------------
# Sanitisation — keep pipe-delimited rows parseable.
# ---------------------------------------------------------------------------


def _sanitize(value: object) -> str:
    """Strip characters that would break the pipe-delimited line format.

    Removes embedded ``|``, CR, LF, and TAB; collapses whitespace runs.
    Returns an empty string for ``None``.
    """
    if value is None:
        return ""
    s = str(value)
    for bad in ("\r\n", "\r", "\n", "\t", "|"):
        s = s.replace(bad, " ")
    return " ".join(s.split())


def _public_program_name(value: str | None) -> str:
    return _PUBLIC_ID_PREFIX_RE.sub("", _sanitize(value or ""))


def _format_amount_man_yen(amount: float | int | None) -> str:
    """Format ``amount_max_man_yen`` (in 万円) compactly."""
    if amount is None:
        return "0"
    try:
        f = float(amount)
    except (TypeError, ValueError):
        return "0"
    if f == int(f):
        return str(int(f))
    return f"{f:g}"


def _format_yen(amount: int | float | None) -> str:
    """Format raw yen integers (case_studies.total_subsidy_received_yen)."""
    if amount is None:
        return "0"
    try:
        return str(int(amount))
    except (TypeError, ValueError):
        return "0"


# ---------------------------------------------------------------------------
# DB access — read-only via URI to prevent accidental writes.
# ---------------------------------------------------------------------------


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        msg = f"db not found: {db_path}"
        raise FileNotFoundError(msg)
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _safe_count(con: sqlite3.Connection, sql: str) -> int:
    """Run a count query; tolerate missing tables (returns 0)."""
    try:
        cur = con.execute(sql)
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return 0


def _safe_rows(con: sqlite3.Connection, sql: str) -> list[sqlite3.Row]:
    """Run a select; tolerate missing tables (returns [])."""
    try:
        return con.execute(sql).fetchall()
    except sqlite3.OperationalError:
        return []


def _source_host_allowed(source_url: str | None) -> bool:
    if not source_url:
        return True
    try:
        hostname = urlparse(str(source_url).strip()).hostname
    except ValueError:
        return True
    if not hostname:
        return True
    host = hostname.lower().rstrip(".")
    return not any(host == banned or host.endswith(f".{banned}") for banned in _BANNED_SOURCE_HOSTS)


# ---------------------------------------------------------------------------
# Section builders — English structural prose. ~150 lines total.
# ---------------------------------------------------------------------------


def _section_header(programs: int, laws: int, cases: int, generated_at: str) -> list[str]:
    return [
        "# jpcite - Japanese public-program database (English LLM index)",
        "",
        f"> Evidence pre-fetch index for Japanese public programs: {programs:,} compact public program rows + {laws:,} laws + {cases:,} adoption case studies. The public search surface has 11,601 searchable program rows; this compact LLM index excludes rows that are not useful for answer generation.",
        "> Use this before answer generation to retrieve cited facts, source URLs, fetched_at metadata, provenance, and compatibility-rule context. It is not an answer generator.",
        "> Token and cost impact is workload-dependent. Current public self-serve pricing is ¥3 per billable unit; normal search/detail calls are 1 unit. See Pricing for the latest terms.",
        "> Program names, law titles, and case fields stay in Japanese where applicable.",
        "> Publisher: jpcite / Canonical: https://jpcite.com",
        f"> Generated: {generated_at}",
        "",
        "---",
        "",
    ]


def _section_about() -> list[str]:
    return [
        "## About jpcite",
        "",
        "jpcite is an Evidence Pre-fetch Layer that exposes Japanese public-program data (subsidies, loans, tax measures, certifications, and related public records) as a REST API and an MCP (Model Context Protocol) server. It is built for AI application developers and enterprise RAG teams that need to ground answers about Japanese public funding in source-linked data.",
        "",
        "Public search returns source-linked rows that have passed jpcite's publication checks. Rows cite government or official institutional sources where available.",
        "",
        "MCP exposes 139 tools in the standard configuration. The MCP server runs over stdio (protocol 2025-06-18) for Claude Desktop, Cursor, Cline, and other MCP clients. ChatGPT Custom GPTs use the OpenAPI Actions integration instead.",
        "",
        "jpcite is an API-first service; downstream callers build their own product workflows and UIs.",
        "",
        "---",
        "",
    ]


def _section_pricing() -> list[str]:
    return [
        "## Pricing",
        "",
        "Fully metered: ¥3 per billable unit (¥3.30 tax-included). Normal search/detail calls are 1 unit. No tier SKUs, no seat fees, no annual minimums.",
        "",
        "- Anonymous tier: 3 requests per day per IP, free. Resets at JST next-day 00:00.",
        "- Authenticated tier: ¥3 per billable unit, billed monthly via Stripe. Monthly budget caps and protective rate limits may apply.",
        "- Authenticated AI agents may send `X-API-Key` or `Authorization: Bearer`, plus `X-Client-Tag` for customer/project attribution. Use `Idempotency-Key` on POST retries and `X-Cost-Cap-JPY` for batch or fanout budget caps.",
        "- jpcite returns source-linked, compact evidence and precomputed decision support so callers can spend fewer steps collecting and normalizing Japanese public-program data.",
        "- Support and enterprise terms are described in the public documentation.",
        "",
        "Sign up at https://jpcite.com/pricing.html. API keys are issued once at Stripe checkout success and shown verbatim in the response - keep the key safe; the only re-issue path is to cancel the subscription via the billing portal and re-checkout.",
        "",
        "---",
        "",
    ]


def _section_audiences() -> list[str]:
    return [
        "## Five canonical audiences",
        "",
        "jpcite is shaped around five concrete user shapes. Each has a representative MCP tool path.",
        "",
        "1. Tax accountants (税理士) - Claude Desktop + jpcite API. Primary tools: search_tax_incentives, evaluate_tax_applicability, list_tax_sunset_alerts.",
        "2. Certified administrative scriveners (行政書士) - one MCP call resolves subsidy + loan + permit eligibility. Primary tools: search_programs, search_loans_am, search_certifications.",
        "3. SMB owners (中小企業経営者) - web/API-assisted subsidy, loan, tax, and public-record checks through internal assistants. LINE is currently a waitlist and notification channel; use web/API workflows for metered searches.",
        "4. VC and M&A advisors - one query by 法人番号 returns enforcement history + adoption track record + invoice-registrant status. Primary tools: search_enforcement_cases, search_acceptance_stats_am, search_invoice_registrants.",
        "5. AI agent developers - 139 MCP tools, ¥3 per billable unit, 3 anonymous requests per day. Primary tools: full surface area; see https://jpcite.com/docs/mcp-tools/.",
        "",
        "---",
        "",
    ]


def _section_coverage(programs: int, laws: int, cases: int) -> list[str]:
    return [
        "## Coverage statistics",
        "",
        f"- Programs: {programs:,} normalized LLM-index rows. Public search exposes 11,601 searchable program rows.",
        f"- Laws: {laws:,} rows in the laws table (e-Gov / ministry primary sources, current + superseded + repealed).",
        f"- Case studies: {cases:,} adoption case studies (採択事例). Each row is a real adopting entity, with 法人番号 when public.",
        "- Loans: 108 rows in loan_programs (担保 / 個人保証人 / 第三者保証人 split into three independent enumerations).",
        "- Enforcement: 1,185 行政処分 cases (enforcement_cases).",
        "- Exclusion rules: 181 registered compatibility checks for duplicate use, prerequisites, and related caveats.",
        "",
        "Update cadence: programs daily; laws delta-loaded continuously from e-Gov; case studies monthly; enforcement weekly.",
        "",
        "---",
        "",
    ]


def _section_programs(rows: list[sqlite3.Row]) -> list[str]:
    """Compact pipe-delimited program inventory. Japanese names preserved."""
    count = len(rows)
    out: list[str] = [
        f"## All Programs ({count:,} compact public program rows)",
        "",
        "Generated from the current public jpcite dataset.",
        "Format: <unified_id> | <primary_name> | <program_kind> | <amount_max_man_yen> | <source_url> | <source_fetched_at>",
        "amount_max_man_yen is denominated in 万円 (10,000 JPY); 0 means unspecified or none. Program names are kept verbatim in Japanese - do not translate.",
        "",
    ]
    for row in rows:
        out.append(
            " | ".join(
                [
                    _sanitize(row["unified_id"]),
                    _public_program_name(row["primary_name"]),
                    _sanitize(row["program_kind"]),
                    _format_amount_man_yen(row["amount_max_man_yen"]),
                    _sanitize(row["source_url"]),
                    _sanitize(row["source_fetched_at"]),
                ]
            )
        )
    out.append("")
    return out


def _section_laws(rows: list[sqlite3.Row]) -> list[str]:
    """Compact pipe-delimited law inventory. Japanese law_title preserved."""
    count = len(rows)
    out: list[str] = [
        f"## All Laws ({count:,} entries, compact)",
        "",
        "Source: e-Gov 法令検索 + ministry primary sources.",
        "Format: <unified_id> | <law_title> | <law_type> | <ministry> | <revision_status> | <full_text_url>",
        "Law titles are kept verbatim in Japanese. Use the e-Gov English-title index for official transliterations where they exist.",
        "",
    ]
    for row in rows:
        out.append(
            " | ".join(
                [
                    _sanitize(row["unified_id"]),
                    _sanitize(row["law_title"]),
                    _sanitize(row["law_type"]),
                    _sanitize(row["ministry"]),
                    _sanitize(row["revision_status"]),
                    _sanitize(row["full_text_url"]),
                ]
            )
        )
    out.append("")
    return out


def _section_cases(rows: list[sqlite3.Row]) -> list[str]:
    """Compact pipe-delimited adoption case studies. Japanese fields preserved."""
    count = len(rows)
    out: list[str] = [
        f"## All Case Studies ({count:,} entries, compact)",
        "",
        "Source: ministry / prefecture adoption announcements.",
        "Format: <case_id> | <case_title> | <prefecture> | <industry_name> | <total_subsidy_received_yen> | <source_url>",
        "case_title and industry_name are kept verbatim in Japanese.",
        "",
    ]
    for row in rows:
        out.append(
            " | ".join(
                [
                    _sanitize(row["case_id"]),
                    _sanitize(row["case_title"]),
                    _sanitize(row["prefecture"]),
                    _sanitize(row["industry_name"]),
                    _format_yen(row["total_subsidy_received_yen"]),
                    _sanitize(row["source_url"]),
                ]
            )
        )
    out.append("")
    return out


def _section_footer() -> list[str]:
    return [
        "---",
        "",
        "## License and attribution",
        "",
        "Publisher: jpcite. Contact: https://jpcite.com/docs/compliance/tokushoho/.",
        "Product: jpcite. Canonical domain: https://jpcite.com. MCP installation is documented at https://jpcite.com/docs/mcp-tools/.",
        "",
        "Data attribution:",
        "- Programs and laws cite their primary government source on each row (source_url).",
        "- Invoice-registrant data redistributed under the National Tax Agency PDL v1.0 license, with editorial annotation per their TOS.",
        "- e-Gov 法令検索 content used per the e-Gov license (CC-BY-compatible attribution required).",
        "",
        "LLM crawler policy:",
        "- This file is intended for ingestion by AI / LLM crawlers (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, and so on).",
        "- See https://jpcite.com/robots.txt for the canonical Allow / Disallow policy.",
        "- The Japanese-language sibling is at https://jpcite.com/llms-full.txt.",
        "- The shorter index file is at https://jpcite.com/llms.en.txt.",
        "",
        "No machine translation of program names, law titles, or case fields. Use the original Japanese labels unless an official English name is published. See https://jpcite.com/docs/i18n_strategy/ for the canonical bilingual policy.",
        "",
    ]


# ---------------------------------------------------------------------------
# Top-level render + atomic write.
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict:
    """Best-effort JSON loader. Returns {} on any failure so regen never breaks."""
    try:
        import json

        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _section_brand_contact() -> list[str]:
    return [
        "## Brand & Contact",
        "",
        "- **Product:** jpcite (Legacy brands 税務会計AI / AutonoMath / zeimu-kaikei.ai appear only as SEO citation bridge markers; the current active brand is jpcite.)",
        "- **Operator:** Bookyou株式会社 (Bookyou Co., Ltd.)",
        "- **Qualified Invoice Issuer (適格請求書発行事業者) registration:** T8010001213708 (registered Reiwa 7 May 12)",
        "- **Registered address:** 2-22-1 Kohinata, Bunkyo-ku, Tokyo 112-0006, Japan",
        "- **Representative:** Shigetoshi Umeda",
        "- **Contact:** info@bookyou.net",
        "- **Canonical site:** https://jpcite.com/",
        "- **API base URL:** https://api.jpcite.com/",
        "- **Specified Commercial Transactions Act page:** https://jpcite.com/tokushoho.html",
        "- **Privacy policy:** https://jpcite.com/privacy.html",
        "- **Terms of service:** https://jpcite.com/tos.html",
        "- **PyPI package:** `autonomath-mcp` (legacy distribution name retained for backward compatibility).",
        "",
        "---",
        "",
    ]


def _section_authentication() -> list[str]:
    return [
        "## Authentication",
        "",
        "jpcite uses **API key (header)** authentication only.",
        "",
        "- **HTTP header:** `X-API-Key: <key>` (recommended). `Authorization: Bearer <key>` is also accepted.",
        "- **Environment variable:** `JPCITE_API_KEY` (recommended), or the compatibility alias `AUTONOMATH_API_KEY`.",
        "- **Key prefixes:**",
        "  - `jc_` - issued from 2026-04-30 onward (jpcite brand era).",
        "  - `sk_` - legacy stripe-derived prefix. Existing keys remain valid indefinitely.",
        "  - `am_` - autonomath-mcp transition prefix. Same backward-compatible policy.",
        "- **Issuance:** API keys are returned verbatim once, at Stripe Checkout success.",
        "- **Anonymous fallback:** 3 requests / day per IP, JST 00:00 next-day reset, 429 on excess.",
        "- **`X-Client-Tag` header:** Optional attribution string for B2B fan-out (customer / 顧問先).",
        "- **`X-Cost-Cap-JPY` header:** Optional per-request total budget (ex-tax JPY) for batch / fan-out routes.",
        "- **`Idempotency-Key` header:** Required for safe retries on POST routes.",
        "",
        "---",
        "",
    ]


def _section_pricing_cost_examples(mcp_json: dict) -> list[str]:
    cost_examples = (
        mcp_json.get("pricing", {}).get("cost_examples", [])
        if isinstance(mcp_json, dict)
        else []
    )
    out = [
        "## Pricing detail (with cost_examples)",
        "",
        "- **Unit price:** **¥3 / billable unit (ex-tax)**, **¥3.30 tax-included**.",
        "- **What counts as 1 billable unit:** Standard search, detail, exclusion-rule check, and meta calls are 1 unit each. Batch routes sum their internal sub-calls.",
        "- **Anonymous quota:** 3 requests per day per IP, free. JST 00:00 next-day reset.",
        "- **Monthly budget cap:** Configurable from the Stripe Customer Portal.",
        "- **No tier SKUs:** No Starter / Pro / Enterprise plan ladders.",
        "- **Invoice:** Stripe issues a monthly qualified invoice (issuer T8010001213708) with 10% consumption tax.",
        "- **Refund:** Generally not provided; usage-record errors result in refund or invoice adjustment.",
        "- **Cancellation:** Remove the card or cancel via Stripe Customer Portal; reverts to anonymous immediately.",
        "",
        "### cost_examples (published estimates)",
        "",
        "| Use case | requests | JPY (tax-incl.) | Note |",
        "|---|---|---|---|",
    ]
    for ex in cost_examples:
        name = ex.get("name", "")
        req = ex.get("req", 0)
        jpy = ex.get("jpy_inc_tax", 0)
        note = ex.get("note", "")
        out.append(f"| {name} | {req:,} | ¥{jpy:,} | {note} |")
    out.append("")
    out.append(
        "All cost_examples assume **no LLM inference is performed by jpcite**. LLM token usage is billed by the caller's own model provider."
    )
    out.append("")
    out.append("---")
    out.append("")
    return out


def _section_coverage_detail() -> list[str]:
    return [
        "## Coverage (production snapshot)",
        "",
        "**Primary SQLite (jpcite primary DB, ~352 MB)**",
        "",
        "- **programs:** 11,601 searchable. tier S=114 / A=1,340 / B=4,186 / C=5,961. Full table 14,472.",
        "- **case_studies (採択事例):** 2,286 rows.",
        "- **loan_programs:** 108 rows. Collateral / individual guarantor / third-party guarantor split into three independent enums.",
        "- **enforcement_cases (行政処分):** 1,185 rows.",
        "- **laws:** 9,484 catalog stubs / 6,493 full-text indexed (e-Gov, CC-BY-4.0).",
        "- **tax_rulesets:** 50 rows.",
        "- **court_decisions:** 2,065 rows live.",
        "- **bids:** 362 rows live.",
        "- **invoice_registrants (適格請求書発行事業者):** 13,801 rows delta. Monthly 4M-row bulk via `nta-bulk-monthly` workflow.",
        "- **exclusion / prerequisite rules:** 181 rows.",
        "",
        "**Entity-fact EAV substrate (~9.4 GB)**",
        "",
        "- **am_entities:** 503,930 rows across 12 record_kinds.",
        "- **am_entity_facts:** 6.12M rows.",
        "- **am_relation:** 177,381 edges.",
        "- **am_alias:** 335,605 rows.",
        "- **am_law_article:** 353,278 rows.",
        "- **am_enforcement_detail:** 22,258 rows (6,455 with 法人番号).",
        "- **am_amendment_snapshot:** 14,596 captures.",
        "- **am_amendment_diff:** 12,116 rows (cron-live).",
        "- **am_tax_treaty:** 33 rows live (international tax cohort, ~80-country seed schema).",
        "- **78 jpi_\\* mirrored tables** across tax measures / certifications / laws / authorities / adoptions / enforcements / loans / mutual insurance / regions.",
        "- **FTS5:** trigram + unicode61 tokenizers.",
        "- **sqlite-vec:** 5 tiered vec indexes.",
        "",
        "---",
        "",
    ]


def _section_business_law_fences(fence_registry: dict) -> list[str]:
    fences_list = fence_registry.get("fences", []) if isinstance(fence_registry, dict) else []
    canonical_count = (
        fence_registry.get("canonical_count", 7) if isinstance(fence_registry, dict) else 7
    )
    labels = {
        "tax_accountant": "Tax Accountant (税理士)",
        "lawyer": "Lawyer (弁護士)",
        "judicial_scrivener": "Judicial Scrivener (司法書士)",
        "administrative_scrivener": "Administrative Scrivener (行政書士)",
        "sharoushi": "Labor & Social Security Attorney (社会保険労務士)",
        "sme_diagnostician": "SME Management Consultant (中小企業診断士)",
        "patent_attorney": "Patent Attorney (弁理士)",
    }
    out = [
        f"## Business-law (業法) fences ({canonical_count} canonical; 8th in expansion)",
        "",
        f"`data/fence_registry.json` canonical_count = **{canonical_count}**. Every API response carries a `_disclaimer` envelope per fence per call.",
        "",
    ]
    for i, f in enumerate(fences_list, 1):
        fid = f.get("id", "")
        law = f.get("law", "")
        article = f.get("article", "")
        scope = f.get("scope", "")
        do_not = f.get("do_not", [])
        may_do = f.get("may_do", [])
        disc_en = f.get("disclaimer_en", "")
        out.append(f"### {i}. {labels.get(fid, fid)} fence (`{fid}`)")
        out.append(f"- **Statute:** {law} {article}")
        out.append(f"- **Scope:** {scope}")
        out.append(f"- **do_not:** {', '.join(do_not)}")
        out.append(f"- **may_do:** {', '.join(may_do)}")
        out.append(f"- **Per-call _disclaimer:** {disc_en}")
        out.append("")
    out.append(
        "Candidate 8th fence (in expansion): **Administrative Procedure Act §3** disadvantage-disposition fence."
    )
    out.append("")
    out.append("---")
    out.append("")
    return out


def _section_mcp_tools_manifest(mcp_server_json: dict) -> list[str]:
    tools = mcp_server_json.get("tools", []) if isinstance(mcp_server_json, dict) else []
    out = [
        f"## MCP {len(tools)} tools manifest (full list)",
        "",
        f"Full expansion of the `tools[]` array in `site/mcp-server.json`. Default-gate count = **{len(tools)}**.",
        "",
        "Format: `<tool name>` - <description one-liner>",
        "",
    ]
    for t in tools:
        name = t.get("name", "")
        desc = (t.get("description") or "").replace("\n", " ").strip()
        if len(desc) > 280:
            desc = desc[:277] + "..."
        out.append(f"- `{name}` - {desc}")
    out.append("")
    out.append("Gated off (default OFF): `query_at_snapshot`, `intent_of`, `reason_answer`, `render_36_kyotei_am`, `get_36_kyotei_metadata_am`.")
    out.append("")
    out.append("---")
    out.append("")
    return out


def _section_openapi_paths_manifest(openapi_json: dict) -> list[str]:
    paths = openapi_json.get("paths", {}) if isinstance(openapi_json, dict) else {}
    out = [
        f"## OpenAPI {len(paths)} path manifest (full list)",
        "",
        f"Full expansion of the `paths` object in `docs/openapi/v1.json`. **{len(paths)}** paths.",
        "",
        "Format: `<METHOD>` `<path>` - <summary one-liner>",
        "",
    ]
    for p in sorted(paths.keys()):
        methods = paths[p]
        for m in ["get", "post", "put", "delete", "patch"]:
            if m in methods:
                entry = methods[m]
                summary = (entry.get("summary") or entry.get("operationId") or "").replace(
                    "\n", " "
                ).strip()
                if len(summary) > 200:
                    summary = summary[:197] + "..."
                out.append(f"- `{m.upper()}` `{p}` - {summary}")
    out.append("")
    out.append(
        "The agent-safe slim profile (`site/openapi.agent.json` / `site/openapi.agent.gpt30.json`) is a 25-50-path subset for Custom GPT / Claude Skill 30-action ceilings."
    )
    out.append("")
    out.append("---")
    out.append("")
    return out


def _section_cohort_revenue_model() -> list[str]:
    return [
        "## 8-cohort revenue model (locked 2026-04-29)",
        "",
        "1. **M&A** - `houjin_watch` (migration 088) + `dispatch_webhooks.py` cron.",
        "2. **Tax accountants (税理士)** - `audit_seal` (migration 089) + monthly PDF/RSS pack.",
        "3. **Certified Public Accountants** - shares 税理士 surface; differentiated by v2 `tax_rulesets`.",
        "4. **Foreign FDI** - `law_articles.body_en` (mig 090) + `am_tax_treaty` (mig 091) + `foreign_capital_eligibility` (mig 092).",
        "5. **Subsidy consultants** - `client_profiles` (mig 096) + `saved_searches.profile_ids` (mig 097) + `run_saved_searches.py` cron.",
        "6. **SMB LINE** - `line_users` + `widget_keys`. Lightweight conversational surface.",
        "7. **Shinkin & Shokokai organic** - S/A-tier coverage + organic SEO via `index_now_ping.py`. Zero paid acquisition.",
        "8. **Industry packs** - `pack_construction` / `pack_manufacturing` / `pack_real_estate` + `program_post_award_calendar` (mig 098).",
        "",
        "Engagement multiplier: `recurring_engagement` (mig 099) + `courses.py` + `trust_infrastructure` (mig 101).",
        "",
        "---",
        "",
    ]


def _section_cross_reference_axes() -> list[str]:
    return [
        "## 22-axis cross-reference cohort (12 base + 10 R8 grow, 2026-05-07)",
        "",
        "12 base axes (on `site/facts.html`): 制度 × 法令 / adoption / case-law / enforcement / exclusion rules / amendment / region; law × article amendment; adoption × industry-scale; counterparty × invoice-registrant; bids × programs; corp × disposition history.",
        "",
        "R8 grow (2026-05-07, +10 endpoints):",
        "",
        "1. Adoption × industry × scale × region cohort matcher - `POST /v1/cases/cohort_match`.",
        "2. Legal-form × program matrix - `api/compatibility.py`.",
        "3. Tax-rule chain - `GET /v1/tax_rules/{rule_id}/full_chain`.",
        "4. M&A / succession program matcher - `api/succession.py`.",
        "5. Disaster recovery × special-measure program surface.",
        "6. Policy upstream signal - `api/policy_upstream.py`.",
        "7. Unified houjin 360 (3-axis scoring) - `api/houjin_360.py`.",
        "8. am_compat_matrix portfolio_optimize + pair compatibility.",
        "9. Cross-reference deep links - programs full_context + laws related_programs + cases narrow.",
        "10. Dynamic eligibility check + amendment-alert subscription + industry benchmark / missed programs.",
        "",
        "---",
        "",
    ]


def _section_install_paths() -> list[str]:
    return [
        "## Install / client integration",
        "",
        "### Claude Desktop (stdio MCP)",
        "",
        "```json",
        "{",
        '  "mcpServers": {',
        '    "jpcite": {',
        '      "command": "uvx",',
        '      "args": ["autonomath-mcp"],',
        '      "env": { "JPCITE_API_KEY": "jc_xxxxxxxxxxxx" }',
        "    }",
        "  }",
        "}",
        "```",
        "",
        "### Cursor / Codex CLI / Cline (stdio MCP)",
        "",
        "Same `command=uvx, args=[autonomath-mcp]` shape as Claude Desktop.",
        "",
        "### ChatGPT Custom GPT (OpenAPI Actions)",
        "",
        "Import `https://api.jpcite.com/v1/openapi.agent.json` (slim 30-path profile) into Custom GPT Actions; auth = API Key (`X-API-Key`).",
        "",
        "### Anthropic API direct (Tool Use)",
        "",
        "Claude API Tool Use - REST - jpcite. No MCP stdio runtime needed.",
        "",
        "### Python (REST direct)",
        "",
        "```python",
        "import requests",
        'r = requests.get("https://api.jpcite.com/v1/programs/search",',
        '                 params={"q": "monozukuri", "limit": 10},',
        '                 headers={"X-API-Key": "jc_xxxxxxxxxxxx"})',
        "print(r.json())",
        "```",
        "",
        "### Node.js (fetch)",
        "",
        "```javascript",
        "const r = await fetch('https://api.jpcite.com/v1/programs/search?q=DX&limit=10',",
        "  { headers: { 'X-API-Key': 'jc_xxxxxxxxxxxx' } });",
        "console.log(await r.json());",
        "```",
        "",
        "---",
        "",
    ]


def _section_recurring_workflows(mcp_json: dict) -> list[str]:
    workflows = (
        mcp_json.get("recurring_agent_workflows", {}).get("workflows", [])
        if isinstance(mcp_json, dict)
        else []
    )
    out = [
        "## Recurring agent workflows",
        "",
        "Agents follow: (1) anonymous 3 req/day trial - (2) `previewCost` estimate - (3) attach `X-API-Key` for paid runs.",
        "",
    ]
    for wf in workflows:
        out.append(
            f"- **{wf.get('id')}** - first_paid_call: `{wf.get('first_paid_call')}` / sequence: {' - '.join(wf.get('sequence', []))}"
        )
    out.append("")
    out.append(
        "Activation rule: Choose one first paid evidence call, use previewCost before broad runs, rerun with X-API-Key after the anonymous daily trial, set X-Client-Tag for attribution."
    )
    out.append("")
    out.append("---")
    out.append("")
    return out


def build_full_en(
    programs: list[sqlite3.Row],
    laws: list[sqlite3.Row],
    cases: list[sqlite3.Row],
) -> str:
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Best-effort discovery surface loaders. Failure to load any of these does
    # not abort regen - the file simply omits the section.
    _here = Path(__file__).resolve().parent.parent
    mcp_json = _load_json(_here / "site" / ".well-known" / "mcp.json")
    fence_registry = _load_json(_here / "data" / "fence_registry.json")
    mcp_server_json = _load_json(_here / "site" / "mcp-server.json")
    openapi_json = _load_json(_here / "docs" / "openapi" / "v1.json")

    out: list[str] = []
    out.extend(_section_header(len(programs), len(laws), len(cases), generated_at))
    out.extend(_section_about())
    out.extend(_section_pricing())
    out.extend(_section_audiences())
    out.extend(_section_coverage(len(programs), len(laws), len(cases)))
    out.extend(_section_brand_contact())
    out.extend(_section_authentication())
    out.extend(_section_pricing_cost_examples(mcp_json))
    out.extend(_section_coverage_detail())
    out.extend(_section_business_law_fences(fence_registry))
    out.extend(_section_mcp_tools_manifest(mcp_server_json))
    out.extend(_section_openapi_paths_manifest(openapi_json))
    out.extend(_section_cohort_revenue_model())
    out.extend(_section_cross_reference_axes())
    out.extend(_section_install_paths())
    out.extend(_section_recurring_workflows(mcp_json))
    out.extend(_section_programs(programs))
    out.extend(_section_laws(laws))
    out.extend(_section_cases(cases))
    out.extend(_section_footer())

    return "\n".join(out)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/jpintel.db"),
        help="Path to jpintel.db (default: data/jpintel.db relative to cwd).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("site/llms-full.en.txt"),
        help="Path to llms-full.en.txt (default: site/llms-full.en.txt).",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=5 * 1024 * 1024,
        help="Refuse to write if the result exceeds this size (default: 5 MiB).",
    )
    args = parser.parse_args(argv)

    db_path: Path = args.db.resolve()
    out_path: Path = args.out.resolve()

    with _connect_ro(db_path) as con:
        denied = load_static_bad_urls()
        programs = [
            row
            for row in _safe_rows(con, PROGRAMS_SQL)
            if _source_host_allowed(row["source_url"]) and row["source_url"] not in denied
        ]
        laws = _safe_rows(con, LAWS_SQL)
        cases = _safe_rows(con, CASES_SQL)

    if not programs:
        sys.stderr.write("warn: programs query returned 0 rows; aborting\n")
        return 2

    content = build_full_en(programs, laws, cases)
    new_bytes = content.encode("utf-8")
    if len(new_bytes) > args.max_bytes:
        sys.stderr.write(
            f"error: rendered file is {len(new_bytes):,} bytes, "
            f"exceeds --max-bytes={args.max_bytes:,}\n"
        )
        return 3

    atomic_write(out_path, content)

    sys.stdout.write(
        f"wrote {out_path} | "
        f"programs={len(programs):,} | laws={len(laws):,} | cases={len(cases):,} | "
        f"bytes={len(new_bytes):,} | lines={content.count(chr(10)) + 1:,}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
