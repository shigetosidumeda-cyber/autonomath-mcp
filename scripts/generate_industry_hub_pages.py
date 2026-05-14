#!/usr/bin/env python3
"""Generate JSIC industry **hub** pages (20 majors + 2 sub-partials).

This is the post 2026-04-29 SEO AI-feel reduction successor to
``generate_industry_program_pages.py``. The legacy generator emitted ~1,049
individual ``industries/{jsic}/{slug}/index.html`` per-program-per-JSIC
pages. The hub generator collapses each JSIC major to a single
``industries/{jsic}/index.html`` that lists the top 20 most relevant
programs **inline**.

Outputs
-------
- ``site/industries/{jsic}/index.html`` for JSIC majors with at least one match
- ``site/industries/{jsic}-sme/index.html`` × 2 (E + L sub-partials, top 20 each)
- ``site/sitemap-industries.xml`` (regenerated, excludes empty hubs)

Selection
---------
Per JSIC major, candidate programs are filtered using the same evidence
rules from the legacy generator (``JSIC_MATCHERS``). Top 20 are picked by
tier (S > A > B), then ``amount_max_man_yen`` DESC, then ``unified_id``.
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
DEFAULT_OUT = REPO_ROOT / "site" / "industries"
DEFAULT_SITEMAP = REPO_ROOT / "site" / "sitemap-industries.xml"
DEFAULT_DOMAIN = "jpcite.com"
DEFAULT_TOP_N = 20

_JST = timezone(timedelta(hours=9))
LOG = logging.getLogger("generate_industry_hub_pages")

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from jpintel_mcp.utils.slug import program_static_slug
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: jpintel_mcp.utils.slug not importable.\n")
    raise

# Reuse the existing JSIC_MATCHERS rather than maintaining a parallel copy.
from generate_industry_program_pages import (  # type: ignore  # noqa: E402
    JSIC_MATCHERS,
    _parse_json_list,
)

KIND_JA = {
    "subsidy": "補助金・交付金",
    "grant": "助成金・給付金",
    "loan": "融資 (政策金融)",
    "tax_credit": "税制優遇",
    "incentive": "奨励・インセンティブ制度",
    "certification": "認定制度",
    "training": "研修・人材育成",
}


# ---------------------------------------------------------------------------
# JSIC matching (mirrors evidence rules from legacy generator)
# ---------------------------------------------------------------------------


SELECT_SQL = """
SELECT unified_id, primary_name, prefecture, program_kind, target_types_json,
       amount_max_man_yen, amount_min_man_yen, tier, source_url,
       authority_name, authority_level
FROM programs
WHERE excluded = 0
  AND tier IN ('S','A','B')
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
_PREPARING_TITLE_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"【\s*準備中\s*】|［\s*準備中\s*］|\[\s*準備中\s*\]|"
    r"（\s*準備中\s*）|\(\s*準備中\s*\)"
    r")\s*"
)
_PREPARING_STATUS_LABEL = "要綱未公表"


def _public_program_name(name: str | None) -> str:
    return _PUBLIC_ID_PREFIX_RE.sub("", (name or "").strip())


def _public_program_display_parts(name: str | None) -> tuple[str, str | None]:
    public_name = _public_program_name(name)
    display_name, replacements = _PREPARING_TITLE_PREFIX_RE.subn("", public_name, count=1)
    if replacements:
        return (display_name.strip() or public_name, _PREPARING_STATUS_LABEL)
    return (public_name, None)


def _public_program_jsonld_name(name: str | None) -> str:
    display_name, status_label = _public_program_display_parts(name)
    if status_label:
        return f"{display_name}（{status_label}）"
    return display_name


def _today_jst_iso() -> str:
    return datetime.now(_JST).date().isoformat()


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


