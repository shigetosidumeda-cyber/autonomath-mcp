#!/usr/bin/env python3
"""ops_refund_helper -- advisory tool for Stripe refund decisions.

Given a Stripe ``charge_id`` (or ``customer_id`` in the future), the
helper reads **only local data** (``data/jpintel.db``) and prints:

- the customer record (id / tier / first-seen / last-seen / call count)
- past dispute / refund history we have logged locally
- a *suggested* action: ``full`` / ``partial`` / ``deny``
- the Stripe Dashboard URL the operator should open to act manually

This script never calls the Stripe API.  Refunds are executed by the
operator from the Stripe Dashboard after eyeballing the recommendation
(memory ``feedback_zero_touch_solo`` -- no auto-refund auto-action).

Usage::

    .venv/bin/python scripts/ops_refund_helper.py ch_3PXXXXXX
    .venv/bin/python scripts/ops_refund_helper.py ch_3PXXXXXX --customer cus_YYYY

Decision flow mirrors ``docs/_internal/operators_playbook.md`` §3.1:

    [1] decided <=7d ago AND call_count < 100  -> full
    [2] mid-cycle, used moderately             -> partial (prorated)
    [3] abuse pattern (low tier, high volume)  -> deny
    [4] otherwise                              -> hold (24h)
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
YEN_PER_REQUEST = 3
# Refund-window thresholds aligned with operators_playbook §3.1.
FULL_REFUND_DAYS = 7
FULL_REFUND_MAX_CALLS = 100
ABUSE_LOW_TIER = {"free", "starter", "anon"}
ABUSE_DAILY_CALL_THRESHOLD = 5_000  # >5k/day on a low tier => abuse pattern


def resolve_db_path() -> Path:
    env = os.environ.get("JPINTEL_DB_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data" / "jpintel.db"


def connect_ro(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        sys.exit(1)
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def find_customer_id(conn: sqlite3.Connection, charge_id: str, override: str | None) -> str | None:
    """Best-effort mapping ``charge_id -> customer_id``.

    We never call Stripe.  The mapping comes from one of:

    1. CLI ``--customer`` override
    2. local cache table ``stripe_charges`` (charge_id -> customer_id)
       populated by webhook ingestion
    3. ``--`` cannot be resolved (helper still runs in degraded mode)
    """
    if override:
        return override
    if has_table(conn, "stripe_charges"):
        row = conn.execute(
            "SELECT customer_id FROM stripe_charges WHERE charge_id = ?",
            (charge_id,),
        ).fetchone()
        if row is not None:
            return row["customer_id"]
    return None


def fetch_customer(conn: sqlite3.Connection, customer_id: str) -> dict | None:
    if not has_table(conn, "api_keys"):
        return None
    row = conn.execute(
        """
        SELECT customer_id, tier, created_at, last_used_at, revoked_at,
               monthly_cap_yen
          FROM api_keys
         WHERE customer_id = ?
         ORDER BY created_at DESC
         LIMIT 1
        """,
        (customer_id,),
    ).fetchone()
    return dict(row) if row else None


def fetch_call_count(conn: sqlite3.Connection, customer_id: str) -> tuple[int, int, int]:
    """Return ``(total, last_7d, max_per_day)`` call counts."""
    if not has_table(conn, "usage_events") or not has_table(conn, "api_keys"):
        return 0, 0, 0
    rows = conn.execute(
        """
        SELECT substr(ue.ts, 1, 10) AS day, COUNT(ue.id) AS n
          FROM usage_events ue
          JOIN api_keys ak ON ak.key_hash = ue.key_hash
         WHERE ak.customer_id = ?
         GROUP BY day
        """,
        (customer_id,),
    ).fetchall()
    total = sum(int(r["n"]) for r in rows)
    cutoff = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    last_7d = sum(int(r["n"]) for r in rows if r["day"] >= cutoff)
    max_per_day = max((int(r["n"]) for r in rows), default=0)
    return total, last_7d, max_per_day


def fetch_past_disputes(conn: sqlite3.Connection, customer_id: str) -> list[dict]:
    if not has_table(conn, "ops_dispute_log"):
        return []
    rows = conn.execute(
        "SELECT charge_id, status, amount_yen, opened_at, closed_at "
        "FROM ops_dispute_log WHERE customer_id = ? "
        "ORDER BY opened_at DESC",
        (customer_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_charge_amount(conn: sqlite3.Connection, charge_id: str) -> int | None:
    if not has_table(conn, "stripe_charges"):
        return None
    row = conn.execute(
        "SELECT amount_yen FROM stripe_charges WHERE charge_id = ?",
        (charge_id,),
    ).fetchone()
    return int(row["amount_yen"]) if row else None


def days_since(iso_ts: str | None) -> float | None:
    if not iso_ts:
        return None
    try:
        # Try with timezone, fall back to naive UTC.
        try:
            dt = datetime.fromisoformat(iso_ts)
        except ValueError:
            dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return (datetime.now(UTC) - dt).total_seconds() / 86400
    except Exception:
        return None


def suggest(
    customer: dict | None,
    total_calls: int,
    last_7d: int,
    max_per_day: int,
    past_disputes: list[dict],
) -> tuple[str, list[str]]:
    """Return (action, reasoning_lines)."""
    notes: list[str] = []
    if customer is None:
        notes.append("customer record not found locally -- HOLD 24h")
        return "hold", notes

    tier = (customer.get("tier") or "").lower()
    age_days = days_since(customer.get("created_at"))
    notes.append(
        f"customer tier={tier or 'unknown'}, created {age_days:.1f}d ago"
        if age_days is not None
        else "created at=?"
    )
    notes.append(f"call counts: total={total_calls}, last_7d={last_7d}, max_per_day={max_per_day}")
    if past_disputes:
        notes.append(f"past disputes recorded locally: {len(past_disputes)}")
    else:
        notes.append("no prior disputes on file")

    # 1) abuse: low tier with sustained high volume -> deny
    if tier in ABUSE_LOW_TIER and max_per_day > ABUSE_DAILY_CALL_THRESHOLD:
        notes.append(
            f"abuse pattern: low tier with peak day {max_per_day} > {ABUSE_DAILY_CALL_THRESHOLD}"
        )
        return "deny", notes

    # 2) repeat disputer -> deny (operator can override)
    if len(past_disputes) >= 2:
        notes.append("repeat disputer: 2+ prior dispute logs -- DENY suggested")
        return "deny", notes

    # 3) recent + low usage -> full
    if (
        age_days is not None
        and age_days <= FULL_REFUND_DAYS
        and total_calls < FULL_REFUND_MAX_CALLS
    ):
        notes.append(
            f"<= {FULL_REFUND_DAYS}d since first key, "
            f"< {FULL_REFUND_MAX_CALLS} total calls -- FULL refund OK"
        )
        return "full", notes

    # 4) mid-cycle moderate use -> partial (prorated)
    notes.append("mid-cycle moderate use -- PARTIAL (prorated) refund recommended")
    return "partial", notes


def stripe_dashboard_url(charge_id: str) -> str:
    # Stripe Dashboard search URL.  The operator confirms charge details
    # and clicks "Refund" manually -- we never automate this.
    return f"https://dashboard.stripe.com/payments/{charge_id}"


def fmt_yen(n: int) -> str:
    return f"¥{n:,}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Advisory: suggest a refund action for a Stripe charge."
    )
    parser.add_argument(
        "charge_id",
        help="Stripe charge_id (e.g. ch_3PXXXX). Looked up against the local "
        "stripe_charges cache when present.",
    )
    parser.add_argument(
        "--customer",
        default=None,
        help="Override: explicit Stripe customer_id when the local cache "
        "cannot resolve it from the charge_id.",
    )
    args = parser.parse_args(argv)

    db_path = resolve_db_path()
    conn = connect_ro(db_path)
    try:
        customer_id = find_customer_id(conn, args.charge_id, args.customer)
        amount = fetch_charge_amount(conn, args.charge_id)
        customer = fetch_customer(conn, customer_id) if customer_id else None
        total, last_7d, max_per_day = (
            fetch_call_count(conn, customer_id) if customer_id else (0, 0, 0)
        )
        past_disputes = fetch_past_disputes(conn, customer_id) if customer_id else []
        action, notes = suggest(customer, total, last_7d, max_per_day, past_disputes)
    finally:
        conn.close()

    today = datetime.now(JST).strftime("%Y-%m-%d")
    print(f"=== ops_refund_helper ({today}) ===")
    print(f"charge_id : {args.charge_id}")
    print(f"customer  : {customer_id or '(unresolved -- pass --customer)'}")
    print(f"amount    : {fmt_yen(amount) if amount is not None else '(unknown)'}")
    if customer:
        print(
            f"key meta  : tier={customer.get('tier')} "
            f"cap_yen={customer.get('monthly_cap_yen')} "
            f"revoked_at={customer.get('revoked_at') or '-'}"
        )
    else:
        print("key meta  : (no local key for this customer)")
    print(f"call cnt  : total={total}, last7d={last_7d}, max/day={max_per_day}")
    if past_disputes:
        for d in past_disputes:
            print(
                f"  past dispute: {d['charge_id']} status={d['status']} "
                f"amount={fmt_yen(int(d['amount_yen'] or 0))} "
                f"opened={d['opened_at']} closed={d['closed_at'] or '-'}"
            )
    print()
    print(f"SUGGESTED ACTION: {action.upper()}")
    for line in notes:
        print(f"  - {line}")
    print()
    print("Operator next steps (manual):")
    print(f"  1. Open Stripe Dashboard: {stripe_dashboard_url(args.charge_id)}")
    if action == "full":
        print("  2. Refund -> 'Full refund' -> reason='requested by customer'.")
        print("  3. Revoke API key per operators_playbook §5.")
        print("  4. Append decision to research/refund_decisions.log.")
    elif action == "partial":
        print(
            "  2. Refund -> 'Partial' -> compute prorated amount per "
            "operators_playbook §3.1 step [2]."
        )
        print("  3. Keep API key live until current cycle end.")
        print("  4. Append decision to research/refund_decisions.log.")
    elif action == "deny":
        print("  2. DO NOT refund.  Reply with refund_denied.md template citing ToS §6.3.")
        print("  3. Consider abuse handling per operators_playbook §5.")
        print("  4. Append decision to research/refund_decisions.log.")
    else:  # hold
        print("  2. HOLD 24h.  Reply with 'will respond within 3 business days'.")
        print("  3. Re-run helper after gathering more info.")
    print("=== End ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
