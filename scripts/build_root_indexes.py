#!/usr/bin/env python3
"""
Build root index pages for /cases/, /laws/, /enforcement/.

Scans titles of existing static pages under site/{cases,laws,enforcement}/,
groups by prefecture/category/ministry respectively, emits three index.html
files with Schema.org JSON-LD (DataCatalog/Dataset/CollectionPage/BreadcrumbList
+ Legislation for laws), canonical, hreflang, OGP, twitter:card.

No external dependencies; reads only filesystem.
"""
from __future__ import annotations

import datetime
import html
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/shigetoumeda/jpcite/site")
CASES_DIR = ROOT / "cases"
LAWS_DIR = ROOT / "laws"
ENFORCEMENT_DIR = ROOT / "enforcement"

PREF_ORDER = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
    "岐阜県", "静岡県", "愛知県", "三重県",
    "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県",
    "沖縄県",
]

PREF_SET = set(PREF_ORDER)

LAW_CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    # order matters: more specific first
    ("憲法", "憲法"),
    ("施行令", "政令"),
    ("施行規則", "省令"),
    ("施行規程", "省令"),
    ("通達", "通達"),
    ("告示", "告示"),
    ("要綱", "要綱"),
    ("内閣府令", "府令"),
    ("府令", "府令"),
    ("省令", "省令"),
    ("政令", "政令"),
    ("命令", "命令"),
    ("規則", "規則"),
    ("条例", "条例"),
    ("法律", "法律"),
    ("法", "法律"),
]

CATEGORY_ORDER = [
    "憲法", "法律", "政令", "府令", "省令", "命令", "規則", "通達", "告示", "要綱", "条例", "その他"
]


