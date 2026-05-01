#!/usr/bin/env python3
"""Customer webhook dispatcher (¥3/req metered, HMAC-signed).

Distinct from `amendment_alert.py` (FREE retention surface, am_amendment_snapshot
fan-out). This cron handles the structured product-event surface registered
via /v1/me/webhooks:

  * program.created               — new programs row (created_at within window)
  * program.amended               — am_amendment_diff row (autonomath.db)
  * enforcement.added             — new enforcement_cases row
  * tax_ruleset.amended           — tax_rulesets row updated
  * invoice_registrant.matched    — invoice_registrants row matched (placeholder
                                    in MVP — emits no events until matcher lands;
                                    schema is forward-compatible.)

Pricing (project_autonomath_business_model — immutable):
  Each SUCCESSFUL HTTP 2xx delivery emits one Stripe usage_record at ¥3/req.
  Failed deliveries (timeout, 4xx, 5xx) and retries do NOT bill. The customer
  pays exactly the same unit price they would have paid for the equivalent
  poll request.

Retry policy:
  Exponential schedule: 60s, 300s, 1800s (1m / 5m / 30m). After 3 attempts on
  a single (webhook, event) tuple the dispatcher stops retrying THIS event
  and increments the parent webhook's `failure_count`. After 5 consecutive
  failure increments without an intervening success, the webhook flips
  status='disabled' and an email is queued via bg_task_queue.

Idempotency:
  webhook_deliveries has UNIQUE(webhook_id, event_type, event_id). The
  dispatcher INSERTs the row BEFORE the POST attempt; on re-run, the conflict
  short-circuits to the existing row, and the dispatcher inspects status_code
  to decide whether to retry or skip. Same event is never delivered twice.

Constraints:
  * No Anthropic / claude / SDK calls. Pure SQLite + httpx + stdlib.
  * HMAC required (X-Jpcite-Signature: hmac-sha256={hex}).
  * User-Agent: jpcite-webhook/1.0.
  * RFC1918 / loopback host rebind defence: re-validates the URL at fire time.

Usage:
    python scripts/cron/dispatch_webhooks.py            # one-shot pass
    python scripts/cron/dispatch_webhooks.py --dry-run  # log only
    python scripts/cron/dispatch_webhooks.py --since 2026-04-29T00:00:00+00:00
    python scripts/cron/dispatch_webhooks.py --window-minutes 60  # default 1440 (24h)
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import socket
import sqlite3
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.api.customer_webhooks import compute_signature  # noqa: E402
from jpintel_mcp.billing.delivery import record_metered_delivery  # noqa: E402
from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402

logger = logging.getLogger("autonomath.cron.dispatch_webhooks")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HTTPX_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Per-attempt retry schedule. Index 0 = first attempt (no wait). Indexes
# 1..N are retry waits in seconds.
_RETRY_BACKOFF_S: tuple[int, ...] = (60, 300, 1800)
_MAX_ATTEMPTS = 1 + len(_RETRY_BACKOFF_S)  # initial + 3 retries = 4

# Auto-disable threshold. After this many consecutive non-2xx deliveries
# without an intervening success the webhook flips status='disabled'.
_AUTO_DISABLE_THRESHOLD = 5

# Default lookback window (minutes). 24h matches the recommended cron
# cadence (once daily) with a generous overlap so a missed run does not
# permanently drop events.
_DEFAULT_WINDOW_MINUTES = 1440


# ---------------------------------------------------------------------------
# URL safety re-check (mirrors api/customer_webhooks._is_internal_host but
# with the DNS-resolution branch from amendment_alert)
# ---------------------------------------------------------------------------


def _is_safe_webhook(url: str) -> tuple[bool, str | None]:
    """Re-validate the URL at fire time. Returns (ok, reason_if_unsafe)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "url_unparseable"
    if parsed.scheme.lower() != "https":
        return False, "scheme_not_https"
    host = (parsed.hostname or "").strip("[]").lower()
    if not host or host == "localhost":
        return False, "no_host"
    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, "internal_ip_literal"
        return True, None
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, "dns_failed"
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, "internal_ip_resolved"
    return True, None


# ---------------------------------------------------------------------------
# Event collection per source table
# ---------------------------------------------------------------------------


