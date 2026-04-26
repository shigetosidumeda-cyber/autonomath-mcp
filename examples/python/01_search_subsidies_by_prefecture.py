"""
01_search_subsidies_by_prefecture.py
------------------------------------
List the top-10 S / A tier programs in 青森県 with amount_max_man_yen >= 500
and print a markdown table. This is the canonical "is this API useful?" demo —
one HTTP call, structured result, copy-paste-ready into a Notion page.

env vars:
    JPINTEL_API_KEY   (optional, free tier works for demo)
    JPINTEL_API_BASE  (default: http://localhost:8080)

run:
    pip install -r ../requirements.txt
    python 01_search_subsidies_by_prefecture.py

expected output (real, against live stub with 6,771 programs):

    | tier | 制度名 | 上限 (万円) | 所轄 |
    | ---- | ------ | ----------- | ---- |
    | S | 経営発展支援事業 | 1000.0 | 青森県つがる市 |
    | A | PREF-02-101_青森_所得向上プログラム実践支援事業 | 1000.0 |  |
    | A | 青森 スマート農業機械導入支援事業 | 1250.0 | 都道府県 |
    total matches: 3
"""
from __future__ import annotations

import os
import sys

import httpx

API_BASE = os.environ.get("JPINTEL_API_BASE", "http://localhost:8080")
API_KEY = os.environ.get("JPINTEL_API_KEY")  # optional — free tier without


def fetch_top_programs(prefecture: str, amount_min: float, limit: int = 10) -> list[dict]:
    """GET /v1/programs/search with prefecture + tier=S,A filters."""
    headers: dict[str, str] = {"Accept": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    params: list[tuple[str, str]] = [
        ("prefecture", prefecture),
        ("tier", "S"),
        ("tier", "A"),
        ("amount_min", str(amount_min)),
        ("limit", str(limit)),
    ]

    try:
        resp = httpx.get(f"{API_BASE}/v1/programs/search", headers=headers, params=params, timeout=15.0)
    except httpx.HTTPError as exc:
        print(f"ERROR: transport failure contacting {API_BASE}: {exc}", file=sys.stderr)
        sys.exit(2)

    if resp.status_code == 401:
        print("ERROR: 401 Unauthorized — set JPINTEL_API_KEY or omit it for free tier", file=sys.stderr)
        sys.exit(1)
    if resp.status_code == 429:
        retry = resp.headers.get("Retry-After", "?")
        print(f"ERROR: 429 rate limit — retry after {retry}s", file=sys.stderr)
        sys.exit(1)
    if resp.status_code >= 500:
        print(f"ERROR: server {resp.status_code} — try again or check {API_BASE}/healthz", file=sys.stderr)
        sys.exit(1)
    resp.raise_for_status()

    data = resp.json()
    return data["results"]


def to_markdown(rows: list[dict]) -> str:
    lines = [
        "| tier | 制度名 | 上限 (万円) | 所轄 |",
        "| ---- | ------ | ----------- | ---- |",
    ]
    for r in rows:
        name = (r.get("primary_name") or "").replace("|", "/")
        authority = (r.get("authority_name") or "").replace("|", "/")
        amount = r.get("amount_max_man_yen")
        lines.append(f"| {r.get('tier')} | {name} | {amount} | {authority} |")
    return "\n".join(lines)


def main() -> None:
    rows = fetch_top_programs(prefecture="青森県", amount_min=500, limit=10)
    print(to_markdown(rows))
    print(f"total matches: {len(rows)}")


if __name__ == "__main__":
    main()
