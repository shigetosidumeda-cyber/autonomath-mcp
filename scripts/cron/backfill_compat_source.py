#!/usr/bin/env python3
"""Source URL backfill for am_compat_matrix (phantom-moat audit fix #2, 2026-04-29).

What it does:
  Walks am_compat_matrix rows that are missing source_url and tries to
  recover one through the am_relation -> am_entity_source -> am_source
  chain. When a citation is found, UPDATE source_url AND clear
  inferred_only -> 0 so the row joins the authoritative corpus.

Why this exists:
  The phantom-moat audit (recommendation #2) found that 90.8% of
  am_compat_matrix rows had no source_url. Migration 077 stamps
  inferred_only=1 on every uncited row and deletes the 4,849-row pure
  noise bucket (status='unknown' AND evidence_relation IS NULL). This
  script reclaims rows that ARE backed by a real relation but where the
  citation never made it into am_compat_matrix.source_url at ingest
  time.

Idempotency:
  Re-running with no new joinable rows updates 0 rows. The script never
  overwrites a non-NULL/non-empty source_url; it only fills blanks.

Recovery scope (verified against live autonomath.db at 2026-04-29):
  778 distinct (program_a_id, program_b_id) pairs are joinable to
  am_relation rows whose source_entity_id has at least one am_source
  row with a non-empty source_url. The first such URL wins (LIMIT 1
  with deterministic ORDER BY) so re-runs converge.

Usage:
    python scripts/cron/backfill_compat_source.py            # full run
    python scripts/cron/backfill_compat_source.py --dry-run  # log only
    python scripts/cron/backfill_compat_source.py --limit 10 # first N rows
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402

logger = logging.getLogger("autonomath.cron.backfill_compat_source")


# Relation types that justify inheriting a citation from the source
# entity. Compatibility / prerequisite / replacement edges are the
# direct semantic match; "related" is broader but still better than
# leaving the row uncited per the audit recommendation.
_USABLE_RELATION_TYPES: tuple[str, ...] = (
    "compatible",
    "incompatible",
    "prerequisite",
    "replaces",
    "successor_of",
    "related",
    "part_of",
)


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.cron.backfill_compat_source")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _candidate_pairs(
    conn: sqlite3.Connection, limit: int | None
) -> list[sqlite3.Row]:
    """Return (program_a_id, program_b_id, recovered_source_url) for every
    am_compat_matrix row that:
      * has no source_url today, AND
      * has at least one am_relation edge between (a, b) of a usable type, AND
      * the source-side entity has at least one am_source.source_url.

    The recovered URL is the lexicographically smallest non-empty
    source_url among the candidates (deterministic, idempotent
    convergence on re-runs).
    """
    placeholders = ",".join(["?"] * len(_USABLE_RELATION_TYPES))
    sql = f"""
        SELECT m.program_a_id      AS program_a_id,
               m.program_b_id      AS program_b_id,
               MIN(s.source_url)   AS recovered_url
          FROM am_compat_matrix m
          JOIN am_relation r
            ON r.source_entity_id = m.program_a_id
           AND r.target_entity_id = m.program_b_id
           AND r.relation_type IN ({placeholders})
          JOIN am_entity_source es
            ON es.entity_id = r.source_entity_id
          JOIN am_source s
            ON s.id = es.source_id
         WHERE (m.source_url IS NULL OR m.source_url = '')
           AND s.source_url IS NOT NULL
           AND s.source_url != ''
         GROUP BY m.program_a_id, m.program_b_id
         ORDER BY m.program_a_id, m.program_b_id
    """
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, _USABLE_RELATION_TYPES).fetchall()


def _apply_one(
    conn: sqlite3.Connection,
    program_a_id: str,
    program_b_id: str,
    recovered_url: str,
    dry_run: bool,
) -> int:
    """Apply the URL recovery for one (a, b) pair.

    Re-checks the source_url IS NULL/'' precondition inside the UPDATE
    so a concurrent writer can't race us into clobbering a real URL
    (defensive — the cron is the only writer in practice). Also flips
    inferred_only -> 0 so the row enters the authoritative corpus.

    Returns the number of rows mutated (0 or 1).
    """
    if dry_run:
        logger.info(
            "would_update a=%s b=%s url=%s",
            program_a_id,
            program_b_id,
            recovered_url,
        )
        return 1

    cur = conn.execute(
        """
        UPDATE am_compat_matrix
           SET source_url    = ?,
               inferred_only = 0
         WHERE program_a_id = ?
           AND program_b_id = ?
           AND (source_url IS NULL OR source_url = '')
        """,
        (recovered_url, program_a_id, program_b_id),
    )
    return int(cur.rowcount or 0)


def run(
    am_db_path: Path,
    limit: int | None,
    dry_run: bool,
) -> dict[str, int]:
    """Iterate joinable pairs, fill source_url, return counters.

    Counters:
      * pairs_scanned         — joinable (a, b) pairs found
      * rows_updated          — am_compat_matrix rows mutated
      * pairs_skipped         — pairs where the row already had a URL
                                  (race / re-run convergence)
    """
    if not am_db_path.is_file():
        logger.error("am_db_missing path=%s", am_db_path)
        return {"pairs_scanned": 0, "rows_updated": 0, "pairs_skipped": 0}

    conn = connect(am_db_path)
    try:
        # Confirm the inferred_only column exists. If migration 077
        # hasn't been applied yet, fail loudly rather than silently
        # do nothing.
        cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(am_compat_matrix)").fetchall()
        }
        if "inferred_only" not in cols:
            logger.error(
                "inferred_only_missing path=%s "
                "did_you_apply_migration=077_compat_matrix_quality.sql",
                am_db_path,
            )
            return {"pairs_scanned": 0, "rows_updated": 0, "pairs_skipped": 0}

        pairs = _candidate_pairs(conn, limit)
        logger.info(
            "backfill_compat_source_start db=%s pairs=%d limit=%s dry_run=%s",
            am_db_path,
            len(pairs),
            limit,
            dry_run,
        )

        rows_updated = 0
        pairs_skipped = 0

        if not dry_run:
            conn.execute("BEGIN")
        try:
            for p in pairs:
                n = _apply_one(
                    conn=conn,
                    program_a_id=p["program_a_id"],
                    program_b_id=p["program_b_id"],
                    recovered_url=p["recovered_url"],
                    dry_run=dry_run,
                )
                if n > 0:
                    rows_updated += n
                else:
                    pairs_skipped += 1
            if not dry_run:
                conn.execute("COMMIT")
        except Exception:
            if not dry_run:
                conn.execute("ROLLBACK")
            raise

        counters = {
            "pairs_scanned": len(pairs),
            "rows_updated": rows_updated,
            "pairs_skipped": pairs_skipped,
        }
        logger.info(
            "backfill_compat_source_done pairs=%d updated=%d skipped=%d",
            counters["pairs_scanned"],
            counters["rows_updated"],
            counters["pairs_skipped"],
        )
        return counters
    finally:
        conn.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Source URL backfill for am_compat_matrix"
        " (phantom-moat audit fix #2)"
    )
    p.add_argument(
        "--am-db",
        type=Path,
        default=None,
        help="Path to autonomath.db (default: settings.autonomath_db_path)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N joinable pairs (test mode)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Log updates but do not write",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)

    am_db_path = args.am_db if args.am_db else settings.autonomath_db_path

    try:
        run(
            am_db_path=am_db_path,
            limit=args.limit,
            dry_run=bool(args.dry_run),
        )
    except Exception as e:
        logger.exception("backfill_compat_source_failed err=%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
