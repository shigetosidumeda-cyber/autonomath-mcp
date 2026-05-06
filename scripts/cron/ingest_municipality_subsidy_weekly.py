#!/usr/bin/env python3
"""Weekly 自治体 補助金 page diff ingest cron (DEEP-44 implementation).

Walks the seed URL list at ``data/municipality_seed_urls.json`` (1st pass:
67 自治体 = 47 都道府県 + 20 政令市), fetches each page, parses HTML
(BeautifulSoup) or PDF (pdfplumber, lazy import), computes sha256 for
diff detection, and writes rows to ``municipality_subsidy`` in jpintel.db.

Spec
----

Source: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_44_municipality_subsidy_weekly_diff.md

Constraints
-----------

* LLM calls = 0. Pure regex + sqlite3 + httpx + bs4 + pdfplumber. No
  anthropic / openai / claude_agent_sdk imports — see
  tests/test_no_llm_in_production.py.
* Concurrency: ``asyncio.Semaphore(50)`` for global concurrent fetches +
  per-host token bucket of 1 req / 2 sec (自治体サーバ負荷配慮).
* Aggregator banlist (CLAUDE.md データ衛生規約): URL netloc whose
  substring matches noukaweb / hojyokin-portal / biz.stayway / stayway.jp /
  subsidies-japan / jgrant-aggregator / nikkei.com / prtimes.jp /
  wikipedia.org is rejected before fetch (1次資料 only).
* 自治体 = 1 次資料 (政府著作物 §13 著作権法). city.*.lg.jp / pref.*.lg.jp /
  metro.tokyo.lg.jp は OK。aggregator は NG。
* Idempotent: ``UNIQUE(muni_code, subsidy_url)`` + ``INSERT OR REPLACE``
  on diff (sha256 不一致) で 上書き. 同一 sha256 の re-run は 0 row insert.
* Failure path: stderr + sys.exit(1) so the GHA workflow's on-fail
  issue auto-create fires.

Usage
-----
    python scripts/cron/ingest_municipality_subsidy_weekly.py
    python scripts/cron/ingest_municipality_subsidy_weekly.py --db data/jpintel.db
    python scripts/cron/ingest_municipality_subsidy_weekly.py --dry-run
    python scripts/cron/ingest_municipality_subsidy_weekly.py --seed data/municipality_seed_urls.json

Exit codes
----------
0  success (≥0 rows inserted/updated)
1  fatal (db missing, seed file missing, network down past retry budget)
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("jpintel.cron.municipality_subsidy_weekly")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GLOBAL_CONCURRENCY = 50
PER_HOST_INTERVAL_SECONDS = 2.0
HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = (
    "jpcite-municipality-cron/0.3.4 (+https://jpcite.com/cron-policy)"
)

# Aggregator banlist — mirrors api/contribute.py + api/_verifier.py +
# api/citation_badge.py. Substring match against urlparse(url).netloc.
# 1次資料 (政府著作物) only — aggregators are forbidden in source_url.
AGGREGATOR_BANLIST: tuple[str, ...] = (
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "stayway.jp",
    "subsidies-japan",
    "jgrant-aggregator",
    "nikkei.com",
    "prtimes.jp",
    "wikipedia.org",
)

# Allowed netloc suffixes for 自治体 1 次資料 (DEEP-28 §2 + DEEP-44 §6).
# 自治体 公式 domain patterns:
#   * .lg.jp (現行 標準) — city.shinjuku.lg.jp 等
#   * .go.jp (中央省庁 — chusho.meti.go.jp 等)
#   * pref.*.jp / city.*.jp / town.*.jp / village.*.jp (legacy 自治体 域)
#   * metro.tokyo.* (東京都 旗艦)
ALLOWED_SUFFIXES: tuple[str, ...] = (
    ".lg.jp",
    ".go.jp",
    "metro.tokyo",
)
# Legacy 自治体 domain patterns (substring match against netloc).
ALLOWED_NETLOC_PATTERNS: tuple[str, ...] = (
    "pref.",
    "city.",
    "town.",
    "village.",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = _REPO_ROOT / "data" / "jpintel.db"
DEFAULT_SEED_PATH = _REPO_ROOT / "data" / "municipality_seed_urls.json"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--db",
        default=os.environ.get("JPINTEL_DB_PATH", str(DEFAULT_DB_PATH)),
        help="jpintel.db path (default: %(default)s).",
    )
    p.add_argument(
        "--seed",
        default=str(DEFAULT_SEED_PATH),
        help="Seed URL JSON path (default: %(default)s).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + parse only; do not insert.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging.",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Aggregator guard
# ---------------------------------------------------------------------------


def is_aggregator_url(url: str) -> bool:
    """Return True if ``url`` netloc matches any banned aggregator substring.

    1次資料 only — aggregator (noukaweb / hojyokin-portal / biz.stayway 等)
    is rejected before fetch (CLAUDE.md データ衛生規約).
    """
    try:
        netloc = urlparse(url).netloc.lower()
    except (ValueError, AttributeError):
        return True  # malformed = treat as banned (defensive)
    if not netloc:
        return True
    for banned in AGGREGATOR_BANLIST:
        if banned in netloc:
            return True
    return False


def is_allowed_municipality_url(url: str) -> bool:
    """Return True if URL netloc ends with an allowlisted suffix.

    自治体 1 次資料 ⊂ {*.lg.jp, *.go.jp, metro.tokyo.jp 系}. Other
    domains (.com / .net / .info etc.) are rejected even if they happen
    to escape the aggregator banlist.
    """
    if is_aggregator_url(url):
        return False
    try:
        netloc = urlparse(url).netloc.lower()
    except (ValueError, AttributeError):
        return False
    if not netloc:
        return False
    # Suffix match (.lg.jp / .go.jp / metro.tokyo).
    for suffix in ALLOWED_SUFFIXES:
        if netloc.endswith(suffix) or suffix in netloc:
            return True
    # Legacy 自治体 prefix patterns (pref.<name>.jp / city.<name>.jp etc.)
    # — only when netloc still ends in a Japan-domain TLD.
    if netloc.endswith(".jp"):
        for prefix in ALLOWED_NETLOC_PATTERNS:
            if prefix in netloc:
                return True
    return False


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _open_db(path: str) -> sqlite3.Connection:
    """Open jpintel.db for read+write (cron is the writer)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"jpintel.db missing: {p}")
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _existing_sha256(
    conn: sqlite3.Connection, muni_code: str, subsidy_url: str
) -> str | None:
    """Return the prior sha256 for this (muni_code, subsidy_url) row, if any."""
    try:
        row = conn.execute(
            "SELECT sha256 FROM municipality_subsidy "
            "WHERE muni_code = ? AND subsidy_url = ?",
            (muni_code, subsidy_url),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return row["sha256"] if row else None


def _upsert_subsidy(
    conn: sqlite3.Connection,
    row: dict[str, Any],
) -> str:
    """Upsert a municipality_subsidy row.

    Returns one of: 'inserted' (new row), 'updated' (sha256 differed),
    'skipped' (sha256 matched the prior row — no diff this week).
    """
    prior = _existing_sha256(conn, row["muni_code"], row["subsidy_url"])
    if prior == row["sha256"]:
        # Update retrieved_at + page_status only — sha256 unchanged means
        # no content diff. Keeps liveness signal honest without polluting
        # diff history with no-op rows.
        conn.execute(
            "UPDATE municipality_subsidy "
            "   SET retrieved_at = ?, page_status = ? "
            " WHERE muni_code = ? AND subsidy_url = ?",
            (
                row["retrieved_at"],
                row["page_status"],
                row["muni_code"],
                row["subsidy_url"],
            ),
        )
        return "skipped"
    # INSERT OR REPLACE to honor UNIQUE(muni_code, subsidy_url) on the
    # 1st-pass schema. A subsequent migration will switch the unique
    # constraint to a 3-tuple including sha256 to retain history (per
    # DEEP-44 §4 note); for now upsert overwrites the prior row.
    conn.execute(
        """
        INSERT OR REPLACE INTO municipality_subsidy
            (pref, muni_code, muni_name, muni_type, subsidy_url,
             subsidy_name, eligibility_text, amount_text, deadline_text,
             retrieved_at, sha256, page_status)
        VALUES (:pref, :muni_code, :muni_name, :muni_type, :subsidy_url,
                :subsidy_name, :eligibility_text, :amount_text, :deadline_text,
                :retrieved_at, :sha256, :page_status)
        """,
        row,
    )
    return "inserted" if prior is None else "updated"


# ---------------------------------------------------------------------------
# Per-host rate limiting
# ---------------------------------------------------------------------------


class HostRateLimiter:
    """Per-host token bucket: 1 request / PER_HOST_INTERVAL_SECONDS.

    自治体サーバ負荷配慮 — even at 50 global concurrency we never hit the
    same host more than once per 2 seconds.
    """

    def __init__(self, interval_seconds: float = PER_HOST_INTERVAL_SECONDS) -> None:
        self.interval = interval_seconds
        self._last_hit: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def _lock_for(self, host: str) -> asyncio.Lock:
        async with self._global_lock:
            if host not in self._locks:
                self._locks[host] = asyncio.Lock()
            return self._locks[host]

    async def acquire(self, host: str) -> None:
        lock = await self._lock_for(host)
        async with lock:
            now = time.monotonic()
            prior = self._last_hit.get(host, 0.0)
            wait = self.interval - (now - prior)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_hit[host] = time.monotonic()


# ---------------------------------------------------------------------------
# HTML / PDF parsing
# ---------------------------------------------------------------------------

# Heuristic regexes (LLM-0).
_AMOUNT_RE = re.compile(
    r"(?:補助(?:額|金額|限度額)|上限|交付限度額)[\s:：]*([0-9,０-９億万円〜～\-]+)"
)
_DEADLINE_RE = re.compile(
    r"(?:申請(?:期限|期間)|締切|締め切り|応募期限)[\s:：]*"
    r"([0-9０-９令和平成]{1,4}[年./\-][0-9０-９]{1,2}[月./\-][0-9０-９]{1,2}[日]?)"
)
_TARGET_RE = re.compile(
    r"(?:対象(?:者|事業者|企業)?|応募資格)[\s:：]*([^\n。]{1,200})"
)


def parse_html(html: str) -> dict[str, str | None]:
    """Extract subsidy_name + eligibility_text + amount_text + deadline_text.

    Pure regex + bs4. Failures fall back to raw text in eligibility_text
    so the listing remains useful even without structured fields.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    # subsidy_name = <h1> first non-empty text, else <title>.
    name: str | None = None
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        name = h1.get_text(strip=True)[:200]
    else:
        title = soup.find("title")
        if title and title.get_text(strip=True):
            name = title.get_text(strip=True)[:200]

    text = soup.get_text("\n", strip=True)
    return _parse_text_fields(text, subsidy_name=name)


def parse_pdf_bytes(pdf_bytes: bytes) -> dict[str, str | None]:
    """Parse PDF bytes via pdfplumber (lazy import). LLM-0."""
    import io

    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_text: list[str] = []
            for page in pdf.pages[:30]:  # cap to first 30 pages for transport
                page_text = page.extract_text() or ""
                pages_text.append(page_text)
        text = "\n".join(pages_text)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("pdfplumber parse failed: %s", exc)
        text = ""
    name = None
    for line in text.split("\n"):
        cleaned = line.strip()
        if cleaned:
            name = cleaned[:200]
            break
    return _parse_text_fields(text, subsidy_name=name)


def _parse_text_fields(text: str, subsidy_name: str | None) -> dict[str, str | None]:
    amount_m = _AMOUNT_RE.search(text)
    deadline_m = _DEADLINE_RE.search(text)
    target_m = _TARGET_RE.search(text)
    return {
        "subsidy_name": subsidy_name,
        "eligibility_text": (target_m.group(1).strip() if target_m else text[:4000]) or None,
        "amount_text": amount_m.group(1).strip() if amount_m else None,
        "deadline_text": deadline_m.group(1).strip() if deadline_m else None,
    }


def compute_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Fetch + ingest one seed
# ---------------------------------------------------------------------------


async def fetch_and_ingest(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    rate: HostRateLimiter,
    conn: sqlite3.Connection,
    seed: dict[str, Any],
    dry_run: bool,
) -> tuple[str, dict[str, Any]]:
    """Fetch one seed URL, parse, upsert. Returns (status, row_dict).

    status: 'inserted' | 'updated' | 'skipped' | 'banned' | 'http_error'
    """
    url = seed["subsidy_url"]
    if is_aggregator_url(url) or not is_allowed_municipality_url(url):
        logger.warning("aggregator/non-1次資料 url rejected: %s", url)
        return "banned", {}

    host = urlparse(url).netloc.lower()
    async with sem:
        await rate.acquire(host)
        try:
            resp = await client.get(url, follow_redirects=True)
        except httpx.HTTPError as exc:
            logger.warning("fetch failed %s: %s", url, exc)
            return "http_error", {}

    if resp.status_code in (404, 410):
        page_status = "404"
        body_bytes = b""
        parsed: dict[str, str | None] = {
            "subsidy_name": None,
            "eligibility_text": None,
            "amount_text": None,
            "deadline_text": None,
        }
    elif resp.status_code >= 400:
        logger.warning("HTTP %s %s", resp.status_code, url)
        return "http_error", {}
    else:
        page_status = (
            "redirect" if str(resp.url) != url else "active"
        )
        body_bytes = resp.content
        ctype = (resp.headers.get("content-type") or "").lower()
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            parsed = parse_pdf_bytes(body_bytes)
        else:
            parsed = parse_html(resp.text)

    sha = compute_sha256(body_bytes or url.encode("utf-8"))
    row: dict[str, Any] = {
        "pref": seed["pref"],
        "muni_code": seed["muni_code"],
        "muni_name": seed["muni_name"],
        "muni_type": seed["muni_type"],
        "subsidy_url": url,
        "subsidy_name": parsed["subsidy_name"],
        "eligibility_text": parsed["eligibility_text"],
        "amount_text": parsed["amount_text"],
        "deadline_text": parsed["deadline_text"],
        "retrieved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha256": sha,
        "page_status": page_status,
    }
    if dry_run:
        return "skipped", row
    status = _upsert_subsidy(conn, row)
    return status, row


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def load_seed(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"seed file missing: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"seed file must be a JSON array: {p}")
    return data


async def run(args: argparse.Namespace) -> int:
    seed = load_seed(args.seed)
    logger.info("DEEP-44 cron start: seed_rows=%d db=%s dry_run=%s",
                len(seed), args.db, args.dry_run)

    conn = _open_db(args.db)
    sem = asyncio.Semaphore(GLOBAL_CONCURRENCY)
    rate = HostRateLimiter()
    counters = {"inserted": 0, "updated": 0, "skipped": 0,
                "banned": 0, "http_error": 0}

    async with httpx.AsyncClient(
        timeout=HTTPX_TIMEOUT,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/pdf,application/xhtml+xml;q=0.9,*/*;q=0.8",
        },
    ) as client:
        tasks = [
            fetch_and_ingest(client, sem, rate, conn, s, args.dry_run)
            for s in seed
        ]
        for coro in asyncio.as_completed(tasks):
            status, _row = await coro
            counters[status] = counters.get(status, 0) + 1
            if not args.dry_run and status in ("inserted", "updated"):
                conn.commit()

    if not args.dry_run:
        conn.commit()
    conn.close()

    logger.info("DEEP-44 cron done: %s", counters)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        return asyncio.run(run(args))
    except FileNotFoundError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("DEEP-44 cron failed")
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