def slurp_title(path: Path) -> str:
    """Read just enough to extract <title>...</title>; fast (no full parse)."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(4096)
    except Exception:
        return ""
    m = re.search(r"<title>(.*?)</title>", head, re.DOTALL)
    return m.group(1).strip() if m else ""


# ---------- /cases/ ----------
PREF_TITLE_RE = re.compile(r"\|\s*([^|]+?)\s*\|")


def case_pref(title: str) -> str:
    for m in PREF_TITLE_RE.finditer(title):
        token = m.group(1).strip()
        if token in PREF_SET:
            return token
    return "不明"


def case_company(title: str) -> str:
    head = title.split("|", 1)[0].strip()
    return head or "—"


def build_cases_groups() -> dict:
    files = sorted(p.name for p in CASES_DIR.glob("mirasapo_case_*.html"))
    pref_buckets: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for fname in files:
        title = slurp_title(CASES_DIR / fname)
        pref = case_pref(title)
        company = case_company(title)
        case_id = fname[:-5]  # strip .html
        pref_buckets[pref].append((case_id, company, title))
    return {
        "total": len(files),
        "buckets": pref_buckets,
    }


# ---------- /laws/ ----------
TITLE_PREFIX_RE = re.compile(r"^(.*?)\s*(?:\((\d{4}-\d{2}-\d{2})\s*施行\))?\s*[—\-]")


def law_category(name: str) -> str:
    """Pick category by suffix on Japanese name (before the parenthesis)."""
    base = name.strip()
    base = re.sub(r"\s*\([^)]*\)\s*$", "", base)
    for kw, cat in LAW_CATEGORY_KEYWORDS:
        if base.endswith(kw):
            return cat
    # fallback: scan for any keyword
    for kw, cat in LAW_CATEGORY_KEYWORDS:
        if kw in base:
            return cat
    return "その他"


def parse_law_title(title: str) -> tuple[str, str]:
    """Return (japanese_name, slug-friendly-display-date)."""
    m = TITLE_PREFIX_RE.match(title)
    if m:
        name = m.group(1).strip()
        date = m.group(2) or ""
        return name, date
    head = title.split("—", 1)[0].strip()
    return head, ""


def build_laws_groups() -> dict:
    files = sorted(p.name for p in LAWS_DIR.glob("*.html") if p.name != "index.html")
    cat_buckets: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for fname in files:
        title = slurp_title(LAWS_DIR / fname)
        name, date = parse_law_title(title)
        if not name:
            continue
        cat = law_category(name)
        slug = fname[:-5]
        cat_buckets[cat].append((slug, name, date))
    return {
        "total": len(files),
        "buckets": cat_buckets,
    }


# ---------- /enforcement/ ----------
MINISTRY_HINTS = [
    ("金融庁", "金融庁"),
    ("消費者庁", "消費者庁"),
    ("公正取引委員会", "公正取引委員会"),
    ("出入国在留管理庁", "出入国在留管理庁"),
    ("中小企業庁", "経済産業省 中小企業庁"),
    ("関東農政局", "農林水産省 関東農政局"),
    ("近畿農政局", "農林水産省 近畿農政局"),
    ("東北農政局", "農林水産省 東北農政局"),
    ("北海道農政事務所", "農林水産省 北海道農政事務所"),
    ("中国四国農政局", "農林水産省 中国四国農政局"),
    ("九州農政局", "農林水産省 九州農政局"),
    ("北陸農政局", "農林水産省 北陸農政局"),
    ("東海農政局", "農林水産省 東海農政局"),
    ("農林水産省", "農林水産省"),
    ("関東運輸局", "国土交通省 関東運輸局"),
    ("中部運輸局", "国土交通省 中部運輸局"),
    ("近畿運輸局", "国土交通省 近畿運輸局"),
    ("北海道運輸局", "国土交通省 北海道運輸局"),
    ("東北運輸局", "国土交通省 東北運輸局"),
    ("中国運輸局", "国土交通省 中国運輸局"),
    ("四国運輸局", "国土交通省 四国運輸局"),
    ("九州運輸局", "国土交通省 九州運輸局"),
    ("北陸信越運輸局", "国土交通省 北陸信越運輸局"),
    ("沖縄総合事務局", "沖縄総合事務局運輸部"),
    ("航空局", "国土交通省 航空局"),
    ("鉄道局", "国土交通省 鉄道局"),
    ("国土交通省", "国土交通省"),
    ("厚生労働省", "厚生労働省"),
    ("経済産業省", "経済産業省"),
    ("関東財務局", "関東財務局"),
    ("近畿財務局", "近畿財務局"),
    ("東京証券取引所", "東京証券取引所"),
    ("PMDA", "医薬品医療機器総合機構（PMDA）"),
    ("総合通信局", "総合通信局"),
    ("総務省", "総務省"),
    ("文部科学省", "文部科学省"),
    ("環境省", "環境省"),
    ("防衛省", "防衛省"),
    ("外務省", "外務省"),
    ("法務省", "法務省"),
    ("東京都", "東京都"),
    ("大阪府", "大阪府"),
    ("大阪市", "大阪市"),
]

ENF_DESC_RE = re.compile(r'meta name="description" content="所管:\s*([^。"]+)')


def enf_ministry(html_head: str) -> str:
    m = ENF_DESC_RE.search(html_head)
    if m:
        return m.group(1).strip()
    for kw, label in MINISTRY_HINTS:
        if kw in html_head:
            return label
    return "その他"


def slurp_head(path: Path, n_bytes: int = 6000) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return f.read(n_bytes)
    except Exception:
        return ""


def build_enforcement_groups() -> dict:
    # Two filename conventions: act-*.html (MAFF/MLIT/FSA/etc.) and
    # case-jbaudit-*.html (会計検査院 r03 検査結果) — both live in /enforcement/.
    files = sorted(
        p.name for p in ENFORCEMENT_DIR.glob("*.html")
        if p.name != "index.html"
    )
    min_buckets: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for fname in files:
        head = slurp_head(ENFORCEMENT_DIR / fname)
        m = re.search(r"<title>(.*?)</title>", head, re.DOTALL)
        title = m.group(1).strip() if m else fname
        # Strip the standard suffix " 行政処分 — ..." or " | jpcite" to
        # leave just the subject entity name.
        name_part = title.split(" 行政処分", 1)[0]
        name_part = name_part.split(" — ", 1)[0]
        name_part = name_part.split(" | ", 1)[0].strip()
        # JBAudit pages have title like "会計検査院 検査結果 ..." — fall back
        # gracefully when no entity is parseable.
        if not name_part:
            name_part = fname[:-5]
        ministry = "会計検査院" if fname.startswith("case-jbaudit") else enf_ministry(head)
        slug = fname[:-5]
        min_buckets[ministry].append((slug, name_part, title))
    return {
        "total": len(files),
        "buckets": min_buckets,
    }


# ---------- HTML emitters ----------

NOW_ISO = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
NOW_DATE = datetime.datetime.utcnow().strftime("%Y-%m-%d")

COMMON_HEAD_TAIL = """<link rel="icon" href="/assets/favicon-v2.svg" type="image/svg+xml">
<link rel="stylesheet" href="/styles.css?v=20260511a">
"""

ORG_JSONLD = {
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
        "addressCountry": "JP",
    },
    "identifier": [
        {"@type": "PropertyValue", "propertyID": "jp-corporate-number", "value": "8010001213708"},
        {"@type": "PropertyValue", "propertyID": "jp-qualified-invoice-number", "value": "T8010001213708"},
    ],
}

SITE_JSONLD = {
    "@type": "WebSite",
    "@id": "https://jpcite.com/#site",
    "name": "jpcite",
    "url": "https://jpcite.com",
    "inLanguage": "ja",
    "publisher": {"@id": "https://jpcite.com/#org"},
}


def he(s: str) -> str:
    return html.escape(s or "", quote=True)


def header_html(*, brand_active: str = "") -> str:
    return """<header class="site-header" role="banner">
 <div class="container header-inner">
 <a class="brand" href="/" aria-label="jpcite ホーム">jpcite</a>
 <nav class="site-nav" aria-label="主要ナビゲーション">
 <a href="/about.html">運営について</a>
 <a href="/products.html">プロダクト</a>
 <a href="/docs/">ドキュメント</a>
 <a href="/pricing.html">料金</a>
 </nav>
 </div>
