#!/usr/bin/env python3
"""5 component real health probe for the jpcite status page.

Outputs:
  * JSON snapshot at site/status/status.json (or `--out PATH`)
  * Optional shields.io-style SVG badge at site/status/badge.svg (or `--badge-out PATH`)

5 components:
  - api             GET /healthz + /v1/am/health/deep (latency_ms + JSON valid)
  - mcp             GET /v1/mcp-server.json + tools 139 + recurring_agent_workflows verify
  - billing         Stripe events.list(invoice.payment_failed, 24h) → 5xx rate
  - data-freshness  4 dataset MAX age (programs / am_amendment_diff /
                    invoice_registrants / case_studies) vs SLA (24h/7d/30d/30d)
  - dashboard       GET /dashboard.html + #billing anchor + magic-link
                    /v1/me/login_request verify rate (24h)

Constraints:
  * NO LLM API imports (anthropic / openai / google.generativeai) — CI guard.
  * Pure stdlib + Stripe SDK (Stripe SDK is operator infrastructure, not LLM).
  * Per-component 10s timeout; no retries.
  * Always exits 0 (cron-friendly). Failure state is encoded in JSON status field.

JSON spec (1.0):
  {
    "snapshot_at": "2026-05-11T...+09:00",
    "components": {
      "api": {"status": "ok|degraded|down", "latency_ms": int, "http": int},
      ...
    },
    "overall": "ok|degraded|down"
  }

CLI:
  --pretty           indent JSON output (default compact stdout, pretty file)
  --out PATH         write JSON to PATH (default site/status/status.json)
  --badge-out PATH   write shields.io-style SVG to PATH
  --stdout           also write JSON to stdout
  --base-url URL     override JPCITE_API_BASE (default https://api.jpcite.com)
  --site-url URL     override site origin (default https://jpcite.com)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Component identifiers (stable JSON keys; do not reorder lightly — the
# status page template enumerates these in render order).
COMPONENT_IDS = ["api", "mcp", "billing", "data-freshness", "dashboard"]

# Status ladder. Order matters for `overall` rollup (down > degraded > ok).
STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_DOWN = "down"

# Defaults; overridable via CLI / env.
DEFAULT_API_BASE = "https://api.jpcite.com"
DEFAULT_SITE_BASE = "https://jpcite.com"

# JST (+09:00) — the status page is consumed by JP operators; emit ISO 8601
# with explicit offset rather than naive Z so dashboards never localize wrong.
JST = timezone(timedelta(hours=9), name="JST")

# Per-component HTTP timeout (seconds). Hard-capped so a single sick
# component cannot stall the whole snapshot beyond ~50s wall-clock.
PROBE_TIMEOUT = 10.0

# Dataset SLA windows (seconds). Used by probe_data_freshness.
# Tight = operator-visible breach. Loose = informational.
SLA_PROGRAMS = 86_400          # 1d   — programs.updated_at
SLA_AMENDMENT_DIFF = 7 * 86_400  # 7d  — am_amendment_diff.detected_at (cron)
SLA_INVOICE_REGS = 30 * 86_400   # 30d — invoice_registrants.fetched_at (monthly bulk)
SLA_CASE_STUDIES = 30 * 86_400   # 30d — case_studies.fetched_at

# Expected runtime cohort. 139 = current default-gate manifest figure
# (`mcp-server.json` tool_count). Probe degrades if drift > 5 either way.
EXPECTED_TOOL_COUNT = 139
TOOL_COUNT_TOLERANCE = 5

# Expected recurring agent workflows count (advertised in mcp-server.json
# extension surface). 3 today (digest / saved-search / quarterly).
EXPECTED_RECURRING_WORKFLOWS = 3


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


def _http_get(url: str, *, accept_json: bool = False) -> tuple[int, int, bytes, str | None]:
    """One-shot HTTP GET with hard timeout.

    Returns (http_status, latency_ms, body_bytes, error_str). On failure
    http_status=0, body=b"", and error_str is populated. Latency is wall
    clock; not retried.
    """
    headers = {"User-Agent": "jpcite-status-probe/1.0"}
    if accept_json:
        headers["Accept"] = "application/json"
    req = urllib.request.Request(url, headers=headers)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as r:
            body = r.read()
            latency_ms = int((time.monotonic() - t0) * 1000)
            return int(r.status), latency_ms, body, None
    except urllib.error.HTTPError as e:
        # HTTPError carries an HTTP status — preserve it so the probe can
        # distinguish a 5xx (service degraded) from a network failure.
        body = b""
        with contextlib.suppress(Exception):
            body = e.read() or b""
        latency_ms = int((time.monotonic() - t0) * 1000)
        return int(e.code), latency_ms, body, f"HTTPError {e.code}"
    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return 0, latency_ms, b"", f"{type(e).__name__}: {str(e)[:160]}"


# ---------------------------------------------------------------------------
# Component probes
# ---------------------------------------------------------------------------


def probe_api(base: str) -> dict[str, Any]:
    """Probe `/healthz` + `/v1/am/health/deep` (JSON valid).

    `/healthz` carries the cheap liveness signal (uvicorn up). The deep
    health gate validates the autonomath stack — JSON parse failure or
    non-200 demotes status. Reports the worst of the two for `status`,
    and latency from the deep probe (more representative).
    """
    healthz_url = f"{base.rstrip('/')}/healthz"
    deep_url = f"{base.rstrip('/')}/v1/am/health/deep"

    h_code, _h_lat, _h_body, h_err = _http_get(healthz_url)
    d_code, d_lat, d_body, d_err = _http_get(deep_url, accept_json=True)

    deep_json_valid = False
    if d_code == 200 and d_body:
        try:
            json.loads(d_body)
            deep_json_valid = True
        except Exception:
            deep_json_valid = False

    if h_code == 200 and d_code == 200 and deep_json_valid and d_lat < 1500:
        status = STATUS_OK
    elif h_code == 200 and (d_code != 200 or not deep_json_valid or d_lat >= 1500):
        status = STATUS_DEGRADED
    elif h_code == 200 and d_code == 200:
        status = STATUS_OK
    elif h_code != 200 and d_code != 200:
        status = STATUS_DOWN
    else:
        status = STATUS_DEGRADED

    return {
        "status": status,
        "latency_ms": int(d_lat),
        "http": int(d_code or h_code or 0),
        "healthz_http": int(h_code or 0),
        "deep_http": int(d_code or 0),
        "deep_json_valid": deep_json_valid,
        "error": h_err or d_err,
    }


def probe_mcp(base: str) -> dict[str, Any]:
    """Probe `/v1/mcp-server.json` (manifest reachability + 139 tools).

    Also verifies the `recurring_agent_workflows` extension surface
    advertises ≥3 entries (digest / saved-search / quarterly). Drift in
    the tool count is tolerated within ±5; outside that band → degraded.
    """
    url = f"{base.rstrip('/')}/v1/mcp-server.json"
    code, latency, body, err = _http_get(url, accept_json=True)

    if code != 200 or not body:
        return {
            "status": STATUS_DOWN,
            "latency_ms": int(latency),
            "http": int(code or 0),
            "tools_count": None,
            "recurring_workflows": None,
            "error": err or f"HTTP {code}",
        }

    try:
        manifest = json.loads(body)
    except Exception as e:
        return {
            "status": STATUS_DEGRADED,
            "latency_ms": int(latency),
            "http": int(code),
            "tools_count": None,
            "recurring_workflows": None,
            "error": f"manifest json parse: {str(e)[:120]}",
        }

    tools = manifest.get("tools") or []
    tools_count = len(tools) if isinstance(tools, list) else None

    # `recurring_agent_workflows` lives under the `x-` / `extensions` /
    # top-level surface depending on registry — accept any of the three.
    recurring = (
        manifest.get("recurring_agent_workflows")
        or (manifest.get("extensions") or {}).get("recurring_agent_workflows")
        or (manifest.get("x-recurring-agent-workflows"))
        or []
    )
    recurring_count = len(recurring) if isinstance(recurring, list) else 0

    tool_drift = (
        tools_count is None
        or abs(tools_count - EXPECTED_TOOL_COUNT) > TOOL_COUNT_TOLERANCE
    )
    workflow_short = recurring_count < EXPECTED_RECURRING_WORKFLOWS

    status = STATUS_DEGRADED if (tool_drift or workflow_short) else STATUS_OK

    return {
        "status": status,
        "latency_ms": int(latency),
        "http": int(code),
        "tools_count": tools_count,
        "tools_expected": EXPECTED_TOOL_COUNT,
        "recurring_workflows": recurring_count,
        "recurring_expected": EXPECTED_RECURRING_WORKFLOWS,
        "error": None,
    }


def probe_billing() -> dict[str, Any]:
    """Probe Stripe via SDK for `invoice.payment_failed` events in last 24h.

    Reports the failed-event count and computes 5xx rate from event-level
    `request` field where available (Stripe events expose the originating
    HTTP status under `request`). Returns degraded if >0 failed events
    and 5xx_rate >= 0.05, ok otherwise.

    No LLM API import — Stripe SDK is operator billing infrastructure.
    If STRIPE_SECRET_KEY is unset OR SDK is unavailable, returns ok with
    a `stub=true` marker (probe sandbox / CI environments).
    """
    secret = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    t0 = time.monotonic()

    if not secret:
        return {
            "status": STATUS_OK,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "http": 0,
            "failed_events_24h": 0,
            "rate_5xx": 0.0,
            "stub": True,
            "error": "STRIPE_SECRET_KEY not configured",
        }

    try:
        import stripe  # type: ignore
    except Exception as e:
        return {
            "status": STATUS_OK,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "http": 0,
            "failed_events_24h": 0,
            "rate_5xx": 0.0,
            "stub": True,
            "error": f"stripe sdk unavailable: {str(e)[:120]}",
        }

    try:
        stripe.api_key = secret
        api_version = os.environ.get("STRIPE_API_VERSION", "").strip()
        if api_version:
            stripe.api_version = api_version
        cutoff = int((datetime.now(UTC) - timedelta(hours=24)).timestamp())
        events = stripe.Event.list(
            type="invoice.payment_failed",
            created={"gte": cutoff},
            limit=100,
        )
        evlist = events.get("data", []) if isinstance(events, dict) else list(events.auto_paging_iter())
        failed_count = len(evlist)
        # Stripe event request status is best-effort: not every event carries
        # a status field. Count only those that explicitly report 5xx.
        fivexx = 0
        for ev in evlist:
            try:
                req = ev.get("request") if isinstance(ev, dict) else getattr(ev, "request", None)
                if isinstance(req, dict):
                    rs = req.get("status")
                    if isinstance(rs, int) and 500 <= rs < 600:
                        fivexx += 1
            except Exception:
                continue
        rate_5xx = (fivexx / failed_count) if failed_count else 0.0
        latency_ms = int((time.monotonic() - t0) * 1000)

        # Degrade only when failures cross a meaningful 5xx-rate threshold —
        # a steady-state of customer card declines is normal, not an outage.
        status = STATUS_DEGRADED if (failed_count > 0 and rate_5xx >= 0.05) else STATUS_OK
        return {
            "status": status,
            "latency_ms": latency_ms,
            "http": 200,
            "failed_events_24h": failed_count,
            "rate_5xx": round(rate_5xx, 4),
            "stub": False,
            "error": None,
        }
    except Exception as e:
        return {
            "status": STATUS_DEGRADED,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "http": 0,
            "failed_events_24h": None,
            "rate_5xx": None,
            "stub": False,
            "error": f"{type(e).__name__}: {str(e)[:160]}",
        }


def _max_ts_seconds(db_path: Path, sql: str) -> int | None:
    """Return wall-clock seconds since the MAX(ts) row in `sql`, or None."""
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=PROBE_TIMEOUT) as conn:
            row = conn.execute(sql).fetchone()
            if not row or not row[0]:
                return None
            raw = str(row[0])
            # Accept ISO 8601 with explicit offset, Z, or naive UTC. Strict
            # fromisoformat() bombs on 'Z' in Python<3.11 — normalize first.
            cleaned = raw.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(cleaned)
            except Exception:
                # Try date-only.
                dt = datetime.strptime(raw[:10], "%Y-%m-%d").replace(tzinfo=UTC)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return max(0, int((datetime.now(UTC) - dt).total_seconds()))
    except Exception:
        return None


def probe_data_freshness() -> dict[str, Any]:
    """Probe MAX(ts) age vs per-dataset SLA across 4 corpora.

    Datasets:
      * programs (jpintel.db)              SLA 24h   on `updated_at`
      * am_amendment_diff (autonomath.db)  SLA 7d    on `detected_at`
      * invoice_registrants (jpintel.db)   SLA 30d   on `fetched_at`
      * case_studies (jpintel.db)          SLA 30d   on `fetched_at`

    Reports overall status = worst-of-4. `last_updated_at` is the freshest
    dataset (closest to now); `max_age_days` is the staleest (worst).
    """
    t0 = time.monotonic()

    jpintel_db = Path(os.environ.get("JPINTEL_DB_PATH", "data/jpintel.db")).resolve()
    autonomath_db = Path(os.environ.get("AUTONOMATH_DB_PATH", "autonomath.db")).resolve()

    measurements = [
        ("programs", jpintel_db, "SELECT MAX(updated_at) FROM programs", SLA_PROGRAMS),
        (
            "am_amendment_diff",
            autonomath_db,
            "SELECT MAX(detected_at) FROM am_amendment_diff",
            SLA_AMENDMENT_DIFF,
        ),
        (
            "invoice_registrants",
            jpintel_db,
            "SELECT MAX(fetched_at) FROM invoice_registrants",
            SLA_INVOICE_REGS,
        ),
        ("case_studies", jpintel_db, "SELECT MAX(fetched_at) FROM case_studies", SLA_CASE_STUDIES),
    ]

    datasets: dict[str, Any] = {}
    worst_status = STATUS_OK
    worst_age_s: int | None = None
    freshest_age_s: int | None = None

    for name, db_path, sql, sla in measurements:
        age_s = _max_ts_seconds(db_path, sql)
        if age_s is None:
            datasets[name] = {
                "status": STATUS_DEGRADED,
                "age_seconds": None,
                "sla_seconds": sla,
                "db_present": db_path.exists(),
            }
            if worst_status != STATUS_DOWN:
                worst_status = STATUS_DEGRADED
            continue
        ratio = age_s / sla
        if ratio <= 1.0:
            ds_status = STATUS_OK
        elif ratio <= 2.0:
            ds_status = STATUS_DEGRADED
        else:
            ds_status = STATUS_DOWN
        datasets[name] = {
            "status": ds_status,
            "age_seconds": age_s,
            "sla_seconds": sla,
            "db_present": True,
        }
        if ds_status == STATUS_DOWN:
            worst_status = STATUS_DOWN
        elif ds_status == STATUS_DEGRADED and worst_status != STATUS_DOWN:
            worst_status = STATUS_DEGRADED
        if worst_age_s is None or age_s > worst_age_s:
            worst_age_s = age_s
        if freshest_age_s is None or age_s < freshest_age_s:
            freshest_age_s = age_s

    last_updated_at = None
    if freshest_age_s is not None:
        last_updated_at = (
            (datetime.now(UTC) - timedelta(seconds=freshest_age_s))
            .astimezone(JST)
            .strftime("%Y-%m-%d")
        )
    max_age_days = (worst_age_s // 86400) if worst_age_s is not None else None

    return {
        "status": worst_status,
        "latency_ms": int((time.monotonic() - t0) * 1000),
        "http": 0,
        "last_updated_at": last_updated_at,
        "max_age_days": max_age_days,
        "datasets": datasets,
        "error": None,
    }


def probe_dashboard(site_base: str, api_base: str) -> dict[str, Any]:
    """Probe `/dashboard.html` + `#billing` anchor + login_request reachability.

    The dashboard is the only browser-facing surface that the magic-link
    flow lands on — if it's down, paid customers cannot retrieve / rotate
    keys even when the API is healthy. The probe checks:

      1. dashboard.html 200 + non-empty body
      2. `#billing` anchor present (sanity that the right page was served,
         not a CF cache miss serving a stale index)
      3. /v1/me/login_request POST round-trips with 400/422 (request body
         intentionally invalid → expected validation error, NOT 500)
    """
    dashboard_url = f"{site_base.rstrip('/')}/dashboard.html"
    code, latency, body, err = _http_get(dashboard_url)

    has_billing_anchor = False
    if body:
        try:
            has_billing_anchor = b"id=\"billing\"" in body or b"#billing" in body
        except Exception:
            has_billing_anchor = False

    # Magic-link reachability probe. We POST an empty JSON body → server
    # should answer 400 / 422 with a validation envelope. A 500 means the
    # route is broken; a network error means the API is unreachable.
    login_url = f"{api_base.rstrip('/')}/v1/me/login_request"
    login_code = 0
    login_err: str | None = None
    try:
        req = urllib.request.Request(
            login_url,
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "jpcite-status-probe/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as r:
                login_code = int(r.status)
        except urllib.error.HTTPError as e:
            login_code = int(e.code)
    except Exception as e:
        login_err = f"{type(e).__name__}: {str(e)[:160]}"

    # A 4xx is the healthy validation rejection; 200 is also fine (means
    # the empty body was accepted somehow); 5xx or network error → bad.
    magic_link_ok = login_err is None and login_code != 0 and login_code < 500

    if code == 200 and has_billing_anchor and magic_link_ok:
        status = STATUS_OK
    elif code == 200 and (not has_billing_anchor or not magic_link_ok):
        status = STATUS_DEGRADED
    else:
        status = STATUS_DOWN

    return {
        "status": status,
        "latency_ms": int(latency),
        "http": int(code or 0),
        "has_billing_anchor": has_billing_anchor,
        "login_request_http": int(login_code or 0),
        "magic_link_ok": bool(magic_link_ok),
        "error": err or login_err,
    }


# ---------------------------------------------------------------------------
# Aggregate + render
# ---------------------------------------------------------------------------


def overall_status(components: dict[str, dict[str, Any]]) -> str:
    statuses = {c.get("status", STATUS_DOWN) for c in components.values()}
    if STATUS_DOWN in statuses:
        return STATUS_DOWN
    if STATUS_DEGRADED in statuses:
        return STATUS_DEGRADED
    return STATUS_OK


def build_snapshot(api_base: str, site_base: str) -> dict[str, Any]:
    components: dict[str, dict[str, Any]] = {
        "api": probe_api(api_base),
        "mcp": probe_mcp(api_base),
        "billing": probe_billing(),
        "data-freshness": probe_data_freshness(),
        "dashboard": probe_dashboard(site_base, api_base),
    }
    return {
        "snapshot_at": datetime.now(JST).isoformat(timespec="seconds"),
        "components": components,
        "overall": overall_status(components),
    }


# ---------------------------------------------------------------------------
# shields.io-style SVG badge
# ---------------------------------------------------------------------------

# shields.io-ish color tokens. Brightgreen for ok so the badge visually
# matches the status page header dot; yellow + red follow CSS convention.
_BADGE_COLORS = {
    STATUS_OK: "#4c1",          # brightgreen
    STATUS_DEGRADED: "#dfb317",  # yellow
    STATUS_DOWN: "#e05d44",     # red
}

_BADGE_LABEL = "jpcite"


def render_badge_svg(status: str) -> str:
    """Render a shields.io-style 2-segment SVG badge.

    Width math is approximate: 6.5 px per char + 12 px padding. Good
    enough for `ok` / `degraded` / `down` — no need to ship Verdana
    metrics. Static height 20 px matches the shields.io contract so
    README embeds line up next to existing badges.
    """
    status_text = status if status in _BADGE_COLORS else "unknown"
    color = _BADGE_COLORS.get(status_text, "#9f9f9f")

    label_w = max(54, int(len(_BADGE_LABEL) * 6.5) + 12)
    status_w = max(34, int(len(status_text) * 6.5) + 12)
    total_w = label_w + status_w

    label_mid = label_w / 2
    status_mid = label_w + status_w / 2

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{total_w}" height="20" role="img" '
        f'aria-label="{_BADGE_LABEL}: {status_text}">'
        f'<title>{_BADGE_LABEL}: {status_text}</title>'
        f'<linearGradient id="s" x2="0" y2="100%">'
        f'<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        f'<stop offset="1" stop-opacity=".1"/>'
        f'</linearGradient>'
        f'<clipPath id="r"><rect width="{total_w}" height="20" rx="3" fill="#fff"/></clipPath>'
        f'<g clip-path="url(#r)">'
        f'<rect width="{label_w}" height="20" fill="#555"/>'
        f'<rect x="{label_w}" width="{status_w}" height="20" fill="{color}"/>'
        f'<rect width="{total_w}" height="20" fill="url(#s)"/>'
        f'</g>'
        f'<g fill="#fff" text-anchor="middle" '
        f'font-family="Verdana,Geneva,DejaVu Sans,sans-serif" '
        f'text-rendering="geometricPrecision" font-size="110">'
        f'<text x="{label_mid * 10}" y="150" fill="#010101" fill-opacity=".3" '
        f'transform="scale(.1)" textLength="{(label_w - 12) * 10}">{_BADGE_LABEL}</text>'
        f'<text x="{label_mid * 10}" y="140" transform="scale(.1)" '
        f'textLength="{(label_w - 12) * 10}">{_BADGE_LABEL}</text>'
        f'<text x="{status_mid * 10}" y="150" fill="#010101" fill-opacity=".3" '
        f'transform="scale(.1)" textLength="{(status_w - 12) * 10}">{status_text}</text>'
        f'<text x="{status_mid * 10}" y="140" transform="scale(.1)" '
        f'textLength="{(status_w - 12) * 10}">{status_text}</text>'
        f'</g></svg>\n'
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="jpcite 5-component status probe (JSON + optional SVG badge).",
    )
    p.add_argument(
        "--pretty", action="store_true",
        help="Indent JSON output with 2 spaces (default: file pretty, stdout compact).",
    )
    p.add_argument(
        "--out", type=Path, default=None,
        help="Write JSON snapshot to this path (default: site/status/status.json).",
    )
    p.add_argument(
        "--badge-out", type=Path, default=None,
        help="Write shields.io-style SVG badge to this path.",
    )
    p.add_argument(
        "--ax-dashboard-out", type=Path, default=None,
        help=(
            "Wave 20 C2: write derived AX-dashboard JSON to this path "
            "(default: site/status/status_components.json). The derived "
            "shape is the 5-component live view consumed by "
            "site/status/ax_dashboard.html via fetch()."
        ),
    )
    p.add_argument(
        "--stdout", action="store_true",
        help="Also write JSON snapshot to stdout (default unless --quiet).",
    )
    p.add_argument(
        "--quiet", action="store_true",
        help="Suppress stdout output (file-only mode).",
    )
    p.add_argument(
        "--base-url", type=str, default=None,
        help=f"API base URL (default: env JPCITE_API_BASE or {DEFAULT_API_BASE}).",
    )
    p.add_argument(
        "--site-url", type=str, default=None,
        help=f"Site origin URL (default: env JPCITE_SITE_BASE or {DEFAULT_SITE_BASE}).",
    )
    return p.parse_args(argv)


def derive_ax_dashboard_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Wave 20 C2: Derived 5-component live snapshot for ax_dashboard.html.

    The base snapshot (`status.json`) is the operator forensic record —
    rich detail per component. ax_dashboard.html only needs the user-
    visible 5 light-bulbs + last_check timestamp. Slim derivation
    decouples the dashboard UI from the probe internals.

    Schema (stable contract for the dashboard fetch()):

        {
          "snapshot_at": "<JST ISO 8601>",
          "components": [
            {"id": "api",             "status": "ok|degraded|down",
             "last_check": "<JST>",   "latency_ms": int,
             "label": "API"},
            ... 5 entries total ...
          ],
          "overall": "ok|degraded|down"
        }

    Where `label` is the human-friendly name surfaced in the dashboard
    pill chip. Localized to JP (sub-second decision: dashboards land
    on a JP audience; the en mirror does its own localization on the
    client side).
    """
    base_components = snapshot.get("components", {}) or {}
    snapshot_at = snapshot.get("snapshot_at", "")

    labels = {
        "api":             "API",
        "mcp":             "MCP",
        "billing":         "Billing (Stripe)",
        "data-freshness":  "データ鮮度",
        "dashboard":       "ダッシュボード",
    }

    derived: list[dict[str, Any]] = []
    for cid in COMPONENT_IDS:
        cdata = base_components.get(cid, {}) or {}
        derived.append({
            "id": cid,
            "label": labels.get(cid, cid),
            "status": cdata.get("status", STATUS_DOWN),
            "last_check": snapshot_at,
            "latency_ms": int(cdata.get("latency_ms", 0) or 0),
        })

    return {
        "snapshot_at": snapshot_at,
        "components": derived,
        "overall": snapshot.get("overall", STATUS_DOWN),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    api_base = (
        args.base_url
        or os.environ.get("JPCITE_API_BASE")
        or os.environ.get("JPINTEL_API_BASE")
        or DEFAULT_API_BASE
    )
    site_base = (
        args.site_url
        or os.environ.get("JPCITE_SITE_BASE")
        or DEFAULT_SITE_BASE
    )

    snapshot = build_snapshot(api_base, site_base)

    # File output (default: site/status/status.json). Always pretty in file
    # so the static site can serve it directly without re-formatting.
    out_path = args.out or Path(
        os.environ.get("STATUS_JSON_OUT", "site/status/status.json")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    if args.badge_out:
        badge_path = args.badge_out
        badge_path.parent.mkdir(parents=True, exist_ok=True)
        badge_path.write_text(render_badge_svg(snapshot["overall"]), encoding="utf-8")

    # Wave 20 C2: emit the AX-dashboard slim derivation. Defaults to
    # site/status/status_components.json so the dashboard fetch() target
    # is stable. The base status.json continues to carry the operator-
    # forensic full detail.
    ax_path = args.ax_dashboard_out or Path(
        os.environ.get("STATUS_AX_DASHBOARD_OUT", "site/status/status_components.json")
    )
    ax_path.parent.mkdir(parents=True, exist_ok=True)
    derived = derive_ax_dashboard_snapshot(snapshot)
    ax_path.write_text(
        json.dumps(derived, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    if not args.quiet:
        # stdout payload: pretty when --pretty, else compact one-liner for
        # cron log brevity. Always JSON so downstream jq pipes work.
        if args.pretty or args.stdout:
            print(json.dumps(snapshot, indent=2 if args.pretty else None, ensure_ascii=False))
        else:
            print(
                f"[status_probe] wrote {out_path}: overall={snapshot['overall']}, "
                f"components={len(snapshot['components'])}"
            )

    # cron-friendly: always exit 0. Failure state is in JSON.status.
    return 0


if __name__ == "__main__":
    sys.exit(main())
