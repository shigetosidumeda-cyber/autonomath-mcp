#!/usr/bin/env python3
"""Generate 47 prefecture-level SEO landing pages for jpcite.com.

Targets long-tail organic queries like:
    "<都道府県名> 補助金"
    "<都道府県名> 融資"
    "<都道府県名> 行政処分"
    "<都道府県名> 採択事例"

Input:
    data/jpintel.db (SQLite). Tables used: programs, case_studies, loan_programs,
    enforcement_cases.
Output:
    site/prefectures/{slug}.html  (47 pages, slug = hokkaido / tokyo / kyoto / ...)
    site/prefectures/index.html   (47-link landing index, region-grouped)
    site/sitemap-prefectures.xml  (47 + 1 URL sitemap fragment, included from
                                   sitemap-index.xml — no overlap with C4's
                                   sitemap-programs.xml or the static sitemap.xml)

Per-prefecture content:
    - top 20 programs (tier S/A first, then B, C; excluded=0; aggregator banned)
    - top 10 case_studies (prefecture filter; confidence DESC)
    - top 5 loan_programs (NATIONAL — loan_programs has no prefecture column;
      we expose the same nationwide JFC/商工中金 set on every prefecture page,
      ranked by amount_max_yen DESC, but contextualised in copy)
    - top 5 enforcement_cases (prefecture filter; disclosed_date DESC)

Design references:
    - docs/seo_strategy.md           (organic acquisition strategy, 2026-04-25)
    - docs/seo_technical_audit.md    (canonical, JSON-LD, audit checklist)
    - site/_templates/prefecture.html (Jinja2 template, this script renders it)
    - scripts/_pref_slugs.py         (canonical 47 slug ↔ JA mapping)
    - scripts/generate_program_pages.py (sibling — per-program pages, owned by C4)

This script does NOT touch:
    - scripts/generate_program_pages.py
    - site/sitemap.xml, site/sitemap-programs.xml, site/sitemap-index.xml
      (we write a separate sitemap-prefectures.xml; user manually updates the
      sitemap-index.xml entry once if desired — see docs/seo_strategy.md)

Usage:
    .venv/bin/python scripts/generate_prefecture_pages.py
    .venv/bin/python scripts/generate_prefecture_pages.py --slug tokyo --dry-run
    .venv/bin/python scripts/generate_prefecture_pages.py --domain example.com

Exit codes:
    0  success (all 47 written, sitemap regenerated, index regenerated)
    1  fatal (db missing, template missing, jinja2 not installed)
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: jinja2 is required. `uv pip install jinja2` or add to pyproject.\n")
    raise

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Reuse generate_program_pages helpers — slugify, JA labels, agency resolution,
# amount lines. This keeps prefecture pages and per-program pages consistent so
# that internal /programs/{slug}.html links resolve correctly.
from _pref_slugs import PREFECTURES, REGIONS, SLUG_TO_JA  # noqa: E402
from generate_program_pages import (  # noqa: E402
    KIND_JA,
    _amount_line,
    _is_public_title_quality_ok,
    _normalize_iso_date,
    _parse_json_list,
    _public_program_name,
    _resolve_agency,
    _target_type_label,
    slugify,
)
from static_bad_urls import load_static_bad_urls  # noqa: E402

LOG = logging.getLogger("generate_prefecture_pages")

DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_TEMPLATE_DIR = REPO_ROOT / "site" / "_templates"
DEFAULT_OUT = REPO_ROOT / "site" / "prefectures"
DEFAULT_SITEMAP = REPO_ROOT / "site" / "sitemap-prefectures.xml"
DEFAULT_DOMAIN = "jpcite.com"

PROGRAMS_PER_PAGE = 20
CASES_PER_PAGE = 10
LOANS_PER_PAGE = 5
ENFORCEMENTS_PER_PAGE = 5

BANNED_AGGREGATORS = "noukaweb / hojyokin-portal / biz.stayway"

OPERATOR_NAME = "Bookyou株式会社"
OPERATOR_CORPORATE_NUMBER = "T8010001213708"
OPERATOR_REP = "梅田茂利"
OPERATOR_EMAIL = "info@bookyou.net"
OPERATOR_ADDRESS_JP = "東京都文京区小日向2-22-1"


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

PROGRAMS_BY_PREF_SQL = """
SELECT
    unified_id,
    primary_name,
    aliases_json,
    authority_level,
    authority_name,
    prefecture,
    municipality,
    program_kind,
    official_url,
    amount_max_man_yen,
    amount_min_man_yen,
    subsidy_rate,
    tier,
    target_types_json,
    funding_purpose_json,
    source_url,
    source_fetched_at,
    updated_at
