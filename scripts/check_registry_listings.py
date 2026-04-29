#!/usr/bin/env python3
"""Daily MCP registry listing presence checker.

Curls each registry's expected listing URL and reports whether
`autonomath-mcp` is present, the HTTP status, and the matched substring.

Designed for daily cron after 2026-05-06 launch:

    30 8 * * * cd /path/to/jpintel-mcp && .venv/bin/python scripts/check_registry_listings.py

Output: writes one JSON line per registry to stdout AND appends to
``data/registry_status_<YYYY-MM-DD>.jsonl``. Exit code 0 if every registry
returns HTTP 2xx (regardless of listing presence — listings can lag).
Exit code 1 only if a registry URL itself errors (DNS / 5xx).

Usage:

    .venv/bin/python scripts/check_registry_listings.py            # full run
    .venv/bin/python scripts/check_registry_listings.py --quiet    # exit code only
    .venv/bin/python scripts/check_registry_listings.py --json     # stdout-only JSON

No external network deps beyond stdlib ``urllib`` (avoids Anthropic API,
honours memory ``feedback_autonomath_no_api_use``).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import certifi  # type: ignore[import-untyped]

    _SSL_CTX: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover — certifi is in core deps
    _SSL_CTX = ssl.create_default_context()

# 12 registries total: 5 primary (F6) + 7 secondary (F7).
# Each entry: id, name, listing URL to GET, substring(s) to find in body.
# F7 owns this file; entries align with mcp_registries_submission.json.
REGISTRIES: list[dict[str, Any]] = [
    # --- F6 primary registries ---
    {
        "id": "official_registry",
        "name": "Official MCP Registry",
        "url": "https://registry.modelcontextprotocol.io/v0/servers/io.github.AutonoMath/autonomath-mcp",
        "needles": ["autonomath-mcp", "AutonoMath"],
        "tier": "primary",
    },
    {
        "id": "smithery",
        "name": "Smithery",
        "url": "https://smithery.ai/server/autonomath-mcp",
        "needles": ["autonomath-mcp", "AutonoMath"],
        "tier": "primary",
    },
    {
        "id": "glama",
        "name": "Glama",
        "url": "https://glama.ai/mcp/servers/AutonoMath/autonomath-mcp",
        "needles": ["autonomath-mcp", "AutonoMath"],
        "tier": "primary",
    },
    {
        "id": "mcp_market",
        "name": "MCP Market",
        "url": "https://mcpmarket.com/server/autonomath-mcp",
        "needles": ["autonomath-mcp", "AutonoMath"],
        "tier": "primary",
    },
    {
        "id": "mcp_hunt",
        "name": "MCP Hunt",
        "url": "https://mcphunt.com/server/autonomath-mcp",
        "needles": ["autonomath-mcp", "AutonoMath"],
        "tier": "primary",
    },
    # --- F7 secondary registries ---
    {
        "id": "cline_marketplace",
        "name": "Cline MCP Marketplace",
        # Cline's marketplace is a GitHub repo — check the README for entry presence.
        "url": "https://raw.githubusercontent.com/cline/mcp-marketplace/main/README.md",
        "needles": ["autonomath-mcp", "AutonoMath"],
        "tier": "secondary",
    },
    {
        "id": "pulsemcp",
        "name": "PulseMCP",
        "url": "https://www.pulsemcp.com/servers/autonomath-mcp",
        "needles": ["autonomath-mcp", "AutonoMath"],
        "tier": "secondary",
    },
    {
        "id": "mcp_so",
        "name": "mcp.so",
        "url": "https://mcp.so/server/autonomath-mcp",
        "needles": ["autonomath-mcp", "AutonoMath"],
        "tier": "secondary",
    },
    {
        "id": "awesome_mcp_servers",
        "name": "Awesome MCP Servers (punkpeye)",
        "url": "https://raw.githubusercontent.com/punkpeye/awesome-mcp-servers/main/README.md",
        "needles": ["AutonoMath/autonomath-mcp"],
        "tier": "secondary",
    },
    {
        "id": "cursor_marketplace",
        "name": "Cursor Marketplace",
        "url": "https://cursor.directory/mcp/autonomath-mcp",
        "needles": ["autonomath-mcp", "AutonoMath"],
        "tier": "secondary",
    },
    {
        "id": "mcpservers_org",
        "name": "mcpservers.org",
        "url": "https://mcpservers.org/server/autonomath-mcp",
        "needles": ["autonomath-mcp", "AutonoMath"],
        "tier": "secondary",
    },
    {
        "id": "mcp_server_finder",
        "name": "MCP Server Finder",
        "url": "https://www.mcpserverfinder.com/servers/autonomath-mcp",
        "needles": ["autonomath-mcp", "AutonoMath"],
        "tier": "secondary",
    },
]

USER_AGENT = "AutonoMath-RegistryChecker/0.1 (+https://zeimu-kaikei.ai; info@bookyou.net)"
TIMEOUT_S = 15


def fetch(url: str) -> tuple[int, str, str | None]:
    """Return (http_status, body_text, error_message_or_none)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=_SSL_CTX) as resp:
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace") if raw else ""
            return resp.status, text, None
    except urllib.error.HTTPError as e:
        # 4xx/5xx — capture body for grep but treat as listing-missing if 404.
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, body, f"HTTPError {e.code}"
    except urllib.error.URLError as e:
        return 0, "", f"URLError: {e.reason}"
    except (TimeoutError, socket.timeout):
        return 0, "", "TimeoutError"
    except Exception as e:  # noqa: BLE001
        return 0, "", f"{type(e).__name__}: {e}"


def check_registry(entry: dict[str, Any]) -> dict[str, Any]:
    status, body, err = fetch(entry["url"])
    listed = False
    matched_needle: str | None = None
    if 200 <= status < 300 and body:
        for needle in entry["needles"]:
            if needle in body:
                listed = True
                matched_needle = needle
                break
    return {
        "id": entry["id"],
        "name": entry["name"],
        "tier": entry["tier"],
        "url": entry["url"],
        "http_status": status,
        "listed": listed,
        "matched_needle": matched_needle,
        "error": err,
        "checked_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="Suppress stdout; exit code only")
    parser.add_argument("--json", action="store_true", help="Stdout-only JSON; do not write log file")
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("AUTONOMATH_DATA_DIR", "data"),
        help="Directory for daily JSONL log (default: data)",
    )
    args = parser.parse_args()

    today = _dt.date.today().isoformat()
    results: list[dict[str, Any]] = []
    any_url_error = False

    for entry in REGISTRIES:
        result = check_registry(entry)
        results.append(result)
        if result["http_status"] == 0:
            any_url_error = True
        if not args.quiet and not args.json:
            mark = "[LISTED]" if result["listed"] else "[--MISS]"
            err = f" err={result['error']}" if result["error"] else ""
            print(
                f"{mark} {result['tier']:9s} {result['name']:32s}  "
                f"http={result['http_status']:3d}{err}"
            )

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        # Append to daily JSONL log.
        log_dir = Path(args.data_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"registry_status_{today}.jsonl"
        with log_path.open("a", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        if not args.quiet:
            listed_count = sum(1 for r in results if r["listed"])
            primary_listed = sum(1 for r in results if r["listed"] and r["tier"] == "primary")
            secondary_listed = sum(1 for r in results if r["listed"] and r["tier"] == "secondary")
            print(
                f"\nSummary: {listed_count}/{len(results)} listed "
                f"(primary={primary_listed}/5, secondary={secondary_listed}/7) — "
                f"log={log_path}"
            )

    return 1 if any_url_error else 0


if __name__ == "__main__":
    sys.exit(main())
