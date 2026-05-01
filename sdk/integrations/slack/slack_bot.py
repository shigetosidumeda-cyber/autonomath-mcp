"""jpcite Slack bot — `/jpcite <query>` slash command handler.

A small Flask app that:

  1. Parses Slack's `application/x-www-form-urlencoded` slash-command body.
  2. Verifies the request signature (Slack v0 HMAC-SHA256, 5-minute window).
  3. Dispatches the parsed query to the right jpcite REST endpoint:
        - 13 digits  -> ``GET /v1/houjin/{bangou}``        (法人 360)
        - 自由文     -> ``GET /v1/programs/search?q=...``  (上位 5 制度)
  4. Renders the response as a Slack ``in_channel`` chat message
     (Block Kit blocks).

Operator: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708)
Brand:    jpcite (https://jpcite.com)
API:      https://api.jpcite.com (X-API-Key, ¥3/req metered)

Constraints (per CLAUDE.md):

  - **No LLM call** anywhere in this module. The bot returns deterministic
    REST output — Slack users who want LLM reasoning over results pipe
    them into their own Claude / ChatGPT / Cursor agent downstream.
  - **No DB writes**; only HTTP GET against ``api.jpcite.com``.
  - **Customer-hosted**: the user runs this Flask app behind their own
    Slack App credentials. Bookyou never proxies traffic and never holds
    the customer's Slack signing secret or jpcite API key.
  - **¥3/req metered**: every successful slash command costs ¥3 (税込
    ¥3.30) on the jpcite side. The bot adds no markup.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urljoin

import httpx

logger = logging.getLogger("jpcite.slack")

# ---- module constants -------------------------------------------------------

JPCITE_API_BASE = os.environ.get("JPCITE_API_BASE", "https://api.jpcite.com")
USER_AGENT = "jpcite-slack-bot/0.3.2"
SLACK_TIMESTAMP_MAX_SKEW_S = 60 * 5  # Slack's documented 5-minute window
SLACK_SIGNING_VERSION = "v0"


# ---- request parsing --------------------------------------------------------

@dataclass(frozen=True)
class SlashCommand:
    """Parsed Slack slash-command POST body.

    Slack's slash-command payload is ``application/x-www-form-urlencoded``;
    we accept either a parsed mapping or the raw form body.
    """
    command: str
    text: str
    team_id: str
    channel_id: str
    user_id: str
    response_url: str

    @classmethod
    def from_form(cls, form: dict[str, str]) -> SlashCommand:
        return cls(
            command=str(form.get("command", "")),
            text=str(form.get("text", "")).strip(),
            team_id=str(form.get("team_id", "")),
            channel_id=str(form.get("channel_id", "")),
            user_id=str(form.get("user_id", "")),
            response_url=str(form.get("response_url", "")),
        )


def classify_query(text: str) -> tuple[str, str]:
    """Return ``(kind, normalized)`` where ``kind`` is one of:
        - ``"houjin"`` — 13-digit corporate number (digits only,
          tolerating spaces / hyphens / full-width)
        - ``"programs"`` — free text
        - ``"empty"`` — nothing useful

    The normalized form for ``"houjin"`` is the digits only (Slack
    sometimes mangles spaces or hyphens that the customer typed).
    """
    if not text or not text.strip():
        return "empty", ""
    stripped = text.strip()
    digits = "".join(ch for ch in stripped if ch.isdigit())
    # If every non-digit character is whitespace or '-' AND we have
    # exactly 13 digits, treat it as a 法人番号. Otherwise free text.
    non_digit_chars = "".join(
        ch for ch in stripped if not ch.isdigit()
    )
    if len(digits) == 13 and all(ch in " -" for ch in non_digit_chars):
        return "houjin", digits
    return "programs", stripped


# ---- signature verification -------------------------------------------------

def verify_slack_signature(
    *,
    signing_secret: str,
    request_body: bytes,
    timestamp: str,
    signature: str,
    now_epoch: float | None = None,
) -> bool:
    """Replicate Slack's v0 HMAC-SHA256 signature check.

    Returns ``True`` only if ``signature`` matches and ``timestamp`` is
    within the 5-minute replay window. ``now_epoch`` is overridable for
    deterministic tests.
    """
    if not signing_secret or not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    now = now_epoch if now_epoch is not None else time.time()
    if abs(now - ts) > SLACK_TIMESTAMP_MAX_SKEW_S:
        return False
    base = f"{SLACK_SIGNING_VERSION}:{ts}:".encode() + request_body
    digest = hmac.new(
        signing_secret.encode("utf-8"), base, hashlib.sha256
    ).hexdigest()
    expected = f"{SLACK_SIGNING_VERSION}={digest}"
    return hmac.compare_digest(expected, signature)


# ---- jpcite REST client -----------------------------------------------------

def _api_url(path: str, query: dict[str, Any] | None = None) -> str:
    base = JPCITE_API_BASE if JPCITE_API_BASE.endswith("/") else JPCITE_API_BASE + "/"
    target = urljoin(base, path.lstrip("/"))
    if query:
        target += ("&" if "?" in target else "?") + urlencode(
            {k: v for k, v in query.items() if v not in (None, "")}
        )
    return target


def _http_get(
    url: str,
    *,
    api_key: str,
    client: httpx.Client | None = None,
    timeout_s: float = 10.0,
) -> httpx.Response:
    headers = {
        "X-API-Key": api_key,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if client is not None:
        return client.get(url, headers=headers, timeout=timeout_s)
    with httpx.Client() as fresh:
        return fresh.get(url, headers=headers, timeout=timeout_s)


def fetch_houjin(
    bangou: str,
    *,
    api_key: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    res = _http_get(
        _api_url(f"/v1/houjin/{bangou}"),
        api_key=api_key,
        client=client,
    )
    res.raise_for_status()
    payload = res.json()
    return payload if isinstance(payload, dict) else {}


def fetch_programs(
    query: str,
    *,
    api_key: str,
    limit: int = 5,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    capped = max(1, min(20, int(limit)))
    res = _http_get(
        _api_url("/v1/programs/search", {"q": query, "limit": capped}),
        api_key=api_key,
        client=client,
    )
    res.raise_for_status()
    payload = res.json()
    if isinstance(payload, dict):
        items = payload.get("results") or payload.get("items") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    out: list[dict[str, Any]] = []
    for row in items:
        if isinstance(row, dict) and (
            row.get("source_url") or row.get("authority")
        ):
            out.append(row)
    return out[:capped]


# ---- Slack response rendering ----------------------------------------------

_FOOTER_BLOCK = {
    "type": "context",
    "elements": [
        {
            "type": "mrkdwn",
            "text": (
                "¥3/req metered (税込 ¥3.30) ・ <https://jpcite.com|jpcite.com> "
                "・ 運営: Bookyou株式会社 (T8010001213708)"
            ),
        }
    ],
}


def render_houjin_message(bangou: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = payload.get("name") or payload.get("houjin_name") or "(名称不明)"
    address = payload.get("address") or payload.get("houjin_address") or ""
    qualified = (
        f"登録あり (T{bangou})" if payload.get("qualified_invoice") else "登録なし"
    )
    enf_count = int(payload.get("enforcement_count") or 0)
    enf = f"該当 {enf_count} 件" if enf_count else "該当なし"
    adopt = int(payload.get("adoption_count") or 0)
    adopt_text = f"{adopt} 件" if adopt else "0 件"
    fields = [
        {"type": "mrkdwn", "text": f"*法人番号*\n{bangou}"},
        {"type": "mrkdwn", "text": f"*名称*\n{name}"},
        {"type": "mrkdwn", "text": f"*住所*\n{address}"},
        {"type": "mrkdwn", "text": f"*適格請求書発行事業者*\n{qualified}"},
        {"type": "mrkdwn", "text": f"*行政処分*\n{enf}"},
        {"type": "mrkdwn", "text": f"*採択履歴*\n{adopt_text}"},
    ]
    return {
        "response_type": "in_channel",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "jpcite 法人 360"},
            },
            {"type": "section", "fields": fields},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "jpcite.com で開く",
                        },
                        "url": f"https://jpcite.com/houjin/{bangou}",
                    }
                ],
            },
            _FOOTER_BLOCK,
        ],
    }


def render_programs_message(
    query: str, items: list[dict[str, Any]]
) -> dict[str, Any]:
    if not items:
        return {
            "response_type": "in_channel",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*jpcite 制度検索* — `{query}`\n"
                            "該当する制度が見つかりませんでした。"
                        ),
                    },
                },
                _FOOTER_BLOCK,
            ],
        }
    lines: list[str] = [f"*jpcite 制度検索* — `{query}` 上位 {len(items)} 件"]
    for i, row in enumerate(items, start=1):
        title = (
            row.get("name")
            or row.get("title")
            or row.get("primary_name")
            or "(名称不明)"
        )
        authority = row.get("authority") or row.get("authority_level") or ""
        url = row.get("source_url") or ""
        line = f"{i}. <{url}|{title}>" if url else f"{i}. {title}"
        if authority:
            line += f"  (_{authority}_)"
        lines.append(line)
    return {
        "response_type": "in_channel",
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(lines)},
            },
            _FOOTER_BLOCK,
        ],
    }


def render_help_message() -> dict[str, Any]:
    return {
        "response_type": "ephemeral",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*jpcite Slack bot*\n"
                        "`/jpcite 8010001213708` → 法人 360\n"
                        "`/jpcite 補助金 東京都 設備投資` → 制度上位 5 件\n"
                        "_¥3/req metered (税込 ¥3.30)_"
                    ),
                },
            },
            _FOOTER_BLOCK,
        ],
    }


def render_error_message(code: str, detail: str = "") -> dict[str, Any]:
    canonical = {
        "AUTH_ERROR": "API キーが無効です。Slack App の secrets を確認してください。",
        "NOT_FOUND": "該当する法人番号が見つかりませんでした。",
        "RATE_LIMITED": "リクエスト制限に達しました。少し時間をおいて再度お試しください。",
        "BAD_REQUEST": "リクエスト形式が不正です。",
        "TIMEOUT": "上流 API がタイムアウトしました。",
    }
    msg = canonical.get(code) or f"リクエストに失敗しました ({code})。"
    if detail:
        msg += f"\n_{detail}_"
    return {
        "response_type": "ephemeral",
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":warning: {msg}"},
            },
            _FOOTER_BLOCK,
        ],
    }


# ---- top-level dispatcher --------------------------------------------------

def handle_slash_command(
    *,
    command: SlashCommand,
    api_key: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    kind, normalized = classify_query(command.text)
    if kind == "empty":
        return render_help_message()
    try:
        if kind == "houjin":
            payload = fetch_houjin(normalized, api_key=api_key, client=client)
            return render_houjin_message(normalized, payload)
        items = fetch_programs(normalized, api_key=api_key, client=client)
        return render_programs_message(normalized, items)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else 0
        if status in (401, 403):
            return render_error_message("AUTH_ERROR")
        if status == 404:
            return render_error_message("NOT_FOUND")
        if status == 429:
            return render_error_message("RATE_LIMITED")
        return render_error_message(f"HTTP_{status}")
    except httpx.TimeoutException:
        return render_error_message("TIMEOUT")
    except httpx.HTTPError as e:
        logger.warning("jpcite slack: upstream HTTPError: %s", e)
        return render_error_message("BAD_REQUEST", detail=str(e))


# ---- optional Flask wiring --------------------------------------------------

def build_flask_app() -> Any:  # pragma: no cover — exercised via README
    """Return a configured Flask app. Imported lazily so the smoke test
    suite does not need Flask installed."""
    from flask import Flask, jsonify, request

    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    api_key = os.environ.get("JPCITE_API_KEY", "")

    app = Flask("jpcite_slack_bot")

    @app.post("/slack/commands")
    def slack_commands_endpoint():
        body = request.get_data() or b""
        ts = request.headers.get("X-Slack-Request-Timestamp", "")
        sig = request.headers.get("X-Slack-Signature", "")
        if not verify_slack_signature(
            signing_secret=signing_secret,
            request_body=body,
            timestamp=ts,
            signature=sig,
        ):
            return jsonify({"error": "invalid_signature"}), 401
        cmd = SlashCommand.from_form(request.form.to_dict())
        return jsonify(handle_slash_command(command=cmd, api_key=api_key))

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "service": "jpcite-slack"})

    return app


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    build_flask_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
