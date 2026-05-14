#!/usr/bin/env python3
"""Generate prefecture × top-10 program **hub** pages.

This is the post 2026-04-29 SEO AI-feel reduction successor to
``generate_geo_program_pages.py``. The legacy generator emitted 47×10 = 470
individual pair pages (one per ``cross/{pref}/{program}.html``). The hub
generator collapses each prefecture to a single ``cross/{pref}/index.html``
that lists the top 10 most relevant programs **inline** so the depth-1 SEO
surface is one page per prefecture instead of ten.

Inputs
------
- ``data/jpintel.db``  — programs (tier S+A, source_url present, non-aggregator)

Outputs
-------
- ``site/cross/{pref_slug}/index.html``  (47 hub pages)
- ``site/sitemap-cross.xml``             (47 entries, regenerated)

Selection
---------
"Top 10" per prefecture is built deterministically:

1. Start with all tier S/A programs that match the prefecture
   (national programs + this prefecture's prefecture-locked programs).
2. Rank by tier (S > A), then ``amount_max_man_yen`` DESC, then ``unified_id``
   for stable tie-break.
3. Take the first 10.

If a prefecture has fewer than 10 matches, the page lists what we have and
declares the actual count honestly. No padding.

The footer disclaimer lives in the embedded HTML below and matches the rest
of the static site.
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
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_OUT = REPO_ROOT / "site" / "cross"
DEFAULT_SITEMAP = REPO_ROOT / "site" / "sitemap-cross.xml"
DEFAULT_DOMAIN = "jpcite.com"

_JST = timezone(timedelta(hours=9))

LOG = logging.getLogger("generate_cross_hub_pages")

# Reuse canonical pref list to avoid drift.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pref_slugs import PREFECTURES, REGIONS  # type: ignore  # noqa: E402

# Reuse program slug derivation so internal links resolve to the freshly
# regenerated /programs/{slug}.html pages.
try:
    from jpintel_mcp.utils.slug import program_static_slug
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: jpintel_mcp.utils.slug not importable — pip install -e . first.\n")
    raise


KIND_JA = {
    "subsidy": "補助金・交付金",
    "grant": "助成金・給付金",
    "loan": "融資 (政策金融)",
    "tax_credit": "税制優遇",
    "incentive": "奨励・インセンティブ制度",
    "certification": "認定制度",
    "training": "研修・人材育成",
}


SELECT_SQL = """
SELECT unified_id, primary_name, prefecture, program_kind,
       amount_max_man_yen, amount_min_man_yen, tier, source_url,
       authority_name
FROM programs
WHERE excluded = 0
  AND tier IN ('S','A')
  AND source_url IS NOT NULL
  AND source_url <> ''
  AND (authority_name IS NULL OR authority_name NOT LIKE '%noukaweb%')
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

_PUBLIC_ID_PREFIX_RE = re.compile(r"^(?:MUN-\d{2,6}-\d{3}|PREF-\d{2,6}-\d{3})[_\s]+")
_PREF_HOST_RE = re.compile(r"(?:^|\.)pref\.([a-z]+)\.(?:lg\.jp|jp)$")
_CITY_HOST_RE = re.compile(r"(?:^|\.)city\.[a-z0-9-]+\.([a-z]+)\.(?:lg\.jp|jp)$")
_PREF_KEY_TO_JA = dict(PREFECTURES)


def _public_program_name(name: str | None) -> str:
    return _PUBLIC_ID_PREFIX_RE.sub("", (name or "").strip())


def _source_prefecture(row: dict[str, Any]) -> str | None:
    try:
        host = (urlparse(row.get("source_url") or "").hostname or "").lower()
    except Exception:
        return None
    if host.startswith("www."):
        host = host[4:]
    for pattern in (_PREF_HOST_RE, _CITY_HOST_RE):
        m = pattern.search(host)
        if m:
            return _PREF_KEY_TO_JA.get(m.group(1))
    return None


def _today_jst_iso() -> str:
    return datetime.now(_JST).date().isoformat()


def _amount_line(max_man: float | None, min_man: float | None) -> str:
    """Compact JA money string. Mirrors generate_geo_program_pages._amount_line."""
    if max_man is None and min_man is None:
        return "金額非公表"
    if max_man is not None and min_man is not None and min_man > 0:
        return f"{int(min_man):,}万円 〜 {int(max_man):,}万円"
    if max_man is not None:
        return f"最大 {int(max_man):,}万円"
    if min_man is not None:
        return f"{int(min_man):,}万円〜"
    return "金額非公表"


def _is_national(pref: str | None) -> bool:
    if pref is None:
        return True
    s = str(pref).strip()
    return s == "" or s == "全国" or s == "national"