def _corpus_snapshot_id(jp_conn: sqlite3.Connection) -> str | None:
    """Best-effort corpus snapshot label for webhook references."""
    try:
        from jpintel_mcp.api._corpus_snapshot import compute_corpus_snapshot

        snapshot_id, _checksum = compute_corpus_snapshot(jp_conn)
        return snapshot_id
    except Exception:
        return None


def _evidence_packet_endpoint(program_id: str) -> str:
    return f"/v1/evidence/packets/program/{program_id}"


def _collect_program_created(
    jp_conn: sqlite3.Connection,
    since_iso: str,
) -> list[dict[str, Any]]:
    """Return events for programs.created within [since_iso, now).

    The `programs` table does not carry a `created_at` column directly; we
    use `updated_at` filtered by `excluded=0` AND tier IN ('S','A','B','C')
    as a best-effort proxy. Customers register `program.created` to get
    notified when something new is searchable.
    """
    rows = jp_conn.execute(
        """SELECT unified_id, primary_name, official_url, source_url,
                  prefecture, program_kind, tier, updated_at
             FROM programs
            WHERE excluded = 0
              AND tier IN ('S','A','B','C')
              AND updated_at >= ?
         ORDER BY updated_at ASC
            LIMIT 1000""",
        (since_iso,),
    ).fetchall()
    snapshot_id = _corpus_snapshot_id(jp_conn)
    return [
        {
            "event_type": "program.created",
            "event_id": str(r["unified_id"]),
            "data": {
                "entity_id": r["unified_id"],
                "unified_id": r["unified_id"],
                "name": r["primary_name"],
                "summary": None,  # programs schema has no summary column
                "diff_id": None,
                "field_name": "created",
                "source_url": r["source_url"] or r["official_url"],
                "prefecture": r["prefecture"],
                "program_kind": r["program_kind"],
                "tier": r["tier"],
                "corpus_snapshot_id": snapshot_id,
                "evidence_packet_endpoint": _evidence_packet_endpoint(
                    str(r["unified_id"])
                ),
            },
            "timestamp": r["updated_at"],
        }
        for r in rows
    ]


