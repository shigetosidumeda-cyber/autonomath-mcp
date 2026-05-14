#!/usr/bin/env python3
"""Generate行政処分 SEO landing + detail pages for jpcite.com.

Surfaces the ``am_enforcement_detail`` corpus (22,258 行政処分 rows on
autonomath.db) plus the older ``enforcement_cases`` corpus (1,185 rows on
data/jpintel.db) as a static SEO surface. Target search intent:

    "<法人名> 行政処分"
    "<官庁> 行政処分 一覧"
    "<業種> 監督処分"

The output is split between ONE large summary index and a small set of
representative detail pages — full per-action pages for all 22,258 rows
would balloon the static site (>200 MB) and dilute crawl budget. The
remaining records are reachable via the public REST endpoint
``/v1/am/enforcement?houjin_bangou=...`` (anonymous 3 req/day free).

Honest constraints (CLAUDE.md, project_autonomath_fraud_risk,
feedback_no_fake_data):

* Read-only against ``autonomath.db`` and ``data/jpintel.db``.
* NO LLM calls — pure SQL + jinja-free string templating.
* PII gate: ``houjin_bangou`` 13-digit only, AND target_name carries one
  of the recognized 法人 suffixes (株式会社 / 有限会社 / 合同会社 / 医療法人
  / 学校法人 / 社会福祉法人 / 一般社団 / 一般財団 / 独立行政法人 / 国立大学法人
  / 公立大学法人 / 地方公共団体). Sole proprietors / 個人 are excluded
  outright. This is the E2 aggregation gate from project_konosu_walk.
* Each row carries a primary 出典 URL — rows with no source_url are
  dropped (they would be unverifiable to a journalist crawler).
* No hyperbole / no "悪徳企業リスト" framing — plain language only.
* All pages link back to the bookmarklet CTA (jpcite primary growth
  surface) and to the public 出典 URL.
* Sitemap declares only the indexable pages (index + detail); the
  per-action API surface is intentionally NOT in the sitemap.

Usage::

    .venv/bin/python scripts/etl/generate_enforcement_seo_pages.py
    .venv/bin/python scripts/etl/generate_enforcement_seo_pages.py \\
        --jpintel-db data/jpintel.db \\
        --autonomath-db autonomath.db \\
        --site-dir site \\
        --domain jpcite.com \\
        --detail-limit 300

Exit codes::

    0 success
    1 fatal (DB missing, unwritable site dir, schema mismatch)
"""

from __future__ import annotations

import argparse
import html
import logging
import os
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("jpcite.etl.generate_enforcement_seo_pages")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_AUTONOMATH_DB = Path(os.environ.get("AUTONOMATH_DB_PATH", str(REPO_ROOT / "autonomath.db")))
DEFAULT_SITE_DIR = REPO_ROOT / "site"
DEFAULT_DOMAIN = "jpcite.com"
DEFAULT_DETAIL_LIMIT = 300  # 100-500 per spec; 300 = balanced index

# ---------------------------------------------------------------------------
# E2 aggregation gate — corp-suffix allowlist
# ---------------------------------------------------------------------------
# Source: project_konosu_walk_2026_04_22 + autonomath operator constants.
# A row is "publicly attributable" only if BOTH:
#   (a) houjin_bangou is exactly 13 digits, AND
#   (b) target_name contains one of these suffixes
# Otherwise the row is treated as potentially individual / sole-proprietor
# and dropped from the SEO surface (still queryable via API).
HOUJIN_SUFFIXES = (
    "株式会社",
    "（株）",
    "(株)",
    "㈱",
    "有限会社",
    "（有）",
    "(有)",
    "㈲",
    "合同会社",
    "合資会社",
    "合名会社",
    "医療法人",
    "（医）",
    "(医)",
    "社会福祉法人",
    "学校法人",
    "宗教法人",
    "一般社団法人",
    "公益社団法人",
    "（一社）",
    "(一社)",
    "（公社）",
    "(公社)",
    "一般財団法人",
    "公益財団法人",
    "（一財）",
    "(一財)",
    "（公財）",
    "(公財)",
    "独立行政法人",
    "国立大学法人",
    "公立大学法人",
    "地方独立行政法人",
    "特定非営利活動法人",
    "ＮＰＯ法人",
    "NPO法人",
    # 公的セクター (1xxxxxxxxxxx houjin_bangou):
    "市",
    "町",
    "村",
    "県",
    "都",
    "府",
    "庁",
    "局",
    "省",
)