def _matches_jsic(row: dict[str, Any], code: str) -> bool:
    matcher = JSIC_MATCHERS.get(code)
    if matcher is None:
        return False
    name = row.get("primary_name") or ""
    auth = row.get("authority_name") or ""
    src = row.get("source_url") or ""
    target_types = _parse_json_list(row.get("target_types_json"))
    # Token signal
    if any(t in target_types for t in matcher.target_type_tokens):
        return True
    # Domain signal
    try:
        host = (urlparse(src).hostname or "").lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    if any(k in host for k in matcher.domain_keywords):
        return True
    # Authority signal
    if any(k in auth for k in matcher.authority_keywords):
        return True
    # Name regex signal
    if matcher.name_regex is not None and matcher.name_regex.search(name):
        return True
    return bool(matcher.name_strong_regex is not None and matcher.name_strong_regex.search(name))


def _rank_key(r: dict[str, Any]) -> tuple[int, float, str]:
    tier_rank = {"S": 0, "A": 1, "B": 2}.get(r.get("tier") or "", 3)
    amt = -float(r.get("amount_max_man_yen") or 0)
    return (tier_rank, amt, r.get("unified_id") or "")


def _select_for_jsic(rows: list[dict[str, Any]], code: str, top_n: int) -> list[dict[str, Any]]:
    matched = [r for r in rows if _matches_jsic(r, code)]
    matched.sort(key=_rank_key)
    return matched[:top_n]


# ---------------------------------------------------------------------------
# Sub-partial filters (E + L are the heaviest majors → split out a "中小" cut)
# ---------------------------------------------------------------------------


_E_SME_REGEX = re.compile(
    "|".join(
        re.escape(k)
        for k in (
            "ものづくり",
            "中小企業",
            "小規模事業者",
            "事業再構築",
            "省エネ",
            "GX",
            "脱炭素",
            "サポイン",
            "Go-Tech",
        )
    )
)


_L_SME_REGEX = re.compile(
    "|".join(
        re.escape(k)
        for k in (
            "中小企業診断士",
            "弁理士",
            "公認会計士",
            "税理士",
            "社会保険労務士",
            "行政書士",
            "司法書士",
            "建築士",
            "経営コンサルタント",
        )
    )
)


