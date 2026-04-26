"""Postmark webhook receiver.

Postmark POSTs a JSON body to this endpoint for every event type we
subscribe to in the server config (Bounce / SpamComplaint / Delivery / Open
/ Click). We only *act* on the suppression-relevant events — hard bounce
and spam complaint — by adding the recipient to the `subscribers` table
with `unsubscribed_at` set, so future digest/newsletter sends skip them.

Soft bounces (transient) are logged only; Postmark's own retry queue will
eventually deliver or promote them to hard. We do not maintain parallel
retry state.

Signature verification
----------------------
Postmark signs the raw request body with the server's webhook secret and
puts the base64'd HMAC-SHA256 in `X-Postmark-Signature`. We compare
constant-time against the expected value. Any mismatch returns **401**
(never 403) so misconfigured secrets surface the same way an unauthenticated
caller would.

If `settings.postmark_webhook_secret` is empty the endpoint returns 503 —
dev mode, nothing to verify against. This is safer than silently
accepting all bodies, which would let a random attacker post synthetic
"bounce" events for real customer addresses and unsubscribe them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import sqlite3
from datetime import UTC, datetime
from typing import Annotated

import orjson
from fastapi import APIRouter, Header, HTTPException, Request, status

from jpintel_mcp.api.deps import DbDep  # noqa: TC001 (runtime for FastAPI Depends resolution)
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.email.webhook")

router = APIRouter(prefix="/v1/email", tags=["email"])

# Sentry capture is best-effort — tests / minimal CI must run without the
# SDK installed. See sibling `billing.py` for the same pattern.
try:
    import sentry_sdk as _sentry_sdk  # noqa: TC003 (runtime guard)
    _SENTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SENTRY_AVAILABLE = False


def _capture(exc: BaseException) -> None:
    """Forward an exception to Sentry iff the SDK is loaded.

    Postmark webhook silently swallowing a DB error means a hard-bounced
    address keeps receiving newsletter sends, which compounds future
    SpamComplaints — hidden cost. Capture every DB-write fault so the
    suppression pipeline failure surfaces.
    """
    if _SENTRY_AVAILABLE:
        try:
            _sentry_sdk.capture_exception(exc)
        except Exception:  # pragma: no cover
            logger.debug("sentry_capture_failed", exc_info=True)


# Postmark event types of interest. Reference:
# https://postmarkapp.com/developer/webhooks/webhooks-overview
_HARD_BOUNCE_TYPES = frozenset(
    {
        "HardBounce",
        "BadEmailAddress",
        "ManuallyDeactivated",
        "Unknown",  # unknown recipient → hard
        "SMTPApiError",
        "Blocked",
    }
)
_SOFT_BOUNCE_TYPES = frozenset(
    {
        "Transient",
        "DnsError",
        "ChallengeVerification",
        "AutoResponder",
        "ContentRelated",
        "VirusNotification",
    }
)


def _verify_signature(body: bytes, provided: str | None) -> bool:
    """Constant-time verify `X-Postmark-Signature` against the raw body."""
    if not provided or not settings.postmark_webhook_secret:
        return False
    mac = hmac.new(
        settings.postmark_webhook_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(mac).decode("ascii")
    return hmac.compare_digest(expected, provided)


def _extract_email(event: dict) -> str | None:
    """Return the normalised recipient email from a Postmark event.

    Bounce / SpamComplaint events put the recipient under `Email`; Delivery
    uses `Recipient`. We check both so the same handler works for any event
    Postmark might ever add to the suppression flow.
    """
    raw = event.get("Email") or event.get("Recipient") or event.get("MessageID")
    if not raw or "@" not in str(raw):
        return None
    return str(raw).strip().lower()


def _suppress(conn: sqlite3.Connection, email: str, reason: str) -> None:
    """Mark a recipient unsubscribed with an audit-friendly `source`.

    P2.6.4 (2026-04-25): now writes to BOTH the legacy `subscribers` table
    (per-list flag, kept for back-compat) AND the new `email_unsubscribes`
    master list (migration 072). The master list is the source of truth
    consulted by every broadcast / activation send path; the legacy table
    is only read by callers we have not yet migrated.

    `subscribers` owns the suppression concept — `unsubscribed_at` sets
    the row OFF. If the email is not in the table we still INSERT one
    so future signups are blocked (UNIQUE on email) until somebody opts in
    via the normal flow. The `source` column doubles as the reason label
    (`'bounce'`, `'spam-complaint'`).

    Non-IntegrityError failures (lock timeout under load, schema drift,
    disk full) are captured to Sentry and re-raised so FastAPI returns a
    5xx and Postmark retries the webhook. Without capture a sustained
    DB outage would silently leak hard-bounced addresses back into the
    digest list — every additional send compounds 配信停止 / spam
    complaints.
    """
    now = datetime.now(UTC).isoformat()
    try:
        conn.execute(
            "INSERT INTO subscribers(email, source, created_at, unsubscribed_at) "
            "VALUES (?, ?, ?, ?)",
            (email, f"suppress:{reason}", now, now),
        )
    except sqlite3.IntegrityError:
        # Row already exists — just flip unsubscribed_at if still NULL.
        try:
            conn.execute(
                "UPDATE subscribers SET unsubscribed_at = ? "
                "WHERE email = ? AND unsubscribed_at IS NULL",
                (now, email),
            )
        except Exception as e:
            # The follow-up UPDATE itself failed — DB lock under
            # contention is the most likely cause. P0 capture.
            _capture(e)
            logger.exception("postmark.suppress_update_failed email=%s", email)
            raise
    except Exception as e:
        # Non-Integrity DB failure on INSERT — capture before raising.
        _capture(e)
        logger.exception(
            "postmark.suppress_insert_failed email=%s reason=%s",
            email,
            reason,
        )
        raise

    # Master list (P2.6.4). Idempotent INSERT OR IGNORE — re-suppression of
    # an already-suppressed address is a no-op. We don't capture failures
    # here to Sentry because the legacy write above is already the
    # critical-path: master-list write failure on a hard bounce just means
    # the next send loop checks subscribers.unsubscribed_at instead of the
    # master list, both fire the same skip path.
    try:
        from jpintel_mcp.email.unsubscribe import record_unsubscribe

        record_unsubscribe(conn, email, reason)
    except Exception:  # pragma: no cover — defensive
        logger.debug("postmark.master_suppress_failed email=%s", email, exc_info=True)


@router.post("/webhook")
async def postmark_webhook(
    request: Request,
    conn: DbDep,
    x_postmark_signature: Annotated[str | None, Header(alias="X-Postmark-Signature")] = None,
) -> dict[str, str]:
    if not settings.postmark_webhook_secret:
        # Safer default than silent accept — see module docstring.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "postmark webhook secret not configured",
        )

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 102_400:  # 100 KB
        raise HTTPException(
            status_code=413,
            detail={"error": "out_of_range", "message": "payload too large"},
        )
    body = await request.body()
    if not _verify_signature(body, x_postmark_signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid signature")

    try:
        event = orjson.loads(body)
    except orjson.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid json") from None

    # Postmark sends object-per-event; `RecordType` distinguishes
    # Bounce / SpamComplaint / Delivery / Open / Click / SubscriptionChange.
    record_type = event.get("RecordType", "")
    email = _extract_email(event)

    # Event-level dedup keyed on Postmark's `MessageID` (audit
    # a9fd80e134b538a32, migration 059). Postmark retries on any non-2xx and
    # may even re-deliver after a 200 if its own ack pipeline burped — both
    # paths previously fired `_suppress` twice, which racewise can flip
    # `unsubscribed_at` on a row that was meanwhile re-subscribed via the
    # normal flow. INSERT-or-IntegrityError gives us atomic single-shot
    # processing without an extra SELECT round-trip.
    #
    # If `MessageID` is absent (older event types Postmark documents as
    # optional, or hand-crafted test payloads) we skip the dedup and fall
    # through to the legacy idempotent path — `subscribers` UNIQUE(email)
    # already protects against duplicate suppression rows for the bounce /
    # complaint case, so no regression vs pre-059 behaviour.
    message_id = event.get("MessageID")
    now_iso = datetime.now(UTC).isoformat()
    if message_id:
        try:
            conn.execute(
                "INSERT INTO postmark_webhook_events"
                " (message_id, event_type, received_at)"
                " VALUES (?, ?, ?)",
                (str(message_id), record_type or "unknown", now_iso),
            )
        except sqlite3.IntegrityError:
            logger.info(
                "postmark.duplicate_ignored message_id=%s record_type=%s",
                message_id,
                record_type or "unknown",
            )
            return {"status": "duplicate_ignored"}
        except Exception as e:
            # Non-Integrity DB failure — capture and let FastAPI 5xx so
            # Postmark retries. Better to retry into a duplicate than to
            # silently drop a hard-bounce.
            _capture(e)
            logger.exception(
                "postmark.dedup_insert_failed message_id=%s", message_id
            )
            raise

    response: dict[str, str]
    if record_type == "Bounce":
        bounce_type = event.get("Type", "")
        if bounce_type in _HARD_BOUNCE_TYPES and email:
            _suppress(conn, email, "bounce")
            logger.info("postmark.hard_bounce email=%s bounce_type=%s", email, bounce_type)
            response = {"status": "suppressed", "reason": "bounce"}
        elif bounce_type in _SOFT_BOUNCE_TYPES:
            logger.info(
                "postmark.soft_bounce email=%s bounce_type=%s",
                email or "?",
                bounce_type,
            )
            response = {"status": "logged", "reason": "soft-bounce"}
        else:
            # Unknown bounce type — log so we can classify later.
            logger.warning(
                "postmark.unknown_bounce email=%s bounce_type=%s",
                email or "?",
                bounce_type,
            )
            response = {"status": "logged", "reason": "unknown-bounce"}
    elif record_type == "SpamComplaint" and email:
        _suppress(conn, email, "spam-complaint")
        logger.info("postmark.spam_complaint email=%s", email)
        response = {"status": "suppressed", "reason": "spam-complaint"}
    elif record_type == "SubscriptionChange" and bool(event.get("SuppressSending")) and email:
        # Recipient used Postmark's built-in list-unsubscribe. Suppress so
        # our own digest cron respects that choice.
        _suppress(conn, email, "list-unsubscribe")
        logger.info("postmark.list_unsubscribe email=%s", email)
        response = {"status": "suppressed", "reason": "list-unsubscribe"}
    else:
        # Delivery / Open / Click / anything else we do not suppress on.
        # Still 200 so Postmark does not retry — we have received + ack'd it.
        logger.debug(
            "postmark.event record_type=%s email=%s",
            record_type or "unknown",
            email or "?",
        )
        response = {"status": "received"}

    # Mark dedup row processed (best-effort — failure here just leaves
    # processed_at NULL, which is harmless and lets ops audits surface the
    # gap. The next duplicate of the same MessageID will still be ignored
    # because the PRIMARY KEY row exists).
    if message_id:
        try:
            conn.execute(
                "UPDATE postmark_webhook_events SET processed_at = ?"
                " WHERE message_id = ?",
                (datetime.now(UTC).isoformat(), str(message_id)),
            )
        except Exception:  # pragma: no cover
            logger.debug("postmark.processed_at_update_failed", exc_info=True)

    return response


__all__ = ["router"]
