#!/usr/bin/env python3
"""ingest_shohi_tsutatsu.py - Ingest 消費税法基本通達 into am_law_article.

Source: nta.go.jp /law/tsutatsu/kihon/shohi/ (Shift_JIS origin, walked into
/tmp/shohi_walk/ as UTF-8 already).

- law_canonical_id: law:shohi-zei-tsutatsu
- article_kind: 'tsutatsu'
- article_number format: 'X-Y-Z' (ASCII hyphen normalized from U+2212),
  branch suffix kept inline (e.g. '11-5-7の2')
- UNIQUE (law_canonical_id, article_number) conflict handled via UPSERT
- 20 existing placeholder rows (article_kind='notice', article_number='通達X-Y-Z')
  are DELETED before load to keep the series coherent.
- Old pre-2023-09-30 tsutatsu (20230930/*) are excluded.

NO Anthropic API. NO LLM. HTML parse only.

Usage:
    .venv/bin/python scripts/ingest/ingest_shohi_tsutatsu.py \
        --cache-dir /tmp/shohi_walk \
        --db autonomath.db

    .venv/bin/python scripts/ingest/ingest_shohi_tsutatsu.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Iterator

try:
    from bs4 import BeautifulSoup, NavigableString, Tag
except ImportError as exc:
    print(f"missing dep: {exc}. pip install beautifulsoup4", file=sys.stderr)
    sys.exit(1)


_LOG = logging.getLogger("ingest_shohi_tsutatsu")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_CACHE = Path("/tmp/shohi_walk")

LAW_CANONICAL_ID = "law:shohi-zei-tsutatsu"
ARTICLE_KIND = "tsutatsu"
BASE_URL = "https://www.nta.go.jp/law/tsutatsu/kihon/shohi"
ATTRIBUTION = "出典: 国税庁 消費税法基本通達"

# File name pattern from walker output.
#   _law_tsutatsu_kihon_shohi_05_07.htm.html        -> chapter=5 section=7 subsection=None
#   _law_tsutatsu_kihon_shohi_05_03_01.htm.html     -> chapter=5 section=3 subsection=1
#   _law_tsutatsu_kihon_shohi_18_01.htm.html        -> chapter=18 section=1
#   _law_tsutatsu_kihon_shohi_02.htm.html           -> preface (skip, no tsutatsu number)
#   _law_tsutatsu_kihon_shohi_01.htm.html           -> TOC (skip)
#   _law_tsutatsu_kihon_shohi_20230930_01.htm.html  -> old version (EXCLUDE)
FNAME_LEAF_RE = re.compile(
    r"^_law_tsutatsu_kihon_shohi_(\d{2})_(\d{2})(?:_(\d{2}))?\.htm\.html$"
)
FNAME_OLD_MARKER = "20230930"

# Article number: "1-1-1", "5-7-14", "11-5-7の2". U+2212 or hyphen.
NUM_RE = re.compile(r"(\d+)\s*[−\-]\s*(\d+)\s*[−\-]\s*(\d+)(の\d+)?")

# Amendment note at body end, e.g. "（平31課消2−9、令５課消2−9により改正）"
AMEND_RE = re.compile(r"[（(]([^（()）]*?により(?:改正|追加|削除)[^（()）]*?)[)）]\s*$")


def url_for(chapter: int, section: int, subsection: int | None) -> str:
    if subsection is None:
        return f"{BASE_URL}/{chapter:02d}/{section:02d}.htm"
    return f"{BASE_URL}/{chapter:02d}/{section:02d}/{subsection:02d}.htm"


def normalize_hyphen(s: str) -> str:
    # U+2212 MINUS SIGN -> ASCII HYPHEN-MINUS
    return s.replace("−", "-")


def parse_leaf(
    html: str, chapter: int, section: int, subsection: int | None, source_url: str
) -> list[dict]:
    """Extract tsutatsu articles from one leaf page.

    Structure (already decoded to UTF-8 by walker):
        <div id="bodyArea"> ...
            <p align=center><strong>第1章 ...</strong></p>
            <h1>第1節 ...</h1>
            <h2>(article title)</h2>
            <p class="indent1"><strong>N</strong><strong>-Y-Z</strong>body</p>
            <p class="indent2">(1) ...</p>
            ...
            <h2>(next article title)</h2>
            ...
    """
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("div", id="bodyArea")
    if body is None:
        _LOG.warning("no bodyArea chapter=%s section=%s sub=%s", chapter, section, subsection)
        return []

    # Chapter / section titles.
    chapter_title = None
    section_title = None
    for strong in body.find_all("strong"):
        txt = strong.get_text(strip=True)
        if txt.startswith(f"第{chapter}章") or re.match(r"^第\d+章", txt):
            chapter_title = txt
            break
    h1 = body.find("h1")
    if h1 is not None:
        section_title = h1.get_text(strip=True)

    # Walk elements in document order and group.
    items: list[dict] = []
    current_title: str | None = None
    current_number: str | None = None
    current_branch: str | None = None
    current_body_parts: list[str] = []
    current_amend: str | None = None

    def flush():
        nonlocal current_title, current_number, current_branch, current_body_parts, current_amend
        if current_number is not None:
            body_text = "\n".join(p for p in current_body_parts if p).strip()
            # Strip trailing amendment note if present.
            amend = current_amend
            m = AMEND_RE.search(body_text)
            if m and amend is None:
                amend = m.group(1).strip()
                body_text = AMEND_RE.sub("", body_text).rstrip()
            anchor = current_number + (current_branch or "")
            items.append(
                {
                    "article_number": anchor,
                    "title": current_title,
                    "body": body_text,
                    "amend": amend,
                    "chapter": chapter,
                    "section": section,
                    "subsection": subsection,
                    "chapter_title": chapter_title,
                    "section_title": section_title,
                    "source_url": f"{source_url}#{anchor}",
                }
            )
        current_title = None
        current_number = None
        current_branch = None
        current_body_parts = []
        current_amend = None

    # Flat iteration over direct descendants.
    for elem in body.descendants:
        if not isinstance(elem, Tag):
            continue
        name = elem.name
        if name == "h2":
            # h2 = new article title (or sitemap footer to skip)
            title_text = elem.get_text(strip=True)
            if not title_text:
                continue
            if "サイトマップ" in title_text:
                # footer marker; flush and stop collecting further
                flush()
                break
            # Strip outer parens (full-width or half-width).
            clean = title_text
            for l, r in [("（", "）"), ("(", ")")]:
                if clean.startswith(l) and clean.endswith(r):
                    clean = clean[1:-1]
                    break
            flush()
            current_title = clean.strip()
        elif name in ("p", "div", "li") and elem.get("class"):
            classes = elem.get("class") or []
            if "indent1" in classes or "indent2" in classes or "indent3" in classes:
                text = elem.get_text(separator="", strip=False)
                text = normalize_hyphen(text)
                # First indent1 under a new title carries the number prefix.
                if current_number is None and "indent1" in classes:
                    m = NUM_RE.search(text)
                    if m:
                        current_number = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                        current_branch = m.group(4) or None
                        # Remove the matched number from body.
                        text = NUM_RE.sub("", text, count=1).strip()
                if text.strip():
                    current_body_parts.append(text.strip())

    flush()

    # Post-filter: only keep items that actually got a number.
    return [it for it in items if it["article_number"]]


def iter_cache_files(cache_dir: Path) -> Iterator[tuple[Path, int, int, int | None]]:
    for p in sorted(cache_dir.iterdir()):
        if not p.is_file():
            continue
        if FNAME_OLD_MARKER in p.name:
            continue
        m = FNAME_LEAF_RE.match(p.name)
        if not m:
            continue
        chapter = int(m.group(1))
        section = int(m.group(2))
        sub = int(m.group(3)) if m.group(3) else None
        # Skip TOC entries: chapter==0 (not present) and the preface 02.htm handled via non-match
        yield p, chapter, section, sub


def number_sort_key(article_number: str) -> float:
    # "1-1-1" -> 1.001001 ; "11-5-7の2" -> 11.005007 + 0.000001 * branch
    m = re.match(r"^(\d+)-(\d+)-(\d+)(?:の(\d+))?$", article_number)
    if not m:
        return 0.0
    c = int(m.group(1))
    s = int(m.group(2))
    n = int(m.group(3))
    b = int(m.group(4)) if m.group(4) else 0
    return c * 1_000_000 + s * 10_000 + n * 100 + b  # safe int spread


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_am_law_row(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT canonical_id FROM am_law WHERE canonical_id=?", (LAW_CANONICAL_ID,)
    ).fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO am_law (
              canonical_id, canonical_name, short_name, law_number, category,
              egov_url, status, ministry, created_at
            ) VALUES (?,?,?,?,?,?,?,?, datetime('now'))
            """,
            (
                LAW_CANONICAL_ID,
                "消費税法基本通達",
                "消費税通達",
                "平成7年課消2-25",
                "税制",
                f"{BASE_URL}/",
                "active",
                "国税庁",
            ),
        )
        _LOG.info("am_law row inserted canonical_id=%s", LAW_CANONICAL_ID)


