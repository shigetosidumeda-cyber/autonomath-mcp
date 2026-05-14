#!/usr/bin/env python3
"""Generate 20 政令指定都市 (designated city) hub pages for jpcite.com.

Targets long-tail organic queries like:
    "<市名> 補助金"
    "<市名> 補助金 一覧"
    "<市名> 中小企業 補助金"
    "<市名> 創業 助成金"

Per W2-11 research (analysis_wave18/research_W2_11_pref_seo_ranking_2026-05-04.md),
政令市 hub pages were 0/20 — every "横浜市 補助金 一覧" query was lost to
hojyokin-portal / smart-hojokin / city 公式. This generator closes that gap.

Input:
    data/jpintel.db (SQLite). Tables used: programs.

Output:
    site/cities/{city_slug}/index.html  (20 pages, slug = sapporo / yokohama /
                                         nagoya / kyoto-city / chiba-city / ...)
    site/cities/index.html               (20-link landing index, region grouped)
    site/sitemap-cities.xml              (20 + 1 = 21 URL sitemap fragment)

Per-city content:
    - top 20 programs filtered by municipality LIKE '%<city>%' (or fallback to
      primary_name LIKE '%<city>%' when municipality is null but the program
      title clearly carries the city name). source_url is required, aggregator
      hosts banned, tier ∈ S/A/B/C, dead URLs excluded.
    - link to upper hub (該当県 prefecture page) and to /programs/{slug}.html
      for each listed program (lower hub).

Design references:
    - scripts/generate_prefecture_pages.py (sister generator, 47 pref hubs)
    - scripts/generate_cross_hub_pages.py (sister generator, 47 cross hubs —
      this script follows the same self-contained {slug}/index.html layout)
    - analysis_wave18/research_W2_11_pref_seo_ranking_2026-05-04.md (gap)
    - CLAUDE.md (banned aggregators, source_url honesty)

Rules followed (CLAUDE.md):
    - NO LLM API import (pure SQLite + Python)
    - aggregator URLs (noukaweb / hojyokin-portal / smart-hojokin / biz.stayway
      / prtimes / wikipedia) banned from source_url
    - source_url honesty: do NOT silently rewrite or backfill
    - tier='X' quarantine excluded
    - canonical = /cities/{slug}/ (slash-terminated, matches Pages routing —
      avoids the .html canonical/redirect mismatch that hurt the pref hubs)

Usage:
    .venv/bin/python scripts/generate_city_pages.py
    .venv/bin/python scripts/generate_city_pages.py --slug yokohama --dry-run
    .venv/bin/python scripts/generate_city_pages.py --domain example.com

Exit codes:
    0  success
    1  fatal (db missing)
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Reuse the same hepburn slug derivation as program pages so internal
# /programs/{slug}.html links resolve to the actual generated artifacts.
try:
    from jpintel_mcp.utils.slug import program_static_slug
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: jpintel_mcp.utils.slug not importable — pip install -e . first.\n")
    raise

LOG = logging.getLogger("generate_city_pages")

DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_OUT = REPO_ROOT / "site" / "cities"
DEFAULT_SITEMAP = REPO_ROOT / "site" / "sitemap-cities.xml"
DEFAULT_DOMAIN = "jpcite.com"

PROGRAMS_PER_PAGE = 20

_JST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# 20 政令指定都市 — slug + JA name + parent prefecture (slug + JA)
# ---------------------------------------------------------------------------
#
# Slug rule:
#   - city slugs that don't collide with a 47-pref slug use the bare romaji
#     (sapporo, yokohama, nagoya, kobe, sakai, kawasaki, sagamihara, hamamatsu,
#     kitakyushu).
#   - city slugs that WOULD collide with a pref slug are suffixed with
#     "-city" (chiba-city, niigata-city, shizuoka-city, kyoto-city, osaka-city,
#     okayama-city, hiroshima-city, fukuoka-city, kumamoto-city).
#   - sendai / saitama do not collide with a pref slug (saitama is a pref slug
#     too — collision! → use saitama-city). sendai → just sendai (no clash).
#
# Each tuple: (city_slug, city_ja, pref_slug, pref_ja, region_ja).
CITIES: list[tuple[str, str, str, str, str]] = [
    ("sapporo", "札幌市", "hokkaido", "北海道", "北海道・東北"),
    ("sendai", "仙台市", "miyagi", "宮城県", "北海道・東北"),
    ("saitama-city", "さいたま市", "saitama", "埼玉県", "関東"),
    ("chiba-city", "千葉市", "chiba", "千葉県", "関東"),
    ("yokohama", "横浜市", "kanagawa", "神奈川県", "関東"),
    ("kawasaki", "川崎市", "kanagawa", "神奈川県", "関東"),
    ("sagamihara", "相模原市", "kanagawa", "神奈川県", "関東"),
    ("niigata-city", "新潟市", "niigata", "新潟県", "中部"),
    ("shizuoka-city", "静岡市", "shizuoka", "静岡県", "中部"),
    ("hamamatsu", "浜松市", "shizuoka", "静岡県", "中部"),
    ("nagoya", "名古屋市", "aichi", "愛知県", "中部"),
    ("kyoto-city", "京都市", "kyoto", "京都府", "近畿"),
    ("osaka-city", "大阪市", "osaka", "大阪府", "近畿"),
    ("sakai", "堺市", "osaka", "大阪府", "近畿"),
    ("kobe", "神戸市", "hyogo", "兵庫県", "近畿"),
    ("okayama-city", "岡山市", "okayama", "岡山県", "中国"),
    ("hiroshima-city", "広島市", "hiroshima", "広島県", "中国"),
    ("kitakyushu", "北九州市", "fukuoka", "福岡県", "九州・沖縄"),
    ("fukuoka-city", "福岡市", "fukuoka", "福岡県", "九州・沖縄"),
    ("kumamoto-city", "熊本市", "kumamoto", "熊本県", "九州・沖縄"),
]

assert len(CITIES) == 20, "CITIES must have exactly 20 entries (政令指定都市)"
assert len({c[0] for c in CITIES}) == 20, "city slugs must be unique"


# ---------------------------------------------------------------------------
# Public-name cleanup helpers (mirrors generate_program_pages /
# generate_prefecture_pages so internal artifacts present consistently).
# ---------------------------------------------------------------------------

_PUBLIC_ID_PREFIX_RE = re.compile(r"^(?:MUN-\d{2,6}-\d{3}|PREF-\d{2,6}-\d{3})[_\s]+")


def _public_program_name(name: str | None) -> str:
    return _PUBLIC_ID_PREFIX_RE.sub("", (name or "").strip())


KIND_JA = {
    "subsidy": "補助金・交付金",
    "grant": "助成金・給付金",
    "loan": "融資 (政策金融)",
    "tax_credit": "税制優遇",
    "incentive": "奨励・インセンティブ制度",
    "certification": "認定制度",
    "training": "研修・人材育成",
}


def _amount_line(max_man: float | None, min_man: float | None) -> str:
    if max_man is None and min_man is None:
        return "金額非公表"
    if max_man is not None and min_man is not None and min_man > 0:
        return f"{int(min_man):,}万円 〜 {int(max_man):,}万円"
    if max_man is not None:
        return f"最大 {int(max_man):,}万円"
    if min_man is not None:
        return f"{int(min_man):,}万円〜"
    return "金額非公表"


def _today_jst_iso() -> str:
    return datetime.now(_JST).date().isoformat()


# ---------------------------------------------------------------------------
# DB query
# ---------------------------------------------------------------------------
#
# We match by:
#   1. municipality LIKE '%<city_ja>%'  (preferred, structured field)
#   2. OR primary_name LIKE '%<city_ja>%' (some city programs have null
#      municipality but the title carries the city name explicitly).
#
# We also filter by parent prefecture so e.g. "京都市" doesn't accidentally
# match a "東京都" program whose name happens to contain "都" (defensive — the
# LIKE patterns are already 京都市 with the 市 suffix, but the prefecture
# filter pins the universe to programs we'd actually want listed for that city).
#
# Aggregator hosts banned (CLAUDE.md), dead URLs excluded, tier ∈ S/A/B/C.

_BANNED_SOURCE_SQL = """
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//smart-hojokin.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.smart-hojokin.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//noukaweb.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.noukaweb.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//hojyokin-portal.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.hojyokin-portal.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//biz.stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.biz.stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//prtimes.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.prtimes.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//wikipedia.org%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.wikipedia.org%'
"""

_PROGRAMS_BY_CITY_SQL_TEMPLATE = """
SELECT
    unified_id,
    primary_name,
    authority_name,
    prefecture,
    municipality,
    program_kind,
    amount_max_man_yen,
    amount_min_man_yen,
    tier,
    source_url
