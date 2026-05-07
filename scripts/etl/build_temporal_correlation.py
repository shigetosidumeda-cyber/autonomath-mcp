#!/usr/bin/env python3
"""Build the am_temporal_correlation mat view (migration 154).

Walks am_amendment_snapshot (dated rows only) → am_law_reference (for
law_canonical_id) → entity_id_map (for jpi_programs.unified_id) →
jpi_adoption_records (for date-bounded adoption counts), and writes
one row per (amendment × program) into am_temporal_correlation.

Re-runs are idempotent: the table is fully wiped + repopulated inside
a single transaction. The dated source set is small (~144 snapshot
rows) and the join is a few hundred rows total, so a full rebuild is
cheaper than per-row UPSERT and avoids stale-PK drift when the
am_amendment_diff cron starts contributing post-launch.

NO LLM, NO network, pure SQLite + Python date arithmetic.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

# am_amendment_snapshot.effective_from carries free-text dates. We accept
# only formats that resolve to an unambiguous YYYY-MM-DD; everything else
# is dropped (not invented). Honest > complete.
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_ISO_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{2})(?!-)")
_JP_YMD = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日")
_JP_YM = re.compile(r"^(\d{4})年(\d{1,2})月(?!\d*日)")


def parse_effective_date(raw: str | None) -> date | None:
    """Return a `date` or None. NULL/'' and free-text-only inputs return None.

    Recognized formats:
      * 2024-04-01            → 2024-04-01
      * 2024-04-01T00:00:00Z  → 2024-04-01
      * 2024-04               → 2024-04-01 (first of month)
      * 2024年4月1日           → 2024-04-01
      * 2024年4月              → 2024-04-01
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    m = _ISO_DATE.match(s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _JP_YMD.match(s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _ISO_YEAR_MONTH.match(s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return None
    m = _JP_YM.match(s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return None
    return None


def parse_announced_date(raw: str | None) -> date | None:
    """jpi_adoption_records.announced_at appears mostly ISO. Reuse parser."""
    return parse_effective_date(raw)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def fetch_dated_amendments(conn: sqlite3.Connection) -> list[tuple]:
    """All snapshot rows whose effective_from parses to a real date.

    Returns: list of (snapshot_id, entity_id, effective_date_obj).
    """
    cur = conn.execute(
        """
        SELECT snapshot_id, entity_id, effective_from
        FROM am_amendment_snapshot
        WHERE effective_from IS NOT NULL
          AND effective_from != ''
        """
    )
    out: list[tuple] = []
    for snapshot_id, entity_id, effective_from in cur:
        d = parse_effective_date(effective_from)
        if d is None:
            continue
        out.append((snapshot_id, entity_id, d))
    return out


def fetch_law_refs_for_entities(
    conn: sqlite3.Connection, entity_ids: Iterable[str]
) -> dict[str, list[str]]:
    """entity_id → list of distinct law_canonical_id (NULL filtered out)."""
    ids = list(set(entity_ids))
    if not ids:
        return {}
    out: dict[str, list[str]] = {eid: [] for eid in ids}
    chunk = 500
    for i in range(0, len(ids), chunk):
        sub = ids[i : i + chunk]
        placeholders = ",".join("?" * len(sub))
        cur = conn.execute(
            f"""
            SELECT entity_id, law_canonical_id
            FROM am_law_reference
            WHERE entity_id IN ({placeholders})
              AND law_canonical_id IS NOT NULL
              AND law_canonical_id != ''
            """,
            sub,
        )
        for entity_id, law_id in cur:
            if law_id not in out[entity_id]:
                out[entity_id].append(law_id)
    return out


def fetch_program_unified_for_entities(
    conn: sqlite3.Connection, entity_ids: Iterable[str]
) -> dict[str, list[str]]:
    """am.canonical_id → list of jpi_programs.unified_id via entity_id_map."""
    ids = list(set(entity_ids))
    if not ids:
        return {}
    out: dict[str, list[str]] = {eid: [] for eid in ids}
    chunk = 500
    for i in range(0, len(ids), chunk):
        sub = ids[i : i + chunk]
        placeholders = ",".join("?" * len(sub))
        cur = conn.execute(
            f"""
            SELECT am_canonical_id, jpi_unified_id
            FROM entity_id_map
            WHERE am_canonical_id IN ({placeholders})
            """,
            sub,
        )
        for am_id, jpi_id in cur:
            if jpi_id and jpi_id not in out[am_id]:
                out[am_id].append(jpi_id)
    return out


def fetch_adoption_dates_for_program(conn: sqlite3.Connection, program_id: str) -> list[date]:
    """All parseable announced_at dates for one program."""
    cur = conn.execute(
        """
        SELECT announced_at
        FROM jpi_adoption_records
        WHERE program_id = ?
          AND announced_at IS NOT NULL
          AND announced_at != ''
        """,
        (program_id,),
    )
    dates: list[date] = []
    for (raw,) in cur:
        d = parse_announced_date(raw)
        if d is not None:
            dates.append(d)
    return dates


def count_window(adoption_dates: list[date], anchor: date, days: int, post: bool) -> int:
    """Count adoptions in [-days, 0) (post=False) or (0, +days] (post=True)."""
    if post:
        lo = anchor + timedelta(days=1)
        hi = anchor + timedelta(days=days)
    else:
        lo = anchor - timedelta(days=days)
        hi = anchor - timedelta(days=1)
    return sum(1 for d in adoption_dates if lo <= d <= hi)


def build(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")

    amendments = fetch_dated_amendments(conn)
    if not amendments:
        conn.close()
        return {"amendments_dated": 0, "rows_inserted": 0, "programs_joined": 0}

    entity_ids = [eid for (_, eid, _) in amendments]
    law_map = fetch_law_refs_for_entities(conn, entity_ids)
    program_map = fetch_program_unified_for_entities(conn, entity_ids)

    # Cache adoption date lookups per program (one query per distinct program).
    adoption_cache: dict[str, list[date]] = {}

    # PK is (amendment_id, program_id); collapse multiple law citations on
    # the same amendment to a single row by taking the first non-empty
    # law_canonical_id (deterministic via sort) — informational column,
    # not a join key in this surface.
    rows_to_insert: list[tuple] = []
    programs_joined = 0

    for snapshot_id, entity_id, eff_date in amendments:
        law_ids_sorted = sorted(law_map.get(entity_id) or [])
        law_id = next((lid for lid in law_ids_sorted if lid), "")
        program_ids = sorted(set(program_map.get(entity_id) or [""]))

        for program_id in program_ids:
            if program_id and program_id not in adoption_cache:
                adoption_cache[program_id] = fetch_adoption_dates_for_program(conn, program_id)
            adoptions = adoption_cache.get(program_id, []) if program_id else []

            pre30 = count_window(adoptions, eff_date, 30, post=False)
            post30 = count_window(adoptions, eff_date, 30, post=True)
            pre90 = count_window(adoptions, eff_date, 90, post=False)
            post90 = count_window(adoptions, eff_date, 90, post=True)

            # no signal when both windows are empty
            ratio: float | None = None if pre30 == 0 and post30 == 0 else post30 / max(pre30, 1)

            if program_id:
                programs_joined += 1

            rows_to_insert.append(
                (
                    str(snapshot_id),
                    eff_date.isoformat(),
                    law_id,
                    program_id,
                    pre30,
                    post30,
                    pre90,
                    post90,
                    ratio,
                )
            )

    # Full rebuild: wipe then bulk-insert in a single transaction.
    with conn:
        conn.execute("DELETE FROM am_temporal_correlation;")
        conn.executemany(
            """
            INSERT INTO am_temporal_correlation (
                amendment_id,
                amendment_effective_at,
                law_canonical_id,
                program_id,
                adoption_count_pre30d,
                adoption_count_post30d,
                adoption_count_pre90d,
                adoption_count_post90d,
                ratio_post_to_pre
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows_to_insert,
        )

    conn.close()
    return {
        "amendments_dated": len(amendments),
        "rows_inserted": len(rows_to_insert),
        "programs_joined": programs_joined,
    }


def report_top_correlations(db_path: Path, threshold: float = 1.5, limit: int = 20) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        SELECT amendment_id,
               amendment_effective_at,
               law_canonical_id,
               program_id,
               adoption_count_pre30d  AS pre30,
               adoption_count_post30d AS post30,
               adoption_count_pre90d  AS pre90,
               adoption_count_post90d AS post90,
               ratio_post_to_pre      AS ratio
        FROM am_temporal_correlation
        WHERE ratio_post_to_pre IS NOT NULL
          AND ratio_post_to_pre >= ?
        ORDER BY ratio_post_to_pre DESC, post30 DESC
        LIMIT ?
        """,
        (threshold, limit),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print(f"[report] No pairs with ratio_post_to_pre >= {threshold}.")
        return
    print(
        f"[report] Top {len(rows)} (amendment × program) pairs with "
        f"ratio_post_to_pre >= {threshold}:"
    )
    print(
        f"  {'amendment_id':>12}  {'effective':10}  {'law_id':30}  "
        f"{'program_id':16}  {'pre30':>5} {'post30':>6}  {'ratio':>6}"
    )
    for r in rows:
        law_id = (r["law_canonical_id"] or "(none)")[:30]
        program_id = (r["program_id"] or "(none)")[:16]
        ratio = r["ratio"]
        print(
            f"  {str(r['amendment_id']):>12}  {r['amendment_effective_at']:10}  "
            f"{law_id:30}  {program_id:16}  "
            f"{r['pre30']:>5} {r['post30']:>6}  {ratio:>6.2f}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=AUTONOMATH_DB)
    parser.add_argument(
        "--threshold",
        type=float,
        default=1.5,
        help="Minimum ratio_post_to_pre for the top-correlation report",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max rows in the top-correlation report",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Skip rebuild; just print the top-correlation report",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"[error] DB not found: {args.db}", file=sys.stderr)
        return 1

    if not args.report_only:
        started = datetime.now()
        stats = build(args.db)
        elapsed = (datetime.now() - started).total_seconds()
        print(
            f"[build] dated_amendments={stats['amendments_dated']} "
            f"rows_inserted={stats['rows_inserted']} "
            f"programs_joined={stats['programs_joined']} "
            f"elapsed={elapsed:.2f}s"
        )

    report_top_correlations(args.db, threshold=args.threshold, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
