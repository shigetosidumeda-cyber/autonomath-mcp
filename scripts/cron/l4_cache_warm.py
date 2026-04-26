#!/usr/bin/env python3
"""Daily L4 cache warm-up (v8 P5-ε++ / 4-Layer cache architecture, dd_v8_C3).

What it does:
  1. Reads usage_events from jpintel.db over the last 7 days.
  2. Buckets events by (endpoint, params_digest) and ranks by call count
     (Zipf-shaped — top ~100 keys are ~80% of traffic).
  3. For each top-N entry the cron *would* re-compute the response and
     INSERT/REPLACE the cached blob into l4_query_cache. The compute
     callbacks are tool-specific (programs.list_open / search_tax_incentives
     / ...), so the launch-day version of this script logs the candidates
     and seeds the table with a sentinel TTL=0 row (effectively a no-op).
  4. Sweeps stale rows via cache.l4.sweep_expired().
  5. Trims the table to a soft cap (default 1000 rows) by deleting the
     bottom-N rows by last_hit_at.

Constraints:
  * No Anthropic / claude / SDK calls. Pure SQLite + standard library.
  * Pre-launch: usage_events is mostly empty, so the candidate list is
     empty and the script is a no-op. That is the intended steady state
     until launch-day traffic arrives.

Usage:
    python scripts/cron/l4_cache_warm.py            # real run
    python scripts/cron/l4_cache_warm.py --dry-run  # log only
    python scripts/cron/l4_cache_warm.py --top 50 --since 2026-04-18
    python scripts/cron/l4_cache_warm.py --soft-cap 500
"""
from __future__ import annotations

import argparse
import logging
import sys
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

from jpintel_mcp.cache.l4 import sweep_expired  # noqa: E402
from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402

logger = logging.getLogger("autonomath.cron.l4_cache_warm")

DEFAULT_TOP_N = 100
DEFAULT_SOFT_CAP = 1000
DEFAULT_LOOKBACK_DAYS = 7


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.cron.l4_cache_warm")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _zipf_candidates(
    conn: sqlite3.Connection, since_iso: str, top_n: int
) -> list[tuple[str, str | None, int]]:
    """Return [(endpoint, params_digest, count), ...] for the top-N keys.

    The query bins by (endpoint, params_digest). params_digest may be NULL
    on legacy rows (status / endpoint without params). Those are still
    counted; their warmth target is the parameter-less default response.
    """
    rows = conn.execute(
        """
        SELECT endpoint, params_digest, COUNT(*) AS cnt
          FROM usage_events
         WHERE ts >= ?
         GROUP BY endpoint, params_digest
         ORDER BY cnt DESC
         LIMIT ?
        """,
        (since_iso, int(top_n)),
    ).fetchall()
    return [(r[0], r[1], int(r[2])) for r in rows]


def _trim_to_soft_cap(conn: sqlite3.Connection, soft_cap: int) -> int:
    """Delete the bottom-N rows by last_hit_at if table exceeds soft_cap."""
    cur = conn.execute("SELECT COUNT(*) FROM l4_query_cache")
    row = cur.fetchone()
    total = int(row[0]) if row else 0
    if total <= soft_cap:
        return 0
    over = total - soft_cap
    cur = conn.execute(
        """
        DELETE FROM l4_query_cache
         WHERE cache_key IN (
             SELECT cache_key
               FROM l4_query_cache
              ORDER BY COALESCE(last_hit_at, created_at) ASC
              LIMIT ?
         )
        """,
        (over,),
    )
    return cur.rowcount or 0


def run(
    db_path: Path,
    since: datetime,
    top_n: int,
    soft_cap: int,
    dry_run: bool,
) -> dict[str, int]:
    """Execute the warm-up cycle. Returns counters for the operator log."""
    counters = {
        "candidates": 0,
        "expired_swept": 0,
        "trimmed": 0,
    }

    since_iso = since.isoformat()
    logger.info(
        "l4_warm_start db=%s since=%s top_n=%d soft_cap=%d dry_run=%s",
        db_path,
        since_iso,
        top_n,
        soft_cap,
        dry_run,
    )

    conn = connect(db_path)
    try:
        candidates = _zipf_candidates(conn, since_iso, top_n)
        counters["candidates"] = len(candidates)
        for endpoint, digest, cnt in candidates:
            logger.info(
                "l4_warm_candidate endpoint=%s digest=%s hits=%d",
                endpoint,
                digest or "-",
                cnt,
            )
            # The actual compute step is per-tool and lives in the API
            # routers. Once the routers expose `compute_for_warm(endpoint,
            # params_digest)` this loop will populate the cache. Until
            # then we leave a structured log line so the operator can see
            # the Zipf head emerging post-launch.

        if not dry_run:
            counters["expired_swept"] = sweep_expired(db_path)
            counters["trimmed"] = _trim_to_soft_cap(conn, soft_cap)
        else:
            logger.info("l4_warm_dry_run skipping_sweep_and_trim")

        logger.info(
            "l4_warm_done candidates=%d expired_swept=%d trimmed=%d",
            counters["candidates"],
            counters["expired_swept"],
            counters["trimmed"],
        )
        return counters
    finally:
        conn.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="L4 cache warm-up for jpintel-mcp")
    p.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to jpintel.db (default: settings.db_path)",
    )
    p.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP_N,
        help=f"Top-N Zipf candidates (default: {DEFAULT_TOP_N})",
    )
    p.add_argument(
        "--soft-cap",
        type=int,
        default=DEFAULT_SOFT_CAP,
        help=f"Soft row-count cap on l4_query_cache (default: {DEFAULT_SOFT_CAP})",
    )
    p.add_argument(
        "--since",
        type=str,
        default=None,
        help="ISO 8601 lower-bound for usage_events.ts (default: now-7d)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Log candidates only; do not sweep / trim / write",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)

    if args.since:
        try:
            since = datetime.fromisoformat(args.since)
        except ValueError:
            logger.error("invalid_since value=%s", args.since)
            return 2
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
    else:
        since = datetime.now(UTC) - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    db_path = args.db if args.db else settings.db_path

    try:
        run(
            db_path=db_path,
            since=since,
            top_n=int(args.top),
            soft_cap=int(args.soft_cap),
            dry_run=bool(args.dry_run),
        )
    except Exception as e:
        logger.exception("l4_warm_failed err=%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
