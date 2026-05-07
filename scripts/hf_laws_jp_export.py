#!/usr/bin/env python3
"""Dedicated Hugging Face export for the laws-jp dataset.

This script exports only the `laws` table from data/jpintel.db. It does not
publish, push, or call external APIs.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
ETL_DIR = REPO_ROOT / "scripts" / "etl"
if str(ETL_DIR) not in sys.path:
    sys.path.insert(0, str(ETL_DIR))

from hf_export_safety_gate import HfExportSafetyError, assert_hf_export_safe  # noqa: E402

DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_OUTPUT = REPO_ROOT / "dist" / "hf-laws-jp"
DATASET_NAME = "laws-jp"
LICENSE = "cc_by_4.0"
PARQUET_NAME = "laws.parquet"

LAWS_QUERY = f"""
SELECT
    unified_id,
    law_number,
    law_title,
    law_short_title,
    law_type,
    ministry,
    promulgated_date,
    enforced_date,
    last_amended_date,
    revision_status,
    superseded_by_law_id,
    article_count,
    full_text_url,
    summary,
    subject_areas_json,
    source_url,
    source_checksum,
    confidence,
    fetched_at,
    updated_at,
    valid_from,
    valid_until,
    '{LICENSE}' AS license
FROM laws
ORDER BY unified_id
"""

EXPORTS = [("laws", LAWS_QUERY)]


def _coerce_laws_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Keep parquet types stable across permissive SQLite values."""
    if "article_count" in df.columns:
        df["article_count"] = pd.to_numeric(df["article_count"], errors="coerce").astype("Int64")
    if "confidence" in df.columns:
        df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce")
    return df


def _assert_explicit_license(df: pd.DataFrame) -> None:
    values = set(df["license"].dropna().astype(str).unique()) if "license" in df.columns else set()
    if values != {LICENSE}:
        raise RuntimeError(
            f"laws export must contain only license={LICENSE!r}; found {sorted(values)!r}"
        )


def export_laws(conn: sqlite3.Connection, out_dir: Path) -> tuple[int, int]:
    """Write laws.parquet and return (row_count, file_size_bytes)."""
    df = pd.read_sql_query(LAWS_QUERY, conn)
    df = _coerce_laws_frame(df)
    _assert_explicit_license(df)

    out_path = out_dir / PARQUET_NAME
    df.to_parquet(out_path, engine="pyarrow", compression="snappy", index=False)
    return len(df), out_path.stat().st_size


def _fmt_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _write_readme(out_dir: Path, row_count: int) -> None:
    text = f"""---
license: cc-by-4.0
language:
- ja
pretty_name: Japanese Laws (e-Gov)
---

# {DATASET_NAME}

This local export contains Japanese law metadata from the `laws` table in
`data/jpintel.db`.

- File: `{PARQUET_NAME}`
- Rows: {row_count}
- License column: `{LICENSE}`
- Source: e-Gov Laws Search URLs preserved per row in `source_url`

This export is generated locally only. No publish, upload, push, or external
API call is performed by `scripts/hf_laws_jp_export.py`.
"""
    (out_dir / "README.md").write_text(text, encoding="utf-8")


def _write_manifest(out_dir: Path, db_path: Path, row_count: int, parquet_bytes: int) -> None:
    manifest: dict[str, Any] = {
        "dataset": DATASET_NAME,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "source_db": str(db_path),
        "exports": [
            {
                "table": "laws",
                "file": PARQUET_NAME,
                "rows": row_count,
                "bytes": parquet_bytes,
                "license": LICENSE,
                "safety_gate": "passed",
            }
        ],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_export(db_path: Path, out_dir: Path) -> tuple[int, int]:
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        assert_hf_export_safe(conn, EXPORTS)
        out_dir.mkdir(parents=True, exist_ok=True)
        rows, parquet_bytes = export_laws(conn, out_dir)
    finally:
        conn.close()

    _write_readme(out_dir, rows)
    _write_manifest(out_dir, db_path, rows, parquet_bytes)
    return rows, parquet_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB, help=f"SQLite DB path (default: {DEFAULT_DB})"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    try:
        rows, parquet_bytes = run_export(args.db, args.output)
    except (FileNotFoundError, HfExportSafetyError, RuntimeError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Source DB:  {args.db}")
    print(f"Output dir: {args.output}")
    print(f"  laws {rows:>7,} rows  {_fmt_bytes(parquet_bytes):>12s}")
    print("  README.md")
    print("  manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
