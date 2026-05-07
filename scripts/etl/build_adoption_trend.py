#!/usr/bin/env python3
"""Populate `am_adoption_trend_monthly` from jpi_adoption_records.

Why this exists:
    Per-industry monthly time-series view of 採択 (adoption) records so
    downstream tools (weekly KPI digest, industry pack tools, public
    "trending industries" surface) can answer "which JSIC major saw the
    biggest 採択 surge in the last quarter" without re-aggregating
    201,845 rows on every request.

Read sources:
    * jpi_adoption_records (autonomath.db)
        - announced_at (date) → year_month bucket
        - houjin_bangou → distinct_houjin_count
        - program_id / program_id_hint → distinct_program_count
        - industry_jsic_medium (single-letter major fallback)
        - program_id (preferred join key)
    * programs.jsic_majors (jpintel.db, attached as `jp` when --jpintel-db
        is passed). JSON list per program — exploded into one (program ×
        major) pair per row to drive the per-industry aggregate. Falls
        back to industry_jsic_medium when programs row not joinable.

Write target:
    am_adoption_trend_monthly — full DELETE + bulk INSERT in one
    transaction. Idempotent and safe to re-run.

trend_flag formula:
    For each (jsic_major), compute the chronologically-ordered series of
    (year_month, adoption_count). For each month i with i >= 5
    (zero-indexed), let:
        cur  = mean(count[i-2..i])           # last 3 months including i
        prev = mean(count[i-5..i-3])         # 3 months before that
    Then:
        +>= 10% lift → 'increasing'
        -<= 10% drop → 'decreasing'
        otherwise    → 'stable'
    Months with insufficient history are left NULL.

Report:
    * Top 5 increasing / top 5 decreasing JSIC majors over last 12 months
      (delta = sum(last 6) - sum(prior 6) divided by sum(prior 6+1))
    * Monthly total adoption count chart for last 12 months (text bars)

Non-LLM: pure SQL aggregation + Python date math.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"


def open_db(path: Path) -> sqlite3.Connection:
    if not path.exists():
        sys.stderr.write(f"ERROR: autonomath.db not found at {path}\n")
        sys.exit(2)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -200000;")  # 200 MB page cache
    return conn


def ensure_table(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_adoption_trend_monthly';"
    ).fetchone()
    if row is None:
        sys.stderr.write(
            "ERROR: am_adoption_trend_monthly missing — apply "
            "scripts/migrations/160_am_adoption_trend_monthly.sql first.\n"
        )
        sys.exit(3)


def attach_jpintel(conn: sqlite3.Connection, jpintel_path: Path) -> bool:
    if not jpintel_path.exists():
        print(
            f"  WARN: jpintel.db not found at {jpintel_path} — "
            f"will rely on industry_jsic_medium only",
            flush=True,
        )
        return False
    conn.execute(f"ATTACH DATABASE '{jpintel_path}' AS jp;")
    return True


def load_program_majors(conn: sqlite3.Connection, attached: bool) -> dict[str, list[str]]:
    """Return {program_unified_id: [jsic_major, ...]} from jp.programs.jsic_majors."""
    if not attached:
        return {}
    print("[1/5] loading programs.jsic_majors from jpintel.db ...", flush=True)
    t0 = time.time()
    out: dict[str, list[str]] = {}
    for row in conn.execute(
        "SELECT unified_id, jsic_majors FROM jp.programs "
        "WHERE jsic_majors IS NOT NULL AND jsic_majors != '';"
    ):
        try:
            arr = json.loads(row["jsic_majors"])
        except (TypeError, ValueError):
            continue
        if not isinstance(arr, list):
            continue
        majors = [m for m in arr if isinstance(m, str) and len(m) == 1 and m.isalpha()]
        if majors:
            out[row["unified_id"]] = majors
    print(f"  programs with majors={len(out):,} ({time.time() - t0:.1f}s)", flush=True)
    return out


def aggregate_buckets(
    conn: sqlite3.Connection,
    program_majors: dict[str, list[str]],
) -> dict[tuple[str, str], dict]:
    """Walk jpi_adoption_records and accumulate per-(year_month, major) buckets."""
    print("[2/5] aggregating jpi_adoption_records into (YM, jsic_major) buckets ...", flush=True)
    t0 = time.time()
    sql = """
        SELECT strftime('%Y-%m', announced_at) AS ym,
               houjin_bangou,
               program_id,
               program_id_hint,
               industry_jsic_medium
          FROM jpi_adoption_records
         WHERE announced_at IS NOT NULL
           AND announced_at != ''
    """
    buckets: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"adopt": 0, "houjin": set(), "program": set()}
    )
    rows_seen = 0
    rows_no_major = 0
    rows_via_program = 0
    rows_via_medium = 0
    for r in conn.execute(sql):
        rows_seen += 1
        ym = r["ym"]
        if not ym or len(ym) != 7:
            continue

        # Resolve majors: prefer programs.jsic_majors (exploded), fall back to
        # industry_jsic_medium (single-letter major encoded under that name).
        majors: list[str] = []
        prog_key = r["program_id"]
        if prog_key and prog_key in program_majors:
            majors = program_majors[prog_key]
            rows_via_program += 1
        else:
            m = r["industry_jsic_medium"]
            if m and len(m) >= 1:
                first = m[0]
                if first.isalpha():
                    majors = [first.upper()]
                    rows_via_medium += 1

        if not majors:
            rows_no_major += 1
            continue

        prog_set_key = r["program_id"] or r["program_id_hint"]
        for mj in majors:
            b = buckets[(ym, mj)]
            b["adopt"] += 1
            if r["houjin_bangou"]:
                b["houjin"].add(r["houjin_bangou"])
            if prog_set_key:
                b["program"].add(prog_set_key)

    print(
        f"  rows={rows_seen:,} bucketed={len(buckets):,} "
        f"via_program={rows_via_program:,} via_medium={rows_via_medium:,} "
        f"no_major={rows_no_major:,} ({time.time() - t0:.1f}s)",
        flush=True,
    )
    return buckets


def compute_trend_flags(
    buckets: dict[tuple[str, str], dict],
) -> dict[tuple[str, str], str | None]:
    """For each major, sort months ascending and compute trend_flag per month
    using a 3-month rolling avg vs prior 3-month avg. Months with i < 5 in
    the per-major series stay NULL.
    """
    print("[3/5] computing trend_flag per (jsic_major, year_month) ...", flush=True)
    t0 = time.time()
    by_major: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for (ym, mj), b in buckets.items():
        by_major[mj].append((ym, b["adopt"]))
    flags: dict[tuple[str, str], str | None] = {}
    for mj, series in by_major.items():
        series.sort(key=lambda kv: kv[0])
        for i, (ym, _cnt) in enumerate(series):
            if i < 5:
                flags[(ym, mj)] = None
                continue
            cur = sum(c for _, c in series[i - 2 : i + 1]) / 3.0
            prev = sum(c for _, c in series[i - 5 : i - 2]) / 3.0
            if prev <= 0:
                flags[(ym, mj)] = "increasing" if cur > 0 else "stable"
                continue
            ratio = cur / prev
            if ratio >= 1.10:
                flags[(ym, mj)] = "increasing"
            elif ratio <= 0.90:
                flags[(ym, mj)] = "decreasing"
            else:
                flags[(ym, mj)] = "stable"
    print(f"  flagged buckets={len(flags):,} ({time.time() - t0:.1f}s)", flush=True)
    return flags


def write_buckets(
    conn: sqlite3.Connection,
    buckets: dict[tuple[str, str], dict],
    flags: dict[tuple[str, str], str | None],
) -> int:
    print(f"[4/5] writing am_adoption_trend_monthly ({len(buckets):,} rows) ...", flush=True)
    t0 = time.time()
    conn.execute("BEGIN;")
    conn.execute("DELETE FROM am_adoption_trend_monthly;")
    insert_sql = """
        INSERT INTO am_adoption_trend_monthly (
            year_month, jsic_major,
            adoption_count, distinct_houjin_count, distinct_program_count,
            trend_flag, computed_at
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    """
    rows: list[tuple] = []
    for (ym, mj), b in buckets.items():
        rows.append(
            (
                ym,
                mj,
                b["adopt"],
                len(b["houjin"]),
                len(b["program"]),
                flags.get((ym, mj)),
            )
        )
    BATCH = 5000  # noqa: N806  (local CONST sentinel, not loop-mut)
    written = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i : i + BATCH]
        conn.executemany(insert_sql, chunk)
        written += len(chunk)
    conn.execute("COMMIT;")
    print(f"  wrote {written:,} rows ({time.time() - t0:.1f}s)", flush=True)
    return written


def report(conn: sqlite3.Connection) -> None:
    print("[5/5] trend report (last 12 months)", flush=True)
    print("=" * 72)

    # Anchor on the most-recent year_month present in the data.
    anchor = conn.execute("SELECT MAX(year_month) FROM am_adoption_trend_monthly;").fetchone()[0]
    if not anchor:
        print("  (no data — table empty)")
        return

    # Build last-12 + prior-6 vs last-6 sliding windows per major.
    # YYYY-MM lex-comparable; build the 12 month ids by walking back.
    yr, mo = int(anchor[:4]), int(anchor[5:7])
    last12: list[str] = []
    for _ in range(12):
        last12.append(f"{yr:04d}-{mo:02d}")
        mo -= 1
        if mo == 0:
            mo = 12
            yr -= 1
    last12.reverse()
    last6 = set(last12[6:])
    prior6 = set(last12[:6])

    print(f"  anchor month: {anchor}")
    print(f"  last 12 months: {last12[0]} .. {last12[-1]}")
    print()

    # Per-major rollup over those 18 months.
    placeholders = ",".join("?" for _ in last12)
    rows = conn.execute(
        f"""
        SELECT jsic_major, year_month, adoption_count
          FROM am_adoption_trend_monthly
         WHERE year_month IN ({placeholders})
        """,
        last12,
    ).fetchall()
    per_major: dict[str, dict[str, int]] = defaultdict(dict)
    for r in rows:
        per_major[r["jsic_major"]][r["year_month"]] = r["adoption_count"]

    deltas: list[tuple[str, int, int, float]] = []
    for mj, ymmap in per_major.items():
        s_last = sum(ymmap.get(ym, 0) for ym in last6)
        s_prev = sum(ymmap.get(ym, 0) for ym in prior6)
        # Pct delta with +1 in denominator to neutralize divide-by-zero.
        delta_pct = (s_last - s_prev) / max(s_prev, 1) * 100.0
        deltas.append((mj, s_prev, s_last, delta_pct))

    deltas_inc = sorted(deltas, key=lambda x: -x[3])
    deltas_dec = sorted(deltas, key=lambda x: x[3])

    print("  Top 5 increasing JSIC majors (last 6 mo vs prior 6 mo):")
    print(f"  {'rank':>4}  {'jsic':<5}  {'prev6':>7}  {'last6':>7}  {'delta%':>9}")
    for i, (mj, p, last, d) in enumerate(deltas_inc[:5], start=1):
        print(f"  {i:>4}  {mj:<5}  {p:>7,}  {last:>7,}  {d:>+9.1f}%")
    print()
    print("  Top 5 decreasing JSIC majors (last 6 mo vs prior 6 mo):")
    print(f"  {'rank':>4}  {'jsic':<5}  {'prev6':>7}  {'last6':>7}  {'delta%':>9}")
    for i, (mj, p, last, d) in enumerate(deltas_dec[:5], start=1):
        print(f"  {i:>4}  {mj:<5}  {p:>7,}  {last:>7,}  {d:>+9.1f}%")
    print()

    # Monthly total chart over last 12 months (cross-major sum).
    monthly_total: dict[str, int] = dict.fromkeys(last12, 0)
    for ymmap in per_major.values():
        for ym, c in ymmap.items():
            if ym in monthly_total:
                monthly_total[ym] += c
    peak = max(monthly_total.values()) if monthly_total else 0
    BAR_WIDTH = 40  # noqa: N806  (local CONST sentinel, not loop-mut)
    print("  Monthly total adoption count (cross-industry, last 12 mo):")
    print(f"  {'YYYY-MM':<8}  {'count':>7}  bar")
    for ym in last12:
        c = monthly_total.get(ym, 0)
        bar_len = int(round(c / peak * BAR_WIDTH)) if peak else 0
        bar = "#" * bar_len
        print(f"  {ym:<8}  {c:>7,}  {bar}")
    print("=" * 72)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help="path to autonomath.db (default: repo-root autonomath.db)",
    )
    ap.add_argument(
        "--jpintel-db",
        type=Path,
        default=DEFAULT_JPINTEL_DB,
        help="path to jpintel.db for programs.jsic_majors join "
        "(default: data/jpintel.db; pass an empty string to disable)",
    )
    args = ap.parse_args()
    db_path = args.db
    if not os.path.isabs(db_path):
        db_path = (REPO_ROOT / db_path).resolve()
    jpintel_path = args.jpintel_db
    if jpintel_path and not os.path.isabs(jpintel_path):
        jpintel_path = (REPO_ROOT / jpintel_path).resolve()

    conn = open_db(db_path)
    try:
        ensure_table(conn)
        attached = False
        if jpintel_path:
            attached = attach_jpintel(conn, jpintel_path)
        program_majors = load_program_majors(conn, attached)
        buckets = aggregate_buckets(conn, program_majors)
        flags = compute_trend_flags(buckets)
        write_buckets(conn, buckets, flags)
        report(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
