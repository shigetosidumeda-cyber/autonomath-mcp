#!/usr/bin/env python3
"""Local Hugging Face readiness export for e-Stat statistic facts.

This script does not publish, push, upload, or call external APIs. Full mode
fails closed unless every e-Stat fact has source-complete safe provenance.
Preview mode writes only the source-complete safe subset so B9 provenance
backfill progress can be inspected locally.
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
    BLOCKED_LICENSES,
    HfExport,
    HfExportSafetyError,
    assert_hf_export_safe,
)

DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_OUTPUT = REPO_ROOT / "dist" / "hf-statistics-estat"
DATASET_NAME = "statistics-estat"
ESTAT_SOURCE_TOPIC = "18_estat_industry_distribution"
PARQUET_NAME = "estat_statistics_facts.parquet"
EXPORT_TABLE = "estat_statistics_facts"
SCHEMA_VERSION = "hf_estat_statistics_export.v1"


class F3ReadinessError(RuntimeError):
    """Raised when full F3 readiness cannot be proven."""


@dataclass(frozen=True)
class ExportResult:
    manifest: dict[str, Any]
    parquet_path: Path


def _blocked_license_sql() -> str:
    return ", ".join(f"'{license_name}'" for license_name in sorted(BLOCKED_LICENSES))


def _topic_literal() -> str:
    return ESTAT_SOURCE_TOPIC.replace("'", "''")


def estat_safe_facts_query() -> str:
    """Return the fail-closed query used for both preview and full exports."""
    topic = _topic_literal()
    blocked = _blocked_license_sql()
    return f"""
    SELECT
        f.id AS fact_id,
        f.entity_id AS entity_id,
        e.primary_name AS primary_name,
        e.source_topic AS source_topic,
        e.source_record_index AS source_record_index,
        f.field_name AS field_name,
        f.field_kind AS field_kind,
        f.field_value_text AS field_value_text,
        f.field_value_json AS field_value_json,
        f.field_value_numeric AS field_value_numeric,
        f.unit AS unit,
        f.source_id AS source_id,
        s.source_url AS source_url,
        s.domain AS source_domain,
        s.source_type AS source_type,
        s.license AS license,
        s.first_seen AS source_first_seen,
        s.last_verified AS source_last_verified,
        e.source_url AS entity_source_url,
        e.source_url_domain AS entity_source_domain,
        e.fetched_at AS entity_fetched_at,
        e.confidence AS entity_confidence,
        f.valid_from AS fact_valid_from,
        f.valid_until AS fact_valid_until,
        e.valid_from AS entity_valid_from,
        e.valid_until AS entity_valid_until
      FROM am_entity_facts f
      JOIN am_entities e ON e.canonical_id = f.entity_id
      JOIN am_source s ON s.id = f.source_id
     WHERE e.record_kind = 'statistic'
       AND e.source_topic = '{topic}'
       AND f.source_id IS NOT NULL
       AND NULLIF(TRIM(CAST(s.source_url AS TEXT)), '') IS NOT NULL
       AND NULLIF(TRIM(CAST(s.license AS TEXT)), '') IS NOT NULL
       AND LOWER(TRIM(CAST(s.license AS TEXT))) NOT IN ({blocked})
  ORDER BY f.id
    """


SAFE_FACTS_QUERY = estat_safe_facts_query()
EXPORTS = [HfExport(table=EXPORT_TABLE, query=SAFE_FACTS_QUERY)]


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"DB not found: {path}")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _require_schema(conn: sqlite3.Connection) -> None:
    required = {
        "am_entities": {
            "canonical_id",
            "record_kind",
            "source_topic",
            "source_record_index",
            "primary_name",
            "source_url",
            "source_url_domain",
            "fetched_at",
            "confidence",
            "valid_from",
            "valid_until",
        },
        "am_entity_facts": {
            "id",
            "entity_id",
            "field_name",
            "field_value_text",
            "field_value_json",
            "field_value_numeric",
            "field_kind",
            "unit",
            "source_url",
            "source_id",
            "valid_from",
            "valid_until",
        },
        "am_source": {
            "id",
            "source_url",
            "source_type",
            "domain",
            "first_seen",
            "last_verified",
            "license",
        },
    }
    missing: dict[str, list[str]] = {}
    for table, columns in required.items():
        table_columns = _table_columns(conn, table)
        table_missing = sorted(columns - table_columns)
        if table_missing:
            missing[table] = table_missing
    if missing:
        raise RuntimeError(f"database missing expected e-Stat export columns: {missing}")


def _count_source_completeness(conn: sqlite3.Connection) -> dict[str, Any]:
    blocked = _blocked_license_sql()
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS total_estat_fact_rows,
            SUM(CASE WHEN f.source_id IS NOT NULL THEN 1 ELSE 0 END)
                AS facts_with_source_id,
            SUM(CASE WHEN f.source_id IS NULL THEN 1 ELSE 0 END)
                AS facts_missing_source_id,
            SUM(CASE WHEN f.source_id IS NOT NULL AND s.id IS NULL THEN 1 ELSE 0 END)
                AS facts_with_dangling_source_id,
            SUM(CASE
                    WHEN f.source_id IS NOT NULL
                     AND s.id IS NOT NULL
                     AND NULLIF(TRIM(CAST(s.source_url AS TEXT)), '') IS NOT NULL
                    THEN 1 ELSE 0
                END) AS facts_with_source_url,
            SUM(CASE
                    WHEN f.source_id IS NOT NULL
                     AND s.id IS NOT NULL
                     AND NULLIF(TRIM(CAST(s.source_url AS TEXT)), '') IS NOT NULL
                     AND NULLIF(TRIM(CAST(s.license AS TEXT)), '') IS NOT NULL
                    THEN 1 ELSE 0
                END) AS facts_with_source_url_and_license,
            SUM(CASE
                    WHEN f.source_id IS NOT NULL
                     AND s.id IS NOT NULL
                     AND NULLIF(TRIM(CAST(s.source_url AS TEXT)), '') IS NOT NULL
                     AND NULLIF(TRIM(CAST(s.license AS TEXT)), '') IS NOT NULL
                     AND LOWER(TRIM(CAST(s.license AS TEXT))) NOT IN ({blocked})
                    THEN 1 ELSE 0
                END) AS source_complete_safe_fact_rows,
            SUM(CASE
                    WHEN f.source_id IS NOT NULL
                     AND s.id IS NOT NULL
                     AND LOWER(TRIM(CAST(COALESCE(s.license, '') AS TEXT)))
                         IN ({blocked})
                    THEN 1 ELSE 0
                END) AS blocked_license_fact_rows,
            SUM(CASE
                    WHEN f.source_id IS NOT NULL
                     AND s.id IS NOT NULL
                     AND NULLIF(TRIM(CAST(s.license AS TEXT)), '') IS NULL
                    THEN 1 ELSE 0
                END) AS missing_license_fact_rows,
            SUM(CASE
                    WHEN f.source_id IS NULL
                     AND NULLIF(TRIM(CAST(f.source_url AS TEXT)), '') IS NOT NULL
                    THEN 1 ELSE 0
                END) AS fact_source_url_without_source_id_rows
          FROM am_entity_facts f
          JOIN am_entities e ON e.canonical_id = f.entity_id
          LEFT JOIN am_source s ON s.id = f.source_id
         WHERE e.record_kind = 'statistic'
           AND e.source_topic = ?
        """,
        (ESTAT_SOURCE_TOPIC,),
    ).fetchone()

    counts = {key: int(value or 0) for key, value in dict(row).items()}
    total = counts["total_estat_fact_rows"]
    safe = counts["source_complete_safe_fact_rows"]
    counts["source_complete_safe_ratio"] = round(safe / total, 6) if total else 0.0
    counts["all_facts_source_complete_and_safe"] = bool(total and safe == total)
    counts["b9_provenance_complete"] = bool(
        total
        and counts["facts_with_source_id"] == total
        and counts["facts_with_dangling_source_id"] == 0
    )
    return counts


