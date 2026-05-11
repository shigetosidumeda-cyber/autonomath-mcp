#!/usr/bin/env python3
# ruff: noqa: E501
"""5 component status probe for jpcite. LLM API 呼出ゼロ、pure stdlib + requests (sync).

Probes 5 production surfaces (api / mcp / billing / data-freshness / dashboard) and emits
a JSON snapshot to stdout. Pipeable; --pretty for indent=2.

Overall verdict:
  - all 5 ok       → "ok"
  - any "n/a"      → "degraded"
  - any "down"     → "down"

Constraints: requests + urllib + datetime + json only. timeout=10s/component, no retry.
LLM API imports forbidden (memory: feedback_no_operator_llm_api).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    import requests  # type: ignore[import-untyped]

    HAVE_REQUESTS = True
except ImportError:
    HAVE_REQUESTS = False

JST = timezone(timedelta(hours=9), name="JST")
TIMEOUT_S = 10
MCP_EXPECTED_EMAIL = "info@bookyou.net"
MCP_TOOLS_COHORT = 139  # SOT: CLAUDE.md manifest hold-at-139
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
FRESH_DAYS = 7

API_BASE = "https://api.jpcite.com"
SITE_BASE = "https://jpcite.com"


def _fetch(url: str) -> tuple[int | None, str | None, int | None]:
    """Return (http_status, body_text, latency_ms). On network failure → (None, None, latency)."""
    t0 = time.monotonic()
    try:
        if HAVE_REQUESTS:
            resp = requests.get(url, timeout=TIMEOUT_S, allow_redirects=True)
            latency_ms = int((time.monotonic() - t0) * 1000)
            return resp.status_code, resp.text, latency_ms
        req = urllib.request.Request(url, headers={"User-Agent": "jpcite-status-probe/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            body = r.read().decode("utf-8", errors="replace")
            latency_ms = int((time.monotonic() - t0) * 1000)
            return r.status, body, latency_ms
    except urllib.error.HTTPError as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = None
        return e.code, body, latency_ms
    except Exception:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return None, None, latency_ms


def probe_api() -> dict:
    """GET https://api.jpcite.com/healthz → 200 + JSON status="ok"."""
    http, body, latency = _fetch(f"{API_BASE}/healthz")
    if http != 200 or body is None:
        return {"status": "down", "latency_ms": latency, "http": http}
    try:
        data = json.loads(body)
        if data.get("status") == "ok":
            return {"status": "ok", "latency_ms": latency, "http": 200}
        return {"status": "down", "latency_ms": latency, "http": 200, "reason": "status!=ok"}
    except (json.JSONDecodeError, ValueError):
        return {"status": "down", "latency_ms": latency, "http": 200, "reason": "non_json"}


def probe_mcp() -> dict:
    """GET https://jpcite.com/.well-known/mcp.json → 200 + .contact.email + tools cohort."""
    http, body, latency = _fetch(f"{SITE_BASE}/.well-known/mcp.json")
    if http != 200 or body is None:
        return {"status": "down", "latency_ms": latency, "http": http}
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return {"status": "down", "latency_ms": latency, "http": 200, "reason": "non_json"}
    contact_email = (data.get("contact") or {}).get("email")
    if contact_email != MCP_EXPECTED_EMAIL:
        return {
            "status": "down",
            "latency_ms": latency,
            "http": 200,
            "reason": f"contact.email={contact_email!r} expected={MCP_EXPECTED_EMAIL!r}",
        }
    tools = data.get("tools")
    tools_count = len(tools) if isinstance(tools, list) else None
    if tools_count != MCP_TOOLS_COHORT:
        return {
            "status": "down",
            "latency_ms": latency,
            "http": 200,
            "reason": f"tools={tools_count} expected={MCP_TOOLS_COHORT}",
            "tools_count": tools_count,
        }
    return {
        "status": "ok",
        "latency_ms": latency,
        "http": 200,
        "tools_count": tools_count,
    }


def probe_billing() -> dict:
    """GET https://api.jpcite.com/v1/billing/healthz → 200 (404 → n/a degraded)."""
    http, _body, latency = _fetch(f"{API_BASE}/v1/billing/healthz")
    if http == 200:
        return {"status": "ok", "latency_ms": latency, "http": 200}
    if http == 404:
        return {"status": "n/a", "latency_ms": None, "http": 404}
    return {"status": "down", "latency_ms": latency, "http": http}


def probe_data_freshness() -> dict:
    """GET https://jpcite.com/data-freshness → 200 + regex YYYY-MM-DD → 7 日以内 ok."""
    http, body, latency = _fetch(f"{SITE_BASE}/data-freshness")
    if http != 200 or body is None:
        return {"status": "down", "latency_ms": latency, "http": http}
    matches = DATE_RE.findall(body)
    if not matches:
        return {
            "status": "down",
            "latency_ms": latency,
            "http": 200,
            "reason": "no_date_found",
        }
    dates: list[datetime] = []
    for y, m, d in matches:
        try:
            dates.append(datetime(int(y), int(m), int(d), tzinfo=JST))
        except ValueError:
            continue
    if not dates:
        return {
            "status": "down",
            "latency_ms": latency,
            "http": 200,
            "reason": "no_parseable_date",
        }
    last_updated = max(dates)
    now = datetime.now(JST)
    age_days = (now - last_updated).days
    last_str = last_updated.strftime("%Y-%m-%d")
    if age_days <= FRESH_DAYS:
        return {
            "status": "ok",
            "latency_ms": latency,
            "http": 200,
            "last_updated": last_str,
        }
    return {
        "status": "down",
        "latency_ms": latency,
        "http": 200,
        "last_updated": last_str,
        "reason": f"stale_{age_days}d",
    }


def probe_dashboard() -> dict:
    """GET https://jpcite.com/dashboard.html → 200 + id="billing" anchor."""
    http, body, latency = _fetch(f"{SITE_BASE}/dashboard.html")
    if http != 200 or body is None:
        return {"status": "down", "latency_ms": latency, "http": http}
    if 'id="billing"' in body or "id='billing'" in body:
        return {"status": "ok", "latency_ms": latency, "http": 200}
    return {
        "status": "down",
        "latency_ms": latency,
        "http": 200,
        "reason": "no_billing_anchor",
    }


def compute_overall(components: dict[str, dict]) -> str:
    """all ok → ok / 1+ n/a → degraded / 1+ down → down (down ranks worse than degraded)."""
    statuses = [c.get("status") for c in components.values()]
    if "down" in statuses:
        return "down"
    if "n/a" in statuses:
        return "degraded"
    return "ok"


def build_snapshot() -> dict:
    components = {
        "api": probe_api(),
        "mcp": probe_mcp(),
        "billing": probe_billing(),
        "data-freshness": probe_data_freshness(),
        "dashboard": probe_dashboard(),
    }
    return {
        "snapshot_at": datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "components": components,
        "overall": compute_overall(components),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="jpcite 5-component status probe (api/mcp/billing/data-freshness/dashboard)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="indent JSON with 2-space indent (default: single-line, pipeable)",
    )
    args = parser.parse_args(argv)

    snapshot = build_snapshot()
    if args.pretty:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(snapshot, ensure_ascii=False))
    return 0 if snapshot["overall"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
