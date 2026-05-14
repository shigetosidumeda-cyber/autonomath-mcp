#!/usr/bin/env python3
"""Generate per-law static HTML pages for jpcite.com.

Input:
    autonomath.db   (am_law metadata + am_law_article full text + body_en)
    data/jpintel.db (laws + program_law_refs for related-program backlinks)

Output:
    site/laws/{slug}.html        (one per law with full-text articles; JA)
    site/en/laws/{slug}.html     (only if the law has at least one body_en article; EN)
    site/sitemap-laws.xml        (regenerated; <urlset> for the JA cohort)
    site/sitemap-laws-en.xml     (regenerated; <urlset> for the EN cohort)

A "law with full-text articles" is one row in am_law that has at least one
am_law_article child whose text_full IS NOT NULL AND text_full != ''. The
expected count at 2026-05-11 snapshot is 6,493 (CLAUDE.md §Overview).

SEO contract per page:
    - <title> = 法令名 + (公布日 if known) — JA / canonical_name_en + (promulgated) — EN
    - meta description = first 160 chars of article #1 text or summary if present
    - canonical link to https://jpcite.com/laws/{slug} (or /en/laws/{slug})
    - hreflang ja/en + x-default (always points at the JA copy)
    - OGP article + Twitter summary_large_image
    - Schema.org Legislation JSON-LD (https://schema.org/Legislation) with
        legislationIdentifier / legislationDate / legislationLegalForce
        / inLanguage / sameAs (e-Gov permalink) / publisher Organization
    - Table of contents = <a href="#art-{slug}"> per article_number
    - Related programs section = up to 12 programs from program_law_refs
        joined on the e-Gov law id (jpintel.db.laws.source_url ↔ am_law.e_gov_lawid)
    - e-Gov 出典 URL block with CC-BY 4.0 attribution

Brand rules (per CLAUDE.md §Non-negotiable constraints):
    - User-facing brand is "jpcite" — do NOT surface jpintel / jpcite / 税務会計AI.
    - No "Phase", no "MVP", no "Free tier" copy.
    - No LLM API import / no human-intervention surface (zero-touch ops).

DB-availability fallback (per task spec):
    - If neither autonomath.db (root) nor data/autonomath.db contains
        am_law_article, we still create a single marker page so the
        directory exists for downstream sitemap collation:
            site/laws/_unavailable.html  (`<!-- generated_at = data unavailable -->`)

Usage
-----
    python3 scripts/generate_law_pages.py
    python3 scripts/generate_law_pages.py --limit 10            # smoke
    python3 scripts/generate_law_pages.py --out site/laws \\
        --en-out site/en/laws --domain jpcite.com

Exit codes
----------
    0 success (incl. fallback marker path when DB unavailable)
    1 fatal (output dir cannot be created, unexpected DB exception)
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

try:
    from jpintel_mcp.utils.slug import program_static_url
except ImportError:  # pragma: no cover - checkout-only fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from jpintel_mcp.utils.slug import program_static_url

_LOG = logging.getLogger("generate_law_pages")
_JST = timezone(timedelta(hours=9))
_DEFAULT_DOMAIN = "jpcite.com"
_DEFAULT_OUT = Path("site/laws")
_DEFAULT_EN_OUT = Path("site/en/laws")
_DEFAULT_JPINTEL_DB = Path("data/jpintel.db")
_AUTONOMATH_DB_CANDIDATES = (
    Path("autonomath.db"),
    Path("data/autonomath.db"),
    Path("src/jpintel_mcp/autonomath.db"),
)

# e-Gov 法令検索 (デジタル庁) — the only sanctioned source per CLAUDE.md.
# License: CC-BY 4.0 https://creativecommons.org/licenses/by/4.0/deed.ja
# The disclaimer string below is held verbatim across MCP / REST / static
# surfaces and is intentionally NOT translated to match the operator-facing
# audit trail (migration 090 §3).
_EGOV_LICENSE_JA = (
    "本ページに表示される法令本文は、デジタル庁 e-Gov 法令検索"
    "(https://laws.e-gov.go.jp/) を出典とし、クリエイティブ・コモンズ"
    "表示 4.0 国際 (CC-BY 4.0) の下で提供されています。"
    "公式な法的効力を持つのは e-Gov 上の原本であり、本サイトの表示は参照用です。"
)
_EGOV_LICENSE_EN = (
    "Statutory text on this page is sourced from e-Gov Houreikensaku "
    "(Japan Digital Agency, https://laws.e-gov.go.jp/) under Creative "
    "Commons Attribution 4.0 International (CC-BY 4.0). The Japanese "
    "original on e-Gov is the only legally authoritative version; this "
    "page is provided for reference."
)
_BODY_EN_DISCLAIMER = (
    "Translations of Japanese laws on this page are courtesy translations "
    "sourced from the Japanese Ministry of Justice's e-Gov 日本法令外国語訳 "
    "(japaneselawtranslation.go.jp) under CC-BY 4.0. The Japanese-language "
    "original is the only legally authoritative version. jpcite provides "
    "these translations as a reference and assumes no responsibility for "
    "legal interpretation derived from them."
)

# Up to N related programs surfaced on each law page. Cap keeps the page
# render size predictable and reduces template drift when a hub law
# (e.g. 中小企業基本法) accrues hundreds of refs.
_RELATED_PROGRAMS_LIMIT = 12

# Article body truncation for the in-page render. Full text remains
# authoritative on e-Gov; this keeps individual law pages under ~1 MB
# even for hub laws (中小企業基本法, 租税特別措置法) without breaking SEO.
_ARTICLE_BODY_RENDER_MAX = 4000
_META_DESCRIPTION_MAX = 160

# Hub laws (e.g. 租税特別措置法, 地方税法) accumulate 1,000+ articles via
# the revision-history fan-out (am_law_article rolls every effective-date
# permutation as its own row). Rendering every article inline would push
# a single page past 9 MB, which (a) blows past Cloudflare Pages' 25 MB
# response cap once gzip + edge templating land, (b) blows past Google's
# 10 MB SEO crawl budget per URL, and (c) breaks the human-readability
# contract — nobody can scroll 4,000 articles. We cap at the first N
# canonical articles and surface a "remainder on e-Gov" notice so the
# canonical URL still earns the inbound link.
_ARTICLES_PER_PAGE_MAX = 250

# Slug derivation: am_law.canonical_id values look like "law:chusho-kihon",
# "law:chusho-kihon-rev-20250401", or "law:gyogyo-no-kyoka_2". We strip the
# leading "law:" prefix and ASCII-normalise the remainder. Underscore and
# revision suffixes are preserved as-is so the URL remains deterministic
# across reruns (idempotency contract for static-drift CI).
_SLUG_STRIP_PREFIX = "law:"
_SLUG_SAFE_RE = re.compile(r"[^a-z0-9._-]+")


def _slug_from_canonical_id(canonical_id: str) -> str:
    """Return a URL-safe slug from am_law.canonical_id."""
    s = canonical_id.strip().lower()
    if s.startswith(_SLUG_STRIP_PREFIX):
        s = s[len(_SLUG_STRIP_PREFIX) :]
    s = _SLUG_SAFE_RE.sub("-", s)
    s = s.strip("-._")
    # Defensive: a canonical_id of just "law:" would collapse to ""; never
    # write a file at site/laws/.html. The fallback "law" + sha would be
    # unstable across reruns, so we hard-fail by surfacing canonical_id.
    return s or f"unknown-{abs(hash(canonical_id)) % 0xFFFFFFFF:08x}"


def _today_jst_iso() -> str:
    return datetime.now(_JST).date().isoformat()


def _now_jst_iso() -> str:
    return datetime.now(_JST).strftime("%Y-%m-%dT%H:%M:%S%z")


def _resolve_autonomath_db(override: Path | None) -> Path | None:
    candidates: tuple[Path, ...] = (
        (override,) if override is not None else _AUTONOMATH_DB_CANDIDATES
    )
    for path in candidates:
        if path is None:
            continue
        try:
            if path.exists() and path.stat().st_size > 0:
                return path
        except OSError:
            continue
    return None


def _open_db_readonly(path: Path) -> sqlite3.Connection:
    # sqlite3 URI mode lets us open the 12 GB autonomath.db read-only
    # which is required because the production DB on Fly is mounted RO
    # for concurrent readers, and we want the same semantics locally.
    uri = f"file:{path}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


# -----------------------------------------------------------------------
# Data loaders
# -----------------------------------------------------------------------


def _load_laws_with_articles(am_db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return the cohort of laws that have at least one article with text_full."""
    sql = """
    SELECT
        l.canonical_id        AS canonical_id,
        l.canonical_name      AS canonical_name,
        l.short_name          AS short_name,
        l.law_number          AS law_number,
        l.category            AS category,
        l.first_enforced      AS first_enforced,
        l.last_amended_at     AS last_amended_at,
        l.ministry            AS ministry,
        l.egov_url            AS egov_url,
        l.e_gov_lawid         AS e_gov_lawid,
        l.status              AS status,
        l.subject_areas_json  AS subject_areas_json
    FROM am_law l
    WHERE l.canonical_id IN (
        SELECT DISTINCT a.law_canonical_id
        FROM am_law_article a
        WHERE a.text_full IS NOT NULL AND a.text_full != ''
    )
    ORDER BY l.canonical_id
    """
    return list(am_db.execute(sql))


