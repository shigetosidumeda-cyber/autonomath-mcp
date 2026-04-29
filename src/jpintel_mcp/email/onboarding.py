"""Post-signup activation sequence (D+0 / D+1 / D+3 / D+7 / D+14 / D+30).

Purpose
-------
D+0 (`send_day0_welcome`) is fired *synchronously* from
`api/billing.py::_send_welcome_safe` at key issuance time — it carries the
one-time raw API key in the TemplateModel and must NOT be scheduled via the
cron (rows in `email_schedule` only hold the hash, never the raw key).
D+1 (`send_day1_quick_win`) is the first *scheduler*-driven mail and
reaches the customer ~24h after the key is issued. Industry data for B2B
dev-tool APIs is consistent: a multi-touch onboarding sequence over the
first month roughly triples "activation" (user making >5 real API calls
by D+30). This module is that sequence.

Why this shape
--------------
Each `send_*` function is a thin wrapper around the shared `PostmarkClient`
instance — SAME codepath as `send_welcome`, so test-mode gating (empty
token OR env=="test") and never-raise semantics come for free. We do NOT
subclass the client or spin up a parallel one; there is one Postmark
token, one From:, one retry policy. Callers (tests, scheduler) pass an
explicit client for control; production paths call through `get_client()`.

`TemplateAlias` values
    - `onboarding-day0`   D+0 welcome + first-request curls + one-time key
                          (fired synchronously from billing.py — NOT the cron)
    - `onboarding-day1`   D+1 quick-win nudge with 3 "if you're stuck, try
                          this" recipes; first cron-fired mail of the sequence
    - `onboarding-day3`   activation examples + MCP wire-up
    - `onboarding-day7`   usage reflection + power-feature surfacing
    - `onboarding-day14`  power-user tips (MCP / batch / monthly_cap_yen)
    - `onboarding-day30`  open-ended feedback ask (NO scale, just reply)

Historical note: D+14 used to be an "inactive-only reminder" gated by
`usage_count == 0`. The 2026-04-29 onboarding redesign re-purposed it as
power-user tips and removed the skip rule — the inactive-customer ask
now lives in D+30 ("Q. なぜ使い始められなかったのでしょうか?"). The
scheduler retains its `{"skipped": true, "reason": "active"}` branch as
a no-op safety net for custom usage_count_fn injectors, but the in-tree
helper no longer emits it.

All functions return whatever Postmark returns (a dict) or the test-mode
stub — never raise. Matches the `send_welcome` contract so callers can
treat the whole email surface uniformly.

Canonical unified_id picks (D+3 activation examples) were selected on
2026-04-23 to span buckets: one national SME subsidy, one prefecture IT
grant, one national SME credit guarantee. Agri is deliberately *not*
over-represented — the MCP is positioning as general-purpose JP
institutional data, not an agri-only tool. See the D+3 HTML template
for the exact three and a justification pointer back to this module.
"""

from __future__ import annotations

from typing import Any

from jpintel_mcp.email.postmark import PostmarkClient, get_client

# ---------------------------------------------------------------------------
# Template aliases — stable strings that match Postmark's UI.
# ---------------------------------------------------------------------------

TEMPLATE_DAY0 = "onboarding-day0"
TEMPLATE_DAY1 = "onboarding-day1"
TEMPLATE_DAY3 = "onboarding-day3"
TEMPLATE_DAY7 = "onboarding-day7"
TEMPLATE_DAY14 = "onboarding-day14"
TEMPLATE_DAY30 = "onboarding-day30"

# ---------------------------------------------------------------------------
# D+3 example programs (for the activation curls in onboarding-day3.html).
# Pinned in code so the templates can reference a hardcoded list without
# another DB round-trip at send time. Selection criteria documented in
# the module docstring above.
# ---------------------------------------------------------------------------

_DAY3_EXAMPLE_IDS: tuple[dict[str, str], ...] = (
    {
        "unified_id": "UNI-14e57fbf79",
        "name": "中小企業成長加速化補助金",
        "bucket": "national / 中小企業 / subsidy",
    },
    {
        "unified_id": "UNI-40bc849d45",
        "name": "東京都サイバーセキュリティ対策促進助成金",
        "bucket": "prefecture (東京都) / IT / grant",
    },
    {
        "unified_id": "UNI-08d8284aae",
        "name": "セーフティネット保証1号",
        "bucket": "national / 金融支援 / loan",
    },
)


