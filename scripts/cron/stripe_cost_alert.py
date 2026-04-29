#!/usr/bin/env python3
"""Daily cost alert — flag when monthly infra spend approaches budget cap.

What it sums (current MTD, UTC month boundary):
  1. Stripe processing fees on `charge.succeeded` events (3.6% + ¥40).
     Pulled from Stripe Events API, scoped to the current month.
  2. Self-reported cost lines in `cost_ledger` table (if present): Fly
     compute, Cloudflare R2 egress, Postmark email send fees, etc. Cron
     hosts that ingest these are out of scope for this script — we just
     read whatever rows exist.
  3. **NEVER** sums Anthropic / OpenAI / Claude API. Per memory
     `feedback_autonomath_no_api_use` AutonoMath does not pay for LLM
     inference at all (¥3/req structure breaks if we did). If a row
     with `provider='anthropic'` ever shows up in cost_ledger that's
     itself an alarm — surfaced as a P0 "no_anthropic_invariant_violated".

Threshold (default ¥10,000/month, override via $AUTONOMATH_BUDGET_JPY):
  * 80%  of cap → warn  (Sentry message-level=warning + email digest)
  * 100% of cap → error (Sentry message-level=error + email digest)
  * 150% of cap → fatal (Sentry message-level=fatal — operator pages)

No Anthropic / claude / SDK calls. Pure SQL + Stripe REST.

Usage:
    python scripts/cron/stripe_cost_alert.py            # real run
    python scripts/cron/stripe_cost_alert.py --dry-run  # no Sentry, no email
    python scripts/cron/stripe_cost_alert.py --budget 5000  # override cap
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat, safe_capture_message  # noqa: E402

logger = logging.getLogger("autonomath.cron.cost_alert")

# Budget defaults (yen). Override via env or --budget.
_DEFAULT_BUDGET_JPY = int(os.getenv("AUTONOMATH_BUDGET_JPY", "10000"))

# Banned providers — see memory `feedback_autonomath_no_api_use`. If a
# cost_ledger row tagged with one of these shows up we treat it as an
# invariant violation, not a budget data point.
_BANNED_PROVIDERS = {"anthropic", "openai", "claude"}


@dataclass
class CostBreakdown:
    """Per-line item totals for the alert email + Sentry tag set."""

    month: str  # "YYYY-MM"
    stripe_fees_jpy: int
    self_reported_jpy: int
    total_jpy: int
    budget_jpy: int
    pct: float  # total / budget * 100

    def severity(self) -> str:
        """Sentry severity bucket. Cap'd at fatal regardless of pct."""
        if self.pct >= 150.0:
            return "fatal"
        if self.pct >= 100.0:
            return "error"
        if self.pct >= 80.0:
            return "warning"
        return "info"


# ---------------------------------------------------------------------------
# Stripe fee aggregation
# ---------------------------------------------------------------------------


def _sum_stripe_fees_mtd(*, dry_run: bool) -> int:
    """Sum Stripe fees (in yen) for charges succeeded since UTC month start.

    Returns 0 when:
      * STRIPE_SECRET_KEY is unset (dev / test / partial env)
      * dry_run=True (the caller is just smoke-testing the wiring)
      * stripe import fails
      * any HTTP / API error (we log + return 0; cost alert must not crash
        the cron host even if Stripe is misbehaving)
    """
    if dry_run:
        logger.info("[dry-run] skipping stripe fees fetch")
        return 0

    secret = settings.stripe_secret_key
    if not secret:
        logger.info("STRIPE_SECRET_KEY unset; stripe fees = 0")
        return 0

    try:
        import stripe
    except ImportError:
        logger.warning("stripe package not installed; fees = 0")
        return 0

    if stripe.api_key != secret:
        stripe.api_key = secret
    if settings.stripe_api_version:
        stripe.api_version = settings.stripe_api_version

    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    since_ts = int(month_start.timestamp())

    total_fee_jpy = 0
    try:
        # Paginate via auto_paging_iter — bounded by month-to-date so even
        # at sustained launch volume this is at most a few thousand
        # charges, well within Stripe's 100/page default.
        charges_iter = stripe.Charge.list(
            created={"gte": since_ts},
            limit=100,
        ).auto_paging_iter()
        for ch in charges_iter:
            if not ch.get("paid"):
                continue
            # `application_fee_amount` is null on direct charges; the real
            # field is `balance_transaction.fee` (set after settlement).
            # For pending / not-yet-settled charges we estimate at 3.6% +
            # ¥40 to keep MTD alerts directionally correct.
            bt_id = ch.get("balance_transaction")
            fee_jpy: int = 0
            if bt_id:
                try:
                    bt = stripe.BalanceTransaction.retrieve(bt_id)
                    fee_jpy = int(bt.get("fee", 0))
                except Exception as exc:  # noqa: BLE001 — non-fatal
                    logger.debug("balance_txn lookup failed for %s: %s", ch.get("id"), exc)
                    fee_jpy = int(ch.get("amount", 0) * 0.036) + 40
            else:
                fee_jpy = int(ch.get("amount", 0) * 0.036) + 40
            total_fee_jpy += fee_jpy
    except Exception as exc:  # noqa: BLE001
        logger.warning("stripe charge.list failed: %s", exc)
        return 0

    return total_fee_jpy


