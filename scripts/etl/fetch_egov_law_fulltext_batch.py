#!/usr/bin/env python3
"""fetch_egov_law_fulltext_batch.py — Parallel e-Gov 法令本文 batch fetcher.

Purpose
-------
Backfill the 9,330 法令 catalog stubs in ``data/jpintel.db`` (laws table)
that have no body text yet. e-Gov publishes 法令 XML under CC-BY 4.0; we
fetch + parse + write to a CSV so the live ``autonomath.db`` (held by an
in-flight other CLI process) never sees a write from this path.

Design
------
* **Read-only** against ``data/jpintel.db``. Selects laws missing body
  text (column-aware: if the laws table grows a ``body_text`` column
  later this script picks it up automatically; otherwise falls back to
  treating every catalog row as a candidate, since the canonical body
  store lives elsewhere — see CLAUDE.md "154 full-text + 9,484 catalog
  stubs"). Either way the SELECT touches no other DB.
* **Parallel** via ``httpx.AsyncClient`` + ``asyncio.Semaphore`` (5
  concurrent in-flight). Each request still respects a per-domain
  Crawl-Delay of 1.0s using a per-host gate, so the effective rate is
  bounded by the slower of (Semaphore, Crawl-Delay).
* **CSV out, no DB writes.** Output rows: ``law_id, body_text,
  fetched_at, source_url, content_hash``. The body_text column is
  newline-stripped + whitespace-collapsed so the CSV stays one-row-per-
  law without quoting hazards.
* **Polite UA** ``jpcite-research/1.0 (+https://jpcite.com/about)``.
  30s timeout, 1 retry on 5xx / network error.
* **Independent of incremental_law_fulltext.py.** Reuses none of its
  state and writes to a different path; the existing weekly cron is
  untouched.

robots.txt note
---------------
``https://laws.e-gov.go.jp/robots.txt`` returns a 200 HTML page (the SPA
shell), i.e. there is no real robots.txt and no Disallow rules to honor.
We log the verification at startup. The script bails if the verification
itself fails (network down at minute 0).

API endpoint divergence
-----------------------
The task spec referenced ``https://elaws.e-gov.go.jp/api/2/lawdata/<id>``
but that path 301-redirects to ``laws.e-gov.go.jp/api/2/lawdata/<id>``
which then 404s. The actual live v2 path on the same host is
``/api/2/law_data/<id>`` (with the underscore — matches what the
existing ``ingest_law_articles_egov.py`` and the weekly cron use). We
use the working path; the docstring records this so a future reader can
see why.

Usage
-----
    .venv/bin/python scripts/etl/fetch_egov_law_fulltext_batch.py \\
        --limit 50 \\
        --out analysis_wave18/egov_law_fulltext_batch_2026-05-01.csv

    .venv/bin/python scripts/etl/fetch_egov_law_fulltext_batch.py \\
        --limit 5 \\
        --dry-run

Exit codes
----------
0  success (with possibly partial fetch failures recorded in stats)
1  fatal (db missing, robots verification failure, etc.)
2  no candidate laws found
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import logging
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    print(f"missing dep: {exc}. pip install httpx", file=sys.stderr)
    sys.exit(1)


_LOG = logging.getLogger("jpcite.etl.fetch_egov_law_fulltext_batch")
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB = _REPO_ROOT / "data" / "jpintel.db"
_DEFAULT_OUT = _REPO_ROOT / "analysis_wave18" / "egov_law_fulltext_batch_2026-05-01.csv"

# Spec divergence (auditable): the task spec referenced
#   ``https://elaws.e-gov.go.jp/api/2/lawdata/<id>``
# but at the time of writing both forms of that path return 404 — the
# redirected ``laws.e-gov.go.jp/api/2/lawdata/<id>`` is also 404. The
# only live v2 endpoint serving the XML body is
#   ``https://laws.e-gov.go.jp/api/2/law_data/<id>``  (note the underscore)
# which is also what the existing ``scripts/cron/incremental_law_fulltext.py``
# uses. We hit the working path here so smoke runs aren't all-404.
_EGOV_URL_TEMPLATE = "https://laws.e-gov.go.jp/api/2/law_data/{law_id}"
_EGOV_HUMAN_URL_TEMPLATE = "https://laws.e-gov.go.jp/law/{law_id}"
_EGOV_ROBOTS_URL = "https://laws.e-gov.go.jp/robots.txt"

_USER_AGENT = "jpcite-research/1.0 (+https://jpcite.com/about)"
_HTTP_TIMEOUT = 30.0
_PARALLEL = 5
_RETRY_LIMIT = 1  # 1 retry on 5xx / network errors (= 2 attempts)
_CRAWL_DELAY_SEC = 1.0  # per-domain Crawl-Delay (e-Gov polite budget)

# CSV column order (stable contract for downstream merge).
_CSV_FIELDS = ["law_id", "body_text", "fetched_at", "source_url", "content_hash"]


# ---------------------------------------------------------------------------
# DB candidate selection (READ-ONLY)
# ---------------------------------------------------------------------------


_LAW_ID_FROM_URL_RE = re.compile(r"/law/([A-Za-z0-9]+)$")


def _extract_law_id(full_text_url: str | None, unified_id: str) -> str | None:
    """Pull the e-Gov law_id out of ``full_text_url``.

    Falls back to ``None`` when the URL is malformed — caller should skip
    those rows rather than guess. (We intentionally do NOT reverse-derive
    a law_id from ``unified_id`` because that mapping is not invertible.)
    """
    if not full_text_url:
        return None
    m = _LAW_ID_FROM_URL_RE.search(full_text_url.strip())
    return m.group(1) if m else None


def _laws_has_column(con: sqlite3.Connection, col: str) -> bool:
    rows = con.execute("PRAGMA table_info(laws)").fetchall()
    return any(r["name"] == col for r in rows)


def select_candidates(con: sqlite3.Connection, limit: int | None) -> list[dict[str, Any]]:
    """Return laws missing body text, capped at ``limit`` (None = all).

    The laws table in jpintel.db doesn't currently carry a ``body_text``
    column — the canonical body store is ``am_law_article`` over in
    autonomath.db, which we are forbidden to write to here. To stay
    forward-compatible if the column is added later, we detect it
    dynamically.
    """
    has_body = _laws_has_column(con, "body_text")
    if has_body:
        sql = (
            "SELECT unified_id, full_text_url, law_title "
            "FROM laws WHERE (body_text IS NULL OR body_text = '') "
            "ORDER BY unified_id"
        )
    else:
        sql = "SELECT unified_id, full_text_url, law_title FROM laws ORDER BY unified_id"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    rows = con.execute(sql).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        law_id = _extract_law_id(r["full_text_url"], r["unified_id"])
        if not law_id:
            continue
        out.append(
            {
                "unified_id": r["unified_id"],
                "law_id": law_id,
                "law_title": r["law_title"],
                "full_text_url": r["full_text_url"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# robots.txt verification
# ---------------------------------------------------------------------------


def verify_robots(client: httpx.Client | None = None) -> dict[str, Any]:
    """Fetch + log robots.txt. Returns a small dict with the outcome.

    e-Gov's site currently returns the SPA HTML shell at /robots.txt
    rather than a real robots.txt file. We treat that as "no Disallow
    rules" but record the body length + content-type so the auditor can
    re-verify later. If the verification itself fails (network down at
    minute zero) the caller should bail.
    """
    own_client = client is None
    if own_client:
        client = httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
        )
    try:
        resp = client.get(_EGOV_ROBOTS_URL)
        ct = resp.headers.get("content-type", "")
        body = resp.text or ""
        # Parse Disallow lines (case-insensitive). If body is HTML we
        # short-circuit: no Disallow lines exist in HTML soup.
        disallows: list[str] = []
        if "text/plain" in ct.lower():
            for line in body.splitlines():
                ls = line.strip()
                if ls.lower().startswith("disallow:"):
                    disallows.append(ls.split(":", 1)[1].strip())
        return {
            "status_code": resp.status_code,
            "content_type": ct,
            "body_len": len(body),
            "disallow_paths": disallows,
        }
    finally:
        if own_client:
            client.close()


def disallows_api_path(disallow_paths: list[str]) -> bool:
    """Return True if any Disallow entry covers ``/api/2/law_data/`` etc."""
    for d in disallow_paths:
        if not d:
            continue
        # Treat "/" as a full block. Otherwise prefix-match against the
        # API root we hit.
        if d == "/" or "/api" in d or "lawdata" in d.lower():
            return True
    return False


# ---------------------------------------------------------------------------
# XML parse helpers
# ---------------------------------------------------------------------------


def _text_recursive(elem: ET.Element) -> str:
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(_text_recursive(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def parse_egov_xml(xml_bytes: bytes) -> dict[str, Any]:
    """Extract body_text + promulgation_date + amendment summary.

    Returns a dict (possibly with empty strings) — never raises on
    well-formed XML; raises ET.ParseError on malformed input so the
    caller can record a parse_error status.
    """
    root = ET.fromstring(xml_bytes)  # nosec B314 - input is trusted gov-source XML; not user-supplied

    # Concatenate every <Article> body. Collapsing intra-article
    # whitespace keeps the CSV one-row-per-law without embedded
    # newlines (which a downstream Excel/pandas merge step may not
    # tolerate gracefully).
    body_chunks: list[str] = []
    for art in root.iter("Article"):
        chunk = _text_recursive(art).strip()
        if chunk:
            body_chunks.append(chunk)
    body_text = " ".join(body_chunks)
    body_text = re.sub(r"[ \t\r\n　]+", " ", body_text).strip()

    # 制定日 (promulgation date) lives at /law_data_response/law_info/promulgation_date
    promulgation_date = ""
    pe = root.find(".//law_info/promulgation_date")
    if pe is not None and pe.text:
        promulgation_date = pe.text.strip()

    # 改正履歴: e-Gov v2 carries it as the revision_info wrapper.
    # We capture a minimal summary string ("revision_id|law_title") rather
    # than the full XML — enough for a downstream consumer to detect
    # whether a refetch is needed.
    amendment_summary = ""
    rev = root.find(".//revision_info")
    if rev is not None:
        rid_el = rev.find("law_revision_id")
        ltitle_el = rev.find("law_title")
        rid = (rid_el.text or "").strip() if rid_el is not None else ""
        ltitle = (ltitle_el.text or "").strip() if ltitle_el is not None else ""
        if rid or ltitle:
            amendment_summary = f"{rid}|{ltitle}"

    return {
        "body_text": body_text,
        "promulgation_date": promulgation_date,
        "amendment_summary": amendment_summary,
        "article_count": len(body_chunks),
    }


# ---------------------------------------------------------------------------
# Fetcher core
# ---------------------------------------------------------------------------


class HostGate:
    """Per-domain Crawl-Delay enforcement.

    With ``_PARALLEL=5`` Semaphore + 1.0s gate per host, the effective
    rate is 1 req/sec on e-Gov regardless of how many tasks are queued.
    """

    def __init__(self, delay_sec: float) -> None:
        self._delay = delay_sec
        self._lock = asyncio.Lock()
        self._next_allowed: dict[str, float] = defaultdict(lambda: 0.0)

    async def acquire(self, host: str) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_allowed[host] - now
            if wait > 0:
                # Release lock while sleeping so other hosts aren't
                # blocked by this host's queue.
                pass
            else:
                wait = 0
            self._next_allowed[host] = max(now, self._next_allowed[host]) + self._delay
        if wait > 0:
            await asyncio.sleep(wait)


async def _fetch_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    gate: HostGate,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Fetch + parse a single law. Returns a row dict ready for CSV."""
    law_id = candidate["law_id"]
    url = _EGOV_URL_TEMPLATE.format(law_id=law_id)
    host = urlparse(url).hostname or "unknown"

    row: dict[str, Any] = {
        "law_id": law_id,
        "unified_id": candidate["unified_id"],
        "body_text": "",
        "fetched_at": "",
        "source_url": _EGOV_HUMAN_URL_TEMPLATE.format(law_id=law_id),
        "content_hash": "",
        "promulgation_date": "",
        "amendment_summary": "",
        "article_count": 0,
        "status": "pending",
        "error": "",
        "host": host,
    }

    async with sem:
        await gate.acquire(host)
        attempts = _RETRY_LIMIT + 1
        last_status: int | None = None
        last_err: str | None = None
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.get(url)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError) as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                if attempt < attempts:
                    await asyncio.sleep(0.5 * attempt)
                    continue
                row["status"] = "fetch_error"
                row["error"] = last_err
                row["fetched_at"] = datetime.now(UTC).isoformat()
                return row

            last_status = resp.status_code
            if resp.status_code == 200:
                xml_bytes = resp.content
                row["fetched_at"] = datetime.now(UTC).isoformat()
                # Update source_url to the actual final URL (after redirect)
                # so downstream consumers can verify provenance.
                row["source_url"] = str(resp.url) or row["source_url"]
                try:
                    parsed = parse_egov_xml(xml_bytes)
                except ET.ParseError as exc:
                    row["status"] = "parse_error"
                    row["error"] = f"ParseError: {exc}"
                    return row
                if not parsed["body_text"]:
                    row["status"] = "empty_body"
                    return row
                row["body_text"] = parsed["body_text"]
                row["promulgation_date"] = parsed["promulgation_date"]
                row["amendment_summary"] = parsed["amendment_summary"]
                row["article_count"] = parsed["article_count"]
                row["content_hash"] = hashlib.sha256(
                    parsed["body_text"].encode("utf-8")
                ).hexdigest()
                row["status"] = "ok"
                return row
            if resp.status_code == 404:
                row["status"] = "egov_404"
                row["error"] = "404"
                row["fetched_at"] = datetime.now(UTC).isoformat()
                return row
            if resp.status_code == 403:
                row["status"] = "blocked"
                row["error"] = "403"
                row["fetched_at"] = datetime.now(UTC).isoformat()
                return row
            if 500 <= resp.status_code < 600:
                last_err = f"HTTP {resp.status_code}"
                if attempt < attempts:
                    await asyncio.sleep(0.5 * attempt)
                    continue
                row["status"] = "fetch_error"
                row["error"] = last_err
                row["fetched_at"] = datetime.now(UTC).isoformat()
                return row
            # Other 4xx — record + give up.
            row["status"] = "client_error"
            row["error"] = f"HTTP {resp.status_code}"
            row["fetched_at"] = datetime.now(UTC).isoformat()
            return row

        # Unreachable (loop always returns), but keep mypy happy.
        row["status"] = "fetch_error"
        row["error"] = last_err or f"HTTP {last_status}"
        row["fetched_at"] = datetime.now(UTC).isoformat()
        return row