FROM programs
WHERE excluded = 0
  AND tier IN ('S','A','B','C')
  AND source_url IS NOT NULL
  AND source_url <> ''
  AND COALESCE(source_url_status, '') NOT IN ('broken', 'dead')
  AND COALESCE(source_last_check_status, 0) NOT IN (403, 404, 410)
  AND (authority_name IS NULL OR authority_name NOT LIKE '%noukaweb%')
  {banned_source_sql}
  AND prefecture = ?
  AND (municipality LIKE ? OR primary_name LIKE ?)
ORDER BY
    CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
    CASE WHEN amount_max_man_yen IS NULL THEN 1 ELSE 0 END,
    amount_max_man_yen DESC,
    unified_id
LIMIT ?
"""

_PROGRAMS_COUNT_BY_CITY_SQL_TEMPLATE = """
SELECT COUNT(*)
FROM programs
WHERE excluded = 0
  AND tier IN ('S','A','B','C')
  AND source_url IS NOT NULL
  AND source_url <> ''
  AND COALESCE(source_url_status, '') NOT IN ('broken', 'dead')
  AND COALESCE(source_last_check_status, 0) NOT IN (403, 404, 410)
  AND (authority_name IS NULL OR authority_name NOT LIKE '%noukaweb%')
  {banned_source_sql}
  AND prefecture = ?
  AND (municipality LIKE ? OR primary_name LIKE ?)
