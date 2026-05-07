"""Workflow integration endpoints — Slack / Google Sheets / Email / Excel / kintone.

Single thin server route file backing the **Top 5 zero-touch workflow
integrations**. Each integration is a different inbound shape that ultimately
calls the existing ``/v1/programs/search`` body builder + ``log_usage``
(``programs.search`` endpoint name → ¥3/req metered for paid keys, anonymous
3/日 IP cap for unauthenticated).

Design constraints (non-negotiable, per project memory):

* **No per-customer OAuth flow** on any of the 5 — auth is always
  ``X-API-Key`` (header) OR ``?key=`` (query, Excel-only fallback because
  ``WEBSERVICE`` cannot send headers).
* **No hosted UI per platform.** Config surface is the platform's own admin
  (Slack workspace settings, Apps Script properties, Postmark inbound
  address, Excel cell, kintone plugin config) OR our existing
  ``/v1/me/connectors`` JSON API (future, not built here).
* **§52 disclaimer in every response** — verbatim string from
  ``api/tax_rulesets.py`` ``_TAX_DISCLAIMER`` so the customer-facing legal
  fence is identical across surfaces.
* **Brand:** jpcite.
* **Each invocation = ¥3 metered** — slash command, sheets call, email
  reply, Excel cell refresh, kintone button click all bill identically.

Endpoints (mounted at ``/v1/integrations/*``):

  POST /v1/integrations/slack             — Slack slash command (form-urlencoded)
  POST /v1/integrations/slack/webhook     — Slack incoming-webhook drop-in
  POST /v1/integrations/sheets            — Google Sheets Apps Script callback
  POST /v1/integrations/email/inbound     — Postmark inbound JSON
  GET  /v1/integrations/excel             — Excel WEBSERVICE (?key=&q=)
  POST /v1/integrations/kintone           — kintone plugin button (JSON)

All routes are non-cached (each call bills) and cap response sizes to
``MAX_INTEGRATION_RESULTS`` rows so a runaway Sheet open / kintone button
mash cannot turn one click into a ¥3,000 bill. Per-IP rate floors are
inherited from ``PerIpEndpointLimitMiddleware`` plus
``RateLimitMiddleware``; Excel additionally gets a stricter cap because
``?key=`` is logged in proxy access logs and easier to leak.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._integration_tokens import (
    load_account,
    record_sync,
    revoke_account,
    upsert_account,
)
from jpintel_mcp.api.deps import (
    ApiContext,
    ApiContextDep,
    DbDep,
    hash_api_key,
    log_usage,
)
from jpintel_mcp.api.programs import _build_search_response
from jpintel_mcp.api.tax_rulesets import _TAX_DISCLAIMER

logger = logging.getLogger("jpintel.integrations")

router = APIRouter(prefix="/v1/integrations", tags=["integrations"])

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Cap on row count returned through any integration. Slack/Sheets/Email/Excel
# /kintone responses are display surfaces — beyond ~5 rows the formatting
# breaks down (Slack message limits, Sheets cell wrap, kintone modal scroll).
# Capping here also caps spend per call: a Sheet that holds 100 cells with
# `=ZEIMUKAIKEI(...)` cannot blow past 100 × 1 = 100 calls × ¥3.
MAX_INTEGRATION_RESULTS = 5

# §52 footer rendered into Slack/Sheets/Email/Excel/kintone bodies. Mirrors
# `_TAX_DISCLAIMER` so all 5 surfaces speak with one voice.
SECTION_52_FOOTER = _TAX_DISCLAIMER

# Plain-text condensed footer for tight surfaces (Slack ephemeral, Excel
# cell, kintone modal). Slack/Sheets attach this verbatim.
SECTION_52_FOOTER_SHORT = (
    "本情報は税務助言ではありません (税理士法 §52)。個別案件は税理士にご相談ください。"
)

# Brand line surfaced in HTML/email bodies + Excel A1 cell.
BRAND_LINE = "jpcite"

# Subject parser for Postmark inbound: extract API key from plus-addressing
# (``query+am_xxx@jpcite.com``). Anchored, conservative — anything that
# does not match is rejected.
_PLUS_ADDR_RE = re.compile(r"^[^+@\s]+\+(am_[A-Za-z0-9_-]{16,80})@", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_key_to_ctx(db, raw_key: str | None) -> ApiContext:
    """Same row-resolution logic as ``deps.require_key`` but synchronous.

    Used by the integration routes that take ``?key=`` or
    ``application/x-www-form-urlencoded`` parameters instead of the
    standard header. We deliberately do NOT raise the 401 trial-revoke
    HTML envelope here — integrations always return platform-shaped
    plaintext / JSON, never the dashboard-style trial cap dialog. A
    revoked / unknown key falls through to anonymous (3/日 IP) so the
    integration still works for an evaluator probing a stale template.
    """
    if not raw_key:
        return ApiContext(key_hash=None, tier="free", customer_id=None)
    raw_key = raw_key.strip()
    if not raw_key.startswith(("am_", "sk_")):
        return ApiContext(key_hash=None, tier="free", customer_id=None)
    try:
        key_hash = hash_api_key(raw_key)
        row = db.execute(
            "SELECT tier, customer_id, stripe_subscription_id, revoked_at "
            "FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()
    except Exception:  # noqa: BLE001 — defensive: never 500 on a Slack call
        return ApiContext(key_hash=None, tier="free", customer_id=None)
    if row is None or row["revoked_at"]:
        return ApiContext(key_hash=None, tier="free", customer_id=None)
    return ApiContext(
        key_hash=key_hash,
        tier=row["tier"],
        customer_id=row["customer_id"],
        stripe_subscription_id=row["stripe_subscription_id"],
    )


def _run_search(
    *,
    db,
    q: str | None,
    prefecture: str | None = None,
    target_type: list[str] | None = None,
    limit: int = MAX_INTEGRATION_RESULTS,
) -> dict[str, Any]:
    """Call the canonical search builder with integration-safe defaults.

    Always uses ``fields="default"`` (no per-tier gate trip) and clamps
    ``limit <= MAX_INTEGRATION_RESULTS``. Failure returns a safe empty
    envelope so a Slack post never 500s on a Saturday.
    """
    safe_limit = max(1, min(limit, MAX_INTEGRATION_RESULTS))
    try:
        body = _build_search_response(
            conn=db,
            q=q,
            tier=None,
            prefecture=prefecture,
            authority_level=None,
            funding_purpose=None,
            target_type=target_type,
            amount_min=None,
            amount_max=None,
            include_excluded=False,
            limit=safe_limit,
            offset=0,
            fields="default",
            include_advisors=False,
            as_of_iso=None,
        )
    except Exception:  # noqa: BLE001 — never 500 to a workflow surface
        logger.exception("integrations.search_failed q=%s", (q or "")[:80])
        return {"total": 0, "results": []}
    return body


def _row_summary(row: dict[str, Any]) -> dict[str, str]:
    """Reduce a `Program` dict to the 4 fields every integration renders."""
    name = row.get("primary_name") or row.get("name") or "(無題)"
    pref = row.get("prefecture") or "全国"
    authority = row.get("authority_name") or row.get("authority") or ""
    amount = row.get("amount_max_man_yen")
    amount_label = f"上限 {int(amount):,} 万円" if amount else "金額: 公表値なし"
    url = row.get("official_url") or row.get("source_url") or ""
    return {
        "name": str(name),
        "prefecture": str(pref),
        "authority": str(authority),
        "amount": amount_label,
        "url": str(url),
    }


def _bill_one_call(
    *,
    db,
    ctx: ApiContext,
    background_tasks: BackgroundTasks | None,
    request: Request,
    integration: str,
    result_count: int,
) -> None:
    """Charge exactly one ``programs.search`` event per integration call.

    Anonymous callers (``ctx.key_hash`` None) are not billed — the
    anonymous 3/日 IP quota already capped them upstream via the
    ``AnonIpLimitDep`` mounted on this router. Authenticated paid callers
    bill ¥3 (税込 ¥3.30) per integration invocation.
    """
    if ctx.key_hash is None:
        return
    log_usage(
        db,
        ctx,
        "programs.search",
        params={"integration": integration},
        latency_ms=None,
        result_count=result_count,
        background_tasks=background_tasks,
        request=request,
        strict_metering=True,
    )


# ---------------------------------------------------------------------------
# 1) Slack — slash command + incoming webhook
# ---------------------------------------------------------------------------


@router.post(
    "/slack",
    summary="Slack slash command",
    description=(
        "Slack POSTs ``application/x-www-form-urlencoded`` from a workspace "
        "slash command (e.g. ``/zeimukaikei DX 製造業``). The request "
        "carries `text=` (the user's query) and integration auth via "
        "``?key=am_...`` (since Slack cannot inject custom headers per call). "
        "Response shape is Slack's standard `{response_type, text, blocks}` "
        "with §52 footer in the last block."
    ),
)
async def slack_slash_command(
    request: Request,
    db: DbDep,
    background_tasks: BackgroundTasks,
    text: Annotated[str, Form()] = "",
    team_id: Annotated[str | None, Form()] = None,
    user_id: Annotated[str | None, Form()] = None,
    command: Annotated[str | None, Form()] = None,
    key: Annotated[str | None, Query()] = None,
) -> JSONResponse:
    ctx = _resolve_key_to_ctx(db, key)
    query = (text or "").strip()
    if not query:
        return JSONResponse(
            content={
                "response_type": "ephemeral",
                "text": (
                    "使い方: `/zeimukaikei <キーワード>` (例: `/zeimukaikei DX 製造業`)\n"
                    + SECTION_52_FOOTER_SHORT
                ),
            }
        )

    body = _run_search(db=db, q=query)
    rows = body.get("results", [])[:MAX_INTEGRATION_RESULTS]
    _bill_one_call(
        db=db,
        ctx=ctx,
        background_tasks=background_tasks,
        request=request,
        integration="slack",
        result_count=len(rows),
    )

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*jpcite* で `{query}` を検索: "
                    f"{body.get('total', 0)} 件 (上位 {len(rows)} 件表示)"
                ),
            },
        }
    ]
    if not rows:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "条件に合う制度が見つかりませんでした。",
                },
            }
        )
    for r in rows:
        s = _row_summary(r)
        line = (
            f"*<{s['url']}|{s['name']}>* — {s['prefecture']}\n_{s['authority']}_ — {s['amount']}"
            if s["url"]
            else f"*{s['name']}* — {s['prefecture']}\n_{s['authority']}_ — {s['amount']}"
        )
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": line}})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"_{SECTION_52_FOOTER_SHORT}_"},
                {"type": "mrkdwn", "text": f"_{BRAND_LINE}_"},
            ],
        }
    )
    return JSONResponse(
        content={
            "response_type": "in_channel",
            "text": f"jpcite: {query}",
            "blocks": blocks,
        }
    )


@router.post(
    "/slack/webhook",
    summary="Slack incoming webhook drop-in",
    description=(
        "Drop-in shape for Slack-compatible relays (Discord/Teams in their "
        "Slack-compat mode, Mattermost). Accepts JSON ``{text}`` or "
        "``{query}`` and returns Slack's `{response_type, text, blocks}` "
        "envelope — same body as ``/slack`` above."
    ),
)
async def slack_incoming_webhook(
    request: Request,
    db: DbDep,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any],
    key: Annotated[str | None, Query()] = None,
) -> JSONResponse:
    ctx = _resolve_key_to_ctx(db, key)
    query = (payload.get("text") or payload.get("query") or "").strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="text or query field required",
        )
    body = _run_search(db=db, q=query)
    rows = body.get("results", [])[:MAX_INTEGRATION_RESULTS]
    _bill_one_call(
        db=db,
        ctx=ctx,
        background_tasks=background_tasks,
        request=request,
        integration="slack_webhook",
        result_count=len(rows),
    )
    return JSONResponse(
        content={
            "response_type": "in_channel",
            "text": f"jpcite: {query}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (f"`{query}`: {body.get('total', 0)} 件 (上位 {len(rows)} 件)"),
                    },
                },
                *[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"*<{_row_summary(r)['url']}|{_row_summary(r)['name']}>*"
                                if _row_summary(r)["url"]
                                else f"*{_row_summary(r)['name']}*"
                            ),
                        },
                    }
                    for r in rows
                ],
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": SECTION_52_FOOTER_SHORT}],
                },
            ],
        }
    )


# ---------------------------------------------------------------------------
# 2) Google Sheets — Apps Script callback (=ZEIMUKAIKEI)
# ---------------------------------------------------------------------------


class SheetsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = Field(..., min_length=1, max_length=200)
    field: str | None = Field(
        default="title",
        description=(
            "Which scalar to return for the FIRST result. One of: "
            "`title`, `url`, `prefecture`, `authority`, `amount`, "
            "`disclaimer`. Returns `''` if no results."
        ),
    )


@router.post(
    "/sheets",
    summary="Google Sheets Apps Script callback",
    description=(
        "Google Sheets Apps Script template POSTs JSON `{query, field}`. "
        "Returns `{value, footer, source_url}` "
        "as a tight scalar so a single sheet cell can render. The Apps "
        "Script wrapper caches 6h via `CacheService` to bound spend on "
        "Sheet-open recalc."
    ),
)
async def sheets_callback(
    request: Request,
    db: DbDep,
    background_tasks: BackgroundTasks,
    body: SheetsRequest,
    key: Annotated[str | None, Query()] = None,
) -> JSONResponse:
    ctx = _resolve_key_to_ctx(db, key)
    search_body = _run_search(db=db, q=body.query, limit=1)
    rows = search_body.get("results", [])
    if not rows:
        _bill_one_call(
            db=db,
            ctx=ctx,
            background_tasks=background_tasks,
            request=request,
            integration="sheets",
            result_count=0,
        )
        return JSONResponse(
            content={
                "value": "",
                "footer": SECTION_52_FOOTER_SHORT,
                "source_url": "",
                "total": 0,
            }
        )
    s = _row_summary(rows[0])
    field = (body.field or "title").lower()
    value_map = {
        "title": s["name"],
        "url": s["url"],
        "prefecture": s["prefecture"],
        "authority": s["authority"],
        "amount": s["amount"],
        "disclaimer": SECTION_52_FOOTER_SHORT,
    }
    value = value_map.get(field, s["name"])
    _bill_one_call(
        db=db,
        ctx=ctx,
        background_tasks=background_tasks,
        request=request,
        integration="sheets",
        result_count=1,
    )
    return JSONResponse(
        content={
            "value": value,
            "footer": SECTION_52_FOOTER_SHORT,
            "source_url": s["url"],
            "total": int(search_body.get("total", 0)),
        }
    )


# ---------------------------------------------------------------------------
# 3) Email — Postmark inbound webhook
# ---------------------------------------------------------------------------


@router.post(
    "/email/inbound",
    summary="Postmark inbound email webhook",
    description=(
        "Customers email `query+am_xxx@jpcite.com`. Postmark POSTs "
        "the parsed email JSON to this endpoint. The plus-address tail "
        "carries the API key (`am_xxx`); the subject carries the query "
        "string. We reply via Postmark's outbound API with HTML + plain "
        "body and §52 footer. The `From:` address must be on the API "
        "key's whitelist (set once via `/v1/me/connectors/email`)."
    ),
)
async def email_inbound(
    request: Request,
    db: DbDep,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any],
    x_postmark_webhook_token: Annotated[
        str | None, Header(alias="X-Postmark-Webhook-Token")
    ] = None,
) -> JSONResponse:
    # Optional webhook-token auth. Postmark lets the operator configure
    # an inbound parse webhook with a custom token header; when set, every
    # POST carries `X-Postmark-Webhook-Token: <token>` and we drop any
    # request that lacks the matching value. Keeps the route from being a
    # public spam relay if the parse domain leaks. When the env var is
    # unset (dev/test) we accept the request — solo-ops onboarding.
    expected_token = os.environ.get("POSTMARK_INBOUND_WEBHOOK_TOKEN", "").strip()
    if expected_token:
        provided = (x_postmark_webhook_token or "").strip()
        if not provided or not secrets.compare_digest(provided, expected_token):
            logger.warning(
                "email.inbound.webhook_token_mismatch provided_len=%d",
                len(provided),
            )
            # 401 (not 403) so a misconfigured Postmark sees the same code
            # as an unauthenticated caller — see api/email_webhook.py.
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid postmark webhook token")
    # Postmark inbound JSON: documented at
    # https://postmarkapp.com/developer/user-guide/inbound/parse-an-email
    to_full = (
        payload.get("OriginalRecipient")
        or payload.get("ToFull", [{}])[0].get("Email", "")
        or payload.get("To", "")
    )
    from_email = (
        (payload.get("FromFull", {}).get("Email") or payload.get("From", "")).strip().lower()
    )
    subject = (payload.get("Subject") or "").strip()
    msg_id = payload.get("MessageID") or ""

    # Extract API key from plus-addressing.
    api_key: str | None = None
    if to_full:
        m = _PLUS_ADDR_RE.match(to_full.strip())
        if m:
            api_key = m.group(1)
    ctx = _resolve_key_to_ctx(db, api_key)

    # `from` whitelist enforcement (per-key allowlist set via dashboard).
    # When the key is unknown / anonymous we silently drop — replying
    # could enable a "spray API key into plus-address" probe.
    if ctx.key_hash is None:
        logger.info("email.inbound.unknown_key to=%s msg=%s", to_full, msg_id)
        return JSONResponse(content={"status": "ignored", "reason": "unknown_key"})
    allowed_from = _email_whitelist_for_key(db, ctx.key_hash)
    if allowed_from and from_email not in allowed_from:
        logger.info(
            "email.inbound.from_not_whitelisted from=%s key_hash_prefix=%s",
            from_email,
            ctx.key_hash[:8],
        )
        return JSONResponse(content={"status": "ignored", "reason": "from_not_whitelisted"})

    query = subject or "補助金"
    body_resp = _run_search(db=db, q=query)
    rows = body_resp.get("results", [])[:MAX_INTEGRATION_RESULTS]
    _bill_one_call(
        db=db,
        ctx=ctx,
        background_tasks=background_tasks,
        request=request,
        integration="email",
        result_count=len(rows),
    )

    # Compose reply via existing Postmark client. Best-effort — Postmark
    # delivery failure is logged but never 500s the webhook so Postmark
    # does not retry-storm.
    try:
        from jpintel_mcp.email.postmark import get_client

        client = get_client()
        html, text = _email_reply_bodies(query, rows, body_resp.get("total", 0))
        client._send(
            to=from_email,
            template_alias="zeimukaikei-search-reply",
            template_model={
                "query": query,
                "html_body": html,
                "text_body": text,
                "footer": SECTION_52_FOOTER,
                "brand_line": BRAND_LINE,
            },
            tag="integrations.email",
        )
    except Exception:  # noqa: BLE001
        logger.exception("email.inbound.reply_failed to=%s", from_email)

    return JSONResponse(content={"status": "ok", "matched": len(rows)})


def _email_whitelist_for_key(db, key_hash: str) -> set[str]:
    """Return the per-key allowed `from` email set.

    Reads from ``api_key_email_whitelist`` (created by the future
    `/v1/me/connectors/email` route). When the table does not exist OR
    the key has no whitelist row, return an empty set — empty whitelist
    means "no policy set" → accept any sender. The route is FREE / no
    DPA, so we leave the policy enforcement up to the customer.
    """
    try:
        rows = db.execute(
            "SELECT from_email FROM api_key_email_whitelist WHERE key_hash = ?",
            (key_hash,),
        ).fetchall()
    except Exception:
        return set()
    return {(r["from_email"] or "").strip().lower() for r in rows if r["from_email"]}


def _email_reply_bodies(query: str, rows: list[dict[str, Any]], total: int) -> tuple[str, str]:
    """Render HTML + plaintext email bodies for the auto-reply."""
    summaries = [_row_summary(r) for r in rows]
    if summaries:
        text_lines = [
            f"検索: {query}",
            f"件数: {total} 件 (上位 {len(summaries)} 件)",
            "",
        ]
        html_items = []
        for s in summaries:
            text_lines.append(
                f"- {s['name']} ({s['prefecture']}) — {s['authority']} — {s['amount']}"
            )
            if s["url"]:
                text_lines.append(f"  {s['url']}")
            html_items.append(
                "<li>"
                f'<a href="{s["url"]}"><b>{s["name"]}</b></a> '
                f"({s['prefecture']}) — {s['authority']} — {s['amount']}"
                "</li>"
            )
        text_body = "\n".join(text_lines + ["", SECTION_52_FOOTER, BRAND_LINE])
        html_body = (
            f"<p><b>検索: </b>{query}</p>"
            f"<p>{total} 件中 上位 {len(summaries)} 件:</p>"
            f"<ul>{''.join(html_items)}</ul>"
            f"<hr><p><small>{SECTION_52_FOOTER}</small></p>"
            f"<p><small>{BRAND_LINE}</small></p>"
        )
    else:
        text_body = (
            f"検索: {query}\n0 件ヒットしませんでした。\n\n{SECTION_52_FOOTER}\n{BRAND_LINE}"
        )
        html_body = (
            f"<p><b>検索: </b>{query}</p>"
            "<p>0 件ヒットしませんでした。</p>"
            f"<hr><p><small>{SECTION_52_FOOTER}</small></p>"
            f"<p><small>{BRAND_LINE}</small></p>"
        )
    return html_body, text_body


# ---------------------------------------------------------------------------
# 4) Excel — WEBSERVICE template (text/plain response)
# ---------------------------------------------------------------------------


@router.get(
    "/excel",
    summary="Excel WEBSERVICE template endpoint",
    description=(
        "Excel's `WEBSERVICE` formula cannot send headers, so auth is "
        "via `?key=` query param. Response is `text/plain` so the cell "
        "renders a single-line answer. `?field=` selects which scalar to "
        "return (title|url|prefecture|authority|amount|footer|count). "
        "§52 footer is also surfaced in the named cell `A1` of the "
        "downloadable Excel template."
    ),
    response_class=PlainTextResponse,
)
async def excel_webservice(
    request: Request,
    db: DbDep,
    background_tasks: BackgroundTasks,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    key: Annotated[str | None, Query()] = None,
    field: Annotated[str, Query()] = "title",
) -> PlainTextResponse:
    ctx = _resolve_key_to_ctx(db, key)
    if field == "footer":
        return PlainTextResponse(SECTION_52_FOOTER_SHORT)
    body = _run_search(db=db, q=q, limit=1)
    rows = body.get("results", [])
    _bill_one_call(
        db=db,
        ctx=ctx,
        background_tasks=background_tasks,
        request=request,
        integration="excel",
        result_count=len(rows),
    )
    if not rows:
        if field == "count":
            return PlainTextResponse("0")
        return PlainTextResponse("")
    s = _row_summary(rows[0])
    value_map = {
        "title": s["name"],
        "url": s["url"],
        "prefecture": s["prefecture"],
        "authority": s["authority"],
        "amount": s["amount"],
        "count": str(int(body.get("total", 0))),
    }
    return PlainTextResponse(value_map.get(field, s["name"]))


# ---------------------------------------------------------------------------
# 5) kintone — plugin button callback
# ---------------------------------------------------------------------------


class KintoneRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = Field(..., min_length=1, max_length=200)
    prefecture: str | None = Field(default=None, max_length=20)
    target_type: list[str] | None = Field(default=None, max_length=8)
    record_id: str | None = Field(
        default=None,
        max_length=64,
        description="Calling kintone record id (logged for audit, not used to filter)",
    )


@router.post(
    "/kintone",
    summary="kintone plugin button callback",
    description=(
        "jpcite kintone plugin "
        "fetches this endpoint when the user clicks the in-record button "
        '"jpcite で関連補助金検索". Returns a JSON envelope the plugin '
        "renders into a modal + writes top result into configured fields. "
        "Origins `*.cybozu.com` / `*.kintone.com` are CORS-allowlisted in "
        "approved kintone domains."
    ),
)
async def kintone_callback(
    request: Request,
    db: DbDep,
    background_tasks: BackgroundTasks,
    body: KintoneRequest,
    key: Annotated[str | None, Query()] = None,
) -> JSONResponse:
    ctx = _resolve_key_to_ctx(db, key)
    search_body = _run_search(
        db=db,
        q=body.query,
        prefecture=body.prefecture,
        target_type=body.target_type,
    )
    rows = search_body.get("results", [])[:MAX_INTEGRATION_RESULTS]
    _bill_one_call(
        db=db,
        ctx=ctx,
        background_tasks=background_tasks,
        request=request,
        integration="kintone",
        result_count=len(rows),
    )
    summaries = [_row_summary(r) for r in rows]
    return JSONResponse(
        content={
            "query": body.query,
            "total": int(search_body.get("total", 0)),
            "results": summaries,
            "footer": SECTION_52_FOOTER,
            "footer_short": SECTION_52_FOOTER_SHORT,
            "brand": BRAND_LINE,
            "record_id": body.record_id,
        }
    )


# ---------------------------------------------------------------------------
# 6) Google Sheets — OAuth start + callback + token-backed account binding
# ---------------------------------------------------------------------------
#
# Why a separate code path from the slash-command sheets_callback above:
# the slash-command path uses ?key= auth and writes nothing back to the
# customer's sheet — it serves the `=ZEIMUKAIKEI(...)` cell formula. This
# OAuth path lets the customer give us write access to a specific sheet
# so the daily saved_searches cron can append rows server-side.
#
# Manual operator setup required (docs/_internal/integrations_setup.md):
#   * GOOGLE_OAUTH_CLIENT_ID  / GOOGLE_OAUTH_CLIENT_SECRET env vars
#   * Google Cloud project with Sheets API enabled, Authorized redirect
#     URI = https://api.jpcite.com/v1/integrations/google/callback
#
# Per project memory ("Solo + zero-touch"): we cannot human-approve OAuth
# requests. The customer self-completes via Google's consent screen; on
# success we drop the encrypted refresh token and let the cron run.

_GOOGLE_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/userinfo.email"
)


def _google_oauth_redirect_uri() -> str:
    base = os.environ.get("JPINTEL_API_BASE_URL", "https://api.jpcite.com").rstrip("/")
    return f"{base}/v1/integrations/google/callback"


@router.post(
    "/google/start",
    summary="Begin Google Sheets OAuth flow",
    description=(
        "Returns a one-time ``authorize_url`` that the customer must open "
        "in a browser to grant Google Sheets write access. The state token "
        "is opaque and embeds the calling api_key_hash + a 16-byte nonce; "
        "the callback validates both. ``GOOGLE_OAUTH_CLIENT_ID`` env var "
        "must be set on the operator side before this works (503 otherwise)."
    ),
)
async def google_oauth_start(
    ctx: ApiContextDep,
    db: DbDep,
) -> JSONResponse:
    if ctx.key_hash is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key required to start OAuth")
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    if not client_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google Sheets integration not configured (operator must set GOOGLE_OAUTH_CLIENT_ID)",
        )
    nonce = secrets.token_urlsafe(16)
    # Store nonce keyed by api_key_hash so the callback can validate.
    # Reuses integration_accounts row schema with a 'pending_oauth' provider.
    db.execute(
        "INSERT OR REPLACE INTO integration_sync_log "
        "  (api_key_hash, provider, idempotency_key, status, result_count) "
        "VALUES (?, 'google_sheets_oauth_state', ?, 'pending', 0)",
        (ctx.key_hash, nonce),
    )
    db.commit()
    state = f"{ctx.key_hash[:16]}.{nonce}"
    params = {
        "client_id": client_id,
        "redirect_uri": _google_oauth_redirect_uri(),
        "response_type": "code",
        "scope": _GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return JSONResponse(
        content={
            "authorize_url": f"{_GOOGLE_AUTHORIZE}?{urllib.parse.urlencode(params)}",
            "state": state,
            "expires_in": 600,
        }
    )


@router.get(
    "/google/callback",
    summary="Google OAuth callback",
    description=(
        "Google redirects here after user consent. Exchanges the code for "
        "a refresh+access token pair and stores it Fernet-encrypted under "
        "``integration_accounts``. Redirects to the dashboard on success "
        "or returns a JSON error envelope on failure."
    ),
)
async def google_oauth_callback(
    db: DbDep,
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
):  # response is RedirectResponse on success; FastAPI cannot validate the
    # union (RedirectResponse + JSONResponse), so we drop the annotation.
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if not (client_id and client_secret):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google Sheets OAuth not configured on the operator side",
        )
    if "." not in state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "malformed state")
    key_prefix, nonce = state.split(".", 1)
    state_row = db.execute(
        "SELECT api_key_hash FROM integration_sync_log "
        "WHERE provider = 'google_sheets_oauth_state' AND idempotency_key = ?",
        (nonce,),
    ).fetchone()
    if state_row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired oauth state")
    api_key_hash = state_row["api_key_hash"]
    if not api_key_hash.startswith(key_prefix):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "state/api_key mismatch")

    # Exchange the code.
    body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": _google_oauth_redirect_uri(),
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        _GOOGLE_TOKEN,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json as _json

            tok = _json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.exception("google_oauth.exchange_failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"google token exchange failed: {type(exc).__name__}",
        ) from exc

    refresh = tok.get("refresh_token")
    access = tok.get("access_token")
    if not refresh or not access:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "google did not return refresh_token (re-consent required)",
        )

    upsert_account(
        db,
        api_key_hash=api_key_hash,
        provider="google_sheets",
        payload={
            "refresh_token": refresh,
            "access_token": access,
            "expires_in": int(tok.get("expires_in") or 3599),
            "scope": tok.get("scope") or _GOOGLE_SCOPES,
            "token_type": tok.get("token_type") or "Bearer",
        },
        display_handle=None,
    )
    # Drop the one-shot state row.
    db.execute(
        "DELETE FROM integration_sync_log "
        "WHERE provider = 'google_sheets_oauth_state' AND idempotency_key = ?",
        (nonce,),
    )
    db.commit()
    # Redirect into the dashboard's connectors panel.
    dashboard = os.environ.get("JPINTEL_DASHBOARD_URL", "https://jpcite.com/dashboard.html")
    return RedirectResponse(url=f"{dashboard}#integrations=google_sheets_ok", status_code=302)


@router.get(
    "/google/status",
    summary="Google Sheets connection status for the calling key",
)
async def google_status(ctx: ApiContextDep, db: DbDep) -> JSONResponse:
    if ctx.key_hash is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    payload = load_account(db, api_key_hash=ctx.key_hash, provider="google_sheets")
    return JSONResponse(
        content={
            "connected": payload is not None,
            "display_handle": (payload or {}).get("_display_handle"),
        }
    )


@router.delete(
    "/google",
    summary="Revoke the Google Sheets credential",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def google_revoke(ctx: ApiContextDep, db: DbDep) -> JSONResponse:
    if ctx.key_hash is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    revoke_account(db, api_key_hash=ctx.key_hash, provider="google_sheets")
    return JSONResponse(content={}, status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# 7) kintone — REST sync (different from /kintone plugin button above)
# ---------------------------------------------------------------------------
#
# The /kintone route earlier in this file is the in-record plugin button —
# customer clicks, gets a modal with results. The /kintone/sync route below
# is the OUTBOUND fan-out: the customer registers their kintone domain +
# app-id + API token once, and a daily cron pushes saved-search results
# into kintone records. Pure REST (no OAuth) — kintone uses static
# per-app API tokens.


# RFC 1035 host label: alphanumeric start, alphanumeric end (no trailing
# dash), alphanumeric or hyphen in the middle, single subdomain, then the
# Cybozu/kintone parent domain. Allowing a trailing-dash label slipped past
# the previous regex (re-tightened 2026-04-29 audit).
_KINTONE_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.(cybozu|kintone)\.com$", re.I)


class KintoneConnectRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    domain: str = Field(..., min_length=4, max_length=63, description="acme.cybozu.com")
    app_id: int = Field(..., ge=1, le=999_999_999)
    api_token: str = Field(..., min_length=8, max_length=512)


@router.post(
    "/kintone/connect",
    summary="Register a kintone API token + app for the calling key",
)
async def kintone_connect(
    payload: KintoneConnectRequest,
    ctx: ApiContextDep,
    db: DbDep,
) -> JSONResponse:
    if ctx.key_hash is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    if not _KINTONE_DOMAIN_RE.match(payload.domain.strip().lower()):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "domain must be of the form *.cybozu.com or *.kintone.com",
        )
    upsert_account(
        db,
        api_key_hash=ctx.key_hash,
        provider="kintone",
        payload={
            "domain": payload.domain.strip().lower(),
            "app_id": int(payload.app_id),
            "api_token": payload.api_token,
        },
        display_handle=f"{payload.domain.strip().lower()}/app/{payload.app_id}",
    )
    return JSONResponse(
        content={
            "ok": True,
            "domain": payload.domain.strip().lower(),
            "app_id": payload.app_id,
        }
    )


class KintoneSyncRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    saved_search_id: int = Field(..., ge=1)
    idempotency_key: str | None = Field(default=None, max_length=120)
    max_rows: int = Field(default=50, ge=1, le=200)


@router.post(
    "/kintone/sync",
    summary="Sync saved-search results into the customer's kintone app",
    description=(
        "Pulls the calling key's saved search, runs the canonical search, "
        "and POSTs the result rows into the customer's kintone app via "
        "``/k/v1/records.json``. One ¥3 charge per sync call regardless of "
        "row count (NOT 100×¥3 for 100 rows). Idempotency on "
        "``(provider='kintone', idempotency_key)``: a repeat call with the "
        "same key returns the cached row count and does NOT bill again."
    ),
)
async def kintone_sync(
    request: Request,
    payload: KintoneSyncRequest,
    ctx: ApiContextDep,
    db: DbDep,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    if ctx.key_hash is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    creds = load_account(db, api_key_hash=ctx.key_hash, provider="kintone")
    if not creds:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            "kintone not connected — POST /v1/integrations/kintone/connect first",
        )

    saved = db.execute(
        "SELECT id, query_json FROM saved_searches WHERE id = ? AND api_key_hash = ?",
        (payload.saved_search_id, ctx.key_hash),
    ).fetchone()
    if saved is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"saved search {payload.saved_search_id} not found",
        )

    import json as _json

    try:
        query = _json.loads(saved["query_json"]) if saved["query_json"] else {}
    except Exception:  # noqa: BLE001
        query = {}

    body = _run_search(
        db=db,
        q=query.get("q"),
        prefecture=query.get("prefecture"),
        target_type=query.get("target_type"),
        limit=payload.max_rows,
    )
    rows = body.get("results", [])[: payload.max_rows]

    # Idempotency: customer-supplied OR (saved_search_id + UTC date).
    idem_key = (
        payload.idempotency_key
        or f"ss{payload.saved_search_id}-{datetime.now(UTC).strftime('%Y%m%d')}"
    )
    is_new, _log_id = record_sync(
        db,
        api_key_hash=ctx.key_hash,
        provider="kintone",
        idempotency_key=idem_key,
        saved_search_id=payload.saved_search_id,
        status_label="ok",
        result_count=len(rows),
    )
    if not is_new:
        return JSONResponse(
            content={
                "ok": True,
                "deduped": True,
                "idempotency_key": idem_key,
                "synced_rows": len(rows),
                "footer": SECTION_52_FOOTER_SHORT,
            }
        )

    # Build kintone records payload — one record per program.
    records = []
    for r in rows:
        s = _row_summary(r)
        records.append(
            {
                "title": {"value": s["name"]},
                "prefecture": {"value": s["prefecture"]},
                "authority": {"value": s["authority"]},
                "amount_label": {"value": s["amount"]},
                "source_url": {"value": s["url"]},
                "synced_by": {"value": "jpcite"},
            }
        )

    # Bill before pushing rows into the external kintone app. If the final
    # cap check rejects the paid call, remove the optimistic idempotency row
    # so the customer can retry after resolving billing/cap state.
    try:
        log_usage(
            db,
            ctx,
            "programs.search",
            params={"integration": "kintone_sync", "rows": len(records)},
            latency_ms=None,
            result_count=len(records),
            background_tasks=background_tasks,
            request=request,
            strict_metering=True,
        )
    except HTTPException:
        db.execute(
            "DELETE FROM integration_sync_log WHERE id = ? AND provider = ?",
            (_log_id, "kintone"),
        )
        db.commit()
        raise

    domain = creds["domain"]
    app_id = creds["app_id"]
    api_token = creds["api_token"]
    posted = 0
    error_class = None
    if records:
        try:
            req = urllib.request.Request(
                f"https://{domain}/k/v1/records.json",
                method="POST",
                data=_json.dumps({"app": app_id, "records": records}, ensure_ascii=False).encode(
                    "utf-8"
                ),
                headers={
                    "Content-Type": "application/json",
                    "X-Cybozu-API-Token": api_token,
                },
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                if 200 <= resp.status < 300:
                    posted = len(records)
                else:
                    error_class = f"http_{resp.status}"
        except Exception as exc:  # noqa: BLE001
            error_class = type(exc).__name__
            logger.exception("kintone.sync.failed key_prefix=%s", ctx.key_hash[:8])

    if error_class:
        # Replace the optimistic 'ok' record with an error label so audit
        # is honest. We do NOT roll back the ¥3 — the call still consumed
        # compute and the customer can retry with a NEW idempotency_key.
        db.execute(
            "UPDATE integration_sync_log SET status = 'error', error_class = ? "
            "WHERE provider = 'kintone' AND idempotency_key = ?",
            (error_class, idem_key),
        )
        db.commit()

    return JSONResponse(
        content={
            "ok": error_class is None,
            "deduped": False,
            "idempotency_key": idem_key,
            "synced_rows": posted,
            "kintone_app": f"{domain}/app/{app_id}",
            "error_class": error_class,
            "footer": SECTION_52_FOOTER_SHORT,
        }
    )


# ---------------------------------------------------------------------------
# 8) Postmark inbound — operator config probe
# ---------------------------------------------------------------------------
#
# The actual /email/inbound webhook handler is defined earlier in this file
# (the slash-command-style path that decodes plus-addressing). This section
# adds a small connect endpoint so the customer can register their preferred
# reply-from address and so the dashboard can display "email inbound is
# configured" without scraping log lines.


class EmailConnectRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reply_from: str = Field(default="query@parse.jpcite.com", min_length=4, max_length=128)


@router.post(
    "/email/connect",
    summary="Mark email-inbound integration as enabled for this key",
    description=(
        "Records the calling key's preference for which inbound parse "
        "address to publish. The Postmark side (mapping the parse domain "
        "to the webhook URL) is a manual operator action — see "
        "``docs/_internal/integrations_setup.md``. This endpoint just "
        "flags that the customer wants the route enabled."
    ),
)
async def email_connect(
    payload: EmailConnectRequest, ctx: ApiContextDep, db: DbDep
) -> JSONResponse:
    if ctx.key_hash is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    upsert_account(
        db,
        api_key_hash=ctx.key_hash,
        provider="postmark_inbound",
        payload={"reply_from": payload.reply_from},
        display_handle=payload.reply_from,
    )
    return JSONResponse(content={"ok": True, "reply_from": payload.reply_from})


__all__ = ["router"]
