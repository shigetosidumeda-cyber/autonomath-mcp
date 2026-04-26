#!/usr/bin/env python3
"""Regenerate site/llms-full.en.txt — the English-language LLM crawler dump.

Mirrors `regen_llms_full.py` (the Japanese flagship), but the structural
sections (header / overview / pricing / audience / coverage / footer) are
written in English. Program names, law titles, and case-study fields stay
in Japanese — translating them mechanically would invent canonical names
that do not exist (memory `feedback_no_fake_data` / fraud-risk vector
per `feedback_autonomath_fraud_risk`).

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
  2. About AutonoMath (English)
  3. Pricing (English, ¥3/req metered)
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
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# SQL — every query filters out the quarantine tier ('X') and excluded rows.
# Same invariants as the Japanese flagship; see CLAUDE.md non-negotiables.
# ---------------------------------------------------------------------------

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
    "WHERE excluded = 0 AND tier IN ('S','A','B','C')"
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


# ---------------------------------------------------------------------------
# Section builders — English structural prose. ~150 lines total.
# ---------------------------------------------------------------------------


def _section_header(programs: int, laws: int, cases: int, generated_at: str) -> list[str]:
    return [
        "# AutonoMath - Japanese public-program database (English LLM index)",
        "",
        f"> Cross-search of Japanese public programs (subsidies, loans, tax measures, certifications): {programs:,} programs + {laws:,} laws + {cases:,} adoption case studies.",
        "> llms-full.en.txt is the English-language LLM crawler dump. Program names, law titles, and case fields stay in Japanese - they are legal entity names and must not be machine-translated.",
        "> Operator: Bookyou Inc. (法人番号 T8010001213708) / Canonical: https://autonomath.ai",
        f"> Generated: {generated_at}",
        "",
        "---",
        "",
    ]


def _section_about() -> list[str]:
    return [
        "## About AutonoMath",
        "",
        "AutonoMath is a developer platform that exposes Japanese public-program data (subsidies, loans, tax measures, certifications, agricultural support) as a REST API and an MCP (Model Context Protocol) server. It is built for AI application developers and enterprise RAG teams that need to ground answers about Japanese public funding in primary-source data.",
        "",
        "Programs are scored on a Tier S/A/B/C/X quality ladder; Tier X is a quarantine tier and is hard-excluded from every search path. Each row cites a primary government source (ministry, prefecture, Japan Finance Corporation, and so on). Aggregator URLs are banned at ingest time to avoid second-hand misinformation.",
        "",
        "MCP exposes 66 tools (38 jpintel + 28 autonomath: 17 V1 + 4 V4 universal + 7 Phase A absorption). The MCP server runs over stdio and is compatible with Claude Desktop, Cursor, and ChatGPT (Plus and above).",
        "",
        "Direct end users (sole proprietors, tax accountants, certified administrative scriveners) are NOT the primary audience. AutonoMath is an API; downstream callers build the UIs.",
        "",
        "---",
        "",
    ]


def _section_pricing() -> list[str]:
    return [
        "## Pricing",
        "",
        "Fully metered: ¥3 per request (¥3.30 tax-included). No tier SKUs, no seat fees, no annual minimums.",
        "",
        "- Anonymous tier: 50 requests per month per IP, free. Resets at JST month-start (00:00).",
        "- Authenticated tier: ¥3 per request, billed monthly via Stripe. Reset at UTC month-start.",
        "- Acquisition: 100% organic. No paid ads, no sales calls, no cold outreach.",
        "- Operations: solo, zero-touch. No DPA / MSA negotiation, no Slack Connect, no phone support.",
        "",
        "Sign up at https://autonomath.ai/pricing.html. API keys are issued once at Stripe checkout success and shown verbatim in the response - keep the key safe; the only re-issue path is to cancel the subscription via the billing portal and re-checkout.",
        "",
        "---",
        "",
    ]


def _section_audiences() -> list[str]:
    return [
        "## Five canonical audiences",
        "",
        "AutonoMath is shaped around five concrete user shapes. Each has a representative cost ceiling and a representative MCP tool path.",
        "",
        "1. Tax accountants (税理士) - Claude Desktop + AutonoMath API. Roughly ¥1,000 per month metered. Primary tools: search_tax_incentives, evaluate_tax_applicability, list_tax_sunset_alerts.",
        "2. Certified administrative scriveners (行政書士) - one MCP call resolves subsidy + loan + permit eligibility. Primary tools: search_programs, search_loans_am, search_certifications.",
        "3. SMB owners (中小企業経営者) - LINE chatbot frontends. 10 questions per month free, ¥3 per question after. Primary tools: smb_starter_pack, subsidy_combo_finder, deadline_calendar.",
        "4. VC and M&A advisors - one query by 法人番号 returns enforcement history + adoption track record + invoice-registrant status. Primary tools: search_enforcement_cases, search_acceptance_stats_am, search_invoice_registrants.",
        "5. AI agent developers - 66 MCP tools, ¥3 per request, 50 free per month. Primary tools: full surface area; see https://autonomath.ai/docs/mcp-tools/.",
        "",
        "---",
        "",
    ]


def _section_coverage(programs: int, laws: int, cases: int) -> list[str]:
    return [
        "## Coverage statistics",
        "",
        f"- Programs: {programs:,} active rows (excluded=0, tier in S/A/B/C). Tier X is the quarantine tier and is excluded everywhere.",
        f"- Laws: {laws:,} rows in the laws table (e-Gov / ministry primary sources, current + superseded + repealed).",
        f"- Case studies: {cases:,} adoption case studies (採択事例). Each row is a real adopting entity, with 法人番号 when public.",
        "- Loans: 108 rows in loan_programs (担保 / 個人保証人 / 第三者保証人 split into three independent enumerations).",
        "- Enforcement: 1,185 行政処分 cases (enforcement_cases).",
        "- Exclusion rules: 181 hand-seeded + auto-extracted exclusivity rules (補助金併用不可 / prerequisite chains).",
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
        f"## All Programs ({count:,} entries, compact)",
        "",
        "Filter: excluded=0 AND tier IN (S,A,B,C). Tier X (quarantine) is excluded.",
        "Format: <unified_id> | <primary_name> | <program_kind> | <amount_max_man_yen> | <source_url> | <source_fetched_at>",
        "amount_max_man_yen is denominated in 万円 (10,000 JPY); 0 means unspecified or none. Program names are kept verbatim in Japanese - do not translate.",
        "",
    ]
    for row in rows:
        out.append(
            " | ".join([
                _sanitize(row["unified_id"]),
                _sanitize(row["primary_name"]),
                _sanitize(row["program_kind"]),
                _format_amount_man_yen(row["amount_max_man_yen"]),
                _sanitize(row["source_url"]),
                _sanitize(row["source_fetched_at"]),
            ])
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
            " | ".join([
                _sanitize(row["unified_id"]),
                _sanitize(row["law_title"]),
                _sanitize(row["law_type"]),
                _sanitize(row["ministry"]),
                _sanitize(row["revision_status"]),
                _sanitize(row["full_text_url"]),
            ])
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
            " | ".join([
                _sanitize(row["case_id"]),
                _sanitize(row["case_title"]),
                _sanitize(row["prefecture"]),
                _sanitize(row["industry_name"]),
                _format_yen(row["total_subsidy_received_yen"]),
                _sanitize(row["source_url"]),
            ])
        )
    out.append("")
    return out


def _section_footer() -> list[str]:
    return [
        "---",
        "",
        "## License and attribution",
        "",
        "Operator: Bookyou Inc. (法人番号 T8010001213708), 代表取締役 梅田茂利, info@bookyou.net.",
        "Product: AutonoMath. Canonical domain: https://autonomath.ai. PyPI package: autonomath-mcp.",
        "",
        "Data attribution:",
        "- Programs and laws cite their primary government source on each row (source_url).",
        "- Invoice-registrant data redistributed under the National Tax Agency PDL v1.0 license, with editorial annotation per their TOS.",
        "- e-Gov 法令検索 content used per the e-Gov license (CC-BY-compatible attribution required).",
        "",
        "LLM crawler policy:",
        "- This file is intended for ingestion by AI / LLM crawlers (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, and so on).",
        "- See https://autonomath.ai/robots.txt for the canonical Allow / Disallow policy.",
        "- The Japanese-language sibling is at https://autonomath.ai/llms-full.txt.",
        "- The shorter index file is at https://autonomath.ai/llms.en.txt.",
        "",
        "No machine translation of program names, law titles, or case fields. They are Japanese legal entity names; inventing English names would be a fraud-risk vector. See https://autonomath.ai/docs/i18n_strategy/ for the canonical bilingual policy.",
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
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
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
        programs = _safe_rows(con, PROGRAMS_SQL)
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
