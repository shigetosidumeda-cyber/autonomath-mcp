"""Generate the public count source for site/stats.html and downstream pages.

Public count source = the single canonical place from which homepage / pricing /
trust pages read dataset counts. Replaces ad-hoc numbers hard-coded across
public surfaces (§4.5 of the AI Discovery / Paid Adoption plan, 2026-05-04).

Outputs:
    site/_data/public_counts.json
        Compact JSON keyed by data-stat-key tokens. Browser-side fetch target;
        also embedded into site/stats.html as a JSON-LD QuantitativeValue list.
    site/stats.html
        Regenerated with the latest counts (existing live-fetch JS for
        coverage / freshness / usage left intact).

Run:
    python scripts/generate_public_counts.py

The script reads from the live SQLite databases (primary corpus DB plus the
unified autonomath.db at the repo root); it does not call any external API or
LLM. Counts that cannot be sourced fall through as ``null`` in the JSON.
"""

from __future__ import annotations

import datetime as _dt
import html
import json
import sqlite3
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PRIMARY_CORPUS_DB = REPO_ROOT / "data" / "jpintel.db"
AUTONOMATH_DB_CANDIDATES = [
    REPO_ROOT / "autonomath.db",
    REPO_ROOT / "data" / "autonomath.db",
]
SITE_DATA_DIR = REPO_ROOT / "site" / "_data"
PUBLIC_COUNTS_JSON = SITE_DATA_DIR / "public_counts.json"
STATS_HTML = REPO_ROOT / "site" / "stats.html"
STATS_CANONICAL_URL = "https://jpcite.com/stats"
STATS_EN_CANONICAL_URL = "https://jpcite.com/en/stats"


def _autonomath_db() -> Path | None:
    for cand in AUTONOMATH_DB_CANDIDATES:
        if cand.exists() and cand.stat().st_size > 1024:  # skip 0-byte placeholder
            return cand
    return None


def _scalar(conn: sqlite3.Connection, sql: str, default: Any = None) -> Any:
    try:
        cur = conn.execute(sql)
        row = cur.fetchone()
        if row is None:
            return default
        return row[0]
    except sqlite3.Error:
        return default


