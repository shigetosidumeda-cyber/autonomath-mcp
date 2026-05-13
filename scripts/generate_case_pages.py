#!/usr/bin/env python3
"""Generate per-record SEO pages for case_studies (採択事例).

Reads `case_studies` from `data/jpintel.db` (2,286 rows at 2026-05-11) and
emits `site/cases/{case_id}.html` for each row + a sitemap-cases.xml.

Notes:
- Source corpus is mirasapo-plus.go.jp (中小企業庁 jirei-navi) — a primary
  government source, NOT an aggregator. Banned aggregators (noukaweb /
  hojyokin-portal / biz.stayway) are filtered out if encountered.
- Brand surface: jpcite only (no jpintel / AutonoMath / zeimu-kaikei.ai
  in visible HTML).
- No LLM call. Pure SQLite + Python f-string rendering.
- Idempotent: re-runs overwrite the same files; existing files are not
  deleted, only replaced.
"""

from __future__ import annotations

import html
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "jpintel.db"
OUT_DIR = REPO_ROOT / "site" / "cases"
SITEMAP_PATH = REPO_ROOT / "site" / "sitemap-cases.xml"
DOMAIN = "jpcite.com"

# Aggregator domains banned per CLAUDE.md SOT — case_studies must cite
# a primary government source. If any aggregator URL slips into the
# corpus, we skip rendering and emit a marker line.
BANNED_AGGREGATORS = (
    "noukaweb.",
    "hojyokin-portal.",
    "biz.stayway.",
    "stayway.jp",
)


def is_banned_source(url: str | None) -> bool:
    if not url:
        return False
    low = url.lower()
    return any(b in low for b in BANNED_AGGREGATORS)


def safe_html(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if isinstance(data, list):
        return [str(x) for x in data if x is not None]
    return []


def format_yen(amount: int | None) -> str:
    if amount is None or amount == 0:
        return ""
    if amount >= 100_000_000:
        oku = amount / 100_000_000
        return f"約 {oku:.1f} 億円"
    if amount >= 10_000:
        man = amount / 10_000
        return f"約 {man:,.0f} 万円"
    return f"約 {amount:,} 円"


def case_url(case_id: str) -> str:
    return f"https://{DOMAIN}/cases/{case_id}.html"


def source_domain(url: str | None) -> str:
    if not url:
        return ""
    try:
        return url.split("/")[2]
    except IndexError:
        return ""


def build_title(row: dict[str, Any]) -> str:
    company = row.get("company_name") or "事例"
    pref = row.get("prefecture") or ""
    industry = row.get("industry_name") or ""
    bits = [company]
    if pref:
        bits.append(pref)
    if industry:
        bits.append(industry)
    bits.append("採択事例")
    return " | ".join(bits) + " - jpcite"


def build_meta_description(row: dict[str, Any], programs: list[str]) -> str:
    company = row.get("company_name") or "事例"
    pref = row.get("prefecture") or ""
    industry = row.get("industry_name") or ""
    title = row.get("case_title") or ""
    parts: list[str] = []
    head = f"{company}"
    if pref:
        head += f" ({pref}"
        if industry:
            head += f"・{industry}"
        head += ")"
    elif industry:
        head += f" ({industry})"
    parts.append(head)
    if title:
        parts.append(title)
    if programs:
        parts.append("利用制度: " + "、".join(programs[:3]))
    parts.append("出典: 中小企業庁 jirei-navi。jpcite が一次資料を機械可読化。")
    desc = " / ".join(parts)
    if len(desc) > 220:
        desc = desc[:217] + "..."
    return desc


def build_jsonld(row: dict[str, Any], programs: list[str], outcomes: list[str]) -> str:
    case_id = row["case_id"]
    src = row.get("source_url") or ""
    pub = row.get("publication_date") or ""
    fetched = row.get("fetched_at") or ""
    company = row.get("company_name") or ""
    title = row.get("case_title") or f"{company} 採択事例"
    summary = row.get("case_summary") or ""
    pref = row.get("prefecture") or ""
    industry = row.get("industry_name") or ""

    headline = title if len(title) <= 110 else title[:107] + "..."
    obj: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Article",
        "@id": f"{case_url(case_id)}#article",
        "headline": headline,
        "url": case_url(case_id),
        "inLanguage": "ja",
        "isAccessibleForFree": True,
        "publisher": {
            "@type": "Organization",
            "name": "Bookyou株式会社",
            "url": f"https://{DOMAIN}",
        },
        "author": {
            "@type": "Organization",
            "name": "jpcite",
            "url": f"https://{DOMAIN}",
        },
    }
    if summary:
        obj["description"] = summary[:500]
    if pub:
        obj["datePublished"] = pub
    if fetched:
        obj["dateModified"] = fetched
    if src:
        obj["isBasedOn"] = src
        # AEO Wave 18: expand citation to a list so AI agents see both the
        # primary source (jirei-navi) and the canonical jpcite URL where
        # this fact is machine-readable.
        obj["citation"] = [
            {
                "@type": "CreativeWork",
                "name": "中小企業庁 jirei-navi (一次資料)",
                "url": src,
            },
            {
                "@type": "WebPage",
                "name": "jpcite 機械可読化レイヤー",
                "url": case_url(row.get("case_id") or ""),
            },
        ]
    about: list[dict[str, Any]] = []
    if company:
        about.append({"@type": "Organization", "name": company})
    if pref:
        about.append({"@type": "Place", "name": pref})
    if industry:
        about.append({"@type": "Thing", "name": industry})
    for p in programs[:5]:
        about.append({"@type": "GovernmentService", "name": p})
    if about:
        obj["about"] = about
    if outcomes:
        obj["mentions"] = [{"@type": "Thing", "name": o[:140]} for o in outcomes[:5]]
    return json.dumps(obj, ensure_ascii=False, indent=2)


