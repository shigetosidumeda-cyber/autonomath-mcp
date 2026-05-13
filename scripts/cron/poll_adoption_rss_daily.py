#!/usr/bin/env python3
"""Axis 3a — 採択 RSS daily poll (Wave 33+ daily ingest hardening).

Polls 一次資料 adoption-announcement RSS feeds daily and upserts new rows into
``am_adoption_records`` (legacy mirror `jpi_adoption_records` is read-only —
this cron writes only the canonical autonomath.db side and lets the
nightly view/refresh sync the jpi mirror).

Sources (一次資料のみ — aggregator banned per memory `feedback_no_fake_data`):

  * mirasapo-plus  https://www.mirasapo-plus.go.jp/feed/
  * j-grants       https://www.jgrants-portal.go.jp/rss/
  * Prefecture RSS https://www.pref.<jis2>.lg.jp/.../subsidy.rss  (47都道府県、
                   `data/adoption_rss_sources.json` で運用維持)

Constraints
-----------
* LLM call = 0. Pure feedparser + sqlite3 + httpx.
* Read-only `am_entities` cross-check; write-only `am_adoption_records`.
* No `PRAGMA integrity_check` / `sha256sum` / `VACUUM full` on autonomath.db
  (>9.7 GB; memory `feedback_no_quick_check_on_huge_sqlite`).
* Idempotent: INSERT OR IGNORE on UNIQUE sha256 skips duplicates so re-runs
  in the same window are no-ops.
* Aggregator URLs (noukaweb / hojyokin-portal / biz.stayway) hard-banned
  per CLAUDE.md "Data hygiene" rule.

Usage
-----
    python scripts/cron/poll_adoption_rss_daily.py
    python scripts/cron/poll_adoption_rss_daily.py --db /data/autonomath.db
    python scripts/cron/poll_adoption_rss_daily.py --days 30 --dry-run

Exit codes
----------
0  success (>=0 new rows)
1  fatal (db missing, all feeds 5xx past retry budget)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Wave 36 wire marker.
from scripts.etl._playwright_helper import fetch_with_fallback_sync  # noqa: E402

logger = logging.getLogger("jpcite.cron.adoption_rss")

# ---------------------------------------------------------------------------
# Config — 一次資料 RSS endpoints only
# ---------------------------------------------------------------------------

RSS_FEEDS: tuple[tuple[str, str], ...] = (
    ("mirasapo", "https://www.mirasapo-plus.go.jp/feed/"),
    ("j-grants", "https://www.jgrants-portal.go.jp/rss/"),
    # Top 5 採択 volume prefectures by program count — extend via data/ JSON.
    ("tokyo", "https://www.metro.tokyo.lg.jp/rss/subsidy.xml"),
    ("osaka", "https://www.pref.osaka.lg.jp/rss/subsidy.xml"),
    ("aichi", "https://www.pref.aichi.jp/rss/subsidy.xml"),
    ("kanagawa", "https://www.pref.kanagawa.jp/rss/subsidy.xml"),
    ("hokkaido", "https://www.pref.hokkaido.lg.jp/rss/subsidy.xml"),
)

# Banned aggregator host substrings (CLAUDE.md 一次資料 rule).
BANNED_HOSTS: frozenset[str] = frozenset(
    {
        "noukaweb",
        "hojyokin-portal",
        "biz.stayway",
        "subsidy-portal",
        "hojyokin-go",
    }
)

RATE_LIMIT_SECONDS = 1.0
MAX_ITEMS_PER_FEED = 200
HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "jpcite-adoption-rss-poll/0.3.5 (+https://jpcite.com)"

DEFAULT_DB_PATH = _REPO_ROOT / "autonomath.db"

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument(
        "--db",
        default=os.environ.get("AUTONOMATH_DB_PATH", str(DEFAULT_DB_PATH)),
        help="autonomath.db path (default: %(default)s).",
    )
    p.add_argument(
        "--days",
        type=int,
        default=7,
        help="Days back from today for the RSS catch-up window (default 7).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch+parse only; do not insert.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------


def _open_db(path: str) -> sqlite3.Connection:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"autonomath.db missing: {p}")
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Create am_adoption_records if absent (defensive — usually exists)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS am_adoption_records (
            adoption_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            program_id            TEXT,
            program_name          TEXT,
            adopter_name          TEXT,
            adopter_houjin_bangou TEXT,
            adopted_at            TEXT,
            announce_url          TEXT,
            source_feed           TEXT,
            sha256                TEXT NOT NULL UNIQUE,
            retrieved_at          TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_am_adoption_program
            ON am_adoption_records(program_id);
        CREATE INDEX IF NOT EXISTS ix_am_adoption_houjin
            ON am_adoption_records(adopter_houjin_bangou);
        CREATE INDEX IF NOT EXISTS ix_am_adoption_date
            ON am_adoption_records(adopted_at);
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# RSS fetch + parse — minimal RSS 2.0 / Atom parser (no extra dep)
# ---------------------------------------------------------------------------

_ITEM_RE = re.compile(r"<item[^>]*>(.*?)</item>", re.DOTALL | re.IGNORECASE)
_ENTRY_RE = re.compile(r"<entry[^>]*>(.*?)</entry>", re.DOTALL | re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_LINK_RE = re.compile(r"<link[^>]*(?:href=\"([^\"]+)\"|>(.*?)</link>)", re.DOTALL | re.IGNORECASE)
_DESC_RE = re.compile(
    r"<(?:description|summary)[^>]*>(.*?)</(?:description|summary)>",
    re.DOTALL | re.IGNORECASE,
)
_PUBDATE_RE = re.compile(
    r"<(?:pubDate|updated|published)[^>]*>(.*?)</(?:pubDate|updated|published)>",
    re.DOTALL | re.IGNORECASE,
)
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
_HOUJIN_RE = re.compile(r"\b(\d{13})\b")
_DATE_RE = re.compile(r"(\d{4})[/\-年](\d{1,2})[/\-月](\d{1,2})")


def _strip_cdata(s: str) -> str:
    m = _CDATA_RE.search(s)
    return (m.group(1) if m else s).strip()


def _parse_feed_body(body: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    blocks = _ITEM_RE.findall(body) or _ENTRY_RE.findall(body)
    for block in blocks[:MAX_ITEMS_PER_FEED]:
        title_m = _TITLE_RE.search(block)
        link_m = _LINK_RE.search(block)
        desc_m = _DESC_RE.search(block)
        date_m = _PUBDATE_RE.search(block)
        link = ""
        if link_m:
            link = (link_m.group(1) or link_m.group(2) or "").strip()
        items.append(
            {
                "title": _strip_cdata(title_m.group(1)) if title_m else "",
                "link": link,
                "description": _strip_cdata(desc_m.group(1)) if desc_m else "",
                "pub_date": _strip_cdata(date_m.group(1)) if date_m else "",
            }
        )
    return items


def _normalize_date(raw: str) -> str:
    if not raw:
        return ""
    m = _DATE_RE.search(raw)
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        return f"{y}-{mo}-{d}"
    # RFC 822 fallback
    try:
        return datetime.strptime(raw[:25], "%a, %d %b %Y %H:%M:%S").date().isoformat()
    except ValueError:
        return ""


def _is_banned(url: str) -> bool:
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    return any(b in host for b in BANNED_HOSTS)


def _build_row(item: dict[str, str], source_feed: str) -> dict[str, Any] | None:
    title = (item.get("title") or "").strip()
    link = (item.get("link") or "").strip()
    desc = (item.get("description") or "").strip()
    pub = _normalize_date(item.get("pub_date") or "")
    if not (title and link and pub):
        return None
    if _is_banned(link):
        logger.warning("banned aggregator host skipped: %s", link)
        return None
    haystack = f"{title}\n{desc}"
    houjin_m = _HOUJIN_RE.search(haystack)
    houjin = houjin_m.group(1) if houjin_m else None
    sha = hashlib.sha256(f"{link}|{title}|{pub}".encode()).hexdigest()
    return {
        "program_id": None,
        "program_name": title[:300],
        "adopter_name": None,
        "adopter_houjin_bangou": houjin,
        "adopted_at": pub,
        "announce_url": link,
        "source_feed": source_feed,
        "sha256": sha,
        "retrieved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _fetch_feed(client: httpx.Client, label: str, url: str) -> list[dict[str, str]]:
    try:
        resp = client.get(url, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as exc:
        logger.warning("rss fetch failed feed=%s err=%s — trying Playwright fallback", label, exc)
        # Wave 36: Playwright fallback on transport failure.
        fb = fetch_with_fallback_sync(url)
        if fb.source == "playwright" and fb.text:
            return _parse_feed_body(fb.text)
        return []
    if resp.status_code != 200:
        logger.warning("rss feed=%s HTTP %d — trying Playwright fallback", label, resp.status_code)
        # Wave 36: Playwright fallback on 4xx/5xx.
        fb = fetch_with_fallback_sync(url)
        if fb.source == "playwright" and fb.text:
            return _parse_feed_body(fb.text)
        return []
    body = resp.text
    return _parse_feed_body(body)


def _upsert(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO am_adoption_records(
                program_id, program_name, adopter_name,
                adopter_houjin_bangou, adopted_at, announce_url,
                source_feed, sha256, retrieved_at
            ) VALUES (
                :program_id, :program_name, :adopter_name,
                :adopter_houjin_bangou, :adopted_at, :announce_url,
                :source_feed, :sha256, :retrieved_at
            )
            """,
            row,
        )
    except sqlite3.OperationalError as exc:
        logger.warning("am_adoption_records upsert failed: %s", exc)
        return 0
    return int(cur.rowcount or 0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(db_path: Path, days: int, dry_run: bool) -> dict[str, int]:
    counters: dict[str, int] = {"fetched": 0, "parsed": 0, "inserted": 0, "skipped": 0}
    cutoff = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    conn: sqlite3.Connection | None = None
    if not dry_run:
        conn = _open_db(str(db_path))
        _ensure_table(conn)
    with httpx.Client(timeout=HTTPX_TIMEOUT) as client:
        for label, url in RSS_FEEDS:
            if _is_banned(url):
                logger.warning("source banned: %s %s", label, url)
                continue
            items = _fetch_feed(client, label, url)
            counters["fetched"] += len(items)
            for it in items:
                row = _build_row(it, label)
                if row is None:
                    counters["skipped"] += 1
                    continue
                if row["adopted_at"] < cutoff:
                    counters["skipped"] += 1
                    continue
                counters["parsed"] += 1
                if conn is not None:
                    counters["inserted"] += _upsert(conn, row)
            time.sleep(RATE_LIMIT_SECONDS)
    if conn is not None:
        conn.commit()
        conn.close()
    return counters


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        counters = run(Path(args.db), days=args.days, dry_run=args.dry_run)
    except FileNotFoundError as exc:
        logger.error("db_missing path=%s err=%s", args.db, exc)
        return 1
    except (httpx.HTTPError, sqlite3.DatabaseError) as exc:
        logger.error("fatal err=%s", exc)
        return 1
    logger.info("adoption_rss_done %s", json.dumps(counters))
    return 0


if __name__ == "__main__":
    sys.exit(main())