def _license_counts_for_all_estat_facts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT COALESCE(NULLIF(TRIM(CAST(s.license AS TEXT)), ''), '<MISSING>')
                   AS license_value,
               COUNT(*) AS row_count
          FROM am_entity_facts f
          JOIN am_entities e ON e.canonical_id = f.entity_id
          LEFT JOIN am_source s ON s.id = f.source_id
         WHERE e.record_kind = 'statistic'
           AND e.source_topic = ?
      GROUP BY license_value
      ORDER BY row_count DESC, license_value
        """,
        (ESTAT_SOURCE_TOPIC,),
    ).fetchall()
    return {str(row["license_value"]): int(row["row_count"]) for row in rows}


def _read_safe_facts(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query(SAFE_FACTS_QUERY, conn)
    for column in ("fact_id", "source_record_index", "source_id"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce").astype("Int64")
    for column in ("field_value_numeric", "entity_confidence"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def _license_counts_from_frame(df: pd.DataFrame) -> dict[str, int]:
    if df.empty or "license" not in df.columns:
        return {}
    values = df["license"].dropna().astype(str).value_counts(sort=False)
    return {str(key): int(value) for key, value in sorted(values.items())}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fmt_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _incomplete_reason(completeness: dict[str, Any]) -> str | None:
    total = int(completeness["total_estat_fact_rows"])
    safe = int(completeness["source_complete_safe_fact_rows"])
    if total and safe == total:
        return None
    if not total:
        return "No e-Stat statistic facts were found; full F3 readiness requires rows."
    missing_source = int(completeness["facts_missing_source_id"])
    dangling = int(completeness["facts_with_dangling_source_id"])
    if missing_source or dangling:
        return (
            "B9 e-Stat fact provenance is not 100% complete: "
            f"{safe}/{total} facts have source_url/license-safe provenance; "
            f"{missing_source} facts lack source_id and {dangling} source_id values "
            "do not join am_source."
        )
    blocked = int(completeness["blocked_license_fact_rows"])
    missing_license = int(completeness["missing_license_fact_rows"])
    if blocked or missing_license:
        return (
            "Full F3 gate blocked by source licenses: "
            f"{blocked} facts resolve to blocked licenses and {missing_license} facts "
            "resolve to missing licenses."
        )
    return (
        "Full F3 gate incomplete: not every e-Stat fact has nonblank source_url "
        "and nonblocked license provenance."
    )


def _write_readme(out_dir: Path, manifest: dict[str, Any]) -> None:
    status = (
        "full-ready"
        if manifest["f3_full_publish_ready"]
        else "preview-only; full F3 readiness is incomplete"
    )
    reason = manifest.get("full_f3_gate_incomplete_reason") or "None"
    license_values = ", ".join(manifest["license_values"]) or "none"
    text = f"""---
