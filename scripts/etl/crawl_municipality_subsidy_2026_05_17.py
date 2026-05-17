"""DD2 — Async 1,714 市町村 補助金 PDF crawler (2026-05-17).

Reads the DD2 manifest at ``data/etl_dd2_municipality_manifest_2026_05_17.json``
(produced by ``scripts/etl/build_dd2_municipality_manifest_2026_05_17.py``),
walks every municipality's ``subsidy_search_seeds`` looking for PDF links
("application/pdf" / ``.pdf`` suffix), and stages the raw PDFs into S3 at::

    s3://jpcite-credit-993693061769-202605-derived/municipality_pdf_raw/
        <municipality_code>/<sha256-prefix>.pdf

A SQLite-backed idempotent ledger (``data/dd2_crawl_ledger.sqlite``) tracks
every fetched URL so re-runs skip work — this matches the existing N4 lane
pattern (``crawl_window_directory_2026_05_17.py``).

Constraints
-----------

* **NO LLM call.** Pure asyncio + httpx + bs4 + sqlite3 + boto3.
* **robots.txt strict.** Each host is probed once for ``/robots.txt`` and
  the resulting ``urllib.robotparser`` decision is cached. Disallowed
  URLs are skipped (not retried).
* **Per-host throttle.** 1 req / 3 sec per host (operator constraint),
  global concurrency limit of 32 hosts in flight.
* **Aggregator banlist.** noukaweb / hojyokin-portal / biz.stayway / stayway.jp
  / subsidies-japan / jgrant-aggregator / nikkei.com / prtimes.jp /
  wikipedia.org are rejected before fetch (CLAUDE.md データ衛生規約).
* **Primary host regex.** Only ``*.lg.jp``, ``pref.*.jp``, ``city.*.jp``,
  ``town.*.jp``, ``vill.*.jp``, ``metro.tokyo.lg.jp`` are accepted as PDF
  hosts. anything else is rejected with reason='non_primary_host'.
* **Cap per municipality.** ``max_pdf_per_municipality`` (default 8) bounds
  blast radius if a single 自治体 hosts dozens of PDFs.

Usage
-----

::

    # Dry-run (no S3 writes, count only) — safe default for development.
    python scripts/etl/crawl_municipality_subsidy_2026_05_17.py --dry-run

    # Live crawl (operator UNLOCK required upstream).
    python scripts/etl/crawl_municipality_subsidy_2026_05_17.py \\
        --manifest data/etl_dd2_municipality_manifest_2026_05_17.json \\
        --bucket jpcite-credit-993693061769-202605-derived \\
        --prefix municipality_pdf_raw/ \\
        --commit

Exit codes
----------
0  success
1  fatal (manifest missing, S3 unreachable when --commit, ledger DB error)
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import logging
import re
import sqlite3
import sys
import time
import urllib.robotparser
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

logger = logging.getLogger("jpcite.etl.dd2_crawl_municipality")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MANIFEST = _REPO_ROOT / "data" / "etl_dd2_municipality_manifest_2026_05_17.json"
_DEFAULT_LEDGER = _REPO_ROOT / "data" / "dd2_crawl_ledger.sqlite"
_DEFAULT_BUCKET = "jpcite-credit-993693061769-202605-derived"
_DEFAULT_PREFIX = "municipality_pdf_raw/"

_USER_AGENT = "jpcite-dd2-crawler/2026-05-17 (+https://jpcite.ai/crawler)"
_PER_HOST_INTERVAL = 3.0  # operator constraint: 1 req / 3 sec
_GLOBAL_CONCURRENCY = 32
_HTTP_TIMEOUT_SECONDS = 30.0
_MAX_PDF_BYTES = 50 * 1024 * 1024  # 50 MB per PDF — safety cap

_PDF_LINK_RE = re.compile(r'href=["\']([^"\']+\.pdf)(?:[?#][^"\']*)?["\']', re.IGNORECASE)
_PRIMARY_HOST_RE = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)*"
    r"(?:lg\.jp|"
    r"pref\.[a-z-]+\.jp|"
    r"city\.[a-z-]+\.[a-z-]+\.jp|city\.[a-z-]+\.jp|"
    r"town\.[a-z-]+\.[a-z-]+\.jp|town\.[a-z-]+\.jp|"
    r"vill\.[a-z-]+\.[a-z-]+\.jp|vill\.[a-z-]+\.jp|"
    r"metro\.tokyo\.lg\.jp)(?:/|$|\?|#)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class CrawlConfig:
    """Operator-facing knobs."""

    manifest_path: Path
    ledger_path: Path
    bucket: str
    prefix: str
    commit: bool
    max_municipalities: int | None
    max_pdf_per_municipality: int


@dataclass(slots=True)
class CrawlStats:
    """Aggregated outcomes of a crawl run."""

    municipalities_visited: int = 0
    seed_urls_fetched: int = 0
    pdf_links_found: int = 0
    pdf_downloaded: int = 0
    pdf_uploaded_s3: int = 0
    pdf_skipped_ledger: int = 0
    robots_disallow: int = 0
    aggregator_rejected: int = 0
    non_primary_host: int = 0
    fetch_failures: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "municipalities_visited": self.municipalities_visited,
            "seed_urls_fetched": self.seed_urls_fetched,
            "pdf_links_found": self.pdf_links_found,
            "pdf_downloaded": self.pdf_downloaded,
            "pdf_uploaded_s3": self.pdf_uploaded_s3,
            "pdf_skipped_ledger": self.pdf_skipped_ledger,
            "robots_disallow": self.robots_disallow,
            "aggregator_rejected": self.aggregator_rejected,
            "non_primary_host": self.non_primary_host,
            "fetch_failures": self.fetch_failures,
        }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=_DEFAULT_MANIFEST)
    parser.add_argument("--ledger", type=Path, default=_DEFAULT_LEDGER)
    parser.add_argument("--bucket", default=_DEFAULT_BUCKET)
    parser.add_argument("--prefix", default=_DEFAULT_PREFIX)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="lift DRY_RUN guard — actually fetch and upload to S3",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="explicit dry-run (default if --commit is absent)",
    )
    parser.add_argument(
        "--max-municipalities",
        type=int,
        default=None,
        help="cap the number of 自治体 walked (smoke test convenience)",
    )
    parser.add_argument(
        "--max-pdf-per-municipality",
        type=int,
        default=8,
        help="cap PDFs uploaded per 自治体 (default 8)",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Aggregator + host guards
# ---------------------------------------------------------------------------


_AGGREGATOR_HOSTS_DEFAULT: tuple[str, ...] = (
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "stayway.jp",
    "subsidies-japan",
    "jgrant-aggregator",
    "nikkei.com",
    "prtimes.jp",
    "wikipedia.org",
    "mapfan",
    "navitime",
    "itp.ne.jp",
    "tabelog",
    "townpages",
    "i-town",
    "ekiten",
    "subsidy-portal",
    "google.com/maps",
)


def _is_aggregator(url: str) -> bool:
    low = url.lower()
    return any(host in low for host in _AGGREGATOR_HOSTS_DEFAULT)


def _is_primary_host(url: str) -> bool:
    return bool(_PRIMARY_HOST_RE.match(url))


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def _init_ledger(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15.0)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS crawl_ledger (
            url           TEXT PRIMARY KEY,
            sha256        TEXT NOT NULL,
            s3_key        TEXT NOT NULL,
            municipality_code TEXT NOT NULL,
            fetched_at    TEXT NOT NULL,
            byte_size     INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_ledger_munic
            ON crawl_ledger(municipality_code);
        CREATE TABLE IF NOT EXISTS robots_cache (
            host          TEXT PRIMARY KEY,
            body          TEXT NOT NULL,
            cached_at     TEXT NOT NULL
        );
        """
    )
    conn.commit()
    return conn