"""

PROGRAMS_BY_CITY_SQL = _PROGRAMS_BY_CITY_SQL_TEMPLATE.format(banned_source_sql=_BANNED_SOURCE_SQL)
PROGRAMS_COUNT_BY_CITY_SQL = _PROGRAMS_COUNT_BY_CITY_SQL_TEMPLATE.format(
    banned_source_sql=_BANNED_SOURCE_SQL
)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _shape_program(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    raw_name = d.get("primary_name") or ""
    return {
        "slug": program_static_slug(raw_name, d.get("unified_id") or ""),
        "name": _public_program_name(raw_name),
        "kind_ja": KIND_JA.get(d.get("program_kind") or "subsidy", "公的支援制度"),
        "tier": (d.get("tier") or "C").upper(),
        "amount_line": _amount_line(d.get("amount_max_man_yen"), d.get("amount_min_man_yen")),
        "authority": d.get("authority_name") or "",
        "source_url": d.get("source_url") or "",
        "municipality": d.get("municipality") or "",
    }


def _meta_description(city_ja: str, pref_ja: str, count: int) -> str:
    base = (
        f"{city_ja}の補助金・助成金 {count}件を出典リンク付きで集約。"
        f"中小企業・創業・ものづくり・IT導入に対応。{pref_ja}全体および国制度との"
        f"組み合わせも jpcite から確認できます。"
    )
    return base if len(base) <= 160 else base[:159] + "…"


def _page_title(city_ja: str, count: int) -> str:
    # Keep under 50 JA chars (Google SERP cap ~32 JA chars displayed).
    return f"{city_ja} の補助金 一覧 2026 | jpcite"


def _h1(city_ja: str, count: int) -> str:
    return f"{city_ja} の補助金 一覧 2026 — 中小企業・創業・ものづくり 主要 {count} 件"


def _build_jsonld(
    city_ja: str,
    city_slug: str,
    pref_ja: str,
    pref_slug: str,
    domain: str,
    programs: list[dict[str, Any]],
) -> dict[str, Any]:
    canonical = f"https://{domain}/cities/{city_slug}/"
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": f"https://{domain}/#publisher",
                "name": "jpcite",
                "url": f"https://{domain}/",
            },
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
                        "name": "政令指定都市別",
                        "item": f"https://{domain}/cities/",
                    },
                    {
                        "@type": "ListItem",
                        "position": 3,
                        "name": pref_ja,
                        "item": f"https://{domain}/prefectures/{pref_slug}.html",
                    },
                    {"@type": "ListItem", "position": 4, "name": city_ja, "item": canonical},
                ],
            },
            {
                "@type": "Place",
                "@id": f"#place-{city_slug}",
                "name": city_ja,
                "url": canonical,
                "containedInPlace": {"@type": "AdministrativeArea", "name": pref_ja},
                "additionalType": "City",
            },
            {
                "@type": "ItemList",
                "@id": f"#itemlist-{city_slug}",
                "name": f"{city_ja}の補助金・助成金 上位{len(programs)}件",
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
            },
        ],
    }


def _render_city_page(
    city_slug: str,
    city_ja: str,
    pref_slug: str,
    pref_ja: str,
    region_ja: str,
    programs: list[dict[str, Any]],
    programs_total: int,
    domain: str,
) -> str:
    canonical = f"https://{domain}/cities/{city_slug}/"
    today = _today_jst_iso()
    title = _page_title(city_ja, programs_total)
    desc = _meta_description(city_ja, pref_ja, programs_total)
    h1 = _h1(city_ja, programs_total)

    json_ld = _build_jsonld(city_ja, city_slug, pref_ja, pref_slug, domain, programs)
    json_ld_str = json.dumps(json_ld, ensure_ascii=False, indent=2).replace("</", "<\\/")

    if programs:
        program_lis = []
        for p in programs:
            program_lis.append(
                '      <li class="city-program">\n'
                f'        <a class="city-program-name" href="/programs/{p["slug"]}.html">'
                f"<strong>{html.escape(p['name'])}</strong></a>\n"
                f'        <span class="city-program-meta">tier {html.escape(p["tier"])} ・ '
                f"{html.escape(p['kind_ja'])} ・ {html.escape(p['amount_line'])}</span>\n"
                + (
                    f'        <span class="city-program-authority muted">提供: '
                    f"{html.escape(p['authority'])}</span>\n"
                    if p["authority"]
                    else ""
                )
                + (
                    f'        <a class="city-program-source" href="{html.escape(p["source_url"])}" '
                    'rel="external nofollow noopener">出典ページ</a>\n'
                    if p["source_url"]
                    else ""
                )
                + "      </li>"
            )
        list_html = "\n".join(program_lis)
        list_section = (
            f'  <section class="city-section" aria-labelledby="programs-title">\n'
            f'    <h2 id="programs-title">{html.escape(city_ja)}の補助金・助成金 '
            f"({len(programs)}件 / 全 {programs_total} 件)</h2>\n"
            f"    <p>{html.escape(city_ja)}が運営または{html.escape(city_ja)}事業者向けに"
            f"提供されている補助金・助成金・交付金のうち、jpcite が出典確認状況と金額情報を"
            f"もとに抽出した上位 {len(programs)} 件です。各制度名は jpcite の制度詳細ページに、"
            f"出典は{html.escape(city_ja)}・{html.escape(pref_ja)}・各省庁などの一次資料に"
            f"直接リンクしています。</p>\n"
            f'    <ol class="city-list">\n{list_html}\n    </ol>\n'
            f"  </section>"
        )
    else:
        list_section = (
            f'  <section class="city-section" aria-labelledby="programs-title">\n'
            f'    <h2 id="programs-title">{html.escape(city_ja)}の補助金・助成金 '
            f"(0件)</h2>\n"
            f"    <p>{html.escape(city_ja)}に紐づく一次資料確認済みの補助金は現在 0 件です。"
            f"{html.escape(pref_ja)} 全体の制度一覧は "
            f'<a href="/prefectures/{pref_slug}.html">{html.escape(pref_ja)} 補助金 一覧</a> '
            f"からご確認ください。</p>\n"
            f"  </section>"
        )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#ffffff">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<meta name="author" content="jpcite">
<meta name="publisher" content="jpcite">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="https://{domain}/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="ja_JP">
<meta property="og:site_name" content="jpcite">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{html.escape(title)}">
<meta name="twitter:description" content="{html.escape(desc)}">
<meta name="twitter:image" content="https://{domain}/assets/og-twitter.png">
<link rel="canonical" href="{canonical}">
<link rel="alternate" hreflang="ja" href="{canonical}">
<link rel="alternate" hreflang="x-default" href="{canonical}">
<link rel="icon" href="/assets/favicon-v2.svg" type="image/svg+xml">
<link rel="stylesheet" href="/styles.css?v=20260428a">
<script type="application/ld+json">
{json_ld_str}
</script>
</head>
<body>
<a href="#main" class="skip-link">本文へスキップ</a>
<header class="site-header" role="banner">
  <div class="container header-inner">
    <a class="brand" href="/" aria-label="jpcite ホーム">
 <picture><source media="(prefers-color-scheme: dark)" srcset="/assets/brand/lockup-transparent-600-lightlogo.png 1x, /assets/brand/lockup-transparent-1200-lightlogo.png 2x"><img src="/assets/brand/lockup-transparent-600-darklogo.png" srcset="/assets/brand/lockup-transparent-600-darklogo.png 1x, /assets/brand/lockup-transparent-1200-darklogo.png 2x" width="190" decoding="async" fetchpriority="high" alt="jpcite" height="32" style="height:32px;width:auto;display:block;"></picture>
 </a>
    <nav class="site-nav" aria-label="主要ナビゲーション">
      <a href="/about.html">運営について</a>
      <a href="/products.html">プロダクト</a>
      <a href="/docs/">ドキュメント</a>
      <a href="/pricing.html">料金</a>
      <a href="/prefectures/">都道府県別</a>
    </nav>
  </div>
</header>
<main id="main" class="container city-page">
  <nav class="breadcrumb" aria-label="パンくずリスト">
    <a href="/">ホーム</a>
    <span aria-hidden="true">›</span>
    <a href="/cities/">政令指定都市別</a>
    <span aria-hidden="true">›</span>
    <a href="/prefectures/{pref_slug}.html">{html.escape(pref_ja)}</a>
    <span aria-hidden="true">›</span>
    <span aria-current="page">{html.escape(city_ja)}</span>
  </nav>
  <article>
  <header class="city-header">
    <h1>{html.escape(h1)}</h1>
    <p class="byline">
      <span class="updated">出典取得: {today}</span>
      <span class="sep">/</span>
      <span class="region muted">{html.escape(region_ja)} ・ {html.escape(pref_ja)}</span>
      <span class="sep">/</span>
      <span class="author">jpcite</span>
    </p>
    <p class="byline-note muted">
      {html.escape(city_ja)}が所管する補助金・助成金、または{html.escape(city_ja)}所在事業者を
      対象とする {html.escape(pref_ja)}・各省庁の制度を、jpcite が一次資料 URL と金額情報をもとに
      集約しています。最終的な対象判定・金額・申請期間は必ず一次資料 URL でご確認ください。
    </p>
  </header>

  <section class="city-tldr" aria-labelledby="tldr-title">
    <h2 id="tldr-title">{html.escape(city_ja)} で確認できる支援制度を一望する</h2>
    <p>{html.escape(city_ja)}は{html.escape(pref_ja)}の政令指定都市であり、市が直接運営する
    中小企業・創業・ものづくり・IT導入支援の補助金に加え、{html.escape(pref_ja)}・国の制度の
    多くが{html.escape(city_ja)}事業者にも適用されます。jpcite ではそれら一次資料の所在を
    制度名・金額・対象・出典 URL とあわせて整理しています。</p>
    <ul>
      <li><strong>市の補助金:</strong> 上位 {len(programs)} 件 (全 {programs_total} 件) を本ページに掲載。</li>
      <li><strong>県の制度:</strong> <a href="/prefectures/{pref_slug}.html">{html.escape(pref_ja)} 補助金 一覧</a> からご確認いただけます。</li>
      <li><strong>全国制度:</strong> <a href="/cross/{pref_slug}/">{html.escape(pref_ja)} から申請できる 全国 補助金</a> のページに集約。</li>
    </ul>
    <p class="muted">本ページは jpcite による集約情報であり、申請可否・受給可否を保証するものではありません。
    最終的な判断は必ず一次情報および有資格者 (税理士・社労士・中小企業診断士) の助言を経て行ってください。</p>
  </section>

{list_section}

  <section class="city-related" aria-labelledby="related-title">
    <h2 id="related-title">関連リンク</h2>
    <ul>
      <li><a href="/prefectures/{pref_slug}.html">{html.escape(pref_ja)} の補助金・融資・税制 一覧</a> (上位 hub)</li>
      <li><a href="/cross/{pref_slug}/">{html.escape(pref_ja)} から申請できる 全国 補助金</a> (国制度の県内適合)</li>
      <li><a href="/cities/">政令指定都市別 補助金 インデックス (20市)</a></li>
      <li><a href="/programs/">全制度を検索する</a></li>
    </ul>
  </section>

  <section class="city-api" aria-labelledby="api-title">
    <h2 id="api-title">{html.escape(city_ja)}データを API / MCP で取得</h2>
    <p>本ページに掲載した{html.escape(city_ja)}の制度データは、jpcite REST API および MCP サーバーから
    機械可読な形式で取得できます。Claude Desktop / Cursor / Cline などの MCP クライアント、または
    ChatGPT Custom GPT の OpenAPI Actions から呼び出せます。</p>
    <pre class="code-block"><code>curl -H "X-API-Key: YOUR_API_KEY" \\
  "https://api.{domain}/v1/programs/search?prefecture={pref_ja}&amp;municipality={city_ja}&amp;limit=20"</code></pre>
  </section>

  <p class="disclaimer">本ページは jpcite が一次情報を集約・構造化したプレビューであり、法的助言・税務助言・申請代行を構成するものではありません。
  制度の最新内容・申請可否・併用可否は所管官公庁・自治体の一次情報および有資格者の助言で必ず確認してください。
  最終取得日: <time datetime="{today}">{today}</time>。</p>
  </article>
</main>
<footer class="site-footer" role="contentinfo">
  <div class="container footer-inner">
    <div class="footer-col">
      <p class="footer-brand"><picture class="footer-brand-mark"><source media="(prefers-color-scheme: light)" srcset="/assets/brand/jpcite-mark-light-fill.svg"><img src="/assets/brand/jpcite-mark-dark-fill.svg" alt="" width="20" height="20" loading="lazy" decoding="async"></picture>jpcite</p>
      <p class="footer-tag">日本の公的制度を、根拠付き成果物に。</p>
    </div>
    <nav class="footer-nav" aria-label="フッター">
      <a href="/about.html">運営について</a>
      <a href="/products.html">成果物</a>
      <a href="/pricing.html">料金</a>
      <a href="/docs/">API ドキュメント</a>
      <a href="/trust.html">信頼</a>
      <a href="/tos.html">利用規約</a>
      <a href="/privacy.html">プライバシー</a>
      <a href="/tokushoho.html">特商法</a>
    </nav>
    <p class="footer-entity">運営: Bookyou株式会社</p>
    <p class="footer-copy">&copy; 2026 Bookyou株式会社</p>
    <p class="muted">本サイトは税理士法 §52 が規定する税務代理・税務書類作成・税務相談の提供を行いません。個別の税務判断は税理士・社労士・中小企業診断士等の有資格者にご相談ください。</p>
  </div>
</footer>
</body>
</html>
"""


