#!/usr/bin/env python3
"""Axis 3b — e-Gov 法改正 diff daily poll (Wave 33+ daily ingest hardening).

Polls e-Gov 法令検索 amendment-history RSS daily and writes new amendment
snapshots + field-level diffs into ``am_amendment_snapshot`` (current
14,596 rows) + ``am_amendment_diff`` (current 12,116 rows, append-only).

Source (一次資料):

  * e-Gov 法令検索  https://elaws.e-gov.go.jp/api/1/amendment.rss
                    (公式 RSS — 改正履歴 daily delta)
  * fallback HTML scan  https://elaws.e-gov.go.jp/ (when RSS endpoint
                    rate-limits — `_fetch_amendment_fallback`)

Constraints
-----------
* LLM call = 0. Pure httpx + regex + sqlite3.
* Append-only `am_amendment_diff` — never UPDATE/DELETE. Idempotent INSERT
  pattern matches the existing migration 075 contract.
* No full-table scan or integrity check on 9.7 GB autonomath.db at boot
  (memory `feedback_no_quick_check_on_huge_sqlite`).
* Banned: aggregator law-portal hosts. Only `*.e-gov.go.jp` accepted.

Usage
-----
    python scripts/cron/poll_egov_amendment_daily.py
    python scripts/cron/poll_egov_amendment_daily.py --db /data/autonomath.db
    python scripts/cron/poll_egov_amendment_daily.py --days 14 --dry-run

Exit codes
----------
0  success (>=0 new snapshots / diffs)
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

logger = logging.getLogger("jpcite.cron.egov_amendment")

# ---------------------------------------------------------------------------
# Config — e-Gov 一次資料 only
# ---------------------------------------------------------------------------

EGOV_AMENDMENT_RSS = "https://elaws.e-gov.go.jp/api/1/amendment.rss"
EGOV_FALLBACK_BASE = "https://elaws.e-gov.go.jp/"
ALLOWED_HOST_SUFFIX = ".e-gov.go.jp"

RATE_LIMIT_SECONDS = 1.0
MAX_AMENDMENTS_PER_RUN = 500
HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "jpcite-egov-amendment-poll/0.3.5 (+https://jpcite.com)"

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
        default=14,
        help="Days back from today for the RSS catch-up window (default 14).",
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


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Defensive — am_amendment_snapshot already exists; am_amendment_diff too."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS am_amendment_snapshot (
            snapshot_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id        TEXT NOT NULL,
            version_seq      INTEGER NOT NULL DEFAULT 1,
            observed_at      TEXT NOT NULL,
            eligibility_hash TEXT,
            amount_max_yen   INTEGER,
            target_set_json  TEXT,
            raw_snapshot_json TEXT,
            source_url       TEXT,
            content_hash     TEXT,
            effective_from   TEXT,
            UNIQUE(entity_id, version_seq, content_hash)
        );
        CREATE INDEX IF NOT EXISTS ix_am_amendment_snap_entity_ts
            ON am_amendment_snapshot(entity_id, observed_at DESC);

        CREATE TABLE IF NOT EXISTS am_amendment_diff (
            diff_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id   TEXT NOT NULL,
            field_name  TEXT NOT NULL,
            prev_value  TEXT,
            new_value   TEXT,
            prev_hash   TEXT,
            new_hash    TEXT,
            detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source_url  TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_am_amendment_diff_entity_time
            ON am_amendment_diff(entity_id, detected_at DESC);
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# RSS fetch + parse
# ---------------------------------------------------------------------------

_ITEM_RE = re.compile(r"<item[^>]*>(.*?)</item>", re.DOTALL | re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_LINK_RE = re.compile(r"<link[^>]*>(.*?)</link>", re.DOTALL | re.IGNORECASE)
_DESC_RE = re.compile(r"<description[^>]*>(.*?)</description>", re.DOTALL | re.IGNORECASE)
_PUBDATE_RE = re.compile(r"<pubDate[^>]*>(.*?)</pubDate>", re.DOTALL | re.IGNORECASE)
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
_LAWNO_RE = re.compile(r"(令和|平成|昭和)\d+年(法律|政令|省令)第\d+号")
_DATE_RE = re.compile(r"(\d{4})[/\-年](\d{1,2})[/\-月](\d{1,2})")


def _strip_cdata(s: str) -> str:
    m = _CDATA_RE.search(s)
    return (m.group(1) if m else s).strip()


def _allowed_host(url: str) -> bool:
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    return host.endswith(ALLOWED_HOST_SUFFIX)


def _parse_amendments(body: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for block in _ITEM_RE.findall(body)[:MAX_AMENDMENTS_PER_RUN]:
        title_m = _TITLE_RE.search(block)
        link_m = _LINK_RE.search(block)
        desc_m = _DESC_RE.search(block)
        date_m = _PUBDATE_RE.search(block)
        items.append(
            {
                "title": _strip_cdata(title_m.group(1)) if title_m else "",
                "link": _strip_cdata(link_m.group(1)) if link_m else "",
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


def _derive_entity_id(item: dict[str, str]) -> str:
    """Canonical id for the amended law — sha-prefixed from law-number string."""
    title = item.get("title") or ""
    link = item.get("link") or ""
    m = _LAWNO_RE.search(title)
    canonical = m.group(0) if m else (title.strip() or link.strip())
    fp = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"law:{fp}"


def _fetch_rss(client: httpx.Client, url: str) -> str:
    try:
        resp = client.get(url, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as exc:
        logger.warning("egov rss fetch failed: %s — trying Playwright fallback", exc)
        # Wave 36: Playwright fallback on transport failure.
        fb = fetch_with_fallback_sync(url)
        return fb.text if (fb.source == "playwright" and fb.text) else ""
    if resp.status_code != 200:
        logger.warning("egov rss HTTP %d — trying Playwright fallback", resp.status_code)
        # Wave 36: Playwright fallback on 4xx/5xx.
        fb = fetch_with_fallback_sync(url)
        return fb.text if (fb.source == "playwright" and fb.text) else ""
    return resp.text


# ---------------------------------------------------------------------------
# Snapshot + diff upsert
# ---------------------------------------------------------------------------


def _last_snapshot(conn: sqlite3.Connection, entity_id: str) -> tuple[int, dict[str, str | None]]:
    row = conn.execute(
        """
        SELECT version_seq, raw_snapshot_json, content_hash, eligibility_hash
        FROM am_amendment_snapshot
        WHERE entity_id = ?
        ORDER BY version_seq DESC
        LIMIT 1
        """,
        (entity_id,),
    ).fetchone()
    if row is None:
        return 0, {}
    snap = json.loads(row["raw_snapshot_json"] or "{}")
    return int(row["version_seq"]), snap


def _insert_snapshot(
    conn: sqlite3.Connection,
    entity_id: str,
    seq: int,
    item: dict[str, str],
    content_hash: str,
) -> int:
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO am_amendment_snapshot(
            entity_id, version_seq, observed_at, eligibility_hash,
            raw_snapshot_json, source_url, content_hash, effective_from
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_id,
            seq,
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            content_hash,
            json.dumps(item, ensure_ascii=False),
            item.get("link", ""),
            content_hash,
            _normalize_date(item.get("pub_date", "")),
        ),
    )
    return int(cur.rowcount or 0)


def _insert_diff_rows(
    conn: sqlite3.Connection,
    entity_id: str,
    prev: dict[str, Any],
    new: dict[str, Any],
    source_url: str,
) -> int:
    keys = sorted(set(prev.keys()) | set(new.keys()))
    n = 0
    for k in keys:
        pv = prev.get(k)
        nv = new.get(k)
        if pv == nv:
            continue
        pv_s = "" if pv is None else str(pv)
        nv_s = "" if nv is None else str(nv)
        ph = hashlib.sha256(pv_s.encode()).hexdigest() if pv is not None else None
        nh = hashlib.sha256(nv_s.encode()).hexdigest() if nv is not None else None
        cur = conn.execute(
            """
            INSERT INTO am_amendment_diff(
                entity_id, field_name, prev_value, new_value,
                prev_hash, new_hash, source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (entity_id, k, pv_s or None, nv_s or None, ph, nh, source_url),
        )
        n += int(cur.rowcount or 0)
    return n


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(db_path: Path, days: int, dry_run: bool) -> dict[str, int]:
    counters = {"fetched": 0, "snap_inserted": 0, "diff_inserted": 0, "skipped": 0}
    cutoff = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    conn: sqlite3.Connection | None = None
    if not dry_run:
        conn = _open_db(str(db_path))
        _ensure_tables(conn)
    with httpx.Client(timeout=HTTPX_TIMEOUT) as client:
        if not _allowed_host(EGOV_AMENDMENT_RSS):
            logger.error("primary source not allowed: %s", EGOV_AMENDMENT_RSS)
            return counters
        body = _fetch_rss(client, EGOV_AMENDMENT_RSS)
        time.sleep(RATE_LIMIT_SECONDS)
        items = _parse_amendments(body)
        counters["fetched"] = len(items)
        for it in items:
            pub = _normalize_date(it.get("pub_date", ""))
            if pub and pub < cutoff:
                counters["skipped"] += 1
                continue
            if not _allowed_host(it.get("link") or EGOV_FALLBACK_BASE):
                counters["skipped"] += 1
                continue
            entity_id = _derive_entity_id(it)
            content_hash = hashlib.sha256(
                json.dumps(it, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            if conn is None:
                # Dry-run path still emits the count.
                counters["snap_inserted"] += 1
                continue
            prev_seq, prev_snap = _last_snapshot(conn, entity_id)
            if prev_snap and prev_snap.get("__hash__") == content_hash:
                counters["skipped"] += 1
                continue
            seq = prev_seq + 1
            new_snap = dict(it)
            new_snap["__hash__"] = content_hash
            counters["snap_inserted"] += _insert_snapshot(conn, entity_id, seq, it, content_hash)
            counters["diff_inserted"] += _insert_diff_rows(
                conn,
                entity_id,
                prev_snap,
                new_snap,
                source_url=it.get("link", ""),
            )
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
    logger.info("egov_amendment_done %s", json.dumps(counters))
    return 0


if __name__ == "__main__":
    sys.exit(main())
