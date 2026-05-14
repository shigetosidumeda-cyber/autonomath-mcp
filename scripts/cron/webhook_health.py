#!/usr/bin/env python3
"""Synthetic Stripe webhook health monitor (R3 fix from Stripe audit).

Background
----------
The webhook handler in ``src/jpintel_mcp/api/billing.py`` (around line 805)
deliberately swallows ALL handler exceptions and then COMMITs the dedup
row to suppress retry storms — the trade-off is that on a hard handler
failure (e.g. transient sqlite3 ``OperationalError`` under WAL contention)
a customer can pay Stripe but never get their API key issued. Sentry
catches the exception, but if Sentry is rate-limited / misconfigured /
down the operator never finds out.

This script is the synthetic safety net. It runs as a cron job and
flags two anomalies that would otherwise silently cost the operator a
customer:

  1. ``customer.subscription.created`` count vs ``invoice.paid`` count
     deviates by more than 2σ from the 7-day median. Under the metered
     ¥3/req plan these two events fire in near-1:1 ratio (Stripe sends
     one invoice.paid per subscription per cycle), so a sudden drop of
     subscription.created events points at a webhook delivery / handler
     dispatch outage.

  2. The gap between ``received_at`` and ``processed_at`` exceeds 60s on
     any event in the rolling 24h window. Stripe enforces a 5s deadline
     on the HTTP response, but ``processed_at`` is written AFTER the
     dispatch tree finishes, so a 60s gap signals a long-stalled handler
     (DB lock, blocking Stripe API call without timeout, etc.).

Dry-run output samples are deterministic enough that the operator can
copy-paste them into a runbook check.

Why not Stripe Dashboard?
~~~~~~~~~~~~~~~~~~~~~~~~~
The Stripe Dashboard surfaces webhook delivery failures but NOT
post-delivery handler outcomes. The 200 we return from billing.webhook
is "Stripe heard us," not "we issued the key." Only ``stripe_webhook_events``
(local, written by the handler itself) carries the post-dispatch truth.

No Anthropic / OpenAI / SDK calls. Pure SQL + statistics.

Usage
-----
    python scripts/cron/webhook_health.py             # real run
    python scripts/cron/webhook_health.py --dry-run   # log only, no Sentry
    python scripts/cron/webhook_health.py --window-hours 6  # tighter look-back
    python scripts/cron/webhook_health.py --gap-seconds 30  # stricter stall
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat, safe_capture_message  # noqa: E402

logger = logging.getLogger("autonomath.cron.webhook_health")

# Default thresholds — overridable via CLI flags.
_DEFAULT_WINDOW_HOURS = 24
_DEFAULT_BASELINE_DAYS = 7
_DEFAULT_GAP_SECONDS = 60
_DEFAULT_SIGMA = 2.0

# Minimum baseline samples before we trust the σ test. Below this we
# warn instead of paging — a 2-day-old DB has too few prior days to
# reason about variance.
_MIN_BASELINE_DAYS = 3

# Minimum invoice.paid count in the window before the ratio test runs.
# Avoids paging on "0 / 0" in the very first launch days when traffic
# is sparse.
_MIN_INVOICE_PAID_FOR_RATIO = 5


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class EventCount:
    """Counts of a single event_type within a time window."""

    event_type: str
    count: int


@dataclass
class HealthReport:
    """Aggregated finding set for one cron run."""

    window_hours: int
    baseline_days: int
    sigma: float
    gap_seconds: int

    # Window counts (last N hours).
    sub_created: int = 0
    invoice_paid: int = 0
    sub_updated: int = 0
    sub_deleted: int = 0
    payment_failed: int = 0
    refunded: int = 0
    other: int = 0

    # Baseline (rolling N-day median, per-day, for the two key event types).
    baseline_sub_created_median: float = 0.0
    baseline_sub_created_stdev: float = 0.0
    baseline_invoice_paid_median: float = 0.0
    baseline_invoice_paid_stdev: float = 0.0

    # Days actually present in baseline (may be < baseline_days at launch).
    baseline_days_present: int = 0

    # Anomaly findings.
    findings: list[dict[str, object]] = field(default_factory=list)

    # Stalled events (received_at - processed_at gap > N s OR processed_at NULL
    # despite the row aging past the gap window).
    stalled_events: list[dict[str, object]] = field(default_factory=list)

    def severity(self) -> str:
        """Highest severity across findings + stalls. info => no page."""
        if self.stalled_events:
            return "error"
        if not self.findings:
            return "info"
        levels = {f.get("level", "warning") for f in self.findings}
        for tier in ("fatal", "error", "warning", "info"):
            if tier in levels:
                return tier
        return "info"


# ---------------------------------------------------------------------------
# Window queries
# ---------------------------------------------------------------------------


def _has_table(conn: sqlite3.Connection) -> bool:
    """Return True iff stripe_webhook_events exists in this DB."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stripe_webhook_events'"
    ).fetchone()
    return bool(row)