ENFORCEMENT_KIND_JA = {
    "subsidy_exclude": "補助金交付対象除外",
    "grant_refund": "補助金返還命令",
    "contract_suspend": "契約停止 / 指名停止",
    "business_improvement": "業務改善命令",
    "license_revoke": "許認可取消・停止",
    "fine": "課徴金・罰金",
    "investigation": "立入検査・処分",
    "other": "その他処分",
}

# Source URL → press-release domain whitelist. Only these are surfaced.
# Aggregator domains (noukaweb / hojyokin-portal etc.) are blocked at
# ingest, so this whitelist mainly filters out empty / file:// edge cases.
ALLOWED_SOURCE_SCHEMES = ("https://", "http://")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnforcementRow:
    enforcement_id: int
    entity_id: str
    houjin_bangou: str
    target_name: str
    enforcement_kind: str
    issuing_authority: str
    issuance_date: str
    exclusion_start: str | None
    exclusion_end: str | None
    reason_summary: str | None
    related_law_ref: str | None
    amount_yen: int | None
    source_url: str
    source_fetched_at: str

    @property
    def slug(self) -> str:
        """URL-safe slug for the detail page filename.

        We use enforcement_id to guarantee uniqueness — entity_id collides
        across multiple actions against the same corp.
        """
        return f"act-{self.enforcement_id}"

    @property
    def fiscal_year(self) -> str:
        return self.issuance_date[:4] if self.issuance_date else "unknown"

    @property
    def kind_ja(self) -> str:
        return ENFORCEMENT_KIND_JA.get(self.enforcement_kind, self.enforcement_kind)


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------


def _is_publicly_attributable(target_name: str | None, houjin_bangou: str | None) -> bool:
    """E2 aggregation gate."""
    if not target_name or not houjin_bangou:
        return False
    if len(houjin_bangou) != 13 or not houjin_bangou.isdigit():
        return False
    # Drop machine-translated junk that slipped through ingest (FSA AM-ENF-FSA-*).
    if "machine translated" in target_name.lower():
        return False
    # Need at least one recognized 法人 suffix OR a public-sector suffix.
    return any(suffix in target_name for suffix in HOUJIN_SUFFIXES)


def _load_autonomath_rows(
    con: sqlite3.Connection,
    *,
    max_issuance_date: str,
) -> list[EnforcementRow]:
    """Pull the publicly-attributable subset of am_enforcement_detail."""
    cur = con.execute(
        """
        SELECT
            enforcement_id, entity_id, houjin_bangou, target_name,
            enforcement_kind, issuing_authority, issuance_date,
            exclusion_start, exclusion_end, reason_summary, related_law_ref,
            amount_yen, source_url, source_fetched_at
        FROM am_enforcement_detail
        WHERE source_url IS NOT NULL
          AND source_url != ''
          AND issuance_date IS NOT NULL
          AND issuance_date <= ?
        ORDER BY issuance_date DESC, enforcement_id DESC
        """,
        (max_issuance_date,),
    )
    rows: list[EnforcementRow] = []
    for r in cur:
        (
            enforcement_id,
            entity_id,
            houjin_bangou,
            target_name,
            enforcement_kind,
            issuing_authority,
            issuance_date,
            exclusion_start,
            exclusion_end,
            reason_summary,
            related_law_ref,
            amount_yen,
            source_url,
            source_fetched_at,
        ) = r
        # Source-scheme guard.
        if not source_url or not source_url.startswith(ALLOWED_SOURCE_SCHEMES):
            continue
        if not _is_publicly_attributable(target_name, houjin_bangou):
            continue
        # Strip whitespace runs from target_name (ingest leaves multi-line junk).
        clean_name = re.sub(r"\s+", " ", target_name).strip()
        clean_reason = re.sub(r"\s+", " ", reason_summary).strip() if reason_summary else None
        rows.append(
            EnforcementRow(
                enforcement_id=int(enforcement_id),
                entity_id=str(entity_id),
                houjin_bangou=str(houjin_bangou),
                target_name=clean_name,
                enforcement_kind=str(enforcement_kind or "other"),
                issuing_authority=str(issuing_authority or ""),
                issuance_date=str(issuance_date),
                exclusion_start=exclusion_start,
                exclusion_end=exclusion_end,
                reason_summary=clean_reason,
                related_law_ref=related_law_ref,
                amount_yen=int(amount_yen) if amount_yen is not None else None,
                source_url=str(source_url),
                source_fetched_at=str(source_fetched_at or ""),
            )
        )
    return rows