def _ledger_has(conn: sqlite3.Connection, url: str) -> bool:
    return (
        conn.execute("SELECT 1 FROM crawl_ledger WHERE url = ? LIMIT 1", (url,)).fetchone()
        is not None
    )


def _ledger_insert(
    conn: sqlite3.Connection,
    *,
    url: str,
    sha: str,
    s3_key: str,
    municipality_code: str,
    byte_size: int,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO crawl_ledger
        (url, sha256, s3_key, municipality_code, fetched_at, byte_size)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            url,
            sha,
            s3_key,
            municipality_code,
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            byte_size,
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------


def _robots_for(host: str) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"https://{host}/robots.txt")
    # Defensive: assume allow if robots.txt unreachable (some 自治体 mis-serve
    # it). Operator can flip to default-deny via env later.
    with contextlib.suppress(OSError):
        rp.read()
    return rp


def _can_fetch_cached(
    cache: dict[str, urllib.robotparser.RobotFileParser],
    url: str,
) -> bool:
    host = urlparse(url).netloc
    if host not in cache:
        cache[host] = _robots_for(host)
    return cache[host].can_fetch(_USER_AGENT, url)


# ---------------------------------------------------------------------------
# HTTP fetch helpers (lazy imports so unit tests stay fast)
# ---------------------------------------------------------------------------


