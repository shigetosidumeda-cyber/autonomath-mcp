#!/usr/bin/env python3
"""Safe aggregate-only HuggingFace export helpers.

Exports only k-anonymous aggregate cells for sensitive invoice and enforcement
tables. No row-level identifiers or source text are selected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
ETL_DIR = REPO_ROOT / "scripts" / "etl"
if str(ETL_DIR) not in sys.path:
    sys.path.insert(0, str(ETL_DIR))

from hf_export_safety_gate import (  # noqa: E402
    HfExport,
    HfExportSafetyError,
    assert_hf_export_safe,
)

DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_OUTPUT = REPO_ROOT / "dist" / "hf-aggregates-safe"
MIN_K = 5


@dataclass(frozen=True)
class AggregateExportDefinition:
    dataset: str
    filename: str
    count_column: str
    query: str
    license: str
    attribution: str
    transformation_note: str
    min_k: int = MIN_K

    @property
    def path_name(self) -> str:
        return f"{self.filename}.parquet"

    def gate_export(self) -> HfExport:
        return HfExport(table=self.dataset, query=self.query)


EXPORT_DEFINITIONS: tuple[AggregateExportDefinition, ...] = (
    AggregateExportDefinition(
        dataset="invoice_registrants_by_prefecture",
        filename="invoice_registrants_by_prefecture",
        count_column="registrant_count",
        query=f"""
        SELECT
            COALESCE(NULLIF(TRIM(prefecture), ''), 'unknown') AS prefecture,
            COUNT(*) AS registrant_count,
            'pdl_v1.0' AS license
          FROM invoice_registrants
      GROUP BY COALESCE(NULLIF(TRIM(prefecture), ''), 'unknown')
        HAVING COUNT(*) >= {MIN_K}
      ORDER BY prefecture
        """,
        license="pdl_v1.0",
        attribution=(
            "Source: National Tax Agency Qualified Invoice Issuer Publication Site (NTA)"
        ),
        transformation_note=(
            "Aggregated by prefecture by Bookyou Inc.; cells below k=5 are not exported."
        ),
    ),
    AggregateExportDefinition(
        dataset="enforcement_cases_by_ministry",
        filename="enforcement_cases_by_ministry",
        count_column="enforcement_count",
        query=f"""
        SELECT
            COALESCE(NULLIF(TRIM(ministry), ''), 'unknown') AS ministry,
            COUNT(*) AS enforcement_count,
            'gov_standard_v2.0' AS license
          FROM enforcement_cases
      GROUP BY COALESCE(NULLIF(TRIM(ministry), ''), 'unknown')
        HAVING COUNT(*) >= {MIN_K}
      ORDER BY ministry
        """,
        license="gov_standard_v2.0",
        attribution="Source: Japanese government ministry enforcement disclosures",
        transformation_note=(
            "Aggregated by ministry by Bookyou Inc.; cells below k=5 are not exported."
        ),
    ),
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_parquet(
    conn: sqlite3.Connection,
    definition: AggregateExportDefinition,
    out_dir: Path,
) -> dict[str, Any]:
    df = pd.read_sql_query(definition.query, conn)
    out_path = out_dir / definition.path_name
    df.to_parquet(out_path, engine="pyarrow", compression="snappy", index=False)
    min_cell = None
    if not df.empty:
        min_cell = int(df[definition.count_column].min())
    return {
        "dataset": definition.dataset,
        "path": definition.path_name,
        "rows": int(len(df)),
        "bytes": out_path.stat().st_size,
        "sha256": _sha256_file(out_path),
        "license": definition.license,
        "min_k": definition.min_k,
        "min_exported_cell_count": min_cell,
        "attribution": definition.attribution,
        "transformation_note": definition.transformation_note,
        "columns": list(df.columns),
    }


def export_safe_aggregates(
    db_path: Path = DEFAULT_DB,
    out_dir: Path = DEFAULT_OUTPUT,
    definitions: tuple[AggregateExportDefinition, ...] = EXPORT_DEFINITIONS,
) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        assert_hf_export_safe(conn, [definition.gate_export() for definition in definitions])
        out_dir.mkdir(parents=True, exist_ok=True)
        datasets = [_write_parquet(conn, definition, out_dir) for definition in definitions]
    finally:
        conn.close()

    manifest: dict[str, Any] = {
        "schema_version": "hf_safe_aggregate_exports.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_db": str(db_path),
        "output_dir": str(out_dir),
        "safety_gate": "scripts/etl/hf_export_safety_gate.py",
        "aggregate_only": True,
        "row_level_sensitive_data_exported": False,
        "datasets": datasets,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    try:
        manifest = export_safe_aggregates(args.db, args.output)
    except (FileNotFoundError, HfExportSafetyError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Source DB:  {args.db}")
    print(f"Output dir: {args.output}")
    for dataset in manifest["datasets"]:
        print(
            f"  {dataset['dataset']:35s} {dataset['rows']:>7,} rows  "
            f"{dataset['bytes']:>10,} bytes  license={dataset['license']}"
        )
    print(f"  {'manifest.json':35s} {len(manifest['datasets']):>7,} datasets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