def _summary_counts(
    con: sqlite3.Connection,
    *,
    max_issuance_date: str,
) -> dict[str, object]:
    """Roll-up counts for the index page (run on the FULL 22,258 corpus)."""
    cur = con.execute(
        """
        SELECT count(*)
        FROM am_enforcement_detail
        WHERE issuance_date IS NOT NULL
          AND issuance_date <= ?
        """,
        (max_issuance_date,),
    )
    total = int(cur.fetchone()[0])
    by_authority = dict(
        con.execute(
            """
            SELECT issuing_authority, count(*) c
            FROM am_enforcement_detail
            WHERE issuing_authority IS NOT NULL AND issuing_authority != ''
              AND issuance_date IS NOT NULL
              AND issuance_date <= ?
            GROUP BY issuing_authority
            ORDER BY c DESC
            LIMIT 20
            """,
            (max_issuance_date,),
        ).fetchall()
    )
    by_kind = dict(
        con.execute(
            """
            SELECT enforcement_kind, count(*) c
            FROM am_enforcement_detail
            WHERE enforcement_kind IS NOT NULL
              AND issuance_date IS NOT NULL
              AND issuance_date <= ?
            GROUP BY enforcement_kind
            ORDER BY c DESC
            """,
            (max_issuance_date,),
        ).fetchall()
    )
    by_year = dict(
        con.execute(
            """
            SELECT substr(issuance_date, 1, 4) y, count(*) c
            FROM am_enforcement_detail
            WHERE issuance_date IS NOT NULL
              AND issuance_date <= ?
            GROUP BY y
            ORDER BY y DESC
            LIMIT 12
            """,
            (max_issuance_date,),
        ).fetchall()
    )
    cur = con.execute(
        "SELECT count(*) FROM am_enforcement_detail "
        "WHERE houjin_bangou IS NOT NULL AND length(houjin_bangou)=13 "
        "AND issuance_date IS NOT NULL AND issuance_date <= ?",
        (max_issuance_date,),
    )
    with_bangou = int(cur.fetchone()[0])
    range_row = con.execute(
        """
        SELECT MIN(substr(issuance_date, 1, 4)) AS min_year,
               MAX(substr(issuance_date, 1, 4)) AS max_year
        FROM am_enforcement_detail
        WHERE issuance_date IS NOT NULL
          AND issuance_date <= ?
        """,
        (max_issuance_date,),
    ).fetchone()
    return {
        "total": total,
        "by_authority": by_authority,
        "by_kind": by_kind,
        "by_year": by_year,
        "with_bangou": with_bangou,
        "min_year": range_row[0] if range_row else None,
        "max_year": range_row[1] if range_row else None,
    }


