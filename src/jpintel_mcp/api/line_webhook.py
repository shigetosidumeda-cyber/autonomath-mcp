"""LINE Messaging API webhook receiver.

Single inbound endpoint backing the LINE bot product surface (one of the
8 cohort capture surfaces, "中小企業 LINE" in CLAUDE.md). Routes inbound
LINE events into the deterministic state machine in
``src/jpintel_mcp/line/flow.py`` and returns LINE Reply API messages.

Endpoint
--------
POST /v1/integrations/line/webhook

Signature verification
----------------------
LINE signs the raw POST body with the channel secret as HMAC-SHA256 and
delivers the base64-encoded digest in the ``X-Line-Signature`` header.
We compare constant-time against the expected value. Any mismatch
returns **401**, not 403 — same convention as the Postmark / Stripe
webhooks elsewhere in this project.

If ``LINE_CHANNEL_SECRET`` is empty we return **503** (dev mode never
auto-accepts an unsigned body — same defensive default as Postmark).

No LLM
------
This module never calls an LLM. The webhook synchronously:

  1. verifies the signature,
  2. parses the (LINE-shaped) JSON event payload,
  3. for each event:
     a. resolves / creates the ``line_users`` row,
     b. checks the monthly free quota (50 events / month / line_user
        when no parent api_key is attached),
     c. calls ``flow.advance(state, text)`` to compute the next reply,
     d. POSTs the reply to LINE's Reply API,
     e. logs the event in ``line_message_log`` (migration 106) with the
        billing decision (¥3 paid via parent api_key OR ¥0 free quota
        OR ¥0 quota_exceeded).

Billing
-------
* When ``line_users.parent_api_key_hash`` is non-NULL (rare in v1; the
  column hook is reserved for the 顧問先 fan-out path under migration
  086), each round-trip is metered as one ``programs.search`` event
  against that key — ¥3 (税込 ¥3.30).
* Otherwise, the round-trip counts against the line_user's monthly
  free allowance (50 events / month, JST 月初 reset). When the counter
  is exhausted the reply is the rate-limit explainer text and the event
  is logged with ``billed=0, quota_exceeded=1``.

The webhook is **idempotent** on (event_id, direction). LINE retries a
5xx delivery for up to ~24h; ``UNIQUE INDEX
idx_line_message_log_event_direction`` (migration 106) prevents
double-billing on retry.

Operator manual config
----------------------
The LINE Developers Console (Messaging API channel) requires four
operator-side actions that cannot ship as code:

  1. Create the channel (Messaging API).
  2. Set the webhook URL to ``https://api.jpcite.com/v1/integrations/line/webhook``.
  3. Disable the auto-reply / greeting messages (we own all replies).
  4. Configure the rich-menu via official-account-manager (`docs/_internal/
     line_bot_operator_setup.md` documents the 4-area menu layout).

The ``LINE_CHANNEL_SECRET`` and ``LINE_CHANNEL_ACCESS_TOKEN`` env vars
are populated from the Console after step 1.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import sqlite3  # noqa: TC003 (runtime: helpers below take sqlite3.Connection)
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import orjson
from fastapi import APIRouter, Header, HTTPException, Request, status

from jpintel_mcp.api.deps import DbDep  # noqa: TC001 (runtime for FastAPI Depends resolution)
from jpintel_mcp.line import flow as line_flow
from jpintel_mcp.line.config import line_settings

logger = logging.getLogger("jpintel.line.webhook")

router = APIRouter(prefix="/v1/integrations/line", tags=["integrations"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hard cap on body size. LINE webhook payload is bounded to 8 events ×
# small JSON each → in practice well under 50 KB. A 100 KB ceiling is
# generous and prevents a misbehaving relay from feeding us megabytes.
_MAX_BODY_BYTES = 100 * 1024  # 100 KB

# LINE Reply API endpoint (we POST replies here using channel access
# token bearer auth). Kept as a module-level constant so tests can
# monkeypatch a fake server.
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"

# Anonymous-equivalent monthly cap mirroring the core API's 50/month
# anonymous quota. The LINE bot's free path uses the same number so the
# user-facing rule is identical: 50 events per JST month per LINE user.
ANON_MONTHLY_CAP = 50

# Per-event ¥amount when billed against a parent API key. The rest of
# the system speaks "programs.search → ¥3" — we mirror that endpoint
# label so the metered Stripe meter and the per-customer dashboard
# rollup do not need a separate SKU.
LINE_BILLED_YEN_PER_EVENT = 3


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def verify_line_signature(body: bytes, provided: str | None) -> bool:
    """Constant-time HMAC-SHA256 verification of `X-Line-Signature`.

    LINE's `X-Line-Signature` is the base64-encoded SHA-256 HMAC of the
    raw request body using the channel secret as key. Reference:
    https://developers.line.biz/en/reference/messaging-api/#signature-validation

    Returns False — never raises — so the caller can decide the response
    code uniformly.
    """
    if not provided or not line_settings.channel_secret:
        return False
    mac = hmac.new(
        line_settings.channel_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(mac).decode("ascii")
    return hmac.compare_digest(expected, provided.strip())


# ---------------------------------------------------------------------------
# DB helpers — all parameterised, no string concatenation.
# ---------------------------------------------------------------------------


def _next_jst_month_reset(now_utc: datetime) -> str:
    """Compute the ISO-8601 UTC timestamp of the next JST 月初 00:00.

    We rely on a fixed +9:00 offset because the LINE bot does not need
    second-level precision and Japan does not observe DST. Returning UTC
    keeps the column comparable with the rest of the schema (which is
    UTC throughout).
    """
    # Translate to JST wall-clock by adding +9h.
    jst_now = now_utc + timedelta(hours=9)
    if jst_now.month == 12:
        next_jst = jst_now.replace(year=jst_now.year + 1, month=1, day=1,
                                   hour=0, minute=0, second=0, microsecond=0)
    else:
        next_jst = jst_now.replace(month=jst_now.month + 1, day=1,
                                   hour=0, minute=0, second=0, microsecond=0)
    # Translate back to UTC.
    return (next_jst - timedelta(hours=9)).replace(tzinfo=UTC).isoformat()


def _ensure_line_user(
    conn: sqlite3.Connection, line_user_id: str, *, display_name: str | None = None
) -> sqlite3.Row:
    """Idempotently fetch or insert a `line_users` row.

    Called on every inbound event because a user might have been
    silently re-following (LINE delivers `follow` only on initial add,
    not on re-add after unblock). Insert-on-miss is the cheapest and
    most idempotent shape.
    """
    row = conn.execute(
        "SELECT * FROM line_users WHERE line_user_id = ?",
        (line_user_id,),
    ).fetchone()
    if row is not None:
        return row
    now = datetime.now(UTC).isoformat()
    reset_at = _next_jst_month_reset(datetime.now(UTC))
    conn.execute(
        "INSERT INTO line_users("
        "  line_user_id, display_name, language, added_at, plan, "
        "  query_count_mtd, query_count_mtd_resets_at, updated_at"
        ") VALUES (?,?,?,?,?,?,?,?)",
        (line_user_id, display_name, "ja", now, "free", 0, reset_at, now),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM line_users WHERE line_user_id = ?",
        (line_user_id,),
    ).fetchone()


def _persist_flow_state(
    conn: sqlite3.Connection,
    line_user_id: str,
    next_state: line_flow.FlowState,
) -> None:
    """Write the post-event flow state back to `line_users`."""
    state_json = json.dumps(next_state, ensure_ascii=False)
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE line_users SET current_flow_state_json = ?, updated_at = ?, "
        "  last_query_at = ? WHERE line_user_id = ?",
        (state_json, now, now, line_user_id),
    )


def _check_and_decrement_quota(
    conn: sqlite3.Connection,
    user_row: sqlite3.Row,
    *,
    has_parent_key: bool,
) -> bool:
    """Return True iff this event may proceed without quota exhaustion.

    When the user has a parent api_key attached (rare in v1; reserved
    for the 顧問先 fan-out cohort), we always allow the event — billing
    happens via the parent's metered subscription, not the free quota.

    Otherwise we look at line_users.query_count_mtd. If the column's
    `resets_at` has elapsed we zero the counter and roll the boundary
    forward inline (self-healing — no cron needed).
    """
    if has_parent_key:
        return True

    now = datetime.now(UTC)
    resets_at = user_row["query_count_mtd_resets_at"]
    count = int(user_row["query_count_mtd"] or 0)
    try:
        resets_dt = datetime.fromisoformat(resets_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        # Defensive — column got corrupted; reset immediately.
        resets_dt = now - timedelta(seconds=1)

    if now >= resets_dt:
        new_reset = _next_jst_month_reset(now)
        conn.execute(
            "UPDATE line_users SET query_count_mtd = 1, "
            "  query_count_mtd_resets_at = ?, updated_at = ? "
            "WHERE line_user_id = ?",
            (new_reset, now.isoformat(), user_row["line_user_id"]),
        )
        return True

    if count >= ANON_MONTHLY_CAP:
        return False

    conn.execute(
        "UPDATE line_users SET query_count_mtd = query_count_mtd + 1, "
        "  updated_at = ? WHERE line_user_id = ?",
        (now.isoformat(), user_row["line_user_id"]),
    )
    return True


def _redact_payload(event: dict[str, Any]) -> dict[str, Any]:
    """Return a redacted copy of a LINE event for `line_message_log`.

    We strip:
      * replyToken — single-use auth token, no value past the same request
      * source.userId is kept (it's the same `line_user_id` we already
        store in the dedicated column, redundancy is fine)
      * any field longer than 256 chars is truncated to deter raw 個人情報
        leaking into the audit table from a misbehaving user typing in a
        phone number (not a typical pattern but worth defending).
    """
    redacted = dict(event)
    redacted.pop("replyToken", None)

    def _trunc(v: Any) -> Any:
        if isinstance(v, str) and len(v) > 256:
            return v[:256] + "...[truncated]"
        if isinstance(v, dict):
            return {k: _trunc(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_trunc(x) for x in v]
        return v

    return _trunc(redacted)


def _log_event(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    line_user_id: str | None,
    event_type: str,
    direction: str,
    flow_step: str | None,
    payload: dict[str, Any],
    billed: bool,
    quota_exceeded: bool,
    api_key_hash: str | None,
    received_at: datetime,
    processed_at: datetime | None,
) -> bool:
    """Insert a `line_message_log` row, idempotent on (event_id, direction).

    Returns True iff a fresh row was written (i.e. not a retry duplicate).
    """
    redacted = _redact_payload(payload)
    cur = conn.execute(
        "INSERT OR IGNORE INTO line_message_log("
        "  event_id, line_user_id, event_type, direction, flow_step, payload_json, "
        "  billed, billed_yen, quota_exceeded, api_key_hash, received_at, processed_at"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            event_id,
            line_user_id,
            event_type,
            direction,
            flow_step,
            json.dumps(redacted, ensure_ascii=False, default=str),
            1 if billed else 0,
            LINE_BILLED_YEN_PER_EVENT if billed else 0,
            1 if quota_exceeded else 0,
            api_key_hash,
            received_at.isoformat(),
            processed_at.isoformat() if processed_at else None,
        ),
    )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# LINE Reply API client (POST to api.line.me).
# ---------------------------------------------------------------------------


async def _post_line_reply(
    reply_token: str,
    messages: list[dict[str, Any]],
) -> bool:
    """POST a Reply API call. Lazy import of httpx to keep tests light.

    Returns True iff the upstream returned 2xx. False on any failure
    (network, timeout, 4xx) so the webhook continues processing other
    events in the batch rather than blowing up the whole POST.
    """
    if not line_settings.channel_access_token:
        logger.warning("line.reply.no_access_token")
        return False
    try:
        import httpx  # local import — keep cold-import budget low
    except ImportError:  # pragma: no cover — httpx is a base dependency
        logger.exception("line.reply.httpx_missing")
        return False

    headers = {
        "Authorization": f"Bearer {line_settings.channel_access_token}",
        "Content-Type": "application/json",
    }
    payload = {"replyToken": reply_token, "messages": messages[:5]}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(LINE_REPLY_URL, headers=headers, json=payload)
        if r.status_code >= 400:
            logger.warning(
                "line.reply.upstream_status status=%s body=%s",
                r.status_code,
                r.text[:300],
            )
            return False
        return True
    except Exception:  # noqa: BLE001 — never let LINE I/O 500 the webhook
        logger.exception("line.reply.upstream_error")
        return False


# ---------------------------------------------------------------------------
# Webhook handler
# ---------------------------------------------------------------------------


@router.post(
    "/webhook",
    summary="LINE Messaging API webhook receiver",
    description=(
        "LINE delivers a JSON envelope `{destination, events: [...]}`. "
        "We verify `X-Line-Signature` HMAC-SHA256 against the raw body, "
        "then dispatch each event into the deterministic state machine "
        "(NO LLM call). Replies are sent via LINE Reply API; each "
        "round-trip bills ¥3 against the user's parent API key OR is "
        "counted against the LINE user's 50-event/month free allowance."
    ),
)
async def line_webhook(
    request: Request,
    conn: DbDep,
    x_line_signature: Annotated[str | None, Header(alias="X-Line-Signature")] = None,
) -> dict[str, str]:
    if not line_settings.channel_secret:
        # Dev mode — refuse to silently accept unsigned bodies.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "line webhook secret not configured",
        )

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"error": "out_of_range", "message": "payload too large"},
        )

    body = await request.body()
    if not verify_line_signature(body, x_line_signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid signature")

    try:
        envelope = orjson.loads(body)
    except orjson.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid json") from None

    events = envelope.get("events") or []
    if not isinstance(events, list):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "events must be a list")

    processed = 0
    skipped = 0

    for event in events:
        try:
            await _dispatch_event(conn, event)
            processed += 1
        except Exception:  # noqa: BLE001 — never let one event fail the batch
            logger.exception("line.webhook.event_failed")
            skipped += 1

    conn.commit()
    return {"status": "ok", "processed": str(processed), "skipped": str(skipped)}


# ---------------------------------------------------------------------------
# Dispatcher — called once per event in the batch.
# ---------------------------------------------------------------------------


async def _dispatch_event(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    """Process one LINE event end-to-end.

    Order of operations is deliberate:

      1. Pull `event_id` and short-circuit on duplicate (LINE retry
         after our 5xx). The UNIQUE constraint on
         line_message_log(event_id, direction) handles the dedup; we
         peek at `inbound` first so the rest of the work is skipped.
      2. Resolve / create line_users row.
      3. For non-message events (follow / unfollow / postback), apply
         the side-effect (e.g. set added_at on follow) and log; no
         user-facing reply needed beyond the welcome on follow.
      4. For message events, decrement quota, run the state machine,
         POST the reply, log the round-trip.
    """
    event_id = str(event.get("webhookEventId") or event.get("id") or "")
    if not event_id:
        # Defensive — without an id we cannot dedup. Synthesize one
        # from the timestamp + source so retries collapse to the same
        # row on a best-effort basis.
        event_id = (
            f"synth-{event.get('timestamp', 0)}-"
            f"{(event.get('source') or {}).get('userId', 'unknown')}"
        )

    event_type = str(event.get("type") or "unknown")
    source = event.get("source") or {}
    line_user_id = source.get("userId")
    received_at = datetime.now(UTC)

    # Idempotency probe: if we already have an `inbound` row for this
    # event_id, this is a retry — skip without re-billing or replying.
    dup = conn.execute(
        "SELECT 1 FROM line_message_log WHERE event_id = ? AND direction = 'inbound'",
        (event_id,),
    ).fetchone()
    if dup is not None:
        logger.info("line.webhook.duplicate_skipped event_id=%s", event_id)
        return

    # Create / fetch user row up front so non-message events still
    # populate the registry. Anonymous (no userId) events are logged
    # with NULL line_user_id and not billed.
    user_row: sqlite3.Row | None = None
    if line_user_id:
        user_row = _ensure_line_user(conn, line_user_id)

    # follow event: persist welcome state, send welcome message.
    if event_type == "follow":
        reply_token = str(event.get("replyToken") or "")
        next_state, messages = line_flow.advance(None, "")
        if user_row:
            _persist_flow_state(conn, user_row["line_user_id"], next_state)
        _log_event(
            conn,
            event_id=event_id,
            line_user_id=line_user_id,
            event_type=event_type,
            direction="inbound",
            flow_step="welcome",
            payload=event,
            billed=False,
            quota_exceeded=False,
            api_key_hash=None,
            received_at=received_at,
            processed_at=None,
        )
        if reply_token:
            await _post_line_reply(reply_token, messages)
            _log_event(
                conn,
                event_id=event_id,
                line_user_id=line_user_id,
                event_type=event_type,
                direction="outbound_reply",
                flow_step="welcome",
                payload={"messages": messages},
                billed=False,
                quota_exceeded=False,
                api_key_hash=None,
                received_at=received_at,
                processed_at=datetime.now(UTC),
            )
        return

    if event_type == "unfollow":
        if user_row:
            now = datetime.now(UTC).isoformat()
            conn.execute(
                "UPDATE line_users SET blocked_at = ?, updated_at = ? "
                "WHERE line_user_id = ?",
                (now, now, line_user_id),
            )
        _log_event(
            conn,
            event_id=event_id,
            line_user_id=line_user_id,
            event_type=event_type,
            direction="inbound",
            flow_step=None,
            payload=event,
            billed=False,
            quota_exceeded=False,
            api_key_hash=None,
            received_at=received_at,
            processed_at=None,
        )
        return

    # message event — the main billable path.
    if event_type != "message":
        # Other event types (postback, beacon, etc) — log only.
        _log_event(
            conn,
            event_id=event_id,
            line_user_id=line_user_id,
            event_type=event_type,
            direction="inbound",
            flow_step=None,
            payload=event,
            billed=False,
            quota_exceeded=False,
            api_key_hash=None,
            received_at=received_at,
            processed_at=None,
        )
        return

    msg = event.get("message") or {}
    if msg.get("type") != "text":
        # Sticker / image / file — politely re-emit the welcome text.
        reply_token = str(event.get("replyToken") or "")
        next_state, messages = line_flow.advance(None, "")
        if user_row:
            _persist_flow_state(conn, user_row["line_user_id"], next_state)
        _log_event(
            conn,
            event_id=event_id,
            line_user_id=line_user_id,
            event_type=event_type,
            direction="inbound",
            flow_step="welcome",
            payload=event,
            billed=False,
            quota_exceeded=False,
            api_key_hash=None,
            received_at=received_at,
            processed_at=None,
        )
        if reply_token:
            await _post_line_reply(reply_token, messages)
        return

    user_text = str(msg.get("text") or "")[:64]   # 64-char clamp; nobody types prefecture > 7
    reply_token = str(event.get("replyToken") or "")

    # Quota / billing decision — v1 has no parent_api_key wiring on
    # line_users (the column is reserved for migration 086 fan-out).
    has_parent_key = False
    api_key_hash: str | None = None

    if user_row is None:
        # Anonymous — log inbound, do not advance state.
        _log_event(
            conn,
            event_id=event_id,
            line_user_id=None,
            event_type=event_type,
            direction="inbound",
            flow_step=None,
            payload=event,
            billed=False,
            quota_exceeded=True,
            api_key_hash=None,
            received_at=received_at,
            processed_at=None,
        )
        return

    quota_ok = _check_and_decrement_quota(
        conn, user_row, has_parent_key=has_parent_key
    )

    # Reload the user row after the quota debit so we read the freshly-
    # written current_flow_state_json (the previous handler may not have
    # committed yet in the same connection — sqlite3 sees its own writes).
    user_row = conn.execute(
        "SELECT * FROM line_users WHERE line_user_id = ?",
        (line_user_id,),
    ).fetchone()
    raw_state = user_row["current_flow_state_json"]
    state: line_flow.FlowState | None
    try:
        state = json.loads(raw_state) if raw_state else None
    except (TypeError, json.JSONDecodeError):
        state = None

    if not quota_ok:
        messages = [
            {"type": "text", "text": line_flow.QUOTA_EXCEEDED_TEXT}
        ]
        _log_event(
            conn,
            event_id=event_id,
            line_user_id=line_user_id,
            event_type=event_type,
            direction="inbound",
            flow_step=(state or {}).get("step") if state else None,
            payload=event,
            billed=False,
            quota_exceeded=True,
            api_key_hash=None,
            received_at=received_at,
            processed_at=None,
        )
        if reply_token:
            await _post_line_reply(reply_token, messages)
            _log_event(
                conn,
                event_id=event_id,
                line_user_id=line_user_id,
                event_type=event_type,
                direction="outbound_reply",
                flow_step="quota_exceeded",
                payload={"messages": messages},
                billed=False,
                quota_exceeded=True,
                api_key_hash=None,
                received_at=received_at,
                processed_at=datetime.now(UTC),
            )
        return

    next_state, messages = line_flow.advance(state, user_text, conn=conn)
    _persist_flow_state(conn, line_user_id, next_state)

    _log_event(
        conn,
        event_id=event_id,
        line_user_id=line_user_id,
        event_type=event_type,
        direction="inbound",
        flow_step=(state or {}).get("step"),
        payload=event,
        billed=has_parent_key,
        quota_exceeded=False,
        api_key_hash=api_key_hash,
        received_at=received_at,
        processed_at=None,
    )

    if reply_token:
        await _post_line_reply(reply_token, messages)
        _log_event(
            conn,
            event_id=event_id,
            line_user_id=line_user_id,
            event_type=event_type,
            direction="outbound_reply",
            flow_step=next_state.get("step"),
            payload={"messages": messages},
            billed=has_parent_key,
            quota_exceeded=False,
            api_key_hash=api_key_hash,
            received_at=received_at,
            processed_at=datetime.now(UTC),
        )
