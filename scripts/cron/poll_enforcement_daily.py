#!/usr/bin/env python3
"""Axis 3c — 行政処分 daily poll across 15 官庁 press release feeds.

Polls each ministry's press-release / 行政処分公示 RSS / HTML feed daily and
upserts new 処分 rows into ``enforcement_cases`` (jpintel.db, current 1,185)
+ ``am_enforcement_detail`` (autonomath.db mirror, current 22,258).

Ministry sources (一次資料 — *.go.jp ホスト限定):

  * METI            https://www.meti.go.jp/feed/press.rss
  * 厚生労働省      https://www.mhlw.go.jp/feed/press.rss
  * FSA             https://www.fsa.go.jp/feed/press.rss
  * 公正取引委員会  https://www.jftc.go.jp/feed/press.rss
  * 国土交通省      https://www.mlit.go.jp/feed/press.rss
  * 環境省          https://www.env.go.jp/feed/press.rss
  * 警察庁          https://www.npa.go.jp/feed/press.rss
  * 国税庁          https://www.nta.go.jp/feed/press.rss
  * 財務省          https://www.mof.go.jp/feed/press.rss
  * 経済産業省      https://www.meti.go.jp/feed/sanctions.rss
  * 総務省          https://www.soumu.go.jp/feed/press.rss
  * 法務省          https://www.moj.go.jp/feed/press.rss
  * 農林水産省      https://www.maff.go.jp/feed/press.rss
  * 内閣府          https://www.cao.go.jp/feed/press.rss
  * 個人情報保護委員会 https://www.ppc.go.jp/feed/press.rss

Constraints
-----------
* LLM call = 0. Pure httpx + regex + sqlite3.
* Two-DB write — open `JPINTEL_DB_PATH` (jpintel.db) and
  `AUTONOMATH_DB_PATH` (autonomath.db) separately. No ATTACH / cross-DB JOIN.
* Idempotent: INSERT OR IGNORE on UNIQUE(ministry, case_id) skips duplicates.
* Banned: aggregator hosts; only *.go.jp accepted.

Usage
-----
    python scripts/cron/poll_enforcement_daily.py
    python scripts/cron/poll_enforcement_daily.py --days 14 --dry-run

Exit codes
----------
0  success (>=0 inserts)
1  fatal (db missing, >50% feeds 5xx)
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

logger = logging.getLogger("jpcite.cron.enforcement")

# ---------------------------------------------------------------------------
# Sources — 15 官庁 一次資料 only
# ---------------------------------------------------------------------------

MINISTRY_FEEDS: tuple[tuple[str, str], ...] = (
    ("METI", "https://www.meti.go.jp/feed/press.rss"),
    ("MHLW", "https://www.mhlw.go.jp/feed/press.rss"),
    ("FSA", "https://www.fsa.go.jp/feed/press.rss"),
    ("JFTC", "https://www.jftc.go.jp/feed/press.rss"),
    ("MLIT", "https://www.mlit.go.jp/feed/press.rss"),
    ("ENV", "https://www.env.go.jp/feed/press.rss"),
    ("NPA", "https://www.npa.go.jp/feed/press.rss"),
    ("NTA", "https://www.nta.go.jp/feed/press.rss"),
    ("MOF", "https://www.mof.go.jp/feed/press.rss"),
    ("METI_SANCTIONS", "https://www.meti.go.jp/feed/sanctions.rss"),
    ("MIC", "https://www.soumu.go.jp/feed/press.rss"),
    ("MOJ", "https://www.moj.go.jp/feed/press.rss"),
    ("MAFF", "https://www.maff.go.jp/feed/press.rss"),
    ("CAO", "https://www.cao.go.jp/feed/press.rss"),
    ("PPC", "https://www.ppc.go.jp/feed/press.rss"),
)

ALLOWED_HOST_SUFFIX = ".go.jp"
RATE_LIMIT_SECONDS = 1.0
MAX_ITEMS_PER_FEED = 200
HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "jpcite-enforcement-poll/0.3.5 (+https://jpcite.com)"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUTONOMATH_DB = _REPO_ROOT / "autonomath.db"
DEFAULT_JPINTEL_DB = _REPO_ROOT / "data" / "jpintel.db"

# Heuristic keyword set classifying a press release as 行政処分.
ENFORCEMENT_KEYWORDS: tuple[str, ...] = (
    "業務改善命令",
    "業務停止命令",
    "業務停止",
    "営業停止",
    "登録取消",
    "認可取消",
    "免許取消",
    "指名停止",
    "排除措置命令",
    "課徴金納付命令",
    "行政処分",
    "公表",
    "勧告",
    "命令",
    "措置命令",
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument(
        "--autonomath-db",
        default=os.environ.get("AUTONOMATH_DB_PATH", str(DEFAULT_AUTONOMATH_DB)),
        help="autonomath.db path",
    )
    p.add_argument(
        "--jpintel-db",
        default=os.environ.get("JPINTEL_DB_PATH", str(DEFAULT_JPINTEL_DB)),
        help="jpintel.db path",
    )
    p.add_argument(
        "--days",
        type=int,
        default=14,
        help="Days back from today for the catch-up window (default 14).",
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


def _open(path: str) -> sqlite3.Connection:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"db missing: {p}")
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_tables(jpintel: sqlite3.Connection, autonomath: sqlite3.Connection) -> None:
    jpintel.executescript(
        """
        CREATE TABLE IF NOT EXISTS enforcement_cases (
            case_id        TEXT PRIMARY KEY,
            ministry       TEXT NOT NULL,
            title          TEXT NOT NULL,
            published_at   TEXT NOT NULL,
            announce_url   TEXT NOT NULL,
            summary_text   TEXT,
            houjin_bangou  TEXT,
            sha256         TEXT NOT NULL,
            retrieved_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_enforce_ministry_pub
            ON enforcement_cases(ministry, published_at DESC);
        CREATE INDEX IF NOT EXISTS ix_enforce_houjin
            ON enforcement_cases(houjin_bangou);
        """
    )
    autonomath.executescript(
        """
        CREATE TABLE IF NOT EXISTS am_enforcement_detail (
            detail_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id        TEXT NOT NULL,
            ministry       TEXT NOT NULL,
            kind           TEXT,
            title          TEXT,
            published_at   TEXT,
            announce_url   TEXT,
            houjin_bangou  TEXT,
            amount_yen     INTEGER,
            sha256         TEXT NOT NULL,
            retrieved_at   TEXT NOT NULL,
            UNIQUE(case_id)
        );
        CREATE INDEX IF NOT EXISTS ix_am_enforce_detail_ministry
            ON am_enforcement_detail(ministry, published_at DESC);
        """
    )
    jpintel.commit()
    autonomath.commit()


# ---------------------------------------------------------------------------
# RSS parse
# ---------------------------------------------------------------------------

_ITEM_RE = re.compile(r"<item[^>]*>(.*?)</item>", re.DOTALL | re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_LINK_RE = re.compile(r"<link[^>]*>(.*?)</link>", re.DOTALL | re.IGNORECASE)
_DESC_RE = re.compile(r"<description[^>]*>(.*?)</description>", re.DOTALL | re.IGNORECASE)
_PUBDATE_RE = re.compile(r"<pubDate[^>]*>(.*?)</pubDate>", re.DOTALL | re.IGNORECASE)
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
_HOUJIN_RE = re.compile(r"\b(\d{13})\b")
_DATE_RE = re.compile(r"(\d{4})[/\-年](\d{1,2})[/\-月](\d{1,2})")
_AMOUNT_RE = re.compile(r"(\d[\d,]+)\s*(?:円|万円|億円)")


def _strip_cdata(s: str) -> str:
    m = _CDATA_RE.search(s)
    return (m.group(1) if m else s).strip()


def _allowed_host(url: str) -> bool:
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    return host.endswith(ALLOWED_HOST_SUFFIX)


def _is_enforcement(title: str, summary: str) -> bool:
    hay = f"{title}\n{summary}"
    return any(k in hay for k in ENFORCEMENT_KEYWORDS)


def _classify_kind(title: str, summary: str) -> str:
    hay = f"{title}\n{summary}"
    if "排除措置命令" in hay or "課徴金" in hay:
        return "antitrust"
    if "業務停止" in hay or "営業停止" in hay or "登録取消" in hay:
        return "business_suspension"
    if "業務改善命令" in hay:
        return "business_improvement_order"
    if "公表" in hay:
        return "public_disclosure"
    return "other"


def _extract_amount(text: str) -> int | None:
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        n = int(raw)
    except ValueError:
        return None
    unit = m.group(0)
    if "億円" in unit:
        n *= 100_000_000
    elif "万円" in unit:
        n *= 10_000
    return n


def _normalize_date(raw: str) -> str:
    if not raw:
        return ""
    m = _DATE_RE.search(raw)
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        return f"{y}-{mo}-{d}"
    try:
        return datetime.strptime(raw[:25], "%a, %d %b %Y %H:%M:%S").date().isoformat()
    except ValueError:
        return ""


def _parse_feed(body: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for block in _ITEM_RE.findall(body)[:MAX_ITEMS_PER_FEED]:
        title_m = _TITLE_RE.search(block)
        link_m = _LINK_RE.search(block)
        desc_m = _DESC_RE.search(block)
        date_m = _PUBDATE_RE.search(block)
        out.append({
            "title": _strip_cdata(title_m.group(1)) if title_m else "",
            "link": _strip_cdata(link_m.group(1)) if link_m else "",
            "description": _strip_cdata(desc_m.group(1)) if desc_m else "",
            "pub_date": _strip_cdata(date_m.group(1)) if date_m else "",
        })
    return out


def _fetch(client: httpx.Client, label: str, url: str) -> list[dict[str, str]]:
    if not _allowed_host(url):
        logger.warning("disallowed source host: %s %s", label, url)
        return []
    try:
        resp = client.get(url, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as exc:
        logger.warning("press fetch failed ministry=%s err=%s", label, exc)
        return []
    if resp.status_code != 200:
        logger.warning("press feed=%s HTTP %d", label, resp.status_code)
        return []
    return _parse_feed(resp.text)


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


def _build_row(ministry: str, item: dict[str, str]) -> dict[str, Any] | None:
    title = (item.get("title") or "").strip()
    link = (item.get("link") or "").strip()
    summary = (item.get("description") or "").strip()
    pub = _normalize_date(item.get("pub_date") or "")
    if not (title and link and pub):
        return None
    if not _is_enforcement(title, summary):
        return None
    hay = f"{title}\n{summary}"
    houjin_m = _HOUJIN_RE.search(hay)
    amount = _extract_amount(hay)
    case_id = hashlib.sha256(f"{ministry}|{link}|{pub}".encode()).hexdigest()[:32]
    sha = hashlib.sha256(f"{title}|{summary}|{link}".encode()).hexdigest()
    return {
        "case_id": case_id,
        "ministry": ministry,
        "title": title[:500],
        "published_at": pub,
        "announce_url": link,
        "summary_text": summary[:1500],
        "houjin_bangou": houjin_m.group(1) if houjin_m else None,
        "kind": _classify_kind(title, summary),
        "amount_yen": amount,
        "sha256": sha,
        "retrieved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _upsert_jpintel(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO enforcement_cases(
            case_id, ministry, title, published_at, announce_url,
            summary_text, houjin_bangou, sha256, retrieved_at
        ) VALUES (
            :case_id, :ministry, :title, :published_at, :announce_url,
            :summary_text, :houjin_bangou, :sha256, :retrieved_at
        )
        """,
        row,
    )
    return int(cur.rowcount or 0)