def collect_counts() -> dict[str, Any]:
    """Pull dataset counts from the live SQLite databases.

    Keys mirror the public-friendly labels surfaced on stats.html.
    Anything that cannot be queried surfaces as ``None`` so that the static
    page renders ``—`` rather than a misleading zero.
    """
    counts: dict[str, Any] = {}

    if PRIMARY_CORPUS_DB.exists():
        with sqlite3.connect(f"file:{PRIMARY_CORPUS_DB}?mode=ro", uri=True) as jp:
            counts["searchable_programs_total"] = _scalar(
                jp,
                "SELECT COUNT(*) FROM programs WHERE excluded=0 AND tier IN ('S','A','B','C')",
            )
            counts["total_programs"] = _scalar(jp, "SELECT COUNT(*) FROM programs")
            counts["tier_s_count"] = _scalar(
                jp,
                "SELECT COUNT(*) FROM programs WHERE excluded=0 AND tier='S'",
            )
            counts["tier_a_count"] = _scalar(
                jp,
                "SELECT COUNT(*) FROM programs WHERE excluded=0 AND tier='A'",
            )
            counts["tier_b_count"] = _scalar(
                jp,
                "SELECT COUNT(*) FROM programs WHERE excluded=0 AND tier='B'",
            )
            counts["tier_c_count"] = _scalar(
                jp,
                "SELECT COUNT(*) FROM programs WHERE excluded=0 AND tier='C'",
            )
            counts["case_studies_total"] = _scalar(jp, "SELECT COUNT(*) FROM case_studies")
            counts["loan_programs_total"] = _scalar(jp, "SELECT COUNT(*) FROM loan_programs")
            counts["enforcement_cases_total"] = _scalar(
                jp, "SELECT COUNT(*) FROM enforcement_cases"
            )
            counts["exclusion_rules_total"] = _scalar(jp, "SELECT COUNT(*) FROM exclusion_rules")
            laws_metadata = _scalar(jp, "SELECT COUNT(*) FROM laws")
            counts["laws_metadata"] = laws_metadata
            counts["laws_total"] = laws_metadata
            counts["tax_rulesets_total"] = _scalar(jp, "SELECT COUNT(*) FROM tax_rulesets")
            counts["court_decisions_total"] = _scalar(jp, "SELECT COUNT(*) FROM court_decisions")
            counts["bids_total"] = _scalar(jp, "SELECT COUNT(*) FROM bids")
            counts["invoice_registrants_total"] = _scalar(
                jp, "SELECT COUNT(*) FROM invoice_registrants"
            )
            counts["last_program_refresh"] = _scalar(jp, "SELECT MAX(updated_at) FROM programs")

    am_path = _autonomath_db()
    if am_path is not None:
        with sqlite3.connect(f"file:{am_path}?mode=ro", uri=True) as am:
            counts["corporate_records_total"] = _scalar(
                am,
                "SELECT COUNT(*) FROM am_entities WHERE record_kind='corporate_entity'",
            )
            counts["sources_total"] = _scalar(am, "SELECT COUNT(*) FROM am_source")
            counts["law_articles_total"] = _scalar(am, "SELECT COUNT(*) FROM am_law_article")
            counts["last_corpus_refresh"] = _scalar(am, "SELECT MAX(updated_at) FROM am_entities")

    # Public fallback from the latest verified static snapshot.
    # Law coverage is disclosed as metadata + text references, not internal
    # full-text indexing progress.
    if counts.get("laws_metadata") is None:
        counts["laws_metadata"] = 9484
    if counts.get("laws_total") is None:
        counts["laws_total"] = counts["laws_metadata"]

    # Hard-coded reference values that are not row-counts but still belong on
    # the public count surface (price + tool count + free quota). These are the
    # source of truth that other pages cite via ``data-stat-key``.
    counts["mcp_tools_total"] = 155
    counts["price_per_req"] = 3
    counts["price_per_req_inc_tax"] = 3.30
    counts["anonymous_quota_per_day"] = 3

    counts["generated_at"] = (
        _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    return counts


# ---------------------------------------------------------------------------
# stats.html re-render
# ---------------------------------------------------------------------------

# Public-friendly labels (no internal vocabulary leaks). The numeric value next
# to each label is hydrated client-side from public_counts.json, so the static
# HTML carries the latest snapshot as a fallback.
PUBLIC_CARD_LABELS: list[tuple[str, str]] = [
    ("searchable_programs_total", "公開検索できる制度"),
    ("tier_s_count", "厳選 (S 品質ラベル)"),
    ("tier_a_count", "高品質 (A 品質ラベル)"),
    ("case_studies_total", "採択事例"),
    ("loan_programs_total", "融資プログラム"),
    ("enforcement_cases_total", "行政処分"),
    ("laws_metadata", "法令メタデータ・本文参照"),
    ("tax_rulesets_total", "税制ルール"),
    ("court_decisions_total", "判例"),
    ("bids_total", "入札"),
    ("invoice_registrants_total", "適格請求書発行事業者"),
    ("corporate_records_total", "法人レコード"),
    ("sources_total", "出典 (一次資料)"),
]


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return html.escape(str(value))


def render_stats_html(counts: dict[str, Any]) -> str:
    rows: list[str] = []
    for key, label in PUBLIC_CARD_LABELS:
        value = counts.get(key)
        rows.append(
            f'    <li class="public-count" data-stat-key="{html.escape(key)}">'
            f'<span class="public-count-label">{html.escape(label)}</span>'
            f'<span class="public-count-value">{_fmt(value)}</span>'
            "</li>"
        )
    list_html = "\n".join(rows)

    # JSON-LD: every card becomes a schema.org QuantitativeValue inside an
    # ItemList. ``unitText`` carries the friendly Japanese label so an LLM
    # crawler can attribute the number to a human-readable concept.
    jsonld_items: list[dict[str, Any]] = []
    for idx, (key, label) in enumerate(PUBLIC_CARD_LABELS, start=1):
        value = counts.get(key)
        item: dict[str, Any] = {
            "@type": "ListItem",
            "position": idx,
            "item": {
                "@type": "QuantitativeValue",
                "name": label,
                "unitText": key,
            },
        }
        if value is not None:
            item["item"]["value"] = value
        jsonld_items.append(item)

    jsonld_block = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": "jpcite public counts",
        "url": STATS_CANONICAL_URL,
        "dateModified": counts.get("generated_at"),
        "itemListElement": jsonld_items,
    }

    refresh = counts.get("last_program_refresh") or counts.get("generated_at") or ""
    refresh_display = _fmt(refresh)
    jsonld_text = json.dumps(jsonld_block, ensure_ascii=False, indent=2)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#ffffff">