def _count_events_by_type(
    conn: sqlite3.Connection,
    *,
    since_iso: str,
    until_iso: str | None = None,
) -> dict[str, int]:
    """Sum events per ``event_type`` between since and until (UTC ISO)."""
    if until_iso is None:
        sql = (
            "SELECT event_type, COUNT(*) FROM stripe_webhook_events "
            "WHERE received_at >= ? GROUP BY event_type"
        )
        rows = conn.execute(sql, (since_iso,)).fetchall()
    else:
        sql = (
            "SELECT event_type, COUNT(*) FROM stripe_webhook_events "
            "WHERE received_at >= ? AND received_at < ? GROUP BY event_type"
        )
        rows = conn.execute(sql, (since_iso, until_iso)).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def _per_day_counts(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    days: int,
    end_iso: str,
) -> list[int]:
    """Return per-day count list (oldest first) for the prior ``days`` days
    ending at ``end_iso`` (NOT including the active window).
    """
    out: list[int] = []
    end = datetime.fromisoformat(end_iso)
    for d in range(days, 0, -1):
        day_end = end - timedelta(days=d - 1)
        day_start = day_end - timedelta(days=1)
        cnt = conn.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events "
            "WHERE event_type = ? AND received_at >= ? AND received_at < ?",
            (event_type, day_start.isoformat(), day_end.isoformat()),
        ).fetchone()[0]
        out.append(int(cnt))
    return out


# ---------------------------------------------------------------------------
# Stall detection
# ---------------------------------------------------------------------------


def _stalled_events(
    conn: sqlite3.Connection,
    *,
    since_iso: str,
    gap_seconds: int,
) -> list[dict[str, object]]:
    """Find events whose dispatch took longer than ``gap_seconds``.

    Two failure modes are flagged:

      1. ``processed_at`` set but ``processed_at - received_at`` > gap.
         Handler ran to completion but slowly — DB lock storm or a
         blocking Stripe retrieve without a timeout.
      2. ``processed_at IS NULL`` AND ``now - received_at`` > gap.
         The dedup row was inserted (BEGIN IMMEDIATE landed) but the
         COMMIT never happened. Either the handler raised after dedup
         insert and before COMMIT (highly unusual given the wrap), or
         the process SIGTERM'd mid-dispatch.
    """
    # SQLite's ``strftime('%s', x)`` returns Unix-seconds as TEXT; cast
    # to int for arithmetic. Both timestamps are stored as
    # ``datetime('now')`` ISO strings (UTC, no tz suffix).
    rows = conn.execute(
        "SELECT event_id, event_type, received_at, processed_at, "
        "       CAST(strftime('%s', COALESCE(processed_at, datetime('now'))) AS INTEGER) - "
        "       CAST(strftime('%s', received_at) AS INTEGER) AS gap_s "
        "FROM stripe_webhook_events "
        "WHERE received_at >= ? "
        "  AND ("
        "      (processed_at IS NOT NULL AND "
        "       CAST(strftime('%s', processed_at) AS INTEGER) - "
        "       CAST(strftime('%s', received_at) AS INTEGER) > ?)"
        "      OR "
        "      (processed_at IS NULL AND "
        "       CAST(strftime('%s', 'now') AS INTEGER) - "
        "       CAST(strftime('%s', received_at) AS INTEGER) > ?)"
        "  )"
        "ORDER BY received_at DESC LIMIT 50",
        (since_iso, gap_seconds, gap_seconds),
    ).fetchall()
    out: list[dict[str, object]] = []
    for r in rows:
        out.append(
            {
                "event_id": r[0],
                "event_type": r[1],
                "received_at": r[2],
                "processed_at": r[3],
                "gap_seconds": int(r[4]) if r[4] is not None else None,
                "kind": "unprocessed" if r[3] is None else "slow",
            }
        )
    return out


