#!/usr/bin/env python3
"""Axis 3d — 予算成立 → 補助金 announce chain detector.

Joins 衆議院・参議院 議案情報 (本会議で予算可決) with その後 30 日以内の
各官庁 補助金 announce, writing pairs into ``am_budget_subsidy_chain``
(migration 234) so agents can answer 「この補助金は何の予算で出たか」 directly.

Sources (一次資料):

  * 衆議院 議案情報    https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/menu_kaiji.htm
  * 参議院 議案情報    https://www.sangiin.go.jp/japanese/joho1/kousei/gian/menu.htm
  * 各官庁 announce RSS — same set as enforcement cron (15 ministries)

Chain rule
----------

For every budget bill row passed in 衆議院本会議 within the catch-up window,
walk forward at most ``--lag-days`` (default 30) calendar days through the
ministry announce stream and emit one chain row per (budget_kokkai_id,
subsidy_program_id) UNIQUE pair detected. ``programs.triggered_by_budget_id``
on autonomath.db is mirrored via UPDATE so REST search surfaces the answer.

Constraints
-----------
* LLM call = 0. Pure httpx + regex + sqlite3.
* Idempotent: INSERT OR IGNORE on UNIQUE(budget_kokkai_id, subsidy_program_id).
* No aggregator hosts; *.go.jp only.
* No DB full-scan or integrity_check at boot.

Usage
-----
    python scripts/cron/detect_budget_to_subsidy_chain.py
    python scripts/cron/detect_budget_to_subsidy_chain.py --lag-days 30 --dry-run

Exit codes
----------
0  success (>=0 chain rows)
1  fatal (db missing, both 議案 sources 5xx)
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("jpcite.cron.budget_subsidy_chain")

# ---------------------------------------------------------------------------
# Sources — *.go.jp only
# ---------------------------------------------------------------------------

SHUGIIN_GIAN_URL = (
    "https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/menu_kaiji.htm"
)
SANGIIN_GIAN_URL = (
    "https://www.sangiin.go.jp/japanese/joho1/kousei/gian/menu.htm"
)

MINISTRY_FEEDS: tuple[tuple[str, str], ...] = (
    ("METI", "https://www.meti.go.jp/feed/press.rss"),
    ("MHLW", "https://www.mhlw.go.jp/feed/press.rss"),
    ("MAFF", "https://www.maff.go.jp/feed/press.rss"),
    ("MLIT", "https://www.mlit.go.jp/feed/press.rss"),
    ("ENV", "https://www.env.go.jp/feed/press.rss"),
    ("FSA", "https://www.fsa.go.jp/feed/press.rss"),
    ("NTA", "https://www.nta.go.jp/feed/press.rss"),
    ("MOF", "https://www.mof.go.jp/feed/press.rss"),
    ("CAO", "https://www.cao.go.jp/feed/press.rss"),
)

ALLOWED_HOST_SUFFIX = ".go.jp"
RATE_LIMIT_SECONDS = 1.0
HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "jpcite-budget-subsidy-chain/0.3.5 (+https://jpcite.com)"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUTONOMATH_DB = _REPO_ROOT / "autonomath.db"

# Heuristic for budget bills.
BUDGET_BILL_RE = re.compile(
    r"(?:補正)?予算(?:案)?(?:.{0,20})(?:本会議.*?可決|成立)"
)
KOKKAI_ID_RE = re.compile(r"第(\d{1,3})回.*?(?:議案)?\D(\d{1,4})")
SUBSIDY_KEYWORDS = ("補助金", "助成金", "交付金", "補助事業", "公募", "公募開始")
DATE_RE = re.compile(r"(\d{4})[/\-年](\d{1,2})[/\-月](\d{1,2})")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument(
        "--db",
        default=os.environ.get("AUTONOMATH_DB_PATH", str(DEFAULT_AUTONOMATH_DB)),
    )
    p.add_argument(
        "--lag-days",
        type=int,
        default=30,
        help="Maximum lag in days between budget passage and subsidy announce.",
    )
    p.add_argument(
        "--window-days",
        type=int,
        default=60,
        help="How far back from today to look for budget passings (default 60).",
    )
    p.add_argument("--dry-run", action="store_true")
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


def _ensure_program_column(conn: sqlite3.Connection) -> None:
    """Defensively add programs.triggered_by_budget_id (idempotent)."""
    row = conn.execute(
        "SELECT value FROM am_budget_subsidy_chain_meta WHERE key = 'column_triggered_by_budget_id_added'"
    ).fetchone()
    if row is not None and row["value"] == "done":
        return
    # programs table is mirrored as `programs` on jpintel.db side; on
    # autonomath.db side the program rows live in `am_entities` (kind='program').
    # We add a column on the am-side proxy table when present.
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(programs)").fetchall()}
    if cols and "triggered_by_budget_id" not in cols:
        try:
            conn.execute("ALTER TABLE programs ADD COLUMN triggered_by_budget_id TEXT")
        except sqlite3.OperationalError as exc:
            logger.warning("programs column ALTER failed (best-effort): %s", exc)
    conn.execute(
        """
        UPDATE am_budget_subsidy_chain_meta
        SET value = 'done'
        WHERE key = 'column_triggered_by_budget_id_added'
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Fetch + parse
# ---------------------------------------------------------------------------