def _load_articles_for_law(am_db: sqlite3.Connection, canonical_id: str) -> list[sqlite3.Row]:
    sql = """
    SELECT
        article_number,
        article_number_sort,
        title,
        text_full,
        body_en,
        body_en_source_url,
        body_en_license,
        effective_from,
        last_amended,
        source_url
    FROM am_law_article
    WHERE law_canonical_id = ?
        AND text_full IS NOT NULL AND text_full != ''
        AND COALESCE(article_kind, 'main') = 'main'
    ORDER BY
        CASE WHEN article_number_sort IS NULL THEN 1 ELSE 0 END,
        article_number_sort,
        article_number
    """
    return list(am_db.execute(sql, (canonical_id,)))


def _load_program_law_refs_index(
    jpintel_db: sqlite3.Connection | None,
) -> dict[str, list[dict[str, Any]]]:
    """Return index keyed by 14-char e-Gov-style lawid → list of program rows.

    Empty when jpintel.db is unavailable or program_law_refs is empty (which
    is the current state in the live snapshot; the function is wired now so
    later seeded refs surface automatically).
    """
    if jpintel_db is None:
        return {}
    # The join key between jpintel.db.laws and autonomath.db.am_law is the
    # e-Gov law id, surfaced as `e_gov_lawid` in am_law (14-char form like
    # `338AC0000000154`). On the jpintel side we extract it from the
    # `source_url` since `laws.unified_id` is a hash. We restrict to laws
    # that actually have program references to keep the dict compact.
    sql = """
    SELECT
        l.unified_id      AS law_unified_id,
        l.law_title       AS law_title,
        l.source_url      AS law_source_url,
        l.full_text_url   AS law_full_text_url,
        plr.program_unified_id AS program_unified_id,
        plr.ref_kind          AS ref_kind,
        plr.article_citation  AS article_citation
    FROM program_law_refs plr
    JOIN laws l ON l.unified_id = plr.law_unified_id
    """
    index: dict[str, list[dict[str, Any]]] = {}
    try:
        for row in jpintel_db.execute(sql):
            url = row["law_source_url"] or row["law_full_text_url"] or ""
            m = re.search(r"/law/([0-9A-Z]+)", url)
            if not m:
                continue
            lawid = m.group(1)
            entry = {
                "program_unified_id": row["program_unified_id"],
                "ref_kind": row["ref_kind"],
                "article_citation": row["article_citation"] or "",
                "law_unified_id": row["law_unified_id"],
            }
            index.setdefault(lawid, []).append(entry)
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        _LOG.warning("program_law_refs index build skipped: %s", exc)
        return {}
    return index


