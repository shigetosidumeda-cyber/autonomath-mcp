#!/usr/bin/env python3
"""Nightly source URL liveness refresh for jpintel-mcp registry.

Today (2026-04-23) ``source_fetched_at`` is a uniform sentinel across every
row in ``data/jpintel.db`` because no real refresh pipeline runs. A full
re-fetch (per-authority scrapers, content diffing, re-enrichment) is out of
scope for this ticket; what this script does is **truthfully** bump
``source_fetched_at`` only for rows whose ``source_url`` is still live:

1. HEAD-request every non-excluded ``source_url`` (fallback to partial GET
   when a server refuses HEAD).
2. Rate-limit per host and globally to stay a polite crawler.
3. Honour ``robots.txt`` before touching any host.
4. On 2xx — update ``source_fetched_at`` + ``source_last_check_status``.
5. On final-URL redirect to a different host — log to ``source_redirects``
   for manual review. We never auto-overwrite ``source_url``.
6. On HTTP failure, transport failure, or unsafe URL refusal — bump
   ``source_fail_count``; quarantine (``excluded=1``, ``tier='X'``) after
   the third persistent failure and note it in ``source_failures``.

The script is idempotent and safe to re-run. ``--dry-run`` performs no
writes; it still emits the report so CI can preview a change set.

See ``docs/data_integrity.md`` for the broader policy; this script is the
"liveness" half of that playbook (the "content freshness" half — diffing
the body — is intentionally not implemented here).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import ipaddress
import json
import os
import socket
import sqlite3
import sys
import time
import urllib.robotparser
from collections import Counter, OrderedDict, defaultdict
from typing import Any
from urllib.parse import urlparse

import httpx

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(REPO_ROOT, "data", "jpintel.db")
DEFAULT_REPORT = os.path.join(REPO_ROOT, "data", "refresh_sources_report.json")

USER_AGENT = "AutonoMath-LivenessBot/0.1 (+https://jpcite.com/bot)"
REQUEST_TIMEOUT = 15.0
MAX_REDIRECTS = 5
QUARANTINE_THRESHOLD = 3
FAILURE_OUTCOMES: frozenset[str] = frozenset({"fail", "error", "unsafe_url"})

# ---------------------------------------------------------------------------
# URL safety guard (R2 P2 hardening, 2026-05-13)
# ---------------------------------------------------------------------------
#
# ``programs.source_url`` is operator-curated, but a single bad ingest row
# pointing at ``file:///etc/passwd`` or ``http://169.254.169.254/latest/`` would
# let this cron exfiltrate cloud-instance metadata or read local files via
# ``httpx``. The scheme guard requires explicit ``https://`` (no
# ``http://``, no ``file://``, no ``ftp://``, no scheme-less hosts). The
# DNS-rebind guard resolves the host BEFORE we issue any HEAD/GET, and
# rejects it if any A/AAAA answer falls inside an RFC 1918 / 6890 /
# loopback / link-local / multicast / reserved range.
#
# A refused URL never reaches the network. It is still a source-liveness
# failure: the row cannot be safely checked, so it advances the same
# 3-strike ``source_fail_count`` path as transport/HTTP failures.

# Maps host -> (is_safe, reason, cached_at). TTL-bounded so a host that
# drift-rebinds to an internal IP after our first check does NOT stay
# "safe" forever — re-resolve after _DNS_RESOLVE_TTL_SEC. LRU-bounded at
# _DNS_RESOLVE_CACHE_MAX entries so a long-running scan over tens of
# thousands of unique hosts cannot grow the cache unbounded. Oldest
# entry is dropped on overflow via OrderedDict.move_to_end on access.
_DNS_RESOLVE_TTL_SEC: float = 300.0  # 5 minutes
_DNS_RESOLVE_CACHE_MAX: int = 10_000
_DNS_RESOLVE_CACHE: OrderedDict[str, tuple[bool, str | None, float]] = OrderedDict()


def _url_scheme_is_safe(url: str) -> bool:
    """Return True iff `url` parses to scheme == 'https'.

    Anything else (``http``, ``file``, ``ftp``, ``data``, ``javascript``,
    empty) is rejected up front. ``programs.source_url`` rows are required
    to point at HTTPS endpoints — non-HTTPS data sources risk on-path
    tampering and have no place in our liveness scan.
    """
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return False
    return parsed.scheme == "https" and bool(parsed.hostname)


def _is_private_or_reserved_ip(addr: str) -> bool:
    """Return True iff `addr` is inside any non-publicly-routable range.

    Covers loopback (127/8 + ::1), RFC1918 (10/8, 172.16/12, 192.168/16),
    link-local (169.254/16 + fe80::/10), unique-local (fc00::/7),
    multicast (224/4 + ff00::/8), reserved, and the canonical AWS IMDS
    address ``169.254.169.254``. ``ipaddress.IPv*Address`` already covers
    all of these via its ``is_*`` properties.
    """
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        # Unparseable as a numeric IP — treat as private for safety; the
        # caller will be the one to convert a hostname into IPs and pass
        # those in, so we should never see a non-IP literal here.
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _cache_store(host: str, verdict: tuple[bool, str | None]) -> tuple[bool, str | None]:
    """Insert ``verdict`` for ``host`` with the current timestamp.

    LRU bound: when the cache is at capacity, drop the oldest entry
    (``popitem(last=False)``) before the new insert. ``move_to_end`` keeps
    the most-recently-written entry at the tail so eviction always targets
    the staleest write.
    """
    now = time.time()
    if host in _DNS_RESOLVE_CACHE:
        _DNS_RESOLVE_CACHE.move_to_end(host)
    _DNS_RESOLVE_CACHE[host] = (verdict[0], verdict[1], now)
    while len(_DNS_RESOLVE_CACHE) > _DNS_RESOLVE_CACHE_MAX:
        _DNS_RESOLVE_CACHE.popitem(last=False)
    return verdict


def _resolve_host_safely(host: str) -> tuple[bool, str | None]:
    """Resolve `host` and return ``(is_safe, reason)``.

    ``is_safe`` is True iff EVERY A/AAAA answer is publicly routable.
    Any answer falling inside an RFC 1918 / 6890 range — including the
    AWS IMDS ``169.254.169.254`` — flips the verdict to False.

    Cached with a 5-minute TTL and a 10,000-entry LRU bound. Entries
    older than ``_DNS_RESOLVE_TTL_SEC`` are re-resolved on next access
    so a host that drift-rebinds to an internal IP after the first
    check does NOT stay "safe" forever. DNS failures (NXDOMAIN,
    timeout) are treated as unsafe — we err on the side of NOT fetching.
    """
    cached = _DNS_RESOLVE_CACHE.get(host)
    if cached is not None:
        is_safe, reason, cached_at = cached
        if time.time() - cached_at <= _DNS_RESOLVE_TTL_SEC:
            _DNS_RESOLVE_CACHE.move_to_end(host)
            return is_safe, reason
        # Stale — fall through to re-resolve and overwrite.
        del _DNS_RESOLVE_CACHE[host]

    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, OSError) as exc:
        return _cache_store(host, (False, f"dns:{type(exc).__name__}"))

    if not infos:
        return _cache_store(host, (False, "dns:no_answers"))

    for info in infos:
        sockaddr = info[4]
        addr = sockaddr[0]
        # IPv6 sockaddr may carry a zone suffix like 'fe80::1%eth0' — strip
        # it before passing to ipaddress.
        if "%" in addr:
            addr = addr.split("%", 1)[0]
        if _is_private_or_reserved_ip(addr):
            return _cache_store(host, (False, f"dns:private:{addr}"))

    return _cache_store(host, (True, None))


def is_url_safe(url: str) -> tuple[bool, str | None]:
    """Return ``(is_safe, reason)`` for `url`.

    The two-stage gate is:
      1. Scheme must be HTTPS (no http://, no file://, no scheme-less).
      2. The host must resolve, and every A/AAAA answer must be a
         publicly routable address. Any private / loopback / link-local /
         multicast / reserved / IMDS address fails the gate.

    Caller is expected to record a liveness failure on a False verdict, NOT
    to fall through to a HEAD/GET. The reason string is opaque to the
    caller; it shows up in the run report so an operator can fix the bad
    ``programs.source_url`` row directly.
    """
    if not _url_scheme_is_safe(url):
        return False, "scheme_not_https"
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False, "no_host"
    return _resolve_host_safely(host)


# Tier scope is now S,A,B,C by default — Tier X is the quarantine tier per
# CLAUDE.md and is intentionally excluded from every search path, this scan
# included. B = weekly cadence, C = monthly cadence, S/A = daily; the workflow
# matrix selects which tier subset runs on a given day.
DEFAULT_TIERS: tuple[str, ...] = ("S", "A", "B", "C")
EXCLUDED_TIERS: frozenset[str] = frozenset({"X"})

# Per-tier concurrency override. Tier C is high volume (~6.4k rows) so we
# halve the concurrency to keep the polite-crawler invariant comfortable
# even when many city/prefecture hosts cluster onto a single CDN.
TIER_CONCURRENCY_CAP: dict[str, int] = {
    "S": 10,
    "A": 10,
    "B": 8,
    "C": 5,
}

# Threshold for tier-C dead-URL alert. When more than this many tier-C rows
# come back failing in a single run, the cron creates a GitHub Issue (best
# effort — see workflow `.github/workflows/refresh-sources.yml`).
TIER_C_DEAD_ISSUE_THRESHOLD = 100

# Schema migrations — executed at startup, idempotent.
MIGRATIONS: tuple[str, ...] = (
    # Columns on programs.
    "ALTER TABLE programs ADD COLUMN source_last_check_status INTEGER",
    "ALTER TABLE programs ADD COLUMN source_fail_count INTEGER DEFAULT 0",
    # Tables.
    """
    CREATE TABLE IF NOT EXISTS source_redirects (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      unified_id TEXT NOT NULL,
      orig_url TEXT NOT NULL,
      final_url TEXT NOT NULL,
      detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_failures (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      unified_id TEXT NOT NULL,
      source_url TEXT NOT NULL,
      status_code INTEGER,
      checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      action TEXT
    )
    """,
)


# ---------------------------------------------------------------------------
# Schema / DB helpers
# ---------------------------------------------------------------------------


def apply_migrations(con: sqlite3.Connection) -> dict[str, bool]:
    """Apply the migration list; return a map of {migration: was_new}.

    ``ALTER TABLE ADD COLUMN`` throws ``OperationalError`` on duplicate column
    which we swallow. ``CREATE TABLE IF NOT EXISTS`` is already idempotent.
    """
    results: dict[str, bool] = {}
    for stmt in MIGRATIONS:
        key = stmt.strip().splitlines()[0].strip()
        try:
            con.execute(stmt)
            # A successful ALTER means the column was freshly added; a
            # successful CREATE TABLE IF NOT EXISTS may still be a no-op,
            # but we can't distinguish that here — treat as "ensured".
            results[key] = True
        except sqlite3.OperationalError as exc:
            msg = str(exc)
            if "duplicate column name" in msg or "already exists" in msg:
                results[key] = False
            else:
                raise
    con.commit()
    return results


def load_rows(
    con: sqlite3.Connection,
    tiers: list[str] | None,
    max_rows: int | None,
) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    clauses = ["excluded=0", "source_url IS NOT NULL", "TRIM(source_url) != ''"]
    params: list[Any] = []
    # Tier X is the quarantine tier (CLAUDE.md "common gotchas") — drop it
    # unconditionally even when the caller passes it explicitly. Search
    # paths exclude it; this scan should mirror that contract so we never
    # waste a HEAD request on a row the product would not surface anyway.
    safe_tiers: list[str] | None = None
    if tiers:
        safe_tiers = [t for t in tiers if t not in EXCLUDED_TIERS]
    if safe_tiers:
        placeholders = ",".join("?" for _ in safe_tiers)
        clauses.append(f"tier IN ({placeholders})")
        params.extend(safe_tiers)
    elif tiers and not safe_tiers:
        # Caller asked exclusively for Tier X — there is nothing to do.
        return []
    sql = (
        "SELECT unified_id, source_url, tier, "
        "COALESCE(source_fail_count, 0) AS source_fail_count "
        "FROM programs WHERE " + " AND ".join(clauses) + " ORDER BY unified_id"
    )
    if max_rows is not None and max_rows > 0:
        sql += f" LIMIT {int(max_rows)}"
    return list(con.execute(sql, params).fetchall())


# ---------------------------------------------------------------------------
# Robots.txt cache
# ---------------------------------------------------------------------------


class RobotsCache:
    """Fetch-once cache for robots.txt per host.

    ``can_fetch`` returns ``True`` when robots.txt is absent, malformed, or
    explicitly allows the path. We are strict only on explicit ``Disallow``
    matches against our UA or ``*``.
    """

    def __init__(self, client: httpx.AsyncClient, user_agent: str) -> None:
        self._client = client
        self._ua = user_agent
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = asyncio.Lock()

    async def can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host:
            return True
        scheme = parsed.scheme or "https"
        key = f"{scheme}://{host}"
        if key not in self._parsers:
            async with self._lock:
                if key not in self._parsers:
                    self._parsers[key] = await self._fetch(key)
        rp = self._parsers[key]
        if rp is None:
            # No robots.txt, or it could not be retrieved — default allow.
            return True
        try:
            return rp.can_fetch(self._ua, url)
        except Exception:
            return True

    async def _fetch(self, host_root: str) -> urllib.robotparser.RobotFileParser | None:
        robots_url = f"{host_root}/robots.txt"
        try:
            resp = await self._client.get(
                robots_url,
                headers={"User-Agent": self._ua},
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
            )
        except (httpx.HTTPError, ssl_err()) as _:  # noqa: F841
            return None
        except Exception:
            return None
        if resp.status_code >= 400:
            return None
        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.parse(resp.text.splitlines())
        except Exception:
            return None
        return rp


def ssl_err():  # pragma: no cover — trivial alias
    import ssl

    return ssl.SSLError


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class RateLimiter:
    """Token-bucket-ish limiter combining a global semaphore with per-host QPS.

    We keep a ``last_hit`` timestamp per host and sleep the difference up to
    ``1/per_host_qps`` before yielding. Global concurrency is bounded by the
    semaphore passed in by the caller.
    """

    def __init__(self, per_host_qps: float) -> None:
        self._min_gap = 1.0 / max(per_host_qps, 0.01)
        self._last_hit: dict[str, float] = defaultdict(lambda: 0.0)
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def acquire(self, host: str) -> None:
        async with self._locks_guard:
            lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            wait = self._last_hit[host] + self._min_gap - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_hit[host] = time.monotonic()


# ---------------------------------------------------------------------------
# Probe logic
# ---------------------------------------------------------------------------


async def probe_url(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[int | None, str | None, str | None]:
    """Return ``(status, final_url, error)``.

    ``status`` is ``None`` when the request could not complete; ``error``
    carries a short diagnostic in that case. ``final_url`` is the resolved
    URL after redirects (only populated for successful responses).
    """
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = await client.head(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        return None, None, f"head:{type(exc).__name__}"
    except Exception as exc:  # e.g. UnicodeError on malformed host
        return None, None, f"head:{type(exc).__name__}"

    status = resp.status_code
    if status in (405, 501):
        try:
            resp = await client.get(
                url,
                headers={**headers, "Range": "bytes=0-1023"},
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            return None, None, f"get:{type(exc).__name__}"
        except Exception as exc:
            return None, None, f"get:{type(exc).__name__}"
        status = resp.status_code

    return status, str(resp.url), None


# ---------------------------------------------------------------------------
# Per-row worker
# ---------------------------------------------------------------------------


async def handle_row(
    row: sqlite3.Row,
    client: httpx.AsyncClient,
    limiter: RateLimiter,
    robots: RobotsCache,
    global_sem: asyncio.Semaphore,
    stats: Counter[str],
    per_host: Counter[str],
    changes: list[dict[str, Any]],
) -> None:
    unified_id = row["unified_id"]
    url = row["source_url"]
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower() or "(no-host)"

    # R2 P2 (2026-05-13): refuse to probe non-HTTPS URLs or hosts that
    # resolve to a private / loopback / link-local / IMDS address. The
    # check runs in a thread pool because socket.getaddrinfo is blocking
    # and we're inside the async loop. A refused row is a liveness failure:
    # we do not fetch it, but it still advances the 3-strike quarantine
    # counter because the source cannot be safely checked.
    safe, reason = await asyncio.to_thread(is_url_safe, url)
    if not safe:
        stats["unsafe_url"] += 1
        new_fail_count = row["source_fail_count"] + 1
        quarantined = new_fail_count >= QUARANTINE_THRESHOLD
        if quarantined:
            stats["quarantined"] += 1
        changes.append(
            {
                "unified_id": unified_id,
                "url": url,
                "host": host,
                "outcome": "unsafe_url",
                "status": None,
                "final_url": None,
                "error": reason,
                "fail_count_after": new_fail_count,
                "quarantined": quarantined,
            }
        )
        return

    async with global_sem:
        per_host[host] += 1

        if not await robots.can_fetch(url):
            stats["robots_disallow"] += 1
            changes.append(
                {
                    "unified_id": unified_id,
                    "url": url,
                    "host": host,
                    "outcome": "robots_disallow",
                    "status": None,
                    "final_url": None,
                    "fail_count_after": row["source_fail_count"],
                }
            )
            return

        await limiter.acquire(host)
        status, final_url, error = await probe_url(client, url)

    if status is None:
        stats["error"] += 1
        new_fail_count = row["source_fail_count"] + 1
        quarantined = new_fail_count >= QUARANTINE_THRESHOLD
        if quarantined:
            stats["quarantined"] += 1
        outcome = "error"
        changes.append(
            {
                "unified_id": unified_id,
                "url": url,
                "host": host,
                "outcome": outcome,
                "status": None,
                "final_url": None,
                "error": error,
                "fail_count_after": new_fail_count,
                "quarantined": quarantined,
            }
        )
        return

    final_host = ""
    if final_url:
        try:
            final_host = (urlparse(final_url).hostname or "").lower()
        except Exception:
            final_host = ""

    redirected_host = bool(final_url and final_host and final_host != host)

    if 200 <= status < 300:
        outcome = "ok"
        stats["ok"] += 1
        if redirected_host:
            stats["redirect_host_changed"] += 1
            outcome = "ok_redirected"
    elif 300 <= status < 400:
        # Most 3xx would be followed by httpx; anything left here is a
        # non-location 3xx or a redirect loop stopped by max_redirects.
        outcome = "redirect_unresolved"
        stats["redirect_unresolved"] += 1
    else:
        outcome = "fail"
        stats["fail"] += 1

    new_fail_count = row["source_fail_count"]
    quarantined = False
    if outcome in ("fail",):
        new_fail_count = row["source_fail_count"] + 1
        if new_fail_count >= QUARANTINE_THRESHOLD:
            quarantined = True
            stats["quarantined"] += 1

    changes.append(
        {
            "unified_id": unified_id,
            "url": url,
            "host": host,
            "outcome": outcome,
            "status": status,
            "final_url": final_url,
            "final_host": final_host,
            "redirected_host": redirected_host,
            "fail_count_after": new_fail_count,
            "quarantined": quarantined,
        }
    )


# ---------------------------------------------------------------------------
# Commit changes back to DB
# ---------------------------------------------------------------------------


def commit_changes(
    con: sqlite3.Connection,
    changes: list[dict[str, Any]],
    dry_run: bool,
) -> Counter[str]:
    written: Counter[str] = Counter()
    if dry_run:
        for ch in changes:
            if ch["outcome"] in ("ok", "ok_redirected"):
                written["would_update_fetched_at"] += 1
            if ch.get("redirected_host"):
                written["would_log_redirect"] += 1
            if ch["outcome"] in FAILURE_OUTCOMES:
                written["would_increment_fail"] += 1
                if ch.get("quarantined"):
                    written["would_quarantine"] += 1
        return written

    cur = con.cursor()
    for ch in changes:
        uid = ch["unified_id"]
        outcome = ch["outcome"]
        status = ch["status"]

        if outcome in ("ok", "ok_redirected"):
            cur.execute(
                "UPDATE programs SET source_fetched_at=DATETIME('now'), "
                "source_last_check_status=?, source_fail_count=0 "
                "WHERE unified_id=?",
                (status, uid),
            )
            written["update_fetched_at"] += 1

        if ch.get("redirected_host"):
            cur.execute(
                "INSERT INTO source_redirects (unified_id, orig_url, final_url) VALUES (?, ?, ?)",
                (uid, ch["url"], ch["final_url"]),
            )
            written["log_redirect"] += 1

        if outcome in FAILURE_OUTCOMES:
            new_count = ch["fail_count_after"]
            reason = ch.get("error") or (f"http_{status}" if status is not None else "unknown")
            action = f"increment_fail_count:{outcome}:{reason}"
            if ch.get("quarantined"):
                cur.execute(
                    "UPDATE programs SET excluded=1, tier='X', "
                    "source_url_corrected_at=DATETIME('now'), "
                    "source_last_check_status=?, source_fail_count=? "
                    "WHERE unified_id=?",
                    (status, new_count, uid),
                )
                written["quarantine"] += 1
                action = f"quarantined_after_{QUARANTINE_THRESHOLD}:{outcome}:{reason}"
            else:
                cur.execute(
                    "UPDATE programs SET source_last_check_status=?, "
                    "source_fail_count=? WHERE unified_id=?",
                    (status, new_count, uid),
                )
                written["increment_fail"] += 1
            cur.execute(
                "INSERT INTO source_failures "
                "(unified_id, source_url, status_code, action) "
                "VALUES (?, ?, ?, ?)",
                (uid, ch["url"], status, action),
            )

    con.commit()
    return written


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def run_async(
    rows: list[sqlite3.Row],
    concurrency: int,
    per_host_qps: float,
) -> tuple[Counter[str], Counter[str], list[dict[str, Any]]]:
    stats: Counter[str] = Counter()
    per_host: Counter[str] = Counter()
    changes: list[dict[str, Any]] = []

    limits = httpx.Limits(
        max_connections=concurrency * 2,
        max_keepalive_connections=concurrency,
    )
    transport = httpx.AsyncHTTPTransport(retries=0)
    async with httpx.AsyncClient(
        transport=transport,
        limits=limits,
        max_redirects=MAX_REDIRECTS,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        robots = RobotsCache(client, USER_AGENT)
        limiter = RateLimiter(per_host_qps)
        sem = asyncio.Semaphore(concurrency)

        tasks = [
            asyncio.create_task(
                handle_row(r, client, limiter, robots, sem, stats, per_host, changes)
            )
            for r in rows
        ]

        total = len(tasks)
        for checked, coro in enumerate(asyncio.as_completed(tasks), 1):
            await coro
            if checked % 100 == 0 or checked == total:
                print(
                    f"  progress {checked}/{total} "
                    f"ok={stats['ok'] + stats['ok_redirected']} "
                    f"redirect={stats['redirect_host_changed']} "
                    f"fail={stats['fail']} "
                    f"error={stats['error']} "
                    f"unsafe_url={stats['unsafe_url']} "
                    f"quarantined={stats['quarantined']}",
                    flush=True,
                )

    return stats, per_host, changes


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def build_report(
    rows: list[sqlite3.Row],
    stats: Counter[str],
    per_host: Counter[str],
    changes: list[dict[str, Any]],
    written: Counter[str],
    started_at: float,
    dry_run: bool,
    tiers_in_scope: list[str] | None = None,
) -> dict[str, Any]:
    elapsed = time.monotonic() - started_at
    host_fail: Counter[str] = Counter()
    for ch in changes:
        if ch["outcome"] in FAILURE_OUTCOMES:
            host_fail[ch["host"]] += 1

    quarantined_ids = [ch["unified_id"] for ch in changes if ch.get("quarantined")]

    # Per-tier roll-up for the freshness report.
    # ``rows`` is the candidate set, ``changes`` mirrors it 1:1 by unified_id.
    tier_by_uid = {r["unified_id"]: (r["tier"] or "?") for r in rows}
    per_tier_total: Counter[str] = Counter()
    per_tier_dead: Counter[str] = Counter()
    per_tier_ok: Counter[str] = Counter()
    for r in rows:
        per_tier_total[r["tier"] or "?"] += 1
    for ch in changes:
        tier = tier_by_uid.get(ch["unified_id"], "?")
        outcome = ch["outcome"]
        if outcome in ("ok", "ok_redirected"):
            per_tier_ok[tier] += 1
        elif outcome in FAILURE_OUTCOMES or outcome == "redirect_unresolved":
            per_tier_dead[tier] += 1

    per_tier = {
        tier: {
            "total": per_tier_total.get(tier, 0),
            "ok": per_tier_ok.get(tier, 0),
            "dead": per_tier_dead.get(tier, 0),
        }
        for tier in sorted(per_tier_total)
    }

    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "tiers_in_scope": list(tiers_in_scope) if tiers_in_scope else None,
        "rows_checked": len(rows),
        "elapsed_seconds": round(elapsed, 2),
        "totals": dict(stats),
        "writes": dict(written),
        "per_tier": per_tier,
        "per_host_checks_top20": per_host.most_common(20),
        "top_failing_hosts": host_fail.most_common(10),
        "quarantined_unified_ids": quarantined_ids,
    }


# ---------------------------------------------------------------------------
# Freshness report (append-mode) for Loop I dashboard
# ---------------------------------------------------------------------------


# Path to the rolling per-tier freshness summary. Loop I (the weekly self-
# improve audit at `src/jpintel_mcp/self_improve/loop_i_doc_freshness.py`)
# treats this file as a snapshot — we replace the top-level structure but
# keep a `history` list with the last 12 runs so the dashboard can chart
# trend without bloating the JSON.
DEFAULT_FRESHNESS_REPORT = os.path.join(REPO_ROOT, "data", "source_freshness_report.json")
FRESHNESS_HISTORY_KEEP = 12


def append_freshness_report(
    report: dict[str, Any],
    freshness_path: str,
) -> dict[str, Any]:
    """Merge this run's per-tier counts into the rolling freshness file.

    Loop I's expected schema (see existing `data/source_freshness_report.json`):
        loop, generated_at, dry_run, stale_threshold_days, rows_scanned,
        stale_count, broken_count, per_tier{tier:{total,stale,broken}},
        high_priority_broken
    We keep the top-level shape compatible (no breaking change) and add a
    `history` list with the last N condensed runs so trend is queryable
    without re-walking every cron output.
    """
    existing: dict[str, Any] = {}
    if os.path.exists(freshness_path):
        try:
            with open(freshness_path, encoding="utf-8") as fh:
                existing = json.load(fh)
        except (OSError, json.JSONDecodeError):
            existing = {}

    per_tier = report.get("per_tier") or {}
    # Synthesise top-level counts from this run's per-tier breakdown so the
    # downstream consumer keeps working without code changes.
    broken_count = sum(int(v.get("dead", 0)) for v in per_tier.values())
    rows_scanned_total = sum(int(v.get("total", 0)) for v in per_tier.values())

    # Translate this run's per_tier into the (total, stale, broken) shape
    # Loop I expects. We surface "dead" as broken; "stale" stays owned by
    # Loop I's stale-by-age check and is left untouched here.
    merged_per_tier: dict[str, dict[str, int]] = dict(existing.get("per_tier") or {})
    for tier, counts in per_tier.items():
        prev = merged_per_tier.get(tier, {"total": 0, "stale": 0, "broken": 0})
        merged_per_tier[tier] = {
            "total": int(counts.get("total", prev.get("total", 0))),
            "stale": int(prev.get("stale", 0)),
            "broken": int(counts.get("dead", 0)),
        }

    history = list(existing.get("history") or [])
    history.append(
        {
            "generated_at": report.get("generated_at"),
            "tiers_in_scope": report.get("tiers_in_scope"),
            "rows_checked": report.get("rows_checked"),
            "per_tier": per_tier,
            "totals": report.get("totals"),
            "elapsed_seconds": report.get("elapsed_seconds"),
            "dry_run": report.get("dry_run"),
        }
    )
    history = history[-FRESHNESS_HISTORY_KEEP:]

    new_doc = {
        "loop": existing.get("loop") or "loop_i_doc_freshness",
        "generated_at": report.get("generated_at"),
        "dry_run": bool(report.get("dry_run")),
        "stale_threshold_days": existing.get("stale_threshold_days") or 60,
        "rows_scanned": max(int(existing.get("rows_scanned") or 0), rows_scanned_total),
        "stale_count": int(existing.get("stale_count") or 0),
        "broken_count": broken_count,
        "per_tier": merged_per_tier,
        "high_priority_broken": existing.get("high_priority_broken") or [],
        "history": history,
    }

    os.makedirs(os.path.dirname(freshness_path), exist_ok=True)
    with open(freshness_path, "w", encoding="utf-8") as fh:
        json.dump(new_doc, fh, ensure_ascii=False, indent=2)
    return new_doc


def maybe_open_dead_url_issue(
    report: dict[str, Any],
    threshold: int = TIER_C_DEAD_ISSUE_THRESHOLD,
) -> dict[str, Any] | None:
    """Best-effort GitHub Issue when Tier-C dead URLs exceed ``threshold``.

    Uses ``gh issue create`` only when ``GH_TOKEN``/``GITHUB_TOKEN`` is
    present; otherwise returns a structured dict so the cron log explains
    what would have happened. Errors never raise — this is purely
    informational.
    """
    per_tier = report.get("per_tier") or {}
    c_counts = per_tier.get("C") or {}
    dead_c = int(c_counts.get("dead", 0))
    if dead_c <= threshold:
        return None

    title = (
        f"refresh_sources: tier C dead URLs = {dead_c} "
        f"(> {threshold}) on {report.get('generated_at')}"
    )
    top_hosts = report.get("top_failing_hosts") or []
    body_lines = [
        f"Tier C dead URL count exceeded the alert threshold (`{dead_c}` > `{threshold}`).",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        f"Tiers in scope: `{report.get('tiers_in_scope')}`",
        f"Rows checked: `{report.get('rows_checked')}`",
        "",
        "Top failing hosts:",
    ]
    for host, n in top_hosts[:10]:
        body_lines.append(f"- `{host}` × {n}")
    body_lines.append("")
    body_lines.append(
        "Per-tier (this run):\n" + "\n".join(f"- {t}: {v}" for t, v in (per_tier.items() or []))
    )
    body = "\n".join(body_lines)

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        return {
            "would_open": True,
            "title": title,
            "body": body,
            "reason": "no_gh_token",
        }

    import shutil
    import subprocess

    if not shutil.which("gh"):
        return {
            "would_open": True,
            "title": title,
            "body": body,
            "reason": "gh_cli_missing",
        }

    try:
        subprocess.run(
            [
                "gh",
                "issue",
                "create",
                "--title",
                title,
                "--label",
                "data-quality",
                "--label",
                "automation",
                "--body",
                body,
            ],
            check=True,
            env={**os.environ, "GH_TOKEN": token},
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {"opened": True, "title": title}
    except Exception as exc:  # pragma: no cover — informational
        return {
            "opened": False,
            "title": title,
            "error": f"{type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_tiers(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [t.strip() for t in raw.split(",") if t.strip()]


def resolve_concurrency(
    user_value: int,
    tiers: list[str] | None,
) -> int:
    """Cap concurrency by the lowest cap among requested tiers.

    Tier C halves the cap (5) so high-volume city / prefecture domain
    clusters never burst past polite-crawler etiquette. If the user
    explicitly passes a smaller value via `--concurrency`, we honour it.
    """
    scope = tiers or list(DEFAULT_TIERS)
    caps = [TIER_CONCURRENCY_CAP[t] for t in scope if t in TIER_CONCURRENCY_CAP]
    if not caps:
        return max(1, user_value)
    tier_cap = min(caps)
    return max(1, min(user_value, tier_cap))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument(
        "--tier",
        default=",".join(DEFAULT_TIERS),
        help=(
            "Comma-separated tier filter (e.g. 'S,A,B,C'). "
            "Default: 'S,A,B,C'. Tier 'X' is silently dropped — it is "
            "the quarantine tier excluded from every search path."
        ),
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--report-only",
        action="store_true",
        help=(
            "Synonym for --dry-run, used by the B/C tier passes that must "
            "remain read-only against the DB (no fetched_at bump, no "
            "fail-count increment, no quarantine). The freshness JSON is "
            "still produced."
        ),
    )
    ap.add_argument("--max-rows", type=int, default=None)
    ap.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help=(
            "Upper bound on concurrent requests. Capped per-tier — Tier C "
            "uses 5, Tier B uses 8, Tier S/A uses 10."
        ),
    )
    ap.add_argument(
        "--per-host-qps",
        type=float,
        default=1.0,
        help=(
            "Per-host request rate ceiling. Default 1 req/sec keeps us "
            "well under any realistic municipal-portal rate limit."
        ),
    )
    ap.add_argument("--report", default=DEFAULT_REPORT)
    ap.add_argument(
        "--freshness-report",
        default=DEFAULT_FRESHNESS_REPORT,
        help=(
            "Path to the rolling per-tier freshness summary "
            "(`data/source_freshness_report.json` by default). The latest "
            "run's per-tier counts are merged in and the last 12 runs "
            "are kept under `history`."
        ),
    )
    ap.add_argument(
        "--issue-on-tier-c-dead-threshold",
        type=int,
        default=TIER_C_DEAD_ISSUE_THRESHOLD,
        help=(
            "When the count of Tier-C dead URLs in this run exceeds this "
            "value, attempt to open a GitHub issue via the `gh` CLI. "
            "Requires GH_TOKEN/GITHUB_TOKEN in env; otherwise logs the "
            "intended payload and continues."
        ),
    )
    args = ap.parse_args(argv)

    tiers = parse_tiers(args.tier)
    dry_run = bool(args.dry_run or args.report_only)
    concurrency = resolve_concurrency(args.concurrency, tiers)

    if not os.path.exists(args.db):
        print(f"ERR: db not found: {args.db}", file=sys.stderr)
        return 2

    con = sqlite3.connect(args.db)
    try:
        migration_results = apply_migrations(con)
        new_migrations = [k for k, v in migration_results.items() if v]
        if new_migrations:
            print("migrations applied:")
            for m in new_migrations:
                print(f"  {m}")

        rows = load_rows(con, tiers, args.max_rows)
        print(
            f"refresh_sources — {len(rows)} rows selected "
            f"(tier={tiers or 'any'}, max_rows={args.max_rows}, "
            f"concurrency={concurrency} (req={args.concurrency}), "
            f"per_host_qps={args.per_host_qps}, dry_run={dry_run})"
        )
        if not rows:
            print("no rows to check — exiting clean")
            report = build_report(
                rows,
                Counter(),
                Counter(),
                [],
                Counter(),
                time.monotonic(),
                dry_run,
                tiers,
            )
            os.makedirs(os.path.dirname(args.report), exist_ok=True)
            with open(args.report, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=2)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        started_at = time.monotonic()
        stats, per_host, changes = asyncio.run(run_async(rows, concurrency, args.per_host_qps))

        written = commit_changes(con, changes, dry_run)
        report = build_report(rows, stats, per_host, changes, written, started_at, dry_run, tiers)
    finally:
        con.close()

    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    # Roll the per-tier counts forward into the long-running freshness file
    # consumed by Loop I and the operator dashboard.
    try:
        append_freshness_report(report, args.freshness_report)
    except Exception as exc:  # pragma: no cover — informational
        print(f"warn: freshness append failed: {exc}", file=sys.stderr)

    issue_action = maybe_open_dead_url_issue(report, threshold=args.issue_on_tier_c_dead_threshold)
    if issue_action:
        print("tier_c_dead_alert:", json.dumps(issue_action, ensure_ascii=False))

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
