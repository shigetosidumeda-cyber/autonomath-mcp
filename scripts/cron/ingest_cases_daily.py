#!/usr/bin/env python3
"""Wave 43.1.8 — 47都道府県 採択事例 RSS 並列化 (daily).

Polls all 47 prefecture-level adoption RSS feeds in parallel via
ThreadPoolExecutor and upserts into `am_adoption_records`. Target:
+2,350 case rows/day.

CLAUDE.md: NO LLM, no aggregator URLs, idempotent (INSERT OR IGNORE on
UNIQUE sha256).

Usage:
    python scripts/cron/ingest_cases_daily.py
    python scripts/cron/ingest_cases_daily.py --prefectures tokyo,osaka --dry-run
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import logging
import re
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from jpintel_mcp._jpcite_env_bridge import get_flag

try:
    from scripts.etl._playwright_helper import fetch_with_fallback_sync
except ImportError:
    fetch_with_fallback_sync = None  # type: ignore[assignment]

logger = logging.getLogger("jpcite.cron.ingest_cases_daily")

PREFECTURE_RSS: dict[str, str] = {
    "hokkaido": "https://www.pref.hokkaido.lg.jp/rss/subsidy.xml",
    "aomori": "https://www.pref.aomori.lg.jp/rss/subsidy.xml",
    "iwate": "https://www.pref.iwate.jp/rss/subsidy.xml",
    "miyagi": "https://www.pref.miyagi.jp/rss/subsidy.xml",
    "akita": "https://www.pref.akita.lg.jp/rss/subsidy.xml",
    "yamagata": "https://www.pref.yamagata.jp/rss/subsidy.xml",
    "fukushima": "https://www.pref.fukushima.lg.jp/rss/subsidy.xml",
    "ibaraki": "https://www.pref.ibaraki.jp/rss/subsidy.xml",
    "tochigi": "https://www.pref.tochigi.lg.jp/rss/subsidy.xml",
    "gunma": "https://www.pref.gunma.jp/rss/subsidy.xml",
    "saitama": "https://www.pref.saitama.lg.jp/rss/subsidy.xml",
    "chiba": "https://www.pref.chiba.lg.jp/rss/subsidy.xml",
    "tokyo": "https://www.metro.tokyo.lg.jp/rss/subsidy.xml",
    "kanagawa": "https://www.pref.kanagawa.jp/rss/subsidy.xml",
    "niigata": "https://www.pref.niigata.lg.jp/rss/subsidy.xml",
    "toyama": "https://www.pref.toyama.jp/rss/subsidy.xml",
    "ishikawa": "https://www.pref.ishikawa.lg.jp/rss/subsidy.xml",
    "fukui": "https://www.pref.fukui.lg.jp/rss/subsidy.xml",
    "yamanashi": "https://www.pref.yamanashi.jp/rss/subsidy.xml",
    "nagano": "https://www.pref.nagano.lg.jp/rss/subsidy.xml",
    "gifu": "https://www.pref.gifu.lg.jp/rss/subsidy.xml",
    "shizuoka": "https://www.pref.shizuoka.jp/rss/subsidy.xml",
    "aichi": "https://www.pref.aichi.jp/rss/subsidy.xml",
    "mie": "https://www.pref.mie.lg.jp/rss/subsidy.xml",
    "shiga": "https://www.pref.shiga.lg.jp/rss/subsidy.xml",
    "kyoto": "https://www.pref.kyoto.jp/rss/subsidy.xml",
    "osaka": "https://www.pref.osaka.lg.jp/rss/subsidy.xml",
    "hyogo": "https://web.pref.hyogo.lg.jp/rss/subsidy.xml",
    "nara": "https://www.pref.nara.jp/rss/subsidy.xml",
    "wakayama": "https://www.pref.wakayama.lg.jp/rss/subsidy.xml",
    "tottori": "https://www.pref.tottori.lg.jp/rss/subsidy.xml",
    "shimane": "https://www.pref.shimane.lg.jp/rss/subsidy.xml",
    "okayama": "https://www.pref.okayama.jp/rss/subsidy.xml",
    "hiroshima": "https://www.pref.hiroshima.lg.jp/rss/subsidy.xml",
    "yamaguchi": "https://www.pref.yamaguchi.lg.jp/rss/subsidy.xml",
    "tokushima": "https://www.pref.tokushima.lg.jp/rss/subsidy.xml",
    "kagawa": "https://www.pref.kagawa.lg.jp/rss/subsidy.xml",
    "ehime": "https://www.pref.ehime.jp/rss/subsidy.xml",
    "kochi": "https://www.pref.kochi.lg.jp/rss/subsidy.xml",
    "fukuoka": "https://www.pref.fukuoka.lg.jp/rss/subsidy.xml",
    "saga": "https://www.pref.saga.lg.jp/rss/subsidy.xml",
    "nagasaki": "https://www.pref.nagasaki.jp/rss/subsidy.xml",
    "kumamoto": "https://www.pref.kumamoto.jp/rss/subsidy.xml",
    "oita": "https://www.pref.oita.jp/rss/subsidy.xml",
    "miyazaki": "https://www.pref.miyazaki.lg.jp/rss/subsidy.xml",
    "kagoshima": "https://www.pref.kagoshima.jp/rss/subsidy.xml",
    "okinawa": "https://www.pref.okinawa.lg.jp/rss/subsidy.xml",
}

CENTRAL_RSS: tuple[tuple[str, str], ...] = (
    ("mirasapo", "https://www.mirasapo-plus.go.jp/feed/"),
    ("j-grants", "https://www.jgrants-portal.go.jp/rss/"),
)

BANNED_HOSTS: frozenset[str] = frozenset(
    {
        "noukaweb",
        "hojyokin-portal",
        "biz.stayway",
        "subsidy-portal",
        "hojyokin-go",
        "hojo-navi",
        "mirai-joho",
    }
)

RATE_LIMIT_SECONDS = 1.0
MAX_ITEMS_PER_FEED = 200
HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "jpcite-cases-daily/0.3.5 (+https://jpcite.com)"
DEFAULT_MAX_WORKERS = 16

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = _REPO_ROOT / "autonomath.db"


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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument(
        "--db",
        default=get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH", str(DEFAULT_DB_PATH)),
    )
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--prefectures", default="all")
    p.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


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
            retrieved_at          TEXT NOT NULL,
            prefecture            TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_am_adoption_program
            ON am_adoption_records(program_id);
        CREATE INDEX IF NOT EXISTS ix_am_adoption_houjin
            ON am_adoption_records(adopter_houjin_bangou);
        CREATE INDEX IF NOT EXISTS ix_am_adoption_date
            ON am_adoption_records(adopted_at);
        CREATE INDEX IF NOT EXISTS ix_am_adoption_pref
            ON am_adoption_records(prefecture);
        """
    )
    try:
        conn.execute("ALTER TABLE am_adoption_records ADD COLUMN prefecture TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()


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
    try:
        return datetime.strptime(raw[:25], "%a, %d %b %Y %H:%M:%S").date().isoformat()
    except ValueError:
        return ""


def _is_banned(url: str) -> bool:
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    return any(b in host for b in BANNED_HOSTS)


def _build_row(
    item: dict[str, str], source_feed: str, prefecture: str | None
) -> dict[str, Any] | None:
    title = (item.get("title") or "").strip()
    link = (item.get("link") or "").strip()
    desc = (item.get("description") or "").strip()
    pub = _normalize_date(item.get("pub_date") or "")
    if not (title and link and pub):
        return None
    if _is_banned(link):
        logger.warning("banned host skip: %s", link)
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
        "prefecture": prefecture,
    }


