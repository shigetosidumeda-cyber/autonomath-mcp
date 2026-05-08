#!/usr/bin/env python3
"""ops_quick_stats — 1-shot operator KPI snapshot.

Read-only by design.  Connects to ``data/jpintel.db`` with ``mode=ro``
SQLite URI so accidental writes are physically impossible even if a
SELECT query is mis-typed into an UPDATE.

Usage::

    .venv/bin/python scripts/ops_quick_stats.py
    .venv/bin/python scripts/ops_quick_stats.py --json
    JPINTEL_DB_PATH=/path/to/jpintel.db .venv/bin/python scripts/ops_quick_stats.py

Designed for the daily 15-min 朝 / 夕 routine in
``docs/operator_daily.md`` §1 / §3.  Output is one screen tall:

    === jpcite ops quick stats (2026-05-06) ===
    MAU: 234 (anon 198 + paid 36)
    MRR (current month): ¥47,250
    MRR WoW Δ: +¥3,210 (+7.3%)
    ¥/customer avg: ¥1,313
    Cap usage: 12 customers cap-set, 3 cap-reached
    Trial signups (24h): 4 new / 30d conv: 18.2%
    Churn (7d): 2 paid keys revoked
    Past-due subscriptions: 1
    Unsynced metered events (>1h): 0
    Reconcile drift: 0.0021 (last run 2026-05-05)
    GEO citation rate: 28.3% (60 probes / latest 2026-04-29)
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
- ``--json`` emits the same KPI payload as ``GET /v1/admin/kpi`` —
  identical schema so the email digest, dashboard, and CLI all read
  one source.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta, timezone
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
    """Open the DB read-only.

    Two-step open:
      1) ``mode=ro`` — preferred; allows reading through a live WAL.
      2) ``mode=ro&immutable=1`` — fallback when SQLite cannot open the
         WAL/SHM sidecars (eg local dev DB checked into a read-only
         working tree, or an offline snapshot copy).  ``immutable=1``
         tells SQLite the file will not change while open, so it skips
         all WAL access entirely.
    """
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        sys.exit(1)
    last_exc: Exception | None = None
    for query in ("mode=ro", "mode=ro&immutable=1"):
        try:
            conn = sqlite3.connect(f"file:{db_path}?{query}", uri=True)
            conn.execute("SELECT 1").fetchone()  # surface errors at open
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.OperationalError as exc:
            last_exc = exc
            continue
    raise last_exc or sqlite3.OperationalError("unable to open database file")


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


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def utc_iso_offset(hours: int = 0, days: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours, days=days)).isoformat()


# ---------------------------------------------------------------------------
# MAU = anonymous distinct ip_hashes this JST month + paid customers
#       active (non-revoked) and used at least once this month.
# ---------------------------------------------------------------------------
def mau(conn: sqlite3.Connection) -> tuple[int, int]:
    month_start = jst_month_start()
    anon = 0
    if has_table(conn, "anon_rate_limit"):
        row = conn.execute(
            "SELECT COUNT(DISTINCT ip_hash) AS n FROM anon_rate_limit WHERE date >= ?",
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
# MRR for an ISO-ts window [start, end).  Counts metered=1 usage_events
# whose api_key is non-revoked.  ``end`` may be NULL for "open ended"
# (default = now).
# ---------------------------------------------------------------------------
def mrr_for_window(conn: sqlite3.Connection, start_iso: str, end_iso: str | None = None) -> int:
    if not has_table(conn, "usage_events"):
        return 0
    has_metered = has_column(conn, "usage_events", "metered")
    has_quantity = has_column(conn, "usage_events", "quantity")
    has_status = has_column(conn, "usage_events", "status")
    where_metered = "AND ue.metered = 1" if has_metered else ""
    where_success = "AND (ue.status IS NULL OR ue.status < 400)" if has_status else ""
    quantity_expr = "COALESCE(ue.quantity, 1)" if has_quantity else "1"
    upper = "AND ue.ts < ?" if end_iso else ""
    sql = (
        f"SELECT COALESCE(SUM({quantity_expr}), 0) AS units FROM usage_events ue "
        f"JOIN api_keys ak ON ak.key_hash = ue.key_hash "
        f"WHERE ue.ts >= ? {upper} {where_metered} {where_success} "
        f"AND ak.revoked_at IS NULL"
    )
    params: tuple = (start_iso, end_iso) if end_iso else (start_iso,)
    row = conn.execute(sql, params).fetchone()
    return int(row["units"] or 0) * YEN_PER_REQUEST


def mrr(conn: sqlite3.Connection) -> int:
    """MRR (current JST month-to-date)."""
    return mrr_for_window(conn, jst_month_start_iso())


def mrr_wow_delta(conn: sqlite3.Connection) -> tuple[int, int, float]:
    """Week-over-week MRR delta.

    Returns ``(this_week, last_week, pct_delta)``.  Both weeks are
    rolling 7-day UTC windows ending now / 7d-ago.  We use UTC
    (not JST) here because billing windows run UTC and the operator
    is comparing against Stripe's invoices.
    """
    end_now = datetime.now(UTC)
    this_start = end_now - timedelta(days=7)
    last_start = end_now - timedelta(days=14)
    last_end = end_now - timedelta(days=7)
    this_week = mrr_for_window(conn, this_start.isoformat())
    last_week = mrr_for_window(conn, last_start.isoformat(), last_end.isoformat())
    pct = ((this_week - last_week) / last_week * 100.0) if last_week else 0.0
    return this_week, last_week, pct


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
        quantity_expr = (
            "COALESCE(ue.quantity, 1)" if has_column(conn, "usage_events", "quantity") else "1"
        )
        status_filter = (
            "AND (ue.status IS NULL OR ue.status < 400)"
            if has_column(conn, "usage_events", "status")
            else ""
        )
        metered_filter = "AND ue.metered = 1" if has_column(conn, "usage_events", "metered") else ""
        rows = conn.execute(
            f"""
            SELECT ak.key_hash, ak.monthly_cap_yen,
                   COALESCE(SUM({quantity_expr}), 0) AS units
              FROM api_keys ak
              LEFT JOIN usage_events ue
                     ON ue.key_hash = ak.key_hash
                    AND ue.ts >= ?
                    {status_filter}
                    {metered_filter}
             WHERE ak.revoked_at IS NULL
               AND ak.monthly_cap_yen IS NOT NULL
             GROUP BY ak.key_hash
            """,
            (month_iso,),
        ).fetchall()
        for r in rows:
            spend = int(r["units"] or 0) * YEN_PER_REQUEST
            if spend >= int(r["monthly_cap_yen"] or 0):
                cap_reached += 1
    return cap_set, cap_reached


# ---------------------------------------------------------------------------
# Churn = paid keys revoked in the trailing 7d.  Trial revocations
# do not count (those are evaluator timeouts, not paid churn).
# ---------------------------------------------------------------------------
def churn_7d(conn: sqlite3.Connection) -> int:
    if not has_table(conn, "api_keys"):
        return 0
    if not has_column(conn, "api_keys", "revoked_at"):
        return 0
    since = utc_iso_offset(days=7)
    sql = (
        "SELECT COUNT(*) AS n FROM api_keys "
        "WHERE revoked_at IS NOT NULL "
        "AND revoked_at >= ? "
        "AND tier = 'paid'"
    )
    row = conn.execute(sql, (since,)).fetchone()
    return int(row["n"] or 0)


# ---------------------------------------------------------------------------
# Past-due = api_keys whose Stripe subscription_status is 'past_due'.
# ---------------------------------------------------------------------------
def past_due_count(conn: sqlite3.Connection) -> int:
    if not has_column(conn, "api_keys", "stripe_subscription_status"):
        return 0
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM api_keys "
        "WHERE revoked_at IS NULL "
        "AND stripe_subscription_status = 'past_due'"
    ).fetchone()
    return int(row["n"] or 0)


# ---------------------------------------------------------------------------
# Unsynced metered events older than 1h — anything > 1h old that
# hasn't been pushed to Stripe is a billing leak signal.
# ---------------------------------------------------------------------------
def unsynced_metered_events(conn: sqlite3.Connection) -> int:
    if not has_table(conn, "usage_events"):
        return 0
    if not has_column(conn, "usage_events", "stripe_synced_at"):
        return 0
    if not has_column(conn, "usage_events", "metered"):
        return 0
    cutoff = utc_iso_offset(hours=1)
    sql = (
        "SELECT COUNT(*) AS n FROM usage_events "
        "WHERE metered = 1 "
        "AND stripe_synced_at IS NULL "
        "AND ts < ?"
    )
    row = conn.execute(sql, (cutoff,)).fetchone()
    return int(row["n"] or 0)


def unsynced_metered_units(conn: sqlite3.Connection) -> int:
    if not has_table(conn, "usage_events"):
        return 0
    if not has_column(conn, "usage_events", "stripe_synced_at"):
        return 0
    if not has_column(conn, "usage_events", "metered"):
        return 0
    quantity_expr = "COALESCE(quantity, 1)" if has_column(conn, "usage_events", "quantity") else "1"
    cutoff = utc_iso_offset(hours=1)
    sql = (
        f"SELECT COALESCE(SUM({quantity_expr}), 0) AS units FROM usage_events "
        "WHERE metered = 1 "
        "AND stripe_synced_at IS NULL "
        "AND ts < ?"
    )
    row = conn.execute(sql, (cutoff,)).fetchone()
    return int(row["units"] or 0)


# ---------------------------------------------------------------------------
# Demand-shape metrics — these answer whether the "100k units/day" target is
# forming as repeatable agent/BPO workflow demand rather than manual search.
# ---------------------------------------------------------------------------
def billable_units_since(conn: sqlite3.Connection, since_iso: str) -> int:
    if not has_table(conn, "usage_events"):
        return 0
    has_metered = has_column(conn, "usage_events", "metered")
    has_quantity = has_column(conn, "usage_events", "quantity")
    has_status = has_column(conn, "usage_events", "status")
    where_metered = "AND metered = 1" if has_metered else ""
    where_success = "AND (status IS NULL OR status < 400)" if has_status else ""
    quantity_expr = "COALESCE(quantity, 1)" if has_quantity else "1"
    row = conn.execute(
        f"SELECT COALESCE(SUM({quantity_expr}), 0) AS units "
        "FROM usage_events "
        f"WHERE ts >= ? {where_metered} {where_success}",
        (since_iso,),
    ).fetchone()
    return int(row["units"] or 0)


def billable_keys_since(conn: sqlite3.Connection, since_iso: str) -> int:
    if not has_table(conn, "usage_events"):
        return 0
    has_metered = has_column(conn, "usage_events", "metered")
    has_status = has_column(conn, "usage_events", "status")
    where_metered = "AND metered = 1" if has_metered else ""
    where_success = "AND (status IS NULL OR status < 400)" if has_status else ""
    row = conn.execute(
        "SELECT COUNT(DISTINCT key_hash) AS n FROM usage_events "
        f"WHERE ts >= ? {where_metered} {where_success}",
        (since_iso,),
    ).fetchone()
    return int(row["n"] or 0)


def client_tag_demand_30d(conn: sqlite3.Connection) -> tuple[int, int, int, float]:
    """Return ``(tagged_units, total_units, active_tag_pairs, pct)``.

    `X-Client-Tag` is the clearest signal that jpcite is being embedded
    into customer/project/company-folder workflows.  A low rate means
    usage is still mostly single-shot exploration, even if traffic grows.
    """
    if not has_column(conn, "usage_events", "client_tag"):
        return 0, 0, 0, 0.0
    since = utc_iso_offset(days=30)
    has_metered = has_column(conn, "usage_events", "metered")
    has_quantity = has_column(conn, "usage_events", "quantity")
    has_status = has_column(conn, "usage_events", "status")
    where_metered = "AND metered = 1" if has_metered else ""
    where_success = "AND (status IS NULL OR status < 400)" if has_status else ""
    quantity_expr = "COALESCE(quantity, 1)" if has_quantity else "1"
    row = conn.execute(
        f"""
        SELECT
          COALESCE(SUM({quantity_expr}), 0) AS total_units,
          COALESCE(SUM(CASE
              WHEN client_tag IS NOT NULL AND client_tag != '' THEN {quantity_expr}
              ELSE 0 END), 0) AS tagged_units,
          COUNT(DISTINCT CASE
              WHEN client_tag IS NOT NULL AND client_tag != ''
              THEN key_hash || ':' || client_tag END) AS tag_pairs
        FROM usage_events
        WHERE ts >= ? {where_metered} {where_success}
        """,
        (since,),
    ).fetchone()
    total_units = int(row["total_units"] or 0)
    tagged_units = int(row["tagged_units"] or 0)
    tag_pairs = int(row["tag_pairs"] or 0)
    pct = (tagged_units / total_units * 100.0) if total_units else 0.0
    return tagged_units, total_units, tag_pairs, pct


def top_key_share_30d_pct(conn: sqlite3.Connection) -> float:
    """Return the largest key's share of 30d billable units.

    100k/day is healthier when it comes from many integrations and
    customer-tagged workflows.  A high share is not bad by itself, but it
    means the revenue projection depends on one integration staying active.
    """
    if not has_table(conn, "usage_events"):
        return 0.0
    since = utc_iso_offset(days=30)
    has_metered = has_column(conn, "usage_events", "metered")
    has_quantity = has_column(conn, "usage_events", "quantity")
    has_status = has_column(conn, "usage_events", "status")
    where_metered = "AND metered = 1" if has_metered else ""
    where_success = "AND (status IS NULL OR status < 400)" if has_status else ""
    quantity_expr = "COALESCE(quantity, 1)" if has_quantity else "1"
    rows = conn.execute(
        f"""
        SELECT key_hash, COALESCE(SUM({quantity_expr}), 0) AS units
          FROM usage_events
         WHERE ts >= ? {where_metered} {where_success}
         GROUP BY key_hash
        """,
        (since,),
    ).fetchall()
    units = [int(r["units"] or 0) for r in rows]
    total = sum(units)
    return (max(units) / total * 100.0) if total else 0.0


def cost_preview_requests_7d(conn: sqlite3.Connection) -> int:
    if not has_table(conn, "analytics_events"):
        return 0
    since = utc_iso_offset(days=7)
    status_filter = "AND status < 400" if has_column(conn, "analytics_events", "status") else ""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM analytics_events "
        "WHERE ts >= ? AND path = '/v1/cost/preview' "
        f"{status_filter}",
        (since,),
    ).fetchone()
    return int(row["n"] or 0)


def cost_preview_to_billable_7d_pct(conn: sqlite3.Connection) -> float:
    """Key-level conversion from preview use to any billable use in 7d."""
    if not has_table(conn, "analytics_events") or not has_table(conn, "usage_events"):
        return 0.0
    if not has_column(conn, "analytics_events", "key_hash"):
        return 0.0
    since = utc_iso_offset(days=7)
    preview_rows = conn.execute(
        """
        SELECT DISTINCT key_hash
          FROM analytics_events
         WHERE ts >= ?
           AND path = '/v1/cost/preview'
           AND key_hash IS NOT NULL
           AND (status IS NULL OR status < 400)
        """,
        (since,),
    ).fetchall()
    preview_keys = {str(r["key_hash"]) for r in preview_rows if r["key_hash"]}
    if not preview_keys:
        return 0.0

    placeholders = ",".join("?" for _ in preview_keys)
    has_metered = has_column(conn, "usage_events", "metered")
    has_status = has_column(conn, "usage_events", "status")
    where_metered = "AND metered = 1" if has_metered else ""
    where_success = "AND (status IS NULL OR status < 400)" if has_status else ""
    rows = conn.execute(
        f"""
        SELECT DISTINCT key_hash
          FROM usage_events
         WHERE ts >= ?
           AND key_hash IN ({placeholders})
           {where_metered}
           {where_success}
        """,
        (since, *tuple(preview_keys)),
    ).fetchall()
    converted = {str(r["key_hash"]) for r in rows if r["key_hash"]}
    return (len(converted) / len(preview_keys) * 100.0) if preview_keys else 0.0


# ---------------------------------------------------------------------------
# Trial signups & conversion — reads ``trial_signups`` + paid api_keys
# linked via ``trial_email``.  Both tables are migration-076 territory;
# guard accordingly.
# ---------------------------------------------------------------------------
def trial_signups_24h(conn: sqlite3.Connection) -> int:
    if not has_table(conn, "trial_signups"):
        return 0
    since = utc_iso_offset(hours=24)
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM trial_signups WHERE created_at >= ?",
        (since,),
    ).fetchone()
    return int(row["n"] or 0)


def trial_to_paid_30d_pct(conn: sqlite3.Connection) -> float:
    """Trial-to-paid conversion in the last 30 days.

    Definition: of trials whose ``verified_at`` falls in [now-30d, now],
    how many converted into a non-trial, non-revoked paid key whose
    ``trial_email`` matches the trial's email.  This measures the
    cohort whose 14-day window closed within the last 30 days.

    Returns 0.0 if either side is missing or no cohort exists.
    """
    if not has_table(conn, "trial_signups"):
        return 0.0
    if not has_column(conn, "api_keys", "trial_email"):
        return 0.0
    since = utc_iso_offset(days=30)
    cohort_row = conn.execute(
        "SELECT COUNT(*) AS n FROM trial_signups "
        "WHERE verified_at IS NOT NULL AND verified_at >= ?",
        (since,),
    ).fetchone()
    cohort_n = int(cohort_row["n"] or 0)
    if cohort_n == 0:
        return 0.0
    converted_row = conn.execute(
        """
        SELECT COUNT(DISTINCT ts.email_normalized) AS n
        FROM trial_signups ts
        JOIN api_keys ak
          ON LOWER(ak.trial_email) = LOWER(ts.email)
        WHERE ts.verified_at IS NOT NULL
          AND ts.verified_at >= ?
          AND ak.tier = 'paid'
          AND ak.revoked_at IS NULL
        """,
        (since,),
    ).fetchone()
    converted_n = int(converted_row["n"] or 0)
    return (converted_n / cohort_n * 100.0) if cohort_n else 0.0


# ---------------------------------------------------------------------------
# Reconcile drift — read the latest analysis_wave18/stripe_reconcile_*.json
# emitted by scripts/cron/stripe_reconcile.py.  This is local-cache, not
# a Stripe API call.
# ---------------------------------------------------------------------------
def reconcile_drift() -> tuple[float | None, str | None]:
    repo = Path(__file__).resolve().parent.parent
    candidates = sorted(
        (repo / "analysis_wave18").glob("stripe_reconcile_*.json"),
        reverse=True,
    )
    if not candidates:
        return None, None
    try:
        data = json.loads(candidates[0].read_text())
    except (OSError, ValueError):
        return None, None
    diff_pct = data.get("diff_pct")
    if diff_pct is None:
        return None, candidates[0].name
    try:
        return float(diff_pct), candidates[0].name
    except (TypeError, ValueError):
        return None, candidates[0].name


# ---------------------------------------------------------------------------
# GEO citation rate — read latest analytics/geo_baseline_*.jsonl,
# count cited=true / total per engine.
# ---------------------------------------------------------------------------
def geo_citation_rate() -> tuple[float | None, int, str | None]:
    repo = Path(__file__).resolve().parent.parent
    candidates = sorted(
        (repo / "analytics").glob("geo_baseline_*.jsonl"),
        reverse=True,
    )
    if not candidates:
        return None, 0, None
    latest = candidates[0]
    try:
        text = latest.read_text(encoding="utf-8")
    except OSError:
        return None, 0, latest.name
    total = 0
    cited = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        total += 1
        if row.get("cited") is True:
            cited += 1
    pct = (cited / total * 100.0) if total else 0.0
    return pct, total, latest.name


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
    sign = "-" if n < 0 else ""
    return f"{sign}¥{abs(n):,}"


def fmt_yen_signed(n: int) -> str:
    if n > 0:
        return f"+¥{n:,}"
    if n < 0:
        return f"-¥{abs(n):,}"
    return "¥0"


# ---------------------------------------------------------------------------
# Severity classification — used by the dashboard + email digest to
# highlight metrics that need attention.  Returned as a parallel dict
# alongside the KPI payload so a downstream renderer can color-code
# without re-deriving the rules.
# ---------------------------------------------------------------------------
def classify(payload: dict) -> dict[str, str]:
    """Return ``{kpi_name: 'ok'|'warn'|'critical'}``.

    Rules are deliberately conservative so the daily digest does NOT
    cry wolf:

    - past_due >= 1                 -> warn
    - past_due >= 3                 -> critical
    - unsynced_metered >= 1         -> warn
    - unsynced_metered >= 100       -> critical
    - reconcile_drift > 1%          -> warn
    - reconcile_drift > 5%          -> critical
    - churn_7d >= 1                 -> warn (always investigate)
    - mrr_wow_pct < -10%            -> warn
    - mrr_wow_pct < -25%            -> critical
    """
    out: dict[str, str] = {}

    pd = payload.get("past_due_count", 0)
    if pd >= 3:
        out["past_due_count"] = "critical"
    elif pd >= 1:
        out["past_due_count"] = "warn"
    else:
        out["past_due_count"] = "ok"

    us = payload.get("unsynced_metered_units", payload.get("unsynced_metered_events", 0))
    if us >= 100:
        out["unsynced_metered_events"] = "critical"
    elif us >= 1:
        out["unsynced_metered_events"] = "warn"
    else:
        out["unsynced_metered_events"] = "ok"

    drift = payload.get("reconcile_drift_pct")
    if drift is None:
        out["reconcile_drift_pct"] = "ok"
    elif drift > 0.05:
        out["reconcile_drift_pct"] = "critical"
    elif drift > 0.01:
        out["reconcile_drift_pct"] = "warn"
    else:
        out["reconcile_drift_pct"] = "ok"

    churn = payload.get("churn_7d", 0)
    out["churn_7d"] = "warn" if churn >= 1 else "ok"

    wow = payload.get("mrr_wow_pct")
    if wow is None:
        out["mrr_wow_pct"] = "ok"
    elif wow < -25:
        out["mrr_wow_pct"] = "critical"
    elif wow < -10:
        out["mrr_wow_pct"] = "warn"
    else:
        out["mrr_wow_pct"] = "ok"

    # A single integration can legitimately dominate early, but above
    # 80% the 100k/day path is fragile enough to show as warn.
    top_share = payload.get("top_key_30d_billable_units_share_pct", 0.0)
    out["top_key_30d_billable_units_share_pct"] = "warn" if top_share >= 80 else "ok"

    return out


def collect_payload(conn: sqlite3.Connection) -> dict:
    anon, paid = mau(conn)
    revenue = mrr(conn)
    per_customer = (revenue // paid) if paid else 0
    cap_set, cap_reached = cap_usage(conn)
    this_week, last_week, wow_pct = mrr_wow_delta(conn)
    drift_pct, drift_file = reconcile_drift()
    geo_pct, geo_total, geo_file = geo_citation_rate()
    units_24h = billable_units_since(conn, utc_iso_offset(hours=24))
    keys_24h = billable_keys_since(conn, utc_iso_offset(hours=24))
    tagged_units_30d, billable_units_30d, tag_pairs_30d, tag_pct_30d = client_tag_demand_30d(conn)

    payload: dict = {
        "generated_at": utc_now_iso(),
        "date_jst": jst_today(),
        # Audience
        "mau_total": anon + paid,
        "mau_anon": anon,
        "mau_paid": paid,
        # Revenue
        "mrr_yen": revenue,
        "mrr_per_customer_yen": per_customer,
        "mrr_wow_this_week_yen": this_week,
        "mrr_wow_last_week_yen": last_week,
        "mrr_wow_delta_yen": this_week - last_week,
        "mrr_wow_pct": round(wow_pct, 2),
        "billable_units_24h": units_24h,
        "billable_keys_24h": keys_24h,
        "daily_100k_goal_progress_pct": round((units_24h / 100_000) * 100.0, 2),
        "billable_units_30d": billable_units_30d,
        "client_tagged_units_30d": tagged_units_30d,
        "client_tag_usage_rate_30d_pct": round(tag_pct_30d, 2),
        "active_client_tag_pairs_30d": tag_pairs_30d,
        "top_key_30d_billable_units_share_pct": round(top_key_share_30d_pct(conn), 2),
        "cost_preview_requests_7d": cost_preview_requests_7d(conn),
        "cost_preview_to_billable_7d_pct": round(cost_preview_to_billable_7d_pct(conn), 2),
        # Caps
        "cap_set": cap_set,
        "cap_reached": cap_reached,
        # Health signals
        "churn_7d": churn_7d(conn),
        "past_due_count": past_due_count(conn),
        "unsynced_metered_events": unsynced_metered_events(conn),
        "unsynced_metered_units": unsynced_metered_units(conn),
        "reconcile_drift_pct": drift_pct,
        "reconcile_source_file": drift_file,
        # Trial funnel
        "trial_signups_24h": trial_signups_24h(conn),
        "trial_to_paid_30d_pct": round(trial_to_paid_30d_pct(conn), 2),
        # GEO
        "geo_citation_rate_pct": round(geo_pct, 2) if geo_pct is not None else None,
        "geo_probes_total": geo_total,
        "geo_source_file": geo_file,
        # Cached external surfaces
        "sentry_row": sentry_row(conn),
        "stripe_row": stripe_row(conn),
    }
    payload["severity"] = classify(payload)
    return payload


def render_text(payload: dict) -> str:
    lines: list[str] = []
    lines.append(f"=== jpcite ops quick stats ({payload['date_jst']}) ===")
    lines.append(
        f"MAU: {payload['mau_total']} (anon {payload['mau_anon']} + paid {payload['mau_paid']})"
    )
    lines.append(f"MRR (current month): {fmt_yen(payload['mrr_yen'])}")
    delta = payload["mrr_wow_delta_yen"]
    lines.append(f"MRR WoW Δ: {fmt_yen_signed(delta)} ({payload['mrr_wow_pct']:+.1f}%)")
    lines.append(f"¥/customer avg: {fmt_yen(payload['mrr_per_customer_yen'])}")
    lines.append(
        "100k/day progress: "
        f"{payload['billable_units_24h']:,} units / "
        f"{payload['billable_keys_24h']} keys "
        f"({payload['daily_100k_goal_progress_pct']:.2f}%)"
    )
    lines.append(
        "Workflow signal (30d): "
        f"{payload['client_tagged_units_30d']:,}/{payload['billable_units_30d']:,} "
        f"units tagged ({payload['client_tag_usage_rate_30d_pct']:.1f}%), "
        f"{payload['active_client_tag_pairs_30d']} active tags, "
        f"top key {payload['top_key_30d_billable_units_share_pct']:.1f}%"
    )
    lines.append(
        "Cost preview (7d): "
        f"{payload['cost_preview_requests_7d']} calls / "
        f"{payload['cost_preview_to_billable_7d_pct']:.1f}% key-level billable conversion"
    )
    lines.append(
        f"Cap usage: {payload['cap_set']} customers cap-set, {payload['cap_reached']} cap-reached"
    )
    lines.append(
        f"Trial signups (24h): {payload['trial_signups_24h']} new / "
        f"30d conv: {payload['trial_to_paid_30d_pct']:.1f}%"
    )
    lines.append(f"Churn (7d): {payload['churn_7d']} paid keys revoked")
    lines.append(f"Past-due subscriptions: {payload['past_due_count']}")
    lines.append(f"Unsynced metered events (>1h): {payload['unsynced_metered_events']}")
    if payload["reconcile_drift_pct"] is not None:
        lines.append(
            f"Reconcile drift: {payload['reconcile_drift_pct']:.4f} "
            f"(source: {payload['reconcile_source_file']})"
        )
    else:
        lines.append("Reconcile drift: (no report yet)")
    if payload["geo_citation_rate_pct"] is not None:
        lines.append(
            f"GEO citation rate: {payload['geo_citation_rate_pct']:.1f}% "
            f"({payload['geo_probes_total']} probes / "
            f"{payload['geo_source_file']})"
        )
    else:
        lines.append("GEO citation rate: (no baseline yet)")
    lines.append(f"Sentry: {payload['sentry_row']}")
    lines.append(f"Stripe: {payload['stripe_row']}")
    crit = [k for k, v in payload["severity"].items() if v == "critical"]
    warn = [k for k, v in payload["severity"].items() if v == "warn"]
    if crit:
        lines.append(f"!! CRITICAL: {', '.join(crit)}")
    elif warn:
        lines.append(f"!  WARN: {', '.join(warn)}")
    lines.append("=== End ===")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON (matches /v1/admin/kpi schema).",
    )
    args = parser.parse_args(argv)

    db_path = resolve_db_path()
    conn = connect_ro(db_path)
    try:
        payload = collect_payload(conn)
    finally:
        conn.close()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
