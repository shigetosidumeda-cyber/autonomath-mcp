#!/usr/bin/env python3
"""CF Pages full propagation audit for jpcite companion-Markdown surface.

Wave 41 Agent F — verify every URL in ``site/sitemap-companion-md.xml`` returns
HTTP 200 from the Cloudflare Pages edge. Emits a JSONL snapshot of any non-200
URLs so the next chunk-push wave can regenerate just the gap.

The audit walks the sitemap with a parallel ``httpx`` async client (default
concurrency 20, configurable via ``--concurrency``). HEAD is used first and
falls back to GET on 405 / 404, because CF Pages cache TTL on static
companion-Markdown assets sometimes serves a stale 404 for HEAD while GET
hits the origin and returns 200.

Usage
-----
    python scripts/ops/cf_pages_full_audit.py
    python scripts/ops/cf_pages_full_audit.py --concurrency 30 --limit 100
    python scripts/ops/cf_pages_full_audit.py --snapshot-only

Outputs
-------
    analytics/cf_pages_404_w41.jsonl   non-200 URL list (one JSON per line)
    analytics/cf_pages_audit_w41.json  rollup stats (latest run)

Memory references
-----------------
- feedback_no_priority_question : no "MVP / phase" framing.
- project_jpcite_2026_05_07_state : CF Pages is propagation-LIVE for the
  9,178-URL companion-md surface at jpcite.com.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
SITEMAP_PATH = REPO_ROOT / "site" / "sitemap-companion-md.xml"
ANALYTICS_DIR = REPO_ROOT / "analytics"
OUTPUT_404_PATH = ANALYTICS_DIR / "cf_pages_404_w41.jsonl"
ROLLUP_PATH = ANALYTICS_DIR / "cf_pages_audit_w41.json"

# CF Pages edge accepts HEAD on cached static, but a cache MISS on a non-existent
# .md returns 404 even when the upstream worker would return 200 on GET — so we
# probe both verbs and consider a URL "live" when EITHER returns 200.
_URL_RE = re.compile(r"<loc>([^<]+)</loc>")


def _extract_urls(text: str) -> list[str]:
    """Pull every <loc> URL from the sitemap XML body."""
    return _URL_RE.findall(text)


async def _probe_one(
    client: httpx.AsyncClient,
    url: str,
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    """Probe one URL with HEAD-then-GET fallback, return result dict."""
    async with sem:
        # First try HEAD — fastest, doesn't burn CF edge bandwidth on the body.
        head_status: int | str | None = None
        head_error: str | None = None
        try:
            r = await client.head(url, follow_redirects=True, timeout=10.0)
            head_status = r.status_code
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            head_error = type(exc).__name__
        # If HEAD says 200, we are done. Otherwise GET — some CDNs serve a
        # stale 404 on HEAD while the body fetch reaches origin and returns 200.
        if head_status == 200:
            return {"url": url, "status": 200, "verb": "HEAD"}
        get_status: int | str | None = None
        get_error: str | None = None
        try:
            r = await client.get(url, follow_redirects=True, timeout=15.0)
            get_status = r.status_code
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            get_error = type(exc).__name__
        if get_status == 200:
            return {"url": url, "status": 200, "verb": "GET"}
        return {
            "url": url,
            "status": get_status if get_status is not None else "error",
            "verb": "GET",
            "head_status": head_status,
            "head_error": head_error,
            "get_error": get_error,
        }


async def _run_audit(
    urls: list[str],
    concurrency: int,
    progress_every: int,
) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(
        max_keepalive_connections=concurrency,
        max_connections=concurrency * 2,
    )
    headers = {
        "User-Agent": "jpcite-cf-pages-audit/0.1 (+https://jpcite.com)",
        "Accept": "text/markdown,text/plain,*/*",
    }
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(limits=limits, headers=headers, http2=False) as client:
        tasks = [_probe_one(client, u, sem) for u in urls]
        done = 0
        for coro in asyncio.as_completed(tasks):
            res = await coro
            results.append(res)
            done += 1
            if progress_every > 0 and done % progress_every == 0:
                sys.stderr.write(f"  [{done}/{len(urls)}] probed\n")
                sys.stderr.flush()
    return results


def _classify(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up status distribution + sample 404 URLs."""
    by_status: Counter[Any] = Counter()
    bad: list[dict[str, Any]] = []
    for r in results:
        by_status[r["status"]] += 1
        if r["status"] != 200:
            bad.append(r)
    return {
        "total": len(results),
        "by_status": {str(k): v for k, v in by_status.most_common()},
        "ok": by_status.get(200, 0),
        "non_ok": sum(v for k, v in by_status.items() if k != 200),
        "bad": bad,
    }


def _emit_404_jsonl(bad: list[dict[str, Any]]) -> None:
    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_404_PATH.write_text(
        "\n".join(json.dumps(b, ensure_ascii=False, sort_keys=True) for b in bad)
        + ("\n" if bad else ""),
        encoding="utf-8",
    )


def _emit_rollup(rollup: dict[str, Any], generated_at: str) -> None:
    """Write the latest rollup snapshot (without the full bad list)."""
    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    safe = {k: v for k, v in rollup.items() if k != "bad"}
    safe["generated_at"] = generated_at
    safe["sample_404"] = [b["url"] for b in rollup["bad"][:50]]
    safe["wave"] = "wave41_agent_f"
    ROLLUP_PATH.write_text(
        json.dumps(safe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--sitemap",
        type=Path,
        default=SITEMAP_PATH,
        help="Path to sitemap-companion-md.xml (default: site/sitemap-companion-md.xml).",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=20,
        help="Parallel httpx workers (default 20).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap probes at this many URLs (0 = no cap).",
    )
    p.add_argument(
        "--progress-every",
        type=int,
        default=500,
        help="Emit progress every N probes (default 500).",
    )
    p.add_argument(
        "--snapshot-only",
        action="store_true",
        help="Print stats and write rollup but skip writing the 404 JSONL.",
    )
    args = p.parse_args(argv)

    sitemap_text = args.sitemap.read_text(encoding="utf-8")
    urls = _extract_urls(sitemap_text)
    if args.limit and args.limit > 0:
        urls = urls[: args.limit]
    if not urls:
        sys.stderr.write(f"[cf-pages-audit] no <loc> URLs in {args.sitemap}\n")
        return 2

    sys.stderr.write(
        f"[cf-pages-audit] probing {len(urls)} URLs (concurrency={args.concurrency})\n"
    )
    sys.stderr.flush()
    results = asyncio.run(_run_audit(urls, args.concurrency, args.progress_every))
    rollup = _classify(results)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not args.snapshot_only:
        _emit_404_jsonl(rollup["bad"])
    _emit_rollup(rollup, generated_at)

    print(
        f"[cf-pages-audit] total={rollup['total']} ok={rollup['ok']} "
        f"non_ok={rollup['non_ok']} 404_path={OUTPUT_404_PATH.relative_to(REPO_ROOT)} "
        f"rollup={ROLLUP_PATH.relative_to(REPO_ROOT)}"
    )
    for k, v in rollup["by_status"].items():
        print(f"  status={k:>6}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