language:
- ja
pretty_name: Japanese e-Stat Statistics Facts
---

# {DATASET_NAME}

Local export of e-Stat statistic facts from `am_entities` and
`am_entity_facts`, limited to facts that join to an `am_source` row with a
nonblank `source_url` and nonblocked per-row `license`.

- File: `{PARQUET_NAME}`
- Exported rows: {manifest["total_exported_rows"]}
- License values: {license_values}
- Source topic: `{ESTAT_SOURCE_TOPIC}`
- F3 status: {status}
- Incomplete reason: {reason}

This export is generated locally only. The script performs no publish, upload,
push, or external API call.
"""
    (out_dir / "README.md").write_text(text, encoding="utf-8")


def _write_manifest(out_dir: Path, manifest: dict[str, Any]) -> None:
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_export(
    db_path: Path = DEFAULT_DB,
    out_dir: Path = DEFAULT_OUTPUT,
    *,
    preview: bool = False,
) -> ExportResult:
    conn = _connect(db_path)
    try:
        _require_schema(conn)
        completeness = _count_source_completeness(conn)
        f3_ready = bool(completeness["all_facts_source_complete_and_safe"])
        reason = _incomplete_reason(completeness)
        if not preview and not f3_ready:
            raise F3ReadinessError(reason)

        assert_hf_export_safe(conn, EXPORTS)
        df = _read_safe_facts(conn)
        all_license_counts = _license_counts_for_all_estat_facts(conn)
    finally:
        conn.close()

    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / PARQUET_NAME
    df.to_parquet(parquet_path, engine="pyarrow", compression="snappy", index=False)
    parquet_bytes = parquet_path.stat().st_size
    exported_license_counts = _license_counts_from_frame(df)
    exported_rows = int(len(df))
    completeness["exported_rows"] = exported_rows

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset": DATASET_NAME,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "source_db": str(db_path),
        "output_dir": str(out_dir),
        "mode": "preview" if preview else "full",
        "preview_only": bool(preview or not f3_ready),
        "publish_performed": False,
        "safety_gate": "scripts/etl/hf_export_safety_gate.py",
        "safety_gate_status": "passed",
        "source_topic": ESTAT_SOURCE_TOPIC,
        "f3_full_publish_ready": f3_ready,
        "b9_provenance_complete": bool(completeness["b9_provenance_complete"]),
        "full_f3_gate_incomplete_reason": reason,
        "total_exported_rows": exported_rows,
        "source_completeness": completeness,
        "license_values": sorted(exported_license_counts),
        "license_counts": exported_license_counts,
        "all_estat_fact_license_counts": all_license_counts,
        "exports": [
            {
                "table": EXPORT_TABLE,
                "file": PARQUET_NAME,
                "rows": exported_rows,
                "bytes": parquet_bytes,
                "sha256": _sha256_file(parquet_path),
                "license_values": sorted(exported_license_counts),
                "columns": list(df.columns),
            }
        ],
    }
    _write_readme(out_dir, manifest)
    _write_manifest(out_dir, manifest)
    return ExportResult(manifest=manifest, parquet_path=parquet_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"SQLite DB path (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="write only source-complete safe rows even when full F3 readiness fails",
    )
    args = parser.parse_args()

    try:
        result = run_export(args.db, args.output, preview=args.preview)
    except (
        FileNotFoundError,
        F3ReadinessError,
        HfExportSafetyError,
        RuntimeError,
        sqlite3.Error,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    manifest = result.manifest
    export = manifest["exports"][0]
    print(f"Source DB:  {args.db}")
    print(f"Output dir: {args.output}")
    print(f"  {EXPORT_TABLE:28s} {export['rows']:>9,} rows  {_fmt_bytes(export['bytes']):>12s}")
    print("  README.md")
    print("  manifest.json")
    print(
        "F3 status: "
        + ("full-ready" if manifest["f3_full_publish_ready"] else "preview-ready only")
    )
    if manifest.get("full_f3_gate_incomplete_reason"):
        print(f"Reason: {manifest['full_f3_gate_incomplete_reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