# ---------------------------------------------------------------------------
# Anomaly engine
# ---------------------------------------------------------------------------


def _detect_subscription_dropoff(report: HealthReport) -> None:
    """If subscription.created is suspiciously low for the window, flag it.

    Two co-tests, both must be active for a paging-level finding:

      * Ratio test: ``invoice.paid`` ≥ minimum AND
        ``sub_created / invoice.paid`` < 0.5. Flags the 詐欺-adjacent
        case where invoices keep landing but subscription.created
        events are getting dropped (P0 — customer paid, no key).
      * σ test: window_sub_created < median - σ * stdev (over the
        rolling 7-day baseline, scaled to the window length).

    Below ``_MIN_BASELINE_DAYS`` of baseline data the σ test is replaced
    with a ``warning`` informational finding instead of a page.
    """
    if report.invoice_paid >= _MIN_INVOICE_PAID_FOR_RATIO:
        ratio = report.sub_created / report.invoice_paid if report.invoice_paid else 0.0
        if ratio < 0.5:
            report.findings.append(
                {
                    "kind": "subscription_created_dropoff_vs_invoice_paid",
                    "level": "fatal",
                    "ratio": round(ratio, 3),
                    "sub_created": report.sub_created,
                    "invoice_paid": report.invoice_paid,
                    "message": (
                        f"customer.subscription.created/invoice.paid ratio = "
                        f"{ratio:.2f} (< 0.5). Customers are being charged "
                        f"but key-issue events are missing. Inspect Stripe "
                        f"webhook delivery + Sentry."
                    ),
                }
            )

    # Scale baseline median (per-day) to the active window.
    window_factor = report.window_hours / 24.0
    expected = report.baseline_sub_created_median * window_factor
    threshold = expected - report.sigma * (report.baseline_sub_created_stdev * window_factor)

    if report.baseline_days_present < _MIN_BASELINE_DAYS:
        if report.sub_created == 0 and report.invoice_paid >= _MIN_INVOICE_PAID_FOR_RATIO:
            report.findings.append(
                {
                    "kind": "subscription_created_zero_with_baseline_too_thin",
                    "level": "warning",
                    "sub_created": report.sub_created,
                    "invoice_paid": report.invoice_paid,
                    "baseline_days_present": report.baseline_days_present,
                    "message": (
                        "0 subscription.created events while invoice.paid "
                        "events flowed; baseline too thin for σ test "
                        f"({report.baseline_days_present} day(s)) — manual "
                        "verification recommended."
                    ),
                }
            )
        return

    if report.sub_created < threshold and expected > 0:
        report.findings.append(
            {
                "kind": "subscription_created_below_baseline",
                "level": "error",
                "sub_created": report.sub_created,
                "expected": round(expected, 2),
                "threshold": round(threshold, 2),
                "sigma": report.sigma,
                "baseline_median_per_day": round(report.baseline_sub_created_median, 2),
                "baseline_stdev_per_day": round(report.baseline_sub_created_stdev, 2),
                "baseline_days_present": report.baseline_days_present,
                "message": (
                    f"customer.subscription.created count "
                    f"({report.sub_created}) below {report.sigma}σ threshold "
                    f"({threshold:.1f}; baseline median {report.baseline_sub_created_median:.1f}/d). "
                    "Webhook delivery or handler may be silently failing."
                ),
            }
        )


