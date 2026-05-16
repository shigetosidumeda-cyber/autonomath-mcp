"""Process Dim U Agent Credit Wallet spending alerts hourly (Wave 47).

Operates on top of the storage layer added by
``scripts/migrations/281_credit_wallet.sql``. For each enabled wallet
with a positive ``monthly_budget_yen``, computes ``spent_yen`` for the
current ``YYYY-MM`` billing cycle (sum of negative ``charge`` txns,
absolute value), evaluates the 50% / 80% / 100% thresholds, and emits
exactly one ``am_credit_spending_alert`` row per (wallet, threshold,
cycle) when crossed for the first time.

The ``UNIQUE (wallet_id, threshold_pct, billing_cycle)`` constraint on
the alert table makes this naturally idempotent: re-running this ETL
within the same cycle is a no-op unless additional spend has crossed a
new threshold.

LLM-0 by construction
---------------------
No LLM API is ever invoked (per ``feedback_no_operator_llm_api``).
Pure SQL aggregation + INSERT OR IGNORE.

Usage
-----
    python scripts/etl/process_credit_wallet_alerts.py            # apply
    python scripts/etl/process_credit_wallet_alerts.py --dry-run  # plan only
    python scripts/etl/process_credit_wallet_alerts.py --db PATH  # custom db
    python scripts/etl/process_credit_wallet_alerts.py --cycle YYYY-MM

JSON output (final stdout line)
-------------------------------
    {
      "dim": "U",
      "wave": 47,
      "dry_run": <bool>,
      "billing_cycle": "YYYY-MM",
      "wallets_scanned": <int>,
      "alerts_fired": [
        {"wallet_id": <int>, "threshold_pct": 50|80|100,
         "spent_yen": <int>, "budget_yen": <int>}
      ]
    }
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"
LOG = logging.getLogger("process_credit_wallet_alerts")

# Threshold order matters: we evaluate from lowest to highest so the
# operator can rely on monotonic alert emission within a single run.
_THRESHOLDS_PCT: tuple[int, ...] = (50, 80, 100)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Process Dim U credit-wallet spending alerts (hourly)")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--cycle",
        default=None,
        help="Override billing cycle bucket (YYYY-MM). Default = current UTC month.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _current_cycle() -> str:
    return _dt.datetime.utcnow().strftime("%Y-%m")


def _spent_in_cycle(conn: sqlite3.Connection, wallet_id: int, cycle: str) -> int:
    """Sum |charge_amount| for the wallet in the current cycle.

    Charge rows have negative ``amount_yen`` (per CHECK constraint), so
    we take the negation of the sum.
    """
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_yen), 0) FROM am_credit_transaction_log "
        "WHERE wallet_id = ? "
        "  AND txn_type = 'charge' "
        "  AND substr(occurred_at, 1, 7) = ?",
        (wallet_id, cycle),
    ).fetchone()
    return -int(row[0])


def _fire_alert(
    conn: sqlite3.Connection,
    *,
    wallet_id: int,
    threshold_pct: int,
    cycle: str,
    spent: int,
    budget: int,
    dry_run: bool,
) -> bool:
    """Insert an alert row, ignoring duplicates. Return True if newly fired."""
    if dry_run:
        # In dry-run, simulate uniqueness check.
        row = conn.execute(
            "SELECT 1 FROM am_credit_spending_alert "
            "WHERE wallet_id = ? AND threshold_pct = ? AND billing_cycle = ?",
            (wallet_id, threshold_pct, cycle),
        ).fetchone()
        return row is None

    cur = conn.execute(
        "INSERT OR IGNORE INTO am_credit_spending_alert "
        "(wallet_id, threshold_pct, billing_cycle, spent_yen, budget_yen) "
        "VALUES (?, ?, ?, ?, ?)",
        (wallet_id, threshold_pct, cycle, spent, budget),
    )
    return cur.rowcount == 1


def main(argv: list[str] | None = None) -> int:
    ns = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if ns.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cycle = ns.cycle or _current_cycle()
    db_path = Path(ns.db)
    if not db_path.exists():
        LOG.warning("db path %s does not exist; nothing to process", db_path)
        report = {
            "dim": "U",
            "wave": 47,
            "dry_run": ns.dry_run,
            "billing_cycle": cycle,
            "wallets_scanned": 0,
            "alerts_fired": [],
        }
        print(json.dumps(report, ensure_ascii=False))
        return 0

    fired: list[dict[str, int]] = []
    wallets_scanned = 0
    conn = _connect(db_path)
    try:
        wallet_rows = conn.execute(
            "SELECT wallet_id, monthly_budget_yen FROM am_credit_wallet "
            "WHERE enabled = 1 AND monthly_budget_yen > 0"
        ).fetchall()
        for wallet_id, budget in wallet_rows:
            wallets_scanned += 1
            spent = _spent_in_cycle(conn, wallet_id, cycle)
            if spent <= 0:
                continue
            pct = (spent * 100) // max(budget, 1)
            for threshold in _THRESHOLDS_PCT:
                if pct >= threshold:
                    newly = _fire_alert(
                        conn,
                        wallet_id=wallet_id,
                        threshold_pct=threshold,
                        cycle=cycle,
                        spent=spent,
                        budget=budget,
                        dry_run=ns.dry_run,
                    )
                    if newly:
                        fired.append(
                            {
                                "wallet_id": int(wallet_id),
                                "threshold_pct": int(threshold),
                                "spent_yen": int(spent),
                                "budget_yen": int(budget),
                            }
                        )
        if not ns.dry_run:
            conn.commit()
    finally:
        conn.close()

    report = {
        "dim": "U",
        "wave": 47,
        "dry_run": ns.dry_run,
        "billing_cycle": cycle,
        "wallets_scanned": wallets_scanned,
        "alerts_fired": fired,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