def _select_e_sme(rows: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    candidates = [r for r in rows if _matches_jsic(r, "E")]
    matched = [r for r in candidates if _E_SME_REGEX.search(r.get("primary_name") or "")]
    matched.sort(key=_rank_key)
    return matched[:top_n]


def _select_l_sme(rows: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    candidates = [r for r in rows if _matches_jsic(r, "L")]
    matched = [r for r in candidates if _L_SME_REGEX.search(r.get("primary_name") or "")]
    matched.sort(key=_rank_key)
    return matched[:top_n]


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _render_hub(
    code: str,
    title_label: str,
    name_ja: str,
    description: str,
    top: list[dict[str, Any]],
    domain: str,
    canonical_path: str,
) -> str:
    today = _today_jst_iso()
    canonical = f"https://{domain}{canonical_path}"
    lis: list[str] = []
    for r in top:
        kind = KIND_JA.get(r.get("program_kind") or "subsidy", "公的支援制度")
        amt = _amount_line(r.get("amount_max_man_yen"), r.get("amount_min_man_yen"))
        tier = (r.get("tier") or "A").upper()
        public_name, status_label = _public_program_display_parts(r["primary_name"] or "")
        name_esc = html.escape(public_name)
        status_html = ""
        if status_label:
            status_esc = html.escape(status_label)
            status_html = f'        <span class="industry-program-status">{status_esc}</span>\n'
        src = html.escape(r.get("source_url") or "")
        # Tier S/A still have a static SSG page (post 2026-04-29 reduction);
        # tier B fell back to dynamic search by unified_id so we never link
        # to a 404. The /programs/share.html surface resolves UNI-* to a
        # real card via /v1/programs/batch.
        if tier in ("S", "A"):
            slug = program_static_slug(r["primary_name"] or "", r["unified_id"])
            program_href = f"/programs/{slug}.html"
        else:
            uid = html.escape(r["unified_id"] or "")
            program_href = f"/programs/share.html?ids={uid}"
        lis.append(
            '      <li class="industry-program">\n'
            f'        <a class="industry-program-name" href="{program_href}">{name_esc}</a>\n'
            f"{status_html}"
            f'        <span class="industry-program-meta">tier {tier} ・ {kind} ・ {amt}</span>\n'
            f'        <a class="industry-program-source" href="{src}" rel="noopener noreferrer">出典ページを開く</a>\n'
            "      </li>"
        )
    if not lis:
        lis.append(
            '      <li class="industry-program-empty">'
            f"{html.escape(name_ja)} 向けに該当する tier S/A/B 制度は現在 0 件です。"
            "</li>"
        )
    inline_html = "\n".join(lis)
    title = f"{title_label} 補助金・税制 主要{len(top)}件 | jpcite"
    desc = description
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
                        "name": "業種別",
                        "item": f"https://{domain}/industries/",
                    },
                    {"@type": "ListItem", "position": 3, "name": title_label, "item": canonical},
                ],
            },
            {
                "@type": "ItemList",
                "name": f"{title_label} 主要制度 上位{len(top)}件",
                "numberOfItems": len(top),
                "itemListOrder": "https://schema.org/ItemListOrderDescending",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": i + 1,
                        "name": _public_program_jsonld_name(r["primary_name"] or ""),
                        "url": (
                            f"https://{domain}/programs/{program_static_slug(r['primary_name'] or '', r['unified_id'])}.html"
                            if (r.get("tier") or "").upper() in ("S", "A")
                            else f"https://{domain}/programs/share.html?ids={r['unified_id']}"
                        ),
                    }
                    for i, r in enumerate(top)
                ],
            },
        ],
    }
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
<link rel="canonical" href="{canonical}">
<link rel="alternate" hreflang="ja" href="{canonical}">
<link rel="alternate" hreflang="x-default" href="{canonical}">
<link rel="icon" href="/assets/favicon-v2.svg" type="image/svg+xml">
<link rel="stylesheet" href="/styles.css?v=20260428a">
<script type="application/ld+json">
{json.dumps(json_ld, ensure_ascii=False, indent=2)}
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
      <a href="/docs/">Docs</a>
      <a href="/pricing.html">Pricing</a>
      <a href="/dashboard.html">検索</a>
    </nav>
  </div>
</header>
<main id="main" class="container">
  <nav class="breadcrumb" aria-label="パンくずリスト">
    <a href="/">ホーム</a>
    <span aria-hidden="true">›</span>
    <a href="/industries/">業種別</a>
    <span aria-hidden="true">›</span>
    <span aria-current="page">{html.escape(title_label)}</span>
  </nav>
  <h1>{html.escape(title_label)} 補助金・税制 主要{len(top)}件</h1>
  <p class="lede">JSIC {html.escape(code)} ({html.escape(name_ja)}) に該当する事業者向けの
  主要制度を、補助金額の大きい順に上位{len(top)}件まで集約しました。
  各制度は jpcite の制度詳細ページに、出典は一次情報の URL に直接リンクしています。</p>
  <section class="industry-section" aria-label="主要制度一覧">
    <h2>主要制度（tier S/A/B）</h2>
    <ul class="industry-list">
{inline_html}
    </ul>
  </section>
  <section class="industry-related" aria-label="関連リンク">
    <h2>関連リンク</h2>
    <ul>
      <li><a href="/programs/">全制度を検索する</a></li>
      <li><a href="/dashboard.html">条件指定で検索（事業類型・金額・締切）</a></li>
      <li><a href="/cross/">都道府県別ハブ</a></li>
    </ul>
  </section>
  <section class="industry-disclaimer" aria-label="免責">
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