def _detect_invoice_paid_dropoff(report: HealthReport) -> None:
    """Mirror σ test on invoice.paid — flags Stripe webhook outage upstream
    of our handler (i.e. Stripe stopped delivering, not we stopped
    processing).
    """
    if report.baseline_days_present < _MIN_BASELINE_DAYS:
        return
    window_factor = report.window_hours / 24.0
    expected = report.baseline_invoice_paid_median * window_factor
    threshold = expected - report.sigma * (report.baseline_invoice_paid_stdev * window_factor)
    if report.invoice_paid < threshold and expected > 0:
        report.findings.append(
            {
                "kind": "invoice_paid_below_baseline",
                "level": "warning",
                "invoice_paid": report.invoice_paid,
                "expected": round(expected, 2),
                "threshold": round(threshold, 2),
                "sigma": report.sigma,
                "baseline_median_per_day": round(report.baseline_invoice_paid_median, 2),
                "message": (
                    f"invoice.paid count ({report.invoice_paid}) below "
                    f"{report.sigma}σ threshold ({threshold:.1f}). Stripe "
                    "delivery may be impaired; check Stripe status page."
                ),
            }
        )


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------


def _run_once(
    *,
    window_hours: int,
    baseline_days: int,
    sigma: float,
    gap_seconds: int,
) -> HealthReport:
    """Build a HealthReport against the live DB. No side-effects."""
    now = datetime.now(UTC).replace(microsecond=0)
    window_start = now - timedelta(hours=window_hours)

    report = HealthReport(
        window_hours=window_hours,
        baseline_days=baseline_days,
        sigma=sigma,
        gap_seconds=gap_seconds,
    )

    with connect() as conn:
        if not _has_table(conn):
            # Pre-launch: no webhook events yet. Treat as "info" no-op.
            logger.info(
                "stripe_webhook_events table absent (pre-launch DB?) — no health checks to run."
            )
            return report

        # Window counts.
        window_counts = _count_events_by_type(conn, since_iso=window_start.isoformat())
        report.sub_created = window_counts.get("customer.subscription.created", 0)
        report.invoice_paid = window_counts.get("invoice.paid", 0)
        report.sub_updated = window_counts.get("customer.subscription.updated", 0)
        report.sub_deleted = window_counts.get("customer.subscription.deleted", 0)
        report.payment_failed = window_counts.get("invoice.payment_failed", 0)
        report.refunded = window_counts.get("charge.refunded", 0)
        known = {
            "customer.subscription.created",
            "invoice.paid",
            "customer.subscription.updated",
            "customer.subscription.deleted",
            "invoice.payment_failed",
            "charge.refunded",
        }
        report.other = sum(c for t, c in window_counts.items() if t not in known)

        # Baseline (per-day, looking back from window_start).
        sub_baseline = _per_day_counts(
            conn,
            event_type="customer.subscription.created",
            days=baseline_days,
            end_iso=window_start.isoformat(),
        )
        inv_baseline = _per_day_counts(
            conn,
            event_type="invoice.paid",
            days=baseline_days,
            end_iso=window_start.isoformat(),
        )
        # Days "present" = days with at least one event of EITHER type.
        # An empty DB across 7 days yields 0 baseline_days_present so the
        # σ branch correctly degrades to the warning path.
        report.baseline_days_present = sum(
            1 for s, i in zip(sub_baseline, inv_baseline, strict=False) if (s + i) > 0
        )

        if sub_baseline:
            report.baseline_sub_created_median = float(statistics.median(sub_baseline))
            if len(sub_baseline) >= 2:
                report.baseline_sub_created_stdev = float(statistics.pstdev(sub_baseline))
        if inv_baseline:
            report.baseline_invoice_paid_median = float(statistics.median(inv_baseline))
            if len(inv_baseline) >= 2:
                report.baseline_invoice_paid_stdev = float(statistics.pstdev(inv_baseline))

        # Stall detection.
        report.stalled_events = _stalled_events(
            conn,
            since_iso=window_start.isoformat(),
            gap_seconds=gap_seconds,
        )

    # Anomaly engine — pure compute over the report.
    _detect_subscription_dropoff(report)
    _detect_invoice_paid_dropoff(report)

    return report


