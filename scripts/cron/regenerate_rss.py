#!/usr/bin/env python3
"""Regenerate /rss.xml + /en/rss.xml from site/news/*.html.

Reads the latest 50 generated news posts (sorted by detected_at desc),
emits an RSS 2.0 feed in JA at site/rss.xml.new and EN at site/en/rss.xml.new.
We never overwrite the existing rss.xml directly — the spec says write to
.new and let the next deploy swap. This protects the live feed from a
broken regen run.

English fallback policy
-----------------------
We do not maintain an EN translation pipeline for /news/* yet. The EN
feed's <description> falls back to the JA summary verbatim — labeled with
`xml:lang="ja"` on the item — which is honest about the missing
translation while still giving en/rss.xml subscribers something fresh.

Idempotency
-----------
Re-running on the same news/*.html corpus produces byte-identical output
because:
  * posts are sorted by detected_at desc, then canonical_url asc (stable)
  * we cap at 50, deterministic
  * we render into a fixed-format RSS 2.0 envelope

Usage
-----
    python scripts/cron/regenerate_rss.py
    python scripts/cron/regenerate_rss.py --news site/news --domain jpcite.com
    python scripts/cron/regenerate_rss.py --dry-run

Exit codes
----------
0 success
1 fatal (news dir missing, etc)
"""

from __future__ import annotations

import argparse
import html as html_lib
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("autonomath.cron.regenerate_rss")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from jpintel_mcp.observability import heartbeat  # noqa: E402

_DEFAULT_NEWS = _REPO_ROOT / "site" / "news"
_DEFAULT_OUT_JA = _REPO_ROOT / "site" / "rss.xml.new"
_DEFAULT_OUT_EN = _REPO_ROOT / "site" / "en" / "rss.xml.new"
_UTC = timezone.utc

_MAX_ITEMS = 50

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_META_DESC_RE = re.compile(
    r'<meta\s+name="description"\s+content="(.*?)"', re.DOTALL | re.IGNORECASE
)
_PUB_TIME_RE = re.compile(
    r'<meta\s+property="article:published_time"\s+content="(.*?)"',
    re.DOTALL | re.IGNORECASE,
)
_SECTION_RE = re.compile(
    r'<meta\s+property="article:section"\s+content="(.*?)"',
    re.DOTALL | re.IGNORECASE,
)
_CANONICAL_RE = re.compile(r'<link\s+rel="canonical"\s+href="(.*?)"', re.DOTALL | re.IGNORECASE)


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.cron.regenerate_rss")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


@dataclass(frozen=True)
class NewsItem:
    title: str
    description: str
    url: str
    pub_date_utc: datetime
    category: str
    guid: str  # stable canonical url


def _read_meta(html: str, pattern: re.Pattern[str]) -> str | None:
    m = pattern.search(html)
    if not m:
        return None
    return html_lib.unescape(m.group(1).strip())


def _parse_news_post(path: Path) -> NewsItem | None:
    try:
        html = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("skip_unreadable path=%s err=%s", path, exc)
        return None
    title = _read_meta(html, _TITLE_RE)
    description = _read_meta(html, _META_DESC_RE)
    pub_iso = _read_meta(html, _PUB_TIME_RE)
    category = _read_meta(html, _SECTION_RE) or "お知らせ"
    canonical = _read_meta(html, _CANONICAL_RE)
    if not (title and description and pub_iso and canonical):
        logger.warning("skip_missing_meta path=%s", path)
        return None
    try:
        pub_dt = datetime.fromisoformat(pub_iso.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("skip_unparseable_date path=%s pub=%s", path, pub_iso)
        return None
    if pub_dt.tzinfo is None:
        pub_dt = pub_dt.replace(tzinfo=_UTC)
    return NewsItem(
        title=title,
        description=description,
        url=canonical,
        pub_date_utc=pub_dt.astimezone(_UTC),
        category=category,
        guid=canonical,
    )


def _walk_news_dir(news_dir: Path) -> list[NewsItem]:
    if not news_dir.is_dir():
        return []
    items: list[NewsItem] = []
    for path in sorted(news_dir.rglob("*.html")):
        # Skip the index page itself (and any other top-level meta files).
        if path.parent == news_dir:
            continue
        item = _parse_news_post(path)
        if item is not None:
            items.append(item)
    # Newest first; tiebreaker on URL keeps the order stable across re-runs.
    items.sort(key=lambda x: (-x.pub_date_utc.timestamp(), x.url))
    return items[:_MAX_ITEMS]


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _render_rss(
    items: Iterable[NewsItem],
    *,
    domain: str,
    title: str,
    description: str,
    feed_url: str,
    home_url: str,
    language: str,
    fallback_lang_for_items: str | None = None,
) -> str:
    """Build an RSS 2.0 document.

    `fallback_lang_for_items` adds xml:lang on each <item> when the feed
    language is en but the item content is still JA (en/rss.xml).
    """
    items = list(items)
    if items:
        last_build = max(i.pub_date_utc for i in items)
    else:
        # When no posts exist yet, stamp lastBuildDate at "now" rounded to
        # the hour. We still emit the channel envelope so the feed URL
        # never 404s — RSS readers tolerate empty channels.
        last_build = datetime.now(_UTC).replace(minute=0, second=0, microsecond=0)
    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
    )
    lines.append("<channel>")
    lines.append(f"  <title>{_xml_escape(title)}</title>")
    lines.append(f"  <link>{_xml_escape(home_url)}</link>")
    lines.append(
        f'  <atom:link href="{_xml_escape(feed_url)}" rel="self" type="application/rss+xml" />'
    )
    lines.append(f"  <description>{_xml_escape(description)}</description>")
    lines.append(f"  <language>{language}</language>")
    lines.append("  <copyright>(C) 2026 Bookyou株式会社</copyright>")
    lines.append("  <generator>AutonoMath site (Bookyou株式会社)</generator>")
    lines.append(f"  <lastBuildDate>{format_datetime(last_build)}</lastBuildDate>")
    lines.append("")
    for it in items:
        lines.append("  <item>")
        lines.append(f"    <title>{_xml_escape(it.title)}</title>")
        lines.append(f"    <link>{_xml_escape(it.url)}</link>")
        if fallback_lang_for_items:
            lines.append(
                f'    <description xml:lang="{fallback_lang_for_items}">'
                f"{_xml_escape(it.description)}</description>"
            )
        else:
            lines.append(f"    <description>{_xml_escape(it.description)}</description>")
        lines.append(f"    <category>{_xml_escape(it.category)}</category>")
        lines.append(f'    <guid isPermaLink="true">{_xml_escape(it.guid)}</guid>')
        lines.append(f"    <pubDate>{format_datetime(it.pub_date_utc)}</pubDate>")
        lines.append("  </item>")
        lines.append("")
    lines.append("</channel>")
    lines.append("</rss>")
    return "\n".join(lines) + "\n"


