#!/usr/bin/env python3
"""IndexNow protocol cron — push fresh URLs to Bing / Yandex / Naver.

Runs after each sitemap regeneration (post-deploy hook + nightly cron via
.github/workflows/index-now-cron.yml). Diffs the current sitemap shards
against the previous run's URL snapshot, then POSTs new URLs to
api.indexnow.org/indexnow in batches of up to 10,000 URLs per call
(IndexNow spec hard cap).

Idempotent: every successful submission is appended to
analytics/indexnow_log.jsonl with a SHA256 of the URL list and the API
response status. Re-running on an unchanged sitemap is a no-op (log line
"no new urls, skipping").

Honesty constraints
-------------------
* Only submit URLs that are present in our own sitemap shards. Never
  invent URLs (e.g. don't speculatively submit a /qa/<slug> that has
  not been generated yet).
* On API failure, log the response body and exit 0. Never crash the
  cron — a transient 503 from IndexNow must not break the GitHub Actions
  workflow that triggers it.
* Skip submission if INDEXNOW_KEY is unset (dev / preview environments).

Usage
-----
    python scripts/cron/index_now_ping.py                # nightly cron mode
    python scripts/cron/index_now_ping.py --dry-run      # plan only, no POST
    python scripts/cron/index_now_ping.py --force        # ignore prev snapshot, push all
    python scripts/cron/index_now_ping.py --limit 100    # cap submission batch size
    python scripts/cron/index_now_ping.py --site site --domain jpcite.com

Required env (production cron)
------------------------------
    INDEXNOW_KEY    32+ char URL-safe token. Must match site/<KEY>.txt.
    INDEXNOW_HOST   Domain without scheme. Default: jpcite.com.

Exit codes
----------
0 success (possibly with "no urls to submit" log)
1 fatal (sitemap directory missing, malformed XML, etc)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

LOG = logging.getLogger("index_now_ping")

REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from jpintel_mcp.observability import heartbeat  # noqa: E402

DEFAULT_SITE_DIR = REPO_ROOT / "site"
DEFAULT_ANALYTICS_DIR = REPO_ROOT / "analytics"
DEFAULT_DOMAIN = "jpcite.com"

# Sitemap shards we ping IndexNow for. We deliberately exclude
# sitemap-structured.xml (10k+ JSON-LD shards that aren't user-facing
# pages — IndexNow is for HTML).
SHARD_BASENAMES = (
    "sitemap.xml",
    "sitemap-programs.xml",
    "sitemap-prefectures.xml",
    "sitemap-audiences.xml",
    "sitemap-industries.xml",
    "sitemap-qa.xml",
    "sitemap-pages.xml",
)

# IndexNow spec: batch up to 10,000 URLs per POST.
# https://www.indexnow.org/documentation
BATCH_LIMIT = 10_000

INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
USER_AGENT = "jpcite.com-indexnow-cron/1.0 (+https://jpcite.com)"
HTTP_TIMEOUT = 30.0

# Sitemap XML namespace per sitemaps.org spec.
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _setup_logging() -> None:
    """Structured JSON-friendly stderr logging (matches other cron scripts)."""
    logging.basicConfig(
        level=os.environ.get("JPINTEL_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_sitemap(path: Path) -> list[str]:
    """Return list of <loc> values from a sitemap shard (XML, deterministic order).

    Returns [] on parse error (so a malformed shard doesn't crash all the others).
    """
    if not path.exists():
        LOG.warning("shard missing: %s", path.name)
        return []
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        LOG.error("shard parse error: %s — %s", path.name, exc)
        return []
    root = tree.getroot()
    locs: list[str] = []
    for url_el in root.findall("sm:url", NS):
        loc_el = url_el.find("sm:loc", NS)
        if loc_el is not None and loc_el.text:
            locs.append(loc_el.text.strip())
    return locs


def collect_urls(site_dir: Path) -> list[str]:
    """Walk all known sitemap shards, return unique URL list (sorted)."""
    seen: set[str] = set()
    for name in SHARD_BASENAMES:
        for u in parse_sitemap(site_dir / name):
            seen.add(u)
    return sorted(seen)


def load_previous_snapshot(snapshot_path: Path) -> set[str]:
    """Return the URL set from the previous run, or empty set if first run."""
    if not snapshot_path.exists():
        return set()
    try:
        return set(json.loads(snapshot_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        LOG.warning("snapshot read failed (treating as cold start): %s", exc)
        return set()


def save_snapshot(snapshot_path: Path, urls: list[str]) -> None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(urls, ensure_ascii=False, indent=0),
        encoding="utf-8",
    )


def submit_indexnow(
    urls: list[str],
    *,
    key: str,
    host: str,
    dry_run: bool,
) -> tuple[int, str]:
    """POST one batch of URLs to IndexNow. Returns (status_code, body_excerpt).

    On dry-run, returns (0, "dry-run") without HTTP I/O.
    """
    if dry_run:
        return 0, "dry-run"

    payload = {
        "host": host,
        "key": key,
        "keyLocation": f"https://{host}/{key}.txt",
        "urlList": urls,
    }
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": USER_AGENT,
    }
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = client.post(INDEXNOW_ENDPOINT, json=payload, headers=headers)
        body = resp.text[:200]
        # IndexNow spec: 200 = accepted, 202 = accepted async,
        # 400 = bad request, 403 = key/file mismatch, 422 = wrong host,
        # 429 = rate limited.
        return resp.status_code, body
    except httpx.HTTPError as exc:
        LOG.warning("indexnow POST failed: %s", exc)
        return -1, f"http_error: {exc!s}"


def append_log(
    log_path: Path,
    *,
    submitted_urls: list[str],
    status: int,
    body: str,
    dry_run: bool,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(
        ("\n".join(sorted(submitted_urls))).encode("utf-8"),
    ).hexdigest()
    row = {
        "ts": _utc_now_iso(),
        "count": len(submitted_urls),
        "sha256": digest,
        "status": status,
        "response": body,
        "dry_run": dry_run,
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--site",
        type=Path,
        default=DEFAULT_SITE_DIR,
        help="Site dir containing sitemap-*.xml shards.",
    )
    p.add_argument(
        "--analytics",
        type=Path,
        default=DEFAULT_ANALYTICS_DIR,
        help="Analytics dir for indexnow_log.jsonl + indexnow_snapshot.json.",
    )
    p.add_argument(
        "--domain",
        default=os.environ.get("INDEXNOW_HOST", DEFAULT_DOMAIN),
        help="Domain without scheme (default: env INDEXNOW_HOST or jpcite.com).",
    )
    p.add_argument(
        "--key",
        default=os.environ.get("INDEXNOW_KEY"),
        help="IndexNow key (default: env INDEXNOW_KEY).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=BATCH_LIMIT,
        help=f"Per-batch URL cap (default {BATCH_LIMIT}, IndexNow hard max).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Submit ALL urls, ignoring the previous snapshot diff.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan + log, but do not POST to IndexNow.",
    )
    return p.parse_args()


def main() -> int:
    _setup_logging()
    args = _parse_args()

    with heartbeat("index_now_ping") as hb:
        site_dir: Path = args.site
        if not site_dir.is_dir():
            LOG.error("site dir missing: %s", site_dir)
            hb["metadata"] = {"error": "site_dir_missing", "path": str(site_dir)}
            return 1

        snapshot_path = args.analytics / "indexnow_snapshot.json"
        log_path = args.analytics / "indexnow_log.jsonl"

        current = collect_urls(site_dir)
        LOG.info(
            "collected %d total urls from %d shards", len(current), len(SHARD_BASENAMES)
        )

        if args.force:
            new_urls = current
        else:
            prev = load_previous_snapshot(snapshot_path)
            new_urls = sorted(set(current) - prev)

        if not new_urls:
            LOG.info("no new urls, skipping IndexNow submission")
            # Still bump snapshot so timestamps are useful.
            save_snapshot(snapshot_path, current)
            hb["rows_processed"] = 0
            hb["rows_skipped"] = len(current)
            hb["metadata"] = {"reason": "no_new_urls", "total_urls": len(current)}
            return 0

        if not args.key and not args.dry_run:
            LOG.warning(
                "INDEXNOW_KEY unset — skipping submission (dev/preview env). "
                "Snapshot still recorded.",
            )
            save_snapshot(snapshot_path, current)
            hb["rows_skipped"] = len(new_urls)
            hb["metadata"] = {"reason": "key_unset", "new_urls": len(new_urls)}
            return 0

        LOG.info(
            "submitting %d new urls in %d batch(es) of up to %d",
            len(new_urls),
            (len(new_urls) + args.limit - 1) // args.limit,
            args.limit,
        )

        total_ok = 0
        for batch_idx, batch in enumerate(chunked(new_urls, args.limit), start=1):
            status, body = submit_indexnow(
                batch,
                key=args.key or "",
                host=args.domain,
                dry_run=args.dry_run,
            )
            ok = status in (0, 200, 202)
            LOG.info(
                "batch %d: status=%s urls=%d body=%r",
                batch_idx,
                status,
                len(batch),
                body[:120],
            )
            append_log(
                log_path,
                submitted_urls=batch,
                status=status,
                body=body,
                dry_run=args.dry_run,
            )
            if ok:
                total_ok += len(batch)

        LOG.info("submitted %d/%d urls successfully", total_ok, len(new_urls))

        # Snapshot last so a failed run can retry on next invocation.
        if total_ok > 0 or args.dry_run:
            save_snapshot(snapshot_path, current)

        hb["rows_processed"] = int(total_ok)
        hb["rows_skipped"] = int(len(new_urls) - total_ok)
        hb["metadata"] = {
            "total_urls": len(current),
            "new_urls": len(new_urls),
            "domain": args.domain,
            "dry_run": bool(args.dry_run),
        }
    return 0


if __name__ == "__main__":
    sys.exit(main())