def _summarize(report: HealthReport) -> dict[str, object]:
    """Flatten report for log + Sentry payload."""
    return {
        "kind": "webhook_health",
        "window_hours": report.window_hours,
        "baseline_days": report.baseline_days,
        "sigma": report.sigma,
        "gap_seconds": report.gap_seconds,
        "counts": {
            "customer.subscription.created": report.sub_created,
            "invoice.paid": report.invoice_paid,
            "customer.subscription.updated": report.sub_updated,
            "customer.subscription.deleted": report.sub_deleted,
            "invoice.payment_failed": report.payment_failed,
            "charge.refunded": report.refunded,
            "other": report.other,
        },
        "baseline": {
            "days_present": report.baseline_days_present,
            "sub_created_median_per_day": report.baseline_sub_created_median,
            "sub_created_stdev_per_day": report.baseline_sub_created_stdev,
            "invoice_paid_median_per_day": report.baseline_invoice_paid_median,
            "invoice_paid_stdev_per_day": report.baseline_invoice_paid_stdev,
        },
        "findings": report.findings,
        "stalled_events": report.stalled_events,
        "severity": report.severity(),
    }


def _zscore_sub_created(report: HealthReport) -> float:
    """Absolute z-score of window sub_created vs the per-day baseline.

    Two-tailed: a spike (promo abuse, bot wave) is as informative as a drop
    (handler outage). The Sentry alert rule `subscription_created_anomaly`
    fires on `max(extra.zscore_abs) > 2.0` over 1h, so we always emit the
    absolute value regardless of direction.

    Returns 0.0 when the baseline is too thin (< _MIN_BASELINE_DAYS) or
    when the per-day stdev is 0 (degenerate baseline — no variance, can't
    z-score). Both branches are cron-safe: a 0.0 emit will never trigger
    the alert, but it keeps the metric visible in Sentry's event stream
    for dashboards.
    """
    if report.baseline_days_present < _MIN_BASELINE_DAYS:
        return 0.0
    window_factor = report.window_hours / 24.0
    expected = report.baseline_sub_created_median * window_factor
    stdev = report.baseline_sub_created_stdev * window_factor
    if stdev <= 0:
        return 0.0
    return abs((report.sub_created - expected) / stdev)