</header>
"""


FOOTER_HTML = """<footer class="site-footer" role="contentinfo">
 <div class="container footer-inner">
 <div class="footer-col">
 <p class="footer-brand">jpcite</p>
 <p class="footer-tag">日本の制度 API</p>
 </div>
 <nav class="footer-nav" aria-label="フッター 法務・連絡">
 <a href="/tos.html">利用規約</a>
 <a href="/privacy.html">プライバシー</a>
 <a href="/tokushoho.html">特定商取引法</a>
 <a href="/about.html">運営情報</a>
 </nav>
 <p class="footer-copy">&copy; 2026 jpcite</p>
 <p class="footer-disclaimer muted">本サイトは税理士法 §52 が規定する税務代理・税務書類作成・税務相談の提供を行いません。個別の税務判断は税理士・社労士・中小企業診断士等の有資格者にご相談ください。</p>
 </div>
</footer>
"""


def page_head(title: str, description: str, canonical: str, page_kind: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#ffffff">
<title>{he(title)}</title>
<meta name="description" content="{he(description)}">
<meta name="author" content="jpcite">
<meta name="publisher" content="jpcite">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta property="og:title" content="{he(title)}">
<meta property="og:description" content="{he(description)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{he(canonical)}">
<meta property="og:image" content="https://jpcite.com/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="ja_JP">
<meta property="og:site_name" content="jpcite">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{he(title)}">
<meta name="twitter:description" content="{he(description)}">
<meta name="twitter:image" content="https://jpcite.com/assets/og-twitter.png">
<link rel="canonical" href="{he(canonical)}">
<link rel="alternate" hreflang="ja" href="{he(canonical)}">
<link rel="alternate" hreflang="en" href="{he(canonical.replace('jpcite.com/', 'jpcite.com/en/'))}">
<link rel="alternate" hreflang="x-default" href="{he(canonical)}">
{COMMON_HEAD_TAIL}"""


def jsonld_block(graph: list[dict]) -> str:
    doc = {"@context": "https://schema.org", "@graph": graph}
    return f'<script type="application/ld+json">{json.dumps(doc, ensure_ascii=False, separators=(",", ":"))}</script>\n'


# ---------- /cases/index.html ----------

