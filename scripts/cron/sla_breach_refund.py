#!/usr/bin/env python3
"""Monthly SLA breach detection + automatic Stripe credit-note issuance.

D3 Wave 16 — self-service enterprise SLA (zero-touch ops). For every Stripe metered
customer, compute the previous calendar month's uptime from the RUM-driven
SLA aggregates that sit alongside `/v1/health/sla`, and when uptime breaches
the **99.9% enterprise target over a 30-day rolling window**, issue a Stripe
Credit Note refunding the affected requests. The customer dashboard surfaces
the credit note under "適格請求書 (請求一覧)" with a credit-note metadata
field. Stripe auto-applies the credit balance to the next invoice.

Why automatic, not a manual ticket
----------------------------------
zero-touch ops: no DPA negotiation, no email back-and-forth, no manual
breach claim form. RUM (Wave 16 E1) is the single source of truth for
uptime; aggregator output JSON lives at
`monitoring/sla_aggregates/{YYYY-MM}.json` and is mirrored to R2 for audit.
The monthly cron reads that JSON, computes refund per customer, and pushes
to Stripe CreditNote idempotently.

Refund formula
--------------
Standard tier target = 99.0% (no automatic refund, only published SLO).
Enterprise tier target = **99.9%** auto-applied to every metered customer.

    breach_minutes = (1 - uptime_pct/100) * 30 * 24 * 60
    expected_down  = (1 - 0.999) * 30 * 24 * 60   # = 43.2 min
    extra_down     = max(0, breach_minutes - expected_down)

    refund_per_min = (customer_units_per_min) * 3 JPY   # ¥3/req metered
    refund_jpy     = floor(extra_down * refund_per_min)

If `refund_jpy < 100` we skip — Stripe minimum credit note amount and our
own noise floor for transient sub-minute blips.

Idempotency
-----------
Local table `sla_breach_refund_grant` keyed on (period_yyyymm, customer_id).
Stripe call uses idempotency key
``sla_breach:{period_yyyymm}:{customer_id}`` so partial retries never
double-issue.

Run via GHA monthly workflow OR Fly machine cron:
    .github/workflows/parquet-export-monthly.yml  # combined with parquet
    0 5 1 * *  /app/.venv/bin/python /app/scripts/cron/sla_breach_refund.py

Required env: STRIPE_SECRET_KEY, JPINTEL_DB_PATH (jpintel.db),
              AUTONOMATH_DB_PATH (autonomath.db),
              SLA_AGGREGATE_DIR (default monitoring/sla_aggregates).

Exit codes: 0 ok / 1 config / 2 aggregate-missing / 3 stripe-error.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("jpcite.cron.sla_breach_refund")

# --- Constants -----------------------------------------------------------

# Enterprise SLA target — applied automatically to every metered customer
# (zero-touch, no tier upgrade, no contract negotiation). Standard published
# SLO is 99.0% but only enterprise breach triggers refund.
SLA_ENTERPRISE_UPTIME_PCT = 99.9

# 30-day rolling window in minutes — matches the public sla.html copy.
SLA_WINDOW_DAYS = 30
SLA_WINDOW_MINUTES = SLA_WINDOW_DAYS * 24 * 60

# ¥3/req metered list price (税抜).
JPY_PER_REQ = 3

# Stripe Credit Note minimum + our noise floor.
REFUND_MIN_JPY = 100

# Metadata tag so the customer dashboard can filter the credit-note feed.
SLA_REFUND_METADATA_KIND = "sla_breach_refund"


# --- Argparse + entrypoint ----------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument(
        "--period",
        help=("Period as YYYY-MM. Default = previous calendar month computed from now (JST)."),
    )
    p.add_argument(
        "--aggregate-dir",
        default=os.environ.get("SLA_AGGREGATE_DIR", "monitoring/sla_aggregates"),
        help="Directory containing {YYYY-MM}.json RUM aggregate output.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute + log refunds but do NOT call Stripe / DB write.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="DEBUG-level logging.",
    )
    return p.parse_args(argv)


def _previous_month_period_jst() -> str:
    """Return YYYY-MM for the previous calendar month in JST."""
    now_utc = datetime.now(UTC)
    # JST = UTC+9; reduce to day-precision then step back into prev month.
    now_jst = now_utc + timedelta(hours=9)
    first_of_month_jst = now_jst.replace(day=1)
    prev_month_last_day_jst = first_of_month_jst - timedelta(days=1)
    return prev_month_last_day_jst.strftime("%Y-%m")


def _load_aggregate(aggregate_dir: Path, period: str) -> dict[str, Any]:
    """Load the RUM aggregate JSON for the period.

    Schema (produced by Wave 16 E1 `scripts/ops/rum_aggregator.py`):
        {
          "period": "YYYY-MM",
          "window_days": 30,
          "uptime_pct": 99.94,                # overall
          "p95_latency_ms": 412,
          "sample_count": 12_345_678,
          "per_customer": {
             "<stripe_customer_id>": {
                "units": 250_000,
                "downtime_minutes": 35.2,
                "uptime_pct": 99.92
             }, ...
          }
        }
    """
    path = aggregate_dir / f"{period}.json"
    if not path.exists():
        raise FileNotFoundError(f"SLA aggregate missing: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _ensure_grant_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sla_breach_refund_grant (
            period_yyyymm TEXT NOT NULL,
            customer_id   TEXT NOT NULL,
            downtime_min  REAL NOT NULL,
            refund_jpy    INTEGER NOT NULL,
            stripe_credit_note_id TEXT,
            granted_at    TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (period_yyyymm, customer_id)
        )
        """
    )


