#!/usr/bin/env python3
"""Predictive billing alert (Tier 1 envelope CS Feature D, P3-M++).

Runs once per day. For every active api_key:

  1. Compute this month's usage_count (UTC month boundary; matches
     stripe_usage cycle).
  2. Compute the rolling-3-month-average usage_count.
  3. If current >= avg * 3.0 AND current >= 100, emit an alert.
  4. Send email via Postmark template 'billing-alert' if available;
     otherwise log structured JSON line and continue.

Idempotency
-----------
A simple per-key + per-month lock-table-free guard: the script writes a
single line to logger; production runs add a dedupe row to a future
`billing_alerts_log` table when one exists. For MVP, we skip the dedupe
and rely on cron-level locking (one daily run).

Usage
-----
    python scripts/cron/predictive_billing_alert.py            # real run
    python scripts/cron/predictive_billing_alert.py --dry-run  # no email
    python scripts/cron/predictive_billing_alert.py --threshold=2.5

No API key usage. No Anthropic / OpenAI / SDK calls. Pure SQL +
deterministic compute.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.mcp.autonomath_tools.cs_features import (  # noqa: E402
    compute_billing_alert,
)
from jpintel_mcp.observability import heartbeat  # noqa: E402

logger = logging.getLogger("autonomath.cron.billing_alert")


# ---------------------------------------------------------------------------
# SQL — count usage_events per api_key for "this month" + previous 3.
# ---------------------------------------------------------------------------


def _month_boundaries_iso(now: datetime) -> tuple[str, str, str]:
    """Return (current_month_start_iso, three_months_ago_iso, prev_month_end_iso).

    Boundaries are UTC; matches Stripe metered billing cycle.
    """
    cur_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Step back ~93 days to safely cover 3 prior calendar months even
    # across 31-day-month edge cases. We take the calendar floor
    # afterwards.
    rough_3mo_back = cur_start - timedelta(days=92)
    three_mo_start = rough_3mo_back.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    )
    return cur_start.isoformat(), three_mo_start.isoformat(), cur_start.isoformat()


def _count_usage(
    conn: sqlite3.Connection,
    *,
    key_hash: str,
    since_iso: str,
    until_iso: str | None = None,
) -> int:
    if until_iso is None:
        sql = (
            "SELECT COUNT(*) FROM usage_events "
            "WHERE key_hash=? AND ts >= ?"
        )
        cur = conn.execute(sql, (key_hash, since_iso))
    else:
        sql = (
            "SELECT COUNT(*) FROM usage_events "
            "WHERE key_hash=? AND ts >= ? AND ts < ?"
        )
        cur = conn.execute(sql, (key_hash, since_iso, until_iso))
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _recent_email_for(conn: sqlite3.Connection, key_hash: str) -> str | None:
    """Look up a last-known email for this key from email_schedule.

    `email_schedule.api_key_id` is the same key_hash used elsewhere; we
    take the most recent row's email column. Returns None when the key
    has no email history (anonymous-tier keys, very old pre-onboarding
    keys, etc.).
    """
    cur = conn.execute(
        "SELECT email FROM email_schedule "
        "WHERE api_key_id=? AND email IS NOT NULL AND email != '' "
        "ORDER BY id DESC LIMIT 1",
        (key_hash,),
    )
    row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Email send (best-effort — log if postmark template not configured).
# ---------------------------------------------------------------------------


def _send_alert_email(
    *,
    to: str,
    template_model: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        logger.info(
            "billing_alert.dry_run to=%s payload=%s",
            to, json.dumps(template_model, ensure_ascii=False),
        )
        return {"skipped": True, "reason": "dry_run"}
    try:
        from jpintel_mcp.email import get_client  # local import
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("billing_alert.email_unavailable err=%s", exc)
        return {"skipped": True, "reason": "email_module_unavailable"}
    try:
        client = get_client()
        # Postmark allows template-not-found errors to surface; if the
        # 'billing-alert' template alias isn't created in the Postmark UI
        # yet, the send returns an error string we just log.
        return client._send(  # type: ignore[attr-defined]
            to=to,
            template_alias="billing-alert",
            template_model=template_model,
            tag="billing-alert",
        )
    except Exception as exc:
        logger.warning("billing_alert.send_failed to=%s err=%s", to, exc)
        return {"skipped": True, "reason": "send_failed", "error": str(exc)}


# ---------------------------------------------------------------------------
# Main loop.
# ---------------------------------------------------------------------------


def run(
    *,
    threshold_multiplier: float = 3.0,
    min_floor: int = 100,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Scan every active api_key, emit alerts where warranted.

    Returns a summary dict suitable for cron output / Sentry breadcrumb.
    """
    now = datetime.now(UTC)
    cur_start_iso, three_mo_start_iso, prev_month_end_iso = _month_boundaries_iso(now)

    conn = connect()
    cur = conn.execute(
        "SELECT key_hash, customer_id, tier, created_at FROM api_keys "
        "WHERE revoked_at IS NULL"
    )
    keys = cur.fetchall()

    alerts_emitted = 0
    keys_scanned = 0
    keys_with_alert: list[dict[str, Any]] = []

    for row in keys:
        key_hash, customer_id, tier, created_at = row
        keys_scanned += 1

        current = _count_usage(conn, key_hash=key_hash, since_iso=cur_start_iso)
        prior = _count_usage(
            conn,
            key_hash=key_hash,
            since_iso=three_mo_start_iso,
            until_iso=prev_month_end_iso,
        )
        # Average over up-to-three prior months.
        rolling_avg = prior / 3.0 if prior > 0 else 0.0

        alert = compute_billing_alert(
            current_month_count=current,
            rolling_avg_count=rolling_avg,
            threshold_multiplier=threshold_multiplier,
            min_floor=min_floor,
        )
        if alert is None:
            continue

        alert.update({
            "key_hash_prefix": key_hash[:8],
            "customer_id": customer_id,
            "tier": tier,
            "key_created_at": created_at,
            "month_start": cur_start_iso,
        })
        keys_with_alert.append(alert)

        email = _recent_email_for(conn, key_hash)
        if email:
            _send_alert_email(
                to=email,
                template_model=alert,
                dry_run=dry_run,
            )
            alerts_emitted += 1
        else:
            # No email -> log only.
            logger.info(
                "billing_alert.no_email key_prefix=%s payload=%s",
                key_hash[:8],
                json.dumps(alert, ensure_ascii=False),
            )

    summary = {
        "ran_at": now.isoformat(),
        "keys_scanned": keys_scanned,
        "alerts_total": len(keys_with_alert),
        "alerts_emailed": alerts_emitted,
        "dry_run": dry_run,
        "threshold_multiplier": threshold_multiplier,
    }
    logger.info("billing_alert.summary %s", json.dumps(summary, ensure_ascii=False))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Daily predictive billing alert cron",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--threshold", type=float, default=3.0)
    parser.add_argument("--min-floor", type=int, default=100)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    with heartbeat("predictive_billing_alert") as hb:
        summary = run(
            threshold_multiplier=args.threshold,
            min_floor=args.min_floor,
            dry_run=args.dry_run,
        )
        hb["rows_processed"] = int(summary.get("alerts_emailed", 0) or 0)
        hb["metadata"] = {
            "keys_scanned": summary.get("keys_scanned"),
            "alerts_total": summary.get("alerts_total"),
            "threshold_multiplier": summary.get("threshold_multiplier"),
            "dry_run": summary.get("dry_run"),
        }
    # Print machine-readable summary to stdout for cron capture.
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
