"""LangChain Tool wrapper for jpcite /v1/programs/search.

Usage:
    from langchain_tool import autonomath_tool
    print(autonomath_tool.run("東京都の中小企業向け補助金"))

Or wire into an agent:
    from langchain.agents import initialize_agent
    agent = initialize_agent([autonomath_tool], llm, ...)

Pricing: ¥3/req authenticated, anonymous 3 req/day/IP free.
Set JPCITE_API_KEY env var for authenticated calls. This is a jpcite API key,
not an LLM provider key.
"""

from __future__ import annotations

import os
import json
from typing import Any

import requests
from langchain.tools import Tool

API_BASE = os.environ.get("JPCITE_API_BASE") or os.environ.get(
    "AUTONOMATH_API_BASE", "https://api.jpcite.com"
)
API_KEY = os.environ.get("JPCITE_API_KEY") or os.environ.get("AUTONOMATH_API_KEY", "")


def _search_programs(query: str) -> str:
    headers: dict[str, str] = {"User-Agent": "autonomath-starter-langchain/0.1"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    try:
        resp = requests.get(
            f"{API_BASE}/v1/programs/search",
            params={"q": query, "limit": 10},
            headers=headers,
            timeout=15,
        )
    except requests.RequestException as exc:
        return json.dumps({"error": "transport", "detail": str(exc)}, ensure_ascii=False)

    if resp.status_code == 429:
        retry = resp.headers.get("Retry-After", "?")
        return json.dumps(
            {"error": "rate_limited", "retry_after_sec": retry,
             "hint": "anonymous tier 3 req/day — set JPCITE_API_KEY for ¥3/req metered access"},
            ensure_ascii=False,
        )
    if resp.status_code >= 400:
        return json.dumps({"error": resp.status_code, "body": resp.text[:500]}, ensure_ascii=False)

    payload: Any = resp.json()
    return json.dumps(payload, ensure_ascii=False, indent=2)


autonomath_tool = Tool(
    name="autonomath_search_programs",
    description=(
        "Search Japanese government subsidies, loans, tax measures, and "
        "certifications by free-text Japanese query. Returns up to 10 "
        "primary-source-cited programs with tier (S/A/B/C), authority, "
        "amount band, and source URL. Input: a Japanese query string."
    ),
    func=_search_programs,
)