def _emit_alerts(report: HealthReport, *, dry_run: bool) -> None:
    """Forward findings, stalls, and the σ-metric tag to Sentry.

    Two distinct Sentry messages on a non-info run:

      1. The roll-up message (existing) — one event per cron run carrying
         the finding count + stall count, severity = highest. This keeps
         a sustained outage from flooding Sentry's quota.
      2. The σ-metric tag (new) — a separate event tagged
         `metric:stripe.webhook.sub_created.zscore` with `extra.zscore_abs`,
         consumed by the `subscription_created_anomaly` alert rule. Always
         emitted (info-level when within band) so the alert rule has a
         signal to evaluate against — silent zero-emission would make the
         rule a no-op on the very first run that crossed the threshold.
    """
    summary = _summarize(report)
    logger.warning("webhook_health %s", json.dumps(summary, ensure_ascii=False))

    if dry_run:
        logger.info("[dry-run] not transmitting to Sentry")
        return

    # σ metric — always emit so the Sentry alert rule
    # `subscription_created_anomaly` (filter:
    # `metric:stripe.webhook.sub_created.zscore`, threshold |z| > 2.0)
    # has a continuous signal. Level scales with the magnitude so the alert
    # rule's `aggregate: max(extra.zscore_abs)` window can still aggregate
    # info-level events without paging.
    zscore_abs = _zscore_sub_created(report)
    z_level = "warning" if zscore_abs >= report.sigma else "info"
    safe_capture_message(
        f"stripe.webhook.sub_created.zscore window={report.window_hours}h "
        f"|z|={zscore_abs:.2f} sub_created={report.sub_created} "
        f"baseline_median_per_day={report.baseline_sub_created_median:.2f}",
        level=z_level,
        metric="stripe.webhook.sub_created.zscore",
        zscore_abs=round(zscore_abs, 4),
        sub_created=report.sub_created,
        baseline_median_per_day=round(report.baseline_sub_created_median, 4),
        baseline_stdev_per_day=round(report.baseline_sub_created_stdev, 4),
        baseline_days_present=report.baseline_days_present,
        window_hours=report.window_hours,
        sigma_threshold=report.sigma,
    )

    severity = report.severity()
    if severity == "info":
        return

    headline_parts: list[str] = []
    if report.findings:
        headline_parts.append(f"{len(report.findings)} finding(s)")
    if report.stalled_events:
        headline_parts.append(f"{len(report.stalled_events)} stall(s) > {report.gap_seconds}s")
    headline = " / ".join(headline_parts) or "anomaly"

    safe_capture_message(
        f"jpcite webhook health: {headline} "
        f"(window={report.window_hours}h, σ={report.sigma}). "
        f"sub.created={report.sub_created} invoice.paid={report.invoice_paid}.",
        level=severity,
        window_hours=report.window_hours,
        baseline_days=report.baseline_days,
        sub_created=report.sub_created,
        invoice_paid=report.invoice_paid,
        finding_count=len(report.findings),
        stall_count=len(report.stalled_events),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute report + log JSON, but do not transmit to Sentry.",
    )
    parser.add_argument(
        "--window-hours",
        type=int,
        default=_DEFAULT_WINDOW_HOURS,
        help="Active observation window in hours (default %(default)s).",
    )
    parser.add_argument(
        "--baseline-days",
        type=int,
        default=_DEFAULT_BASELINE_DAYS,
        help="Rolling baseline length in days (default %(default)s).",
    )
    parser.add_argument(
        "--sigma",
        type=float,
        default=_DEFAULT_SIGMA,
        help="σ multiplier for the anomaly band (default %(default)s).",
    )
    parser.add_argument(
        "--gap-seconds",
        type=int,
        default=_DEFAULT_GAP_SECONDS,
        help=("Maximum allowed gap between received_at and processed_at (default %(default)s)."),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full summary JSON to stdout (for piping into jq).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    with heartbeat("webhook_health") as hb:
        try:
            report = _run_once(
                window_hours=args.window_hours,
                baseline_days=args.baseline_days,
                sigma=args.sigma,
                gap_seconds=args.gap_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("webhook_health run failed")
            # Never raise — cron host should keep ticking. Emit a Sentry note
            # so a sustained run failure is at least visible.
            if not args.dry_run:
                safe_capture_message(
                    f"webhook_health cron failed: {exc!r}",
                    level="error",
                    kind="webhook_health_cron_failure",
                )
            hb["metadata"] = {"error": "run_once_failed", "exc": repr(exc)}
            return 2

        _emit_alerts(report, dry_run=args.dry_run)

        if args.json:
            print(json.dumps(_summarize(report), ensure_ascii=False, indent=2))

        sev = report.severity()
        hb["rows_processed"] = int(len(report.findings) or 0)
        hb["rows_skipped"] = int(len(report.stalled_events) or 0)
        hb["metadata"] = {
            "severity": sev,
            "window_hours": args.window_hours,
            "dry_run": bool(args.dry_run),
        }

        # Exit code semantics:
        #   0 = info / healthy
        #   1 = warning (cron continues, no page)
        #   2 = error or fatal (operator should investigate)
        if sev in ("error", "fatal"):
            return 2
        if sev == "warning":
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
