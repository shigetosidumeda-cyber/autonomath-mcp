#!/usr/bin/env python3
"""Generate per-record SEO pages for ``enforcement_cases`` (jpintel.db).

This complements ``scripts/etl/generate_enforcement_seo_pages.py`` (which
emits a summary index + ~300 ``act-*`` detail pages sampled from the
larger ``am_enforcement_detail`` corpus on autonomath.db).

Scope here: ONE static HTML page per row in ``enforcement_cases``
(1,185 rows on data/jpintel.db) — the 会計検査院 / 厚労省 不正受給 公開記録
subset. These are clawback / penalty events with primary URLs.

Target search intent
--------------------
- "<法人名 / 自治体名> 行政処分"
- "<制度名> 不正受給"
- "M&A デューデリ 行政処分 過去"      (M&A advisor)
- "信用金庫 与信前 公的処分 履歴"     (信金渉外 due diligence)

Output
------
- site/enforcement/case-{slug}.html    (per-record page)
- site/sitemap-enforcement-cases.xml   (per-record sitemap)
  NOTE: we write a SEPARATE sitemap file so the existing
  ``site/sitemap-enforcement.xml`` (managed by the etl script for the
  am_enforcement_detail corpus + act-*.html pages) is NOT clobbered.

Honest constraints
------------------
* Read-only against jpintel.db.
* NO LLM calls — pure SQL + string templating (mirrors program.html).
* PII gate: visible HTML hides recipient names entirely when
  ``recipient_kind`` ∈ {''corporation','organization_other','houjin'}
  AND no houjin_bangou is present (i.e. could be sole proprietor).
  自治体・国立大学法人 等は名称表示 OK。会計検査院 anonymized_jbaudit
  rows show only the bureau / prefecture string. 個人名は一切表示しない。
* No aggregator-derived source labels. ``source_url`` is the recipient
  ministry's own page (会計検査院 / 厚労省 / 金融庁 / etc.).
* No "Phase" / "MVP" / "Free tier" / 旧 brand strings.

Usage
-----
    .venv/bin/python scripts/generate_enforcement_pages.py
    .venv/bin/python scripts/generate_enforcement_pages.py \\
        --db data/jpintel.db --site-dir site --domain jpcite.com

If ``--db`` is missing (no jpintel.db / no autonomath.db), the script
writes only a marker page at site/enforcement/cases-index-marker.html
and exits 0 — operator hosts must never crash on absent data.

Exit codes
----------
0 success
1 fatal (writable site dir missing, template mismatch)
"""

from __future__ import annotations

import argparse
import hashlib
import html as htmlmod
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

logger = logging.getLogger("jpcite.generate_enforcement_pages")

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_AUTONOMATH_DB = Path(os.environ.get("AUTONOMATH_DB_PATH", str(REPO_ROOT / "autonomath.db")))
DEFAULT_SITE_DIR = REPO_ROOT / "site"
DEFAULT_DOMAIN = "jpcite.com"
JST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------------------
# PII / display gate
# ---------------------------------------------------------------------------
# Visible HTML hides individual / unverified recipient names. Legal-entity
# suffixes (Konosu walk allowlist) flip the gate to "show".
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
    "学校法人",
    "社会福祉法人",
    "一般社団法人",
    "公益社団法人",
    "一般財団法人",
    "公益財団法人",
    "独立行政法人",
    "国立大学法人",
    "公立大学法人",
    "特殊法人",
    "認可法人",
)
# 自治体 (municipality) is always safe to display (公的主体).
MUNICIPAL_KINDS = frozenset({"municipality"})
# anonymized_jbaudit: 会計検査院 が既に匿名化済み (実体は 県名 / 事業者種別 のみ)。
# 名称をそのまま表示してよい (会計検査院公表時点で識別性を消した記録)。
ANON_KINDS = frozenset({"anonymized_jbaudit"})


def has_houjin_suffix(name: str | None) -> bool:
    if not name:
        return False
    return any(s in name for s in HOUJIN_SUFFIXES)


