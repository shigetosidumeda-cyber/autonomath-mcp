#!/usr/bin/env python3
"""DEEP-41 brand mention dashboard cron - scrape 10 signals weekly.

Spec
----
tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_41_brand_mention_dashboard.md

Pulls jpcite / autonomath brand mentions from 10 organic signal sources,
dedups via INSERT OR IGNORE on (source, mention_url) UNIQUE, classifies
mention_kind = self / other against data/brand_self_accounts.json
allowlist, and persists rows to autonomath.db.brand_mention.

Sources (10):
    1.  github             REST search /search/issues?q=jpcite+in:body
    2.  pypi               pypistats.org/api/packages/{pkg}/recent
    3.  npm                api.npmjs.org/downloads/range/last-month/{pkg}
    4.  zenn               zenn.dev/api/articles?q=jpcite
    5.  qiita              qiita.com/api/v2/items?query=jpcite
    6.  x                  twitter.com/search?q=jpcite&f=live (HTML, no key)
    7.  hn                 hn.algolia.com/api/v1/search?query=jpcite
    8.  lobsters           lobste.rs/search.rss?q=jpcite (RSS)
    9.  industry_journal   DEEP-40 industry_journal_mention table SELECT
    10. industry_assoc     manual semi-annual sample (no-op in weekly run)

Constraints (NON-NEGOTIABLE):
    * NO LLM calls (no anthropic / openai / google.generativeai / claude_agent_sdk)
    * NO paid intel SaaS (Crayon / Klue / Brandwatch named-NG)
    * NO trademark filings (rename-only on conflicts)
    * httpx + asyncio + stdlib + (optional) feedparser / xml.etree only
    * GITHUB_TOKEN secret optional (lifts unauth 60 req/h ceiling)
    * Failure-tolerant: 1 source down does NOT abort the other 9.
        Each source's success / fail / row-count gets logged to
        analytics/brand_signals_run.jsonl.

Cadence:
    Mondays 06:00 JST = Mondays 21:00 UTC (.github/workflows/brand-signals-weekly.yml).
    workflow_dispatch supported for ad-hoc backfills.

Run:
    python scripts/cron/scrape_brand_signals.py
    python scripts/cron/scrape_brand_signals.py --dry-run   # log only, no DB write
    python scripts/cron/scrape_brand_signals.py --source github,zenn  # subset
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = os.environ.get("AUTONOMATH_DB_PATH", str(REPO_ROOT / "autonomath.db"))
DEFAULT_ALLOWLIST_PATH = REPO_ROOT / "data" / "brand_self_accounts.json"
DEFAULT_RUN_LOG_PATH = REPO_ROOT / "analytics" / "brand_signals_run.jsonl"

ALL_SOURCES: tuple[str, ...] = (
    "github",
    "pypi",
    "npm",
    "zenn",
    "qiita",
    "x",
    "hn",
    "lobsters",
    "industry_journal",
    "industry_assoc",
)

BRAND_REGEX = re.compile(r"jpcite|autonomath", re.IGNORECASE)
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "jpcite-brand-signals/1.0 (+https://jpcite.com/transparency/brand-health)"

logger = logging.getLogger("scrape_brand_signals")


# ---------------------------------------------------------------------------
# Allowlist / classification
# ---------------------------------------------------------------------------


def load_allowlist(path: Path = DEFAULT_ALLOWLIST_PATH) -> dict[str, set[str]]:
    """Return per-source set of self-account handles (lowercased)."""
    if not path.exists():
        logger.warning("allowlist missing at %s; defaulting to empty", path)
        return {src: set() for src in ALL_SOURCES}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for src in ALL_SOURCES:
        out[src] = {str(x).lower() for x in raw.get(src, [])}
    # Email domains apply to industry_journal / industry_assoc.
    domains = {str(x).lower() for x in raw.get("email_domains", [])}
    for src in ("industry_journal", "industry_assoc"):
        out[src] |= domains
    return out


def classify_kind(source: str, author: str | None, allowlist: dict[str, set[str]]) -> str:
    """Return 'self' if author matches allowlist for source, else 'other'.

    Email-style authors check the domain too (industry_journal / assoc).
    """
    if not author:
        return "other"
    needle = author.lower()
    bucket = allowlist.get(source, set())
    if needle in bucket:
        return "self"
    # Accept partial match on email domain (e.g. "info@bookyou.net" → bookyou.net).
    if "@" in needle:
        domain = needle.split("@", 1)[-1]
        if domain in bucket:
            return "self"
    # Accept partial match on free-text publisher containing org name.
    for entry in bucket:
        if entry and entry in needle:
            return "self"
    return "other"


# ---------------------------------------------------------------------------
# Source fetchers (each returns list[dict]: source/mention_url/author/mention_date/snippet)
# ---------------------------------------------------------------------------


async def fetch_github(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    headers: dict[str, str] = {}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    headers["Accept"] = "application/vnd.github+json"
    rows: list[dict[str, Any]] = []
    for q in ("jpcite+in:body", "autonomath+in:body"):
        url = f"https://api.github.com/search/issues?q={q}&per_page=50"
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        for item in r.json().get("items", [])[:50]:
            body = (item.get("body") or "")[:240]
            if not BRAND_REGEX.search(body) and not BRAND_REGEX.search(item.get("title", "")):
                continue
            rows.append(
                {
                    "source": "github",
                    "mention_url": item["html_url"],
                    "author": (item.get("user") or {}).get("login"),
                    "mention_date": (item.get("created_at") or "")[:10],
                    "snippet": (item.get("title") or "")[:240],
                }
            )
    return rows


async def fetch_pypi(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pkg in ("autonomath-mcp", "jpcite-disclaimer-spec"):
        url = f"https://pypistats.org/api/packages/{pkg}/recent"
        try:
            r = await client.get(url)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            data = r.json().get("data", {})
        except httpx.HTTPError:
            continue
        rows.append(
            {
                "source": "pypi",
                "mention_url": f"https://pypi.org/project/{pkg}/",
                "author": "bookyou",
                "mention_date": datetime.now(UTC).strftime("%Y-%m-%d"),
                "snippet": f"pypi downloads recent={data}",
            }
        )
    return rows


async def fetch_npm(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pkg in ("@jpcite/disclaimer-spec",):
        url = f"https://api.npmjs.org/downloads/range/last-month/{pkg}"
        try:
            r = await client.get(url)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError:
            continue
        total = sum(d.get("downloads", 0) for d in data.get("downloads", []))
        rows.append(
            {
                "source": "npm",
                "mention_url": f"https://www.npmjs.com/package/{pkg}",
                "author": "@jpcite",
                "mention_date": datetime.now(UTC).strftime("%Y-%m-%d"),
                "snippet": f"npm downloads last_month={total}",
            }
        )
    return rows


async def fetch_zenn(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for q in ("jpcite", "autonomath"):
        url = f"https://zenn.dev/api/articles?q={q}&order=latest"
        try:
            r = await client.get(url)
            r.raise_for_status()
            for art in r.json().get("articles", [])[:50]:
                slug = art.get("slug", "")
                user = (art.get("user") or {}).get("username", "")
                rows.append(
                    {
                        "source": "zenn",
                        "mention_url": f"https://zenn.dev/{user}/articles/{slug}",
                        "author": user,
                        "mention_date": (art.get("published_at") or "")[:10],
                        "snippet": (art.get("title") or "")[:240],
                    }
                )
        except httpx.HTTPError:
            continue
    return rows


async def fetch_qiita(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for q in ("jpcite", "autonomath"):
        url = f"https://qiita.com/api/v2/items?query={q}&per_page=50"
        try:
            r = await client.get(url)
            r.raise_for_status()
            for item in r.json()[:50]:
                rows.append(
                    {
                        "source": "qiita",
                        "mention_url": item.get("url"),
                        "author": (item.get("user") or {}).get("id"),
                        "mention_date": (item.get("created_at") or "")[:10],
                        "snippet": (item.get("title") or "")[:240],
                    }
                )
        except httpx.HTTPError:
            continue
    return rows


async def fetch_x(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """X (Twitter) public search HTML scrape - no API key, organic visibility only.

    NOTE: X aggressively rate-limits unauthenticated HTML scraping. We treat a
    failure as soft-fail (logged in run jsonl, count = 0 for the week).
    """
    rows: list[dict[str, Any]] = []
    url = "https://twitter.com/search?q=jpcite&f=live"
    try:
        r = await client.get(url, headers={"User-Agent": USER_AGENT})
        if r.status_code != 200:
            return rows
        # Public HTML now requires JS render in most cases; we keep the path
        # so the source is exercised but expect 0 rows in 99% of weeks.
        for handle, status_id in re.findall(r"/([A-Za-z0-9_]{1,15})/status/(\d+)", r.text)[:20]:
            rows.append(
                {
                    "source": "x",
                    "mention_url": f"https://twitter.com/{handle}/status/{status_id}",
                    "author": handle,
                    "mention_date": datetime.now(UTC).strftime("%Y-%m-%d"),
                    "snippet": f"x post {status_id}",
                }
            )
    except httpx.HTTPError:
        pass
    return rows


async def fetch_hn(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for q in ("jpcite", "autonomath"):
        url = f"https://hn.algolia.com/api/v1/search?query={q}&tags=story"
        try:
            r = await client.get(url)
            r.raise_for_status()
            for hit in r.json().get("hits", [])[:50]:
                obj_id = hit.get("objectID")
                rows.append(
                    {
                        "source": "hn",
                        "mention_url": f"https://news.ycombinator.com/item?id={obj_id}",
                        "author": hit.get("author"),
                        "mention_date": (hit.get("created_at") or "")[:10],
                        "snippet": (hit.get("title") or hit.get("story_text") or "")[:240],
                    }
                )
        except httpx.HTTPError:
            continue
    return rows


async def fetch_lobsters(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for q in ("jpcite", "autonomath"):
        url = f"https://lobste.rs/search.rss?q={q}"
        try:
            r = await client.get(url)
            r.raise_for_status()
            try:
                root = ET.fromstring(r.text)
            except ET.ParseError:
                continue
            for item in root.iter("item"):
                link_el = item.find("link")
                title_el = item.find("title")
                pub_el = item.find("pubDate")
                author_el = item.find("{http://purl.org/dc/elements/1.1/}creator")
                if link_el is None or not (link_el.text or "").strip():
                    continue
                rows.append(
                    {
                        "source": "lobsters",
                        "mention_url": (link_el.text or "").strip(),
                        "author": (author_el.text if author_el is not None else None),
                        "mention_date": _rss_date_to_iso(
                            pub_el.text if pub_el is not None else None
                        ),
                        "snippet": ((title_el.text or "") if title_el is not None else "")[:240],
                    }
                )
        except httpx.HTTPError:
            continue
    return rows


async def fetch_industry_journal(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Read DEEP-40 industry_journal_mention rows (cron-internal SQL handoff).

    DEEP-40 is a peer cron; we treat its table as a handoff substrate. If the
    table is not yet present (DEEP-40 not landed), we soft-skip with 0 rows.
    """
    rows: list[dict[str, Any]] = []
    db_path = os.environ.get("AUTONOMATH_DB_PATH", DEFAULT_DB_PATH)
    if not Path(db_path).exists():
        return rows
    try:
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='industry_journal_mention'"
            )
            if cur.fetchone() is None:
                return rows
            cur = conn.execute(
                "SELECT mention_url, journal_name, mention_date, headline "
                "FROM industry_journal_mention LIMIT 200"
            )
            for url, journal, date, headline in cur.fetchall():
                rows.append(
                    {
                        "source": "industry_journal",
                        "mention_url": url,
                        "author": journal,
                        "mention_date": date or datetime.now(UTC).strftime("%Y-%m-%d"),
                        "snippet": (headline or "")[:240],
                    }
                )
        finally:
            conn.close()
    except sqlite3.Error:
        pass
    return rows


