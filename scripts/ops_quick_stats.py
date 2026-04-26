#!/usr/bin/env python3
"""ops_quick_stats — 1-shot operator KPI snapshot.

Read-only by design.  Connects to ``data/jpintel.db`` with ``mode=ro``
SQLite URI so accidental writes are physically impossible even if a
SELECT query is mis-typed into an UPDATE.

Usage::

    .venv/bin/python scripts/ops_quick_stats.py
    JPINTEL_DB_PATH=/path/to/jpintel.db .venv/bin/python scripts/ops_quick_stats.py

Designed for the daily 15-min 朝 / 夕 routine in
``docs/operator_daily.md`` §1 / §3.  Output is one screen tall:

    === AutonoMath ops quick stats (2026-05-06) ===
    MAU: 234 (anon 198 + paid 36)
    MRR (current month): ¥47,250
    ¥/customer avg: ¥1,313
    Cap usage: 12 customers cap-set, 3 cap-reached
    Sentry: 0 unresolved critical / 2 resolved
    Stripe: 1 dispute in pending (¥3,510)
    === End ===

Notes:

- We **never** call the Stripe / Sentry HTTP API from this script
  (memory ``feedback_autonomath_no_api_use``).  Sentry / Stripe rows
  are sourced from optional cache tables only.  When the cache is
  absent the row prints ``(unconfigured -- see <surface> dashboard)``
  rather than failing.
- Pricing math uses the constant ``YEN_PER_REQUEST`` because the
  config-side value lives in ``src/jpintel_mcp/config.py`` which we
  must not import from a stand-alone script (decoupled CLI).
- All dates are computed in **JST** because that is the operator's
  natural timezone and matches the anonymous quota reset boundary.
  See ``CLAUDE.md`` "Common gotchas" for the JST/UTC asymmetry.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# AutonoMath unit price -- 税抜 ¥3 / req.  See pyproject.toml +
# docs/pricing.md.  Hard-coded here to keep this CLI standalone (we do
# not import jpintel_mcp.config in operator scripts).
YEN_PER_REQUEST = 3
# JST timezone offset.
JST = timezone(timedelta(hours=9))


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


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not has_table(conn, table):
        return False
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def jst_today() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def jst_month_start() -> str:
    """First day of the current JST month, ``YYYY-MM-DD``."""
    now = datetime.now(JST)
    return now.replace(day=1).strftime("%Y-%m-%d")


def jst_month_start_iso() -> str:
    """First day of the current JST month as an ISO timestamp."""
    now = datetime.now(JST)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat()


# ---------------------------------------------------------------------------
# MAU = anonymous distinct ip_hashes this JST month + paid customers
#       active (non-revoked) and used at least once this month.
# ---------------------------------------------------------------------------
def mau(conn: sqlite3.Connection) -> tuple[int, int]:
    month_start = jst_month_start()
    anon = 0
    if has_table(conn, "anon_rate_limit"):
        row = conn.execute(
            "SELECT COUNT(DISTINCT ip_hash) AS n "
            "FROM anon_rate_limit WHERE date >= ?",
            (month_start,),
        ).fetchone()
        anon = int(row["n"] or 0)
    paid = 0
    if has_table(conn, "api_keys"):
        # paid = active key with last_used_at within current JST month
        # Use ISO comparison; last_used_at is UTC ISO but month-grain
        # matches well enough for an at-a-glance MAU.
        month_iso = jst_month_start_iso()
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM api_keys "
            "WHERE revoked_at IS NULL AND last_used_at IS NOT NULL "
            "AND last_used_at >= ?",
            (month_iso,),
        ).fetchone()
        paid = int(row["n"] or 0)
    return anon, paid


# ---------------------------------------------------------------------------
# MRR = sum(metered usage_events this JST month) * YEN_PER_REQUEST
#       restricted to events whose key_hash points at a non-revoked,
#       paid-tier api_keys row.  Cancelled subscriptions still owe for
#       the partial month, but we only show the *recognised* portion
#       here -- precise reconciliation is Stripe's job.
# ---------------------------------------------------------------------------
def mrr(conn: sqlite3.Connection) -> int:
    if not has_table(conn, "usage_events"):
        return 0
    month_iso = jst_month_start_iso()
    # metered=1 means the event was recognised by the billing pipeline.
    # Some installs may not have populated `metered` yet; guard with the
    # column existence check and fall back to all events.
    if has_column(conn, "usage_events", "metered"):
        sql = (
            "SELECT COUNT(*) AS n FROM usage_events ue "
            "JOIN api_keys ak ON ak.key_hash = ue.key_hash "
            "WHERE ue.ts >= ? AND ue.metered = 1 "
            "AND ak.revoked_at IS NULL"
        )
    else:
        sql = (
            "SELECT COUNT(*) AS n FROM usage_events ue "
            "JOIN api_keys ak ON ak.key_hash = ue.key_hash "
            "WHERE ue.ts >= ? AND ak.revoked_at IS NULL"
        )
    row = conn.execute(sql, (month_iso,)).fetchone()
    n = int(row["n"] or 0)
    return n * YEN_PER_REQUEST


# ---------------------------------------------------------------------------
# Cap usage = how many active keys have a monthly_cap_yen set, and how
# many have already exceeded that cap this JST month.
# ---------------------------------------------------------------------------
def cap_usage(conn: sqlite3.Connection) -> tuple[int, int]:
    if not has_column(conn, "api_keys", "monthly_cap_yen"):
        return 0, 0
    cap_set = int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM api_keys "
            "WHERE revoked_at IS NULL AND monthly_cap_yen IS NOT NULL"
        ).fetchone()["n"]
        or 0
    )
    cap_reached = 0
    if has_table(conn, "usage_events"):
        month_iso = jst_month_start_iso()
        rows = conn.execute(
            """
            SELECT ak.key_hash, ak.monthly_cap_yen,
                   COUNT(ue.id) AS n_calls
              FROM api_keys ak
              LEFT JOIN usage_events ue
                     ON ue.key_hash = ak.key_hash
                    AND ue.ts >= ?
             WHERE ak.revoked_at IS NULL
               AND ak.monthly_cap_yen IS NOT NULL
             GROUP BY ak.key_hash
            """,
            (month_iso,),
        ).fetchall()
        for r in rows:
            spend = int(r["n_calls"] or 0) * YEN_PER_REQUEST
            if spend >= int(r["monthly_cap_yen"] or 0):
                cap_reached += 1
    return cap_set, cap_reached


# ---------------------------------------------------------------------------
# Sentry / Stripe rows.  We do NOT call external APIs.  We optionally
# read a local cache table populated by an out-of-band cron (not part
# of this CLI).  When absent, print the "unconfigured" sentinel.
# ---------------------------------------------------------------------------
def sentry_row(conn: sqlite3.Connection) -> str:
    if has_table(conn, "ops_sentry_cache"):
        row = conn.execute(
            "SELECT unresolved_critical, resolved_24h "
            "FROM ops_sentry_cache ORDER BY cached_at DESC LIMIT 1"
        ).fetchone()
        if row is not None:
            return (
                f"{int(row['unresolved_critical'])} unresolved critical / "
                f"{int(row['resolved_24h'])} resolved"
            )
    return "(unconfigured -- see Sentry dashboard)"


def stripe_row(conn: sqlite3.Connection) -> str:
    if has_table(conn, "ops_stripe_cache"):
        row = conn.execute(
            "SELECT disputes_pending, dispute_amount_yen "
            "FROM ops_stripe_cache ORDER BY cached_at DESC LIMIT 1"
        ).fetchone()
        if row is not None:
            n = int(row["disputes_pending"] or 0)
            amt = int(row["dispute_amount_yen"] or 0)
            return f"{n} dispute in pending (¥{amt:,})"
    return "(unconfigured -- see Stripe dashboard)"


def fmt_yen(n: int) -> str:
    return f"¥{n:,}"


def main() -> int:
    db_path = resolve_db_path()
    conn = connect_ro(db_path)
    try:
        anon, paid = mau(conn)
        revenue = mrr(conn)
        per_customer = (revenue // paid) if paid else 0
        cap_set, cap_reached = cap_usage(conn)
        sentry = sentry_row(conn)
        stripe = stripe_row(conn)
    finally:
        conn.close()

    today = jst_today()
    print(f"=== AutonoMath ops quick stats ({today}) ===")
    print(f"MAU: {anon + paid} (anon {anon} + paid {paid})")
    print(f"MRR (current month): {fmt_yen(revenue)}")
    print(f"¥/customer avg: {fmt_yen(per_customer)}")
    print(
        f"Cap usage: {cap_set} customers cap-set, {cap_reached} cap-reached"
    )
    print(f"Sentry: {sentry}")
    print(f"Stripe: {stripe}")
    print("=== End ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