def is_publicly_attributable(row: dict) -> bool:
    """Return True iff visible HTML may carry the recipient_name verbatim.

    Rules:
      - municipality / anonymized_jbaudit → always True.
      - houjin_bangou present (13 digits) AND name has houjin suffix → True.
      - otherwise → False (could be sole proprietor → name redacted).
    """
    kind = (row.get("recipient_kind") or "").strip()
    if kind in MUNICIPAL_KINDS or kind in ANON_KINDS:
        return True
    name = row.get("recipient_name") or ""
    bangou = (row.get("recipient_houjin_bangou") or "").strip()
    bangou_ok = len(bangou) == 13 and bangou.isdigit()
    return bool(bangou_ok and has_houjin_suffix(name))


def displayable_recipient(row: dict) -> str:
    """Return what to put in the H1 / breadcrumb. Falls back to bureau/prefecture."""
    if is_publicly_attributable(row):
        nm = (row.get("recipient_name") or "").strip()
        if nm:
            return nm
    # Fallback labels — these are always safe (no PII).
    parts = []
    if row.get("ministry"):
        parts.append(row["ministry"])
    if row.get("bureau") and row["bureau"] != row.get("ministry"):
        parts.append(row["bureau"])
    if row.get("prefecture"):
        parts.append(row["prefecture"])
    label = " / ".join([p for p in parts if p])
    return label or "公的補助 不正受給 公開記録"


# ---------------------------------------------------------------------------
# Slug
# ---------------------------------------------------------------------------
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def case_slug(case_id: str) -> str:
    """Stable filesystem-safe slug. Always prefixed ``case-`` so it cannot
    collide with the existing ``act-*.html`` page family."""
    sanitized = _SLUG_RE.sub("-", case_id.strip())
    sanitized = sanitized.strip("-")
    if not sanitized:
        sanitized = hashlib.sha1(case_id.encode("utf-8")).hexdigest()[:12]
    if len(sanitized) > 80:
        suffix = hashlib.sha1(case_id.encode("utf-8")).hexdigest()[:8]
        sanitized = sanitized[:60] + "-" + suffix
    return f"case-{sanitized}"


# ---------------------------------------------------------------------------
# Event-type labels (no hyperbole)
# ---------------------------------------------------------------------------
EVENT_TYPE_LABEL = {
    "clawback": "補助金 返還命令",
    "penalty": "課徴金 / 罰則",
    "suspension": "業務停止 / 停止命令",
    "withdrawal": "認定取消",
}


def event_label(ev: str | None) -> str:
    if not ev:
        return "行政処分"
    return EVENT_TYPE_LABEL.get(ev, ev)


def jpy_label(yen: int | float | None) -> str:
    if yen is None or yen == 0:
        return ""
    try:
        y = int(yen)
    except Exception:  # noqa: BLE001
        return ""
    return f"¥{y:,}"


# ---------------------------------------------------------------------------
# Law / program join (lookup is best-effort; no LLM, simple LIKE)
# ---------------------------------------------------------------------------
def lookup_laws(cur: sqlite3.Cursor, legal_basis: str | None) -> list[dict]:
    """Map ``legal_basis`` text (e.g. '補助金等に係る予算の執行の適正化に関する法律 第17条')
    to law rows. We strip article-suffix tail and LIKE-match law_title."""
    if not legal_basis:
        return []
    # Strip article tail "第N条" / "第N条・第M条" / "施行令" handled too.
    base = re.sub(r"\s*第[一二三四五六七八九十百千〇0-9]+条.*$", "", legal_basis).strip()
    if not base:
        base = legal_basis
    try:
        cur.execute(
            "SELECT unified_id, law_title, law_short_title, source_url FROM laws "
            "WHERE law_title = ? OR law_title LIKE ? LIMIT 5",
            (base, f"{base}%"),
        )
        out = [dict(r) for r in cur.fetchall()]
    except sqlite3.OperationalError:
        out = []
    return out