async def fetch_industry_assoc(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Semi-annual manual sample - weekly cron is a no-op. See spec §1 row 10."""
    return []


SOURCE_FETCHERS = {
    "github": fetch_github,
    "pypi": fetch_pypi,
    "npm": fetch_npm,
    "zenn": fetch_zenn,
    "qiita": fetch_qiita,
    "x": fetch_x,
    "hn": fetch_hn,
    "lobsters": fetch_lobsters,
    "industry_journal": fetch_industry_journal,
    "industry_assoc": fetch_industry_assoc,
}


def _rss_date_to_iso(s: str | None) -> str:
    if not s:
        return datetime.now(UTC).strftime("%Y-%m-%d")
    # RFC 822 'Mon, 05 May 2026 12:00:00 +0000'
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(UTC).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def insert_rows(
    db_path: str, rows: list[dict[str, Any]], allowlist: dict[str, set[str]]
) -> dict[str, int]:
    """Bulk-insert rows with INSERT OR IGNORE; classify kind. Return per-source counts."""
    counts: dict[str, int] = dict.fromkeys(ALL_SOURCES, 0)
    if not rows:
        return counts
    conn = sqlite3.connect(db_path)
    try:
        for row in rows:
            src = row.get("source", "")
            url = row.get("mention_url")
            if not url or src not in ALL_SOURCES:
                continue
            kind = classify_kind(src, row.get("author"), allowlist)
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO brand_mention
                        (source, mention_url, author, mention_date,
                         mention_kind, snippet)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        src,
                        url,
                        row.get("author"),
                        row.get("mention_date") or datetime.now(UTC).strftime("%Y-%m-%d"),
                        kind,
                        (row.get("snippet") or "")[:1024],
                    ),
                )
                if conn.total_changes:
                    counts[src] += 1
            except sqlite3.Error as exc:
                logger.warning("insert failed for %s/%s: %s", src, url, exc)
        conn.commit()
    finally:
        conn.close()
    return counts


def append_run_log(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def run_async(sources: list[str], dry_run: bool, db_path: str) -> dict[str, Any]:
    allowlist = load_allowlist()
    started = datetime.now(UTC).isoformat()
    per_source: dict[str, dict[str, Any]] = {}
    all_rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:
        tasks = [SOURCE_FETCHERS[s](client) for s in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    for src, res in zip(sources, results, strict=True):
        if isinstance(res, Exception):
            per_source[src] = {"ok": False, "error": str(res)[:240], "rows": 0}
            logger.warning("source %s failed: %s", src, res)
            continue
        per_source[src] = {"ok": True, "rows": len(res)}
        all_rows.extend(res)
    inserted = dict.fromkeys(sources, 0) if dry_run else insert_rows(db_path, all_rows, allowlist)
    summary = {
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "sources_run": sources,
        "fetched_rows_total": len(all_rows),
        "inserted_rows_per_source": inserted,
        "per_source": per_source,
        "dry_run": dry_run,
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Fetch but skip DB writes.")
    parser.add_argument(
        "--source",
        type=str,
        default=",".join(ALL_SOURCES),
        help=f"Comma-separated subset of {ALL_SOURCES}",
    )
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH)
    parser.add_argument("--log-level", type=str, default="INFO")
    args = parser.parse_args()
    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s"
    )
    requested = [s.strip() for s in args.source.split(",") if s.strip()]
    sources = [s for s in requested if s in ALL_SOURCES]
    if not sources:
        logger.error("no valid sources in %r", args.source)
        return 2
    summary = asyncio.run(run_async(sources, args.dry_run, args.db))
    append_run_log(DEFAULT_RUN_LOG_PATH, summary)
    logger.info("done: %s", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