def _allowed_host(url: str) -> bool:
    return urlparse(url).netloc.lower().endswith(ALLOWED_HOST_SUFFIX)


def _fetch(client: httpx.Client, url: str) -> str:
    if not _allowed_host(url):
        return ""
    try:
        resp = client.get(url, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as exc:
        logger.warning("fetch failed url=%s err=%s", url, exc)
        return ""
    if resp.status_code != 200:
        logger.warning("HTTP %d url=%s", resp.status_code, url)
        return ""
    return resp.text


def _parse_budget_passings(body: str, window_start: date) -> list[dict[str, str]]:
    """Extract budget-bill passing dates from a chamber 議案 page (HTML)."""
    out: list[dict[str, str]] = []
    # Naive table-row split — 衆議院/参議院 議案ページは行単位.
    for line in body.splitlines():
        if "予算" not in line or "可決" not in line and "成立" not in line:
            continue
        date_m = DATE_RE.search(line)
        if not date_m:
            continue
        try:
            d = date(
                int(date_m.group(1)),
                int(date_m.group(2)),
                int(date_m.group(3)),
            )
        except ValueError:
            continue
        if d < window_start:
            continue
        kid_m = KOKKAI_ID_RE.search(line)
        kokkai_id = (
            f"{kid_m.group(1)}-{kid_m.group(2)}" if kid_m else f"{d.isoformat()}-?"
        )
        kind = "supplementary_budget" if "補正" in line else "main_budget"
        out.append({
            "kokkai_id": kokkai_id,
            "passing_date": d.isoformat(),
            "kind": kind,
            "title": line.strip()[:300],
        })
    return out


def _parse_ministry_rss(body: str) -> list[dict[str, str]]:
    """RSS item parsing (reused from poll_enforcement_daily)."""
    item_re = re.compile(r"<item[^>]*>(.*?)</item>", re.DOTALL | re.IGNORECASE)
    title_re = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
    link_re = re.compile(r"<link[^>]*>(.*?)</link>", re.DOTALL | re.IGNORECASE)
    date_re = re.compile(r"<pubDate[^>]*>(.*?)</pubDate>", re.DOTALL | re.IGNORECASE)
    cdata_re = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)

    def strip_cdata(s: str) -> str:
        m = cdata_re.search(s)
        return (m.group(1) if m else s).strip()

    out: list[dict[str, str]] = []
    for block in item_re.findall(body):
        tm, lm, dm = title_re.search(block), link_re.search(block), date_re.search(block)
        title = strip_cdata(tm.group(1)) if tm else ""
        link = strip_cdata(lm.group(1)) if lm else ""
        pub_raw = strip_cdata(dm.group(1)) if dm else ""
        m = DATE_RE.search(pub_raw)
        if m:
            pub = f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
        else:
            try:
                pub = datetime.strptime(pub_raw[:25], "%a, %d %b %Y %H:%M:%S").date().isoformat()
            except ValueError:
                pub = ""
        out.append({"title": title, "link": link, "pub_date": pub})
    return out


def _is_subsidy_announce(title: str) -> bool:
    return any(k in title for k in SUBSIDY_KEYWORDS)


