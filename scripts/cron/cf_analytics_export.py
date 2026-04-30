#!/usr/bin/env python3
"""Cloudflare Web Analytics → analytics/cf_daily.jsonl (append-only).

Runs daily (03:00 JST via .github/workflows/analytics-cron.yml).

Required env:
  CF_API_TOKEN  Cloudflare API token, scope = "Account.Account Analytics:Read"
                (https://dash.cloudflare.com/profile/api-tokens — create token,
                template "Read Analytics", set zone = jpcite.com).
  CF_ZONE_ID    Zone ID for jpcite.com (Cloudflare → Overview → API).

Output: 1 JSONL row per UTC day with shape:
  {"date":"2026-04-28","metric":"summary","unique_visitors":N,
   "page_views":N,"top_paths":[{"path":"/","views":N},...]}

Idempotency: scans existing file for date+metric pair before writing.
Network failure: skip + log to stderr, exit 0 (cron must not crash).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from jpintel_mcp.observability import heartbeat  # noqa: E402

ANALYTICS_DIR = _REPO_ROOT / "analytics"
OUT_PATH = ANALYTICS_DIR / "cf_daily.jsonl"
GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"
QUERY = """
query ($zone:String!,$since:Time!,$until:Time!){
  viewer{ zones(filter:{zoneTag:$zone}){
    httpRequests1dGroups(limit:1, filter:{date_geq:$since, date_lt:$until}){
      sum{ pageViews requests }
      uniq{ uniques }
    }
    topPaths: httpRequests1hGroups(
      limit:10, orderBy:[sum_requests_DESC],
      filter:{datetime_geq:$since, datetime_lt:$until}
    ){
      sum{ requests }
      dimensions{ clientRequestPath: edgeResponseStatus }
    }
  }}
}
"""


def _existing_keys(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            keys.add((row.get("date", ""), row.get("metric", "")))
        except json.JSONDecodeError:
            continue
    return keys


def main() -> int:
    with heartbeat("cf_analytics_export") as hb:
        token = os.environ.get("CF_API_TOKEN")
        zone = os.environ.get("CF_ZONE_ID")
        if not token or not zone:
            print(
                "[cf_analytics] CF_API_TOKEN/CF_ZONE_ID unset — skip",
                file=sys.stderr,
            )
            hb["metadata"] = {"reason": "creds_missing"}
            hb["rows_skipped"] = 1
            return 0

        yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
        date_str = yesterday.isoformat()
        since = f"{date_str}T00:00:00Z"
        until = f"{(yesterday + timedelta(days=1)).isoformat()}T00:00:00Z"

        if (date_str, "summary") in _existing_keys(OUT_PATH):
            print(
                f"[cf_analytics] {date_str} already recorded — skip",
                file=sys.stderr,
            )
            hb["metadata"] = {"reason": "already_recorded", "date": date_str}
            hb["rows_skipped"] = 1
            return 0

        try:
            resp = httpx.post(
                GRAPHQL_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": QUERY,
                    "variables": {"zone": zone, "since": since, "until": until},
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            print(f"[cf_analytics] network error: {exc} — skip", file=sys.stderr)
            hb["metadata"] = {"reason": "network_error", "exc": repr(exc)}
            return 0

        try:
            zones = payload["data"]["viewer"]["zones"]
            groups = zones[0]["httpRequests1dGroups"] if zones else []
            agg = groups[0] if groups else {}
            page_views = agg.get("sum", {}).get("pageViews", 0)
            uniques = agg.get("uniq", {}).get("uniques", 0)
        except (KeyError, IndexError, TypeError) as exc:
            print(
                f"[cf_analytics] unexpected payload shape: {exc} — skip",
                file=sys.stderr,
            )
            hb["metadata"] = {"reason": "payload_shape", "exc": repr(exc)}
            return 0

        ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
        row = {
            "date": date_str,
            "metric": "summary",
            "unique_visitors": int(uniques or 0),
            "page_views": int(page_views or 0),
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        with OUT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            f"[cf_analytics] wrote {date_str}: visitors={uniques} pv={page_views}"
        )
        hb["rows_processed"] = 1
        hb["metadata"] = {
            "date": date_str,
            "unique_visitors": int(uniques or 0),
            "page_views": int(page_views or 0),
        }
    return 0


if __name__ == "__main__":
    sys.exit(main())