def _render_index(
    code_to_count: dict[str, int],
    sme_pages: list[tuple[str, str, int]],  # (slug, label, count)
    domain: str,
) -> str:
    today = _today_jst_iso()
    canonical = f"https://{domain}/industries/"
    rows_html: list[str] = []
    for code, matcher in JSIC_MATCHERS.items():
        n = code_to_count.get(code, 0)
        label = f"JSIC {code} {html.escape(matcher.name_ja)}"
        if n:
            rows_html.append(
                f'      <li><a href="/industries/{code}/">{label}</a> '
                f'<span class="industry-count">{n}件</span></li>'
            )
        else:
            rows_html.append(
                f"      <li><span>{label}</span> "
                '<span class="industry-count">候補確認中</span></li>'
            )
    sme_lis: list[str] = []
    for slug, label, n in sme_pages:
        sme_lis.append(
            f'      <li><a href="/industries/{slug}/">{html.escape(label)}</a> '
            f'<span class="industry-count">{n}件</span></li>'
        )
    title = "業種別ハブ 一覧 (JSIC 22部門) | jpcite"
    desc = (
        "JSIC 産業大分類 20 部門と中小企業向け 2 部門 (製造業中小・専門技術業中小) "
        "の業種別ハブから、各業種に関連する補助金・税制を出典リンク付きで横断的に検索。"
    )
    rows_str = "\n".join(rows_html)
    sme_str = "\n".join(sme_lis)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<meta name="author" content="jpcite">
<meta name="publisher" content="jpcite">
<meta name="robots" content="index, follow">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="https://{domain}/assets/og.png">
<meta property="og:locale" content="ja_JP">
<meta property="og:site_name" content="jpcite">
<link rel="canonical" href="{canonical}">
<link rel="icon" href="/assets/favicon-v2.svg" type="image/svg+xml">
<link rel="stylesheet" href="/styles.css?v=20260428a">
</head>
<body>
<a href="#main" class="skip-link">本文へスキップ</a>
<header class="site-header" role="banner">
  <div class="container header-inner">
    <a class="brand" href="/" aria-label="jpcite ホーム">
 <picture><source media="(prefers-color-scheme: dark)" srcset="/assets/brand/lockup-transparent-600-lightlogo.png 1x, /assets/brand/lockup-transparent-1200-lightlogo.png 2x"><img src="/assets/brand/lockup-transparent-600-darklogo.png" srcset="/assets/brand/lockup-transparent-600-darklogo.png 1x, /assets/brand/lockup-transparent-1200-darklogo.png 2x" width="190" decoding="async" fetchpriority="high" alt="jpcite" height="32" style="height:32px;width:auto;display:block;"></picture>
 </a>
    <nav class="site-nav" aria-label="主要ナビゲーション">
      <a href="/docs/">Docs</a>
      <a href="/pricing.html">Pricing</a>
      <a href="/dashboard.html">検索</a>
    </nav>
  </div>
</header>
<main id="main" class="container">
  <nav class="breadcrumb" aria-label="パンくずリスト">
    <a href="/">ホーム</a>
    <span aria-hidden="true">›</span>
    <span aria-current="page">業種別</span>
  </nav>
  <h1>業種別ハブ 一覧</h1>
  <p class="lede">日本標準産業分類 (JSIC) の大分類 20 部門 + 中小企業向け 2 部門のハブから、
  各業種に関連する補助金・助成金・融資・税制を出典リンク付きで横断的に検索できます。</p>
  <section class="industry-major-list">
    <h2>JSIC 大分類</h2>
    <ul>
{rows_str}
    </ul>
  </section>
  <section class="industry-sme-list">
    <h2>中小企業向け 主要パーシャル</h2>
    <ul>
{sme_str}
    </ul>
  </section>
  <section class="industry-disclaimer" aria-label="免責">
    <h2>免責</h2>
    <p>業種マッピングは制度名・所管・対象種別・出典ドメインの 4 軸 evidence マッチで判定しています。
    誤った関連付けを避けるため、根拠が弱い組合せはハブから除外しています。
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