def load(
    conn: sqlite3.Connection, items: list[dict], dry_run: bool = False
) -> tuple[int, int]:
    """Delete placeholders, UPSERT all items."""
    now = datetime.now(UTC).isoformat()

    if dry_run:
        return (len(items), 0)

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Purge 20 placeholder rows (article_number prefixed with 通達 or article_kind=notice
        # under this canonical id, to avoid duplicate series).
        placeholder_del = conn.execute(
            """
            DELETE FROM am_law_article
             WHERE law_canonical_id = ?
               AND (article_number LIKE '通達%' OR article_kind = 'notice')
            """,
            (LAW_CANONICAL_ID,),
        ).rowcount

        inserted = 0
        for it in items:
            anchor = it["article_number"]
            full_text = it["body"]
            if it.get("amend"):
                full_text = (full_text + f"\n\n（{it['amend']}）").strip()
            summary = full_text.split("\n", 1)[0][:200] if full_text else None

            conn.execute(
                """
                INSERT INTO am_law_article (
                    law_canonical_id, article_number, article_number_sort,
                    title, text_summary, text_full,
                    source_url, source_fetched_at, article_kind,
                    last_amended
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(law_canonical_id, article_number) DO UPDATE SET
                    article_number_sort = excluded.article_number_sort,
                    title               = excluded.title,
                    text_summary        = excluded.text_summary,
                    text_full           = excluded.text_full,
                    source_url          = excluded.source_url,
                    source_fetched_at   = excluded.source_fetched_at,
                    article_kind        = excluded.article_kind,
                    last_amended        = excluded.last_amended
                """,
                (
                    LAW_CANONICAL_ID,
                    anchor,
                    number_sort_key(anchor),
                    it["title"],
                    summary,
                    full_text,
                    it["source_url"],
                    now,
                    ARTICLE_KIND,
                    it.get("amend"),
                ),
            )
            inserted += 1

        conn.commit()
        return inserted, placeholder_del
    except Exception:
        conn.rollback()
        raise


def integrity_check(conn: sqlite3.Connection) -> dict:
    cur = conn.cursor()
    total = cur.execute(
        "SELECT COUNT(*) FROM am_law_article WHERE law_canonical_id=? AND article_kind=?",
        (LAW_CANONICAL_ID, ARTICLE_KIND),
    ).fetchone()[0]
    missing_title = cur.execute(
        "SELECT COUNT(*) FROM am_law_article WHERE law_canonical_id=? AND article_kind=? AND (title IS NULL OR title='')",
        (LAW_CANONICAL_ID, ARTICLE_KIND),
    ).fetchone()[0]
    missing_body = cur.execute(
        "SELECT COUNT(*) FROM am_law_article WHERE law_canonical_id=? AND article_kind=? AND (text_full IS NULL OR text_full='')",
        (LAW_CANONICAL_ID, ARTICLE_KIND),
    ).fetchone()[0]
    distinct_chapters = cur.execute(
        """
        SELECT COUNT(DISTINCT substr(article_number, 1, instr(article_number,'-')-1))
          FROM am_law_article
         WHERE law_canonical_id=? AND article_kind=?
        """,
        (LAW_CANONICAL_ID, ARTICLE_KIND),
    ).fetchone()[0]
    return {
        "total": total,
        "missing_title": missing_title,
        "missing_body": missing_body,
        "distinct_chapters": distinct_chapters,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not args.cache_dir.is_dir():
        print(f"cache dir missing: {args.cache_dir}", file=sys.stderr)
        return 2

    all_items: list[dict] = []
    pages = 0
    for path, chapter, section, sub in iter_cache_files(args.cache_dir):
        pages += 1
        html = path.read_text(encoding="utf-8", errors="replace")
        src_url = url_for(chapter, section, sub)
        items = parse_leaf(html, chapter, section, sub, src_url)
        _LOG.info(
            "parsed file=%s chapter=%d section=%d sub=%s items=%d",
            path.name, chapter, section, sub, len(items),
        )
        all_items.extend(items)

    _LOG.info("total pages=%d total items=%d", pages, len(all_items))

    # Drop duplicates within items (defensive; UNIQUE would catch too).
    by_num: dict[str, dict] = {}
    for it in all_items:
        key = it["article_number"]
        if key not in by_num:
            by_num[key] = it
        else:
            # Prefer longer body (more informative parse).
            if len(it["body"]) > len(by_num[key]["body"]):
                by_num[key] = it
    deduped = list(by_num.values())
    _LOG.info("after dedup items=%d", len(deduped))

    conn = connect_db(args.db)
    try:
        if not args.dry_run:
            ensure_am_law_row(conn)
            conn.commit()
        inserted, placeholder_del = load(conn, deduped, dry_run=args.dry_run)
        _LOG.info(
            "load inserted=%d placeholders_deleted=%d dry_run=%s",
            inserted, placeholder_del, args.dry_run,
        )
        if not args.dry_run:
            ic = integrity_check(conn)
            _LOG.info("integrity %s", ic)
            print(
                "INGEST_REPORT "
                f"pages={pages} items_parsed={len(all_items)} items_loaded={inserted} "
                f"placeholders_deleted={placeholder_del} total={ic['total']} "
                f"missing_title={ic['missing_title']} missing_body={ic['missing_body']} "
                f"chapters={ic['distinct_chapters']}"
            )
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