def _load_program_slugs(
    jpintel_db: sqlite3.Connection | None, program_ids: list[str]
) -> dict[str, dict[str, str]]:
    """Map program_unified_id → {static_url, name} for backlinks.

    The static program URL is derived from primary_name + unified_id by the
    same helper used by the program-page generator and API runtime. If a row
    lacks primary_name, callers fall back to share.html by unified_id.
    """
    if jpintel_db is None or not program_ids:
        return {}
    # Chunk to keep parameter count under SQLite's 999-host-param limit
    # (default SQLITE_MAX_VARIABLE_NUMBER). 12 hub laws × dozens of refs each
    # can easily push past 999 on a fully-seeded program_law_refs corpus.
    chunk = 800
    out: dict[str, dict[str, str]] = {}
    for i in range(0, len(program_ids), chunk):
        batch = program_ids[i : i + chunk]
        placeholders = ",".join("?" * len(batch))
        sql = f"SELECT unified_id, primary_name FROM programs WHERE unified_id IN ({placeholders})"
        try:
            for row in jpintel_db.execute(sql, batch):
                name = row["primary_name"] or ""
                unified_id = row["unified_id"]
                out[row["unified_id"]] = {
                    "static_url": program_static_url(name, unified_id) if name else "",
                    "name": name or unified_id,
                }
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            _LOG.warning("program_meta load failed: %s", exc)
            return out
    return out


# -----------------------------------------------------------------------
# Render helpers
# -----------------------------------------------------------------------