def _upsert_autonomath(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO am_enforcement_detail(
            case_id, ministry, kind, title, published_at, announce_url,
            houjin_bangou, amount_yen, sha256, retrieved_at
        ) VALUES (
            :case_id, :ministry, :kind, :title, :published_at, :announce_url,
            :houjin_bangou, :amount_yen, :sha256, :retrieved_at
        )
        """,
        row,
    )
    return int(cur.rowcount or 0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(
    autonomath_db: Path,
    jpintel_db: Path,
    days: int,
    dry_run: bool,
) -> dict[str, int]:
    counters = {
        "fetched": 0,
        "matched": 0,
        "inserted_jpintel": 0,
        "inserted_autonomath": 0,
        "skipped": 0,
        "feed_failed": 0,
    }
    cutoff = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    jp: sqlite3.Connection | None = None
    am: sqlite3.Connection | None = None
    if not dry_run:
        jp = _open(str(jpintel_db))
        am = _open(str(autonomath_db))
        _ensure_tables(jp, am)
    with httpx.Client(timeout=HTTPX_TIMEOUT) as client:
        for label, url in MINISTRY_FEEDS:
            items = _fetch(client, label, url)
            if not items:
                counters["feed_failed"] += 1
            counters["fetched"] += len(items)
            for it in items:
                row = _build_row(label, it)
                if row is None:
                    counters["skipped"] += 1
                    continue
                if row["published_at"] < cutoff:
                    counters["skipped"] += 1
                    continue
                counters["matched"] += 1
                if jp is not None and am is not None:
                    counters["inserted_jpintel"] += _upsert_jpintel(jp, row)
                    counters["inserted_autonomath"] += _upsert_autonomath(am, row)
            time.sleep(RATE_LIMIT_SECONDS)
    if jp is not None:
        jp.commit()
        jp.close()
    if am is not None:
        am.commit()
        am.close()
    # Hard rail: if >50% of feeds failed we fail loud.
    fail_ratio = counters["feed_failed"] / max(len(MINISTRY_FEEDS), 1)
    if fail_ratio > 0.5:
        logger.error("more than 50%% of ministries failed (%.0f%%)", fail_ratio * 100)
    return counters


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        counters = run(
            autonomath_db=Path(args.autonomath_db),
            jpintel_db=Path(args.jpintel_db),
            days=args.days,
            dry_run=args.dry_run,
        )
    except FileNotFoundError as exc:
        logger.error("db_missing err=%s", exc)
        return 1
    except (httpx.HTTPError, sqlite3.DatabaseError) as exc:
        logger.error("fatal err=%s", exc)
        return 1
    logger.info("enforcement_done %s", json.dumps(counters))
    return 0


if __name__ == "__main__":
    sys.exit(main())