def _render_index_page(
    city_summaries: list[dict[str, Any]],
    domain: str,
) -> str:
    canonical = f"https://{domain}/cities/"
    today = _today_jst_iso()
    title = "政令指定都市別 補助金 一覧 (20市) | jpcite"
    desc = (
        "札幌・仙台・さいたま・千葉・横浜・川崎・相模原・新潟・静岡・浜松・名古屋・京都・大阪・堺・"
        "神戸・岡山・広島・北九州・福岡・熊本の 20 政令指定都市別補助金・助成金 一覧。"
        "jpcite が一次資料 URL とあわせて集約。"
    )

    # Region grouping: same buckets as PREFECTURES REGIONS.
    region_buckets: dict[str, list[dict[str, Any]]] = {}
    region_order: list[str] = []
    for s in city_summaries:
        region = s["region_ja"]
        if region not in region_buckets:
            region_buckets[region] = []
            region_order.append(region)
        region_buckets[region].append(s)

    region_html_parts = []
    for region in region_order:
        items = region_buckets[region]
        item_html = "\n".join(
            f'        <li><a href="/cities/{s["slug"]}/">{html.escape(s["city_ja"])}'
            f'</a> <span class="muted">({s["count"]}件 / {html.escape(s["pref_ja"])})</span></li>'
            for s in items
        )
        region_html_parts.append(
            f'    <section class="city-region">\n'
            f"      <h2>{html.escape(region)}</h2>\n"
            f'      <ul class="city-region-list">\n{item_html}\n      </ul>\n'
            f"    </section>"
        )
    regions_html = "\n".join(region_html_parts)

    # JSON-LD
    item_list = []
    pos = 1
    for region in region_order:
        for s in region_buckets[region]:
            item_list.append(
                {
                    "@type": "ListItem",
                    "position": pos,
                    "url": f"https://{domain}/cities/{s['slug']}/",
                    "name": s["city_ja"],
                }
            )
            pos += 1
    json_ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": f"https://{domain}/#publisher",
                "name": "jpcite",
                "url": f"https://{domain}/",
            },
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
                        "name": "政令指定都市別",
                        "item": canonical,
                    },
                ],
            },
            {
                "@type": "ItemList",
                "@id": "#cities-index",
                "name": "政令指定都市別 補助金 インデックス (20市)",
                "numberOfItems": len(item_list),
                "itemListElement": item_list,
            },
        ],
    }
    json_ld_str = json.dumps(json_ld, ensure_ascii=False, indent=2).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#ffffff">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<meta name="author" content="jpcite">
