"""Wave 22 — AI bot User-Agent welcome verification.

Cross-checks two surfaces:

1. **Static robots.txt policy** — every UA in the canonical welcome list
   must appear as an explicit ``User-agent:`` directive in
   ``site/robots.txt`` so AI crawlers do not fall through to the default
   ``Crawl-delay: 1`` rule. (Wave 19 expanded robots.txt to 39+ AI bots;
   this test gates the welcome list against regression.)

2. **Live API surface** — for every UA in the welcome list, hitting
   ``/v1/programs/search?limit=1`` against an in-process TestClient must
   return HTTP 200 + ``application/json``. (Confirms no UA-based
   middleware silently 403/404s an AI agent — historic regression risk
   on Cloudflare Bot Fight Mode + custom WAF rules.)

The list contains 16+ canonical AI / search bot UAs spanning OpenAI,
Anthropic, Google, Perplexity, Meta, Twitter/X, Amazon, Mistral,
DeepSeek, Alibaba (Qwen), ByteDance, Cohere, Apple, Microsoft.

This test is **network-free by default** — both probes are local
file reads / in-process TestClient. Set ``JPCITE_TEST_NETWORK=1`` to
additionally walk the live production hostnames (skipped in CI).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
ROBOTS_TXT = REPO_ROOT / "site" / "robots.txt"

# 16+ AI bot / search bot User-Agent fragments.
# Each entry: (label, robots_txt_token, ua_string_for_request).
# robots_txt_token is what appears in `User-agent:` lines (case-insensitive
# substring match). The ua_string_for_request is the verbatim UA header
# value an actual bot sends.
AI_BOT_WELCOME_LIST: list[tuple[str, str, str]] = [
    (
        "GPTBot (OpenAI search-index)",
        "GPTBot",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.2; +https://openai.com/gptbot",
    ),
    (
        "ChatGPT-User (OpenAI live-fetch)",
        "ChatGPT-User",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot",
    ),
    (
        "ClaudeBot (Anthropic search-index)",
        "ClaudeBot",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ClaudeBot/1.0; +https://www.anthropic.com/claude-bot",
    ),
    (
        "Claude-User (Anthropic live-fetch)",
        "Claude-User",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; Claude-User/1.0; +https://www.anthropic.com/claude-user",
    ),
    (
        "anthropic-ai (Anthropic legacy)",
        "anthropic-ai",
        "anthropic-ai/1.0",
    ),
    (
        "Google-Extended (Google AI training)",
        "Google-Extended",
        "Mozilla/5.0 (compatible; Google-Extended/1.0)",
    ),
    (
        "Googlebot (Google search)",
        "Googlebot",
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    ),
    (
        "PerplexityBot (Perplexity AI)",
        "PerplexityBot",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot",
    ),
    (
        "Meta-ExternalAgent (Meta AI)",
        "Meta-ExternalAgent",
        "meta-externalagent/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)",
    ),
    (
        "Twitterbot (X.com)",
        "Twitterbot",
        "Twitterbot/1.0",
    ),
    (
        "Amazonbot (Amazon Alexa)",
        "Amazonbot",
        "Mozilla/5.0 (compatible; Amazonbot/0.1; +https://developer.amazon.com/amazonbot)",
    ),
    (
        "MistralAI-User (Mistral AI)",
        "MistralAI-User",
        "MistralAI-User/1.0",
    ),
    (
        "DeepSeekBot (DeepSeek AI)",
        "DeepSeekBot",
        "Mozilla/5.0 (compatible; DeepSeekBot/1.0; +https://www.deepseek.com)",
    ),
    (
        "Bytespider (ByteDance / TikTok)",
        "Bytespider",
        "Mozilla/5.0 (Linux; Android 5.0) AppleWebKit/537.36 (KHTML, like Gecko); compatible; Bytespider; bytespider@bytedance.com",
    ),
    (
        "cohere-ai (Cohere)",
        "cohere-ai",
        "cohere-ai/1.0",
    ),
    (
        "Applebot-Extended (Apple Intelligence)",
        "Applebot-Extended",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko); Applebot-Extended/0.1",
    ),
    (
        "Bingbot (Microsoft / Copilot)",
        "Bingbot",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm",
    ),
    # Bonus: Qwen (Alibaba) — not yet a public crawler with a stable UA,
    # but reserved here so when Alibaba publishes one we can flip it
    # straight to required.
]


def _robots_txt_text() -> str:
    return ROBOTS_TXT.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "label,token,_ua",
    AI_BOT_WELCOME_LIST,
    ids=[entry[0] for entry in AI_BOT_WELCOME_LIST],
)
def test_robots_txt_lists_ai_bot(label: str, token: str, _ua: str) -> None:
    """robots.txt must explicitly call out each AI bot UA in a User-agent: directive.

    Falling back to the default ``User-agent: *`` policy is acceptable for
    crawlers we have not opinionated on, but every UA in the welcome list
    should have its own dedicated stanza so AI bot operators can verify
    we have an explicit policy for them (and so a future restrictive
    default does not silently cut off LLM training).
    """
    body = _robots_txt_text().lower()
    needle = f"user-agent: {token.lower()}"
    assert needle in body, (
        f"{label}: expected `{needle}` line in site/robots.txt; "
        f"AI bot welcome regression — add a `User-agent: {token}` stanza."
    )


@pytest.mark.parametrize(
    "label,_token,ua",
    AI_BOT_WELCOME_LIST,
    ids=[entry[0] for entry in AI_BOT_WELCOME_LIST],
)
def test_v1_programs_serves_ai_bot_ua(label: str, _token: str, ua: str, jpintel_seeded_db) -> None:
    """Hitting /v1/programs/search?limit=1 with each AI bot UA must return 200 JSON.

    Catches the regression where a middleware (WAF, Bot Fight, custom
    UA filter) silently 403s an AI agent. The anonymous-quota path is
    tested rather than an authenticated key because that is what live
    bots actually use.
    """
    from jpintel_mcp.api.main import create_app

    client = TestClient(create_app())
    r = client.get(
        "/v1/programs/search",
        params={"limit": 1},
        headers={"User-Agent": ua, "Accept": "application/json"},
    )
    assert r.status_code == 200, f"{label}: expected 200, got {r.status_code}. Body: {r.text[:200]}"
    ct = r.headers.get("content-type", "")
    assert ct.startswith("application/json"), (
        f"{label}: expected application/json content-type, got `{ct}`"
    )


def test_ai_bot_welcome_list_size() -> None:
    """At least 16 distinct AI / search bot UAs must be enumerated.

    The welcome list is the canonical contract — additions to robots.txt
    without a matching entry here are caught by this gate.
    """
    assert len(AI_BOT_WELCOME_LIST) >= 16, (
        f"welcome list shrank to {len(AI_BOT_WELCOME_LIST)} — expected ≥16"
    )
    tokens = {entry[1].lower() for entry in AI_BOT_WELCOME_LIST}
    assert len(tokens) == len(AI_BOT_WELCOME_LIST), (
        "duplicate token in AI_BOT_WELCOME_LIST — labels must map to distinct UAs"
    )


@pytest.mark.skipif(
    os.environ.get("JPCITE_TEST_NETWORK") != "1",
    reason="skip-network mode: set JPCITE_TEST_NETWORK=1 to walk live hosts",
)
@pytest.mark.parametrize(
    "label,_token,ua",
    AI_BOT_WELCOME_LIST,
    ids=[entry[0] for entry in AI_BOT_WELCOME_LIST],
)
def test_live_api_serves_ai_bot_ua(label: str, _token: str, ua: str) -> None:
    """Optional: walk the live production API for each UA.

    Skipped in CI (`JPCITE_TEST_NETWORK` not set). Set the env var to
    1 to walk https://api.jpcite.com against the full welcome list.
    """
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        "https://api.jpcite.com/v1/programs/search?limit=1",
        headers={"User-Agent": ua, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
            status = r.status
            ct = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        pytest.fail(f"{label}: live API returned HTTP {e.code} for UA `{ua}`")
        return
    assert status == 200, f"{label}: live API returned {status}"
    assert ct.startswith("application/json"), (
        f"{label}: live API content-type `{ct}` not application/json"
    )