def load_static_law_hrefs(site_dir: Path) -> dict[str, str]:
    """Map e-Gov source URLs from generated law markdown to static law URLs."""
    laws_dir = site_dir / "laws"
    out: dict[str, str] = {}
    if not laws_dir.exists():
        return out
    for md_path in laws_dir.glob("*.md"):
        try:
            head = md_path.read_text(encoding="utf-8", errors="ignore")[:1200]
        except OSError:
            continue
        if not head.startswith("---"):
            continue
        front_matter = head.split("---", 2)[1] if head.count("---") >= 2 else ""
        source_url = ""
        slug = md_path.stem
        for line in front_matter.splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "source_url":
                source_url = value.strip()
            elif key.strip() == "slug":
                slug = value.strip() or slug
        if source_url and slug and (laws_dir / f"{slug}.html").exists():
            out[source_url] = f"/laws/{slug}"
    return out


def lookup_programs(cur: sqlite3.Cursor, hint: str | None, limit: int = 4) -> list[dict]:
    """Match ``program_name_hint`` against programs.primary_name / aliases.
    Strip trailing 都道府県 / 事業 markers to broaden the search."""
    if not hint:
        return []
    # Trim noise: |, 第N章, 令和X年度, 「 」, []
    core = hint.split("|")[0]
    core = re.sub(r"^[ 　]*", "", core)
    core = re.sub(r"［.*?］", "", core)
    core = re.sub(r"\[.*?\]", "", core)
    core = re.sub(r"\(.*?\)", "", core)
    core = re.sub(r"（.*?）", "", core)
    core = core.strip("　 .")
    # Keep only the longest 12-char segment to avoid LIKE pathological matches.
    segments = re.split(r"[、・,、 　]+", core)
    segments = [s for s in segments if len(s) >= 6]
    if not segments:
        return []
    seed = max(segments, key=len)[:20]
    try:
        cur.execute(
            "SELECT unified_id, primary_name FROM programs "
            "WHERE excluded = 0 AND (primary_name LIKE ? OR aliases_json LIKE ?) "
            "AND source_url IS NOT NULL LIMIT ?",
            (f"%{seed}%", f"%{seed}%", limit),
        )
        return [dict(r) for r in cur.fetchall()]
    except sqlite3.OperationalError:
        return []


# ---------------------------------------------------------------------------
# JSON-LD
# ---------------------------------------------------------------------------
def law_href(law: dict, law_hrefs: dict[str, str], domain: str) -> str:
    source_url = law.get("source_url") or ""
    static_href = law_hrefs.get(source_url)
    if static_href:
        return f"https://{domain}{static_href}"
    if source_url:
        return source_url
    title = law.get("law_title") or law.get("law_short_title") or law.get("unified_id") or ""
    return (
        "https://laws.e-gov.go.jp/search/elawsSearch/elaws_search/lsg0100/"
        f"?searchKeyword={quote_plus(str(title)[:80])}"
    )


def law_link_rel(href: str, domain: str) -> str:
    if href.startswith(f"https://{domain}/") or href.startswith("/"):
        return ""
    return ' rel="external nofollow noopener"'