def _matches_pref(row_pref: str | None, target_ja: str) -> bool:
    """True if a program row applies to the target prefecture (national counts)."""
    if _is_national(row_pref):
        return True
    return str(row_pref).strip() == target_ja


def _matches_pref_strict(row: dict[str, Any], target_ja: str) -> bool:
    row_pref = row.get("prefecture")
    if not _matches_pref(row_pref, target_ja):
        return False
    source_pref = _source_prefecture(row)
    return source_pref is None or source_pref == target_ja


def _rank_key(r: dict[str, Any]) -> tuple[int, float, str]:
    tier_rank = 0 if (r.get("tier") or "") == "S" else 1
    amt = -float(r.get("amount_max_man_yen") or 0)  # DESC via negation
    return (tier_rank, amt, r.get("unified_id") or "")


def _select_top_for_pref(
    rows: list[dict[str, Any]], pref_ja: str, top_n: int
) -> list[dict[str, Any]]:
    matched = [r for r in rows if _matches_pref_strict(r, pref_ja)]
    matched.sort(key=_rank_key)
    return matched[:top_n]


def _render_hub(
    pref_slug: str,
    pref_ja: str,
    region_ja: str,
    top: list[dict[str, Any]],
    domain: str,
) -> str:
    """Self-contained HTML hub page. No Jinja2 — keeps script standalone."""
    today = _today_jst_iso()
    canonical = f"https://{domain}/cross/{pref_slug}/"
    lis: list[str] = []
    for r in top:
        slug = program_static_slug(r["primary_name"] or "", r["unified_id"])
        kind = KIND_JA.get(r.get("program_kind") or "subsidy", "公的支援制度")
        amt = _amount_line(r.get("amount_max_man_yen"), r.get("amount_min_man_yen"))
        tier = (r.get("tier") or "A").upper()
        name_esc = html.escape(_public_program_name(r["primary_name"] or ""))
        src = html.escape(r.get("source_url") or "")
        lis.append(
            '      <li class="cross-program">\n'
            f'        <a class="cross-program-name" href="/programs/{slug}.html">{name_esc}</a>\n'
            f'        <span class="cross-program-meta">tier {tier} ・ {kind} ・ {amt}</span>\n'
            f'        <a class="cross-program-source" href="{src}" rel="noopener noreferrer">出典ページを開く</a>\n'
            "      </li>"
        )
    if not lis:
        lis.append(
            '      <li class="cross-program-empty">'
            f"{html.escape(pref_ja)} 向け tier S/A 制度は現在 0 件です。"
            "</li>"
        )
    inline_html = "\n".join(lis)
    title = f"{pref_ja} 補助金・税制 主要{len(top)}件 | jpcite"
    desc = (
        f"{pref_ja}から確認されやすい全国制度・広域制度・地域制度の候補を tier S/A の上位 {len(top)} 件で集約。"
        "対象地域・申請者要件は出典ページで確認が必要です。jpcite API/MCP で同等データ取得可。"
    )
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
                        "name": "都道府県別",
                        "item": f"https://{domain}/cross/",
                    },
                    {"@type": "ListItem", "position": 3, "name": pref_ja, "item": canonical},
                ],
            },
            {
                "@type": "ItemList",
                "name": f"{pref_ja} 主要制度 上位{len(top)}件",
                "itemListOrder": "https://schema.org/ItemListOrderDescending",
                "numberOfItems": len(top),
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": i + 1,
                        "name": _public_program_name(r["primary_name"] or ""),
                        "url": f"https://{domain}/programs/{program_static_slug(r['primary_name'] or '', r['unified_id'])}.html",
                    }
                    for i, r in enumerate(top)
                ],
            },
        ],
    }
    json_ld_str = json.dumps(json_ld, ensure_ascii=False, indent=2)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
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
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{html.escape(title)}">
<meta name="twitter:description" content="{html.escape(desc)}">
<meta name="twitter:image" content="https://{domain}/assets/og-twitter.png">
<link rel="canonical" href="{canonical}">
<link rel="alternate" hreflang="ja" href="{canonical}">
<link rel="alternate" hreflang="x-default" href="{canonical}">
<link rel="icon" href="/assets/favicon-v2.svg" type="image/svg+xml">
<link rel="stylesheet" href="/styles.css?v=20260515c">
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
 <a href="/products.html">成果物</a>
 <a href="/connect/">接続</a>
 <a href="/prompts/">Prompts</a>
 <a href="/pricing.html">料金</a>
 <a href="/audiences/">利用者層</a>
 <a href="/docs/">API ドキュメント</a>
 <a href="/about.html">会社</a>
 <details class="nav-trust">
 <summary>信頼</summary>
 <ul>
 <li><a href="/trust.html">信頼の設計</a></li>
 <li><a href="/status.html">稼働状況</a></li>
 <li><a href="/data-freshness.html">データ鮮度</a></li>
 <li><a href="/transparency.html">透明性</a></li>
 <li><a href="/sources.html">出典</a></li>
 </ul>
 </details>
 <span class="lang-switch" role="group" aria-label="Language / 言語">
 <a href="/" lang="ja" hreflang="ja">JP</a>
 <span class="sep" aria-hidden="true">/</span>
 <a href="/en/index.html" lang="en" hreflang="en">EN</a>
 </span>
 </nav>
  </div>