def _client_or(default: PostmarkClient | None) -> PostmarkClient:
    """Return the caller-supplied client or the process-wide singleton.

    Tests pass a client with `httpx.MockTransport` (or env="test") so they
    can assert on payload shape without reaching Postmark. Production code
    passes nothing and hits the shared client.
    """
    return default or get_client()


# ---------------------------------------------------------------------------
# Day 0 — welcome: one-time raw-key delivery + first-request curls
# ---------------------------------------------------------------------------


def send_day0_welcome(
    *,
    to: str,
    api_key: str,
    tier: str,
    client: PostmarkClient | None = None,
) -> dict[str, Any]:
    """D+0 welcome — the ONE email that shows the raw API key.

    Called from `api/billing.py::_send_welcome_safe` synchronously after
    `issue_key()` returns the raw key; NOT enqueued into `email_schedule`
    because the cron only ever sees the key hash. The TemplateModel carries
    `{email, api_key, tier}` so the Postmark-side template can render the
    recipient's address in the greeting line and print the key once.

    Treat the returned dict the same way as every other helper: test-mode
    and transport errors surface as keyed dicts rather than exceptions so
    the Stripe webhook never fails because of a down mailer.
    """
    return _client_or(client)._send(
        to=to,
        template_alias=TEMPLATE_DAY0,
        template_model={
            "email": to,
            "api_key": api_key,
            "tier": tier,
            # `key_last4` kept for Postmark-side template parity with the
            # rest of the sequence; `api_key` is the one-time surface.
            "key_last4": api_key[-4:] if api_key else "????",
        },
        tag="onboarding-day0",
    )


# ---------------------------------------------------------------------------
# Day 1 — quick-win nudge: 3 "if stuck, try this" recipes
# ---------------------------------------------------------------------------


def send_day1_quick_win(
    *,
    to: str,
    api_key_last4: str,
    tier: str,
    usage_count: int,
    unsubscribe_url: str = "{{{pm:unsubscribe}}}",
    client: PostmarkClient | None = None,
) -> dict[str, Any]:
    """D+1 — quick-win recipes (facet search / MCP config / batch).

    Designed to fire ~24h after key issuance as the first cron-dispatched
    mail of the sequence. We do NOT skip on `usage_count > 0`; a customer
    who has made one ping call still benefits from seeing the facet /
    batch / MCP shapes they have not yet tried.

    `unsubscribe_url` defaults to Postmark's built-in `{{{pm:unsubscribe}}}`
    placeholder so the rendered email carries a one-click unsubscribe link
    (APPI / CAN-SPAM equivalents). Callers may override for ops-initiated
    resends where a custom one-click token is desired.
    """
    return _client_or(client)._send(
        to=to,
        template_alias=TEMPLATE_DAY1,
        template_model={
            "key_last4": api_key_last4,
            "tier": tier,
            "usage_count": usage_count,
            "unsubscribe_url": unsubscribe_url,
        },
        tag="onboarding-day1",
    )


# ---------------------------------------------------------------------------
# Day 3 — activation: three real curls + MCP snippet
# ---------------------------------------------------------------------------


def send_day3_activation(
    *,
    to: str,
    api_key_last4: str,
    tier: str,
    usage_count: int,
    client: PostmarkClient | None = None,
) -> dict[str, Any]:
    """D+3 activation — three example curls with REAL unified_ids + MCP config.

    `usage_count` is *informational* only — the copy adapts ("もう鍵を使った
    方へ" vs "まだの方") but we do NOT skip. Every D+3 customer gets
    activation examples; a user who already sent a request on D+1 still
    benefits from seeing what the OTHER endpoints look like.

    The three `unified_id`s baked into the template (`_DAY3_EXAMPLE_IDS`)
    are passed through explicitly so the template renders without any DB
    lookup — Postmark's template engine has no DB.
    """
    return _client_or(client)._send(
        to=to,
        template_alias=TEMPLATE_DAY3,
        template_model={
            "key_last4": api_key_last4,
            "tier": tier,
            "usage_count": usage_count,
            "has_used_key": usage_count > 0,
            "examples": list(_DAY3_EXAMPLE_IDS),
        },
        tag="onboarding-day3",
    )


# ---------------------------------------------------------------------------
# Day 7 — value: usage reflection + power features
# ---------------------------------------------------------------------------


