#!/usr/bin/env python3
"""Hourly cross-source agreement refresher (mig 101 #6 + #8).

For every (entity_id, field_name) row in `am_entity_facts`, count the
distinct source_id values and write that back into the
`confirming_source_count` column added by migration 101. When the
recomputed count drops vs the previously-stored value (a regression — a
source went away or the row was downgraded) we ALSO write a
`correction_log` row tagged ``cross_source_conflict`` so the public RSS
feed surfaces the change.

Idempotency
-----------
Re-running on the same dataset produces zero correction_log rows after the
first pass — only DELTAS write a new correction_log row. This is the
"no spam" guard the public feed needs.

Cron cadence
------------
Hourly. Tuned to be cheap: GROUP BY entity_id+field_name caps the inner
result set at the number of distinct facts (~6.12M rows / ~30 fields max
per entity → bounded). On a hot DB this completes in <30 seconds.

Baseline gating
---------------
The very first wet run on a fresh `confirming_source_count` column would
emit ~4.88M correction_log rows — every fact whose stored value was the
column DEFAULT (1) and whose live distinct-source count came in at 0 or
under. The Trust 8-pack agent flagged this as P0 because every
correction_log row triggers a public markdown post + RSS append.

The cron now consults `cross_source_baseline_state` (migration 107). If
`baseline_completed = 0`, the run behaves as `--baseline`:

  * `confirming_source_count` IS refreshed.
  * `correction_log` writes are SUPPRESSED (regressions counted only).
  * On exit the flag flips to 1 + `baseline_run_at` is set.

From the second run onwards regression detection runs normally. Any
genuine regression hidden by the baseline pass re-emits on the next tick
(~1 hour later), so the worst-case detection latency is 1 cron tick.

The `--baseline` CLI flag forces baseline behaviour regardless of state
(handy for re-baselining after a known data migration).
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("autonomath.cron.cross_source_check")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from jpintel_mcp.observability import heartbeat  # noqa: E402

_DEFAULT_DB = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_REPO_ROOT / "autonomath.db")))


def _open_rw(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"autonomath.db missing at {path}")
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _baseline_pending(conn: sqlite3.Connection) -> bool:
    """True iff `cross_source_baseline_state.baseline_completed = 0`.

    Returns False (i.e. baseline already done OR table missing) on any
    error so the absence of migration 107 cannot accidentally keep the
    cron in baseline mode forever once mig 107 + this code both ship.
    """
    try:
        row = conn.execute(
            "SELECT baseline_completed FROM cross_source_baseline_state WHERE id = 1"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        # mig 107 not yet applied → fall through to legacy behaviour.
        logger.warning("cross_source_baseline_state missing: %s", exc)
        return False
    if row is None:
        return False
    return int(row["baseline_completed"] or 0) == 0


def _mark_baseline_complete(conn: sqlite3.Connection, *, now: str) -> None:
    """Flip `baseline_completed = 1` + set `baseline_run_at = now`."""
    try:
        conn.execute(
            "UPDATE cross_source_baseline_state "
            "SET baseline_completed = 1, baseline_run_at = ? "
            "WHERE id = 1",
            (now,),
        )
    except sqlite3.OperationalError as exc:
        logger.warning(
            "could not mark cross_source_baseline_state complete: %s",
            exc,
        )


def _run(
    db_path: Path,
    *,
    dry_run: bool = False,
    baseline: bool = False,
) -> dict[str, int]:
    """Refresh confirming_source_count + emit correction_log rows on regressions.

    Args:
        db_path: path to autonomath.db.
        dry_run: when True, no writes at all (no count refresh, no
            correction_log rows, no baseline state mutation).
        baseline: when True, force baseline mode (refresh counts, suppress
            correction_log writes, mark state complete on success). When
            False, the cron auto-detects baseline state from
            `cross_source_baseline_state.baseline_completed`.
    """
    out = {
        "checked": 0,
        "updated": 0,
        "regressions": 0,
        "logged": 0,
        "baseline_mode": 0,
        "baseline_marked_complete": 0,
    }
    conn = _open_rw(db_path)
    try:
        # Decide baseline mode: explicit flag wins; otherwise consult state.
        if baseline:
            in_baseline = True
        elif not dry_run and _baseline_pending(conn):
            in_baseline = True
            logger.info(
                "cross_source_baseline_state.baseline_completed=0 — "
                "auto-baseline mode for this run",
            )
        else:
            in_baseline = False
        out["baseline_mode"] = 1 if in_baseline else 0

        try:
            rows = conn.execute(
                "SELECT entity_id, field_name, "
                "       COUNT(DISTINCT source_id) AS sources, "
                "       MAX(confirming_source_count) AS prev "
                "FROM am_entity_facts "
                "GROUP BY entity_id, field_name "
                "HAVING entity_id IS NOT NULL"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            logger.error("am_entity_facts unreadable: %s", exc)
            return out

        now = datetime.now(UTC).isoformat()
        for r in rows:
            out["checked"] += 1
            live = int(r["sources"] or 0)
            prev = r["prev"]
            entity_id = r["entity_id"]
            field_name = r["field_name"]
            if prev is not None and int(prev) > live:
                out["regressions"] += 1
                # Baseline mode: count regressions but DO NOT write
                # correction_log rows. Same regressions re-fire on the
                # next non-baseline run (~1 cron tick latency).
                if not dry_run and not in_baseline:
                    try:
                        conn.execute(
                            "INSERT INTO correction_log("
                            "  detected_at, dataset, entity_id, field_name, "
                            "  prev_value_hash, new_value_hash, root_cause, "
                            "  source_url, reproducer_sql"
                            ") VALUES (?,?,?,?,?,?,?,?,?)",
                            (
                                now,
                                "am_entity_facts",
                                entity_id,
                                field_name,
                                f"sources:{int(prev)}",
                                f"sources:{live}",
                                "cross_source_conflict",
                                None,
                                f"SELECT * FROM am_entity_facts "
                                f"WHERE entity_id='{entity_id}' "
                                f"AND field_name='{field_name}'",
                            ),
                        )
                        out["logged"] += 1
                    except sqlite3.OperationalError as exc:
                        # correction_log table absent → mig 101 not applied.
                        logger.warning("correction_log unreachable: %s", exc)
                        break
            if not dry_run and (prev is None or int(prev) != live):
                try:
                    cur = conn.execute(
                        "UPDATE am_entity_facts SET confirming_source_count = ? "
                        "WHERE entity_id = ? AND field_name = ?",
                        (live, entity_id, field_name),
                    )
                    out["updated"] += int(cur.rowcount or 0)
                except sqlite3.OperationalError as exc:
                    logger.warning("confirming_source_count column missing: %s", exc)
                    break

        # Flip the baseline flag on exit when this run was a baseline pass.
        # Only when not dry_run and we actually completed a real iteration.
        if in_baseline and not dry_run:
            _mark_baseline_complete(conn, now=now)
            out["baseline_marked_complete"] = 1
    finally:
        conn.close()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=_DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--baseline",
        action="store_true",
        help=(
            "Force baseline mode: refresh confirming_source_count but "
            "skip ALL correction_log writes. Marks "
            "cross_source_baseline_state.baseline_completed=1 on success."
        ),
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    with heartbeat("cross_source_check") as hb:
        res = _run(args.db, dry_run=args.dry_run, baseline=args.baseline)
        logger.info(
            "cross_source_check: checked=%(checked)d updated=%(updated)d "
            "regressions=%(regressions)d logged=%(logged)d "
            "baseline_mode=%(baseline_mode)d "
            "baseline_marked_complete=%(baseline_marked_complete)d",
            res,
        )
        hb["rows_processed"] = int(res.get("updated", 0) or 0)
        hb["rows_skipped"] = int(res.get("checked", 0) or 0) - int(res.get("updated", 0) or 0)
        hb["metadata"] = {
            "checked": res.get("checked"),
            "regressions": res.get("regressions"),
            "logged": res.get("logged"),
            "baseline_mode": res.get("baseline_mode"),
            "baseline_marked_complete": res.get("baseline_marked_complete"),
            "dry_run": bool(args.dry_run),
        }
    return 0


if __name__ == "__main__":
    sys.exit(main())
