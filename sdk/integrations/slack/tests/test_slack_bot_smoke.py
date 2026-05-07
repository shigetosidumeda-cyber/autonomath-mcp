"""Smoke tests for the jpcite Slack bot.

Pure-mock: every jpcite API call is intercepted via ``httpx.MockTransport``
so the suite never hits the paid endpoint and never requires a live
Slack workspace.
"""

from __future__ import annotations

import hashlib
import hmac
import sys
import time
from pathlib import Path

import httpx
import pytest

# Allow ``import slack_bot`` directly from the plug-in folder so the
# suite is importable both from the repo root and from inside the
# integration directory.
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

from slack_bot import (  # noqa: E402
    SLACK_SIGNING_VERSION,
    SlashCommand,
    classify_query,
    fetch_houjin,
    fetch_programs,
    handle_slash_command,
    render_error_message,
    render_help_message,
    render_houjin_message,
    render_programs_message,
    verify_slack_signature,
)

# ---- helpers ---------------------------------------------------------------


def _slack_sig(secret: str, ts: int, body: bytes) -> str:
    base = f"{SLACK_SIGNING_VERSION}:{ts}:".encode() + body
    digest = hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return f"{SLACK_SIGNING_VERSION}={digest}"


def _client_for(handler) -> httpx.Client:
    """Return an httpx.Client that routes every call through MockTransport.

    `slack_bot._http_get` accepts an injected client, so feeding this in
    means every test runs with zero real network traffic.
    """
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---- query classifier ------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", ("empty", "")),
        ("   ", ("empty", "")),
        ("8010001213708", ("houjin", "8010001213708")),
        ("8010-0012137-08", ("houjin", "8010001213708")),
        ("  8010 001 2137 08  ", ("houjin", "8010001213708")),
        # Non-13-digit input falls through to free-text search.
        ("8010001", ("programs", "8010001")),
        ("補助金 東京都 設備投資", ("programs", "補助金 東京都 設備投資")),
    ],
)
def test_classify_query_table(raw, expected):
    assert classify_query(raw) == expected


# ---- signature verification ------------------------------------------------


def test_verify_signature_happy_path():
    secret = "topsecret"
    body = b"command=/jpcite&text=8010001213708"
    ts = int(time.time())
    sig = _slack_sig(secret, ts, body)
    assert verify_slack_signature(
        signing_secret=secret,
        request_body=body,
        timestamp=str(ts),
        signature=sig,
        now_epoch=ts + 1,
    )


def test_verify_signature_rejects_replay():
    secret = "topsecret"
    body = b"command=/jpcite&text=hello"
    ts = int(time.time())
    sig = _slack_sig(secret, ts, body)
    # Six-minute clock skew → outside Slack's 5-minute window.
    assert not verify_slack_signature(
        signing_secret=secret,
        request_body=body,
        timestamp=str(ts),
        signature=sig,
        now_epoch=ts + 6 * 60 + 1,
    )


def test_verify_signature_rejects_tampered_body():
    secret = "topsecret"
    body = b"command=/jpcite&text=hello"
    ts = int(time.time())
    sig = _slack_sig(secret, ts, body)
    assert not verify_slack_signature(
        signing_secret=secret,
        request_body=body + b"&injected=1",
        timestamp=str(ts),
        signature=sig,
        now_epoch=ts + 1,
    )


def test_verify_signature_rejects_empty_secret():
    assert not verify_slack_signature(
        signing_secret="",
        request_body=b"x",
        timestamp=str(int(time.time())),
        signature="v0=deadbeef",
    )


# ---- jpcite REST integration (mocked) --------------------------------------


def test_fetch_houjin_routes_to_v1_houjin():
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["x_api_key"] = req.headers.get("x-api-key", "")
        return httpx.Response(
            200,
            json={
                "name": "テスト株式会社",
                "address": "東京都文京区小日向2-22-1",
                "qualified_invoice": True,
                "enforcement_count": 0,
                "adoption_count": 2,
            },
        )

    with _client_for(handler) as client:
        payload = fetch_houjin("8010001213708", api_key="jpcite_sk_test", client=client)
    assert payload["name"] == "テスト株式会社"
    assert "/v1/houjin/8010001213708" in seen["url"]
    assert seen["x_api_key"] == "jpcite_sk_test"