def _fetch_one(label: str, url: str) -> tuple[str, list[dict[str, str]]]:
    if _is_banned(url):
        return label, []
    try:
        with httpx.Client(timeout=HTTPX_TIMEOUT) as client:
            resp = client.get(url, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as exc:
        logger.warning("[%s] httpx err: %s — trying Playwright fallback", label, exc)
        if fetch_with_fallback_sync is None:
            return label, []
        try:
            fb = fetch_with_fallback_sync(url)
            if fb.source == "playwright" and fb.text:
                return label, _parse_feed_body(fb.text)
        except Exception as exc2:  # noqa: BLE001
            logger.debug("[%s] playwright err: %s", label, exc2)
        return label, []
    if resp.status_code != 200:
        logger.warning("[%s] HTTP %d — trying Playwright fallback", label, resp.status_code)
        if fetch_with_fallback_sync is None:
            return label, []
        try:
            fb = fetch_with_fallback_sync(url)
            if fb.source == "playwright" and fb.text:
                return label, _parse_feed_body(fb.text)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[%s] playwright err: %s", label, exc)
        return label, []
    return label, _parse_feed_body(resp.text)


def _upsert(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO am_adoption_records(
                program_id, program_name, adopter_name,
                adopter_houjin_bangou, adopted_at, announce_url,
                source_feed, sha256, retrieved_at, prefecture
            ) VALUES (
                :program_id, :program_name, :adopter_name,
                :adopter_houjin_bangou, :adopted_at, :announce_url,
                :source_feed, :sha256, :retrieved_at, :prefecture
            )
            """,
            row,
        )
    except sqlite3.OperationalError as exc:
        logger.warning("upsert fail: %s", exc)
        return 0
    return int(cur.rowcount or 0)


def run(
    db_path: Path, days: int, dry_run: bool, prefectures: list[str], max_workers: int
) -> dict[str, Any]:
    counters: dict[str, int] = {
        "fetched": 0,
        "parsed": 0,
        "inserted": 0,
        "skipped": 0,
        "feeds_ok": 0,
        "feeds_fail": 0,
    }
    pref_counts: dict[str, int] = {}
    cutoff = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    conn: sqlite3.Connection | None = None
    if not dry_run:
        conn = _open_db(str(db_path))
        _ensure_table(conn)

    feeds: list[tuple[str, str, str | None]] = []
    for label, url in CENTRAL_RSS:
        feeds.append((label, url, None))
    if prefectures == ["all"]:
        for pref, url in PREFECTURE_RSS.items():
            feeds.append((pref, url, pref))
    else:
        for pref in prefectures:
            if pref in PREFECTURE_RSS:
                feeds.append((pref, PREFECTURE_RSS[pref], pref))
            else:
                logger.warning("unknown prefecture: %s", pref)

    logger.info("[plan] %d feeds, max_workers=%d cutoff=%s", len(feeds), max_workers, cutoff)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_fetch_one, label, url): (label, url, pref) for label, url, pref in feeds
        }
        for fut in concurrent.futures.as_completed(futures):
            label, _url, pref = futures[fut]
            try:
                label2, items = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] worker err: %s", label, exc)
                counters["feeds_fail"] += 1
                continue
            counters["fetched"] += len(items)
            if items:
                counters["feeds_ok"] += 1
            else:
                counters["feeds_fail"] += 1
            for it in items:
                row = _build_row(it, label2, pref)
                if row is None:
                    counters["skipped"] += 1
                    continue
                if row["adopted_at"] < cutoff:
                    counters["skipped"] += 1
                    continue
                counters["parsed"] += 1
                if conn is not None:
                    delta = _upsert(conn, row)
                    counters["inserted"] += delta
                    if delta and pref:
                        pref_counts[pref] = pref_counts.get(pref, 0) + 1

    if conn is not None:
        conn.commit()
        conn.close()

    out = dict(counters)
    out["pref_counts"] = pref_counts
    out["cutoff"] = cutoff
    out["feeds_planned"] = len(feeds)
    return out


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.prefectures == "all":
        prefectures = ["all"]
    else:
        prefectures = [p.strip() for p in args.prefectures.split(",") if p.strip()]
    try:
        out = run(
            Path(args.db),
            days=args.days,
            dry_run=args.dry_run,
            prefectures=prefectures,
            max_workers=args.max_workers,
        )
    except FileNotFoundError as exc:
        logger.error("db_missing path=%s err=%s", args.db, exc)
        return 1
    except (httpx.HTTPError, sqlite3.DatabaseError) as exc:
        logger.error("fatal err=%s", exc)
        return 1
    logger.info("ingest_cases_daily_done %s", json.dumps(out))
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