def _h(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _meta_description(articles: list[sqlite3.Row], law_name: str) -> str:
    for art in articles:
        body = (art["text_full"] or "").strip()
        if not body:
            continue
        snippet = re.sub(r"\s+", " ", body).strip()
        if snippet:
            base = f"{law_name} 第{art['article_number']}条 {snippet}"
            return _truncate(base, _META_DESCRIPTION_MAX)
    return _truncate(f"{law_name} の条文を e-Gov 出典で表示。jpcite。", _META_DESCRIPTION_MAX)


def _meta_description_en(articles: list[sqlite3.Row], law_name: str) -> str:
    for art in articles:
        body = (art["body_en"] or "").strip()
        if not body:
            continue
        snippet = re.sub(r"\s+", " ", body).strip()
        base = f"{law_name} Article {art['article_number']}: {snippet}"
        return _truncate(base, _META_DESCRIPTION_MAX)
    return _truncate(
        f"{law_name} — Japanese statutory text with e-Gov English translations (CC-BY 4.0). jpcite.",
        _META_DESCRIPTION_MAX,
    )


def _article_anchor(article_number: str) -> str:
    # Anchor stable across reruns; mirrors the article_number verbatim minus
    # whitespace so JA users can deep-link "...#art-第1条".
    return "art-" + _SLUG_SAFE_RE.sub("-", article_number.lower()).strip("-")


def _format_date_ja(value: Any) -> str:
    if not value:
        return ""
    s = str(value)
    # Pass through ISO dates verbatim; downstream renderer wraps in <time>.
    return s


def _format_law_subject_areas(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(parsed, list):
        return [str(x) for x in parsed if x]
    return []


def _build_jsonld(
    law: sqlite3.Row,
    domain: str,
    slug: str,
    lang: str,
    related_count: int,
) -> dict[str, Any]:
    """Build a https://schema.org/Legislation JSON-LD doc."""
    egov_url = law["egov_url"] or ""
    page_path = f"/laws/{slug}" if lang == "ja" else f"/en/laws/{slug}"
    canonical = f"https://{domain}{page_path}"
    legislation = {
        "@context": "https://schema.org",
        "@type": "Legislation",
        "@id": canonical + "#legislation",
        "name": law["canonical_name"],
        "alternateName": law["short_name"] or None,
        "legislationIdentifier": law["law_number"] or law["e_gov_lawid"],
        "legislationDate": law["first_enforced"] or None,
        "legislationLegalForce": (
            "InForce" if (law["status"] or "active") == "active" else "NotInForce"
        ),
        "inLanguage": "ja" if lang == "ja" else "en",
        "isPartOf": {
            "@type": "Legislation",
            "name": "Japanese statute corpus",
            "publisher": {
                "@type": "GovernmentOrganization",
                "name": "デジタル庁 e-Gov 法令検索"
                if lang == "ja"
                else "Japan Digital Agency, e-Gov Houreikensaku",
                "url": "https://laws.e-gov.go.jp/",
            },
        },
        "publisher": {
            "@type": "Organization",
            "name": "Bookyou株式会社",
            "url": f"https://{domain}",
            "identifier": [
                {
                    "@type": "PropertyValue",
                    "propertyID": "jp-qualified-invoice-number",
                    "value": "T8010001213708",
                }
            ],
        },
        "url": canonical,
        "mainEntityOfPage": canonical,
        "license": "https://creativecommons.org/licenses/by/4.0/",
    }
    if egov_url:
        legislation["sameAs"] = [egov_url]
    if law["ministry"]:
        legislation["jurisdiction"] = {
            "@type": "AdministrativeArea",
            "name": "Japan",
        }
    if related_count > 0:
        legislation["potentialAction"] = {
            "@type": "Action",
            "name": "リンクされる公的支援制度を確認"
            if lang == "ja"
            else "View linked public-support programs",
            "target": canonical + "#related-programs",
        }
    # Drop empty optional keys so the JSON-LD stays compact.
    return {k: v for k, v in legislation.items() if v not in (None, "", [])}


def _build_breadcrumb_jsonld(domain: str, slug: str, lang: str, law_name: str) -> dict[str, Any]:
    base = f"https://{domain}"
    if lang == "ja":
        items = [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": base + "/"},
            {
                "@type": "ListItem",
                "position": 2,
                "name": "法令",
                "item": base + "/laws/",
            },
            {
                "@type": "ListItem",
                "position": 3,
                "name": law_name,
                "item": f"{base}/laws/{slug}",
            },
        ]
    else:
        items = [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": base + "/en/"},
            {
                "@type": "ListItem",
                "position": 2,
                "name": "Laws",
                "item": base + "/en/laws/",
            },
            {
                "@type": "ListItem",
                "position": 3,
                "name": law_name,
                "item": f"{base}/en/laws/{slug}",
            },
        ]
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items,
    }


def _render_toc(articles: list[sqlite3.Row], lang: str) -> str:
    if not articles:
        return ""
    label = "目次" if lang == "ja" else "Table of contents"
    # Cap the TOC at the same article-count threshold as the body render.
    # The TOC anchors target headings that exist on the page, so listing
    # 4,000 entries would (a) bloat the file and (b) link to anchors that
    # never render because the body itself is capped.
    rendered = articles[:_ARTICLES_PER_PAGE_MAX]
    parts = [f'<details class="law-toc" open><summary>{label}</summary>', "<ol>"]
    for art in rendered:
        anchor = _article_anchor(art["article_number"])
        art_no = _h(art["article_number"])
        title = _h(art["title"] or "")
        if title:
            parts.append(f'<li><a href="#{anchor}">{art_no} {title}</a></li>')
        else:
            parts.append(f'<li><a href="#{anchor}">{art_no}</a></li>')
    parts.append("</ol></details>")
    return "\n".join(parts)


def _render_articles_ja(articles: list[sqlite3.Row], egov_url: str | None) -> str:
    if not articles:
        return '<p class="law-no-articles">条文データを読み込み中です。</p>'
    truncated_total = len(articles) > _ARTICLES_PER_PAGE_MAX
    render_set = articles[:_ARTICLES_PER_PAGE_MAX]
    blocks: list[str] = []
    for art in render_set:
        anchor = _article_anchor(art["article_number"])
        title = _h(art["title"] or "")
        text_full = (art["text_full"] or "").strip()
        truncated_marker = ""
        if len(text_full) > _ARTICLE_BODY_RENDER_MAX:
            text_full = text_full[:_ARTICLE_BODY_RENDER_MAX].rstrip()
            truncated_marker = (
                '<p class="law-article-truncated">'
                "本文が長いため一部のみ表示しています。"
                "完全な条文は e-Gov 法令検索の原本をご参照ください。</p>"
            )
        body_html = _h(text_full).replace("\n", "<br>")
        head = f'<h2 id="{anchor}">第{_h(art["article_number"])}条'
        if title:
            head += f' <span class="law-article-title">{title}</span>'
        head += "</h2>"
        blocks.append(
            '<article class="law-article">'
            + head
            + f'<div class="law-article-body">{body_html}</div>'
            + truncated_marker
            + "</article>"
        )
    if truncated_total:
        remainder = len(articles) - _ARTICLES_PER_PAGE_MAX
        egov_link = (
            f'<a href="{_h(egov_url)}" rel="noopener external" target="_blank">e-Gov 法令検索</a>'
            if egov_url
            else "e-Gov 法令検索"
        )
        blocks.append(
            '<aside class="law-articles-overflow">'
            f"<p>本ページではこの法令の最初の {_ARTICLES_PER_PAGE_MAX} 条のみを表示しています。"
            f"残り {remainder} 条以降の本文は {egov_link} で参照できます。</p>"
            "</aside>"
        )
    return "\n".join(blocks)


def _render_articles_en(articles: list[sqlite3.Row], egov_url: str | None) -> str:
    if not articles:
        return (
            '<p class="law-no-articles">English translations are not yet '
            "available for this law. The Japanese original is the only "
            "authoritative version.</p>"
        )
    en_articles = [a for a in articles if (a["body_en"] or "").strip()]
    truncated_total = len(en_articles) > _ARTICLES_PER_PAGE_MAX
    render_set = en_articles[:_ARTICLES_PER_PAGE_MAX]
    blocks: list[str] = []
    for art in render_set:
        body_en = (art["body_en"] or "").strip()
        anchor = _article_anchor(art["article_number"])
        title = _h(art["title"] or "")
        body = body_en
        truncated_marker = ""
        if len(body) > _ARTICLE_BODY_RENDER_MAX:
            body = body[:_ARTICLE_BODY_RENDER_MAX].rstrip()
            truncated_marker = (
                '<p class="law-article-truncated">'
                "The full English translation is abridged here; "
                "consult e-Gov Houreikensaku for the complete text.</p>"
            )
        body_html = _h(body).replace("\n", "<br>")
        head = f'<h2 id="{anchor}">Article {_h(art["article_number"])}'
        if title:
            head += f' <span class="law-article-title">{title}</span>'
        head += "</h2>"
        blocks.append(
            '<article class="law-article">'
            + head
            + f'<div class="law-article-body">{body_html}</div>'
            + truncated_marker
            + "</article>"
        )
    if not blocks:
        return (
            '<p class="law-no-articles">English translations are not yet '
            "available for this law. The Japanese original is the only "
            "authoritative version.</p>"
        )
    if truncated_total:
        remainder = len(en_articles) - _ARTICLES_PER_PAGE_MAX
        egov_link = (
            f'<a href="{_h(egov_url)}" rel="noopener external" target="_blank">e-Gov Houreikensaku</a>'
            if egov_url
            else "e-Gov Houreikensaku"
        )
        blocks.append(
            '<aside class="law-articles-overflow">'
            f"<p>This page renders only the first {_ARTICLES_PER_PAGE_MAX} articles. "
            f"The remaining {remainder} translated articles are available on {egov_link}.</p>"
            "</aside>"
        )
    return "\n".join(blocks)


def _render_related_programs(
    refs: list[dict[str, Any]],
    program_meta: dict[str, dict[str, str]],
    lang: str,
) -> str:
    if not refs:
        return ""
    head = "関連する公的支援制度" if lang == "ja" else "Related public-support programs"
    items: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        pid = ref.get("program_unified_id") or ""
        if not pid or pid in seen:
            continue
        seen.add(pid)
        meta = program_meta.get(pid)
        name = meta["name"] if meta else pid
        static_url = meta["static_url"] if meta else ""
        href = static_url or f"/programs/share.html?ids={pid}"
        kind = ref.get("ref_kind") or ""
        article = ref.get("article_citation") or ""
        suffix_parts = [p for p in (kind, article) if p]
        suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""
        items.append(f'<li><a href="{_h(href)}">{_h(name)}</a>{_h(suffix)}</li>')
        if len(items) >= _RELATED_PROGRAMS_LIMIT:
            break
    if not items:
        return ""
    return (
        f'<section class="law-related-programs" id="related-programs">'
        f"<h2>{head}</h2><ul>" + "".join(items) + "</ul></section>"
    )


def _render_metadata_panel(law: sqlite3.Row, lang: str) -> str:
    rows: list[tuple[str, str]] = []
    if lang == "ja":
        if law["law_number"]:
            rows.append(("法令番号", _h(law["law_number"])))
        if law["first_enforced"]:
            rows.append(("施行日", _h(law["first_enforced"])))
        if law["last_amended_at"]:
            rows.append(("最終改正", _h(law["last_amended_at"])))
        if law["ministry"]:
            rows.append(("所管", _h(law["ministry"])))
        if law["category"]:
            rows.append(("カテゴリ", _h(law["category"])))
        if law["e_gov_lawid"]:
            rows.append(("e-Gov 法令 ID", _h(law["e_gov_lawid"])))
        if law["status"]:
            rows.append(("ステータス", _h(law["status"])))
    else:
        if law["law_number"]:
            rows.append(("Law number", _h(law["law_number"])))
        if law["first_enforced"]:
            rows.append(("Enforced", _h(law["first_enforced"])))
        if law["last_amended_at"]:
            rows.append(("Last amended", _h(law["last_amended_at"])))
        if law["ministry"]:
            rows.append(("Ministry", _h(law["ministry"])))
        if law["category"]:
            rows.append(("Category", _h(law["category"])))
        if law["e_gov_lawid"]:
            rows.append(("e-Gov ID", _h(law["e_gov_lawid"])))
        if law["status"]:
            rows.append(("Status", _h(law["status"])))
    if not rows:
        return ""
    body = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    return f'<dl class="law-meta">{body}</dl>'


def _render_cite_in_ai(law: sqlite3.Row, domain: str, slug: str, lang: str) -> str:
    """AEO Wave 18: explicit Cite-this-in-AI block for AI agent citation.

    Renders an HTML section with a copy-able Markdown citation block + the
    canonical jpcite URL so AI agents see one obvious anchor for the fact.
    """
    law_name = law["canonical_name"] or ""
    if lang == "ja":
        page_path = f"/laws/{slug}"
        canonical = f"https://{domain}{page_path}"
        short = f"{domain}/laws/{slug}"
        return (
            '<section class="cite-this-section" aria-labelledby="cite-title">'
            '<h2 id="cite-title">Cite this in AI / 引用</h2>'
            "<p>AI 回答に本法令を引用させる時の canonical URL です。出典 (jpcite) の明記をお願いします。"
            "一次資料は e-Gov 法令検索 (CC-BY 4.0)。</p>"
            '<pre class="code-block cite-block"><code>'
            f"&gt; {_h(law_name)} "
            f"(出典: https://{_h(short)}、jpcite が e-Gov 一次資料を機械可読化)"
            "</code></pre>"
            '<p class="muted">'
            f'<button type="button" class="copy-cite-btn" data-cite-url="{_h(canonical)}" '
            f"onclick=\"navigator.clipboard&amp;&amp;navigator.clipboard.writeText('{_h(canonical)}')\">"
            "URL をコピー</button> "
            f'<a href="{_h(canonical)}">{_h(canonical)}</a>'
            "</p>"
            "</section>"
        )
    page_path = f"/en/laws/{slug}"
    canonical = f"https://{domain}{page_path}"
    short = f"{domain}/en/laws/{slug}"
    return (
        '<section class="cite-this-section" aria-labelledby="cite-title">'
        '<h2 id="cite-title">Cite this in AI</h2>'
        "<p>Canonical jpcite URL to use when an AI answer references this statute. "
        "Please attribute jpcite. Primary source is e-Gov Houreikensaku (CC-BY 4.0).</p>"
        '<pre class="code-block cite-block"><code>'
        f"&gt; {_h(law_name)} "
        f"(source: https://{_h(short)} — machine-readable layer over e-Gov by jpcite)"
        "</code></pre>"
        '<p class="muted">'
        f'<button type="button" class="copy-cite-btn" data-cite-url="{_h(canonical)}" '
        f"onclick=\"navigator.clipboard&amp;&amp;navigator.clipboard.writeText('{_h(canonical)}')\">"
        "Copy URL</button> "
        f'<a href="{_h(canonical)}">{_h(canonical)}</a>'
        "</p>"
        "</section>"
    )


def _render_egov_attribution(law: sqlite3.Row, lang: str) -> str:
    egov_url = law["egov_url"] or ""
    if lang == "ja":
        if egov_url:
            link = f'<p><strong>e-Gov 出典</strong>: <a href="{_h(egov_url)}" rel="noopener external" target="_blank">{_h(egov_url)}</a></p>'
        else:
            link = ""
        return (
            '<section class="law-attribution"><h2>出典とライセンス</h2>'
            + link
            + f"<p>{_h(_EGOV_LICENSE_JA)}</p></section>"
        )
    if egov_url:
        link = f'<p><strong>Source (e-Gov)</strong>: <a href="{_h(egov_url)}" rel="noopener external" target="_blank">{_h(egov_url)}</a></p>'
    else:
        link = ""
    return (
        '<section class="law-attribution"><h2>Source and license</h2>'
        + link
        + f"<p>{_h(_EGOV_LICENSE_EN)}</p>"
        + f'<p class="law-translation-disclaimer">{_h(_BODY_EN_DISCLAIMER)}</p>'
        + "</section>"
    )


# -----------------------------------------------------------------------
# HTML page render
# -----------------------------------------------------------------------


_COMMON_JSONLD = (
    '<script type="application/ld+json" data-jpcite-jsonld="common">'
    "{"
    '"@context":"https://schema.org",'
    '"@graph":['
    "{"
    '"@type":"Organization",'
    '"@id":"https://jpcite.com/#org",'
    '"name":"Bookyou株式会社",'
    '"url":"https://jpcite.com",'
    '"identifier":['
    '{"@type":"PropertyValue","propertyID":"jp-corporate-number","value":"8010001213708"},'
    '{"@type":"PropertyValue","propertyID":"jp-qualified-invoice-number","value":"T8010001213708"}'
    "]"
    "},"
    "{"
    '"@type":"WebSite",'
    '"@id":"https://jpcite.com/#site",'
    '"name":"jpcite",'
    '"url":"https://jpcite.com",'
    '"publisher":{"@id":"https://jpcite.com/#org"}'
    "}"
    "]}"
    "</script>"
)


def _render_page_ja(
    law: sqlite3.Row,
    articles: list[sqlite3.Row],
    related_refs: list[dict[str, Any]],
    program_meta: dict[str, dict[str, str]],
    domain: str,
    slug: str,
    has_en: bool,
    generated_at: str,
) -> str:
    law_name = law["canonical_name"]
    title_parts = [law_name]
    if law["first_enforced"]:
        title_parts.append(f"({_format_date_ja(law['first_enforced'])} 施行)")
    page_title = " ".join(title_parts) + " — 法令本文 | jpcite"
    meta_desc = _meta_description(articles, law_name)
    canonical_url = f"https://{domain}/laws/{slug}"
    canonical_en_url = f"https://{domain}/en/laws/{slug}"
    legislation_jsonld = _build_jsonld(law, domain, slug, "ja", len(related_refs))
    breadcrumb_jsonld = _build_breadcrumb_jsonld(domain, slug, "ja", law_name)
    jsonld_text = json.dumps(legislation_jsonld, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    breadcrumb_text = json.dumps(
        breadcrumb_jsonld, ensure_ascii=False, separators=(",", ":")
    ).replace("</", "<\\/")

    toc_html = _render_toc(articles, "ja")
    article_html = _render_articles_ja(articles, law["egov_url"])
    related_html = _render_related_programs(related_refs, program_meta, "ja")
    metadata_html = _render_metadata_panel(law, "ja")
    attribution_html = _render_egov_attribution(law, "ja")
    cite_in_ai_html = _render_cite_in_ai(law, domain, slug, "ja")
    hreflang_en = (
        f'<link rel="alternate" hreflang="en" href="{canonical_en_url}">' if has_en else ""
    )
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="theme-color" content="#ffffff">
<title>{_h(page_title)}</title>
<meta name="description" content="{_h(meta_desc)}">
<meta name="author" content="jpcite">
<meta name="publisher" content="Bookyou株式会社">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta property="og:title" content="{_h(page_title)}">
<meta property="og:description" content="{_h(meta_desc)}">
<meta property="og:type" content="article">
<meta property="og:url" content="{canonical_url}">
<meta property="og:image" content="https://{domain}/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="ja_JP">
<meta property="og:site_name" content="jpcite">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{_h(page_title)}">
<meta name="twitter:description" content="{_h(meta_desc)}">
<meta name="twitter:image" content="https://{domain}/assets/og-twitter.png">
<link rel="canonical" href="{canonical_url}">
<link rel="alternate" hreflang="ja" href="{canonical_url}">
{hreflang_en}
<link rel="alternate" hreflang="x-default" href="{canonical_url}">
<link rel="icon" href="/assets/favicon-v2.svg" type="image/svg+xml">
<link rel="icon" href="/assets/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/assets/favicon-16.png" sizes="16x16" type="image/png">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
<link rel="stylesheet" href="/styles.css?v=20260515b">
<script type="application/ld+json">{jsonld_text}</script>
<script type="application/ld+json" data-jpcite-jsonld="breadcrumb">{breadcrumb_text}</script>
{_COMMON_JSONLD}
</head>
<body>
<nav class="breadcrumb" aria-label="パンくず">
<a href="/">ホーム</a> &raquo; <a href="/laws/">法令</a> &raquo; <span>{_h(law_name)}</span>
</nav>
<main class="law-page">
<header class="law-header">
<h1>{_h(law_name)}</h1>
{f'<p class="law-short">略称: {_h(law["short_name"])}</p>' if law["short_name"] else ""}
{metadata_html}
</header>
{toc_html}
<section class="law-articles">
{article_html}
</section>
{related_html}
{attribution_html}
{cite_in_ai_html}
<footer class="law-footer">
<p class="law-generated"><time datetime="{generated_at}">{generated_at}</time> 時点で e-Gov 法令検索から取得した条文を表示しています。</p>
<p class="law-license-marker">出典: e-Gov 法令検索 (デジタル庁) / CC-BY 4.0</p>
</footer>
</main>
</body>
</html>
"""


def _render_page_en(
    law: sqlite3.Row,
    articles: list[sqlite3.Row],
    related_refs: list[dict[str, Any]],
    program_meta: dict[str, dict[str, str]],
    domain: str,
    slug: str,
    generated_at: str,
) -> str:
    law_name = law["canonical_name"]
    page_title = f"{law_name} — Statute (with English translation) | jpcite"
    meta_desc = _meta_description_en(articles, law_name)
    canonical_url = f"https://{domain}/en/laws/{slug}"
    canonical_ja_url = f"https://{domain}/laws/{slug}"
    legislation_jsonld = _build_jsonld(law, domain, slug, "en", len(related_refs))
    breadcrumb_jsonld = _build_breadcrumb_jsonld(domain, slug, "en", law_name)
    jsonld_text = json.dumps(legislation_jsonld, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    breadcrumb_text = json.dumps(
        breadcrumb_jsonld, ensure_ascii=False, separators=(",", ":")
    ).replace("</", "<\\/")

    toc_html = _render_toc([a for a in articles if (a["body_en"] or "").strip()], "en")
    article_html = _render_articles_en(articles, law["egov_url"])
    related_html = _render_related_programs(related_refs, program_meta, "en")
    metadata_html = _render_metadata_panel(law, "en")
    attribution_html = _render_egov_attribution(law, "en")
    cite_in_ai_html = _render_cite_in_ai(law, domain, slug, "en")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="theme-color" content="#ffffff">
<title>{_h(page_title)}</title>
<meta name="description" content="{_h(meta_desc)}">
<meta name="author" content="jpcite">
<meta name="publisher" content="Bookyou Co., Ltd.">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta property="og:title" content="{_h(page_title)}">
<meta property="og:description" content="{_h(meta_desc)}">
<meta property="og:type" content="article">
<meta property="og:url" content="{canonical_url}">
<meta property="og:image" content="https://{domain}/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="en_US">
<meta property="og:site_name" content="jpcite">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{_h(page_title)}">
<meta name="twitter:description" content="{_h(meta_desc)}">
<meta name="twitter:image" content="https://{domain}/assets/og-twitter.png">
<link rel="canonical" href="{canonical_url}">
<link rel="alternate" hreflang="ja" href="{canonical_ja_url}">
<link rel="alternate" hreflang="en" href="{canonical_url}">
<link rel="alternate" hreflang="x-default" href="{canonical_ja_url}">
<link rel="icon" href="/assets/favicon-v2.svg" type="image/svg+xml">
<link rel="icon" href="/assets/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/assets/favicon-16.png" sizes="16x16" type="image/png">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
<link rel="stylesheet" href="/styles.css?v=20260515b">
<script type="application/ld+json">{jsonld_text}</script>
<script type="application/ld+json" data-jpcite-jsonld="breadcrumb">{breadcrumb_text}</script>
{_COMMON_JSONLD}
</head>
<body>
<nav class="breadcrumb" aria-label="Breadcrumb">
<a href="/en/">Home</a> &raquo; <a href="/en/laws/">Laws</a> &raquo; <span>{_h(law_name)}</span>
</nav>
<main class="law-page">
<header class="law-header">
<h1>{_h(law_name)}</h1>
{f'<p class="law-short">Short title: {_h(law["short_name"])}</p>' if law["short_name"] else ""}
{metadata_html}
<p class="law-translation-disclaimer">{_h(_BODY_EN_DISCLAIMER)}</p>
</header>
{toc_html}
<section class="law-articles">
{article_html}
</section>
{related_html}
{attribution_html}
{cite_in_ai_html}
<footer class="law-footer">
<p class="law-generated"><time datetime="{generated_at}">{generated_at}</time> snapshot from e-Gov Houreikensaku (Japan Digital Agency).</p>
<p class="law-license-marker">Source: e-Gov Houreikensaku / CC-BY 4.0 (statute), japaneselawtranslation.go.jp / CC-BY 4.0 (English).</p>
</footer>
</main>
</body>
</html>
"""


# -----------------------------------------------------------------------
# Sitemap writers
# -----------------------------------------------------------------------


def _write_sitemap(path: Path, urls: list[tuple[str, str]], today_iso: str) -> None:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, lastmod in urls:
        parts.append("  <url>")
        parts.append(f"    <loc>{_h(loc)}</loc>")
        parts.append(f"    <lastmod>{_h(lastmod or today_iso)}</lastmod>")
        parts.append("    <changefreq>monthly</changefreq>")
        parts.append("    <priority>0.5</priority>")
        parts.append("  </url>")
    parts.append("</urlset>")
    parts.append("")
    path.write_text("\n".join(parts), encoding="utf-8")


def _write_marker_page(out_dir: Path, reason: str, generated_at: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    marker = out_dir / "_unavailable.html"
    body = (
        '<!DOCTYPE html>\n<html lang="ja">\n<head>'
        '<meta charset="UTF-8">'
        f"<!-- generated_at = {generated_at} data unavailable -->"
        "<title>法令データ準備中 | jpcite</title>"
        '<meta name="robots" content="noindex">'
        "</head><body>"
        f"<main><h1>法令データ準備中</h1><p>{_h(reason)}</p></main>"
        "</body></html>\n"
    )
    marker.write_text(body, encoding="utf-8")
    return marker


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--am-db", type=Path, default=None, help="autonomath.db path override")
    p.add_argument("--jpintel-db", type=Path, default=_DEFAULT_JPINTEL_DB)
    p.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    p.add_argument("--en-out", type=Path, default=_DEFAULT_EN_OUT)
    p.add_argument("--domain", default=_DEFAULT_DOMAIN)
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="If >0, only generate the first N laws (smoke test).",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    generated_at = _now_jst_iso()
    today_iso = _today_jst_iso()

    args.out.mkdir(parents=True, exist_ok=True)
    args.en_out.mkdir(parents=True, exist_ok=True)

    am_db_path = _resolve_autonomath_db(args.am_db)
    if am_db_path is None:
        reason = (
            "autonomath.db is not present locally. Run hydrate "
            "(`flyctl ssh sftp get`) or wait for the next CI seed."
        )
        marker = _write_marker_page(args.out, reason, generated_at)
        _LOG.warning("DB unavailable; wrote marker page %s", marker)
        # Still emit an empty sitemap so downstream sitemap-index does not 404.
        _write_sitemap(args.out.parent / "sitemap-laws.xml", [], today_iso)
        _write_sitemap(args.out.parent / "sitemap-laws-en.xml", [], today_iso)
        return 0

    _LOG.info("autonomath.db = %s", am_db_path)
    am_db = _open_db_readonly(am_db_path)

    jpintel_db: sqlite3.Connection | None = None
    if args.jpintel_db.exists():
        try:
            jpintel_db = _open_db_readonly(args.jpintel_db)
            _LOG.info("jpintel.db = %s", args.jpintel_db)
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            _LOG.warning("jpintel.db open failed: %s", exc)
            jpintel_db = None
    else:
        _LOG.warning("jpintel.db missing at %s — related-programs will be empty", args.jpintel_db)

    laws = _load_laws_with_articles(am_db)
    if args.limit > 0:
        laws = laws[: args.limit]
    _LOG.info("laws with full-text articles: %d", len(laws))

    program_refs_index = _load_program_law_refs_index(jpintel_db)
    _LOG.info("program_law_refs lawid keys: %d", len(program_refs_index))

    # Collect all program ids ahead of per-page render so we do a single
    # batched name lookup against jpintel.db rather than one row per page.
    all_program_ids: list[str] = []
    for refs in program_refs_index.values():
        for r in refs:
            pid = r.get("program_unified_id")
            if pid:
                all_program_ids.append(pid)
    program_meta = _load_program_slugs(jpintel_db, sorted(set(all_program_ids)))
    _LOG.info("program_meta entries: %d", len(program_meta))

    ja_urls: list[tuple[str, str]] = []
    en_urls: list[tuple[str, str]] = []
    written_ja = 0
    written_en = 0

    for law in laws:
        slug = _slug_from_canonical_id(law["canonical_id"])
        articles = _load_articles_for_law(am_db, law["canonical_id"])
        lawid = law["e_gov_lawid"] or ""
        related_refs = program_refs_index.get(lawid, [])
        has_en_articles = any((a["body_en"] or "").strip() for a in articles)

        ja_html = _render_page_ja(
            law,
            articles,
            related_refs,
            program_meta,
            args.domain,
            slug,
            has_en_articles,
            generated_at,
        )
        ja_path = args.out / f"{slug}.html"
        # Idempotent write: skip if identical content already present so the
        # static-drift CI gate does not flag a no-op rerun.
        existing = None
        if ja_path.exists():
            try:
                existing = ja_path.read_text(encoding="utf-8")
            except OSError:
                existing = None
        if existing != ja_html:
            ja_path.write_text(ja_html, encoding="utf-8")
        written_ja += 1
        ja_urls.append(
            (
                f"https://{args.domain}/laws/{slug}",
                law["last_amended_at"] or law["first_enforced"] or today_iso,
            )
        )

        if has_en_articles:
            en_html = _render_page_en(
                law,
                articles,
                related_refs,
                program_meta,
                args.domain,
                slug,
                generated_at,
            )
            en_path = args.en_out / f"{slug}.html"
            existing_en = None
            if en_path.exists():
                try:
                    existing_en = en_path.read_text(encoding="utf-8")
                except OSError:
                    existing_en = None
            if existing_en != en_html:
                en_path.write_text(en_html, encoding="utf-8")
            written_en += 1
            en_urls.append(
                (
                    f"https://{args.domain}/en/laws/{slug}",
                    law["last_amended_at"] or law["first_enforced"] or today_iso,
                )
            )

        if written_ja % 500 == 0:
            _LOG.info("progress: %d / %d laws", written_ja, len(laws))

    _write_sitemap(args.out.parent / "sitemap-laws.xml", ja_urls, today_iso)
    _write_sitemap(args.out.parent / "sitemap-laws-en.xml", en_urls, today_iso)

    _LOG.info(
        "done: ja=%d en=%d sitemap_ja=%s sitemap_en=%s",
        written_ja,
        written_en,
        args.out.parent / "sitemap-laws.xml",
        args.out.parent / "sitemap-laws-en.xml",
    )
    am_db.close()
    if jpintel_db is not None:
        jpintel_db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
