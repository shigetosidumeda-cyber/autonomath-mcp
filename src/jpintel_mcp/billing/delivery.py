"""Shared metered-delivery logging for cron and pre-render jobs.

Cron jobs do not have a FastAPI request scope, but their paid deliveries still
must use the same usage_events, monthly-cap, and Stripe-idempotency path as
normal API requests. This helper builds the minimal ApiContext from api_keys and
delegates to deps.log_usage() inline.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from jpintel_mcp.api.deps import ApiContext, log_usage

_log = logging.getLogger("jpintel.billing.delivery")


def _row_get(row: Any, key: str, idx: int, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        keys = row.keys()
    except AttributeError:
        try:
            return row[idx]
        except (IndexError, TypeError):
            return default
    if key in keys:
        return row[key]
    return default


def _api_context_for_key(
    conn: sqlite3.Connection, key_hash: str
) -> ApiContext | None:
    fallback_shape = False
    try:
        row = conn.execute(
            "SELECT tier, customer_id, stripe_subscription_id, id, parent_key_id "
            "FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL",
            (key_hash,),
        ).fetchone()
    except sqlite3.OperationalError:
        fallback_shape = True
        # Older local fixtures may not have customer_id / parent columns. Keep
        # single-key cap semantics rather than bypassing usage logging.
        try:
            row = conn.execute(
                "SELECT tier, stripe_subscription_id FROM api_keys "
                "WHERE key_hash = ? AND revoked_at IS NULL",
                (key_hash,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = conn.execute(
                "SELECT tier, stripe_subscription_id FROM api_keys WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
    if row is None:
        return None
    if fallback_shape:
        return ApiContext(
            key_hash=key_hash,
            tier=str(_row_get(row, "tier", 0, "free") or "free"),
            customer_id=None,
            stripe_subscription_id=_row_get(row, "stripe_subscription_id", 1),
        )
    return ApiContext(
        key_hash=key_hash,
        tier=str(_row_get(row, "tier", 0, "free") or "free"),
        customer_id=_row_get(row, "customer_id", 1),
        stripe_subscription_id=_row_get(row, "stripe_subscription_id", 2),
        key_id=_row_get(row, "id", 3),
        parent_key_id=_row_get(row, "parent_key_id", 4),
    )


def record_metered_delivery(
    conn: sqlite3.Connection,
    *,
    key_hash: str,
    endpoint: str,
    status_code: int = 200,
    quantity: int = 1,
    latency_ms: int | None = None,
    result_count: int | None = None,
    client_tag: str | None = None,
) -> bool:
    """Record one delivery through the canonical usage/cap billing path.

    Returns True when a usage row (or other inline usage-side update) was
    written. False means the key was missing or the monthly cap final guard
    blocked the billable row. Stripe reporting remains fire-and-forget inside
    deps.log_usage().
    """
    if not key_hash:
        return False
    ctx = _api_context_for_key(conn, key_hash)
    if ctx is None:
        _log.warning("metered_delivery.api_key_missing endpoint=%s", endpoint)
        return False
    before = conn.total_changes
    log_usage(
        conn,
        ctx,
        endpoint,
        status_code=status_code,
        latency_ms=latency_ms,
        result_count=result_count,
        client_tag=client_tag,
        quantity=quantity,
    )
    return conn.total_changes > before