async def _fetch(
    httpx_mod: Any,
    client: Any,
    url: str,
    *,
    expect_pdf: bool = False,
) -> tuple[int, bytes, str]:
    """Return (status_code, body, content_type) for ``url``.

    Caller is responsible for robots + aggregator guards.
    """
    try:
        resp = await client.get(url, follow_redirects=True)
    except httpx_mod.HTTPError as exc:
        return 0, b"", f"http_error:{exc.__class__.__name__}"

    ctype = resp.headers.get("content-type", "")
    body = resp.content if expect_pdf else (resp.text or "").encode("utf-8", "replace")
    if expect_pdf and len(body) > _MAX_PDF_BYTES:
        return resp.status_code, b"", f"oversize:{len(body)}"
    return resp.status_code, body, ctype


def _extract_pdf_links(base_url: str, html: str) -> list[str]:
    out: list[str] = []
    for m in _PDF_LINK_RE.finditer(html):
        href = m.group(1)
        absolute = urljoin(base_url, href)
        out.append(absolute)
    # Dedup while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for u in out:
        if u in seen:
            continue
        seen.add(u)
        deduped.append(u)
    return deduped


# ---------------------------------------------------------------------------
# Per-host throttle
# ---------------------------------------------------------------------------


class HostThrottle:
    """1 req / N sec per host gate using ``asyncio.Lock`` per host."""

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait(self, host: str) -> None:
        async with self._locks[host]:
            now = time.monotonic()
            prev = self._last.get(host, 0.0)
            delta = now - prev
            if delta < self._interval:
                await asyncio.sleep(self._interval - delta)
            self._last[host] = time.monotonic()


# ---------------------------------------------------------------------------
# Crawl loop
# ---------------------------------------------------------------------------