def build_json_ld(
    row: dict,
    domain: str,
    slug: str,
    laws: list[dict],
    programs: list[dict],
    law_hrefs: dict[str, str],
) -> str:
    """Schema.org GovernmentAction (LegalAction is the closest fit for
    補助金返還命令 / 課徴金納付命令). We keep the @graph slim — the global
    Organization/WebSite/Service are duplicated in the common include
    embedded in the template body."""
    ev = row.get("event_type")
    label = event_label(ev)
    disclosed = row.get("disclosed_date") or ""
    ministry = row.get("ministry") or "日本国政府機関"
    url = f"https://{domain}/enforcement/{slug}"

    if ev == "penalty":
        pass

    actor_name = displayable_recipient(row)
    object_program = row.get("program_name_hint") or ""

    graph: list[dict] = [
        {
            "@type": "GovernmentService",
            "@id": f"{url}#service",
            "serviceType": label,
            "name": f"{actor_name} — {label}",
            "url": url,
            "provider": {"@type": "GovernmentOrganization", "name": ministry},
            "areaServed": {"@type": "Country", "name": "Japan"},
            "termsOfService": row.get("source_url") or None,
            "description": row.get("reason_excerpt") or None,
            "dateModified": row.get("fetched_at") or None,
            "datePublished": disclosed or None,
        },
        {
            "@type": "BreadcrumbList",
            "@id": f"{url}#bc",
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
                    "name": "行政処分",
                    "item": f"https://{domain}/enforcement/",
                },
                {"@type": "ListItem", "position": 3, "name": label, "item": url},
            ],
        },
    ]

    if object_program:
        graph[0]["object"] = {"@type": "GovernmentService", "name": object_program}

    if row.get("amount_improper_grant_yen"):
        graph[0]["potentialAction"] = {
            "@type": "PayAction",
            "name": "補助金返還",
            "price": str(int(row["amount_improper_grant_yen"])),
            "priceCurrency": "JPY",
        }

    if laws:
        graph.append(
            {
                "@type": "Legislation",
                "@id": f"{url}#law",
                "name": laws[0]["law_title"],
                "url": law_href(laws[0], law_hrefs, domain),
            }
        )

    # AEO Wave 18: explicit citation field on the GovernmentService node so
    # AI agents (Schema.org-aware crawlers) see both the primary public
    # record URL and the jpcite canonical URL where this fact is served.
    src_url = row.get("source_url") or ""
    citation_list: list[dict] = []
    if src_url:
        citation_list.append(
            {
                "@type": "CreativeWork",
                "name": "一次公的記録",
                "url": src_url,
            }
        )
    citation_list.append(
        {
            "@type": "WebPage",
            "name": "jpcite 機械可読化レイヤー",
            "url": url,
        }
    )
    if citation_list:
        graph[0]["citation"] = citation_list

    payload = {"@context": "https://schema.org", "@graph": [g for g in graph if g]}
    # Drop None-valued keys for cleaner output.
    cleaned: list = []
    for g in payload["@graph"]:
        cleaned.append({k: v for k, v in g.items() if v is not None})
    payload["@graph"] = cleaned
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def esc(s: object) -> str:
    if s is None:
        return ""
    return htmlmod.escape(str(s), quote=True)


def program_share_href(unified_id: str) -> str:
    """Return a static-safe program URL for a UNI id.

    Enforcement pages only have the program unified_id from the DB join, while
    generated program pages are slug-based. Route through the existing share
    page so the link resolves without guessing a slug.
    """
    return f"/programs/share.html?ids={esc(unified_id)}"


