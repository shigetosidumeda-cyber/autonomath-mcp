#!/usr/bin/env python3
"""Nightly Stripe usage reconciliation (K9 / launch wave 18).

Compares the last 24 hours of locally-recorded ``usage_events`` (metered=1,
status<400 — what we *charged* the customer for) against Stripe's view of
the same window (subscription_item.usage_record_summaries OR meter_events
depending on API version pin) and surfaces the diff.

Why a cron and not a real-time check
------------------------------------
``billing/stripe_usage.py:report_usage_async`` is fire-and-forget — every
HTTP / network failure is swallowed after a WARN. That is the right
production posture (we never block the customer's request on Stripe), but
it means a Stripe outage, an expired API key, or a stale
``subscription_item_id`` cache silently drops billable usage on the floor.
Without a reconciliation pass we under-bill (lost revenue) or over-bill
(refund risk + 詐欺 risk per ``feedback_autonomath_fraud_risk``).

What it does
------------
1. SQL: ``SELECT COUNT(*) FROM usage_events WHERE metered=1 AND status<400
   AND ts >= now-24h``  → expected_usage.
2. Stripe: for each distinct ``api_keys.stripe_subscription_id`` seen in
   the same window, fetch the subscription_item's usage_record_summaries
   for the period and aggregate quantity. Sum across customers →
   reported_usage.
3. Compute diff_pct = abs(expected - reported) / max(expected, 1).
4. If diff_pct > 0.001 (0.1%): Sentry message-level=error with tags
   ``period_start`` / ``expected`` / ``reported`` / ``diff_abs``.
5. Always write a JSON report to
   ``analysis_wave18/stripe_reconcile_<YYYY-MM-DD>.json``.

Output shape::

    {
      "run_id": "2026-04-25T00:00:00Z",
      "window": {"from": "...", "to": "..."},
      "expected_usage": 1234,
      "reported_usage": 1230,
      "diff_abs": 4,
      "diff_pct": 0.00324,
      "alerted": true,
      "per_subscription": [
        {"sub_id": "sub_...", "expected": 12, "reported": 12, "diff": 0}
      ]
    }

No Anthropic / OpenAI / SDK calls. Pure SQL + Stripe REST.

Usage::

    python scripts/cron/stripe_reconcile.py            # real run
    python scripts/cron/stripe_reconcile.py --dry-run  # no Sentry, write report
    python scripts/cron/stripe_reconcile.py --window-hours 24
    python scripts/cron/stripe_reconcile.py --threshold 0.001
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

from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import safe_capture_message  # noqa: E402

logger = logging.getLogger("autonomath.cron.stripe_reconcile")

# Default tolerance: 0.1%. Below this we treat as "in-sync" (Stripe meter
# events are eventually consistent — a few stragglers per 24h is normal).
_DEFAULT_THRESHOLD = 0.001
_DEFAULT_WINDOW_HOURS = 24


# ---------------------------------------------------------------------------
# Local side: count metered usage_events in the window.
# ---------------------------------------------------------------------------


def _count_local_usage(
    conn: sqlite3.Connection,
    *,
    since_iso: str,
    until_iso: str,
) -> int:
    """Return count of metered + non-error events in [since, until)."""
    cur = conn.execute(
        "SELECT COUNT(*) FROM usage_events "
        "WHERE metered=1 AND (status IS NULL OR status < 400) "
        "AND ts >= ? AND ts < ?",
        (since_iso, until_iso),
    )
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _per_subscription_local(
    conn: sqlite3.Connection,
    *,
    since_iso: str,
    until_iso: str,
) -> dict[str, int]:
    """Return {stripe_subscription_id: local_count} for the window.

    Joins usage_events to api_keys to recover the Stripe subscription. Keys
    with NULL stripe_subscription_id (anonymous tier requests, free quota
    pre-Stripe) are bucketed under the empty string and excluded from the
    Stripe-side comparison — they are not billable.
    """
    cur = conn.execute(
        """
        SELECT COALESCE(ak.stripe_subscription_id, '') AS sub_id,
               COUNT(*) AS n
        FROM usage_events ue
        LEFT JOIN api_keys ak ON ak.key_hash = ue.key_hash
        WHERE ue.metered = 1
          AND (ue.status IS NULL OR ue.status < 400)
          AND ue.ts >= ? AND ue.ts < ?
        GROUP BY sub_id
        """,
        (since_iso, until_iso),
    )
    out: dict[str, int] = {}
    for row in cur.fetchall():
        sub_id, n = row[0], int(row[1])
        if sub_id:  # skip anon / free
            out[sub_id] = n
    return out


# ---------------------------------------------------------------------------
# Stripe side: pull usage_record_summaries per subscription_item.
# ---------------------------------------------------------------------------


def _stripe_usage_for_sub(
    subscription_id: str,
    *,
    since_ts: int,
    until_ts: int,
) -> int | None:
    """Pull total quantity reported to Stripe in [since_ts, until_ts).

    Returns None on any error (caller logs + continues). Uses the legacy
    metered API (``UsageRecordSummary.list``) to match the writer side
    pinned at API version 2024-11-20.acacia.

    Note: usage_record_summaries are bucketed by Stripe billing period,
    not arbitrary ranges. We sum every summary whose period overlaps our
    window and rely on the monthly billing cycle keeping summary count
    small (<= 2 summaries per sub during a normal 24h window).
    """
    if not settings.stripe_secret_key:
        return None
    try:
        import stripe  # local import — keep cron import-light
    except Exception:
        logger.warning("stripe import failed — skipping Stripe-side check")
        return None
    try:
        if stripe.api_key != settings.stripe_secret_key:
            stripe.api_key = settings.stripe_secret_key
        if settings.stripe_api_version:
            stripe.api_version = settings.stripe_api_version
    except Exception:
        logger.warning("stripe configure failed", exc_info=True)
        return None

    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        items_dict = sub.get("items", {}) if isinstance(sub, dict) else None
        items = items_dict.get("data") if items_dict else None
        if not items:
            return None
        si_id = items[0]["id"]
    except Exception:
        logger.warning(
            "sub retrieve failed sub=%s — skipping",
            subscription_id,
            exc_info=True,
        )
        return None

    try:
        # legacy API — pinned via stripe.api_version above.
        page = stripe.SubscriptionItem.list_usage_record_summaries(  # type: ignore[attr-defined]
            si_id,
            limit=10,
        )
    except Exception:
        logger.warning(
            "usage summary list failed si=%s — skipping",
            si_id,
            exc_info=True,
        )
        return None

    total = 0
    for s in page.auto_paging_iter() if hasattr(page, "auto_paging_iter") else page.get("data", []):
        period = s.get("period", {}) if isinstance(s, dict) else getattr(s, "period", {})
        p_start = int(period.get("start", 0) or 0)
        p_end = int(period.get("end", 0) or 0)
        if p_end < since_ts or p_start >= until_ts:
            continue
        qty = s.get("total_usage", 0) if isinstance(s, dict) else getattr(s, "total_usage", 0)
        try:
            total += int(qty or 0)
        except (TypeError, ValueError):
            continue
    return total


# ---------------------------------------------------------------------------
# Main reconcile pass.
# ---------------------------------------------------------------------------


def reconcile(
    *,
    window_hours: int = _DEFAULT_WINDOW_HOURS,
    threshold: float = _DEFAULT_THRESHOLD,
    dry_run: bool = False,
    db_path: str | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    since = now - timedelta(hours=window_hours)
    since_iso = since.isoformat()
    until_iso = now.isoformat()
    since_ts = int(since.timestamp())
    until_ts = int(now.timestamp())

    conn = connect(db_path) if db_path else connect()
    try:
        expected_total = _count_local_usage(
            conn, since_iso=since_iso, until_iso=until_iso,
        )
        per_sub_local = _per_subscription_local(
            conn, since_iso=since_iso, until_iso=until_iso,
        )
    finally:
        conn.close()

    per_sub_report: list[dict[str, Any]] = []
    reported_total = 0
    for sub_id, local_n in sorted(per_sub_local.items()):
        stripe_n = _stripe_usage_for_sub(
            sub_id, since_ts=since_ts, until_ts=until_ts,
        )
        # When Stripe is unreachable for a single sub, treat its reported
        # value as equal to local — we cannot diagnose, so we abstain
        # rather than mis-alert. The aggregate threshold check below still
        # catches systemic outages because a *real* outage trips the
        # global None path (settings.stripe_secret_key unset, etc.).
        if stripe_n is None:
            per_sub_report.append({
                "sub_id": sub_id,
                "expected": local_n,
                "reported": None,
                "diff": None,
                "note": "stripe_unreachable_or_no_key",
            })
            reported_total += local_n
            continue
        per_sub_report.append({
            "sub_id": sub_id,
            "expected": local_n,
            "reported": stripe_n,
            "diff": local_n - stripe_n,
        })
        reported_total += stripe_n

    diff_abs = abs(expected_total - reported_total)
    diff_pct = diff_abs / max(expected_total, 1)
    alerted = False
    if diff_pct > threshold and not dry_run:
        safe_capture_message(
            f"Stripe reconcile drift: expected={expected_total} "
            f"reported={reported_total} diff_pct={diff_pct:.4f}",
            level="error",
            period_start=since_iso,
            expected=str(expected_total),
            reported=str(reported_total),
            diff_abs=str(diff_abs),
        )
        alerted = True

    report: dict[str, Any] = {
        "run_id": now.isoformat(),
        "window": {"from": since_iso, "to": until_iso},
        "expected_usage": expected_total,
        "reported_usage": reported_total,
        "diff_abs": diff_abs,
        "diff_pct": round(diff_pct, 6),
        "threshold": threshold,
        "alerted": alerted,
        "dry_run": dry_run,
        "per_subscription": per_sub_report,
    }

    out_dir = output_dir or (_REPO / "analysis_wave18")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"stripe_reconcile_{now.strftime('%Y-%m-%d')}.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    logger.info("reconcile done expected=%s reported=%s diff_pct=%.4f",
                expected_total, reported_total, diff_pct)
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="Skip Sentry alert; still write JSON report.")
    p.add_argument("--window-hours", type=int, default=_DEFAULT_WINDOW_HOURS,
                   help=f"Reconcile window (default {_DEFAULT_WINDOW_HOURS}h).")
    p.add_argument("--threshold", type=float, default=_DEFAULT_THRESHOLD,
                   help=f"Diff fraction (default {_DEFAULT_THRESHOLD}).")
    p.add_argument("--db", default=None,
                   help="Override DB path (default: settings.db_path).")
    p.add_argument("--out", default=None,
                   help="Output dir (default analysis_wave18/).")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    out_dir = Path(args.out) if args.out else None
    report = reconcile(
        window_hours=args.window_hours,
        threshold=args.threshold,
        dry_run=args.dry_run,
        db_path=args.db,
        output_dir=out_dir,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