def _resolve_program_id(conn: sqlite3.Connection, title: str, link: str) -> str:
    """Best-effort lookup of am_entities.canonical_id for a subsidy program.

    Falls back to a deterministic hash-based id when no row matches, so
    chain rows are still recorded with a stable surrogate.
    """
    try:
        row = conn.execute(
            """
            SELECT canonical_id
            FROM am_entities
            WHERE record_kind = 'program'
              AND (source_url = ? OR canonical_name LIKE ?)
            LIMIT 1
            """,
            (link, f"%{title[:80]}%"),
        ).fetchone()
        if row:
            return str(row["canonical_id"])
    except sqlite3.OperationalError:
        pass
    fp = hashlib.sha256(f"{title}|{link}".encode()).hexdigest()[:16]
    return f"subsidy:unmatched:{fp}"


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


def _upsert_chain(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    sha = hashlib.sha256(
        f"{row['budget_kokkai_id']}|{row['subsidy_program_id']}|{row['announce_date']}".encode()
    ).hexdigest()
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO am_budget_subsidy_chain(
            budget_kokkai_id, budget_passing_date, budget_kind,
            subsidy_program_id, announce_date, lag_days,
            evidence_url, sha256
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["budget_kokkai_id"],
            row["budget_passing_date"],
            row["budget_kind"],
            row["subsidy_program_id"],
            row["announce_date"],
            row["lag_days"],
            row["evidence_url"],
            sha,
        ),
    )
    inserted = int(cur.rowcount or 0)
    if inserted and not row["subsidy_program_id"].startswith("subsidy:unmatched:"):
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(
                """
                UPDATE programs
                SET triggered_by_budget_id = ?
                WHERE canonical_id = ? AND (triggered_by_budget_id IS NULL OR triggered_by_budget_id = '')
                """,
                (row["budget_kokkai_id"], row["subsidy_program_id"]),
            )
    return inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(db_path: Path, lag_days: int, window_days: int, dry_run: bool) -> dict[str, int]:
    counters = {
        "budgets": 0,
        "subsidies": 0,
        "chains_inserted": 0,
        "skipped": 0,
    }
    conn: sqlite3.Connection | None = None
    if not dry_run:
        conn = _open(str(db_path))
        _ensure_program_column(conn)
    window_start = (datetime.now(UTC) - timedelta(days=window_days)).date()
    with httpx.Client(timeout=HTTPX_TIMEOUT) as client:
        budgets: list[dict[str, str]] = []
        for u in (SHUGIIN_GIAN_URL, SANGIIN_GIAN_URL):
            body = _fetch(client, u)
            time.sleep(RATE_LIMIT_SECONDS)
            budgets.extend(_parse_budget_passings(body, window_start))
        counters["budgets"] = len(budgets)
        if not budgets:
            logger.warning("no budget passings parsed in window=%dd", window_days)
            return counters

        announces: list[tuple[str, dict[str, str]]] = []
        for label, url in MINISTRY_FEEDS:
            body = _fetch(client, url)
            time.sleep(RATE_LIMIT_SECONDS)
            for item in _parse_ministry_rss(body):
                if _is_subsidy_announce(item.get("title") or ""):
                    announces.append((label, item))
        counters["subsidies"] = len(announces)
        for budget in budgets:
            try:
                bpd = date.fromisoformat(budget["passing_date"])
            except ValueError:
                continue
            for _label, ann in announces:
                pub = ann.get("pub_date") or ""
                try:
                    apd = date.fromisoformat(pub)
                except ValueError:
                    continue
                lag = (apd - bpd).days
                if lag < 0 or lag > lag_days:
                    counters["skipped"] += 1
                    continue
                if conn is None:
                    counters["chains_inserted"] += 1
                    continue
                program_id = _resolve_program_id(
                    conn,
                    ann.get("title", ""),
                    ann.get("link", ""),
                )
                row = {
                    "budget_kokkai_id": budget["kokkai_id"],
                    "budget_passing_date": budget["passing_date"],
                    "budget_kind": budget["kind"],
                    "subsidy_program_id": program_id,
                    "announce_date": pub,
                    "lag_days": lag,
                    "evidence_url": ann.get("link", ""),
                }
                counters["chains_inserted"] += _upsert_chain(conn, row)
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
        counters = run(
            db_path=Path(args.db),
            lag_days=args.lag_days,
            window_days=args.window_days,
            dry_run=args.dry_run,
        )
    except FileNotFoundError as exc:
        logger.error("db_missing err=%s", exc)
        return 1
    except (httpx.HTTPError, sqlite3.DatabaseError) as exc:
        logger.error("fatal err=%s", exc)
        return 1
    logger.info("budget_subsidy_chain_done %s", json.dumps(counters))
    return 0


if __name__ == "__main__":
    sys.exit(main())