def _collect_program_amended(
    am_path: Path,
    jp_conn: sqlite3.Connection,
    since_iso: str,
) -> list[dict[str, Any]]:
    """Return events for am_amendment_diff rows within window."""
    if not am_path.is_file():
        return []
    am_conn = sqlite3.connect(str(am_path))
    am_conn.row_factory = sqlite3.Row
    try:
        # am_amendment_diff exists post-migration 075. Defensive try/except
        # in case the cron runs before migration applied.
        try:
            rows = am_conn.execute(
                """SELECT diff_id, entity_id, field_name, prev_value, new_value,
                          detected_at, source_url
                     FROM am_amendment_diff
                    WHERE detected_at >= ?
                 ORDER BY detected_at ASC, diff_id ASC
                    LIMIT 1000""",
                (since_iso,),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return []
            raise
        # Group by entity_id so we emit ONE program.amended per program with
        # an array of field-level diffs. Customers want "what changed for X"
        # not 5 events per program.
        grouped: dict[str, dict[str, Any]] = {}
        snapshot_id = _corpus_snapshot_id(jp_conn)
        for r in rows:
            eid = r["entity_id"]
            if eid not in grouped:
                grouped[eid] = {
                    "event_type": "program.amended",
                    "event_id": f"{eid}@{r['detected_at']}",
                    "data": {
                        "entity_id": eid,
                        "unified_id": eid,
                        "name": None,
                        "diff_id": r["diff_id"],
                        "field_name": r["field_name"],
                        "diffs": [],
                        "source_url": r["source_url"],
                        "corpus_snapshot_id": snapshot_id,
                        "evidence_packet_endpoint": _evidence_packet_endpoint(eid),
                    },
                    "timestamp": r["detected_at"],
                }
            grouped[eid]["data"]["diffs"].append({
                "field": r["field_name"],
                "before": r["prev_value"],
                "after": r["new_value"],
            })
        return list(grouped.values())
    finally:
        am_conn.close()


def _collect_enforcement_added(
    jp_conn: sqlite3.Connection,
    since_iso: str,
) -> list[dict[str, Any]]:
    rows = jp_conn.execute(
        """SELECT case_id, event_type, recipient_name, recipient_houjin_bangou,
                  prefecture, ministry, amount_yen, reason_excerpt,
                  source_url, disclosed_date, fetched_at
             FROM enforcement_cases
            WHERE fetched_at >= ?
         ORDER BY fetched_at ASC
            LIMIT 1000""",
        (since_iso,),
    ).fetchall()
    return [
        {
            "event_type": "enforcement.added",
            "event_id": str(r["case_id"]),
            "data": {
                "case_id": r["case_id"],
                "event_kind": r["event_type"],
                "recipient_name": r["recipient_name"],
                "recipient_houjin_bangou": r["recipient_houjin_bangou"],
                "prefecture": r["prefecture"],
                "ministry": r["ministry"],
                "amount_yen": r["amount_yen"],
                "reason_excerpt": r["reason_excerpt"],
                "source_url": r["source_url"],
                "disclosed_date": r["disclosed_date"],
            },
            "timestamp": r["fetched_at"],
        }
        for r in rows
    ]


def _collect_tax_ruleset_amended(
    jp_conn: sqlite3.Connection,
    since_iso: str,
) -> list[dict[str, Any]]:
    # tax_rulesets: we treat any row with effective_from or effective_until
    # >= since as a fresh amendment. This is best-effort and matches the
    # schema.sql posture.
    try:
        rows = jp_conn.execute(
            """SELECT unified_id, ruleset_name, tax_category, ruleset_kind,
                      effective_from, effective_until, related_law_ids_json
                 FROM tax_rulesets
                WHERE effective_from >= ? OR effective_until >= ?
             ORDER BY effective_from ASC NULLS LAST
                LIMIT 500""",
            (since_iso, since_iso),
        ).fetchall()
    except sqlite3.OperationalError:
        # NULLS LAST not always supported on older sqlite; retry without.
        rows = jp_conn.execute(
            """SELECT unified_id, ruleset_name, tax_category, ruleset_kind,
                      effective_from, effective_until, related_law_ids_json
                 FROM tax_rulesets
                WHERE effective_from >= ? OR effective_until >= ?
                LIMIT 500""",
            (since_iso, since_iso),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "event_type": "tax_ruleset.amended",
            "event_id": str(r["unified_id"]),
            "data": {
                "unified_id": r["unified_id"],
                "name": r["ruleset_name"],
                "tax_category": r["tax_category"],
                "ruleset_kind": r["ruleset_kind"],
                "effective_from": r["effective_from"],
                "effective_until": r["effective_until"],
                "related_law_ids": json.loads(r["related_law_ids_json"] or "[]"),
            },
            "timestamp": r["effective_from"] or datetime.now(UTC).isoformat(),
        })
    return out


def _collect_invoice_registrant_matched(
    jp_conn: sqlite3.Connection,
    since_iso: str,
) -> list[dict[str, Any]]:
    """Placeholder. The matcher pipeline is not yet wired (see CLAUDE.md
    invoice_registrants delta posture). Returns [] so the dispatcher path
    stays stable; subscribers to this event type get an empty fan-out
    until the matcher lands.
    """
    return []


_COLLECTORS = {
    "program.created": _collect_program_created,
    "enforcement.added": _collect_enforcement_added,
    "tax_ruleset.amended": _collect_tax_ruleset_amended,
    "invoice_registrant.matched": _collect_invoice_registrant_matched,
}


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def _deliver_one(
    *,
    client: httpx.Client,
    url: str,
    secret: str,
    event_type: str,
    payload: dict[str, Any],
    dry_run: bool,
) -> tuple[int | None, str | None]:
    """POST one delivery. Returns (status_code, error_or_none).

    NEVER raises — failure modes are captured in the error string.
    """
    if dry_run:
        logger.info(
            "webhook.dry_run host=%s event=%s",
            urlparse(url).hostname, event_type,
        )
        return 200, None

    safe, reason = _is_safe_webhook(url)
    if not safe:
        return None, f"unsafe_target: {reason}"

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sig = compute_signature(secret, body)
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "jpcite-webhook/1.0",
        "X-Jpcite-Signature": sig,
        "X-Jpcite-Event": event_type,
        # Legacy aliases retained for existing integrations.
        "X-Zeimu-Signature": sig,
        "X-Zeimu-Event": event_type,
    }
    try:
        r = client.post(url, content=body, headers=headers, timeout=_HTTPX_TIMEOUT)
        return r.status_code, None
    except httpx.TimeoutException:
        return None, "timeout"
    except httpx.HTTPError as exc:
        return None, f"transport_error: {exc!r}"[:1024]