def render_cases_index(data: dict) -> str:
    total = data["total"]
    buckets = data["buckets"]
    ordered_prefs = [p for p in PREF_ORDER if p in buckets]
    extras = sorted([p for p in buckets if p not in PREF_SET])
    pref_seq = ordered_prefs + extras

    # JSON-LD
    breadcrumb = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": "https://jpcite.com/"},
            {"@type": "ListItem", "position": 2, "name": "採択事例", "item": "https://jpcite.com/cases/"},
        ],
    }
    dataset = {
        "@type": "Dataset",
        "@id": "https://jpcite.com/cases/#dataset",
        "name": "日本の中小企業 採択事例 (jpcite)",
        "description": (
            f"日本の中小企業 採択事例 {total:,} 件 を都道府県別にロールアップ。"
            "出典は中小企業庁 mirasapo / jirei-navi 等の一次資料。"
        ),
        "creator": {"@id": "https://jpcite.com/#org"},
        "publisher": {"@id": "https://jpcite.com/#org"},
        "url": "https://jpcite.com/cases/",
        "isAccessibleForFree": True,
        "license": "https://www.digital.go.jp/resources/open_data",
        "keywords": "採択事例, 補助金, 中小企業, jpcite",
        "variableMeasured": ["company_name", "prefecture", "industry", "subsidy_program"],
        "spatialCoverage": {"@type": "Country", "name": "Japan"},
        "inLanguage": "ja",
        "datePublished": "2026-05-11",
        "size": f"{total:,} records",
    }
    catalog = {
        "@type": "DataCatalog",
        "@id": "https://jpcite.com/cases/#catalog",
        "name": "jpcite 採択事例 カタログ",
        "publisher": {"@id": "https://jpcite.com/#org"},
        "dataset": {"@id": "https://jpcite.com/cases/#dataset"},
    }
    collection = {
        "@type": "CollectionPage",
        "@id": "https://jpcite.com/cases/#page",
        "name": f"日本の中小企業 採択事例 {total:,} 件",
        "url": "https://jpcite.com/cases/",
        "inLanguage": "ja",
        "isPartOf": {"@id": "https://jpcite.com/#site"},
    }
    jsonld = jsonld_block([ORG_JSONLD, SITE_JSONLD, catalog, dataset, collection, breadcrumb])

    title = f"日本の中小企業 採択事例 {total:,} 件 — jpcite"
    description = (
        f"日本の中小企業 採択事例 {total:,} 件 を都道府県別にインデックス化。"
        "出典は中小企業庁 mirasapo / jirei-navi 等の一次資料。jpcite が機械可読化。"
    )

    head = page_head(title, description, "https://jpcite.com/cases/", "cases")

    # body
    parts: list[str] = []
    parts.append(head)
    parts.append(jsonld)
    parts.append('</head>\n<body>\n')
    parts.append('<a href="#main" class="skip-link">本文へスキップ</a>\n')
    parts.append(header_html())
    parts.append('<main id="main" class="cases-index">\n <div class="container">\n')
    parts.append(
        '<nav class="breadcrumb" aria-label="パンくず">'
        '<a href="/">ホーム</a> &rsaquo; <span aria-current="page">採択事例</span></nav>\n'
    )
    parts.append('<article>\n<header>\n')
    parts.append(f'<h1>日本の中小企業 採択事例 {total:,} 件 (jpcite)</h1>\n')
    parts.append(
        f'<p class="byline"><span class="updated">生成日時: {NOW_ISO}</span> '
        f'<span class="sep">/</span> <span class="author">jpcite</span></p>\n'
    )
    parts.append('</header>\n')
    parts.append(
        '<aside class="disclaimer-block" role="note" aria-label="重要な注意事項" '
        'style="border:1px solid #ccc;padding:12px;margin:16px 0;background:#fafafa;">'
        '<p><strong>概要:</strong> 政府が公表した中小企業の補助金採択事例を、'
        '都道府県別に集計したインデックスです。一次資料 URL は各事例ページに掲載。</p></aside>\n'
    )

    # Summary section
    parts.append('<section class="summary">\n<h2>収録概要</h2>\n')
    parts.append('<ul>\n')
    parts.append(f'<li>収録件数: <strong>{total:,}</strong> 件</li>\n')
    parts.append(f'<li>都道府県カバー: <strong>{len([p for p in pref_seq if p in PREF_SET])}</strong> / 47</li>\n')
    parts.append('<li>出典: 中小企業庁 mirasapo / jirei-navi 等 (一次資料 URL 完全保持)</li>\n')
    parts.append('<li>ライセンス: 政府標準利用規約 v2.0 (CC-BY 互換)</li>\n')
    parts.append('</ul>\n</section>\n')

    # Index of prefectures (anchor TOC)
    parts.append('<nav class="pref-toc" aria-label="都道府県インデックス">\n<h2>都道府県別 一覧</h2>\n<ul class="pref-list">\n')
    for pref in pref_seq:
        n = len(buckets[pref])
        anchor = f"pref-{abs(hash(pref))%999999:06d}"
        parts.append(f'<li><a href="#{anchor}">{he(pref)} ({n:,})</a></li>\n')
    parts.append('</ul>\n</nav>\n')

    # Per-prefecture sections
    for pref in pref_seq:
        rows = buckets[pref]
        n = len(rows)
        anchor = f"pref-{abs(hash(pref))%999999:06d}"
        parts.append(f'<section id="{anchor}" class="pref-section">\n')
        parts.append(f'<h3>{he(pref)} <span class="count">({n:,} 件)</span></h3>\n')
        parts.append('<ol class="case-top5">\n')
        for case_id, company, _title in rows[:5]:
            parts.append(
                f'<li><a href="/cases/{he(case_id)}.html">{he(company)}</a></li>\n'
            )
        parts.append('</ol>\n')
        if n > 5:
            parts.append(
                f'<p class="more-link"><a href="/search?q=&prefecture={he(pref)}">'
                f'{he(pref)} の全 {n:,} 件を検索</a></p>\n'
            )
        parts.append('</section>\n')

    # API CTA
    parts.append(
        '<section class="api-cta">\n<h2>API で取得</h2>\n'
        '<p>本ページの全件データは REST / MCP の両方で取得できます。</p>\n'
        '<pre class="code-block"><code>curl -H "X-API-Key: YOUR_API_KEY" \\\n'
        ' "https://api.jpcite.com/v1/cases?prefecture=東京都"</code></pre>\n'
        '<p>MCP クライアントからは <code>similar_cases(...)</code> で呼べます。'
        '詳細は <a href="/docs/">API reference</a> 参照。</p>\n'
        '<p class="api-cta-line">無料 3 リクエスト/日。'
        '<a href="/pricing.html">料金体系</a> · '
        '<a href="/pricing.html#api-paid">API キー発行</a> · '
        '<a href="/dashboard.html">既存キー管理</a></p>\n</section>\n'
    )

    parts.append(
        '<p class="disclaimer">本ページは政府公表記録から機械生成された一覧で、'
        '法的助言・税務助言・調査報告を構成するものではありません。最新情報は'
        '所管官公庁の一次情報を必ず確認してください。</p>\n'
    )
    parts.append('</article>\n </div>\n</main>\n')
    parts.append(FOOTER_HTML)
    parts.append('</body>\n</html>\n')
    return "".join(parts)


