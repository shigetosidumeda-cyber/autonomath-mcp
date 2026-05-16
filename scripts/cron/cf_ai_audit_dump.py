#!/usr/bin/env python3
"""cf_ai_audit_dump.py — daily AI-bot visit counts (Wave 16 E7).

Pulls the previous-UTC-day per-user-agent breakdown from Cloudflare's
``httpRequestsAdaptiveGroups`` GraphQL surface and emits a per-day JSONL
file under ``analytics/cf_ai_audit_{YYYY-MM-DD}.jsonl`` with one row per
AI bot family (GPTBot / ClaudeBot / PerplexityBot / Bytespider / Diffbot /
cohere-ai / YouBot / MistralAI). Mirrors the role of
``scripts/cron/cf_analytics_export.py`` but with AI-bot focus.

Companion to Cloudflare's "AI Audit" feature (PATCH
``/accounts/{id}/ai_audit``) — the AI Audit dashboard surfaces the same
data inside the CF dashboard; this script captures a versioned snapshot
so we can detect crawl-pattern shifts (e.g. ClaudeBot ramp) without
relying on the CF UI.

Required env (both Fly secret AND GHA secret per
``feedback_secret_store_separation``):

  CF_API_TOKEN  Token with "Account.Account Analytics:Read" + zone scope.
  CF_ZONE_ID    Zone ID for jpcite.com.

Output schema: one JSON line per bot family.

  {"date":"2026-05-10","bot":"GPTBot","requests":1234,
   "page_views":1187,"unique_paths":42,
   "ua_samples":["mozilla/5.0 (compatible; gptbot/1.2; ..."]}

Idempotency: if today's file already exists, the script logs and exits 0.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUT_DIR = _REPO_ROOT / "analytics"
_GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"
_TOP_UA_LIMIT = 200  # CF caps at 10k; 200 is plenty for the AI-bot long tail.

# Bot family → list of UA-substring needles. Lower-case match.
# Keep this in sync with web-vitals SKIP list in site/assets/rum.js so the
# two layers agree on "what is a bot".
_BOT_FAMILIES: dict[str, tuple[str, ...]] = {
    "GPTBot": ("gptbot",),
    "ClaudeBot": ("claudebot", "claude-web", "anthropic-ai"),
    "PerplexityBot": ("perplexitybot", "perplexity-ai"),
    "Bytespider": ("bytespider",),
    "Diffbot": ("diffbot",),
    "cohere-ai": ("cohere-ai", "coherebot"),
    "YouBot": ("youbot",),
    "MistralAI": ("mistralai", "mistral-ai"),
}

_QUERY = """
query ($zone:String!,$since:Time!,$until:Time!,$limit:Int!){
  viewer{ zones(filter:{zoneTag:$zone}){
    httpRequestsAdaptiveGroups(
      limit:$limit, orderBy:[sum_requests_DESC],
      filter:{datetime_geq:$since, datetime_lt:$until}
    ){
      sum{ requests pageViews }
      dimensions{ userAgent clientRequestPath }
    }
  }}
}
"""


def _post_graphql(*, token: str, query: str, variables: dict) -> dict | None:
    try:
        resp = httpx.post(
            _GRAPHQL_URL,
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
        print(f"[cf_ai_audit] graphql error: {exc} — skip", file=sys.stderr)
        return None


def _classify(ua: str) -> str | None:
    ua_low = ua.lower()
    for family, needles in _BOT_FAMILIES.items():
        for n in needles:
            if n in ua_low:
                return family
    return None


def main() -> int:
    token = os.environ.get("CF_API_TOKEN")
    zone = os.environ.get("CF_ZONE_ID")
    if not token or not zone:
        print("[cf_ai_audit] CF_API_TOKEN/CF_ZONE_ID unset — skip", file=sys.stderr)
        return 0

    yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
    date_str = yesterday.isoformat()
    next_day = (yesterday + timedelta(days=1)).isoformat()
    since_time = f"{date_str}T00:00:00Z"
    until_time = f"{next_day}T00:00:00Z"

    out_path = _OUT_DIR / f"cf_ai_audit_{date_str}.jsonl"
    if out_path.exists():
        print(f"[cf_ai_audit] {out_path.name} already exists — skip", file=sys.stderr)
        return 0

    payload = _post_graphql(
        token=token,
        query=_QUERY,
        variables={
            "zone": zone,
            "since": since_time,
            "until": until_time,
            "limit": _TOP_UA_LIMIT,
        },
    )
    if payload is None:
        return 0

    try:
        zones = payload["data"]["viewer"]["zones"]
        groups = zones[0]["httpRequestsAdaptiveGroups"] if zones else []
    except (KeyError, IndexError, TypeError) as exc:
        print(f"[cf_ai_audit] payload shape: {exc} — skip", file=sys.stderr)
        return 0

    buckets: dict[str, dict[str, object]] = {
        fam: {"requests": 0, "page_views": 0, "paths": set(), "samples": []}
        for fam in _BOT_FAMILIES
    }
    for g in groups or []:
        dims = g.get("dimensions") or {}
        sums = g.get("sum") or {}
        ua = dims.get("userAgent") or ""
        path = dims.get("clientRequestPath") or ""
        family = _classify(ua)
        if not family:
            continue
        b = buckets[family]
        b["requests"] = int(b["requests"]) + int(sums.get("requests") or 0)
        b["page_views"] = int(b["page_views"]) + int(sums.get("pageViews") or 0)
        paths = b["paths"]
        if isinstance(paths, set) and path:
            paths.add(path)
        samples = b["samples"]
        if isinstance(samples, list) and len(samples) < 3 and ua and ua not in samples:
            samples.append(ua)

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC).isoformat()
    rows_written = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for family, b in sorted(buckets.items(), key=lambda kv: -int(kv[1]["requests"])):
            paths = b["paths"] if isinstance(b["paths"], set) else set()
            row = {
                "date": date_str,
                "bot": family,
                "requests": int(b["requests"]),
                "page_views": int(b["page_views"]),
                "unique_paths": len(paths),
                "ua_samples": b["samples"] if isinstance(b["samples"], list) else [],
                "fetched_at": fetched_at,
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            rows_written += 1

    total_reqs = sum(int(b["requests"]) for b in buckets.values())
    print(
        f"[cf_ai_audit] wrote {out_path.name} families={rows_written} total_requests={total_reqs}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