def render_page(row: dict[str, Any]) -> str:
    case_id = row["case_id"]
    company = row.get("company_name") or "事例"
    pref = row.get("prefecture") or ""
    muni = row.get("municipality") or ""
    industry = row.get("industry_name") or ""
    industry_jsic = row.get("industry_jsic") or ""
    title_h1 = row.get("case_title") or f"{company} 採択事例"
    summary = row.get("case_summary") or ""
    excerpt = row.get("source_excerpt") or ""
    employees = row.get("employees")
    founded = row.get("founded_year")
    capital = row.get("capital_yen")
    subsidy = row.get("total_subsidy_received_yen")
    pub_date = row.get("publication_date") or ""
    fetched = row.get("fetched_at") or ""
    src_url = row.get("source_url") or ""
    houjin = row.get("houjin_bangou") or ""
    is_sole = bool(row.get("is_sole_proprietor"))

    programs = parse_json_list(row.get("programs_used_json"))
    outcomes = parse_json_list(row.get("outcomes_json"))
    patterns = parse_json_list(row.get("patterns_json"))

    page_title = build_title(row)
    meta_desc = build_meta_description(row, programs)
    canonical = case_url(case_id)
    jsonld = build_jsonld(row, programs, outcomes)
    sdomain = source_domain(src_url)

    # Build body sections
    def li(text: str) -> str:
        return f"<li>{safe_html(text)}</li>"

    programs_html = ""
    if programs:
        programs_html = (
            "<section aria-labelledby='programs-title'>"
            "<h2 id='programs-title'>利用制度</h2>"
            "<ul class='programs-list'>" + "".join(li(p) for p in programs) + "</ul></section>"
        )

    outcomes_html = ""
    if outcomes:
        outcomes_html = (
            "<section aria-labelledby='outcomes-title'>"
            "<h2 id='outcomes-title'>成果・効果</h2>"
            "<ul class='outcomes-list'>" + "".join(li(o) for o in outcomes) + "</ul></section>"
        )

    patterns_html = ""
    if patterns:
        patterns_html = (
            "<section aria-labelledby='patterns-title'>"
            "<h2 id='patterns-title'>取り組みパターン</h2>"
            "<ul class='patterns-list'>" + "".join(li(p) for p in patterns) + "</ul></section>"
        )

    meta_rows: list[str] = []
    if pref:
        meta_rows.append(f"<dt>所在地</dt><dd>{safe_html(pref)}{safe_html(muni)}</dd>")
    if industry:
        ind_label = industry
        if industry_jsic:
            ind_label += f" (JSIC {industry_jsic})"
        meta_rows.append(f"<dt>業種</dt><dd>{safe_html(ind_label)}</dd>")
    if employees is not None:
        meta_rows.append(f"<dt>従業員数</dt><dd>{safe_html(employees)} 名</dd>")
    if founded:
        meta_rows.append(f"<dt>設立</dt><dd>{safe_html(founded)} 年</dd>")
    if capital:
        meta_rows.append(f"<dt>資本金</dt><dd>{format_yen(capital)}</dd>")
    if subsidy:
        meta_rows.append(f"<dt>受給額 (累計)</dt><dd>{format_yen(subsidy)}</dd>")
    if houjin:
        meta_rows.append(f"<dt>法人番号</dt><dd><code>{safe_html(houjin)}</code></dd>")
    if is_sole:
        meta_rows.append("<dt>事業形態</dt><dd>個人事業主</dd>")
    if pub_date:
        meta_rows.append(f"<dt>公表日</dt><dd>{safe_html(pub_date)}</dd>")
    meta_dl = "<dl class='program-meta'>" + "".join(meta_rows) + "</dl>" if meta_rows else ""

    summary_html = (
        f"<section aria-labelledby='summary-title'>"
        f"<h2 id='summary-title'>概要</h2><p>{safe_html(summary)}</p></section>"
        if summary
        else ""
    )

    excerpt_html = ""
    if excerpt and excerpt != summary:
        excerpt_html = (
            "<section aria-labelledby='excerpt-title'>"
            "<h2 id='excerpt-title'>出典抜粋</h2>"
            f"<blockquote class='source-excerpt'>{safe_html(excerpt)}</blockquote>"
            "<p class='muted'>※上記は出典ページからの抜粋です。著作権は出典元に帰属します。"
            "</p></section>"
        )

    source_html = (
        "<section aria-labelledby='source-title'>"
        "<h2 id='source-title'>出典</h2>"
        "<p>本ページの内容は以下の一次出典に基づきます。最新の事例情報は出典ページから確認してください。</p>"
    )
    if src_url:
        source_html += (
            f"<p><a class='primary-link' rel='external nofollow noopener' href='{safe_html(src_url)}'>"
            f"{safe_html(sdomain or '出典ページ')} を開く</a></p>"
        )
    if fetched:
        source_html += f"<p class='muted'>出典取得: {safe_html(fetched)}</p>"
    source_html += "</section>"

    api_html = (
        "<section aria-labelledby='api-title'>"
        "<h2 id='api-title'>API で取得</h2>"
        "<p>本事例の機械可読データは REST / MCP の両方で取得できます。</p>"
        f"<pre class='code-block'><code>curl -H \"X-API-Key: YOUR_API_KEY\" \\\n"
        f'  "https://api.{DOMAIN}/v1/cases/{safe_html(case_id)}"</code></pre>'
        "<p>MCP クライアント (Claude Desktop / Cursor / Cline 等) では "
        f"<code>similar_cases(case_id=&quot;{safe_html(case_id)}&quot;)</code> "
        "で類似事例を取得できます。詳細は <a href='/docs/api-reference'>API リファレンス</a>。"
        "</p>"
        "<p class='api-cta-line'>無料 3 リクエスト/日 (匿名 IP)。<a href='/pricing.html'>料金</a> ・ "
        "<a href='/dashboard.html'>API キー発行</a></p>"
        "</section>"
    )

    # AEO Wave 18: explicit "Cite this in AI" block so AI agents pick the
    # canonical jpcite URL when surfacing this fact in a generated answer.
    cite_url_short = f"{DOMAIN}/cases/{case_id}"
    cite_block_html = (
        "<section aria-labelledby='cite-title' class='cite-this-section'>"
        "<h2 id='cite-title'>Cite this in AI / 引用</h2>"
        "<p>AI に本事例を引用させる時の canonical URL です。"
        f"出典 (jpcite) の明記をお願いします。一次資料は "
        f"{'<a href=' + chr(39) + safe_html(src_url) + chr(39) + ' rel=' + chr(39) + 'external nofollow noopener' + chr(39) + '>中小企業庁 jirei-navi</a>' if src_url else '中小企業庁 jirei-navi'}"
        "。</p>"
        "<pre class='code-block cite-block'><code>"
        f"&gt; {safe_html(title_h1)} "
        f"(出典: https://{safe_html(cite_url_short)}、jpcite が中小企業庁 jirei-navi 一次資料を機械可読化)"
        "</code></pre>"
        "<p class='muted'>"
        f"<button type='button' class='copy-cite-btn' data-cite-url='https://{safe_html(cite_url_short)}' "
        f"onclick=\"navigator.clipboard&amp;&amp;navigator.clipboard.writeText('https://{safe_html(cite_url_short)}')\">"
        "URL をコピー</button> "
        f"<a href='https://{safe_html(cite_url_short)}'>https://{safe_html(cite_url_short)}</a>"
        "</p>"
        "</section>"
    )

    # Append cite block onto api_html so both surfaces (developer +
    # citation) appear together in the rendered article.
    api_html = api_html + cite_block_html

    breadcrumb_pref = ""
    if pref:
        breadcrumb_pref = f"<a href='/prefectures/'>{safe_html(pref)}</a> &rsaquo; "

    common_jsonld = """  <script type="application/ld+json" data-jpcite-jsonld="common">{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "@id": "https://jpcite.com/#org",
      "name": "Bookyou株式会社",
      "legalName": "Bookyou株式会社",
      "url": "https://jpcite.com",
      "logo": "https://jpcite.com/_assets/logo.svg",
      "address": {
        "@type": "PostalAddress",
        "streetAddress": "小日向2-22-1",
        "addressLocality": "文京区",
        "addressRegion": "東京都",
        "postalCode": "112-0006",
        "addressCountry": "JP"
      },
      "contactPoint": {
        "@type": "ContactPoint",
        "email": "info@bookyou.net",
        "contactType": "customer support",
        "availableLanguage": ["ja", "en"]
      },
      "identifier": [
        {"@type": "PropertyValue", "propertyID": "jp-corporate-number", "value": "8010001213708"},
        {"@type": "PropertyValue", "propertyID": "jp-qualified-invoice-number", "value": "T8010001213708"}
      ]
    },
    {
      "@type": "WebSite",
      "@id": "https://jpcite.com/#site",
      "name": "jpcite",
      "url": "https://jpcite.com",
      "inLanguage": "ja",
      "publisher": {"@id": "https://jpcite.com/#org"}
    }
  ]
}</script>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="theme-color" content="#ffffff">
<title>{safe_html(page_title)}</title>
<meta name="description" content="{safe_html(meta_desc)}">
<meta name="author" content="jpcite">
<meta name="publisher" content="jpcite">
<meta name="robots" content="index, follow, max-image-preview:large">

<meta property="og:title" content="{safe_html(page_title)}">
<meta property="og:description" content="{safe_html(meta_desc)}">
<meta property="og:type" content="article">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="https://{DOMAIN}/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="ja_JP">
<meta property="og:site_name" content="jpcite">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{safe_html(page_title)}">
<meta name="twitter:description" content="{safe_html(meta_desc)}">
<meta name="twitter:image" content="https://{DOMAIN}/assets/og-twitter.png">

<link rel="canonical" href="{canonical}">
<link rel="alternate" hreflang="ja" href="{canonical}">
<link rel="alternate" hreflang="x-default" href="{canonical}">
<link rel="icon" href="/assets/favicon-v2.svg" type="image/svg+xml">
<link rel="icon" href="/assets/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/assets/favicon-16.png" sizes="16x16" type="image/png">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
<link rel="stylesheet" href="/styles.css?v=20260428a">

<script type="application/ld+json">
{jsonld}
</script>
{common_jsonld}
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" data-jpcite-a11y="baseline">
  <link rel="manifest" href="/manifest.webmanifest">
</head>
<body>
<a href="#main" class="skip-link">本文へスキップ</a>

<header class="site-header" role="banner">
 <div class="container header-inner">
 <a class="brand" href="/" aria-label="jpcite ホーム">
 <picture><source media="(prefers-color-scheme: dark)" srcset="/assets/brand/lockup-transparent-600-lightlogo.png 1x, /assets/brand/lockup-transparent-1200-lightlogo.png 2x"><img src="/assets/brand/lockup-transparent-600-darklogo.png" srcset="/assets/brand/lockup-transparent-600-darklogo.png 1x, /assets/brand/lockup-transparent-1200-darklogo.png 2x" alt="jpcite" height="32" style="height:32px;width:auto;display:block;"></picture>
 </a>
 <nav class="site-nav" aria-label="主要ナビゲーション">
 <a href="/about.html">運営について</a>
 <a href="/products.html">プロダクト</a>
 <a href="/docs/">ドキュメント</a>
 <a href="/pricing.html">料金</a>
 <a href="/audiences/">利用者層</a>
 </nav>
 </div>
</header>

<main id="main" class="program-page">
 <div class="container">

 <nav class="breadcrumb" aria-label="パンくず">
 <a href="/">ホーム</a> &rsaquo;
 <a href="/cases/">採択事例</a> &rsaquo;
 {breadcrumb_pref}<span aria-current="page">{safe_html(company)}</span>
 </nav>

 <article>
 <header class="program-header">
 <h1>{safe_html(title_h1)}</h1>
 <p class="byline">
 <span class="company">{safe_html(company)}</span>
 {f"<span class='sep'>/</span><span class='source'>出典: <a href='{safe_html(src_url)}' rel='external nofollow noopener'>{safe_html(sdomain)}</a></span>" if src_url else ""}
 {f"<span class='sep'>/</span><span class='updated'>出典取得: {safe_html(fetched)}</span>" if fetched else ""}
 </p>
 <p class="byline-note muted">※採択事例は中小企業庁 jirei-navi の公表データを基に jpcite が機械可読化したものです。事例の最新情報は出典ページをご確認ください。</p>
 </header>

 {meta_dl}
 {summary_html}
 {programs_html}
 {outcomes_html}
 {patterns_html}
 {excerpt_html}
 {source_html}
 {api_html}

 <p class="disclaimer">本ページは自動生成された採択事例データのプレビューであり、法的助言・税務助言・申請代行を構成するものではありません。事例企業の現状や制度の最新内容は所管官公庁・自治体の一次情報を必ず確認してください。</p>
 </article>

 </div>
</main>

<footer class="site-footer" role="contentinfo">
 <div class="container footer-inner">
 <div class="footer-col">
 <p class="footer-brand">jpcite</p>
 <p class="footer-tag">日本の制度 API</p>
 <p class="footer-entity">制度データ提供: jpcite</p>
 </div>
 <nav class="footer-nav" aria-label="フッター 法務・連絡">
 <a href="/tos.html">利用規約</a>
 <a href="/privacy.html">プライバシー</a>
 <a href="/tokushoho.html">特定商取引法</a>
 <a href="/docs/faq/">ヘルプ</a>
 </nav>
 <nav class="footer-nav footer-nav-axes" aria-label="フッター 横断軸">
 <a href="/industries/" hreflang="ja">業種別</a>
 <a href="/qa/" hreflang="ja">Q&amp;A</a>
 <a href="/compare.html" hreflang="ja">比較</a>
 <a href="/prefectures/" hreflang="ja">都道府県別</a>
 </nav>
 <p class="footer-copy">&copy; 2026 jpcite</p>
 <p class="footer-disclaimer muted">本サイトは税理士法 §52 が規定する税務代理・税務書類作成・税務相談の提供を行いません。個別の税務判断は税理士・社労士・中小企業診断士等の有資格者にご相談ください。</p>
 </div>
</footer>

</body>
</html>
"""