def page_html(
    row: dict,
    domain: str,
    slug: str,
    laws: list[dict],
    programs: list[dict],
    law_hrefs: dict[str, str],
) -> str:
    label = event_label(row.get("event_type"))
    actor = displayable_recipient(row)
    disclosed = row.get("disclosed_date") or ""
    ministry = row.get("ministry") or ""
    bureau = row.get("bureau") or ""
    prefecture = row.get("prefecture") or ""
    src = row.get("source_url") or ""
    src_title = row.get("source_title") or row.get("program_name_hint") or "所管官庁の公式ページ"
    amount_total = row.get("amount_improper_grant_yen") or row.get("amount_yen") or 0
    project_cost = row.get("amount_project_cost_yen") or 0
    grant_paid = row.get("amount_grant_paid_yen") or 0
    reason = row.get("reason_excerpt") or ""
    legal_basis = row.get("legal_basis") or ""
    program_hint = row.get("program_name_hint") or ""
    bangou = (row.get("recipient_houjin_bangou") or "").strip()
    bangou_shown = (
        bangou if (len(bangou) == 13 and bangou.isdigit() and is_publicly_attributable(row)) else ""
    )

    title_chunks = [actor, label]
    if disclosed:
        title_chunks.append(f"({disclosed})")
    page_title = " — ".join([t for t in title_chunks if t]) + " | jpcite"

    desc_parts: list[str] = []
    if actor:
        desc_parts.append(f"{actor} に関する{label}の公開記録")
    if ministry:
        desc_parts.append(f"所管: {ministry}")
    if disclosed:
        desc_parts.append(f"公表日 {disclosed}")
    if program_hint:
        desc_parts.append(f"制度名: {program_hint[:50]}")
    desc_parts.append("出典: 一次資料あり。jpcite が政府公表記録から取得。")
    meta_desc = "。".join(desc_parts)[:300]

    json_ld = build_json_ld(row, domain, slug, laws, programs, law_hrefs)

    # ---- Related law links ----
    if laws:
        law_lis = "".join(
            f'<li><a href="{esc(href := law_href(law, law_hrefs, domain))}"'
            f"{law_link_rel(href, domain)}>{esc(law['law_title'])}</a></li>"
            for law in laws
        )
        related_law_html = (
            f'<section><h2>関連法令</h2><ul class="related-list">{law_lis}</ul></section>'
        )
    elif legal_basis:
        related_law_html = (
            f"<section><h2>関連法令</h2><p>{esc(legal_basis)} "
            "(e-Gov 法令検索で全文を確認: "
            f'<a href="https://laws.e-gov.go.jp/search/elawsSearch/elaws_search/lsg0100/?searchKeyword={esc(legal_basis[:40])}" '
            'rel="external nofollow noopener">e-Gov</a>)</p></section>'
        )
    else:
        related_law_html = ""

    # ---- Related programs ----
    if programs:
        prog_lis = "".join(
            f'<li><a href="{program_share_href(p["unified_id"])}">{esc(p["primary_name"])}</a></li>'
            for p in programs
        )
        related_prog_html = (
            f"<section><h2>関連する公的制度</h2>"
            f'<p class="muted">jpcite の制度カタログから自動マッチ。詳細は各制度ページをご確認ください。</p>'
            f'<ul class="related-list">{prog_lis}</ul></section>'
        )
    else:
        related_prog_html = ""

    # ---- Amount detail ----
    amount_rows: list[str] = []
    if project_cost:
        amount_rows.append(f"<dt>事業費</dt><dd>{esc(jpy_label(project_cost))}</dd>")
    if grant_paid:
        amount_rows.append(f"<dt>交付済額</dt><dd>{esc(jpy_label(grant_paid))}</dd>")
    if amount_total:
        amount_rows.append(
            f"<dt>不正受給 / 返還 / 課徴金 額</dt><dd><strong>{esc(jpy_label(amount_total))}</strong></dd>"
        )
    amount_html = (
        f'<section><h2>金額</h2><dl class="enforcement-amount">{"".join(amount_rows)}</dl></section>'
        if amount_rows
        else ""
    )

    # ---- Meta block (omit fields we don't want visible) ----
    meta_rows: list[str] = []
    if actor and is_publicly_attributable(row):
        meta_rows.append(f"<dt>対象</dt><dd>{esc(actor)}</dd>")
    elif actor:
        meta_rows.append(
            f"<dt>対象</dt><dd>{esc(actor)} <span class='muted'>(個人特定不能化のため詳細非表示)</span></dd>"
        )
    if bangou_shown:
        meta_rows.append(f"<dt>法人番号</dt><dd><code>{esc(bangou_shown)}</code></dd>")
    meta_rows.append(f"<dt>処分種別</dt><dd>{esc(label)}</dd>")
    if ministry:
        meta_rows.append(f"<dt>所管</dt><dd>{esc(ministry)}</dd>")
    if bureau and bureau != ministry:
        meta_rows.append(f"<dt>担当局 / 地方</dt><dd>{esc(bureau)}</dd>")
    if prefecture:
        meta_rows.append(f"<dt>都道府県</dt><dd>{esc(prefecture)}</dd>")
    if disclosed:
        meta_rows.append(f"<dt>公表日</dt><dd>{esc(disclosed)}</dd>")
    if program_hint:
        meta_rows.append(f"<dt>制度名 (公表時)</dt><dd>{esc(program_hint[:200])}</dd>")
    meta_html = "<dl class='enforcement-meta'>" + "".join(meta_rows) + "</dl>"

    # ---- Reason ----
    reason_html = (
        f"<section><h2>処分理由 (公表記録より要約)</h2><p>{esc(reason)}</p></section>"
        if reason
        else ""
    )

    # ---- Use-case CTA (M&A / 信金) ----
    usecase_html = (
        "<section><h2>このページの使い方</h2>"
        '<ul class="usecase-list">'
        "<li>M&A 仲介・FA: 対象企業の過去処分の有無を 1 ページで一次資料リンク付きで確認。</li>"
        "<li>信用金庫・信金渉外: 与信前 due diligence で取引先の公的処分履歴をスキャン。</li>"
        "<li>会計事務所・税理士: 補助金関与先のリスクヒアリングで公表記録を提示。</li>"
        "<li>研究者・記者: 一次資料 URL に直接ジャンプし、原本確認。</li>"
        "</ul></section>"
    )

    breadcrumb = (
        '<nav class="breadcrumb" aria-label="パンくず">'
        f'<a href="/">ホーム</a> &rsaquo; <a href="/enforcement/">行政処分</a> &rsaquo; '
        f'<span aria-current="page">{esc(label)}</span></nav>'
    )

    primary_source_block = ""
    if src:
        primary_source_block = (
            "<section><h2>一次資料</h2>"
            "<p>本ページの内容は以下の公的記録に基づきます。最新の取消・撤回情報は必ず一次資料をご確認ください。</p>"
            f'<p><a class="primary-link" rel="external nofollow noopener" href="{esc(src)}">{esc(src_title)} を開く</a></p>'
            f'<p class="muted">出典取得日時: {esc(row.get("fetched_at") or "")}</p>'
            "</section>"
        )

    canonical = f"https://{domain}/enforcement/{slug}"

    # AEO Wave 18: explicit "Cite this in AI" block for the rendered HTML body.
    cite_url_short = f"{domain}/enforcement/{slug}"
    cite_in_ai_html = (
        '<section aria-labelledby="cite-title" class="cite-this-section">'
        '<h2 id="cite-title">Cite this in AI / 引用</h2>'
        "<p>AI 回答に本処分記録を引用させる時の canonical URL です。出典 (jpcite) の明記をお願いします。"
        + (
            f'一次資料は <a href="{esc(src)}" rel="external nofollow noopener">公的公表記録</a>。'
            if src
            else ""
        )
        + "</p>"
        '<pre class="code-block cite-block"><code>'
        f"&gt; {esc(actor)} — {esc(label)} "
        f"(出典: https://{esc(cite_url_short)}、jpcite が政府公表記録を機械可読化)"
        "</code></pre>"
        '<p class="muted">'
        f'<button type="button" class="copy-cite-btn" data-cite-url="https://{esc(cite_url_short)}" '
        f"onclick=\"navigator.clipboard&amp;&amp;navigator.clipboard.writeText('https://{esc(cite_url_short)}')\">"
        "URL をコピー</button> "
        f'<a href="https://{esc(cite_url_short)}">https://{esc(cite_url_short)}</a>'
        "</p>"
        "</section>"
    )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="theme-color" content="#ffffff">