<meta name="publisher" content="jpcite">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="https://{domain}/assets/og.png">
<meta property="og:locale" content="ja_JP">
<meta property="og:site_name" content="jpcite">
<link rel="canonical" href="{canonical}">
<link rel="alternate" hreflang="ja" href="{canonical}">
<link rel="alternate" hreflang="x-default" href="{canonical}">
<link rel="icon" href="/assets/favicon-v2.svg" type="image/svg+xml">
<link rel="stylesheet" href="/styles.css?v=20260428a">
<script type="application/ld+json">
{json_ld_str}
</script>
</head>
<body>
<a href="#main" class="skip-link">本文へスキップ</a>
<header class="site-header" role="banner">
  <div class="container header-inner">
    <a class="brand" href="/" aria-label="jpcite ホーム">
 <picture><source media="(prefers-color-scheme: dark)" srcset="/assets/brand/lockup-transparent-600-lightlogo.png 1x, /assets/brand/lockup-transparent-1200-lightlogo.png 2x"><img src="/assets/brand/lockup-transparent-600-darklogo.png" srcset="/assets/brand/lockup-transparent-600-darklogo.png 1x, /assets/brand/lockup-transparent-1200-darklogo.png 2x" width="190" decoding="async" fetchpriority="high" alt="jpcite" height="32" style="height:32px;width:auto;display:block;"></picture>
 </a>
    <nav class="site-nav" aria-label="主要ナビゲーション">
      <a href="/about.html">運営について</a>
      <a href="/products.html">プロダクト</a>
      <a href="/docs/">ドキュメント</a>
      <a href="/pricing.html">料金</a>
      <a href="/prefectures/">都道府県別</a>
    </nav>
  </div>
