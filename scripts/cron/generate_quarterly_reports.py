#!/usr/bin/env python3
"""Quarterly report cron — generate per-customer PDF on Q1/Q2/Q3/Q4 boundaries.

Cron schedule (one workflow, branches on month):
    * Q1 → April 1   (covers Jan–Mar of the prior calendar year? — no:
                       see _quarter_for_today below — we follow 日本会計年度,
                       so Q1 begins on the cron run-day's quarter-start.)
    * Q2 → July 1
    * Q3 → October 1
    * Q4 → January 1

Each run loops over every paid api_keys row with at least one
client_profile and pre-renders the quarterly PDF into
data/quarterly_pdfs/<api_key_id>_<year>_q<n>.pdf so the customer's
subsequent GET /v1/me/recurring/quarterly/{year}/{quarter} download is
a cache hit (no extra ¥3 charge — billing happened at render time).

Cost posture:
    * ¥3 per generated PDF (matches the on-demand path).
    * Empty PDF (no usage stats, no watch list, no eligible programs)
      is still rendered — the customer paid for the cadence, the
      quarterly review is the deliverable.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402

logger = logging.getLogger("autonomath.cron.quarterly")


def _quarter_for_today(now: datetime) -> tuple[int, int] | None:
    """Return (year, quarter) iff today is the first day of a fiscal quarter.

    日本会計年度 boundaries:
        * Q1 begins April 1
        * Q2 begins July 1
        * Q3 begins October 1
        * Q4 begins January 1 (= prev year's Q4)

    Returns None on any other day so a manually-triggered cron does not
    accidentally batch-render off-cycle.
    """
    if now.month == 4 and now.day == 1:
        return now.year, 1
    if now.month == 7 and now.day == 1:
        return now.year, 2
    if now.month == 10 and now.day == 1:
        return now.year, 3
    if now.month == 1 and now.day == 1:
        # Q4 of the previous fiscal year (covers Jan-Mar of THIS calendar year)
        return now.year - 1, 4
    return None


def _eligible_keys(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """SELECT DISTINCT cp.api_key_hash
             FROM client_profiles cp
             JOIN api_keys ak ON ak.key_hash = cp.api_key_hash
            WHERE ak.tier = 'paid'"""
    ).fetchall()
    return [r["api_key_hash"] for r in rows]


def run(*, year: int | None = None, quarter: int | None = None,
        dry_run: bool = False) -> dict[str, Any]:
    """Render quarterly PDFs for every eligible customer.

    When `year`+`quarter` are not supplied, the cron auto-detects the
    quarter from today's date. Off-cycle invocations (any day other
    than 1st of Jan/Apr/Jul/Oct) require explicit year/quarter.
    """
    now = datetime.now(UTC)
    if year is None or quarter is None:
        detected = _quarter_for_today(now)
        if detected is None:
            logger.warning(
                "quarterly.off_cycle today=%s — supply --year + --quarter to force",
                now.date(),
            )
            return {"rendered": 0, "billed": 0, "off_cycle": True}
        year, quarter = detected

    conn = connect()
    rendered = 0
    billed = 0
    skipped = 0
    try:
        from jpintel_mcp.api.recurring_quarterly import (
            _QUARTERLY_CACHE_DIR,
            _api_key_id_token,
            _gather_eligible_unapplied,
            _gather_usage_stats,
            _gather_watch_amendments,
            _quarter_period,
            _record_metered_pdf,
            _redacted_key_id,
            _render_pdf_to,
        )

        keys = _eligible_keys(conn)
        period_start, period_end = _quarter_period(year, quarter)
        for key_hash in keys:
            token = _api_key_id_token(key_hash)
            cache_path = _QUARTERLY_CACHE_DIR / f"{token}_{year}_q{quarter}.pdf"
            if cache_path.exists():
                skipped += 1
                continue

            usage_stats = _gather_usage_stats(conn, key_hash, period_start, period_end)
            watch_amendments = _gather_watch_amendments(
                conn, key_hash, period_start, period_end
            )
            eligible_unapplied = _gather_eligible_unapplied(conn, key_hash)
            amendment_summary = {
                "ウォッチ対象改正": len(watch_amendments),
                "新規申請可能制度": len(eligible_unapplied),
                "対象期間 (日)": (
                    datetime.fromisoformat(period_end)
                    - datetime.fromisoformat(period_start)
                ).days + 1,
            }
            context = {
                "year": year,
                "quarter": quarter,
                "period_start": period_start,
                "period_end": period_end,
                "rendered_at": now.isoformat(timespec="minutes").replace("+00:00", "Z"),
                "api_key_id_redacted": _redacted_key_id(key_hash),
                "usage_stats": usage_stats,
                "watch_amendments": watch_amendments,
                "eligible_unapplied": eligible_unapplied,
                "amendment_summary": amendment_summary,
            }
            if dry_run:
                logger.info(
                    "quarterly.dry_run key_token=%s year=%s quarter=%s",
                    token, year, quarter,
                )
                rendered += 1
                continue
            ok = _render_pdf_to(out_path=cache_path, context=context)
            if not ok:
                continue
            rendered += 1
            if _record_metered_pdf(conn, key_hash):
                billed += 1
        summary = {
            "ran_at": now.isoformat(),
            "year": year,
            "quarter": quarter,
            "rendered": rendered,
            "billed": billed,
            "skipped_cached": skipped,
            "dry_run": dry_run,
        }
        logger.info(
            "quarterly.summary %s",
            json.dumps(summary, ensure_ascii=False),
        )
        return summary
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quarterly PDF batch cron")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--quarter", type=int, choices=[1, 2, 3, 4], default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    with heartbeat("generate_quarterly_reports") as hb:
        summary = run(year=args.year, quarter=args.quarter, dry_run=args.dry_run)
        if isinstance(summary, dict):
            hb["rows_processed"] = int(
                summary.get("pdfs_generated", summary.get("reports", 0)) or 0
            )
            hb["rows_skipped"] = int(summary.get("skipped", 0) or 0)
            hb["metadata"] = {
                k: summary.get(k)
                for k in ("year", "quarter", "delivered", "errors", "dry_run")
                if k in summary
            }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
