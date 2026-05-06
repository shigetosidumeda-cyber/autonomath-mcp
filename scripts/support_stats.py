#!/usr/bin/env python3
"""Weekly support stats — read-only.

Prints a terminal report the operator reviews during the Monday ritual
(see docs/_internal/operators_playbook.md Appendix A).

Usage:
    python scripts/support_stats.py
    JPINTEL_DB_PATH=/path/to/jpintel.db python scripts/support_stats.py

Never writes to the DB. Uses the live schema columns only (verified
against the production DB at data/jpintel.db on 2026-04-23):

    api_keys(key_hash, customer_id, tier, stripe_subscription_id,
             created_at, revoked_at, last_used_at)
    usage_events(id, key_hash, endpoint, ts, status, metered)
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

# tier default daily rate limits (see src/jpintel_mcp/config.py +
# docs/pricing.md). Used to flag outliers at >3x normal.
TIER_DAILY_LIMIT = {
    "free": 100,
    "plus": 1_000,
    "pro": 10_000,
    # business is metered, no fixed ceiling — treat as 100_000/day for
    # outlier detection only (report only, never enforcement).
    "business": 100_000,
}

OUTLIER_MULTIPLIER = 3.0


def resolve_db_path() -> Path:
    env = os.environ.get("JPINTEL_DB_PATH")
    if env:
        return Path(env)
    # relative to repo root if cwd happens to be anywhere inside the repo
    here = Path(__file__).resolve().parent.parent
    return here / "data" / "jpintel.db"


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        sys.exit(1)
    # URI with mode=ro — prevents accidental writes even on bugs.
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def active_keys_by_tier(conn: sqlite3.Connection) -> None:
    section("Active API keys by tier")
    rows = conn.execute(
        """
        SELECT tier,
               COUNT(*) AS n,
               SUM(CASE WHEN last_used_at IS NOT NULL THEN 1 ELSE 0 END) AS n_used
          FROM api_keys
         WHERE revoked_at IS NULL
         GROUP BY tier
         ORDER BY CASE tier
                    WHEN 'business' THEN 0
                    WHEN 'pro' THEN 1
                    WHEN 'plus' THEN 2
                    WHEN 'free' THEN 3
                    ELSE 9 END
        """
    ).fetchall()
    if not rows:
        print("  (no active keys)")
        return
    print(f"  {'tier':<10} {'active':>8} {'ever-used':>10}")
    print(f"  {'-' * 10} {'-' * 8:>8} {'-' * 10:>10}")
    total = 0
    for r in rows:
        total += r["n"]
        print(f"  {r['tier']:<10} {r['n']:>8} {r['n_used']:>10}")
    print(f"  {'TOTAL':<10} {total:>8}")


def revoked_this_week(conn: sqlite3.Connection, now: datetime) -> None:
    section("Keys revoked in the last 7 days")
    since = (now - timedelta(days=7)).isoformat()
    rows = conn.execute(
        """
        SELECT tier, COUNT(*) AS n
          FROM api_keys
         WHERE revoked_at IS NOT NULL AND revoked_at >= ?
         GROUP BY tier
         ORDER BY n DESC
        """,
        (since,),
    ).fetchall()
    total_row = conn.execute(
        "SELECT COUNT(*) AS n FROM api_keys WHERE revoked_at IS NOT NULL AND revoked_at >= ?",
        (since,),
    ).fetchone()
    total = total_row["n"] if total_row else 0
    print(f"  Window: {since}  ...  {now.isoformat()}")
    print(f"  Total revoked: {total}")
    if rows:
        print(f"  {'tier':<10} {'revoked':>8}")
        print(f"  {'-' * 10} {'-' * 8:>8}")
        for r in rows:
            print(f"  {r['tier']:<10} {r['n']:>8}")
    detail = conn.execute(
        """
        SELECT substr(key_hash, 1, 12) AS key_prefix,
               customer_id, tier, created_at, revoked_at, last_used_at
          FROM api_keys
         WHERE revoked_at IS NOT NULL AND revoked_at >= ?
         ORDER BY revoked_at DESC
         LIMIT 20
        """,
        (since,),
    ).fetchall()
    if detail:
        print()
        print("  Recent revokes (most recent 20):")
        print(
            f"  {'key_prefix':<14} {'customer_id':<20} {'tier':<8} "
            f"{'created_at':<26} {'revoked_at':<26}"
        )
        for r in detail:
            cid = (r["customer_id"] or "-")[:20]
            print(
                f"  {r['key_prefix']:<14} {cid:<20} {r['tier']:<8} "
                f"{(r['created_at'] or '-'):<26} {(r['revoked_at'] or '-'):<26}"
            )


def top_customers_by_usage(conn: sqlite3.Connection, now: datetime) -> None:
    section("Top 10 customers by usage (last 7 days)")
    since = (now - timedelta(days=7)).isoformat()
    rows = conn.execute(
        """
        SELECT ak.customer_id,
               ak.tier,
               ak.last_used_at,
               COUNT(ue.id) AS call_count
          FROM api_keys ak
          LEFT JOIN usage_events ue
                 ON ue.key_hash = ak.key_hash
                AND ue.ts >= ?
         WHERE ak.customer_id IS NOT NULL
           AND ak.revoked_at IS NULL
         GROUP BY ak.customer_id
         ORDER BY call_count DESC, ak.last_used_at DESC
         LIMIT 10
        """,
        (since,),
    ).fetchall()
    if not rows:
        print("  (no paid customer activity in window)")
        return
    print(f"  Window: calls since {since}")
    print(f"  {'rank':<5} {'customer_id':<22} {'tier':<8} {'last_used_at':<26} {'call_count':>10}")
    print(f"  {'-' * 5:<5} {'-' * 22:<22} {'-' * 8:<8} {'-' * 26:<26} {'-' * 10:>10}")
    for i, r in enumerate(rows, 1):
        cid = (r["customer_id"] or "-")[:22]
        lua = (r["last_used_at"] or "-")[:26]
        print(f"  {i:<5} {cid:<22} {r['tier']:<8} {lua:<26} {r['call_count']:>10}")


def outliers(conn: sqlite3.Connection, now: datetime) -> None:
    section(f"Outliers (daily call-count > {OUTLIER_MULTIPLIER:g}x tier limit, last 7 days)")
    # aggregate calls per (key_hash, date-in-utc)
    since = (now - timedelta(days=7)).isoformat()
    rows = conn.execute(
        """
        SELECT ak.key_hash,
               substr(ak.key_hash, 1, 12) AS key_prefix,
               ak.customer_id,
               ak.tier,
               substr(ue.ts, 1, 10) AS day,
               COUNT(ue.id) AS n_calls
          FROM usage_events ue
          JOIN api_keys ak ON ak.key_hash = ue.key_hash
         WHERE ue.ts >= ?
           AND ak.revoked_at IS NULL
         GROUP BY ak.key_hash, day
         ORDER BY n_calls DESC
        """,
        (since,),
    ).fetchall()
    flagged = []
    peak_per_key: dict[str, int] = defaultdict(int)
    meta_per_key: dict[str, dict] = {}
    for r in rows:
        limit = TIER_DAILY_LIMIT.get(r["tier"], 100)
        if r["n_calls"] > limit * OUTLIER_MULTIPLIER:
            flagged.append(r)
        if r["n_calls"] > peak_per_key[r["key_hash"]]:
            peak_per_key[r["key_hash"]] = r["n_calls"]
            meta_per_key[r["key_hash"]] = {
                "key_prefix": r["key_prefix"],
                "customer_id": r["customer_id"],
                "tier": r["tier"],
                "day": r["day"],
            }
    if not flagged:
        print("  (no outliers)")
    else:
        print(
            f"  {'key_prefix':<14} {'customer_id':<22} {'tier':<8} "
            f"{'day':<12} {'n_calls':>10} {'limit':>8} {'x':>6}"
        )
        print(
            f"  {'-' * 14:<14} {'-' * 22:<22} {'-' * 8:<8} {'-' * 12:<12} "
            f"{'-' * 10:>10} {'-' * 8:>8} {'-' * 6:>6}"
        )
        for r in flagged:
            limit = TIER_DAILY_LIMIT.get(r["tier"], 100)
            ratio = r["n_calls"] / limit if limit else 0
            cid = (r["customer_id"] or "-")[:22]
            print(
                f"  {r['key_prefix']:<14} {cid:<22} {r['tier']:<8} "
                f"{r['day']:<12} {r['n_calls']:>10} {limit:>8} {ratio:>5.1f}x"
            )
    # Also show peaks even if under threshold — helpful for tuning.
    print()
    print("  Peak day per active key (top 5):")
    peaks_sorted = sorted(peak_per_key.items(), key=lambda kv: kv[1], reverse=True)[:5]
    if not peaks_sorted:
        print("    (no usage)")
    else:
        for key_hash, peak in peaks_sorted:
            meta = meta_per_key[key_hash]
            limit = TIER_DAILY_LIMIT.get(meta["tier"], 100)
            ratio = peak / limit if limit else 0
            cid = (meta["customer_id"] or "-")[:22]
            print(
                f"    {meta['key_prefix']:<14} {cid:<22} {meta['tier']:<8} "
                f"peak={peak:>6} on {meta['day']} ({ratio:>4.2f}x limit)"
            )


def subscriber_count(conn: sqlite3.Connection) -> None:
    section("Subscriber list (newsletter)")
    row = conn.execute(
        "SELECT COUNT(*) AS n_total, "
        "SUM(CASE WHEN unsubscribed_at IS NULL THEN 1 ELSE 0 END) AS n_active "
        "FROM subscribers"
    ).fetchone()
    total = row["n_total"] if row else 0
    active = row["n_active"] if row else 0
    print(f"  total rows: {total}")
    print(f"  active    : {active}")


def main() -> int:
    db_path = resolve_db_path()
    now = datetime.now(UTC)
    print("jpintel-mcp support stats")
    print(f"  db  : {db_path}")
    print(f"  now : {now.isoformat()}")

    conn = connect(db_path)
    try:
        active_keys_by_tier(conn)
        revoked_this_week(conn, now)
        top_customers_by_usage(conn, now)
        outliers(conn, now)
        subscriber_count(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