def compute_refund_jpy(
    downtime_minutes: float,
    units_in_window: int,
    *,
    target_uptime_pct: float = SLA_ENTERPRISE_UPTIME_PCT,
    window_minutes: int = SLA_WINDOW_MINUTES,
    jpy_per_req: int = JPY_PER_REQ,
) -> int:
    """Pure helper — easy to unit test without DB / Stripe.

    Returns 0 when downtime sits within the published SLO (no refund), or
    when the customer issued zero requests in the window.
    """
    if units_in_window <= 0 or window_minutes <= 0:
        return 0
    expected_down = (1 - target_uptime_pct / 100.0) * window_minutes
    extra_down = max(0.0, downtime_minutes - expected_down)
    if extra_down <= 0:
        return 0
    # Estimate the fraction of requests that landed in the breached window.
    affected_units = units_in_window * (extra_down / window_minutes)
    refund_jpy = math.floor(affected_units * jpy_per_req)
    return max(0, refund_jpy)


def _issue_stripe_credit_note(
    stripe_client: Any,
    *,
    customer_id: str,
    period_yyyymm: str,
    downtime_minutes: float,
    refund_jpy: int,
    invoice_id: str,
) -> Any:
    description = (
        f"SLA breach refund ¥{refund_jpy:,} — "
        f"{downtime_minutes:.1f} min downtime in {period_yyyymm} "
        f"(enterprise target 99.9%, 30-day window)"
    )
    return stripe_client.CreditNote.create(
        invoice=invoice_id,
        amount=refund_jpy,
        memo=description,
        reason="other",
        metadata={
            "kind": SLA_REFUND_METADATA_KIND,
            "period_yyyymm": period_yyyymm,
            "downtime_minutes": f"{downtime_minutes:.2f}",
            "refund_jpy": str(refund_jpy),
        },
        idempotency_key=f"sla_breach:{period_yyyymm}:{customer_id}",
    )