# ---------- /laws/index.html ----------

def render_laws_index(data: dict) -> str:
    total = data["total"]
    buckets = data["buckets"]
    cat_seq = [c for c in CATEGORY_ORDER if c in buckets]
    extras = [c for c in buckets if c not in set(CATEGORY_ORDER)]
    cat_seq = cat_seq + extras

    breadcrumb = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": "https://jpcite.com/"},
            {"@type": "ListItem", "position": 2, "name": "法令", "item": "https://jpcite.com/laws/"},
        ],
    }
    dataset = {
        "@type": "Dataset",
        "@id": "https://jpcite.com/laws/#dataset",
        "name": "日本の法令 (jpcite / e-Gov CC-BY)",
        "description": (
            f"日本の法令 {total:,} 件を 法令種別 (憲法 / 法律 / 政令 / 省令 / 規則 等) 別にインデックス化。"
            "出典は e-Gov 法令検索 (CC-BY 4.0)。"
        ),
        "creator": {"@id": "https://jpcite.com/#org"},
        "publisher": {"@id": "https://jpcite.com/#org"},
        "url": "https://jpcite.com/laws/",
        "isAccessibleForFree": True,
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "keywords": "法令, 法律, 政令, 省令, 規則, e-Gov, jpcite",
        "spatialCoverage": {"@type": "Country", "name": "Japan"},
        "inLanguage": "ja",
        "datePublished": "2026-05-11",
        "size": f"{total:,} records",
    }
    catalog = {
        "@type": "DataCatalog",
        "@id": "https://jpcite.com/laws/#catalog",
        "name": "jpcite 法令カタログ",
        "publisher": {"@id": "https://jpcite.com/#org"},
        "dataset": {"@id": "https://jpcite.com/laws/#dataset"},
    }
    legislation = {
        "@type": "Legislation",
        "@id": "https://jpcite.com/laws/#legislation",
        "name": "日本の法令体系 (e-Gov CC-BY)",
        "legislationJurisdiction": {"@type": "Country", "name": "Japan"},
        "legislationType": "Compilation",
        "inLanguage": "ja",
        "isPartOf": {"@id": "https://jpcite.com/laws/#dataset"},
        "url": "https://elaws.e-gov.go.jp/",
    }
    collection = {
        "@type": "CollectionPage",
        "@id": "https://jpcite.com/laws/#page",
        "name": f"日本の法令 {total:,} 件",
        "url": "https://jpcite.com/laws/",
        "inLanguage": "ja",
        "isPartOf": {"@id": "https://jpcite.com/#site"},
    }
    jsonld = jsonld_block([ORG_JSONLD, SITE_JSONLD, catalog, dataset, legislation, collection, breadcrumb])

    title = f"日本の法令 {total:,} 件 (e-Gov CC-BY) — jpcite"
    description = (
        f"日本の法令 {total:,} 件を 憲法 / 法律 / 政令 / 省令 / 規則 別にインデックス化。"
        "出典は e-Gov 法令検索 (CC-BY 4.0)。jpcite が機械可読化。"
    )

    head = page_head(title, description, "https://jpcite.com/laws/", "laws")

    parts: list[str] = []
    parts.append(head)
    parts.append(jsonld)
    parts.append('</head>\n<body>\n')
    parts.append('<a href="#main" class="skip-link">本文へスキップ</a>\n')
    parts.append(header_html())
    parts.append('<main id="main" class="laws-index">\n <div class="container">\n')
    parts.append(
        '<nav class="breadcrumb" aria-label="パンくず">'
        '<a href="/">ホーム</a> &rsaquo; <span aria-current="page">法令</span></nav>\n'
    )
    parts.append('<article>\n<header>\n')
    parts.append(f'<h1>日本の法令 {total:,} 件 (e-Gov CC-BY、jpcite)</h1>\n')
    parts.append(
        f'<p class="byline"><span class="updated">生成日時: {NOW_ISO}</span> '
        f'<span class="sep">/</span> <span class="author">jpcite</span></p>\n'
    )
    parts.append('</header>\n')
    parts.append(
        '<aside class="disclaimer-block" role="note" aria-label="重要な注意事項" '
        'style="border:1px solid #ccc;padding:12px;margin:16px 0;background:#fafafa;">'
        '<p><strong>出典:</strong> 本ページは e-Gov 法令検索 (CC-BY 4.0) を一次資料として'
        '機械再構成したインデックスです。法令の最新本文は e-Gov 公式版を必ず確認してください。</p></aside>\n'
    )

    parts.append('<section class="summary">\n<h2>収録概要</h2>\n')
    parts.append('<ul>\n')
    parts.append(f'<li>収録件数: <strong>{total:,}</strong> 件</li>\n')
    parts.append(f'<li>法令種別カテゴリ: <strong>{len(cat_seq)}</strong></li>\n')
    parts.append('<li>出典: e-Gov 法令検索 (CC-BY 4.0)</li>\n')
    parts.append('<li>ライセンス: クリエイティブ・コモンズ表示 4.0 国際</li>\n')
    parts.append('</ul>\n</section>\n')

    parts.append('<nav class="cat-toc" aria-label="法令種別インデックス">\n<h2>法令種別 一覧</h2>\n<ul class="cat-list">\n')
    for cat in cat_seq:
        n = len(buckets[cat])
        anchor = f"cat-{abs(hash(cat))%999999:06d}"
        parts.append(f'<li><a href="#{anchor}">{he(cat)} ({n:,})</a></li>\n')
    parts.append('</ul>\n</nav>\n')

    for cat in cat_seq:
        rows = buckets[cat]
        # sort by date desc, fallback alpha
        rows_sorted = sorted(rows, key=lambda r: (r[2] or "", r[1]), reverse=True)
        n = len(rows_sorted)
        anchor = f"cat-{abs(hash(cat))%999999:06d}"
        parts.append(f'<section id="{anchor}" class="cat-section">\n')
        parts.append(f'<h3>{he(cat)} <span class="count">({n:,} 件)</span></h3>\n')
        parts.append('<ol class="law-top5">\n')
        for slug, name, date in rows_sorted[:5]:
            label = f"{name} ({date} 施行)" if date else name
            parts.append(
                f'<li><a href="/laws/{he(slug)}">{he(label)}</a></li>\n'
            )
        parts.append('</ol>\n')
        if n > 5:
            parts.append(
                f'<p class="more-link"><a href="/search?q=&law_type={he(cat)}">'
                f'{he(cat)} の全 {n:,} 件を検索</a></p>\n'
            )
        parts.append('</section>\n')

    parts.append(
        '<section class="api-cta">\n<h2>API で取得</h2>\n'
        '<p>本ページの全件データは REST / MCP の両方で取得できます。</p>\n'
        '<pre class="code-block"><code>curl -H "X-API-Key: YOUR_API_KEY" \\\n'
        ' "https://api.jpcite.com/v1/laws?law_type=法律"</code></pre>\n'
        '<p>MCP クライアントからは <code>get_law_article_am(law_id=...)</code> '
        'または <code>search_by_law(...)</code> で呼べます。'
        '詳細は <a href="/docs/">API reference</a> 参照。</p>\n'
        '<p class="api-cta-line">無料 3 リクエスト/日。'
        '<a href="/pricing.html">料金体系</a> · '
        '<a href="/pricing.html#api-paid">API キー発行</a> · '
        '<a href="/dashboard.html">既存キー管理</a></p>\n</section>\n'
    )

    parts.append(
        '<p class="disclaimer">本ページは e-Gov 公開法令の機械再構成インデックスです。'
        '法令の解釈・適用は弁護士・税理士・有資格専門家にご相談ください。</p>\n'
    )
    parts.append('</article>\n </div>\n</main>\n')
    parts.append(FOOTER_HTML)
    parts.append('</body>\n</html>\n')
    return "".join(parts)


