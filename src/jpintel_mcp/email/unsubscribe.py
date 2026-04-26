"""Master email suppression list (P2.6.4 / 特電法 §3, 2026-04-25).

This module owns the global "do-not-email" register backed by the
`email_unsubscribes` table (migration 072). Two responsibilities, one
narrow surface:

    * `is_unsubscribed(conn, email)` — single fast lookup before any
      broadcast / activation / digest send. Production callers wrap
      `_send_*` helpers in onboarding.py + scheduler.py + the digest
      cron with this guard.
    * `record_unsubscribe(conn, email, reason)` — idempotent insert
      that the self-serve `POST /v1/email/unsubscribe` endpoint and
      the Postmark bounce/spam webhook funnel into. Same shape as
      `subscribers._suppress` but writes to the master list, not a
      per-feature list.

Why a separate module
---------------------
Two existing per-list suppression flags exist:

    * `subscribers.unsubscribed_at` (newsletter — api/subscribers.py)
    * `compliance_subscribers.deleted_at` (法令改正アラート — api/compliance.py)

Both correctly suppress *their own* list, but neither acts as a global
master record. A user who unsubscribes from the newsletter today can
still legitimately receive a future onboarding D+30 NPS mail because
the onboarding sequence keys off `email_schedule` rows tied to the
api_key, not the email address. `email_unsubscribes` closes that gap.

特電法 (Act on Regulation of Transmission of Specified Electronic Mail)
exempts 取引関連メール (transactional / billing / security notices) from
the opt-out requirement under §3-2 i. We therefore deliberately do NOT
gate these on `email_unsubscribes`:

    * D+0 welcome (carries the one-time raw API key — 取引控え)
    * key_rotated security notice (security-relationship mail)
    * dunning payment-failed (billing-relationship mail)
    * receipt forwarding (請求書転送)

All other paths (D+1/3/7/14/30 onboarding, weekly digest, compliance
alerts, future broadcasts) MUST call `is_unsubscribed()` and skip the
send when it returns True.

GDPR / 個情法 / 特電法 retention
-------------------------------
The table holds only `(email, unsubscribed_at, reason)`. We never store
IP / UA / token at unsubscribe time — opting out should not itself create
a new personal-data record. Unsubscribe rows are kept indefinitely so the
operator can prove "we honoured the request" if challenged; 特電法 has no
explicit retention ceiling but the §法定保存期間 for marketing records is
10 years (景表法 §27 准用).

Solo + zero-touch
-----------------
The endpoint is fully self-serve via the HMAC token already minted by
`api/subscribers.make_unsubscribe_token` — no operator intervention,
no manual queue. Bounce/spam events route through the existing Postmark
webhook in `api/email_webhook.py` and call `record_unsubscribe()` from
there.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Final

logger = logging.getLogger("jpintel.email.unsubscribe")

# Reason values written by the various suppression sources. Kept here as a
# stable enum so the operator can SELECT reason, COUNT(*) FROM ... and
# get a triage breakdown without a CASE statement.
REASON_USER_SELF_SERVE: Final[str] = "user-self-serve"
REASON_BOUNCE: Final[str] = "bounce"
REASON_SPAM_COMPLAINT: Final[str] = "spam-complaint"
REASON_MANUAL_OPS: Final[str] = "manual-ops"

# Free-text reason cap — enforced at the API layer before we hit the DB
# so a 1MB body cannot fill the column.
REASON_MAX_LEN: Final[int] = 64


def _normalise(email: str) -> str:
    """Canonical form: stripped + lowercased.

    Email is case-insensitive in the local-part per RFC 5321 §2.4 in
    practice, and every mailbox provider that matters folds case at
    delivery. Storing the lowercase form makes the PRIMARY KEY actually
    enforce uniqueness.
    """
    return email.strip().lower()


def is_unsubscribed(conn: sqlite3.Connection, email: str) -> bool:
    """True iff `email` is on the master suppression list.

    Single indexed lookup on the PRIMARY KEY — sub-millisecond on a
    table with millions of rows. Fail-CLOSED on DB errors: when the
    lookup raises we treat the user as unsubscribed and skip the send.
    Over-suppressing is strictly safer than over-mailing under 特電法
    (one missed digest vs a 違反 fine + Postmark deliverability hit).
    """
    if not email:
        return False
    em = _normalise(email)
    try:
        row = conn.execute(
            "SELECT 1 FROM email_unsubscribes WHERE email = ? LIMIT 1",
            (em,),
        ).fetchone()
    except sqlite3.Error:
        # Fail-closed. Log + move on.
        logger.exception("email.unsubscribe.is_unsubscribed_db_error email=%s", _redact(em))
        return True
    return row is not None


def record_unsubscribe(
    conn: sqlite3.Connection,
    email: str,
    reason: str = REASON_USER_SELF_SERVE,
) -> bool:
    """Idempotent insert into the master list. Returns True iff a NEW row
    was created (False if `email` was already on the list).

    The PRIMARY KEY on `email` makes a re-unsubscribe a silent no-op via
    INSERT OR IGNORE — we deliberately do NOT update `unsubscribed_at`
    on a duplicate so the original opt-out time stays the source of truth
    for "when did they ask".

    `reason` is truncated defensively. Callers (the API layer) already
    enforce REASON_MAX_LEN, but a misbehaving direct-call from a script
    should not blow the column up.
    """
    if not email:
        return False
    em = _normalise(email)
    if reason and len(reason) > REASON_MAX_LEN:
        reason = reason[:REASON_MAX_LEN]
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO email_unsubscribes(email, reason) VALUES (?, ?)",
            (em, reason or None),
        )
    except sqlite3.Error:
        logger.exception("email.unsubscribe.record_db_error email=%s", _redact(em))
        return False
    return cur.rowcount > 0


def _redact(addr: str) -> str:
    """Match `postmark._redact_email` so unsubscribe / send logs correlate."""
    if "@" not in addr:
        return "***"
    local, _, domain = addr.partition("@")
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}***@{domain}"


__all__ = [
    "REASON_BOUNCE",
    "REASON_MANUAL_OPS",
    "REASON_MAX_LEN",
    "REASON_SPAM_COMPLAINT",
    "REASON_USER_SELF_SERVE",
    "is_unsubscribed",
    "record_unsubscribe",
]