<title>公開件数 | jpcite Stats</title>
<meta name="description" content="jpcite が公開しているデータセット件数 (補助金・法令・税制・適格事業者・行政処分・出典) と最終更新日。サイト内の数字はすべてこのページの値を引用しています。">
<meta name="robots" content="index, follow">

<meta property="og:title" content="公開件数 | jpcite Stats">
<meta property="og:description" content="補助金・法令・税制・適格事業者・行政処分・出典の公開件数と最終更新日。サイト内の数字はこのページが基準。">
<meta property="og:type" content="website">
<meta property="og:url" content="{STATS_CANONICAL_URL}">
<meta property="og:image" content="https://jpcite.com/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="ja_JP">
<meta property="og:locale:alternate" content="en_US">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="公開件数 | jpcite Stats">
<meta name="twitter:description" content="補助金・法令・税制・適格事業者・行政処分・出典の公開件数と最終更新日。サイト内の数字はこのページが基準。">
<meta name="twitter:image" content="https://jpcite.com/assets/og-twitter.png">

<link rel="canonical" href="{STATS_CANONICAL_URL}">
<link rel="alternate" hreflang="ja" href="{STATS_CANONICAL_URL}">
<link rel="alternate" hreflang="en" href="{STATS_EN_CANONICAL_URL}">
<link rel="alternate" hreflang="x-default" href="{STATS_CANONICAL_URL}">
<link rel="icon" href="/assets/favicon-v2.svg" type="image/svg+xml">
<link rel="icon" href="/assets/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/assets/favicon-16.png" sizes="16x16" type="image/png">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;600;700&family=Noto+Serif+JP:wght@600;700;800&family=JetBrains+Mono:wght@400;600&display=swap">
<link rel="stylesheet" href="styles.css?v=20260515c">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "公開件数 | jpcite Stats",
  "url": "{STATS_CANONICAL_URL}",
  "description": "jpcite の公開件数ダッシュボード。データセット件数と最終更新日。",
  "isPartOf": {{
    "@type": "WebSite",
    "name": "jpcite",
    "url": "https://jpcite.com/"
  }},
  "publisher": {{
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "url": "https://jpcite.com/about.html"
  }}
}}
</script>
<script type="application/ld+json" id="public-counts-jsonld">
{jsonld_text}
</script>
<style>
  .stats-page {{ padding: 48px 0 64px; }}
  .stats-page h1 {{ font-size: 28px; margin: 0 0 4px; font-weight: 800; letter-spacing: -0.01em; }}
  .stats-page .sub {{ color: var(--text-muted); margin: 0 0 28px; font-size: 15px; }}
  .stats-section {{ margin: 0 0 40px; }}
  .stats-section h2 {{ font-size: 18px; margin: 0 0 14px; font-weight: 700; }}
  .stats-section .desc {{ color: var(--text-muted); margin: 0 0 18px; font-size: 14px; }}
  ul.public-count-list {{
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
  }}
  li.public-count {{
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 18px;
    background: var(--bg);
    display: flex;
    flex-direction: column;
    gap: 6px;
  }}
  .public-count-label {{
    font-size: 12px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
  }}
  .public-count-value {{
    font-size: 24px;
    font-weight: 800;
    letter-spacing: -0.02em;
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px;
  }}
  .card {{
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 18px;
    background: var(--bg);
  }}
  .card .label {{
    font-size: 12px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: 0 0 6px;
    font-weight: 600;
  }}
  .card .value {{
    font-size: 24px;
    font-weight: 800;
    margin: 0;
    letter-spacing: -0.02em;
  }}
  .card .value.pending {{ color: var(--text-muted); font-size: 16px; font-weight: 500; }}
  table.fresh {{
    width: 100%;
    border-collapse: collapse;
    margin: 0 0 16px;
    font-size: 14px;
  }}
  table.fresh th,
  table.fresh td {{
    text-align: left;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  table.fresh th {{
    color: var(--text-muted);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
    background: var(--bg-alt);
  }}
  table.fresh td.num {{ font-variant-numeric: tabular-nums; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  table.fresh td.muted {{ color: var(--text-muted); font-size: 13px; }}
  .usage-chart-wrap {{ border: 1px solid var(--border); border-radius: 10px; padding: 22px 24px; background: var(--bg); }}
  .usage-chart-wrap svg {{ width: 100%; height: 120px; display: block; }}
  .usage-chart-wrap .axis {{ font-size: 11px; color: var(--text-muted); display: flex; justify-content: space-between; margin: 8px 0 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  .footer-note {{ margin: 8px 0 0; font-size: 13px; color: var(--text-muted); }}
  .updated-at {{ color: var(--text-muted); font-size: 13px; margin: 24px 0 0; padding-top: 16px; border-top: 1px solid var(--border); }}
  .updated-at code {{ background: var(--bg-alt); border: 1px solid var(--border); padding: 1px 6px; border-radius: 4px; font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  .err {{ color: var(--danger); font-size: 13px; margin: 8px 0 0; }}
  @media (max-width: 768px) {{
    .stats-page {{ padding: 32px 0 48px; }}
  }}
</style>
</head>
<body>

<a class="skip-link" href="#main">メインコンテンツへスキップ / Skip to main content</a>

<header class="site-header" role="banner">
 <div class="container header-inner">
 <a class="brand" href="/" aria-label="jpcite ホーム">
 <picture><source media="(prefers-color-scheme: dark)" srcset="/assets/brand/lockup-transparent-600-lightlogo.png 1x, /assets/brand/lockup-transparent-1200-lightlogo.png 2x"><img src="/assets/brand/lockup-transparent-600-darklogo.png" srcset="/assets/brand/lockup-transparent-600-darklogo.png 1x, /assets/brand/lockup-transparent-1200-darklogo.png 2x" alt="jpcite" height="32" style="height:32px;width:auto;display:block;"></picture>
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

<main id="main">
<section class="stats-page">
 <div class="container">

 <h1>公開件数</h1>
 <p class="sub">jpcite が公開しているデータセットの件数と、各データセットの最終更新日。サイト内の数字はすべてこのページの値を出典とします。生成 1 日 1 回。</p>

 <!-- Public Counts ------------------------------------------------------- -->
 <section class="stats-section" aria-labelledby="public-counts-h">
 <h2 id="public-counts-h">公開件数</h2>
 <p class="desc">公的機関 (省庁・自治体・公庫など) の一次資料から取り込んだ件数。集約サイトは出典として採用していません。</p>
 <ul class="public-count-list" id="public-count-list">
{list_html}
 </ul>
 <p class="footer-note">最終データ更新: <code>{refresh_display}</code></p>
 </section>

 <!-- Coverage (live) ---------------------------------------------------- -->
 <section class="stats-section" aria-labelledby="coverage-h">
 <h2 id="coverage-h">ライブ件数 (5 分キャッシュ)</h2>
 <p class="desc">API 経由で取得したライブ件数。上の「公開件数」が日次スナップショット、こちらは API のリアルタイム値です。</p>
 <div class="grid" id="coverage-grid">
 <div class="card"><p class="label">programs (補助金等)</p><p class="value pending">…</p></div>
 <div class="card"><p class="label">case_studies (採択事例)</p><p class="value pending">…</p></div>
 <div class="card"><p class="label">loan_programs (融資)</p><p class="value pending">…</p></div>
 <div class="card"><p class="label">enforcement_cases (行政処分)</p><p class="value pending">…</p></div>
 <div class="card"><p class="label">exclusion_rules (排他)</p><p class="value pending">…</p></div>
 <div class="card"><p class="label">laws (法令)</p><p class="value pending">…</p></div>
 <div class="card"><p class="label">tax_rulesets (税制)</p><p class="value pending">…</p></div>
 <div class="card"><p class="label">court_decisions (判例)</p><p class="value pending">…</p></div>
 <div class="card"><p class="label">bids (入札)</p><p class="value pending">…</p></div>
 <div class="card"><p class="label">invoice_registrants (適格事業者)</p><p class="value pending">…</p></div>
 </div>
 <p class="err" id="coverage-err" hidden></p>
 </section>

 <!-- Freshness ----------------------------------------------------------- -->
 <section class="stats-section" aria-labelledby="freshness-h">
 <h2 id="freshness-h">鮮度 — 出典の取得時期</h2>
 <p class="desc">各データセットを jpcite が出典から取り込んだ日付の最古・最新・行間平均インターバル。古いほど鮮度が下がり、平均インターバルが大きいほど取得頻度が低いことを示します (景表法・消費者契約法の観点から「最終更新」と表記せず「出典取得」を用います)。</p>
 <table class="fresh" aria-describedby="freshness-h">
 <thead>
 <tr><th scope="col">出典</th><th scope="col" class="num">件数</th><th scope="col">最古取得日</th><th scope="col">最新取得日</th><th scope="col" class="num">平均間隔 (日)</th></tr>
 </thead>
 <tbody id="freshness-body">
 <tr><td colspan="5" class="muted">読み込み中…</td></tr>
 </tbody>
 </table>
 <p class="err" id="freshness-err" hidden></p>
 </section>

 <!-- Usage --------------------------------------------------------------- -->
 <section class="stats-section" aria-labelledby="usage-h">
 <h2 id="usage-h">Usage — 過去 30 日の API 利用量</h2>
 <p class="desc">認証済み API キー経由の累積リクエスト数。匿名 (X-API-Key 無し) は集計対象外。グラフは日次、ラインは累積。</p>
 <div class="usage-chart-wrap">
 <svg id="usage-svg" viewBox="0 0 600 120" preserveAspectRatio="none" role="img" aria-label="過去 30 日の日別 API 利用量">
 <text x="300" y="60" text-anchor="middle" font-size="12" fill="#555">読み込み中…</text>
 </svg>
 <p class="axis"><span id="usage-axis-from">—</span><span id="usage-axis-to">—</span></p>
 <p class="footer-note" id="usage-total">合計: —</p>
 </div>
 <p class="err" id="usage-err" hidden></p>
 </section>

 <p class="updated-at">
 Cadence: 1 日 1 回ライブ集計 (5 分メモリキャッシュ経由)。
 Source: <code>GET /v1/stats/coverage</code> · <code>GET /v1/stats/freshness</code> · <code>GET /v1/stats/usage</code>。
 公開件数 JSON: <code>/_data/public_counts.json</code>。
 最終生成: <code id="generated-at">{html.escape(counts.get("generated_at", "—"))}</code>
 </p>

 </div>
</section>
</main>

<footer class="site-footer" role="contentinfo">
 <div class="container footer-inner">
 <div class="footer-col">
 <p class="footer-brand"><picture class="footer-brand-mark"><source media="(prefers-color-scheme: dark)" srcset="/assets/brand/jpcite-mark-light-fill.svg"><img src="/assets/brand/jpcite-mark-dark-fill.svg" alt="" width="20" height="20" loading="lazy" decoding="async"></picture>jpcite</p>
 <p class="footer-tag">日本の公的制度を、根拠付き成果物に。</p>
 </div>
 <nav class="footer-nav" aria-label="フッター">
 <a href="about.html">運営について</a>
 <a href="products.html">プロダクト</a>
 <a href="pricing.html">料金</a>
 <a href="/docs/">ドキュメント</a>
 <a href="trust.html">信頼</a>
 <a href="tos.html">利用規約</a>
 <a href="privacy.html">プライバシー</a>
 <a href="tokushoho.html">特商法</a><a href="mailto:info@bookyou.net">お問い合わせ</a>
 </nav>
 <p class="footer-entity">運営: Bookyou株式会社 · <a href="mailto:info@bookyou.net">info@bookyou.net</a></p>
 <p class="footer-copy">&copy; 2026 Bookyou株式会社</p>
 </div>
</footer>

<script>
(function() {{
  "use strict";

  // Allow override for cross-origin local dev; defaults to the production API on jpcite.com.
  var BASE = (typeof window !== "undefined" && window.JPCITE_API_BASE) || (typeof window !== "undefined" && window.location && window.location.hostname === "jpcite.com" ? "https://api.jpcite.com" : "");

  var COVERAGE_LABELS = [
    ["programs", "programs (補助金等)"],
    ["case_studies", "case_studies (採択事例)"],
    ["loan_programs", "loan_programs (融資)"],
    ["enforcement_cases", "enforcement_cases (行政処分)"],
    ["exclusion_rules", "exclusion_rules (排他)"],
    ["laws", "laws (法令)"],
    ["tax_rulesets", "tax_rulesets (税制)"],
    ["court_decisions", "court_decisions (判例)"],
    ["bids", "bids (入札)"],
    ["invoice_registrants", "invoice_registrants (適格事業者)"]
  ];

  function fmtNum(n) {{
    if (n === null || n === undefined) return "—";
    return Number(n).toLocaleString("ja-JP");
  }}

  function showErr(el, err, retry) {{
    if (!el) return;
    var friendlyMsg = err && err.name === "AbortError"
      ? "タイムアウト — 再度お試しください"
      : "読み込みに失敗しました。時間をおいて再試行してください";
    el.innerHTML = "";
    var span = document.createElement("span");
    span.textContent = friendlyMsg + " · ";
    el.appendChild(span);
    if (retry) {{
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "再試行";
      btn.style.cssText = "margin:0 8px 0 0;padding:2px 10px;font-size:12px;border:1px solid var(--border);border-radius:4px;background:var(--bg-alt);cursor:pointer;";
      btn.addEventListener("click", function() {{ el.hidden = true; retry(); }});
      el.appendChild(btn);
    }}
    var link = document.createElement("a");
    link.href = "status.html";
    link.textContent = "障害状況";
    el.appendChild(link);
    el.hidden = false;
  }}

  function loadCoverage() {{
    var ctrl = new AbortController();
    var timer = setTimeout(function() {{ ctrl.abort(); }}, 15000);
    fetch(BASE + "/v1/stats/coverage", {{ signal: ctrl.signal }})
      .then(function (r) {{
        if (!r.ok) throw new Error("coverage fetch failed: " + r.status);
        return r.json();
      }})
      .then(function (data) {{
        var grid = document.getElementById("coverage-grid");
        if (!grid) return;
        grid.innerHTML = "";
        COVERAGE_LABELS.forEach(function (pair) {{
          var key = pair[0], label = pair[1];
          var card = document.createElement("div");
          card.className = "card";
          var lab = document.createElement("p");
          lab.className = "label";
          lab.textContent = label;
          var val = document.createElement("p");
          val.className = "value";
          val.textContent = fmtNum(data[key]);
          card.appendChild(lab);
          card.appendChild(val);
          grid.appendChild(card);
        }});
        var ts = document.getElementById("generated-at");
        if (ts && data.generated_at) ts.textContent = data.generated_at;
      }})
      .catch(function (e) {{
        showErr(document.getElementById("coverage-err"), e, loadCoverage);
      }})
      .then(function() {{ clearTimeout(timer); }});
  }}

  function loadFreshness() {{
    var ctrl = new AbortController();
    var timer = setTimeout(function() {{ ctrl.abort(); }}, 15000);
    fetch(BASE + "/v1/stats/freshness", {{ signal: ctrl.signal }})
      .then(function (r) {{
        if (!r.ok) throw new Error("freshness fetch failed: " + r.status);
        return r.json();
      }})
      .then(function (data) {{
        var body = document.getElementById("freshness-body");
        if (!body) return;
        body.innerHTML = "";
        Object.keys(data.sources).forEach(function (k) {{
          var s = data.sources[k];
          var tr = document.createElement("tr");
          var tdName = document.createElement("td");
          tdName.textContent = k;
          var tdCount = document.createElement("td");
          tdCount.className = "num";
          tdCount.textContent = fmtNum(s.count);
          var tdMin = document.createElement("td");
          tdMin.textContent = s.min || "—";
          if (!s.min) tdMin.className = "muted";
          var tdMax = document.createElement("td");
          tdMax.textContent = s.max || "—";
          if (!s.max) tdMax.className = "muted";
          var tdAvg = document.createElement("td");
          tdAvg.className = "num";
          tdAvg.textContent = s.avg_interval_days === null || s.avg_interval_days === undefined
            ? "—" : Number(s.avg_interval_days).toFixed(2);
          tr.appendChild(tdName);
          tr.appendChild(tdCount);
          tr.appendChild(tdMin);
          tr.appendChild(tdMax);
          tr.appendChild(tdAvg);
          body.appendChild(tr);
        }});
      }})
      .catch(function (e) {{
        var body = document.getElementById("freshness-body");
        if (body) body.innerHTML = "";
        showErr(document.getElementById("freshness-err"), e, loadFreshness);
      }})
      .then(function() {{ clearTimeout(timer); }});
  }}

  function renderUsage(daily, total, since, until) {{
    var svg = document.getElementById("usage-svg");
    if (!svg) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var W = 600, H = 120, pad = 4;
    var max = 0;
    daily.forEach(function (d) {{ if (d.count > max) max = d.count; }});
    if (max < 1) max = 1;
    var bw = (W - pad * 2) / daily.length;
    daily.forEach(function (d, i) {{
      var h = (d.count / max) * (H - pad * 2);
      var x = pad + i * bw;
      var y = H - pad - h;
      var rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", x.toFixed(2));
      rect.setAttribute("y", y.toFixed(2));
      rect.setAttribute("width", Math.max(1, bw - 1).toFixed(2));
      rect.setAttribute("height", Math.max(0, h).toFixed(2));
      rect.setAttribute("fill", "#1e3a8a");
      var title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      title.textContent = d.date + ": " + d.count + " calls (累積 " + d.cumulative + ")";
      rect.appendChild(title);
      svg.appendChild(rect);
    }});
    var fr = document.getElementById("usage-axis-from");
    var to = document.getElementById("usage-axis-to");
    if (fr) fr.textContent = since;
    if (to) to.textContent = until;
    var t = document.getElementById("usage-total");
    if (t) t.textContent = "合計: " + fmtNum(total) + " calls (過去 30 日)";
  }}

  function loadUsage() {{
    var ctrl = new AbortController();
    var timer = setTimeout(function() {{ ctrl.abort(); }}, 15000);
    fetch(BASE + "/v1/stats/usage", {{ signal: ctrl.signal }})
      .then(function (r) {{
        if (!r.ok) throw new Error("usage fetch failed: " + r.status);
        return r.json();
      }})
      .then(function (data) {{
        renderUsage(data.daily, data.total, data.since, data.until);
      }})
      .catch(function (e) {{
        showErr(document.getElementById("usage-err"), e, loadUsage);
      }})
      .then(function() {{ clearTimeout(timer); }});
  }}

  // Hydrate any [data-stat-key] hooks (on this page + parents that include
  // shared.js), preferring values from /_data/public_counts.json.
  function hydratePublicCounts() {{
    var nodes = document.querySelectorAll("[data-stat-key]");
    if (!nodes.length) return;
    fetch("/_data/public_counts.json", {{ cache: "no-cache" }})
      .then(function (r) {{ if (!r.ok) throw new Error("public_counts fetch failed: " + r.status); return r.json(); }})
      .then(function (data) {{
        nodes.forEach(function (el) {{
          var key = el.getAttribute("data-stat-key");
          if (!key || !(key in data) || data[key] === null || data[key] === undefined) return;
          var v = data[key];
          var target = el.querySelector(".public-count-value") || el;
          target.textContent = (typeof v === "number") ? v.toLocaleString("ja-JP") : String(v);
        }});
      }})
      .catch(function () {{ /* leave fallback values intact */ }});
  }}

  document.addEventListener("DOMContentLoaded", function() {{
    loadCoverage();
    loadFreshness();
    loadUsage();
    hydratePublicCounts();
  }});
}})();
</script>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    counts = collect_counts()
    SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_COUNTS_JSON.write_text(
        json.dumps(counts, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    STATS_HTML.write_text(render_stats_html(counts), encoding="utf-8")
    print(f"wrote {PUBLIC_COUNTS_JSON.relative_to(REPO_ROOT)}")
    print(f"wrote {STATS_HTML.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
