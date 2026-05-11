#!/usr/bin/env python3
"""rum_aggregator.py — daily RUM rollup (Wave 16 E1).

Reads RUM beacon rows landed by `POST /v1/rum/beacon` (stored in
``analytics/rum_beacons.jsonl`` by the API layer) plus, as a fallback for
days where the in-app beacon receiver was offline, the Cloudflare Web
Analytics GraphQL surface (the same ``CF_API_TOKEN`` + ``CF_ZONE_ID``
already used by ``scripts/cron/cf_analytics_export.py``).

Output: ``site/status/rum.json`` — 7-day rolling p75 + sample count per
Core Web Vital. Consumed by ``site/status/rum.html``.

Idempotent: re-running on the same day overwrites the JSON with the
freshest p75. Cron cadence: hourly is fine, daily is the minimum.

Required env:
  None (CF API fallback is best-effort; if ``CF_API_TOKEN`` is missing,
  the script falls back to in-app beacons only and still writes a valid
  ``rum.json``).
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BEACON_PATH = _REPO_ROOT / "analytics" / "rum_beacons.jsonl"
_OUT_PATH = _REPO_ROOT / "site" / "status" / "rum.json"
_GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"
_WINDOW_DAYS = 7
_METRICS = ("lcp", "inp", "cls", "ttfb", "fcp")


def _percentile(values: list[float], pct: float) -> float | None:
    """Return the ``pct`` percentile of ``values`` (Python statistics-free)."""
    if not values:
        return None
    sv = sorted(values)
    k = max(0, min(len(sv) - 1, int(round((pct / 100.0) * (len(sv) - 1)))))
    return float(sv[k])


def _read_beacons() -> list[dict]:
    """Read the append-only beacon JSONL (best-effort, skip malformed)."""
    if not _BEACON_PATH.exists():
        return []
    rows: list[dict] = []
    with _BEACON_PATH.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _date_of(row: dict) -> str | None:
    """Coerce a beacon row's ``ts`` (epoch ms) into a UTC ``YYYY-MM-DD``."""
    ts = row.get("ts")
    if not isinstance(ts, (int, float)):
        return row.get("date") if isinstance(row.get("date"), str) else None
    try:
        return datetime.fromtimestamp(ts / 1000.0, tz=UTC).date().isoformat()
    except (OSError, ValueError, OverflowError):
        return None


def _fetch_cf_fallback(date_str: str) -> list[dict]:
    """Best-effort: pull synthetic browsing metrics from CF Web Analytics.

    The CF Browser Insights GraphQL surface (``rumWebVitalsEventsAdaptive
    Groups``) returns aggregate web-vitals when a site has Web Analytics
    enabled. If the token lacks the scope, or the dataset is empty, we
    silently return [] and let the in-app beacons drive the rollup.
    """
    token = os.environ.get("CF_API_TOKEN")
    zone = os.environ.get("CF_ZONE_ID")
    if not token or not zone:
        return []
    query = (
        "query($z:String!,$d:Date!){viewer{zones(filter:{zoneTag:$z}){"
        "rumWebVitalsEventsAdaptiveGroups(limit:10000,"
        "filter:{date:$d}){count "
        "quantiles{lcpP75 inpP75 clsP75 fcpP75 ttfbP75}}}}}"
    )
    try:
        resp = httpx.post(
            _GRAPHQL_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": {"z": zone, "d": date_str}},
            timeout=20.0,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    try:
        groups = payload["data"]["viewer"]["zones"][0]["rumWebVitalsEventsAdaptiveGroups"]
    except (KeyError, IndexError, TypeError):
        return []
    synth: list[dict] = []
    for g in groups or []:
        q = g.get("quantiles") or {}
        n = int(g.get("count") or 0)
        synth.append({
            "date": date_str,
            "lcp": q.get("lcpP75"),
            "inp": q.get("inpP75"),
            "cls": q.get("clsP75"),
            "ttfb": q.get("ttfbP75"),
            "fcp": q.get("fcpP75"),
            "samples": n,
            "source": "cf_fallback",
        })
    return synth


def main() -> int:
    today = datetime.now(UTC).date()
    window_start = today - timedelta(days=_WINDOW_DAYS - 1)

    by_day: dict[str, dict[str, list[float]]] = {}
    sample_counts: dict[str, int] = {}
    for row in _read_beacons():
        date = _date_of(row)
        if not date:
            continue
        try:
            row_d = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            continue
        if row_d < window_start or row_d > today:
            continue
        bucket = by_day.setdefault(date, {m: [] for m in _METRICS})
        for m in _METRICS:
            v = row.get(m)
            if isinstance(v, (int, float)) and v >= 0:
                bucket[m].append(float(v))
        sample_counts[date] = sample_counts.get(date, 0) + 1

    days_out: list[dict] = []
    for offset in range(_WINDOW_DAYS):
        d = window_start + timedelta(days=offset)
        date_str = d.isoformat()
        bucket = by_day.get(date_str)
        entry: dict[str, object] = {"date": date_str, "samples": sample_counts.get(date_str, 0)}
        if bucket and any(bucket[m] for m in _METRICS):
            for m in _METRICS:
                entry[m] = _percentile(bucket[m], 75.0)
            entry["source"] = "in_app_beacons"
        else:
            cf_rows = _fetch_cf_fallback(date_str)
            if cf_rows:
                first = cf_rows[0]
                for m in _METRICS:
                    entry[m] = first.get(m)
                entry["samples"] = first.get("samples", 0)
                entry["source"] = "cf_fallback"
            else:
                for m in _METRICS:
                    entry[m] = None
                entry["source"] = "empty"
        days_out.append(entry)

    out = {
        "generated_at": datetime.now(UTC).isoformat(),
        "window_days": _WINDOW_DAYS,
        "p75_thresholds": {
            "lcp": {"ok": 2500, "warn": 4000},
            "inp": {"ok": 200, "warn": 500},
            "cls": {"ok": 0.1, "warn": 0.25},
            "ttfb": {"ok": 800, "warn": 1800},
            "fcp": {"ok": 1800, "warn": 3000},
        },
        "days": days_out,
    }
    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(d["samples"] for d in days_out if isinstance(d["samples"], int))
    print(f"[rum_aggregator] wrote {_OUT_PATH.relative_to(_REPO_ROOT)} days={len(days_out)} samples={total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