<title>{esc(page_title)}</title>
<meta name="description" content="{esc(meta_desc)}">
<meta name="author" content="jpcite">
<meta name="publisher" content="jpcite">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta property="og:title" content="{esc(page_title)}">
<meta property="og:description" content="{esc(meta_desc)}">
<meta property="og:type" content="article">
<meta property="og:url" content="{esc(canonical)}">
<meta property="og:image" content="https://{esc(domain)}/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="ja_JP">
<meta property="og:site_name" content="jpcite">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(page_title)}">
<meta name="twitter:description" content="{esc(meta_desc)}">
<meta name="twitter:image" content="https://{esc(domain)}/assets/og-twitter.png">
<link rel="canonical" href="{esc(canonical)}">
<link rel="alternate" hreflang="ja" href="{esc(canonical)}">
<link rel="alternate" hreflang="x-default" href="{esc(canonical)}">
<link rel="icon" href="/assets/favicon-v2.svg" type="image/svg+xml">
<link rel="stylesheet" href="/styles.css?v=20260515c">
<script type="application/ld+json">
{json_ld}
</script>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
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
<main id="main" class="enforcement-page">
 <div class="container">
{breadcrumb}
<article>
<header>
<h1>{esc(actor)} — {esc(label)}</h1>
<p class="byline">
<span class="updated">出典取得: {esc(row.get("fetched_at") or "")}</span>
{('<span class="sep">/</span> <span class="source">出典: <a href="' + esc(src) + '" rel="external nofollow noopener">公的記録</a></span>') if src else ""}
<span class="sep">/</span> <span class="author">jpcite</span>
</p>
<p class="byline-note muted">※公表時点の記録です。撤回・取消・期間満了している可能性があります。最新情報は一次資料をご確認ください。</p>
</header>
<aside class="disclaimer-block" role="note" aria-label="重要な注意事項" style="border:1px solid #ccc;padding:12px;margin:16px 0;background:#fafafa;">
<p>本ページは jpcite が政府・自治体の公式公表記録から機械収集した行政処分の公開記録です。掲載対象は法人格を持つ事業者・自治体・公的法人のみで、個人事業主や特定個人が識別される可能性のある記録は名称表示を抑制しています。処分は公表時点の記録であり、現時点では撤回・取消・期間満了している可能性があります。監査責任・法的判断は弁護士・税理士・公認会計士など有資格者へご相談ください。</p>
</aside>
{meta_html}
{amount_html}
{reason_html}
{related_law_html}
{related_prog_html}
{primary_source_block}
{usecase_html}
<section>
<h2>API で取得</h2>
<pre class="code-block"><code>curl -H "X-API-Key: YOUR_API_KEY" \\
 "https://api.{esc(domain)}/v1/enforcement/cases/{esc(row.get("case_id") or "")}"</code></pre>