FROM programs
WHERE excluded = 0
  AND tier IN ('S','A','B','C')
  AND source_url IS NOT NULL
  AND source_url <> ''
  AND COALESCE(source_url_status, '') NOT IN ('broken', 'dead')
  AND COALESCE(source_last_check_status, 0) NOT IN (403, 404, 410)
  AND (authority_name IS NULL OR authority_name NOT LIKE '%noukaweb%')
  AND prefecture = ?
ORDER BY
    CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
    CASE WHEN amount_max_man_yen IS NULL THEN 1 ELSE 0 END,
    amount_max_man_yen DESC,
    unified_id
LIMIT ?
"""

PROGRAMS_COUNT_BY_PREF_SQL = """
SELECT COUNT(*)
FROM programs
WHERE excluded = 0
  AND tier IN ('S','A','B','C')
  AND source_url IS NOT NULL
  AND source_url <> ''
  AND COALESCE(source_url_status, '') NOT IN ('broken', 'dead')
  AND COALESCE(source_last_check_status, 0) NOT IN (403, 404, 410)
  AND (authority_name IS NULL OR authority_name NOT LIKE '%noukaweb%')
  AND prefecture = ?
"""

CASES_BY_PREF_SQL = """
SELECT
    case_id,
    company_name,
    prefecture,
    municipality,
    industry_jsic,
    industry_name,
    case_title,
    case_summary,
    programs_used_json,
    total_subsidy_received_yen,
    publication_date,
    source_url,
    source_excerpt,
    confidence
FROM case_studies
WHERE prefecture = ?
ORDER BY confidence DESC, publication_date DESC, case_id
LIMIT ?
"""

CASES_COUNT_BY_PREF_SQL = "SELECT COUNT(*) FROM case_studies WHERE prefecture = ?"

# MAX(source_fetched_at) across all indexable programs in this prefecture.
# Used as the prefecture page's sitemap <lastmod>: if any underlying program
# was re-fetched today, the aggregate page is "as fresh as that"; otherwise
# the lastmod reflects the oldest viable freshness signal we have.
PREF_MAX_FETCHED_SQL = """
SELECT MAX(source_fetched_at) AS max_fetched
FROM programs
WHERE excluded = 0
  AND tier IN ('S','A','B','C')
  AND source_url IS NOT NULL
  AND source_url <> ''
  AND COALESCE(source_url_status, '') NOT IN ('broken', 'dead')
  AND COALESCE(source_last_check_status, 0) NOT IN (403, 404, 410)
  AND (authority_name IS NULL OR authority_name NOT LIKE '%noukaweb%')
  AND prefecture = ?
"""

# loan_programs has no prefecture column (JFC etc are nationwide).
# We pick the same global top-N for every prefecture; copy contextualises this.
LOANS_TOP_SQL = """
SELECT
    id,
    program_name,
    provider,
    loan_type,
    amount_max_yen,
    loan_period_years_max,
    interest_rate_base_annual,
    target_conditions,
    official_url,
    collateral_required,
    personal_guarantor_required,
    third_party_guarantor_required,
    security_notes,
    confidence
FROM loan_programs
WHERE program_name IS NOT NULL AND program_name <> ''
  AND (provider IS NULL OR provider NOT LIKE '%noukaweb%')
ORDER BY
    CASE WHEN amount_max_yen IS NULL THEN 1 ELSE 0 END,
    amount_max_yen DESC,
    confidence DESC,
    id
LIMIT ?
"""

ENFORCEMENTS_BY_PREF_SQL = """
SELECT
    case_id,
    event_type,
    program_name_hint,
    recipient_name,
    recipient_kind,
    bureau,
    prefecture,
    ministry,
    amount_yen,
    amount_improper_grant_yen,
    reason_excerpt,
    legal_basis,
    source_url,
    source_title,
    disclosed_date,
    disclosed_until,
    confidence
FROM enforcement_cases
WHERE prefecture = ?
  AND (source_url IS NULL OR source_url NOT LIKE '%noukaweb%')