# ---------- /enforcement/index.html ----------

def render_enforcement_index(data: dict) -> str:
    total = data["total"]
    buckets = data["buckets"]
    # order by descending count
    ministries = sorted(buckets, key=lambda k: -len(buckets[k]))

    breadcrumb = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": "https://jpcite.com/"},
            {"@type": "ListItem", "position": 2, "name": "行政処分", "item": "https://jpcite.com/enforcement/"},
        ],
    }
    dataset = {
        "@type": "Dataset",
        "@id": "https://jpcite.com/enforcement/#dataset",
        "name": "日本の行政処分 公開記録 (jpcite)",
        "description": (
            f"日本の行政処分 {total:,} 件 (法人格保有・法人番号 13 桁公表済み) を所管官庁別にロールアップ。"
            "出典は各官庁の公式プレスリリース。"
        ),
        "creator": {"@id": "https://jpcite.com/#org"},
        "publisher": {"@id": "https://jpcite.com/#org"},
        "url": "https://jpcite.com/enforcement/",
        "isAccessibleForFree": True,
        "license": "https://www.digital.go.jp/resources/open_data",
        "keywords": "行政処分, 業務改善命令, 許認可取消, 課徴金, jpcite",
        "spatialCoverage": {"@type": "Country", "name": "Japan"},
        "inLanguage": "ja",
        "datePublished": "2026-05-11",
        "size": f"{total:,} records",
    }
    catalog = {
        "@type": "DataCatalog",
        "@id": "https://jpcite.com/enforcement/#catalog",
        "name": "jpcite 行政処分カタログ",
        "publisher": {"@id": "https://jpcite.com/#org"},
        "dataset": {"@id": "https://jpcite.com/enforcement/#dataset"},
    }
    collection = {
        "@type": "CollectionPage",
        "@id": "https://jpcite.com/enforcement/#page",
        "name": f"日本の行政処分 {total:,} 件",
        "url": "https://jpcite.com/enforcement/",
        "inLanguage": "ja",
        "isPartOf": {"@id": "https://jpcite.com/#site"},
    }
    jsonld = jsonld_block([ORG_JSONLD, SITE_JSONLD, catalog, dataset, collection, breadcrumb])

    title = f"日本の行政処分 公開記録 {total:,} 件 — 所管官庁別ロールアップ | jpcite"
    description = (
        f"日本の行政処分 {total:,} 件 を所管官庁別にロールアップ。"
        "法人番号 13 桁が公表された法人格保有事業者のみ。一次資料 URL 完全保持。"
    )

    head = page_head(title, description, "https://jpcite.com/enforcement/", "enforcement")

    parts: list[str] = []
    parts.append(head)
    parts.append(jsonld)
    parts.append('</head>\n<body>\n')
    parts.append('<a href="#main" class="skip-link">本文へスキップ</a>\n')
    parts.append(header_html())
    parts.append('<main id="main" class="enforcement-page">\n <div class="container">\n')
    parts.append(
        '<nav class="breadcrumb" aria-label="パンくず">'
        '<a href="/">ホーム</a> &rsaquo; <span aria-current="page">行政処分</span></nav>\n'
    )
    parts.append('<article>\n<header>\n')
    parts.append(f'<h1>行政処分 公開記録 サマリー — 所管官庁別 {total:,} 件</h1>\n')
    parts.append(
        f'<p class="byline"><span class="updated">生成日時: {NOW_ISO}</span> '
        f'<span class="sep">/</span> <span class="author">jpcite</span></p>\n'
    )
    parts.append('</header>\n')

    parts.append(
        '<aside class="disclaimer-block" role="note" aria-label="重要な注意事項" '
        'style="border:1px solid #ccc;padding:12px;margin:16px 0;background:#fafafa;">'
        '<p><strong>重要:</strong> 本ページは jpcite が政府・自治体の公式プレスリリースから'
        '機械収集した行政処分の公開記録です。掲載対象は法人番号 13 桁が公表され、かつ法人格を持つ'
        '事業者のみです。個人事業主や特定個人が識別される可能性のある記録は掲載対象外です。'
        '処分は当時の公開記録であり、現在は撤回・取消・期間満了している可能性があります。'
        '監査責任・法的判断は弁護士・税理士・公認会計士など有資格者へご相談ください。'
        '本サイトの集計は官報全件ではなく、政府公表記録の取得済みサブセットです。</p></aside>\n'
    )

    # Summary section
    parts.append('<section class="summary">\n<h2>集計概要</h2>\n')
    parts.append('<ul>\n')
    parts.append(f'<li>取得済み処分件数 (静的詳細ページ): <strong>{total:,}</strong> 件</li>\n')
    parts.append(f'<li>所管官庁・自治体カバー: <strong>{len(ministries)}</strong> 機関</li>\n')
    parts.append('<li>掲載基準: 法人番号 13 桁 公表済み + 法人格保有 (個人事業主・特定個人は除外)</li>\n')
    parts.append('<li>収録対象期間: 1998年〜2026年 (公表済み処分日ベース)</li>\n')
    parts.append('</ul>\n</section>\n')

    # TOC by ministry
    parts.append('<nav class="ministry-toc" aria-label="所管官庁インデックス">\n<h2>所管官庁別 ロールアップ</h2>\n<ul class="ministry-list">\n')
    for m in ministries:
        n = len(buckets[m])
        anchor = f"min-{abs(hash(m))%999999:06d}"
        parts.append(f'<li><a href="#{anchor}">{he(m)} ({n:,})</a></li>\n')
    parts.append('</ul>\n</nav>\n')

    # Per-ministry sections
    for m in ministries:
        rows = buckets[m]
        n = len(rows)
        anchor = f"min-{abs(hash(m))%999999:06d}"
        parts.append(f'<section id="{anchor}" class="ministry-section">\n')
        parts.append(f'<h3>{he(m)} <span class="count">({n:,} 件)</span></h3>\n')
        parts.append('<ol class="enforcement-top5">\n')
        for slug, name, _title in rows[:5]:
            parts.append(
                f'<li><a href="/enforcement/{he(slug)}">{he(name)}</a></li>\n'
            )
        parts.append('</ol>\n')
        if n > 5:
            parts.append(
                f'<p class="more-link"><a href="/search?q=&ministry={he(m)}">'
                f'{he(m)} の全 {n:,} 件を検索</a></p>\n'
            )
        parts.append('</section>\n')

    parts.append(
        '<section class="api-cta">\n<h2>API で取得</h2>\n'
        '<p>本ページの全件データは REST / MCP の両方で取得できます。</p>\n'
        '<pre class="code-block"><code>curl -H "X-API-Key: YOUR_API_KEY" \\\n'
        ' "https://api.jpcite.com/v1/am/enforcement?houjin_bangou=&lt;13桁&gt;"</code></pre>\n'
        '<p>MCP クライアントからは <code>check_enforcement_am(houjin_bangou=...)</code> '
        'で呼べます。詳細は <a href="/docs/">API reference</a> 参照。</p>\n'
        '<p class="api-cta-line">無料 3 リクエスト/日。'
        '<a href="/pricing.html">料金体系</a> · '
        '<a href="/pricing.html#api-paid">API キー発行</a> · '
        '<a href="/dashboard.html">既存キー管理</a> · '
        '<a href="/bookmarklet.html">ブラウザ拡張で 1 クリック検索</a></p>\n</section>\n'
    )

    parts.append(
        '<p class="disclaimer">本ページは自動生成された公開記録のロールアップであり、'
        '法的助言・税務助言・調査報告を構成するものではありません。処分の最新内容は'
        '所管官公庁の一次情報を必ず確認してください。</p>\n'
    )
    parts.append('</article>\n </div>\n</main>\n')
    parts.append(FOOTER_HTML)
    parts.append('</body>\n</html>\n')
    return "".join(parts)


# ---------- main ----------

def main() -> None:
    print("Scanning cases...")
    cases = build_cases_groups()
    print(f"  cases total = {cases['total']}, buckets = {len(cases['buckets'])}")
    cases_html = render_cases_index(cases)
    (CASES_DIR / "index.html").write_text(cases_html, encoding="utf-8")
    print(f"  wrote /cases/index.html ({len(cases_html):,} bytes)")

    print("Scanning laws...")
    laws = build_laws_groups()
    print(f"  laws total = {laws['total']}, buckets = {len(laws['buckets'])}")
    laws_html = render_laws_index(laws)
    (LAWS_DIR / "index.html").write_text(laws_html, encoding="utf-8")
    print(f"  wrote /laws/index.html ({len(laws_html):,} bytes)")

    print("Scanning enforcement...")
    enf = build_enforcement_groups()
    print(f"  enforcement total = {enf['total']}, buckets = {len(enf['buckets'])}")
    enf_html = render_enforcement_index(enf)
    (ENFORCEMENT_DIR / "index.html").write_text(enf_html, encoding="utf-8")
    print(f"  wrote /enforcement/index.html ({len(enf_html):,} bytes)")


if __name__ == "__main__":
    main()