</header>
<main id="main" class="container">
  <nav class="breadcrumb" aria-label="パンくずリスト">
    <a href="/">ホーム</a>
    <span aria-hidden="true">›</span>
    <a href="/cross/">都道府県別</a>
    <span aria-hidden="true">›</span>
    <span aria-current="page">{html.escape(pref_ja)}</span>
  </nav>
  <h1>{html.escape(pref_ja)} 補助金・税制 主要{len(top)}件</h1>
  <p class="lede">この一覧は、{html.escape(region_ja)}・{html.escape(pref_ja)}から確認されやすい
  全国制度・広域制度・地域制度の候補を、tier S/A と金額情報をもとに上位{len(top)}件まで集約したものです。
  掲載制度には地域外自治体や特定地域向けの制度が含まれる場合があります。申請前に、対象地域・所在地要件・業種要件を一次資料で必ず確認してください。
  各制度名は jpcite の制度詳細ページに、出典は一次資料 URL に直接リンクしています。</p>
  <section class="cross-section" aria-label="主要制度一覧">
    <h2>主要制度（tier S/A）</h2>
    <ul class="cross-list">
{inline_html}
    </ul>
  </section>
  <section class="cross-related" aria-label="関連リンク">
    <h2>関連リンク</h2>
    <ul>
      <li><a href="/prefectures/{pref_slug}.html">{html.escape(pref_ja)} 一次資料・地域制度ハイライト</a></li>
      <li><a href="/programs/">全制度を検索する</a></li>
      <li><a href="/dashboard.html">条件指定で検索（事業類型・金額・締切）</a></li>
    </ul>
  </section>
  <section class="cross-disclaimer" aria-label="免責">
    <h2>免責</h2>
    <p>本ページは jpcite が公開する一次資料ベースの集約結果です。掲載内容は
    出典確認状況に基づいて整理しており、申請可否や採択を保証するものではありません。
    最新の公募要領・申請期間・対象要件は必ず一次資料 URL でご確認ください。
    最終取得日: <time datetime="{today}">{today}</time>。</p>
  </section>
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


def _region_for(pref_slug: str) -> str:
    for region_ja, slugs in REGIONS:
        if pref_slug in slugs:
            return region_ja
    return ""


def _write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _write_sitemap(entries: list[tuple[str, str]], path: Path, domain: str) -> None:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- Cross-prefecture hub sitemap shard for jpcite.com. -->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for pref_slug, lastmod in entries:
        lines.append("  <url>")
        lines.append(f"    <loc>https://{domain}/cross/{pref_slug}/</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("    <changefreq>weekly</changefreq>")
        lines.append("    <priority>0.6</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate(
    db_path: Path,
    out_dir: Path,
    sitemap_path: Path | None,
    domain: str,
    top_n: int,
) -> tuple[int, int]:
    if not db_path.exists():
        LOG.error("database not found: %s", db_path)
        raise SystemExit(1)
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(SELECT_SQL)]
    LOG.info("tier S/A pool size: %d", len(rows))
    written = 0
    skipped = 0
    sitemap_entries: list[tuple[str, str]] = []
    today = _today_jst_iso()
    for pref_slug, pref_ja in PREFECTURES:
        top = _select_top_for_pref(rows, pref_ja, top_n)
        region_ja = _region_for(pref_slug)
        html_doc = _render_hub(pref_slug, pref_ja, region_ja, top, domain)
        path = out_dir / pref_slug / "index.html"
        if _write_if_changed(path, html_doc):
            written += 1
        else:
            skipped += 1
        sitemap_entries.append((pref_slug, today))
    if sitemap_path is not None:
        _write_sitemap(sitemap_entries, sitemap_path, domain)
    return written, skipped


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB), type=Path)
    p.add_argument("--out", default=str(DEFAULT_OUT), type=Path)
    p.add_argument("--sitemap", default=str(DEFAULT_SITEMAP), type=Path)
    p.add_argument("--domain", default=DEFAULT_DOMAIN)
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    sitemap = args.sitemap if str(args.sitemap) else None
    written, skipped = generate(
        db_path=args.db,
        out_dir=args.out,
        sitemap_path=sitemap,
        domain=args.domain,
        top_n=args.top,
    )
    LOG.info("written=%d skipped=%d", written, skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