ORDER BY disclosed_date DESC NULLS LAST, confidence DESC, case_id
LIMIT ?
"""

ENFORCEMENTS_COUNT_BY_PREF_SQL = "SELECT COUNT(*) FROM enforcement_cases WHERE prefecture = ?"


# ---------------------------------------------------------------------------
# Row shaping
# ---------------------------------------------------------------------------

EVENT_LABEL = {
    "cancellation": "交付決定取消",
    "revocation": "交付決定取消",
    "return_order": "補助金返還命令",
    "improper_disbursement": "不適正支給",
    "warning": "是正勧告",
    "penalty": "処分",
}


def _shape_program(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    target_types = _parse_json_list(d.get("target_types_json"))
    aliases = _parse_json_list(d.get("aliases_json"))
    raw_name = d.get("primary_name") or ""
    name = _public_program_name(raw_name)
    return {
        "slug": slugify(raw_name, d.get("unified_id") or ""),
        "name": name,
        "aliases": aliases,
        "kind_ja": KIND_JA.get(d.get("program_kind") or "subsidy", "公的支援制度"),
        "tier": d.get("tier") or "C",
        "amount_line": _amount_line(d.get("amount_max_man_yen"), d.get("amount_min_man_yen")),
        "authority": _resolve_agency(d),
        "target_types_ja": [_target_type_label(t) for t in target_types],
    }


def _yen_jp(amount: Any) -> str | None:
    if amount is None:
        return None
    try:
        v = int(amount)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v >= 100_000_000:
        oku = v // 100_000_000
        rem = (v % 100_000_000) // 10_000
        if rem:
            return f"{oku:,}億{rem:,}万円"
        return f"{oku:,}億円"
    if v >= 10_000:
        return f"{v // 10_000:,}万円"
    return f"{v:,}円"


def _truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _row_url_allowed(row: sqlite3.Row, field: str, bad_urls: set[str]) -> bool:
    url = str(dict(row).get(field) or "").strip()
    return not url or url not in bad_urls


def _program_row_publishable(row: sqlite3.Row, bad_urls: set[str]) -> bool:
    if not _row_url_allowed(row, "source_url", bad_urls):
        return False
    return _is_public_title_quality_ok(row["primary_name"])


def _shape_case(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    return {
        "case_id": d.get("case_id"),
        "title": _truncate(d.get("case_title") or d.get("company_name") or "(無題)", 80),
        "industry_name": d.get("industry_name"),
        "subsidy_yen": _yen_jp(d.get("total_subsidy_received_yen")),
        "summary": _truncate(d.get("case_summary") or "", 180),
        "source_url": d.get("source_url"),
    }


_GUARANTOR_LABEL = {
    "required": "必須",
    "optional": "任意 / 状況による",
    "not_required": "不要",
    "case_by_case": "要相談",
    "y": "必須",
    "n": "不要",
}


def _g_label(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    return _GUARANTOR_LABEL.get(s, str(raw))


def _shape_loan(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    amount_yen = d.get("amount_max_yen")
    amount_line = _yen_jp(amount_yen) if amount_yen else None
    return {
        "id": d.get("id"),
        "name": d.get("program_name") or "",
        "provider": d.get("provider") or "金融機関",
        "amount_line": amount_line,
        "collateral_label": _g_label(d.get("collateral_required")),
        "personal_guarantor_label": _g_label(d.get("personal_guarantor_required")),
        "third_party_guarantor_label": _g_label(d.get("third_party_guarantor_required")),
        "official_url": d.get("official_url"),
    }


def _shape_enforcement(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    event_type = (d.get("event_type") or "").strip().lower()
    label = EVENT_LABEL.get(event_type) or d.get("program_name_hint") or "公示"
    amount_yen = d.get("amount_improper_grant_yen") or d.get("amount_yen")
    amount_line = _yen_jp(amount_yen) if amount_yen else None
    return {
        "case_id": d.get("case_id"),
        "event_label": label,
        "recipient": d.get("recipient_name"),
        "bureau": d.get("bureau") or d.get("ministry"),
        "amount_line": amount_line,
        "disclosed_date": _normalize_iso_date(d.get("disclosed_date")),
        "source_url": d.get("source_url"),
        "reason": _truncate(d.get("reason_excerpt") or "", 160),
    }


# ---------------------------------------------------------------------------
# Per-prefecture summary text
# ---------------------------------------------------------------------------


def _overview_paragraph(
    pref_ja: str, programs_count: int, cases_count: int, loans_count: int, enforcements_count: int
) -> str:
    return (
        f"{pref_ja}では、中央省庁 (中小企業庁・農林水産省・経済産業省・厚生労働省) "
        f"および{pref_ja}庁・市区町村が運営する公的支援制度に加え、日本政策金融公庫等の政策金融融資、"
        f"国税庁の税制優遇措置、各種認定制度が事業者向けに提供されています。jpcite では、"
        f"{pref_ja}に関連する補助金・助成金 {programs_count} 件、{pref_ja}所在事業者の採択事例 {cases_count} 件、"
        f"全国対応の政策金融融資 {loans_count} 件、{pref_ja}関連の行政処分公示 {enforcements_count} 件を、"
        "公式出典を確認できる形で集約しています。制度名・金額・地域・出典URLを同時に確認できるため、"
        "AIや担当者が長い公募ページを読む前の候補整理に使えます。"
    )


def _meta_description(pref_ja: str, programs_count: int, cases_count: int) -> str:
    base = (
        f"{pref_ja}の補助金・助成金 {programs_count} 件、採択事例 {cases_count} 件、"
        "政策金融融資、行政処分公示を出典リンク付きで集約。jpcite API/MCP で取得可能。"
    )
    return _truncate(base, 160)


def _page_title(pref_ja: str, programs_count: int) -> str:
    # Japanese characters render ≈2x SERP width vs ASCII, so the previous
    # 70-char cap (which counts Python chars) produced ~92-93 SERP-width titles
    # that Google truncated mid-word at "…行政処". Drop the "…一覧" suffix and
    # cap at 50 chars so the title fits the JA SERP width budget cleanly.
    base = f"{pref_ja} 補助金{programs_count}件・融資・税制 | jpcite"
    return _truncate(base, 50)


# ---------------------------------------------------------------------------
# JSON-LD
# ---------------------------------------------------------------------------


def _org_node(domain: str) -> dict[str, Any]:
    # Canonical Organization @id, unified across all template generators.
    return {
        "@type": "Organization",
        "@id": "https://jpcite.com/#publisher",
        "name": "jpcite",
        "url": f"https://{domain}/",
        "logo": {
            "@type": "ImageObject",
            "url": f"https://{domain}/assets/logo.png",
            "width": 600,
            "height": 60,
        },
        # TODO populate when LinkedIn / GitHub / X / Crunchbase live.
        "sameAs": [],
    }


def _breadcrumb_node(pref_ja: str, slug: str, domain: str) -> dict[str, Any]:
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": f"https://{domain}/"},
            {
                "@type": "ListItem",
                "position": 2,
                "name": "都道府県別",
                "item": f"https://{domain}/prefectures/",
            },
            {
                "@type": "ListItem",
                "position": 3,
                "name": pref_ja,
                "item": f"https://{domain}/prefectures/{slug}",
            },
        ],
    }


def _place_node(pref_ja: str, domain: str, slug: str) -> dict[str, Any]:
    return {
        "@type": "Place",
        "@id": f"#place-{slug}",
        "name": pref_ja,
        "url": f"https://{domain}/prefectures/{slug}",
        "containedInPlace": {"@type": "Country", "name": "日本"},
        "additionalType": "AdministrativeArea",
    }


def _itemlist_node(
    pref_ja: str, programs: list[dict[str, Any]], domain: str, slug: str
) -> dict[str, Any]:
    return {
        "@type": "ItemList",
        "@id": f"#itemlist-{slug}",
        "name": f"{pref_ja}の公的支援制度一覧",
        "numberOfItems": len(programs),
        "itemListOrder": "https://schema.org/ItemListOrderDescending",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "url": f"https://{domain}/programs/{p['slug']}.html",
                "name": p["name"],
            }
            for i, p in enumerate(programs)
        ],
    }


def _build_prefecture_jsonld(
    pref_ja: str,
    slug: str,
    domain: str,
    programs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@graph": [
            _org_node(domain),
            _breadcrumb_node(pref_ja, slug, domain),
            _place_node(pref_ja, domain, slug),
            _itemlist_node(pref_ja, programs, domain, slug),
        ],
    }


def _build_index_jsonld(domain: str, region_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    pos = 1
    for region in region_summaries:
        for pref in region["items"]:
            items.append(
                {
                    "@type": "ListItem",
                    "position": pos,
                    "url": f"https://{domain}/prefectures/{pref['slug']}",
                    "name": pref["name_ja"],
                }
            )
            pos += 1
    return {
        "@context": "https://schema.org",
        "@graph": [
            _org_node(domain),
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": 1,
                        "name": "ホーム",
                        "item": f"https://{domain}/",
                    },
                    {
                        "@type": "ListItem",
                        "position": 2,
                        "name": "都道府県別",
                        "item": f"https://{domain}/prefectures/",
                    },
                ],
            },
            {
                "@type": "ItemList",
                "@id": "#prefecture-index",
                "name": "47 都道府県別 公的支援制度インデックス",
                "numberOfItems": len(items),
                "itemListElement": items,
            },
        ],
    }


# ---------------------------------------------------------------------------
# Render + write
# ---------------------------------------------------------------------------


def _build_env(template_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(enabled_extensions=("html", "xml"), default=True),
        trim_blocks=False,
        lstrip_blocks=False,
    )


def _today_iso() -> str:
    return datetime.now(tz=UTC).date().isoformat()


def _today_ja() -> str:
    today = date.today()
    return f"{today.year}年{today.month}月{today.day}日"


def _write_if_changed(path: Path, content: str) -> bool:
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = None
        if existing == content:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def render_prefecture_page(
    env: Environment,
    conn: sqlite3.Connection,
    slug: str,
    pref_ja: str,
    domain: str,
    bad_urls: set[str],
    loans_cache: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, int]]:
    """Render a single prefecture page. Returns (html, counts dict)."""

    program_rows = [
        r
        for r in conn.execute(PROGRAMS_BY_PREF_SQL, (pref_ja, PROGRAMS_PER_PAGE * 8))
        if _program_row_publishable(r, bad_urls)
    ][:PROGRAMS_PER_PAGE]
    programs = [_shape_program(r) for r in program_rows]
    programs_total = sum(
        1
        for r in conn.execute(PROGRAMS_BY_PREF_SQL, (pref_ja, 10_000))
        if _program_row_publishable(r, bad_urls)
    )

    case_rows = [
        r
        for r in conn.execute(CASES_BY_PREF_SQL, (pref_ja, CASES_PER_PAGE * 4))
        if _row_url_allowed(r, "source_url", bad_urls)
    ][:CASES_PER_PAGE]
    case_studies = [_shape_case(r) for r in case_rows]
    cases_total = conn.execute(CASES_COUNT_BY_PREF_SQL, (pref_ja,)).fetchone()[0]

    if loans_cache is None:
        loan_rows = [
            r
            for r in conn.execute(LOANS_TOP_SQL, (LOANS_PER_PAGE * 4,))
            if _row_url_allowed(r, "official_url", bad_urls)
        ][:LOANS_PER_PAGE]
        loans = [_shape_loan(r) for r in loan_rows]
    else:
        loans = loans_cache

    enforcement_rows = [
        r
        for r in conn.execute(ENFORCEMENTS_BY_PREF_SQL, (pref_ja, ENFORCEMENTS_PER_PAGE * 4))
        if _row_url_allowed(r, "source_url", bad_urls)
    ][:ENFORCEMENTS_PER_PAGE]
    enforcements = [_shape_enforcement(r) for r in enforcement_rows]
    enforcements_total = conn.execute(ENFORCEMENTS_COUNT_BY_PREF_SQL, (pref_ja,)).fetchone()[0]

    json_ld = _build_prefecture_jsonld(pref_ja, slug, domain, programs)

    overview = _overview_paragraph(
        pref_ja, programs_total, cases_total, len(loans), enforcements_total
    )
    page_title = _page_title(pref_ja, programs_total)
    meta_description = _meta_description(pref_ja, programs_total, cases_total)

    template = env.get_template("prefecture.html")
    html = template.render(
        DOMAIN=domain,
        slug=slug,
        pref_ja=pref_ja,
        page_title=page_title,
        meta_description=meta_description,
        programs=programs,
        programs_count=len(programs),
        programs_total=programs_total,
        case_studies=case_studies,
        cases_count=len(case_studies),
        cases_total=cases_total,
        loans=loans,
        loans_count=len(loans),
        enforcements=enforcements,
        enforcements_count=len(enforcements),
        enforcements_total=enforcements_total,
        overview_paragraph=overview,
        generated_ja=_today_ja(),
        banned_aggregators=BANNED_AGGREGATORS,
        json_ld_pretty=json.dumps(json_ld, ensure_ascii=False, indent=2).replace("</", "<\\/"),
    )
    counts = {
        "programs": len(programs),
        "programs_total": programs_total,
        "cases": len(case_studies),
        "cases_total": cases_total,
        "loans": len(loans),
        "enforcements": len(enforcements),
        "enforcements_total": enforcements_total,
    }
    return html, counts


def render_index(
    env: Environment,
    domain: str,
    pref_summaries: list[dict[str, Any]],
) -> str:
    region_summaries: list[dict[str, Any]] = []
    by_slug = {p["slug"]: p for p in pref_summaries}
    for region_name, slugs in REGIONS:
        items = [by_slug[s] for s in slugs if s in by_slug]
        region_summaries.append({"name": region_name, "items": items})

    json_ld = _build_index_jsonld(domain, region_summaries)
    template = env.get_template("prefecture_index.html")
    return template.render(
        DOMAIN=domain,
        generated_ja=_today_ja(),
        regions=[(r["name"], r["items"]) for r in region_summaries],
        json_ld_pretty=json.dumps(json_ld, ensure_ascii=False, indent=2).replace("</", "<\\/"),
    )


# ---------------------------------------------------------------------------
# Sitemap (separate file — does NOT touch sitemap.xml or sitemap-programs.xml)
# ---------------------------------------------------------------------------


def write_sitemap(
    domain: str,
    slugs: list[str],
    path: Path,
    pref_lastmods: dict[str, str] | None = None,
) -> None:
    """Emit sitemap-prefectures.xml.

    `pref_lastmods` maps slug → ISO date (YYYY-MM-DD) derived from
    MAX(source_fetched_at) over the prefecture's indexable programs. This is
    the SEO-honest signal: when the underlying data backing this page was
    last re-fetched. Falls back to today's date when missing (e.g. a
    prefecture has zero indexable programs — rare but possible mid-ingest).

    The /prefectures/ index lastmod = max across all per-pref lastmods so the
    index reflects the freshest underlying signal, never going backwards just
    because we re-ran the generator.
    """
    today = _today_iso()
    pref_lastmods = pref_lastmods or {}
    per_slug_lastmod = {slug: pref_lastmods.get(slug) or today for slug in slugs}
    index_lastmod = max(per_slug_lastmod.values(), default=today)
    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!--",
        "  Auto-generated by scripts/generate_prefecture_pages.py",
        "  Independent fragment — does not overlap sitemap.xml or sitemap-programs.xml.",
        "  47 prefecture pages + 1 index = 48 URLs.",
        "  <lastmod> = MAX(source_fetched_at) across the prefecture's indexable",
        "  programs (when we last pulled the underlying primary source).",
        "-->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        "  <url>",
        f"    <loc>https://{domain}/prefectures/</loc>",
        f"    <lastmod>{index_lastmod}</lastmod>",
        "    <changefreq>weekly</changefreq>",
        "    <priority>0.8</priority>",
        "  </url>",
    ]
    for slug in slugs:
        slug_lastmod = per_slug_lastmod[slug]
        lines.extend(
            [
                "  <url>",
                f"    <loc>https://{domain}/prefectures/{slug}</loc>",
                f"    <lastmod>{slug_lastmod}</lastmod>",
                "    <changefreq>weekly</changefreq>",
                "    <priority>0.7</priority>",
                "  </url>",
            ]
        )
    lines.append("</urlset>")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--template-dir", type=Path, default=DEFAULT_TEMPLATE_DIR)
    parser.add_argument("--domain", default=DEFAULT_DOMAIN)
    parser.add_argument("--sitemap", type=Path, default=DEFAULT_SITEMAP)
    parser.add_argument(
        "--slug",
        default=None,
        help="Generate only this prefecture slug (e.g. tokyo). Implies sample mode.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render but do not write files. Print line counts to stdout.",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if not args.db.exists():
        LOG.error("DB not found: %s", args.db)
        return 1
    if not (args.template_dir / "prefecture.html").exists():
        LOG.error("Template missing: %s/prefecture.html", args.template_dir)
        return 1

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    env = _build_env(args.template_dir)
    bad_urls = load_static_bad_urls()
    if bad_urls:
        LOG.info("Loaded %d static bad-url denylist entries", len(bad_urls))

    # Cache loans once — same for every prefecture (loan_programs is national).
    loan_rows = [
        r
        for r in conn.execute(LOANS_TOP_SQL, (LOANS_PER_PAGE * 4,))
        if _row_url_allowed(r, "official_url", bad_urls)
    ][:LOANS_PER_PAGE]
    loans_cache = [_shape_loan(r) for r in loan_rows]
    LOG.info("Loaded %d national loan programs (shared across all prefectures)", len(loans_cache))

    targets: list[tuple[str, str]]
    if args.slug:
        if args.slug not in SLUG_TO_JA:
            LOG.error(
                "Unknown slug: %s. Valid: %s",
                args.slug,
                ",".join(s for s, _ in PREFECTURES[:5]) + ",...",
            )
            return 1
        targets = [(args.slug, SLUG_TO_JA[args.slug])]
    else:
        targets = list(PREFECTURES)

    pref_summaries: list[dict[str, Any]] = []
    pref_lastmods: dict[str, str] = {}
    written = 0
    skipped = 0
    line_counts: list[int] = []

    for slug, pref_ja in targets:
        html, counts = render_prefecture_page(
            env,
            conn,
            slug,
            pref_ja,
            args.domain,
            bad_urls,
            loans_cache=loans_cache,
        )
        line_counts.append(html.count("\n") + 1)

        # Per-prefecture sitemap <lastmod> = MAX(source_fetched_at) over its
        # indexable programs. SEO-honest signal: matches when we last touched
        # the upstream primary source for that prefecture's data.
        max_fetched_row = conn.execute(PREF_MAX_FETCHED_SQL, (pref_ja,)).fetchone()
        max_fetched_iso = _normalize_iso_date(max_fetched_row[0] if max_fetched_row else None)
        if max_fetched_iso:
            pref_lastmods[slug] = max_fetched_iso

        pref_summaries.append(
            {
                "slug": slug,
                "name_ja": pref_ja,
                "programs_count": counts["programs_total"],
                "cases_count": counts["cases_total"],
                "enforcements_count": counts["enforcements_total"],
            }
        )

        out_path = args.out / f"{slug}.html"
        if args.dry_run:
            LOG.info(
                "[dry-run] %s (%s) — %d lines, %d programs, %d cases, %d loans, %d enforcements",
                slug,
                pref_ja,
                line_counts[-1],
                counts["programs"],
                counts["cases"],
                counts["loans"],
                counts["enforcements"],
            )
        else:
            changed = _write_if_changed(out_path, html)
            if changed:
                written += 1
            else:
                skipped += 1
            LOG.info(
                "%s %s (%s) — %d programs, %d cases, %d loans, %d enforcements (total: P=%d C=%d E=%d)",
                "WROTE" if changed else "skip",
                slug,
                pref_ja,
                counts["programs"],
                counts["cases"],
                counts["loans"],
                counts["enforcements"],
                counts["programs_total"],
                counts["cases_total"],
                counts["enforcements_total"],
            )

    if args.slug:
        # Single-slug mode: skip index + sitemap regeneration.
        avg_lines = sum(line_counts) // len(line_counts) if line_counts else 0
        LOG.info("Single slug done. avg_lines=%d", avg_lines)
        return 0

    # Render index using actual counts from this run.
    index_html = render_index(env, args.domain, pref_summaries)
    index_path = args.out / "index.html"
    if args.dry_run:
        LOG.info("[dry-run] index.html — %d lines", index_html.count("\n") + 1)
    else:
        if _write_if_changed(index_path, index_html):
            written += 1
        else:
            skipped += 1

    # Sitemap (47 + 1 = 48 URLs).
    if not args.dry_run:
        write_sitemap(
            args.domain,
            [slug for slug, _ in PREFECTURES],
            args.sitemap,
            pref_lastmods=pref_lastmods,
        )
        LOG.info("Wrote sitemap: %s", args.sitemap)

    avg_lines = sum(line_counts) // len(line_counts) if line_counts else 0
    LOG.info(
        "Done. wrote=%d skipped=%d avg_lines=%d (over %d prefectures)",
        written,
        skipped,
        avg_lines,
        len(line_counts),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