def _write_if_changed(path: Path, content: str, dry_run: bool) -> bool:
    if dry_run:
        logger.info(
            "would_write path=%s bytes=%d",
            path.relative_to(_REPO_ROOT) if str(path).startswith(str(_REPO_ROOT)) else path,
            len(content.encode("utf-8")),
        )
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except Exception:
            existing = ""
        if existing == content:
            logger.info("rss_unchanged path=%s", path)
            return False
    path.write_text(content, encoding="utf-8")
    logger.info("wrote_rss path=%s bytes=%d", path, len(content.encode("utf-8")))
    return True


def run(
    news_dir: Path,
    out_ja: Path,
    out_en: Path,
    domain: str,
    dry_run: bool,
) -> dict[str, int]:
    counters = {"items": 0, "wrote_ja": 0, "wrote_en": 0}
    if not news_dir.is_dir():
        logger.warning("news_dir_missing path=%s — emitting empty channels", news_dir)

    items = _walk_news_dir(news_dir)
    counters["items"] = len(items)

    ja_xml = _render_rss(
        items,
        domain=domain,
        title="AutonoMath お知らせ",
        description=(
            "AutonoMath (Bookyou株式会社) の制度変更検出ログ・リリース・主要マイグレーションのお知らせ。"
            " am_amendment_diff (追記専用) から週次で自動生成。"
        ),
        feed_url=f"https://{domain}/rss.xml",
        home_url=f"https://{domain}/",
        language="ja",
    )
    en_xml = _render_rss(
        items,
        domain=domain,
        title="AutonoMath News (Japanese public-program changes)",
        description=(
            "AutonoMath (Bookyou Inc.) Japanese public-program change-detection log."
            " Generated weekly from am_amendment_diff (append-only)."
            " Item bodies fall back to Japanese when no translation is available."
        ),
        feed_url=f"https://{domain}/en/rss.xml",
        home_url=f"https://{domain}/en/",
        language="en",
        fallback_lang_for_items="ja",
    )
    if _write_if_changed(out_ja, ja_xml, dry_run):
        counters["wrote_ja"] = 1
    if _write_if_changed(out_en, en_xml, dry_run):
        counters["wrote_en"] = 1
    logger.info(
        "rss_regen_done items=%d wrote_ja=%d wrote_en=%d",
        counters["items"],
        counters["wrote_ja"],
        counters["wrote_en"],
    )
    return counters


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Regenerate /rss.xml + /en/rss.xml.")
    p.add_argument("--news", type=Path, default=_DEFAULT_NEWS)
    p.add_argument("--out-ja", type=Path, default=_DEFAULT_OUT_JA)
    p.add_argument("--out-en", type=Path, default=_DEFAULT_OUT_EN)
    p.add_argument("--domain", type=str, default="jpcite.com")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)
    with heartbeat("regenerate_rss") as hb:
        try:
            counters = run(
                news_dir=args.news,
                out_ja=args.out_ja,
                out_en=args.out_en,
                domain=args.domain,
                dry_run=bool(args.dry_run),
            )
        except Exception as e:
            logger.exception("rss_regen_failed err=%s", e)
            return 1
        hb["rows_processed"] = int(counters.get("items", 0) or 0)
        hb["metadata"] = {
            "wrote_ja": counters.get("wrote_ja"),
            "wrote_en": counters.get("wrote_en"),
            "dry_run": bool(args.dry_run),
        }
    return 0


if __name__ == "__main__":
    sys.exit(main())