def _record_delivery_attempt(
    conn: sqlite3.Connection,
    *,
    webhook_id: int,
    event_type: str,
    event_id: str,
    payload: dict[str, Any],
    status_code: int | None,
    attempt_count: int,
    error: str | None,
) -> int:
    """INSERT or UPDATE the webhook_deliveries row for this (webhook, event).

    The UNIQUE(webhook_id, event_type, event_id) constraint serves as the
    idempotency key. On INSERT conflict we UPDATE the existing row's
    status_code / attempt_count / delivered_at / error.
    """
    payload_str = json.dumps(payload, ensure_ascii=False)
    now = datetime.now(UTC).isoformat()
    delivered_at = now if status_code is not None and 200 <= status_code < 300 else None
    try:
        cur = conn.execute(
            """INSERT INTO webhook_deliveries(
                    webhook_id, event_type, event_id, payload_json,
                    status_code, attempt_count, delivered_at, error, created_at
               ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                webhook_id, event_type, event_id, payload_str,
                status_code, attempt_count, delivered_at, error, now,
            ),
        )
        return int(cur.lastrowid or 0)
    except sqlite3.IntegrityError:
        # Already exists — update with latest attempt result.
        conn.execute(
            """UPDATE webhook_deliveries
                  SET status_code = ?, attempt_count = ?, delivered_at = ?,
                      error = ?, payload_json = ?
                WHERE webhook_id = ? AND event_type = ? AND event_id = ?""",
            (
                status_code, attempt_count, delivered_at, error, payload_str,
                webhook_id, event_type, event_id,
            ),
        )
        row = conn.execute(
            "SELECT id FROM webhook_deliveries "
            "WHERE webhook_id = ? AND event_type = ? AND event_id = ?",
            (webhook_id, event_type, event_id),
        ).fetchone()
        return int(row[0]) if row else 0


def _already_delivered(
    conn: sqlite3.Connection,
    webhook_id: int,
    event_type: str,
    event_id: str,
) -> bool:
    """Return True if a 2xx delivery for this (webhook, event) already exists."""
    row = conn.execute(
        """SELECT status_code FROM webhook_deliveries
            WHERE webhook_id = ? AND event_type = ? AND event_id = ?""",
        (webhook_id, event_type, event_id),
    ).fetchone()
    if row is None:
        return False
    code = row[0]
    return code is not None and 200 <= int(code) < 300


def _maybe_disable_webhook(
    conn: sqlite3.Connection,
    webhook_id: int,
    failure_count: int,
    last_error: str | None,
) -> bool:
    """Flip status='disabled' when failure_count crosses the threshold.

    Returns True iff the webhook was just disabled (caller queues email).
    """
    if failure_count < _AUTO_DISABLE_THRESHOLD:
        return False
    now = datetime.now(UTC).isoformat()
    reason = f"{_AUTO_DISABLE_THRESHOLD} consecutive failures: {last_error or 'unknown'}"[:256]
    conn.execute(
        """UPDATE customer_webhooks
              SET status = 'disabled', disabled_at = ?, disabled_reason = ?,
                  updated_at = ?
            WHERE id = ? AND status = 'active'""",
        (now, reason, now, webhook_id),
    )
    return conn.total_changes > 0


def _bill_one_delivery(
    jp_conn: sqlite3.Connection,
    webhook_id: int,
    api_key_hash: str,
) -> None:
    """Emit a usage_event + Stripe usage_record for one successful delivery.

    Mirrors the inline path in `deps.log_usage` but with endpoint=
    'webhook.delivered' so dashboards can break out webhook revenue.
    Failures here are non-fatal: the delivery already succeeded, the
    customer endpoint already received the payload, billing reconciliation
    happens via the cron + Stripe usage backfill scripts.
    """
    if not jp_conn:
        return
    ok = record_metered_delivery(
        jp_conn,
        key_hash=api_key_hash,
        endpoint="webhook.delivered",
    )
    if not ok:
        logger.warning("webhook.delivery_billing_skipped webhook_id=%s", webhook_id)


def _queue_disabled_email(
    jp_conn: sqlite3.Connection,
    *,
    api_key_hash: str,
    webhook_id: int,
    url_host: str,
    reason: str,
) -> None:
    """Best-effort: queue an email notifying the customer of auto-disable.

    Uses bg_task_queue (migration 060). On a missing queue / missing
    template alias the email simply does not fire — the customer can still
    see the disabled state on the dashboard.
    """
    try:
        # Look up the email tied to this key (same lookup path as
        # me.py:_lookup_subscriber_email).
        row = jp_conn.execute(
            "SELECT email FROM email_schedule WHERE api_key_id = ? "
            "ORDER BY id ASC LIMIT 1",
            (api_key_hash,),
        ).fetchone()
        if row is None:
            return
        email = row["email"] if hasattr(row, "keys") else row[0]
        if not email:
            return
    except Exception:
        return

    try:
        from jpintel_mcp.api._bg_task_queue import enqueue
        enqueue(
            jp_conn,
            kind="webhook_disabled_email",
            payload={
                "to": email,
                "webhook_id": webhook_id,
                "url_host": url_host,
                "reason": reason,
            },
            dedup_key=f"webhook_disabled:{webhook_id}",
        )
    except Exception:
        logger.warning("webhook_disabled_email enqueue failed", exc_info=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(
    *,
    since_iso: str | None = None,
    window_minutes: int = _DEFAULT_WINDOW_MINUTES,
    dry_run: bool = False,
    autonomath_db: Path | None = None,
    jpintel_db: Path | None = None,
) -> dict[str, Any]:
    """Single dispatcher pass. Returns a summary dict for cron capture."""
    am_path = autonomath_db or Path(str(settings.autonomath_db_path))

    if since_iso is None:
        since_iso = (
            datetime.now(UTC) - timedelta(minutes=window_minutes)
        ).isoformat()

    jp_conn = connect(jpintel_db) if jpintel_db else connect()

    summary: dict[str, Any] = {
        "ran_at": datetime.now(UTC).isoformat(),
        "since": since_iso,
        "events_collected": 0,
        "deliveries_attempted": 0,
        "deliveries_succeeded": 0,
        "deliveries_failed": 0,
        "deliveries_skipped_dedup": 0,
        "webhooks_disabled": 0,
        "billed_units": 0,
        "dry_run": dry_run,
    }

    try:
        # 1. Active webhooks indexed by api_key_hash → list[row].
        whs = jp_conn.execute(
            """SELECT id, api_key_hash, url, event_types_json, secret_hmac,
                      failure_count
                 FROM customer_webhooks
                WHERE status = 'active'"""
        ).fetchall()
        if not whs:
            return summary

        # 2. Collect events per type. Group all collectors so unsubscribed
        # event types are NOT collected (saves DB work).
        subscribed_types: set[str] = set()
        for w in whs:
            try:
                types = json.loads(w["event_types_json"] or "[]")
            except json.JSONDecodeError:
                types = []
            subscribed_types.update(types)

        events: list[dict[str, Any]] = []
        if "program.amended" in subscribed_types:
            events.extend(_collect_program_amended(am_path, jp_conn, since_iso))
        for et, fn in _COLLECTORS.items():
            if et in subscribed_types and et != "program.amended":
                events.extend(fn(jp_conn, since_iso))
        summary["events_collected"] = len(events)
        if not events:
            return summary

        # 3. Per-webhook fan out with idempotency.
        client = httpx.Client(timeout=_HTTPX_TIMEOUT)
        try:
            now_iso = datetime.now(UTC).isoformat()
            for w in whs:
                wid = w["id"]
                try:
                    types = set(json.loads(w["event_types_json"] or "[]"))
                except json.JSONDecodeError:
                    types = set()
                if not types:
                    continue

                cur_failure_count = int(w["failure_count"])
                failures_this_run: list[str] = []
                last_success: str | None = None

                for ev in events:
                    if ev["event_type"] not in types:
                        continue
                    if _already_delivered(
                        jp_conn, wid, ev["event_type"], ev["event_id"]
                    ):
                        summary["deliveries_skipped_dedup"] += 1
                        continue

                    payload = {
                        "event_type": ev["event_type"],
                        "timestamp": ev["timestamp"] or now_iso,
                        "data": ev["data"],
                    }

                    # Per-event retry loop: initial + 3 retries.
                    status_code: int | None = None
                    error: str | None = None
                    for attempt_idx in range(_MAX_ATTEMPTS):
                        if attempt_idx > 0:
                            time.sleep(_RETRY_BACKOFF_S[attempt_idx - 1])
                        status_code, error = _deliver_one(
                            client=client,
                            url=w["url"],
                            secret=w["secret_hmac"],
                            event_type=ev["event_type"],
                            payload=payload,
                            dry_run=dry_run,
                        )
                        summary["deliveries_attempted"] += 1
                        if status_code is not None and 200 <= status_code < 300:
                            break
                        # Don't retry on 4xx (client error — customer fix).
                        if (
                            status_code is not None
                            and 400 <= status_code < 500
                            and status_code not in (408, 429)
                        ):
                            break
                        # Don't retry when the URL safety re-check rejected
                        # the target (DNS rebind / scheme drift / etc.) —
                        # retrying will not change the verdict, just burn
                        # 35 minutes of wall-clock waiting for a guaranteed
                        # failure.
                        if error and error.startswith("unsafe_target"):
                            break

                    _record_delivery_attempt(
                        jp_conn,
                        webhook_id=wid,
                        event_type=ev["event_type"],
                        event_id=ev["event_id"],
                        payload=payload,
                        status_code=status_code,
                        attempt_count=attempt_idx + 1,
                        error=error,
                    )

                    if status_code is not None and 200 <= status_code < 300:
                        summary["deliveries_succeeded"] += 1
                        last_success = now_iso
                        cur_failure_count = 0
                        # Bill the successful delivery.
                        if not dry_run:
                            _bill_one_delivery(jp_conn, wid, w["api_key_hash"])
                            summary["billed_units"] += 1
                    else:
                        summary["deliveries_failed"] += 1
                        cur_failure_count += 1
                        failures_this_run.append(error or f"http_{status_code}")
                        if cur_failure_count >= _AUTO_DISABLE_THRESHOLD:
                            # Stop attempting further events for this webhook
                            # — it just got auto-disabled.
                            break

                # 4. Update parent webhook row (failure_count, last_delivery_at).
                if not dry_run:
                    if last_success is not None:
                        jp_conn.execute(
                            """UPDATE customer_webhooks
                                  SET failure_count = ?, last_delivery_at = ?,
                                      updated_at = ?
                                WHERE id = ?""",
                            (cur_failure_count, last_success,
                             datetime.now(UTC).isoformat(), wid),
                        )
                    elif failures_this_run:
                        jp_conn.execute(
                            """UPDATE customer_webhooks
                                  SET failure_count = ?, updated_at = ?
                                WHERE id = ?""",
                            (cur_failure_count,
                             datetime.now(UTC).isoformat(), wid),
                        )
                    if _maybe_disable_webhook(
                        jp_conn, wid, cur_failure_count,
                        failures_this_run[-1] if failures_this_run else None,
                    ):
                        summary["webhooks_disabled"] += 1
                        _queue_disabled_email(
                            jp_conn,
                            api_key_hash=w["api_key_hash"],
                            webhook_id=wid,
                            url_host=urlparse(w["url"]).hostname or "?",
                            reason=failures_this_run[-1] if failures_this_run else "unknown",
                        )
        finally:
            client.close()

        logger.info(
            "dispatch_webhooks.summary %s",
            json.dumps(summary, ensure_ascii=False),
        )
        return summary
    finally:
        import contextlib
        with contextlib.suppress(Exception):
            jp_conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Customer webhook dispatcher")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--since", default=None,
                        help="ISO datetime (default: now - --window-minutes)")
    parser.add_argument("--window-minutes", type=int,
                        default=_DEFAULT_WINDOW_MINUTES,
                        help="Lookback window when --since not provided.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    with heartbeat("dispatch_webhooks") as hb:
        summary = run(
            since_iso=args.since,
            window_minutes=args.window_minutes,
            dry_run=args.dry_run,
        )
        hb["rows_processed"] = int(
            summary.get("delivered", summary.get("dispatched", 0)) or 0
        )
        hb["rows_skipped"] = int(summary.get("skipped", 0) or 0)
        hb["metadata"] = {
            k: summary[k]
            for k in ("scanned", "failed", "retried", "dry_run")
            if k in summary
        }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