</header>
<main id="main" class="container cities-index-page">
  <nav class="breadcrumb" aria-label="パンくずリスト">
    <a href="/">ホーム</a>
    <span aria-hidden="true">›</span>
    <span aria-current="page">政令指定都市別</span>
  </nav>
  <article>
    <header>
      <h1>政令指定都市別 補助金 一覧 (20市)</h1>
      <p class="byline">
        <span class="updated">出典取得: {today}</span>
        <span class="sep">/</span>
        <span class="author">jpcite</span>
      </p>
      <p class="muted">日本の 20 政令指定都市 (札幌・仙台・さいたま・千葉・横浜・川崎・相模原・新潟・静岡・浜松・
      名古屋・京都・大阪・堺・神戸・岡山・広島・北九州・福岡・熊本) ごとの補助金・助成金 一覧です。
      各市のページには市・県・国の一次資料リンクとともに掲載しています。</p>
    </header>
{regions_html}
  </article>
</main>
<footer class="site-footer" role="contentinfo">
  <div class="container footer-inner">
    <div class="footer-col">
      <p class="footer-brand"><picture class="footer-brand-mark"><source media="(prefers-color-scheme: light)" srcset="/assets/brand/jpcite-mark-light-fill.svg"><img src="/assets/brand/jpcite-mark-dark-fill.svg" alt="" width="20" height="20" loading="lazy" decoding="async"></picture>jpcite</p>
      <p class="footer-tag">日本の公的制度を、根拠付き成果物に。</p>
    </div>
    <nav class="footer-nav" aria-label="フッター">
      <a href="/about.html">運営について</a>
      <a href="/products.html">成果物</a>
      <a href="/pricing.html">料金</a>
      <a href="/docs/">API ドキュメント</a>
      <a href="/trust.html">信頼</a>
      <a href="/tos.html">利用規約</a>
      <a href="/privacy.html">プライバシー</a>
      <a href="/tokushoho.html">特商法</a>
    </nav>
    <p class="footer-entity">運営: Bookyou株式会社</p>
    <p class="footer-copy">&copy; 2026 Bookyou株式会社</p>
  </div>
</footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------


def _write_sitemap(
    city_slugs: list[str],
    path: Path,
    domain: str,
    today: str,
) -> None:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!--",
        "  City hub sitemap shard for jpcite.com.",
        "  20 政令指定都市 hub pages + 1 index = 21 URLs.",
        "  Independent fragment — does not overlap sitemap-prefectures.xml or",
        "  sitemap-cross.xml. URL form is /cities/{slug}/ (slash-terminated)",
        "  to match public routing and avoid canonical/redirect mismatch.",
        "-->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        "  <url>",
        f"    <loc>https://{domain}/cities/</loc>",
        f"    <lastmod>{today}</lastmod>",
        "    <changefreq>weekly</changefreq>",
        "    <priority>0.7</priority>",
        "  </url>",
    ]
    for slug in city_slugs:
        lines.extend(
            [
                "  <url>",
                f"    <loc>https://{domain}/cities/{slug}/</loc>",
                f"    <lastmod>{today}</lastmod>",
                "    <changefreq>weekly</changefreq>",
                "    <priority>0.6</priority>",
                "  </url>",
            ]
        )
    lines.append("</urlset>")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--domain", default=DEFAULT_DOMAIN)
    parser.add_argument("--sitemap", type=Path, default=DEFAULT_SITEMAP)
    parser.add_argument(
        "--slug",
        default=None,
        help="Generate only this city slug (e.g. yokohama). Skips index + sitemap.",
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

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    targets: list[tuple[str, str, str, str, str]]
    if args.slug:
        match = [c for c in CITIES if c[0] == args.slug]
        if not match:
            LOG.error("Unknown city slug: %s. Valid: %s", args.slug, ",".join(c[0] for c in CITIES))
            return 1
        targets = match
    else:
        targets = list(CITIES)

    today = _today_jst_iso()
    city_summaries: list[dict[str, Any]] = []
    written = 0
    skipped = 0
    line_counts: list[int] = []

    for city_slug, city_ja, pref_slug, pref_ja, region_ja in targets:
        like_pat = f"%{city_ja}%"
        rows = list(
            conn.execute(
                PROGRAMS_BY_CITY_SQL,
                (pref_ja, like_pat, like_pat, PROGRAMS_PER_PAGE),
            )
        )
        programs = [_shape_program(r) for r in rows]
        total_row = conn.execute(
            PROGRAMS_COUNT_BY_CITY_SQL, (pref_ja, like_pat, like_pat)
        ).fetchone()
        programs_total = int(total_row[0]) if total_row else 0

        html_doc = _render_city_page(
            city_slug,
            city_ja,
            pref_slug,
            pref_ja,
            region_ja,
            programs,
            programs_total,
            args.domain,
        )
        line_counts.append(html_doc.count("\n") + 1)

        out_path = args.out / city_slug / "index.html"
        if args.dry_run:
            LOG.info(
                "[dry-run] %s (%s) — %d lines, %d programs (total %d)",
                city_slug,
                city_ja,
                line_counts[-1],
                len(programs),
                programs_total,
            )
        else:
            changed = _write_if_changed(out_path, html_doc)
            if changed:
                written += 1
            else:
                skipped += 1
            LOG.info(
                "%s %s (%s) — %d programs (total %d)",
                "WROTE" if changed else "skip",
                city_slug,
                city_ja,
                len(programs),
                programs_total,
            )

        city_summaries.append(
            {
                "slug": city_slug,
                "city_ja": city_ja,
                "pref_slug": pref_slug,
                "pref_ja": pref_ja,
                "region_ja": region_ja,
                "count": programs_total,
            }
        )

    if args.slug:
        avg_lines = sum(line_counts) // len(line_counts) if line_counts else 0
        LOG.info("Single slug done. avg_lines=%d", avg_lines)
        return 0

    # Index page
    index_html = _render_index_page(city_summaries, args.domain)
    index_path = args.out / "index.html"
    if args.dry_run:
        LOG.info("[dry-run] index.html — %d lines", index_html.count("\n") + 1)
    else:
        if _write_if_changed(index_path, index_html):
            written += 1
        else:
            skipped += 1

    # Sitemap (20 + 1 = 21 URLs)
    if not args.dry_run:
        _write_sitemap(
            [c[0] for c in CITIES],
            args.sitemap,
            args.domain,
            today,
        )
        LOG.info("Wrote sitemap: %s", args.sitemap)

    avg_lines = sum(line_counts) // len(line_counts) if line_counts else 0
    LOG.info(
        "Done. wrote=%d skipped=%d avg_lines=%d (over %d cities)",
        written,
        skipped,
        avg_lines,
        len(line_counts),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