# ---------------------------------------------------------------------------
# Self-reported cost ledger (optional table; absent = 0)
# ---------------------------------------------------------------------------


def _sum_self_reported_mtd(conn: sqlite3.Connection) -> tuple[int, list[str]]:
    """Sum `cost_ledger.amount_jpy` for the current month if the table exists.

    Returns (total_jpy, banned_provider_violations). If `cost_ledger`
    does not exist (pre-launch), returns (0, []).
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='cost_ledger'"
    ).fetchone()
    if not row:
        return 0, []

    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    total = conn.execute(
        "SELECT COALESCE(SUM(amount_jpy), 0) FROM cost_ledger WHERE incurred_at >= ?",
        (month_start,),
    ).fetchone()[0]

    # Detect banned-provider rows. These are an invariant violation, not
    # a budget line — we surface them as a separate severity=fatal alert.
    violations: list[str] = []
    for prov in _BANNED_PROVIDERS:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM cost_ledger WHERE incurred_at >= ? AND lower(provider) = ?",
            (month_start, prov),
        ).fetchone()[0]
        if cnt:
            violations.append(f"{prov}({cnt})")

    return int(total), violations


# ---------------------------------------------------------------------------
# Alert dispatch
# ---------------------------------------------------------------------------


def _emit_alert(breakdown: CostBreakdown, *, dry_run: bool) -> None:
    severity = breakdown.severity()

    payload = {
        "kind": "cost_alert",
        "month": breakdown.month,
        "stripe_fees_jpy": breakdown.stripe_fees_jpy,
        "self_reported_jpy": breakdown.self_reported_jpy,
        "total_jpy": breakdown.total_jpy,
        "budget_jpy": breakdown.budget_jpy,
        "pct": round(breakdown.pct, 1),
        "severity": severity,
    }
    logger.warning("cost_alert %s", json.dumps(payload, ensure_ascii=False))

    if dry_run:
        logger.info("[dry-run] not transmitting to Sentry")
        return

    if severity == "info":
        # Below 80% — log only, do not page.
        return

    safe_capture_message(
        f"AutonoMath monthly cost {breakdown.pct:.0f}% of ¥{breakdown.budget_jpy:,} "
        f"(total ¥{breakdown.total_jpy:,}, stripe ¥{breakdown.stripe_fees_jpy:,})",
        level=severity,
        month=breakdown.month,
        budget_jpy=breakdown.budget_jpy,
        total_jpy=breakdown.total_jpy,
    )


def _emit_violation(violations: list[str], *, dry_run: bool) -> None:
    """Banned-provider rows in cost_ledger trigger a fatal alert.

    Per memory `feedback_autonomath_no_api_use` we never pay for LLM
    inference. If a row with provider='anthropic' shows up the upstream
    pipeline is broken — pre-launch operator must investigate before
    the next billing cycle closes.
    """
    msg = (
        f"INVARIANT VIOLATION: cost_ledger contains banned providers "
        f"({', '.join(violations)}). Per feedback_autonomath_no_api_use, "
        f"AutonoMath must not pay for LLM inference. Inspect cost_ledger "
        f"and root-cause the ingest path."
    )
    logger.error(msg)
    if dry_run:
        return
    safe_capture_message(msg, level="fatal", invariant="no_api_use")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute totals + log, but do not transmit to Sentry / email.",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=_DEFAULT_BUDGET_JPY,
        help="Monthly cap in JPY. Default %(default)s.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    with heartbeat("stripe_cost_alert") as hb:
        stripe_jpy = _sum_stripe_fees_mtd(dry_run=args.dry_run)

        self_jpy = 0
        violations: list[str] = []
        try:
            with connect() as conn:
                self_jpy, violations = _sum_self_reported_mtd(conn)
        except Exception as exc:  # noqa: BLE001 — non-fatal
            logger.warning("cost_ledger sum failed: %s", exc)

        total = stripe_jpy + self_jpy
        pct = (total / args.budget * 100.0) if args.budget else 0.0

        now = datetime.now(UTC)
        breakdown = CostBreakdown(
            month=now.strftime("%Y-%m"),
            stripe_fees_jpy=stripe_jpy,
            self_reported_jpy=self_jpy,
            total_jpy=total,
            budget_jpy=args.budget,
            pct=pct,
        )

        _emit_alert(breakdown, dry_run=args.dry_run)

        hb["rows_processed"] = int(total)
        hb["metadata"] = {
            "month": breakdown.month,
            "stripe_fees_jpy": stripe_jpy,
            "self_reported_jpy": self_jpy,
            "budget_jpy": args.budget,
            "pct": pct,
            "violations": len(violations),
            "dry_run": bool(args.dry_run),
        }

        if violations:
            _emit_violation(violations, dry_run=args.dry_run)
            return 2  # operator must investigate

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
