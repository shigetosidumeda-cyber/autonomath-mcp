#!/usr/bin/env python3
"""Daily cron: evict expired rows from `am_idempotency_cache`.

Background
----------
Migration 087 introduced the 24h Idempotency-Key replay cache used by:
  * `IdempotencyMiddleware` (every metered POST that supplies the
    `Idempotency-Key` header — `src/jpintel_mcp/api/middleware/idempotency.py`).
  * `bulk_evaluate.py` (consultant CSV fan-out — keys cached by
    sha256(api_key_hash + ':/v1/me/clients/bulk_evaluate:' + idempotency_key)).

Both call sites are lazy-evict on read (rows past `expires_at` are
treated as cold misses), but without an active sweep the table grows
unbounded. At the documented ceiling of "tens of KB per cached POST"
this would be ~megabytes / month at low launch volumes — unbounded but
slow. The sweep keeps the table at steady-state size and guarantees
that abandoned cache entries cannot accidentally replay 24h+ later if
the eviction-on-read path ever has a defect.

Posture
-------
* Idempotent — re-running mid-day is safe; the WHERE clause skips rows
  that are still inside their TTL.
* Single-process — invoked once a day from a GitHub Actions cron via
  flyctl ssh. No locking concerns at launch volume.
* Telemetry — emits one structured log line + heartbeat row.

Wiring
------
Should be referenced by a GitHub Actions workflow at
`.github/workflows/idempotency-sweep-cron.yml` running daily at
03:30 JST (the slot just before `nta-bulk-monthly` starts at 03:00 on
the 1st). Until that workflow lands, the sweep is invokable manually:

    .venv/bin/python scripts/cron/idempotency_cache_sweep.py --dry-run

Operator: Bookyou株式会社 (T8010001213708).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from jpintel_mcp.db.session import connect
from jpintel_mcp.observability.cron_heartbeat import heartbeat

logger = logging.getLogger("jpintel.cron.idempotency_cache_sweep")

# Default cap on rows deleted per run. Generous — at expected launch
# volumes a single run will rarely top a few hundred. The cap exists
# only to keep a single run from holding a writer lock for minutes if a
# regression ever floods the table (e.g. middleware writing per-second
# keys for a stuck retry loop).
DEFAULT_LIMIT = 100_000


def sweep_expired(*, dry_run: bool = False, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Delete rows whose `expires_at` is in the past.

    Returns a counts dict {"scanned": int, "deleted": int, "errors": int}
    so the caller can render JSON / heartbeat metadata.
    """
    counts: dict[str, Any] = {
        "scanned": 0,
        "deleted": 0,
        "errors": 0,
        "dry_run": bool(dry_run),
    }
    now_iso = datetime.now(UTC).isoformat()
    conn = connect()
    try:
        # Count first so the heartbeat reports honest numbers even on dry-run.
        try:
            (n_due,) = conn.execute(
                "SELECT COUNT(*) FROM am_idempotency_cache WHERE expires_at < ?",
                (now_iso,),
            ).fetchone()
        except Exception:  # noqa: BLE001 — table missing on a partial migration
            logger.warning("am_idempotency_cache missing — migration 087 not applied?")
            return counts
        counts["scanned"] = int(n_due or 0)

        if dry_run or not n_due:
            return counts

        try:
            # ROWID-bounded delete keeps the lock window short.
            cur = conn.execute(
                "DELETE FROM am_idempotency_cache WHERE rowid IN ("
                "  SELECT rowid FROM am_idempotency_cache "
                "  WHERE expires_at < ? "
                "  LIMIT ?"
                ")",
                (now_iso, int(limit)),
            )
            counts["deleted"] = int(cur.rowcount or 0)
        except Exception:  # noqa: BLE001 — never raise from a cron
            logger.exception("idempotency_cache_sweep delete failed")
            counts["errors"] += 1
    finally:
        with contextlib.suppress(Exception):
            conn.close()

    return counts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Sweep expired am_idempotency_cache rows (daily cron).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Count rows that WOULD be deleted; do not actually DELETE.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Cap rows deleted per run (default {DEFAULT_LIMIT}).",
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    with heartbeat("idempotency_cache_sweep") as hb:
        counts = sweep_expired(dry_run=args.dry_run, limit=args.limit)
        logger.info(
            "idempotency_cache_sweep.done scanned=%d deleted=%d errors=%d dry_run=%s",
            counts["scanned"],
            counts["deleted"],
            counts["errors"],
            bool(counts["dry_run"]),
        )
        hb["rows_processed"] = int(counts.get("deleted", 0) or 0)
        hb["rows_skipped"] = int((counts.get("scanned", 0) or 0) - (counts.get("deleted", 0) or 0))
        hb["metadata"] = {
            "scanned": counts.get("scanned"),
            "errors": counts.get("errors"),
            "dry_run": bool(counts.get("dry_run", args.dry_run)),
        }

    print(json.dumps(counts, indent=2, ensure_ascii=False))
    return 1 if counts["errors"] > 0 else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["DEFAULT_LIMIT", "main", "sweep_expired"]
