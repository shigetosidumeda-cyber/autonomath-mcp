#!/usr/bin/env python3
"""Cloudflare Web Analytics → analytics/cf_daily.jsonl (append-only).

Runs daily (03:00 JST via .github/workflows/analytics-cron.yml).

Required env:
  CF_API_TOKEN  Cloudflare API token, scope = "Account.Account Analytics:Read"
                (https://dash.cloudflare.com/profile/api-tokens — create token,
                template "Read Analytics", set zone = jpcite.com).
  CF_ZONE_ID    Zone ID for jpcite.com (Cloudflare → Overview → API).

Output: 1+ JSONL row per UTC day. Each row has a stable {date, metric, ...}
shape. Today's collector emits these metric rows (one per call):

  - {"metric":"summary",       unique_visitors, page_views, requests}
  - {"metric":"top_paths",     items=[{path, requests, page_views}]}
  - {"metric":"top_status",    items=[{status, requests}]}
  - {"metric":"top_ua_class",  items=[{user_agent_class, requests, page_views}]}
  - {"metric":"top_countries", items=[{country, requests}]}
  - {"metric":"top_referers",  items=[{referer_host, requests}]}

The previous shape merged path+status into a single broken `dimensions{...}`
block (GraphQL coerced it to a single field — the column was lost). Each
dimension is now a separate top-N query so downstream consumers can slice
by axis without re-parsing a stringly-typed bucket.

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

# Top-N cap for each dimension query. 25 is a balance: large enough to
# expose long-tail bots/paths, small enough that the JSONL stays grep-able.
_TOP_N = 25

# ---- GraphQL queries --------------------------------------------------------
# httpRequests1dGroups gives the per-day rollup (uniques + pageViews +
# requests). httpRequestsAdaptiveGroups is the dimension-rich groupBy
# surface — `groupBy` accepts only a single field per query, so we issue
# one request per axis.
_QUERY_SUMMARY = """
query ($zone:String!,$since:Date!,$until:Date!){
  viewer{ zones(filter:{zoneTag:$zone}){
    httpRequests1dGroups(limit:1, filter:{date_geq:$since, date_lt:$until}){
      sum{ pageViews requests }
      uniq{ uniques }
    }
  }}
}
"""

_QUERY_TOP_PATHS = """
query ($zone:String!,$since:Time!,$until:Time!,$limit:Int!){
  viewer{ zones(filter:{zoneTag:$zone}){
    httpRequestsAdaptiveGroups(
      limit:$limit, orderBy:[sum_requests_DESC],
      filter:{datetime_geq:$since, datetime_lt:$until}
    ){
      sum{ requests pageViews }
      dimensions{ clientRequestPath }
    }
  }}
}
"""

_QUERY_TOP_STATUS = """
query ($zone:String!,$since:Time!,$until:Time!,$limit:Int!){
  viewer{ zones(filter:{zoneTag:$zone}){
    httpRequestsAdaptiveGroups(
      limit:$limit, orderBy:[sum_requests_DESC],
      filter:{datetime_geq:$since, datetime_lt:$until}
    ){
      sum{ requests }
      dimensions{ edgeResponseStatus }
    }
  }}
}
"""

_QUERY_TOP_UA = """
query ($zone:String!,$since:Time!,$until:Time!,$limit:Int!){
  viewer{ zones(filter:{zoneTag:$zone}){
    httpRequestsAdaptiveGroups(
      limit:$limit, orderBy:[sum_requests_DESC],
      filter:{datetime_geq:$since, datetime_lt:$until}
    ){
      sum{ requests pageViews }
      dimensions{ userAgent }
    }
  }}
}
"""

_QUERY_TOP_COUNTRIES = """
query ($zone:String!,$since:Time!,$until:Time!,$limit:Int!){
  viewer{ zones(filter:{zoneTag:$zone}){
    httpRequestsAdaptiveGroups(
      limit:$limit, orderBy:[sum_requests_DESC],
      filter:{datetime_geq:$since, datetime_lt:$until}
    ){
      sum{ requests }
      dimensions{ clientCountryName }
    }
  }}
}
"""

_QUERY_TOP_REFERERS = """
query ($zone:String!,$since:Time!,$until:Time!,$limit:Int!){
  viewer{ zones(filter:{zoneTag:$zone}){
    httpRequestsAdaptiveGroups(
      limit:$limit, orderBy:[sum_requests_DESC],
      filter:{datetime_geq:$since, datetime_lt:$until}
    ){
      sum{ requests }
      dimensions{ refererHost }
    }
  }}
}
"""


# ---- UA classification (mirror of api/anon_limit.py) -----------------------
# Kept inline to avoid importing FastAPI deps in a cron context. Keep in
# sync with `_UA_PATTERNS` in `src/jpintel_mcp/api/anon_limit.py` — divergence
# means UA buckets in the JSONL won't match the buckets stored in
# `analytics_events.user_agent_class`.
_UA_PATTERNS: tuple[tuple[str, str], ...] = (
    # Bots / crawlers (highest priority — these dominate CF raw PV).
    ("bot:googlebot", "googlebot"),
    ("bot:bingbot", "bingbot"),
    ("bot:gptbot", "gptbot"),
    ("bot:claudebot", "claudebot"),
    ("bot:perplexity", "perplexitybot"),
    ("bot:facebook", "facebookexternalhit"),
    ("bot:twitter", "twitterbot"),
    ("bot:applebot", "applebot"),
    ("bot:duckduck", "duckduckbot"),
    ("bot:yandex", "yandexbot"),
    ("bot:baidu", "baiduspider"),
    ("bot:semrush", "semrushbot"),
    ("bot:ahrefs", "ahrefsbot"),
    ("bot:generic", "bot"),
    ("bot:generic", "spider"),
    ("bot:generic", "crawler"),
    # LLM clients (explicit MCP / chat clients).
    ("claude-desktop", "claude desktop"),
    ("claude-code", "claude-code"),
    ("chatgpt", "chatgpt"),
    ("cursor", "cursor"),
    ("zed", "zed-editor"),
    ("cline", "cline"),
    ("continue", "continue.dev"),
    # Official SDKs (LLM provider HTTP signatures).
    ("anthropic-sdk", "anthropic"),
    ("openai-sdk", "openai"),
    ("google-genai", "google-genai"),
    ("mcp-client", "mcp/"),
    # Generic CLI / scripting.
    ("curl", "curl/"),
    ("wget", "wget/"),
    ("httpx", "python-httpx"),
    ("requests", "python-requests"),
    ("axios", "axios/"),
    # Browsers (lowest priority — fall through after specific clients).
    ("browser:firefox", "firefox/"),
    ("browser:safari", "safari/"),
    ("browser:edge", "edg/"),
    ("browser:chrome", "chrome/"),
)


def classify_user_agent(ua: str | None) -> str:
    """Map a User-Agent string to a stable class label.

    Returns one of: ``bot:*``, ``claude-desktop``, ``claude-code``,
    ``chatgpt``, ``cursor``, ``zed``, ``cline``, ``continue``,
    ``anthropic-sdk``, ``openai-sdk``, ``google-genai``, ``mcp-client``,
    ``curl``, ``wget``, ``httpx``, ``requests``, ``axios``,
    ``browser:firefox``, ``browser:safari``, ``browser:edge``,
    ``browser:chrome``, ``unknown`` (no UA), or ``other`` (no rule hit).
    """
    if not ua:
        return "unknown"
    ua_low = ua.lower()
    for label, needle in _UA_PATTERNS:
        if needle in ua_low:
            return label
    return "other"


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


def _post_graphql(
    *,
    token: str,
    query: str,
    variables: dict,
) -> dict | None:
    """Issue one GraphQL POST. Returns parsed payload or None on error."""
    try:
        resp = httpx.post(
            GRAPHQL_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": variables},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"[cf_analytics] graphql error: {exc} — skip", file=sys.stderr)
        return None


def _extract_groups(payload: dict | None, kind: str) -> list[dict]:
    """Return the `httpRequestsAdaptiveGroups` list (or [] on shape mismatch)."""
    if not payload:
        return []
    try:
        zones = payload["data"]["viewer"]["zones"]
        if not zones:
            return []
        groups = zones[0].get(kind) or []
        return list(groups) if isinstance(groups, list) else []
    except (KeyError, TypeError):
        return []


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
        next_day = (yesterday + timedelta(days=1)).isoformat()
        # httpRequests1dGroups expects Date (yyyy-mm-dd); the adaptive group
        # surface expects Time (RFC3339). We pass both formats below.
        since_date = date_str
        until_date = next_day
        since_time = f"{date_str}T00:00:00Z"
        until_time = f"{next_day}T00:00:00Z"

        existing = _existing_keys(OUT_PATH)
        if (date_str, "summary") in existing:
            print(
                f"[cf_analytics] {date_str} already recorded — skip",
                file=sys.stderr,
            )
            hb["metadata"] = {"reason": "already_recorded", "date": date_str}
            hb["rows_skipped"] = 1
            return 0

        # ---- 1. summary ----------------------------------------------------
        summary_payload = _post_graphql(
            token=token,
            query=_QUERY_SUMMARY,
            variables={
                "zone": zone,
                "since": since_date,
                "until": until_date,
            },
        )
        if summary_payload is None:
            hb["metadata"] = {"reason": "summary_network_error"}
            return 0
        try:
            zones = summary_payload["data"]["viewer"]["zones"]
            groups = zones[0]["httpRequests1dGroups"] if zones else []
            agg = groups[0] if groups else {}
            page_views = int(agg.get("sum", {}).get("pageViews", 0) or 0)
            requests_total = int(agg.get("sum", {}).get("requests", 0) or 0)
            uniques = int(agg.get("uniq", {}).get("uniques", 0) or 0)
        except (KeyError, IndexError, TypeError) as exc:
            print(
                f"[cf_analytics] summary payload shape: {exc} — skip",
                file=sys.stderr,
            )
            hb["metadata"] = {"reason": "summary_shape", "exc": repr(exc)}
            return 0

        ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
        rows: list[dict] = []
        fetched_at = datetime.now(UTC).isoformat()

        rows.append(
            {
                "date": date_str,
                "metric": "summary",
                "unique_visitors": uniques,
                "page_views": page_views,
                "requests": requests_total,
                "fetched_at": fetched_at,
            }
        )

        # ---- 2. top paths --------------------------------------------------
        if (date_str, "top_paths") not in existing:
            top_paths_payload = _post_graphql(
                token=token,
                query=_QUERY_TOP_PATHS,
                variables={
                    "zone": zone,
                    "since": since_time,
                    "until": until_time,
                    "limit": _TOP_N,
                },
            )
            items = []
            for g in _extract_groups(top_paths_payload, "httpRequestsAdaptiveGroups"):
                dims = g.get("dimensions") or {}
                sums = g.get("sum") or {}
                path = dims.get("clientRequestPath") or ""
                if not path:
                    continue
                items.append(
                    {
                        "path": path,
                        "requests": int(sums.get("requests", 0) or 0),
                        "page_views": int(sums.get("pageViews", 0) or 0),
                    }
                )
            rows.append(
                {
                    "date": date_str,
                    "metric": "top_paths",
                    "items": items,
                    "fetched_at": fetched_at,
                }
            )

        # ---- 3. top status -------------------------------------------------
        if (date_str, "top_status") not in existing:
            top_status_payload = _post_graphql(
                token=token,
                query=_QUERY_TOP_STATUS,
                variables={
                    "zone": zone,
                    "since": since_time,
                    "until": until_time,
                    "limit": _TOP_N,
                },
            )
            items = []
            for g in _extract_groups(top_status_payload, "httpRequestsAdaptiveGroups"):
                dims = g.get("dimensions") or {}
                sums = g.get("sum") or {}
                status = dims.get("edgeResponseStatus")
                if status is None:
                    continue
                items.append(
                    {
                        "status": int(status),
                        "requests": int(sums.get("requests", 0) or 0),
                    }
                )
            rows.append(
                {
                    "date": date_str,
                    "metric": "top_status",
                    "items": items,
                    "fetched_at": fetched_at,
                }
            )

        # ---- 4. top user-agent class --------------------------------------
        if (date_str, "top_ua_class") not in existing:
            top_ua_payload = _post_graphql(
                token=token,
                query=_QUERY_TOP_UA,
                variables={
                    "zone": zone,
                    "since": since_time,
                    "until": until_time,
                    # Pull more raw UAs because we re-bucket client-side and
                    # multiple distinct UA strings collapse into one class.
                    "limit": _TOP_N * 4,
                },
            )
            # Roll up raw UA strings into stable class labels client-side.
            # CF can't bucket UAs for us — we only get raw strings.
            buckets: dict[str, dict[str, int]] = {}
            for g in _extract_groups(top_ua_payload, "httpRequestsAdaptiveGroups"):
                dims = g.get("dimensions") or {}
                sums = g.get("sum") or {}
                raw_ua = dims.get("userAgent") or ""
                cls = classify_user_agent(raw_ua)
                bucket = buckets.setdefault(cls, {"requests": 0, "page_views": 0})
                bucket["requests"] += int(sums.get("requests", 0) or 0)
                bucket["page_views"] += int(sums.get("pageViews", 0) or 0)
            items = sorted(
                (
                    {
                        "user_agent_class": cls,
                        "is_bot": cls.startswith("bot:"),
                        "requests": v["requests"],
                        "page_views": v["page_views"],
                    }
                    for cls, v in buckets.items()
                ),
                key=lambda r: r["requests"],
                reverse=True,
            )[:_TOP_N]
            rows.append(
                {
                    "date": date_str,
                    "metric": "top_ua_class",
                    "items": items,
                    "fetched_at": fetched_at,
                }
            )

        # ---- 5. top countries ---------------------------------------------
        if (date_str, "top_countries") not in existing:
            top_countries_payload = _post_graphql(
                token=token,
                query=_QUERY_TOP_COUNTRIES,
                variables={
                    "zone": zone,
                    "since": since_time,
                    "until": until_time,
                    "limit": _TOP_N,
                },
            )
            items = []
            for g in _extract_groups(top_countries_payload, "httpRequestsAdaptiveGroups"):
                dims = g.get("dimensions") or {}
                sums = g.get("sum") or {}
                country = dims.get("clientCountryName") or ""
                if not country:
                    continue
                items.append(
                    {
                        "country": country,
                        "requests": int(sums.get("requests", 0) or 0),
                    }
                )
            rows.append(
                {
                    "date": date_str,
                    "metric": "top_countries",
                    "items": items,
                    "fetched_at": fetched_at,
                }
            )

        # ---- 6. top referers ----------------------------------------------
        if (date_str, "top_referers") not in existing:
            top_referers_payload = _post_graphql(
                token=token,
                query=_QUERY_TOP_REFERERS,
                variables={
                    "zone": zone,
                    "since": since_time,
                    "until": until_time,
                    "limit": _TOP_N,
                },
            )
            items = []
            for g in _extract_groups(top_referers_payload, "httpRequestsAdaptiveGroups"):
                dims = g.get("dimensions") or {}
                sums = g.get("sum") or {}
                ref = dims.get("refererHost") or ""
                if not ref:
                    continue
                items.append(
                    {
                        "referer_host": ref,
                        "requests": int(sums.get("requests", 0) or 0),
                    }
                )
            rows.append(
                {
                    "date": date_str,
                    "metric": "top_referers",
                    "items": items,
                    "fetched_at": fetched_at,
                }
            )

        # ---- write all rows in one append ----------------------------------
        with OUT_PATH.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            f"[cf_analytics] wrote {date_str}: visitors={uniques} "
            f"pv={page_views} reqs={requests_total} metrics={len(rows)}"
        )
        hb["rows_processed"] = len(rows)
        hb["metadata"] = {
            "date": date_str,
            "unique_visitors": uniques,
            "page_views": page_views,
            "requests": requests_total,
            "metric_rows": len(rows),
        }
    return 0


if __name__ == "__main__":
    sys.exit(main())
