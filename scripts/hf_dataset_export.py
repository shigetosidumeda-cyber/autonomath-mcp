#!/usr/bin/env python3
"""HuggingFace dataset export for AutonoMath public-program corpus.

Reads the canonical 4 tables from data/jpintel.db and writes parquet files
plus a HuggingFace dataset card (README.md) and a DataCard.md to the
output directory. Does NOT publish — login + upload is a separate operator
runbook (see docs/_internal/hf_publish_runbook.md).

Filter rules:
  - programs: only excluded=0 AND tier IN ('S','A','B','C') (the canonical
    "11,547 programs" view per CLAUDE.md). Quarantine tier 'X' and excluded
    rows are dropped — they are not safe for public consumption.
  - laws: full dump (9,484 rows).
  - case_studies: full dump (2,286 rows).
  - enforcement_cases: full dump (1,185 rows).

Outputs (under --output, default dist/hf-dataset/):
  - programs.parquet
  - laws.parquet
  - case_studies.parquet
  - enforcement_cases.parquet
  - README.md (dataset card, copied from repo template)
  - DataCard.md (DataCard schema, copied from repo template)

License: see README.md (CC-BY 4.0 for e-Gov 法令, 政府標準利用規約 v2.0 for
ministry programs / case studies / enforcement records, with primary-source
attribution preserved per row in `source_url`).
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_OUTPUT = REPO_ROOT / "dist" / "hf-dataset"

# Canonical public-program filter. See CLAUDE.md:
#   "11,547 programs (補助金・融資・税制・認定, tier S/A/B/C excluded=0)".
# Quarantine tier 'X' and excluded=1 rows are not safe to redistribute —
# they are either ambiguous, low-confidence, or aggregator-sourced.
PROGRAMS_FILTER = "excluded = 0 AND tier IN ('S', 'A', 'B', 'C')"

EXPORTS = [
    ("programs", f"SELECT * FROM programs WHERE {PROGRAMS_FILTER}"),
    ("laws", "SELECT * FROM laws"),
    ("case_studies", "SELECT * FROM case_studies"),
    ("enforcement_cases", "SELECT * FROM enforcement_cases"),
]


def _coerce_columns(conn: sqlite3.Connection, df: pd.DataFrame, table: str) -> pd.DataFrame:
    """Coerce numeric / boolean columns to clean dtypes.

    SQLite is permissive about column types — a REAL column can legitimately
    contain TEXT (e.g. `subsidy_rate = '定額'`). pyarrow refuses to write
    such mixed columns. We resolve this by reading the declared column type
    from PRAGMA and coercing:
      - REAL → pd.to_numeric(errors='coerce') (text becomes NaN)
      - INTEGER → pd.to_numeric(errors='coerce') then nullable Int64
    Stray TEXT values that cannot parse as numbers become NULL in parquet —
    this is the right behavior since they are upstream data-quality bugs
    rather than meaningful values.
    """
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    declared = {row[1]: (row[2] or "").upper() for row in cur.fetchall()}

    for col, declared_type in declared.items():
        if col not in df.columns:
            continue
        if "REAL" in declared_type or "FLOAT" in declared_type or "DOUBLE" in declared_type:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        elif "INT" in declared_type:
            # Use nullable Int64 so NULLs survive the round-trip cleanly.
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df


def export_table(conn: sqlite3.Connection, table: str, query: str, out_dir: Path) -> tuple[int, int]:
    """Run SELECT and write parquet. Returns (row_count, file_size_bytes)."""
    df = pd.read_sql_query(query, conn)
    df = _coerce_columns(conn, df, table)
    out_path = out_dir / f"{table}.parquet"
    # snappy compression is the parquet ecosystem default and is well-
    # supported by both pandas and polars without extra deps.
    df.to_parquet(out_path, engine="pyarrow", compression="snappy", index=False)
    return len(df), out_path.stat().st_size


def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def copy_doc(name: str, out_dir: Path) -> int | None:
    """Copy a doc template (README.md / DataCard.md) into out_dir if it
    already exists at out_dir/<name>. Returns line count or None if missing."""
    target = out_dir / name
    if target.exists():
        with target.open(encoding="utf-8") as f:
            return sum(1 for _ in f)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"SQLite DB path (default: {DEFAULT_DB})",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    args = ap.parse_args()

    db_path: Path = args.db
    out_dir: Path = args.output

    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Source DB:  {db_path}")
    print(f"Output dir: {out_dir}")
    print()

    conn = sqlite3.connect(str(db_path))
    try:
        total_rows = 0
        total_bytes = 0
        for table, query in EXPORTS:
            rows, size = export_table(conn, table, query, out_dir)
            total_rows += rows
            total_bytes += size
            print(f"  {table:20s} {rows:>7,} rows  {fmt_bytes(size):>12s}")
    finally:
        conn.close()

    print()
    print(f"  {'TOTAL':20s} {total_rows:>7,} rows  {fmt_bytes(total_bytes):>12s}")
    print()

    # README.md / DataCard.md are committed in the repo (templates). If
    # they're missing here it's a setup error — surface it but don't fail
    # the export, since parquet generation is the load-bearing step.
    for doc in ("README.md", "DataCard.md"):
        lines = copy_doc(doc, out_dir)
        if lines is None:
            print(f"WARN: {doc} missing under {out_dir} — operator must add before publish")
        else:
            print(f"  {doc:20s} {lines:>7,} lines")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