async def fetch_batch(
    candidates: list[dict[str, Any]],
    *,
    parallel: int = _PARALLEL,
    crawl_delay_sec: float = _CRAWL_DELAY_SEC,
    timeout_sec: float = _HTTP_TIMEOUT,
) -> list[dict[str, Any]]:
    """Fetch all candidates with bounded concurrency + per-host Crawl-Delay."""
    sem = asyncio.Semaphore(parallel)
    gate = HostGate(delay_sec=crawl_delay_sec)
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/xml, text/xml; q=0.9, */*; q=0.1",
    }
    async with httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(timeout_sec, connect=10.0),
        follow_redirects=True,
    ) as client:
        tasks = [asyncio.create_task(_fetch_one(client, sem, gate, c)) for c in candidates]
        rows: list[dict[str, Any]] = []
        for fut in asyncio.as_completed(tasks):
            r = await fut
            rows.append(r)
            _LOG.info(
                "fetch law_id=%s status=%s articles=%d host=%s",
                r["law_id"],
                r["status"],
                r["article_count"],
                r["host"],
            )
    return rows


# ---------------------------------------------------------------------------
# CSV writer + stats
# ---------------------------------------------------------------------------


def write_csv(out_path: Path, rows: list[dict[str, Any]]) -> int:
    """Write the success rows to CSV. Returns number of rows written.

    Only ``status == 'ok'`` rows go into the CSV; failures are surfaced
    via the per-domain stats dict instead. This keeps the CSV usable as
    a direct feed into a downstream merge without secondary filtering.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_CSV_FIELDS, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for r in rows:
            if r["status"] != "ok":
                continue
            w.writerow({k: r.get(k, "") for k in _CSV_FIELDS})
            n += 1
    return n


def compute_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: Counter[str] = Counter()
    by_host: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        by_status[r["status"]] += 1
        by_host[r["host"]][r["status"]] += 1
    return {
        "total": len(rows),
        "by_status": dict(by_status),
        "by_host": {h: dict(c) for h, c in by_host.items()},
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool) -> None:
    root = logging.getLogger("jpcite.etl.fetch_egov_law_fulltext_batch")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Parallel e-Gov 法令本文 batch fetcher (CSV out, no DB write)."
    )
    p.add_argument(
        "--db",
        type=Path,
        default=_DEFAULT_DB,
        help=f"Read-only SQLite path (default: {_DEFAULT_DB})",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of laws to fetch (default: all missing).",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"CSV output path (default: {_DEFAULT_OUT.relative_to(_REPO_ROOT)})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print rows to stdout, do not write CSV.",
    )
    p.add_argument(
        "--parallel",
        type=int,
        default=_PARALLEL,
        help=f"Concurrent in-flight requests (default: {_PARALLEL}).",
    )
    p.add_argument(
        "--crawl-delay",
        type=float,
        default=_CRAWL_DELAY_SEC,
        help=f"Per-domain Crawl-Delay seconds (default: {_CRAWL_DELAY_SEC}).",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=_HTTP_TIMEOUT,
        help=f"Per-request timeout seconds (default: {_HTTP_TIMEOUT}).",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    if not args.db.is_file():
        _LOG.error("db_missing path=%s", args.db)
        return 1

    # 1) robots.txt verification (mandatory per spec).
    try:
        robots = verify_robots()
    except Exception as exc:
        _LOG.error("robots_check_failed err=%s", exc)
        return 1
    _LOG.info(
        "robots_check status=%d content_type=%s body_len=%d disallow_paths=%s",
        robots["status_code"],
        robots["content_type"],
        robots["body_len"],
        robots["disallow_paths"],
    )
    if disallows_api_path(robots["disallow_paths"]):
        _LOG.error(
            "robots_disallow blocked api path; aborting. paths=%s",
            robots["disallow_paths"],
        )
        return 1

    # 2) Read-only candidate selection.
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    try:
        candidates = select_candidates(con, args.limit)
    finally:
        con.close()

    if not candidates:
        _LOG.warning("no_candidates db=%s", args.db)
        return 2

    _LOG.info(
        "candidates_selected n=%d limit=%s parallel=%d crawl_delay=%.1fs",
        len(candidates),
        args.limit,
        args.parallel,
        args.crawl_delay,
    )

    # 3) Async fetch.
    t0 = time.time()
    rows = asyncio.run(
        fetch_batch(
            candidates,
            parallel=args.parallel,
            crawl_delay_sec=args.crawl_delay,
            timeout_sec=args.timeout,
        )
    )
    elapsed = time.time() - t0

    # 4) Stats + CSV.
    stats = compute_stats(rows)
    _LOG.info(
        "run_done elapsed=%.1fs total=%d by_status=%s",
        elapsed,
        stats["total"],
        stats["by_status"],
    )
    for host, host_stats in stats["by_host"].items():
        _LOG.info("by_host host=%s stats=%s", host, host_stats)

    if args.dry_run:
        # Print first 5 rows for visual inspection.
        for r in rows[:5]:
            preview = (r.get("body_text", "") or "")[:80]
            print(
                f"law_id={r['law_id']} status={r['status']} "
                f"hash={r['content_hash'][:12]} body_preview={preview!r}"
            )
        print(f"[dry-run] would write {sum(1 for r in rows if r['status'] == 'ok')} CSV rows")
    else:
        n = write_csv(args.out, rows)
        _LOG.info("wrote_csv path=%s rows=%d", args.out, n)

    return 0


if __name__ == "__main__":
    sys.exit(main())