<p class="api-cta-line">公的記録 1,185 件をプログラムから検索: <a href="/docs/">ドキュメント</a> · <a href="/pricing.html#api-paid">API キー発行</a> · <a href="/dashboard.html">既存キー管理</a></p>
</section>
{cite_in_ai_html}
<p class="disclaimer">本ページは自動生成された公開記録の要約であり、法的助言・税務助言・信用調査・コンプライアンス判断を構成するものではありません。個別の判断は弁護士・税理士・公認会計士・行政書士等の有資格者にご相談ください。処分の現況・撤回情報は所管官公庁にお問い合わせください。</p>
</article>
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
 </div>
</footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------
def write_sitemap(out_path: Path, domain: str, slugs_with_dates: list[tuple[str, str]]) -> None:
    today = datetime.now(JST).date().isoformat()
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- Enforcement case sitemap shard for jpcite.com. -->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for slug, disclosed in slugs_with_dates:
        lastmod = disclosed or today
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", lastmod):
            lastmod = today
        lines.append("  <url>")
        lines.append(f"    <loc>https://{domain}/enforcement/{slug}</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("    <changefreq>monthly</changefreq>")
        lines.append("    <priority>0.5</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Marker (no DB fallback)
# ---------------------------------------------------------------------------
def write_marker(site_dir: Path, domain: str, reason: str) -> None:
    out = site_dir / "enforcement" / "cases-index-marker.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    body = f"""<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="UTF-8">
<title>行政処分 公開記録 — データ準備中 | jpcite</title>
<meta name="robots" content="noindex, nofollow">
<link rel="canonical" href="https://{esc(domain)}/enforcement/">
</head><body>
<main><h1>行政処分 公開記録 — データ準備中</h1>
<p>{esc(reason)}</p>
<p><a href="/">jpcite トップへ</a></p>
</main></body></html>
"""
    out.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--db", type=Path, default=DEFAULT_DB, help="jpintel.db path (enforcement_cases)"
    )
    p.add_argument(
        "--autonomath-db",
        type=Path,
        default=DEFAULT_AUTONOMATH_DB,
        help="autonomath.db path (used only for fallback marker check)",
    )
    p.add_argument("--site-dir", type=Path, default=DEFAULT_SITE_DIR)
    p.add_argument("--domain", default=DEFAULT_DOMAIN)
    p.add_argument("--limit", type=int, default=0, help="0 = no limit (all rows)")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s %(message)s",
    )

    site_dir: Path = args.site_dir
    enforcement_dir = site_dir / "enforcement"
    enforcement_dir.mkdir(parents=True, exist_ok=True)

    db_path: Path = args.db
    if not db_path.exists():
        # Fallback marker only — also check autonomath.db for completeness signal.
        am_exists = args.autonomath_db.exists() and args.autonomath_db.stat().st_size > 0
        msg = f"jpintel.db not present ({db_path}); autonomath.db present={am_exists}. Re-run after data sync."
        logger.warning(msg)
        write_marker(site_dir, args.domain, msg)
        print(
            json.dumps(
                {"db_read_ok": False, "generated": 0, "marker": True, "reason": msg},
                ensure_ascii=False,
            )
        )
        return 0

    try:
        con = sqlite3.connect(str(db_path))
    except sqlite3.OperationalError as e:
        msg = f"failed to open jpintel.db: {e}"
        logger.error(msg)
        write_marker(site_dir, args.domain, msg)
        print(
            json.dumps(
                {"db_read_ok": False, "generated": 0, "marker": True, "reason": msg},
                ensure_ascii=False,
            )
        )
        return 0

    con.row_factory = sqlite3.Row
    cur = con.cursor()

    sql = (
        "SELECT * FROM enforcement_cases "
        "WHERE source_url IS NOT NULL AND source_url != '' "
        "ORDER BY disclosed_date DESC, case_id ASC"
    )
    if args.limit and args.limit > 0:
        sql += f" LIMIT {int(args.limit)}"
    cur.execute(sql)
    rows = [dict(r) for r in cur.fetchall()]

    written = 0
    skipped = 0
    law_link_count_total = 0
    slugs_for_sitemap: list[tuple[str, str]] = []
    law_hrefs = load_static_law_hrefs(site_dir)

    for r in rows:
        cid = r.get("case_id") or ""
        if not cid:
            skipped += 1
            continue
        slug = case_slug(cid)
        laws = lookup_laws(cur, r.get("legal_basis"))
        programs = lookup_programs(cur, r.get("program_name_hint"))
        law_link_count_total += len(laws)
        html_str = page_html(r, args.domain, slug, laws, programs, law_hrefs)
        out_path = enforcement_dir / f"{slug}.html"
        # Idempotent write: skip if identical
        if out_path.exists():
            try:
                prev = out_path.read_text(encoding="utf-8")
                if prev == html_str:
                    written += 1  # count as present
                    slugs_for_sitemap.append((slug, r.get("disclosed_date") or ""))
                    continue
            except Exception:  # noqa: BLE001
                pass
        out_path.write_text(html_str, encoding="utf-8")
        written += 1
        slugs_for_sitemap.append((slug, r.get("disclosed_date") or ""))

    # Sitemap (separate file, doesn't touch existing sitemap-enforcement.xml)
    sitemap_path = site_dir / "sitemap-enforcement-cases.xml"
    write_sitemap(sitemap_path, args.domain, slugs_for_sitemap)

    avg_law_links = (law_link_count_total / written) if written else 0.0
    report = {
        "db_read_ok": True,
        "db_path": str(db_path),
        "rows_scanned": len(rows),
        "generated": written,
        "skipped_no_case_id": skipped,
        "avg_related_law_links": round(avg_law_links, 3),
        "sitemap_path": str(sitemap_path),
        "out_dir": str(enforcement_dir),
    }
    print(json.dumps(report, ensure_ascii=False))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
