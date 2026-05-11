#!/usr/bin/env python3
"""Monthly volume rebate (retrospective ¥0.50/req credit for >1M req).

Wave 15 D2 — strictly metered economics with NO tier surface. Customers
who exceed **1,000,000 billable units in a single calendar month** receive
a retrospective ¥0.50/req credit on the over-1M portion, issued as a
Stripe Credit Note against the previous month's invoice. The credit is
applied automatically against the *next* month's invoice.

Why retrospective and not a tier
--------------------------------
A tier ("¥3/req for the first 1M, ¥2.50/req thereafter") would create a
discrimination surface and break the CLAUDE.md SOT (¥3/req metered only,
no tier SKUs). A retrospective rebate keeps every call uniformly billed
at ¥3 list and treats the rebate as a *post-fact* operator goodwill
gesture for unusually heavy load. The customer still sees ¥3/req on
every invoice; the credit note is a separate line.

Mechanism
---------
1. Group `usage_events` rows for the previous calendar month (JST) by
   the customer's Stripe customer_id, summing `quantity` (billable units).
2. For every (customer_id, units) pair where units > 1,000,000:
     rebate_jpy = floor((units - 1,000,000) * 0.50)
3. Issue ``stripe.CreditNote.create()`` against the customer's previous
   month metered invoice with `amount=rebate_jpy` and metadata
   ``kind=volume_rebate`` so the customer dashboard surfaces it under
   "適格請求書 (請求一覧)" with a 信頼できる出典 string.
4. Stripe auto-applies the credit note balance to the next invoice.

Idempotency
-----------
Local table `volume_rebate_grant` records (period_yyyymm, customer_id)
as PRIMARY KEY. Re-running the cron in the same month skips already-
granted rows. The Stripe call uses idempotency key
``volume_rebate:{period_yyyymm}:{customer_id}`` so a partial retry never
issues a second credit note.

Why ¥0.50
---------
Pulled from analysis_wave18 §3 — at >1M req/month the marginal infra
cost per request drops below ¥0.20 (SQLite L3 cache hit > 98 %). A
¥0.50 rebate keeps gross margin > 80 % while signaling that heavy load
is welcome. The rebate amount is intentionally NOT discoverable via API
— it's a static policy in the cron and the pricing page.

Usage::

    python scripts/cron/volume_rebate.py                  # process previous month
    python scripts/cron/volume_rebate.py --period 202604  # explicit YYYYMM
    python scripts/cron/volume_rebate.py --dry-run        # log only, no Stripe call

Schedule: monthly cron, JST 03:00 on the 2nd of every month (after Stripe
has finalised the previous month's invoice on the 1st).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

try:
    import stripe  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover — cron environment always has stripe
    stripe = None  # type: ignore[assignment]


logger = logging.getLogger("jpintel.cron.volume_rebate")

VOLUME_REBATE_THRESHOLD_UNITS: int = 1_000_000
VOLUME_REBATE_JPY_PER_REQ: float = 0.50
VOLUME_REBATE_METADATA_KIND: str = "volume_rebate"


def _previous_month_yyyymm(today: _dt.date | None = None) -> str:
    """Return the previous calendar month as YYYYMM (JST)."""
    today = today or _dt.datetime.now(_dt.UTC).astimezone(
        _dt.timezone(_dt.timedelta(hours=9))
    ).date()
    first_of_this_month = today.replace(day=1)
    last_of_prev = first_of_this_month - _dt.timedelta(days=1)
    return f"{last_of_prev.year:04d}{last_of_prev.month:02d}"


def _period_bounds_jst(period_yyyymm: str) -> tuple[str, str]:
    """Return (start_iso, end_iso) JST bounds for the YYYYMM period.

    Returns UTC ISO strings because `usage_events.ts` is stored UTC.
    Boundaries are aligned to JST midnight (UTC-9h shift) so a request at
    JST 23:59:59 on the last day stays in the correct month.
    """
    if len(period_yyyymm) != 6 or not period_yyyymm.isdigit():
        raise ValueError(f"period must be YYYYMM, got {period_yyyymm!r}")
    year = int(period_yyyymm[:4])
    month = int(period_yyyymm[4:])
    start_jst = _dt.datetime(year, month, 1, 0, 0, 0, tzinfo=_dt.timezone(_dt.timedelta(hours=9)))
    if month == 12:
        end_jst = _dt.datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=start_jst.tzinfo)
    else:
        end_jst = _dt.datetime(year, month + 1, 1, 0, 0, 0, tzinfo=start_jst.tzinfo)
    return start_jst.astimezone(_dt.UTC).isoformat(), end_jst.astimezone(_dt.UTC).isoformat()


def _ensure_grant_table(conn: sqlite3.Connection) -> None:
    """Create the local idempotency table on first run."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS volume_rebate_grant (
            period_yyyymm     TEXT NOT NULL,
            customer_id       TEXT NOT NULL,
            units             INTEGER NOT NULL,
            rebate_jpy        INTEGER NOT NULL,
            stripe_credit_note_id TEXT,
            granted_at        TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (period_yyyymm, customer_id)
        )
        """
    )


def compute_rebate_jpy(units: int) -> int:
    """¥0.50 per req for the over-1M portion. Floor to whole yen.

    units <= threshold → 0
    units > threshold  → floor((units - threshold) * 0.50)
    """
    if units <= VOLUME_REBATE_THRESHOLD_UNITS:
        return 0
    excess = units - VOLUME_REBATE_THRESHOLD_UNITS
    return int(excess * VOLUME_REBATE_JPY_PER_REQ)


def _aggregate_monthly_units(
    conn: sqlite3.Connection,
    *,
    start_iso: str,
    end_iso: str,
) -> list[tuple[str, int]]:
    """Sum quantity per stripe customer for the given UTC window.

    Excludes anonymous credit-pack-funded rows because those were already
    paid up-front and are not part of the metered subscription invoice
    that the credit note attaches to.
    """
    rows = conn.execute(
        """
        SELECT api_keys.stripe_customer_id AS customer_id,
               SUM(usage_events.quantity) AS units
        FROM usage_events
        JOIN api_keys ON api_keys.key_hash = usage_events.key_hash
        WHERE usage_events.ts >= ?
          AND usage_events.ts <  ?
          AND COALESCE(usage_events.credit_pack_kind, 'metered') != 'anon'
          AND api_keys.stripe_customer_id IS NOT NULL
        GROUP BY api_keys.stripe_customer_id
        HAVING units > ?
        """,
        (start_iso, end_iso, VOLUME_REBATE_THRESHOLD_UNITS),
    ).fetchall()
    return [(str(r[0]), int(r[1])) for r in rows]


def _previous_month_invoice_id(stripe_client: Any, customer_id: str, period_yyyymm: str) -> str | None:
    """Find the metered invoice issued for the period, if any."""
    year = int(period_yyyymm[:4])
    month = int(period_yyyymm[4:])
    period_start_ts = int(_dt.datetime(year, month, 1, tzinfo=_dt.UTC).timestamp())
    if month == 12:
        period_end_ts = int(_dt.datetime(year + 1, 1, 1, tzinfo=_dt.UTC).timestamp())
    else:
        period_end_ts = int(_dt.datetime(year, month + 1, 1, tzinfo=_dt.UTC).timestamp())
    invoices = stripe_client.Invoice.list(
        customer=customer_id,
        created={"gte": period_start_ts, "lt": period_end_ts + 86400 * 7},
        limit=10,
    )
    for inv in invoices.auto_paging_iter():
        md = getattr(inv, "metadata", None) or {}
        if md.get("kind") in {"credit_pack", "credit_pack_anon"}:
            continue
        return str(inv.id)
    return None


def issue_volume_rebate(
    stripe_client: Any,
    *,
    customer_id: str,
    period_yyyymm: str,
    units: int,
    invoice_id: str,
    rebate_jpy: int,
) -> Any:
    """Create a Stripe Credit Note for the rebate amount."""
    description = (
        f"Volume rebate ¥{rebate_jpy:,} — "
        f"{units:,} units in {period_yyyymm} (>1M threshold, ¥0.50/req over-1M)"
    )
    return stripe_client.CreditNote.create(
        invoice=invoice_id,
        amount=rebate_jpy,
        memo=description,
        reason="other",
        metadata={
            "kind": VOLUME_REBATE_METADATA_KIND,
            "period_yyyymm": period_yyyymm,
            "units": str(units),
            "rebate_jpy": str(rebate_jpy),
        },
        idempotency_key=f"volume_rebate:{period_yyyymm}:{customer_id}",
    )


def _db_path() -> Path:
    raw = (
        os.environ.get("JPINTEL_DB_PATH")
        or os.environ.get("AUTONOMATH_DB_PATH")
        or "data/jpintel.db"
    )
    return Path(raw)


def run(period_yyyymm: str | None = None, *, dry_run: bool = False) -> int:
    """Process a calendar month. Returns 0 on success, non-zero on partial failure."""
    period = period_yyyymm or _previous_month_yyyymm()
    start_iso, end_iso = _period_bounds_jst(period)
    logger.info("volume_rebate.start period=%s window=[%s, %s) dry_run=%s", period, start_iso, end_iso, dry_run)

    if stripe is None and not dry_run:
        logger.error("stripe SDK not importable and not dry-run; aborting")
        return 2

    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        _ensure_grant_table(conn)
        candidates = _aggregate_monthly_units(conn, start_iso=start_iso, end_iso=end_iso)
        logger.info("volume_rebate.candidates count=%d", len(candidates))

        failures = 0
        for customer_id, units in candidates:
            rebate_jpy = compute_rebate_jpy(units)
            if rebate_jpy <= 0:
                continue
            existing = conn.execute(
                "SELECT stripe_credit_note_id FROM volume_rebate_grant "
                "WHERE period_yyyymm = ? AND customer_id = ?",
                (period, customer_id),
            ).fetchone()
            if existing is not None:
                logger.info(
                    "volume_rebate.skip already_granted customer=%s period=%s credit_note=%s",
                    customer_id, period, existing["stripe_credit_note_id"],
                )
                continue
            logger.info(
                "volume_rebate.compute customer=%s units=%d rebate_jpy=%d",
                customer_id, units, rebate_jpy,
            )
            if dry_run:
                continue
            try:
                invoice_id = _previous_month_invoice_id(stripe, customer_id, period)
                if invoice_id is None:
                    logger.warning(
                        "volume_rebate.no_invoice customer=%s period=%s — skipped",
                        customer_id, period,
                    )
                    failures += 1
                    continue
                note = issue_volume_rebate(
                    stripe,
                    customer_id=customer_id,
                    period_yyyymm=period,
                    units=units,
                    invoice_id=invoice_id,
                    rebate_jpy=rebate_jpy,
                )
                conn.execute(
                    "INSERT INTO volume_rebate_grant "
                    "(period_yyyymm, customer_id, units, rebate_jpy, stripe_credit_note_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (period, customer_id, units, rebate_jpy, getattr(note, "id", None)),
                )
                conn.commit()
                logger.info(
                    "volume_rebate.granted customer=%s credit_note=%s rebate_jpy=%d",
                    customer_id, getattr(note, "id", None), rebate_jpy,
                )
            except Exception:
                logger.exception("volume_rebate.failed customer=%s", customer_id)
                failures += 1
        logger.info("volume_rebate.done period=%s failures=%d", period, failures)
        return 0 if failures == 0 else 1
    finally:
        conn.close()


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", help="YYYYMM (defaults to previous JST month)")
    parser.add_argument("--dry-run", action="store_true", help="Log only, no Stripe call")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return run(period_yyyymm=args.period, dry_run=args.dry_run)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
