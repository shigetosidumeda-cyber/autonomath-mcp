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
        "> Brand bridge: current primary brand is jpcite; formerly 税務会計AI / AutonoMath on zeimu-kaikei.ai.",
        f"> Evidence pre-fetch index for Japanese public programs: {programs:,} compact public program rows + {laws:,} laws + {cases:,} adoption case studies. The public search surface has 11,601 searchable program rows; this compact LLM index excludes rows that are not useful for answer generation.",
        "> Use this before answer generation to retrieve cited facts, source URLs, fetched_at metadata, provenance, and compatibility-rule context. It is not an answer generator.",
        "> Token and cost impact is workload-dependent. Current public self-serve pricing is tax-exclusive ¥3 per billable unit; normal search/detail calls are 1 unit. See https://jpcite.com/pricing for the current public pricing table.",
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
        "MCP exposes 151 tools in the standard configuration. The MCP server runs over stdio (protocol 2025-06-18) for Claude Desktop, Cursor, Cline, and other MCP clients. ChatGPT Custom GPTs use the OpenAPI Actions integration instead.",
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
        "- Anonymous tier: 3 requests/day/IP, free. Resets at JST next-day 00:00.",
        "- Authenticated tier: ¥3 per billable unit, billed monthly via Stripe. Monthly budget caps and protective rate limits may apply.",
        "- Authenticated AI agents should send `X-API-Key`, plus `X-Client-Tag` for customer/project attribution. Use `Idempotency-Key` on POST retries and `X-Cost-Cap-JPY` for batch or fanout budget caps.",
        "- jpcite returns source-linked, compact evidence and precomputed decision support so callers can spend fewer steps collecting and normalizing Japanese public-program data.",
        "- Support and enterprise terms are described in the public documentation.",
        "",
        "Sign up at https://jpcite.com/pricing. API keys are issued once at Stripe checkout success and shown verbatim in the response - keep the key safe; the only re-issue path is to cancel the subscription via the billing portal and re-checkout.",
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
        "3. SMB owners (中小企業経営者) - web/API-assisted subsidy, loan, tax, and public-record checks through internal assistants. Current notifications start with email; use web/API workflows for metered searches.",
        "4. VC and M&A advisors - one query by 法人番号 returns enforcement history + adoption track record + invoice-registrant status. Primary tools: search_enforcement_cases, search_acceptance_stats_am, search_invoice_registrants.",
        "5. AI agent developers - 151 MCP tools, ¥3 per billable unit, 3 anonymous requests per day. Primary tools: full surface area; see https://jpcite.com/docs/mcp-tools/.",
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
        "Generated from the published jpcite index snapshot.",
        "Format: <unified_id> | <primary_name> | <program_kind> | <amount_max_man_yen> | <source_url> | <source_fetched_at>",
        "amount_max_man_yen is denominated in 万円 (10,000 JPY); 0 means unspecified or none, not zero funding. Do not quote an amount unless source_url confirms it. Program names are kept verbatim in Japanese - do not translate.",
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
        "Publisher: jpcite. Contact: https://jpcite.com/tokushoho.html.",
        "Product: jpcite. Canonical domain: https://jpcite.com. MCP installation is documented at https://jpcite.com/docs/mcp-tools/.",
        "",
        "Data attribution:",
        "- Programs and laws cite their primary government source on each row (source_url).",
        "- Invoice-registrant data redistributed under the National Tax Agency PDL v1.0 license, with editorial annotation per their TOS.",
        "- e-Gov 法令検索 content used per the e-Gov license (CC-BY-compatible attribution required).",
        "",
        "LLM crawler policy:",
        "- This file is intended for ingestion by AI / LLM crawlers (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, and so on).",
        "- Discovery sitemap: https://jpcite.com/sitemap-llms.xml.",
        "- Sitemap index: https://jpcite.com/sitemap-index.xml.",
        "- Agent manifest: https://jpcite.com/.well-known/agents.json.",
        "- MCP manifest: https://jpcite.com/.well-known/mcp.json.",
        "- LLMS manifest: https://jpcite.com/.well-known/llms.json.",
        "- OpenAPI discovery manifest: https://jpcite.com/.well-known/openapi-discovery.json.",
        "- See https://jpcite.com/robots.txt for the canonical Allow / Disallow policy.",
        "- The Japanese-language sibling is at https://jpcite.com/llms-full.txt.",
        "- The shorter index file is at https://jpcite.com/llms.en.txt.",
        "",
        "No machine translation of program names, law titles, or case fields. Use the original Japanese labels unless an official English name is published. See https://jpcite.com/llms.en.txt for the canonical bilingual index.",
        "",
    ]


# ---------------------------------------------------------------------------
# Top-level render + atomic write.
# ---------------------------------------------------------------------------


def build_full_en(
    programs: list[sqlite3.Row],
    laws: list[sqlite3.Row],
    cases: list[sqlite3.Row],
) -> str:
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    out: list[str] = []
    out.extend(_section_header(len(programs), len(laws), len(cases), generated_at))
    out.extend(_section_about())
    out.extend(_section_pricing())
    out.extend(_section_audiences())
    out.extend(_section_coverage(len(programs), len(laws), len(cases)))
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