def _write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _write_sitemap(entries: list[tuple[str, str]], path: Path, domain: str) -> None:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- Industry hub sitemap shard for jpcite.com. -->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path_loc, lastmod in entries:
        lines.append("  <url>")
        lines.append(f"    <loc>https://{domain}{path_loc}</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("    <changefreq>weekly</changefreq>")
        lines.append("    <priority>0.5</priority>")
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
    LOG.info("tier S/A/B pool size: %d", len(rows))

    written = 0
    skipped = 0
    sitemap_entries: list[tuple[str, str]] = []
    today = _today_jst_iso()
    code_to_count: dict[str, int] = {}

    # 20 majors (A..T)
    for code in JSIC_MATCHERS:
        matcher = JSIC_MATCHERS[code]
        top = _select_for_jsic(rows, code, top_n)
        code_to_count[code] = len(top)
        if not top:
            stale_path = out_dir / code / "index.html"
            if stale_path.exists():
                stale_path.unlink()
                written += 1
                LOG.info("JSIC %s (%s): 0 matches → removed stale empty hub", code, matcher.name_ja)
            else:
                LOG.info("JSIC %s (%s): 0 matches → skipping hub", code, matcher.name_ja)
            continue
        title_label = f"JSIC {code} {matcher.name_ja}"
        desc = (
            f"JSIC {code} ({matcher.name_ja}) の事業者向け 補助金・助成金・融資・税制 "
            f"上位{len(top)}件を出典リンク付きで集約。tier S/A/B のみ。"
        )
        html_doc = _render_hub(
            code,
            title_label,
            matcher.name_ja,
            desc,
            top,
            domain,
            f"/industries/{code}/",
        )
        path = out_dir / code / "index.html"
        if _write_if_changed(path, html_doc):
            written += 1
        else:
            skipped += 1
        sitemap_entries.append((f"/industries/{code}/", today))

    # 2 sub-partials: E-sme (製造業中小) + L-sme (専門技術業中小)
    sme_pages: list[tuple[str, str, int]] = []

    e_top = _select_e_sme(rows, top_n)
    sme_pages.append(("E-sme", "JSIC E 製造業 (中小企業)", len(e_top)))
    e_doc = _render_hub(
        "E",
        "JSIC E 製造業 (中小企業)",
        "製造業 中小企業特化",
        f"製造業 (JSIC E) のうち中小企業・小規模事業者向けの主要制度 上位{len(e_top)}件。"
        "ものづくり補助金・事業再構築補助金・省エネ・GX 関連を集約。",
        e_top,
        domain,
        "/industries/E-sme/",
    )
    path = out_dir / "E-sme" / "index.html"
    if _write_if_changed(path, e_doc):
        written += 1
    else:
        skipped += 1
    sitemap_entries.append(("/industries/E-sme/", today))

    l_top = _select_l_sme(rows, top_n)
    sme_pages.append(("L-sme", "JSIC L 専門・技術サービス業 (士業)", len(l_top)))
    l_doc = _render_hub(
        "L",
        "JSIC L 専門・技術サービス業 (士業)",
        "専門・技術サービス業 士業特化",
        f"専門・技術サービス業 (JSIC L) のうち士業 (税理士・公認会計士・社労士・弁理士 等) "
        f"向けの主要制度 上位{len(l_top)}件。",
        l_top,
        domain,
        "/industries/L-sme/",
    )
    path = out_dir / "L-sme" / "index.html"
    if _write_if_changed(path, l_doc):
        written += 1
    else:
        skipped += 1
    sitemap_entries.append(("/industries/L-sme/", today))

    # Top-level /industries/index.html
    index_doc = _render_index(code_to_count, sme_pages, domain)
    path = out_dir / "index.html"
    if _write_if_changed(path, index_doc):
        written += 1
    else:
        skipped += 1
    sitemap_entries.append(("/industries/", today))

    if sitemap_path is not None:
        _write_sitemap(sitemap_entries, sitemap_path, domain)
    return written, skipped


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB), type=Path)
    p.add_argument("--out", default=str(DEFAULT_OUT), type=Path)
    p.add_argument("--sitemap", default=str(DEFAULT_SITEMAP), type=Path)
    p.add_argument("--domain", default=DEFAULT_DOMAIN)
    p.add_argument("--top", type=int, default=DEFAULT_TOP_N)
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