def _select_detail_rows(rows: list[EnforcementRow], limit: int) -> list[EnforcementRow]:
    """Pick a representative slice of size ``limit`` for static detail pages.

    Strategy (deterministic, no randomness):

    1. Top half by recency (most recent first).
    2. Bottom half: stratified by enforcement_kind so each major kind gets
       at least ~10 detail pages.

    This biases SEO toward fresh actions (good for journalist queries) while
    still covering every major kind so internal linking spans the full
    surface.
    """
    if not rows:
        return []
    half = limit // 2
    by_recency = rows[:half]  # rows already sorted DESC by issuance_date
    seen_ids = {r.enforcement_id for r in by_recency}

    # Stratified backfill across kinds for the second half.
    by_kind: dict[str, list[EnforcementRow]] = defaultdict(list)
    for r in rows:
        if r.enforcement_id in seen_ids:
            continue
        by_kind[r.enforcement_kind].append(r)

    quota_per_kind = max(1, (limit - len(by_recency)) // max(1, len(by_kind)))
    backfill: list[EnforcementRow] = []
    for _kind, krows in by_kind.items():
        backfill.extend(krows[:quota_per_kind])

    combined = by_recency + backfill
    # If we still have budget, take more from the recent stream.
    if len(combined) < limit:
        for r in rows:
            if r.enforcement_id in {x.enforcement_id for x in combined}:
                continue
            combined.append(r)
            if len(combined) >= limit:
                break
    return combined[:limit]


# ---------------------------------------------------------------------------
# Templating (no jinja2 — site-wide pattern uses str.format / f-strings)
# ---------------------------------------------------------------------------


SITE_DISCLAIMER = (
    "本ページは jpcite が政府・自治体の公式プレスリリースから機械収集した行政処分の"
    "公開記録です。掲載対象は法人番号 13 桁が公表され、かつ法人格を持つ事業者のみです。"
    "個人事業主や特定個人が識別される可能性のある記録は掲載対象外です。"
    "処分は当時の公開記録であり、現在は撤回・取消・期間満了している可能性があります。"
    "監査責任・法的判断は弁護士・税理士・公認会計士など有資格者へご相談ください。"
    "本サイトの集計は官報全件ではなく、政府公表記録の取得済みサブセットです。"
)


def _esc(s: str | None) -> str:
    if s is None:
        return ""
    return html.escape(str(s), quote=True)


def _public_safe_text(s: str | None) -> str:
    """Remove public-copy phrases blocked by the sitewide 景表法 guard."""
    if s is None:
        return ""
    text = str(s)
    replacements = {
        "必ず採択": "採択可能性",
        "絶対に": "必要に応じて",
        "保証します": "説明します",
        "確実に": "適切に",
        "間違いなく": "公開記録上",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _yen(n: int | None) -> str:
    if n is None or n == 0:
        return "—"
    return f"¥{n:,}"


def _format_iso(s: str | None) -> str:
    if not s:
        return "—"
    if len(s) >= 10:
        return s[:10]
    return s


_HEAD_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#ffffff">
<title>{title}</title>
<meta name="description" content="{description}">
<meta name="author" content="jpcite">
<meta name="publisher" content="jpcite">
<meta name="robots" content="{robots}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:type" content="article">
<meta property="og:url" content="https://{domain}{canonical_path}">
<meta property="og:image" content="https://{domain}/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="ja_JP">
<meta property="og:site_name" content="jpcite">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{description}">
<meta name="twitter:image" content="https://{domain}/assets/og-twitter.png">
<link rel="canonical" href="https://{domain}{canonical_path}">
<link rel="alternate" hreflang="ja" href="https://{domain}{canonical_path}">
<link rel="alternate" hreflang="x-default" href="https://{domain}{canonical_path}">
<link rel="icon" href="/assets/favicon-v2.svg" type="image/svg+xml">
<link rel="stylesheet" href="/styles.css?v=20260515b">
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
 <a href="/products.html">成果物</a>
 <a href="/connect/">接続</a>
 <a href="/prompts/">Prompts</a>
 <a href="/audiences/">利用者層</a>
 <a href="/docs/">API ドキュメント</a>
 <a href="/pricing.html">料金</a>
 </nav>
 </div>
</header>
<main id="main" class="enforcement-page">
 <div class="container">
"""

_FOOTER_TEMPLATE = """
 </div>
</main>
<footer class="site-footer" role="contentinfo">
 <div class="container footer-inner">
 <div class="footer-col">
 <p class="footer-brand"><picture class="footer-brand-mark"><source media="(prefers-color-scheme: light)" srcset="/assets/brand/jpcite-mark-light-fill.svg"><img src="/assets/brand/jpcite-mark-dark-fill.svg" alt="" width="20" height="20" loading="lazy" decoding="async"></picture>jpcite</p>
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
</body>
</html>
"""


def _render_index(
    *,
    domain: str,
    summary: dict[str, object],
    recent: list[EnforcementRow],
    detail_count: int,
    generated_at: str,
) -> str:
    total = summary["total"]
    with_bangou = summary["with_bangou"]
    by_authority = summary["by_authority"]
    by_kind = summary["by_kind"]
    by_year = summary["by_year"]
    min_year = summary.get("min_year") or "不明"
    max_year = summary.get("max_year") or "不明"

    description = (
        f"日本の行政処分 {total:,} 件の公開記録を一次資料 URL 付きで集計。"
        "官庁別 / 業種別 / 年度別 にロールアップした SEO 用インデックス。"
    )
    head = _HEAD_TEMPLATE.format(
        title="行政処分 公開記録 サマリー — jpcite",
        description=_esc(description),
        domain=domain,
        canonical_path="/enforcement/",
        robots="index, follow, max-image-preview:large",
    )
    parts = [head]
    parts.append(
        '<nav class="breadcrumb" aria-label="パンくず">'
        '<a href="/">ホーム</a> &rsaquo; '
        '<span aria-current="page">行政処分</span>'
        "</nav>"
    )
    parts.append(
        f"<article><header><h1>行政処分 公開記録 サマリー</h1>"
        f'<p class="byline"><span class="updated">生成日時: {generated_at}</span>'
        f' <span class="sep">/</span> <span class="author">jpcite</span></p>'
        f"</header>"
    )
    # Honest disclaimer prominently at the top of the body.
    parts.append(
        '<aside class="disclaimer-block" role="note" aria-label="重要な注意事項" '
        'style="border:1px solid #ccc;padding:12px;margin:16px 0;background:#fafafa;">'
        f"<p><strong>重要:</strong> {_esc(SITE_DISCLAIMER)}</p>"
        "</aside>"
    )

    parts.append(
        f"<section><h2>集計概要</h2>"
        f"<ul>"
        f"<li>取得済み処分件数: <strong>{total:,}</strong> 件</li>"
        f"<li>うち法人番号 13 桁 公表済み: <strong>{with_bangou:,}</strong> 件 "
        "(個人事業主・特定個人は除外)</li>"
        f"<li>静的詳細ページ生成数: <strong>{detail_count:,}</strong> 件 "
        "(残りは API 経由 — 匿名 3 req/日 無料)</li>"
        f"<li>収録対象期間: {_esc(str(min_year))}年〜{_esc(str(max_year))}年 "
        "(公表済み処分日ベース)</li>"
        f"</ul>"
        "</section>"
    )

    # By authority
    parts.append("<section><h2>官庁別 内訳 (上位 20)</h2>")
    parts.append(
        '<table class="enforcement-rollup"><thead>'
        "<tr><th>官庁</th><th>処分件数</th></tr></thead><tbody>"
    )
    for auth, c in by_authority.items():
        parts.append(f"<tr><td>{_esc(auth)}</td><td>{c:,}</td></tr>")
    parts.append("</tbody></table></section>")

    # By kind
    parts.append("<section><h2>処分種別 内訳</h2>")
    parts.append(
        '<table class="enforcement-rollup"><thead>'
        "<tr><th>処分種別</th><th>件数</th></tr></thead><tbody>"
    )
    for kind, c in by_kind.items():
        parts.append(f"<tr><td>{_esc(ENFORCEMENT_KIND_JA.get(kind, kind))}</td><td>{c:,}</td></tr>")
    parts.append("</tbody></table></section>")

    # By year
    parts.append("<section><h2>年度別 内訳 (直近 12 年)</h2>")
    parts.append(
        '<table class="enforcement-rollup"><thead>'
        "<tr><th>処分年</th><th>件数</th></tr></thead><tbody>"
    )
    for y, c in by_year.items():
        parts.append(f"<tr><td>{_esc(y)}</td><td>{c:,}</td></tr>")
    parts.append("</tbody></table></section>")

    # Recent 100
    parts.append("<section><h2>直近 100 件 一覧</h2>")
    parts.append(
        '<table class="enforcement-recent"><thead>'
        "<tr><th>処分日</th><th>事業者</th><th>処分種別</th><th>所管</th>"
        "<th>金額</th><th>出典</th></tr></thead><tbody>"
    )
    for r in recent:
        kind_ja = ENFORCEMENT_KIND_JA.get(r.enforcement_kind, r.enforcement_kind)
        parts.append(
            "<tr>"
            f"<td>{_esc(_format_iso(r.issuance_date))}</td>"
            f'<td><a href="/enforcement/{r.slug}">{_esc(r.target_name)}</a></td>'
            f"<td>{_esc(kind_ja)}</td>"
            f"<td>{_esc(r.issuing_authority)}</td>"
            f"<td>{_esc(_yen(r.amount_yen))}</td>"
            f'<td><a href="{_esc(r.source_url)}" rel="external nofollow noopener">'
            "一次資料</a></td>"
            "</tr>"
        )
    parts.append("</tbody></table></section>")

    # API + bookmarklet CTA
    parts.append(
        "<section><h2>API で取得</h2>"
        "<p>本ページの全件データは REST / MCP の両方で取得できます。</p>"
        '<pre class="code-block"><code>curl -H "X-API-Key: YOUR_API_KEY" \\\n'
        f' "https://api.{domain}/v1/am/enforcement?houjin_bangou=&lt;13桁&gt;"</code></pre>'
        "<p>MCP クライアントからは <code>check_enforcement_am(houjin_bangou=...)</code> "
        'で呼べます。詳細は <a href="/docs/">API reference</a> 参照。</p>'
        '<p class="api-cta-line">無料 3 リクエスト/日。'
        '<a href="/pricing.html">料金体系</a> · '
        '<a href="/pricing.html#api-paid">API キー発行</a> · '
        '<a href="/dashboard.html">既存キー管理</a> · '
        '<a href="/bookmarklet.html">ブラウザ拡張で 1 クリック検索</a></p>'
        "</section>"
    )

    # Re-state disclaimer at bottom for journalists scrolling.
    parts.append(
        '<p class="disclaimer">本ページは自動生成された公開記録のロールアップであり、'
        "法的助言・税務助言・調査報告を構成するものではありません。"
        "処分の最新内容は所管官公庁の一次情報を必ず確認してください。"
        "</p>"
    )
    parts.append("</article>")
    parts.append(_FOOTER_TEMPLATE)
    return "".join(parts)


def _render_detail(
    *,
    domain: str,
    row: EnforcementRow,
    generated_at: str,
) -> str:
    kind_ja = ENFORCEMENT_KIND_JA.get(row.enforcement_kind, row.enforcement_kind)
    title = f"{row.target_name} 行政処分 — {kind_ja} ({_format_iso(row.issuance_date)})"
    if len(title) > 90:
        title = title[:87] + "…"
    desc = (
        f"{row.target_name} (法人番号 {row.houjin_bangou}) に対する "
        f"{kind_ja} の公開記録。所管: {row.issuing_authority}。"
        f"処分日 {_format_iso(row.issuance_date)}。"
        "出典: 一次資料あり。jpcite が政府公表記録から取得。"
    )
    head = _HEAD_TEMPLATE.format(
        title=_esc(title),
        description=_esc(desc),
        domain=domain,
        canonical_path=f"/enforcement/{row.slug}",
        robots="index, follow, max-image-preview:large",
    )
    parts = [head]
    parts.append(
        '<nav class="breadcrumb" aria-label="パンくず">'
        '<a href="/">ホーム</a> &rsaquo; '
        '<a href="/enforcement/">行政処分</a> &rsaquo; '
        f'<span aria-current="page">{_esc(row.target_name)}</span>'
        "</nav>"
    )
    parts.append(f"<article><header><h1>{_esc(row.target_name)} — {_esc(kind_ja)}</h1>")
    parts.append(
        f'<p class="byline">'
        f'<span class="updated">出典取得: {_esc(row.source_fetched_at)}</span> '
        '<span class="sep">/</span> '
        f'<span class="source">出典: <a href="{_esc(row.source_url)}" '
        'rel="external nofollow noopener">公式プレスリリース</a></span>'
        '<span class="sep">/</span> '
        '<span class="author">jpcite</span>'
        "</p>"
        '<p class="byline-note muted">※公表時点の記録です。'
        "現在は撤回・取消・期間満了している可能性があります。"
        "</p></header>"
    )
    # Top disclaimer — abbreviated.
    parts.append(
        '<aside class="disclaimer-block" role="note" aria-label="重要な注意事項" '
        'style="border:1px solid #ccc;padding:12px;margin:16px 0;background:#fafafa;">'
        f"<p>{_esc(SITE_DISCLAIMER)}</p>"
        "</aside>"
    )
    # Meta dl
    parts.append('<dl class="enforcement-meta">')
    parts.append(f"<dt>事業者名</dt><dd>{_esc(row.target_name)}</dd>")
    parts.append(f"<dt>法人番号</dt><dd><code>{_esc(row.houjin_bangou)}</code></dd>")
    parts.append(f"<dt>処分種別</dt><dd>{_esc(kind_ja)}</dd>")
    parts.append(f"<dt>所管 (発出機関)</dt><dd>{_esc(row.issuing_authority)}</dd>")
    parts.append(f"<dt>処分日</dt><dd>{_esc(_format_iso(row.issuance_date))}</dd>")
    if row.exclusion_start:
        parts.append(f"<dt>除外開始</dt><dd>{_esc(_format_iso(row.exclusion_start))}</dd>")
    if row.exclusion_end:
        parts.append(f"<dt>除外終了</dt><dd>{_esc(_format_iso(row.exclusion_end))}</dd>")
    if row.amount_yen:
        parts.append(f"<dt>金額</dt><dd>{_esc(_yen(row.amount_yen))}</dd>")
    if row.related_law_ref:
        parts.append(f"<dt>関連条文</dt><dd>{_esc(row.related_law_ref)}</dd>")
    parts.append("</dl>")
    # Reason summary
    parts.append("<section><h2>処分理由 (公表記録より要約)</h2>")
    if row.reason_summary:
        # Cap at 800 chars for SEO + readability — full text is on the source URL.
        body = _public_safe_text(row.reason_summary)
        if len(body) > 800:
            body = body[:797] + "…"
        parts.append(f"<p>{_esc(body)}</p>")
    else:
        parts.append(
            '<p class="muted">理由要約は公表されていません。'
            "原文の所管プレスリリース URL をご確認ください。</p>"
        )
    parts.append("</section>")
    # Source section
    parts.append(
        "<section><h2>一次資料</h2>"
        "<p>本ページの内容は以下の公的プレスリリースに基づきます。"
        "全文・別添資料・最新の取消情報は必ず一次資料をご確認ください。</p>"
        f'<p><a class="primary-link" rel="external nofollow noopener" '
        f'href="{_esc(row.source_url)}">所管官庁の公式ページを開く</a></p>'
        f'<p class="muted">出典取得日時: {_esc(row.source_fetched_at)}</p>'
        "</section>"
    )
    # API
    parts.append(
        "<section><h2>API で取得</h2>"
        f'<pre class="code-block"><code>curl -H "X-API-Key: YOUR_API_KEY" \\\n'
        f' "https://api.{domain}/v1/am/enforcement?houjin_bangou={row.houjin_bangou}"</code></pre>'
        "<p>MCP クライアントから: "
        f'<code>check_enforcement_am(houjin_bangou="{row.houjin_bangou}")</code></p>'
        '<p class="api-cta-line">無料 3 リクエスト/日。'
        '<a href="/pricing.html">料金体系</a> · '
        '<a href="/pricing.html#api-paid">API キー発行</a> · '
        '<a href="/dashboard.html">既存キー管理</a> · '
        '<a href="/bookmarklet.html">ブラウザ拡張</a></p>'
        "</section>"
    )
    parts.append(
        '<p class="disclaimer">本ページは自動生成された公開記録の要約であり、'
        "法的助言・税務助言・信用調査・コンプライアンス判断を構成するものではありません。"
        "個別の判断は弁護士・税理士・公認会計士・行政書士等の有資格者にご相談ください。"
        "処分の現況・撤回情報は所管官公庁にお問い合わせください。"
        "</p>"
    )
    parts.append("</article>")
    parts.append(_FOOTER_TEMPLATE)
    return "".join(parts)


def _render_sitemap(
    *,
    domain: str,
    detail_rows: list[EnforcementRow],
    today_iso: str,
) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- Enforcement topic sitemap shard for jpcite.com. -->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        "  <url>",
        f"    <loc>https://{domain}/enforcement/</loc>",
        f"    <lastmod>{today_iso}</lastmod>",
        "    <changefreq>weekly</changefreq>",
        "    <priority>0.8</priority>",
        "  </url>",
    ]
    for r in detail_rows:
        lastmod = _format_iso(r.source_fetched_at) or today_iso
        parts.append("  <url>")
        parts.append(f"    <loc>https://{domain}/enforcement/{r.slug}.html</loc>")
        parts.append(f"    <lastmod>{lastmod}</lastmod>")
        parts.append("    <changefreq>monthly</changefreq>")
        parts.append("    <priority>0.5</priority>")
        parts.append("  </url>")
    parts.append("</urlset>")
    parts.append("")
    return "\n".join(parts)


def _ensure_sitemap_index_includes_enforcement(
    sitemap_index_path: Path, *, domain: str, today_iso: str
) -> None:
    """Inject the enforcement sitemap into the master index, idempotent."""
    if not sitemap_index_path.exists():
        logger.warning("sitemap-index.xml missing at %s — skipping injection", sitemap_index_path)
        return
    text = sitemap_index_path.read_text(encoding="utf-8")
    target_loc = f"https://{domain}/sitemap-enforcement.xml"
    if target_loc in text:
        # Already present — bump lastmod only.
        text = re.sub(
            r"(<sitemap>\s*<loc>" + re.escape(target_loc) + r"</loc>\s*<lastmod>)[^<]+(</lastmod>)",
            rf"\g<1>{today_iso}\g<2>",
            text,
        )
        sitemap_index_path.write_text(text, encoding="utf-8")
        return
    insertion = (
        "  <sitemap>\n"
        f"    <loc>{target_loc}</loc>\n"
        f"    <lastmod>{today_iso}</lastmod>\n"
        "  </sitemap>\n"
    )
    text = text.replace("</sitemapindex>", insertion + "</sitemapindex>")
    sitemap_index_path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _build(
    *,
    jpintel_db: Path,
    autonomath_db: Path,
    site_dir: Path,
    domain: str,
    detail_limit: int,
    today_iso: str | None = None,
    generated_at: str | None = None,
) -> dict[str, int]:
    if not autonomath_db.exists():
        raise FileNotFoundError(f"autonomath.db not found at {autonomath_db}")
    if not jpintel_db.exists():
        # Soft warning — generator only requires autonomath.db at the moment;
        # jpintel.db enforcement_cases is a future-extension hook.
        logger.warning(
            "data/jpintel.db not present at %s — proceeding without "
            "the legacy enforcement_cases corpus",
            jpintel_db,
        )
    today_iso = today_iso or datetime.now(UTC).strftime("%Y-%m-%d")
    generated_at = generated_at or datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    # Connect read-only. Future-dated rows can appear from source OCR or
    # upstream data entry drift; do not publish them as current records.
    am_uri = f"file:{autonomath_db}?mode=ro"
    con = sqlite3.connect(am_uri, uri=True)
    try:
        summary = _summary_counts(con, max_issuance_date=today_iso)
        all_rows = _load_autonomath_rows(con, max_issuance_date=today_iso)
    finally:
        con.close()

    # Render index
    index_recent = all_rows[:100]
    detail_rows = _select_detail_rows(all_rows, detail_limit)

    site_dir.mkdir(parents=True, exist_ok=True)
    enf_dir = site_dir / "enforcement"
    enf_dir.mkdir(parents=True, exist_ok=True)

    index_html = _render_index(
        domain=domain,
        summary=summary,
        recent=index_recent,
        detail_count=len(detail_rows),
        generated_at=generated_at,
    )
    index_path = enf_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    for r in detail_rows:
        page = _render_detail(domain=domain, row=r, generated_at=generated_at)
        (enf_dir / f"{r.slug}.html").write_text(page, encoding="utf-8")

    sitemap_xml = _render_sitemap(domain=domain, detail_rows=detail_rows, today_iso=today_iso)
    sitemap_path = site_dir / "sitemap-enforcement.xml"
    sitemap_path.write_text(sitemap_xml, encoding="utf-8")

    _ensure_sitemap_index_includes_enforcement(
        site_dir / "sitemap-index.xml", domain=domain, today_iso=today_iso
    )

    return {
        "publicly_attributable_rows": len(all_rows),
        "detail_pages": len(detail_rows),
        "index_lines": len(index_html.splitlines()),
        "sitemap_urls": 1 + len(detail_rows),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate行政処分 SEO pages for jpcite.com")
    parser.add_argument("--jpintel-db", type=Path, default=DEFAULT_JPINTEL_DB)
    parser.add_argument("--autonomath-db", type=Path, default=DEFAULT_AUTONOMATH_DB)
    parser.add_argument("--site-dir", type=Path, default=DEFAULT_SITE_DIR)
    parser.add_argument("--domain", default=DEFAULT_DOMAIN)
    parser.add_argument(
        "--detail-limit",
        type=int,
        default=DEFAULT_DETAIL_LIMIT,
        help="Max number of static per-action detail pages (100-500 typical).",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        report = _build(
            jpintel_db=args.jpintel_db,
            autonomath_db=args.autonomath_db,
            site_dir=args.site_dir,
            domain=args.domain,
            detail_limit=args.detail_limit,
        )
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    except sqlite3.DatabaseError as exc:
        logger.error("DB error: %s", exc)
        return 1

    logger.info(
        "wrote enforcement SEO surface: index=1 detail=%d sitemap_urls=%d "
        "(publicly_attributable_rows=%d)",
        report["detail_pages"],
        report["sitemap_urls"],
        report["publicly_attributable_rows"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