def _previous_month_invoice_id(stripe_client: Any, customer_id: str, period: str) -> str | None:
    """Best-effort lookup: most-recent paid metered invoice for the customer.

    Mirrors `volume_rebate._previous_month_invoice_id` semantics but kept
    standalone to avoid coupling.
    """
    invoices = stripe_client.Invoice.list(customer=customer_id, limit=10, status="paid")
    items = getattr(invoices, "data", invoices) or []
    if not items:
        return None
    # Prefer the most-recently-finalised invoice whose period_end falls in the period.
    for inv in items:
        period_end = getattr(inv, "period_end", None) or inv.get("period_end")  # type: ignore[union-attr]
        if not period_end:
            continue
        dt = datetime.fromtimestamp(int(period_end), tz=UTC)
        if dt.strftime("%Y-%m") == period:
            return getattr(inv, "id", None) or inv.get("id")  # type: ignore[union-attr]
    # Fallback: first invoice in list.
    inv0 = items[0]
    return getattr(inv0, "id", None) or inv0.get("id")  # type: ignore[union-attr]


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    period = args.period or _previous_month_period_jst()
    aggregate_dir = Path(args.aggregate_dir)
    logger.info("sla_breach_refund.start period=%s dry_run=%s", period, args.dry_run)

    try:
        agg = _load_aggregate(aggregate_dir, period)
    except FileNotFoundError as exc:
        logger.error("sla_breach_refund.no_aggregate %s", exc)
        return 2

    per_customer = agg.get("per_customer", {})
    if not per_customer:
        logger.info("sla_breach_refund.no_customer_rows period=%s", period)
        return 0

    db_path = os.environ.get("JPINTEL_DB_PATH", "data/jpintel.db")
    conn: sqlite3.Connection | None = None
    if not args.dry_run:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        _ensure_grant_table(conn)

    stripe_client: Any = None
    if not args.dry_run:
        try:
            import stripe  # type: ignore
        except ImportError:
            logger.error("sla_breach_refund.stripe_missing pip install stripe")
            return 1
        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
        if not stripe.api_key:
            logger.error("sla_breach_refund.no_stripe_key")
            return 1
        stripe_client = stripe

    issued = 0
    skipped = 0
    total_refund = 0
    for customer_id, row in per_customer.items():
        units = int(row.get("units", 0))
        downtime_min = float(row.get("downtime_minutes", 0.0))
        refund_jpy = compute_refund_jpy(downtime_min, units)
        if refund_jpy < REFUND_MIN_JPY:
            logger.debug(
                "sla_breach_refund.skip_noise customer=%s refund=%d",
                customer_id,
                refund_jpy,
            )
            skipped += 1
            continue
        logger.info(
            "sla_breach_refund.compute customer=%s downtime=%.2fmin refund_jpy=%d",
            customer_id,
            downtime_min,
            refund_jpy,
        )
        total_refund += refund_jpy
        if args.dry_run or conn is None or stripe_client is None:
            continue
        existing = conn.execute(
            "SELECT stripe_credit_note_id FROM sla_breach_refund_grant "
            "WHERE period_yyyymm = ? AND customer_id = ?",
            (period, customer_id),
        ).fetchone()
        if existing is not None:
            logger.info(
                "sla_breach_refund.already_granted customer=%s credit_note=%s",
                customer_id,
                existing["stripe_credit_note_id"],
            )
            continue
        try:
            invoice_id = _previous_month_invoice_id(stripe_client, customer_id, period)
            if invoice_id is None:
                logger.warning(
                    "sla_breach_refund.no_invoice customer=%s period=%s — skipped",
                    customer_id,
                    period,
                )
                continue
            note = _issue_stripe_credit_note(
                stripe_client,
                customer_id=customer_id,
                period_yyyymm=period,
                downtime_minutes=downtime_min,
                refund_jpy=refund_jpy,
                invoice_id=invoice_id,
            )
            conn.execute(
                "INSERT INTO sla_breach_refund_grant "
                "(period_yyyymm, customer_id, downtime_min, refund_jpy, stripe_credit_note_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (period, customer_id, downtime_min, refund_jpy, getattr(note, "id", None)),
            )
            conn.commit()
            issued += 1
            logger.info(
                "sla_breach_refund.granted customer=%s credit_note=%s refund_jpy=%d",
                customer_id,
                getattr(note, "id", None),
                refund_jpy,
            )
        except Exception as exc:
            logger.exception(
                "sla_breach_refund.stripe_error customer=%s err=%s",
                customer_id,
                exc,
            )

    logger.info(
        "sla_breach_refund.done period=%s issued=%d skipped=%d total_refund_jpy=%d dry_run=%s",
        period,
        issued,
        skipped,
        total_refund,
        args.dry_run,
    )
    if conn is not None:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(run())
