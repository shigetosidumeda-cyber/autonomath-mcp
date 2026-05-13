#!/usr/bin/env python3
"""Wave 20 B22 — Cloudflare Pages parity verify across 3 jpcite domains.

Purpose
-------
jpcite is served on 3 hostnames:
    1. jpcite.com           — apex (canonical)
    2. www.jpcite.com       — www CNAME (SEO equivalence, 301 to apex)
    3. api.jpcite.com       — API hostname (Fly.io)

For SEO/GEO + agent discovery (.well-known, sitemap, robots.txt, llms.txt)
the **same resource** must be reachable on all 3 hosts. Drift between
hostnames silently degrades search engine and AI crawler discovery —
an agent that lands on www.jpcite.com/llms.txt and gets a 404 when
the apex serves 200 will silently de-rank the brand.

This script fans out a GET request to all 3 hostnames for a fixed
resource list and verifies:

  - HTTP status code parity (200 on all 3, or matching 301/302).
  - Content length within a 5% tolerance (rules out partial CDN edge
    caches serving stale slim versions).
  - Content-Type header consistency.

Resources under verify
----------------------
1. /llms.txt                    (LLM crawler discovery)
2. /llms-full.txt               (LLM crawler full corpus)
3. /sitemap.xml                 (search engine sitemap)
4. /sitemap-llms.xml            (LLM-specific sitemap)
5. /robots.txt                  (crawler policy)
6. /.well-known/mcp-server.json (MCP discovery)
7. /.well-known/ai-plugin.json  (OpenAI plugin discovery)
8. /.well-known/agents.json     (agent capability advertisement)
9. /.well-known/security.txt    (security contact)
10. /openapi.json               (REST API discovery)

Behavior
--------
- One GET per (host, path) combination = 30 HTTP requests per run.
- 10s timeout per request; no retries.
- Output: JSON snapshot to `site/status/cf_parity.json` + console summary.
- Cron-friendly: always exits 0; failure state encoded in JSON `overall`.

No LLM imports. Pure stdlib.

Usage
-----
    python scripts/ops/cf_parity_verify.py
    python scripts/ops/cf_parity_verify.py --out custom/path/parity.json
    python scripts/ops/cf_parity_verify.py --hosts jpcite.com,www.jpcite.com

Wave 22 — AI bot UA fanout mode
-------------------------------
    python scripts/ops/cf_parity_verify.py --ua-mode

In ``--ua-mode`` the script fans out every (host × path) probe across
the 17-entry ``AI_BOT_USER_AGENTS`` welcome list (GPTBot / ClaudeBot /
PerplexityBot / etc.). 3 hosts × 10 paths × 17 UAs = 510 HTTP calls per
run. Each UA must receive 200 (or the expected 3xx redirect) — any
403/429/4xx indicates a Cloudflare Bot Fight Mode or custom WAF rule
that is silently denying an AI agent. Snapshot is written to
``site/status/cf_parity_ua.json`` by default.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# JST tz for the snapshot timestamp.
JST = timezone(timedelta(hours=9), name="JST")

DEFAULT_HOSTS = [
    "jpcite.com",
    "www.jpcite.com",
    "api.jpcite.com",
]

# Per-host scheme override. All 3 default to https; allow override for
# local-dev (LOCAL_HTTP=1 → http for jpcite.com only).
HOST_SCHEME_OVERRIDE: dict[str, str] = {}

# Resources that MUST be present on all 3 hosts.
TARGET_PATHS = [
    "/llms.txt",
    "/llms-full.txt",
    "/sitemap.xml",
    "/sitemap-llms.xml",
    "/robots.txt",
    "/.well-known/mcp-server.json",
    "/.well-known/ai-plugin.json",
    "/.well-known/agents.json",
    "/.well-known/security.txt",
    "/openapi.json",
]

# Some resources legitimately differ between www vs apex vs api:
#   - api.jpcite.com serves /openapi.json natively, NOT a redirect.
#   - apex + www serve /openapi.json as a static fixture (may differ slightly).
# Encode these as expected differences so the parity gate does not flag
# them as drift. Format: {path: {host: 'accept'|'redirect'|'absent'}}.
EXPECTED_HOST_BEHAVIOR: dict[str, dict[str, str]] = {
    "/openapi.json": {
        "jpcite.com": "accept",
        "www.jpcite.com": "redirect",  # 301 to api.jpcite.com
        "api.jpcite.com": "accept",
    },
    "/.well-known/mcp-server.json": {
        "jpcite.com": "accept",
        "www.jpcite.com": "accept",
        "api.jpcite.com": "accept",
    },
}

# Status enum
STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_DOWN = "down"

PROBE_TIMEOUT = 10.0  # seconds

# Content-length tolerance — 5%. CDN edge variants can differ slightly
# (e.g. different ETag headers in HTML responses); 5% is loose enough
# for cache variation but tight enough to catch stale slim responses.
SIZE_TOLERANCE = 0.05

# Wave 22: AI bot UA welcome list. When `--ua-mode` is set, every probe
# fans out against this list (16 UAs × 3 hosts × N paths). Each UA must
# return 200 (or expected redirect) on every host/path combo.
AI_BOT_USER_AGENTS: list[tuple[str, str]] = [
    (
        "GPTBot",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.2; +https://openai.com/gptbot",
    ),
    (
        "ChatGPT-User",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot",
    ),
    (
        "ClaudeBot",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ClaudeBot/1.0; +https://www.anthropic.com/claude-bot",
    ),
    (
        "Claude-User",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; Claude-User/1.0; +https://www.anthropic.com/claude-user",
    ),
    ("anthropic-ai", "anthropic-ai/1.0"),
    ("Google-Extended", "Mozilla/5.0 (compatible; Google-Extended/1.0)"),
    ("Googlebot", "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"),
    (
        "PerplexityBot",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot",
    ),
    (
        "Meta-ExternalAgent",
        "meta-externalagent/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)",
    ),
    ("Twitterbot", "Twitterbot/1.0"),
    (
        "Amazonbot",
        "Mozilla/5.0 (compatible; Amazonbot/0.1; +https://developer.amazon.com/amazonbot)",
    ),
    ("MistralAI-User", "MistralAI-User/1.0"),
    ("DeepSeekBot", "Mozilla/5.0 (compatible; DeepSeekBot/1.0; +https://www.deepseek.com)"),
    (
        "Bytespider",
        "Mozilla/5.0 (Linux; Android 5.0) AppleWebKit/537.36 (KHTML, like Gecko); compatible; Bytespider; bytespider@bytedance.com",
    ),
    ("cohere-ai", "cohere-ai/1.0"),
    (
        "Applebot-Extended",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko); Applebot-Extended/0.1",
    ),
    (
        "Bingbot",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm",
    ),
]


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


def _http_head_or_get(
    url: str, user_agent: str | None = None
) -> tuple[int, int, str, str, str | None]:
    """One-shot HTTP GET. Returns (status, body_len, content_type, etag, error).

    We use GET rather than HEAD because Cloudflare's CDN sometimes
    serves HEAD differently from GET (different headers, sometimes
    different status codes when origin is misconfigured). GET is the
    real crawler signal.

    Wave 22: ``user_agent`` overrides the default UA. Used by the AI-bot
    UA-fanout mode so we can verify that an AI crawler's UA does not
    trigger Cloudflare Bot Fight Mode / custom WAF rules.
    """
    headers = {
        "User-Agent": user_agent or "jpcite-cf-parity-verify/1.0",
        "Accept": "*/*",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as r:
            body = r.read()
            ct = r.headers.get("Content-Type", "")
            etag = r.headers.get("ETag", "")
            return int(r.status), len(body), ct, etag, None
    except urllib.error.HTTPError as e:
        # Read body for length even on error so we can compare sizes.
        body = b""
        with contextlib.suppress(Exception):
            body = e.read() or b""
        ct = e.headers.get("Content-Type", "") if e.headers else ""
        return int(e.code), len(body), ct, "", f"HTTPError {e.code}"
    except Exception as e:
        return 0, 0, "", "", f"{type(e).__name__}: {str(e)[:120]}"


def _build_url(host: str, path: str) -> str:
    scheme = HOST_SCHEME_OVERRIDE.get(host, "https")
    return f"{scheme}://{host}{path}"


# ---------------------------------------------------------------------------
# Verify loop
# ---------------------------------------------------------------------------


def verify_path_across_hosts(path: str, hosts: list[str]) -> dict[str, Any]:
    """Probe `path` on each host. Returns drift analysis."""
    per_host: dict[str, Any] = {}
    for host in hosts:
        url = _build_url(host, path)
        t0 = time.monotonic()
        status, blen, ct, etag, err = _http_head_or_get(url)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        per_host[host] = {
            "url": url,
            "http_status": status,
            "body_len": blen,
            "content_type": ct,
            "etag": etag,
            "latency_ms": elapsed_ms,
            "error": err,
        }

    # Compute drift signals.
    expected = EXPECTED_HOST_BEHAVIOR.get(path, {})

    {h: per_host[h]["http_status"] for h in hosts}
    [per_host[h]["body_len"] for h in hosts if per_host[h]["body_len"] > 0]
    cts = {per_host[h]["content_type"] for h in hosts if per_host[h]["content_type"]}

    drift = []

    # Status parity, taking into account expected per-host behavior.
    for h in hosts:
        expected_behavior = expected.get(h, "accept")
        actual = per_host[h]["http_status"]
        if expected_behavior == "accept":
            if actual != 200:
                drift.append(f"{h}: expected 200, got {actual}")
        elif expected_behavior == "redirect":
            if actual not in (301, 302, 307, 308):
                drift.append(f"{h}: expected 3xx redirect, got {actual}")
        elif expected_behavior == "absent" and actual in (200,):
            drift.append(f"{h}: expected 404, got {actual}")

    # Size parity. Skip if any host returned non-200 — comparing 200 vs 404
    # body sizes is meaningless. Only enforce for the subset of hosts
    # that returned 200 AND are not configured as 'redirect'.
    sizes_for_compare = [
        per_host[h]["body_len"]
        for h in hosts
        if per_host[h]["http_status"] == 200
        and expected.get(h, "accept") != "redirect"
        and per_host[h]["body_len"] > 0
    ]
    if len(sizes_for_compare) >= 2:
        s_max = max(sizes_for_compare)
        s_min = min(sizes_for_compare)
        if s_max > 0:
            delta = (s_max - s_min) / s_max
            if delta > SIZE_TOLERANCE:
                drift.append(
                    f"size drift: {s_min}..{s_max} bytes ({delta:.1%} > {SIZE_TOLERANCE:.0%})"
                )

    # Content-Type drift (multiple distinct types = drift).
    # Strip charset parameter; only compare the major MIME type.
    bare_cts = {ct.split(";")[0].strip().lower() for ct in cts}
    if len(bare_cts) > 1:
        drift.append(f"content-type drift: {sorted(bare_cts)}")

    status = STATUS_OK if not drift else STATUS_DEGRADED

    return {
        "path": path,
        "per_host": per_host,
        "drift": drift,
        "status": status,
    }


def overall_status(per_path: list[dict[str, Any]]) -> str:
    if any(p["status"] == STATUS_DOWN for p in per_path):
        return STATUS_DOWN
    if any(p["status"] == STATUS_DEGRADED for p in per_path):
        return STATUS_DEGRADED
    return STATUS_OK


def build_snapshot(hosts: list[str], paths: list[str]) -> dict[str, Any]:
    per_path = [verify_path_across_hosts(p, hosts) for p in paths]
    return {
        "snapshot_at": datetime.now(JST).isoformat(timespec="seconds"),
        "hosts": hosts,
        "paths": paths,
        "per_path": per_path,
        "overall": overall_status(per_path),
    }


def verify_path_across_uas(
    path: str, hosts: list[str], user_agents: list[tuple[str, str]]
) -> dict[str, Any]:
    """Wave 22: Probe `path` on each host with each AI bot UA. Returns
    {ua_label: {host: probe_result}} drift analysis.

    Surface == ``hosts × user_agents`` total HTTP calls per path. Default
    UA welcome list has 17 UAs; 3 hosts × 17 UAs × 10 paths = 510 calls.
    """
    per_ua: dict[str, Any] = {}
    drift: list[str] = []
    for ua_label, ua_string in user_agents:
        per_host: dict[str, Any] = {}
        for host in hosts:
            url = _build_url(host, path)
            t0 = time.monotonic()
            status, blen, ct, etag, err = _http_head_or_get(url, user_agent=ua_string)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            per_host[host] = {
                "url": url,
                "user_agent": ua_label,
                "http_status": status,
                "body_len": blen,
                "content_type": ct,
                "etag": etag,
                "latency_ms": elapsed_ms,
                "error": err,
            }
            # AI bot must not be 403'd. Acceptable: 200 (welcome),
            # 301/302/307/308 (redirect to canonical host), 304 (cached).
            # Anything else (especially 403 / 429) is a bot-policy regression.
            expected_behavior = EXPECTED_HOST_BEHAVIOR.get(path, {}).get(host, "accept")
            if expected_behavior == "redirect":
                if status not in (301, 302, 307, 308):
                    drift.append(f"{ua_label}@{host}: expected 3xx redirect, got {status}")
            elif expected_behavior == "accept":
                if status not in (200, 304):
                    drift.append(f"{ua_label}@{host}: expected 200/304, got {status}")
            elif expected_behavior == "absent" and status == 200:
                drift.append(f"{ua_label}@{host}: expected absent, got 200")
        per_ua[ua_label] = per_host

    return {
        "path": path,
        "per_ua": per_ua,
        "drift": drift,
        "status": STATUS_OK if not drift else STATUS_DEGRADED,
    }


def build_ua_snapshot(
    hosts: list[str], paths: list[str], user_agents: list[tuple[str, str]]
) -> dict[str, Any]:
    """Wave 22: Top-level snapshot for AI-bot UA fanout mode."""
    per_path = [verify_path_across_uas(p, hosts, user_agents) for p in paths]
    return {
        "snapshot_at": datetime.now(JST).isoformat(timespec="seconds"),
        "mode": "ai_bot_ua_fanout",
        "hosts": hosts,
        "paths": paths,
        "user_agents": [ua[0] for ua in user_agents],
        "per_path": per_path,
        "overall": overall_status(per_path),
        "probe_count": len(hosts) * len(paths) * len(user_agents),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="jpcite Cloudflare Pages parity verify (3 hosts × 10 paths).",
    )
    p.add_argument(
        "--hosts",
        type=str,
        default=",".join(DEFAULT_HOSTS),
        help=f"Comma-separated hostnames (default: {','.join(DEFAULT_HOSTS)}).",
    )
    p.add_argument(
        "--paths",
        type=str,
        default=",".join(TARGET_PATHS),
        help=f"Comma-separated paths (default: {len(TARGET_PATHS)} pre-configured resources).",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("site/status/cf_parity.json"),
        help="Write JSON snapshot to this path.",
    )
    p.add_argument(
        "--pretty",
        action="store_true",
        help="Indent JSON output.",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress stdout summary.",
    )
    p.add_argument(
        "--ua-mode",
        action="store_true",
        help=(
            "Wave 22: AI-bot UA fanout mode. Probe every (host × path) "
            "combination with each UA in the AI_BOT_USER_AGENTS list. "
            "Output written to --ua-out (default site/status/cf_parity_ua.json)."
        ),
    )
    p.add_argument(
        "--ua-out",
        type=Path,
        default=Path("site/status/cf_parity_ua.json"),
        help="Output path for --ua-mode snapshot.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    hosts = [h.strip() for h in args.hosts.split(",") if h.strip()]
    paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    if not hosts or not paths:
        print("[cf_parity_verify] no hosts or paths to probe", file=sys.stderr)
        return 1

    if args.ua_mode:
        ua_snapshot = build_ua_snapshot(hosts, paths, AI_BOT_USER_AGENTS)
        args.ua_out.parent.mkdir(parents=True, exist_ok=True)
        args.ua_out.write_text(
            json.dumps(
                ua_snapshot, indent=2 if args.pretty else None, ensure_ascii=False, sort_keys=False
            )
            + "\n",
            encoding="utf-8",
        )
        if not args.quiet:
            n_probes = ua_snapshot["probe_count"]
            n_degraded = sum(1 for p in ua_snapshot["per_path"] if p["status"] != STATUS_OK)
            print(
                f"[cf_parity_verify] wrote {args.ua_out}: ua-mode "
                f"overall={ua_snapshot['overall']}, probes={n_probes}, "
                f"degraded_paths={n_degraded}"
            )
            if n_degraded:
                for p in ua_snapshot["per_path"]:
                    if p["status"] != STATUS_OK:
                        print(
                            f"  - {p['path']}: {'; '.join(p['drift'][:5])}"
                            + (" ..." if len(p["drift"]) > 5 else "")
                        )
        return 0

    snapshot = build_snapshot(hosts, paths)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(snapshot, indent=2 if args.pretty else None, ensure_ascii=False, sort_keys=False)
        + "\n",
        encoding="utf-8",
    )

    if not args.quiet:
        n_paths = len(snapshot["per_path"])
        n_degraded = sum(1 for p in snapshot["per_path"] if p["status"] != STATUS_OK)
        print(
            f"[cf_parity_verify] wrote {args.out}: overall={snapshot['overall']}, "
            f"paths={n_paths}, degraded={n_degraded}"
        )
        if n_degraded:
            for p in snapshot["per_path"]:
                if p["status"] != STATUS_OK:
                    print(f"  - {p['path']}: {'; '.join(p['drift'])}")
    # cron-friendly: always exit 0.
    return 0


if __name__ == "__main__":
    sys.exit(main())