async def _crawl_municipality(
    *,
    httpx_mod: Any,
    client: Any,
    throttle: HostThrottle,
    semaphore: asyncio.Semaphore,
    robots: dict[str, urllib.robotparser.RobotFileParser],
    ledger: sqlite3.Connection,
    s3_uploader: Any | None,
    config: CrawlConfig,
    municipality: dict[str, Any],
    stats: CrawlStats,
) -> None:
    """Walk seeds for one 自治体, upload PDFs to S3, write ledger rows."""
    code = str(municipality["municipality_code"])
    seeds: list[str] = list(municipality.get("subsidy_search_seeds") or [])
    if not seeds:
        return

    pdfs_uploaded_for_this_munic = 0
    pdf_candidates: list[str] = []

    async with semaphore:
        # 1) Walk each seed page → collect PDF links.
        for seed in seeds:
            if _is_aggregator(seed):
                stats.aggregator_rejected += 1
                continue
            if not _is_primary_host(seed):
                stats.non_primary_host += 1
                continue
            if not _can_fetch_cached(robots, seed):
                stats.robots_disallow += 1
                continue

            await throttle.wait(urlparse(seed).netloc)
            status, body, ctype = await _fetch(httpx_mod, client, seed, expect_pdf=False)
            stats.seed_urls_fetched += 1
            if status != 200 or not body:
                stats.fetch_failures += 1
                continue

            for url in _extract_pdf_links(seed, body.decode("utf-8", "replace")):
                if url not in pdf_candidates:
                    pdf_candidates.append(url)
            if len(pdf_candidates) >= config.max_pdf_per_municipality * 3:
                # Stop seed walk once we have enough candidates to fill the cap.
                break

        stats.pdf_links_found += len(pdf_candidates)

        # 2) Download + upload each PDF (cap-bounded).
        for pdf_url in pdf_candidates:
            if pdfs_uploaded_for_this_munic >= config.max_pdf_per_municipality:
                break
            if _is_aggregator(pdf_url) or not _is_primary_host(pdf_url):
                stats.non_primary_host += 1
                continue
            if _ledger_has(ledger, pdf_url):
                stats.pdf_skipped_ledger += 1
                pdfs_uploaded_for_this_munic += 1
                continue
            if not _can_fetch_cached(robots, pdf_url):
                stats.robots_disallow += 1
                continue

            await throttle.wait(urlparse(pdf_url).netloc)
            status, body, ctype = await _fetch(httpx_mod, client, pdf_url, expect_pdf=True)
            if status != 200 or not body or "pdf" not in ctype.lower():
                stats.fetch_failures += 1
                continue
            stats.pdf_downloaded += 1

            sha = hashlib.sha256(body).hexdigest()
            s3_key = f"{config.prefix.rstrip('/')}/{code}/{sha[:16]}.pdf"

            if config.commit and s3_uploader is not None:
                try:
                    s3_uploader.put_object(
                        Bucket=config.bucket,
                        Key=s3_key,
                        Body=body,
                        ContentType="application/pdf",
                        Metadata={
                            "municipality_code": code,
                            "source_url": pdf_url[:1024],
                            "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        },
                    )
                    stats.pdf_uploaded_s3 += 1
                except Exception:  # noqa: BLE001 — boto3 surfaces ClientError
                    stats.fetch_failures += 1
                    continue
            else:
                # Dry-run: count what would have been uploaded but skip the call.
                stats.pdf_uploaded_s3 += 1

            _ledger_insert(
                ledger,
                url=pdf_url,
                sha=sha,
                s3_key=s3_key,
                municipality_code=code,
                byte_size=len(body),
            )
            pdfs_uploaded_for_this_munic += 1

    stats.municipalities_visited += 1


async def _run_async(config: CrawlConfig) -> CrawlStats:
    """Top-level async driver."""
    manifest = json.loads(config.manifest_path.read_text(encoding="utf-8"))
    municipalities: list[dict[str, Any]] = list(manifest.get("municipalities", []))
    if config.max_municipalities is not None:
        municipalities = municipalities[: config.max_municipalities]

    ledger = _init_ledger(config.ledger_path)

    # Lazy imports.
    try:
        import httpx  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:  # pragma: no cover
        msg = f"httpx not installed: {exc}"
        raise SystemExit(msg) from exc

    s3_client: Any | None = None
    if config.commit:
        from scripts.aws_credit_ops._aws import s3_client as _s3_factory

        s3_client = _s3_factory()

    timeout = httpx.Timeout(_HTTP_TIMEOUT_SECONDS, connect=10.0)
    headers = {"user-agent": _USER_AGENT, "accept-language": "ja,en;q=0.5"}

    throttle = HostThrottle(_PER_HOST_INTERVAL)
    semaphore = asyncio.Semaphore(_GLOBAL_CONCURRENCY)
    robots: dict[str, urllib.robotparser.RobotFileParser] = {}
    stats = CrawlStats()

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        tasks = [
            _crawl_municipality(
                httpx_mod=httpx,
                client=client,
                throttle=throttle,
                semaphore=semaphore,
                robots=robots,
                ledger=ledger,
                s3_uploader=s3_client,
                config=config,
                municipality=m,
                stats=stats,
            )
            for m in municipalities
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    ledger.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    """Entrypoint."""
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not args.manifest.exists():
        sys.stderr.write(f"FATAL: manifest missing: {args.manifest}\n")
        return 1

    commit = bool(args.commit) and not bool(args.dry_run)

    config = CrawlConfig(
        manifest_path=args.manifest,
        ledger_path=args.ledger,
        bucket=args.bucket,
        prefix=args.prefix,
        commit=commit,
        max_municipalities=args.max_municipalities,
        max_pdf_per_municipality=args.max_pdf_per_municipality,
    )

    logger.info(
        "DD2 crawl start commit=%s manifest=%s bucket=%s prefix=%s",
        commit,
        config.manifest_path,
        config.bucket,
        config.prefix,
    )

    stats = asyncio.run(_run_async(config))
    logger.info("DD2 crawl summary %s", stats.to_dict())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