def send_day7_value(
    *,
    to: str,
    api_key_last4: str,
    tier: str,
    usage_count: int,
    client: PostmarkClient | None = None,
) -> dict[str, Any]:
    """D+7 value — personalised usage stat + pointer to two power features.

    Copy says "あなたの <N> 回のクエリで〜" and then highlights:
        * 排他ルール check (`/v1/exclusions/check`) — avoid stacking
          mutually exclusive subsidies.
        * `source_mentions_json` — every program carries the citations it
          was derived from; makes audit defensible.

    Links to the examples doc (the in-repo cookbook equivalent). We do NOT
    reference a nonexistent `docs/prompt_cookbook.md` — the live anchor is
    `docs/examples.md` which the static site renders at `/examples/`.
    """
    return _client_or(client)._send(
        to=to,
        template_alias=TEMPLATE_DAY7,
        template_model={
            "key_last4": api_key_last4,
            "tier": tier,
            "usage_count": usage_count,
        },
        tag="onboarding-day7",
    )


# ---------------------------------------------------------------------------
# Day 14 — power-user tips (MCP / batch / monthly_cap_yen)
# ---------------------------------------------------------------------------


def send_day14_inactive_reminder(
    *,
    to: str,
    api_key_last4: str,
    tier: str,
    usage_count: int,
    client: PostmarkClient | None = None,
) -> dict[str, Any]:
    """D+14 — power-user tips (MCP integration, /programs/batch, monthly_cap_yen).

    Renamed in spirit (function symbol kept for scheduler back-compat) on
    2026-04-29. The original "inactive reminder" framing was deprecated —
    a customer who is paying but inactive at D+14 is better served by D+30
    feedback ask, not another nudge mail. The new D+14 spotlights three
    operational features that turn casual usage into production usage:

      * MCP wiring (Claude / Cursor / Cline) — push the curl loop into the LLM.
      * /programs/batch — N entities, 1 request, 1 ¥3.30 charge.
      * monthly_cap_yen — hard ¥ ceiling per key (JST 月初 reset).

    Sent regardless of `usage_count` — the copy is useful for both
    high-frequency users (production guardrails) and one-off users
    (lowering the friction to come back). The scheduler no longer treats
    `{"skipped": True, "reason": "active"}` returns specially because we
    no longer emit them; the legacy branch in scheduler.run_due remains a
    no-op for any caller that supplies a custom usage_count_fn that
    legitimately wants to skip.
    """
    return _client_or(client)._send(
        to=to,
        template_alias=TEMPLATE_DAY14,
        template_model={
            "key_last4": api_key_last4,
            "tier": tier,
            "usage_count": usage_count,
        },
        tag="onboarding-day14",
    )


# ---------------------------------------------------------------------------
# Day 30 — feedback (one open-ended question, no scale)
# ---------------------------------------------------------------------------


def send_day30_feedback(
    *,
    to: str,
    api_key_last4: str,
    tier: str,
    usage_count: int,
    client: PostmarkClient | None = None,
) -> dict[str, Any]:
    """D+30 — single open-ended feedback ask. NO NPS scale.

    Design constraint: ONE question, no number, no form. The 2026-04-29
    redesign deliberately dropped the 0-10 NPS scale: solo-ops zero-touch
    has no resources to triage NPS scores at scale, and a free-text reply
    surfaces signal that a number cannot ("I'd pay double if you added
    the 〇〇 dataset" / "MCP setup ate two hours, please document
    Cline-specific timeout"). The reply lands in POSTMARK_FROM_REPLY
    which is the operator's monitored mailbox.

    We send regardless of `usage_count` because the signal from an
    inactive 30-day user is itself the most valuable data point
    ("I paid and never used it because…"). The copy branches on
    `has_used_key` so active vs inactive customers get differently framed
    asks (active: "what would make it better?" / inactive: "why didn't
    you start?"). This is the LAST automated mail in the onboarding
    sequence; subsequent contact is operator-initiated only.
    """
    return _client_or(client)._send(
        to=to,
        template_alias=TEMPLATE_DAY30,
        template_model={
            "key_last4": api_key_last4,
            "tier": tier,
            "usage_count": usage_count,
            "has_used_key": usage_count > 0,
        },
        tag="onboarding-day30",
    )


__all__ = [
    "TEMPLATE_DAY0",
    "TEMPLATE_DAY1",
    "TEMPLATE_DAY3",
    "TEMPLATE_DAY7",
    "TEMPLATE_DAY14",
    "TEMPLATE_DAY30",
    "send_day0_welcome",
    "send_day1_quick_win",
    "send_day3_activation",
    "send_day7_value",
    "send_day14_inactive_reminder",
    "send_day30_feedback",
]