def render_sitemap(case_ids: list[tuple[str, str | None]]) -> str:
    today = datetime.now(UTC).date().isoformat()
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for case_id, fetched in case_ids:
        lastmod = (fetched or "").split("T")[0] or today
        lines.append("  <url>")
        lines.append(f"    <loc>{case_url(case_id)}</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("    <changefreq>monthly</changefreq>")
        lines.append("    <priority>0.5</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def write_marker_page() -> None:
    """When DB is unavailable, drop one marker page so deploy paths don't 404."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat()
    marker = OUT_DIR / "_unavailable.html"
    marker.write_text(
        "<!DOCTYPE html>\n"
        "<html lang='ja'><head><meta charset='UTF-8'>"
        "<title>採択事例 - データ取得中 - jpcite</title>"
        "<meta name='robots' content='noindex'>"
        f"<!-- generated_at = data unavailable @ {stamp} -->"
        "</head><body><p>採択事例データは現在再構築中です。</p></body></html>\n",
        encoding="utf-8",
    )


def main() -> int:
    if not DB_PATH.exists() or DB_PATH.stat().st_size < 1_000_000:
        print(f"[WARN] DB not available at {DB_PATH} (size < 1MB). Writing marker page only.")
        write_marker_page()
        SITEMAP_PATH.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            "</urlset>\n",
            encoding="utf-8",
        )
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM case_studies ORDER BY case_id")
    rows = cur.fetchall()
    conn.close()

    total = len(rows)
    written = 0
    skipped_banned = 0
    sitemap_entries: list[tuple[str, str | None]] = []

    for r in rows:
        row = dict(r)
        case_id = row.get("case_id")
        if not case_id:
            continue
        if is_banned_source(row.get("source_url")):
            skipped_banned += 1
            continue
        # Sanitize filename — case_id is opaque (e.g. mirasapo_case_118)
        safe_id = "".join(c for c in case_id if c.isalnum() or c in "-_")
        if not safe_id:
            continue
        out_path = OUT_DIR / f"{safe_id}.html"
        page = render_page(row)
        out_path.write_text(page, encoding="utf-8")
        sitemap_entries.append((safe_id, row.get("fetched_at")))
        written += 1

    SITEMAP_PATH.write_text(render_sitemap(sitemap_entries), encoding="utf-8")

    print(f"[OK] case_studies rows: {total}")
    print(f"[OK] pages written:     {written}")
    print(f"[OK] skipped (banned):  {skipped_banned}")
    print(f"[OK] sitemap entries:   {len(sitemap_entries)} -> {SITEMAP_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
