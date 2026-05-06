"""Security audit log helper.

不正アクセス禁止法 incident-response baseline. Backs migration
``058_audit_log.sql`` (table ``audit_log``). Every event is one row; the
key_hash columns hold sha256 hashes only — raw API keys never touch this
table.

P1 from API key rotation audit (a4298e454aab2aa43, 2026-04-25): the
rotate-key endpoint previously had no forensic trail. Event taxonomy:

- ``key_rotate``     — POST /v1/me/rotate-key. Carries both old + new hash.
- ``key_revoke``     — Stripe webhook (charge.refunded) or admin action.
- ``login``          — POST /v1/session success.
- ``login_failed``   — POST /v1/session 401 (invalid / revoked key).
- ``billing_portal`` — POST /v1/me/billing-portal Stripe session created.
- ``cap_change``     — POST /v1/me/cap monthly cap update.

Callers pass the FastAPI ``Request`` so we can capture the originating IP
and User-Agent (truncated to 500 chars to keep row size bounded). Anything
event-specific lands in ``metadata`` as JSON.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3

    from fastapi import Request


def log_event(
    db: sqlite3.Connection,
    *,
    event_type: str,
    key_hash: str | None = None,
    key_hash_new: str | None = None,
    customer_id: str | None = None,
    request: Request | None = None,
    **metadata: Any,
) -> None:
    """Append a row to ``audit_log``. Never raises on schema absence — a
    missing table during a partial migration must not break the hot path.
    """
    ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    ip: str | None = None
    ua: str | None = None
    if request is not None:
        try:
            ip = request.client.host if request.client else None
        except Exception:
            ip = None
        try:
            raw_ua = request.headers.get("user-agent", "")
            ua = raw_ua[:500] if raw_ua else None
        except Exception:
            ua = None
    md_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    try:
        db.execute(
            "INSERT INTO audit_log (ts, event_type, key_hash, key_hash_new, "
            "customer_id, ip, user_agent, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, event_type, key_hash, key_hash_new, customer_id, ip, ua, md_json),
        )
    except Exception:
        # Audit logging must never break the user request. The webhook /
        # session / rotate paths each have their own logger.exception
        # instrumentation; an audit-write failure is logged via the row
        # absence (forensics looks for missing entries) but the request
        # itself proceeds.
        pass


__all__ = ["log_event"]
