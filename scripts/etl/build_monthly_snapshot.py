"""Monthly snapshot batch for the Dim Q time-machine surface (Wave 47).

Materialises the operational audit layer behind the Dim Q
"regulatory time machine + counterfactual" surface (per
``feedback_time_machine_query_design.md``) on top of the audit tables
added by ``scripts/migrations/277_time_machine.sql``.

Scope
-----
For each ``as_of_date`` (default: first of current UTC month) and each
configured table in ``_SNAPSHOT_TABLES``:

1. Compute a deterministic ``sha256`` over the ordered canonical digest
   of every row in the table (or its time-machine spine view).
2. Insert/replace one row into ``am_monthly_snapshot_log`` keyed by
   ``(as_of_date, table_name)`` with ``row_count`` + ``sha256``.

The script does NOT mutate the underlying spine tables (e.g.
``am_amendment_snapshot``); it only writes to the audit log. The
existing index migration ``wave24_180_time_machine_index`` already
owns the live "what was alive at as_of" lookup path — this batch
records monthly digest fingerprints so an operator can prove that the
snapshot for a given month has not drifted.

Retention (``--gc``)
--------------------
Per ``feedback_time_machine_query_design`` we keep **60 monthly
snapshots** (5 years rolling). Running with ``--gc`` deletes any
``am_monthly_snapshot_log`` row whose ``as_of_date`` is older than
``today - 5y``.

Usage
-----
    python scripts/etl/build_monthly_snapshot.py               # apply current month
    python scripts/etl/build_monthly_snapshot.py --dry-run     # plan only
    python scripts/etl/build_monthly_snapshot.py --as-of 2024-06-01
    python scripts/etl/build_monthly_snapshot.py --db PATH
    python scripts/etl/build_monthly_snapshot.py --gc          # 5y retention sweep

No LLM API import — Dim Q snapshots are deterministic batch sql + hashing
(per ``feedback_no_operator_llm_api``). No aggregator fetch — snapshots
operate exclusively on the local autonomath.db spine (per
``feedback_time_machine_query_design`` "aggregator 禁止").

JSON output (final line, stdout)
--------------------------------
    {
      "dim": "Q",
      "wave": 47,
      "dry_run": <bool>,
      "as_of_date": "YYYY-MM-DD",
      "snapshots": [
        {"table_name": "...", "row_count": <int>, "sha256": "<hex>",
         "action": "inserted|updated|noop"}
      ],
      "gc_removed": <int>
    }
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"
LOG = logging.getLogger("build_monthly_snapshot")

# 5-year retention per feedback_time_machine_query_design ("過去 5 年保持").
_RETENTION_DAYS = 5 * 365

# Tables snapshotted each month. Keep small + audit-oriented: this is a
# fingerprint log, not a clone. The time-machine spine
# (am_amendment_snapshot, am_program_history) is the highest-value
# target; cross_source / law_jorei give corroboration.
_SNAPSHOT_TABLES: tuple[str, ...] = (
    "am_amendment_snapshot",
    "am_program_history",
    "am_law_jorei",
    "am_cross_source_agreement",
)


def _first_of_current_month_utc() -> str:
    today = _dt.datetime.now(_dt.UTC).date()
    return today.replace(day=1).isoformat()


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Refuse to run if migration 277 has not been applied."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name IN "
        "('am_monthly_snapshot_log', 'am_counterfactual_eval_log')"
    ).fetchall()
    found = {r[0] for r in rows}
    missing = {"am_monthly_snapshot_log", "am_counterfactual_eval_log"} - found
    if missing:
        raise RuntimeError(
            f"migration 277_time_machine not applied: missing tables {sorted(missing)}"
        )


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _compute_digest(conn: sqlite3.Connection, table: str) -> tuple[int, str]:
    """Return (row_count, sha256_hex) of canonical row dump for ``table``.

    Canonicalisation: rows are pulled with ``ORDER BY rowid`` and each
    row is JSON-serialised with sorted keys. The digest is sha256 over
    the concatenation of those line-delimited JSON strings.
    """
    if not _table_exists(conn, table):
        # Empty digest for absent tables — the audit row records the
        # snapshot attempt without conflating with "real data".
        empty = hashlib.sha256(b"").hexdigest()
        return 0, empty

    cur = conn.execute(f"SELECT * FROM {table} ORDER BY rowid")
    cols = [d[0] for d in cur.description]
    hasher = hashlib.sha256()
    n = 0
    for row in cur:
        payload = json.dumps(dict(zip(cols, row, strict=True)), sort_keys=True, default=str).encode(
            "utf-8"
        )
        hasher.update(payload + b"\n")
        n += 1
    return n, hasher.hexdigest()


def _upsert_snapshot(
    conn: sqlite3.Connection,
    *,
    as_of_date: str,
    table_name: str,
    row_count: int,
    sha256_hex: str,
    dry_run: bool,
) -> str:
    """Insert or update one row in am_monthly_snapshot_log; return action."""
    existing = conn.execute(
        "SELECT row_count, sha256 FROM am_monthly_snapshot_log "
        "WHERE as_of_date = ? AND table_name = ?",
        (as_of_date, table_name),
    ).fetchone()

    if existing is None:
        if dry_run:
            return "would_insert"
        conn.execute(
            "INSERT INTO am_monthly_snapshot_log "
            "(as_of_date, table_name, row_count, sha256) "
            "VALUES (?, ?, ?, ?)",
            (as_of_date, table_name, row_count, sha256_hex),
        )
        return "inserted"

    old_rows, old_hash = existing
    if old_rows == row_count and old_hash == sha256_hex:
        return "noop"

    if dry_run:
        return "would_update"
    conn.execute(
        "UPDATE am_monthly_snapshot_log "
        "SET row_count = ?, sha256 = ?, "
        "    created_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE as_of_date = ? AND table_name = ?",
        (row_count, sha256_hex, as_of_date, table_name),
    )
    return "updated"


def _gc(conn: sqlite3.Connection, *, dry_run: bool) -> int:
    """Drop rows older than 5y per feedback_time_machine_query_design."""
    cutoff = (_dt.datetime.now(_dt.UTC).date() - _dt.timedelta(days=_RETENTION_DAYS)).isoformat()
    n = conn.execute(
        "SELECT COUNT(*) FROM am_monthly_snapshot_log WHERE as_of_date < ?",
        (cutoff,),
    ).fetchone()[0]
    if dry_run or n == 0:
        return n
    conn.execute(
        "DELETE FROM am_monthly_snapshot_log WHERE as_of_date < ?",
        (cutoff,),
    )
    return n


def _validate_as_of(value: str) -> str:
    # Mirrors am_monthly_snapshot_log CHECK(length(as_of_date)=10).
    try:
        _dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--as-of must be YYYY-MM-DD: {exc}") from exc
    if len(value) != 10:
        raise argparse.ArgumentTypeError("--as-of must be exactly 10 chars")
    return value


def _build_snapshots(
    conn: sqlite3.Connection,
    *,
    as_of_date: str,
    dry_run: bool,
    tables: Iterable[str] = _SNAPSHOT_TABLES,
) -> list[dict]:
    out: list[dict] = []
    for table in tables:
        n, digest = _compute_digest(conn, table)
        action = _upsert_snapshot(
            conn,
            as_of_date=as_of_date,
            table_name=table,
            row_count=n,
            sha256_hex=digest,
            dry_run=dry_run,
        )
        out.append(
            {
                "table_name": table,
                "row_count": n,
                "sha256": digest,
                "action": action,
            }
        )
        LOG.info(
            "snapshot %s table=%s rows=%d action=%s",
            as_of_date,
            table,
            n,
            action,
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--as-of",
        type=_validate_as_of,
        default=_first_of_current_month_utc(),
        help="YYYY-MM-DD; defaults to first of current UTC month",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--gc",
        action="store_true",
        help="Sweep snapshot log rows older than 5y after snapshotting",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not args.db.exists():
        LOG.error("db %s does not exist", args.db)
        return 2

    conn = sqlite3.connect(str(args.db))
    try:
        _ensure_tables(conn)
        snapshots = _build_snapshots(conn, as_of_date=args.as_of, dry_run=args.dry_run)
        gc_removed = _gc(conn, dry_run=args.dry_run) if args.gc else 0
        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    print(
        json.dumps(
            {
                "dim": "Q",
                "wave": 47,
                "dry_run": bool(args.dry_run),
                "as_of_date": args.as_of,
                "snapshots": snapshots,
                "gc_removed": gc_removed,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