def test_fetch_programs_filters_aggregator_rows():
    """Rows missing both source_url AND authority are dropped — defends
    against the aggregator-ban policy in CLAUDE.md."""

    def handler(req: httpx.Request) -> httpx.Response:
        assert "/v1/programs/search" in str(req.url)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"name": "良", "source_url": "https://example.go.jp/a"},
                    {"name": "認可なし"},  # dropped
                    {"name": "別パス", "authority": "経産省"},
                ]
            },
        )

    with _client_for(handler) as client:
        rows = fetch_programs("東京都 設備投資", api_key="k", limit=5, client=client)
    assert len(rows) == 2
    assert rows[0]["name"] == "良"


# ---- top-level dispatcher --------------------------------------------------


def test_handle_slash_command_houjin_path_renders_blocks():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "name": "Bookyou株式会社",
                "address": "東京都文京区小日向2-22-1",
                "qualified_invoice": True,
                "enforcement_count": 0,
                "adoption_count": 1,
            },
        )

    cmd = SlashCommand(
        command="/jpcite",
        text="8010001213708",
        team_id="T1",
        channel_id="C1",
        user_id="U1",
        response_url="https://hooks.slack.com/x",
    )
    with _client_for(handler) as client:
        out = handle_slash_command(command=cmd, api_key="k", client=client)
    assert out["response_type"] == "in_channel"
    types = [b.get("type") for b in out["blocks"]]
    assert "header" in types
    text_blob = "".join(
        f.get("text", "") if isinstance(f, dict) else ""
        for b in out["blocks"]
        for f in b.get("fields", [])
    )
    assert "Bookyou" in text_blob
    assert "8010001213708" in text_blob


def test_handle_slash_command_empty_text_returns_help():
    cmd = SlashCommand(
        command="/jpcite",
        text="",
        team_id="T1",
        channel_id="C1",
        user_id="U1",
        response_url="",
    )
    out = handle_slash_command(command=cmd, api_key="k")
    assert out["response_type"] == "ephemeral"
    blocks_text = "".join(
        b.get("text", {}).get("text", "") for b in out["blocks"] if isinstance(b.get("text"), dict)
    )
    assert "/jpcite" in blocks_text


def test_handle_slash_command_404_renders_error():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not_found"})

    cmd = SlashCommand(
        command="/jpcite",
        text="9999999999999",
        team_id="T1",
        channel_id="C1",
        user_id="U1",
        response_url="",
    )
    with _client_for(handler) as client:
        out = handle_slash_command(command=cmd, api_key="k", client=client)
    assert out["response_type"] == "ephemeral"
    blocks_text = "".join(
        b.get("text", {}).get("text", "") for b in out["blocks"] if isinstance(b.get("text"), dict)
    )
    assert "見つかりません" in blocks_text


def test_handle_slash_command_429_renders_rate_limit():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate_limited"})

    cmd = SlashCommand(
        command="/jpcite",
        text="補助金 東京都",
        team_id="T1",
        channel_id="C1",
        user_id="U1",
        response_url="",
    )
    with _client_for(handler) as client:
        out = handle_slash_command(command=cmd, api_key="k", client=client)
    assert out["response_type"] == "ephemeral"


# ---- copy hygiene ----------------------------------------------------------


def test_help_card_mentions_brand_and_cost():
    out = render_help_message()
    blob = str(out)
    assert "jpcite" in blob
    assert "¥3/req" in blob
    assert "Bookyou" in blob
    assert "T8010001213708" in blob


def test_houjin_message_carries_footer():
    out = render_houjin_message(
        "8010001213708",
        {
            "name": "x",
            "address": "y",
            "qualified_invoice": False,
            "enforcement_count": 0,
            "adoption_count": 0,
        },
    )
    last_block = out["blocks"][-1]
    assert last_block["type"] == "context"
    assert "Bookyou" in last_block["elements"][0]["text"]


def test_programs_empty_message_renders_footer():
    out = render_programs_message("東京都", [])
    assert any(
        "該当する制度が見つかりませんでした" in b.get("text", {}).get("text", "")
        for b in out["blocks"]
        if isinstance(b.get("text"), dict)
    )


def test_error_message_renders_warning_emoji():
    out = render_error_message("AUTH_ERROR")
    text = out["blocks"][0]["text"]["text"]
    assert "⚠" in text or ":warning:" in text
    assert "API" in text or "鍵" in text or "キー" in text


def test_no_llm_imports_in_module_body():
    body = (PLUGIN_ROOT / "slack_bot.py").read_text(encoding="utf-8")
    for forbidden in (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "claude_agent_sdk",
        "google.generativeai",
    ):
        assert forbidden not in body, (
            f"slack_bot.py must not embed {forbidden!r} — LLM-API ban (CLAUDE.md)"
        )
