#!/usr/bin/env python3
"""Build a read-only coverage report for the NTA corpus tables.

B10 is an audit helper only. It reads the four NTA corpus tables from SQLite,
summarizes count coverage and metadata quality, and optionally writes the
report to JSON. It never mutates the source database.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "nta_corpus_coverage_2026-05-01.json"


@dataclass(frozen=True)
class CorpusTable:
    name: str
    dimension_column: str
    dimension_label: str


CORPUS_TABLES = (
    CorpusTable("nta_shitsugi", "category", "category"),
    CorpusTable("nta_bunsho_kaitou", "category", "category"),
    CorpusTable("nta_saiketsu", "tax_type", "tax_type"),
    CorpusTable("nta_tsutatsu_index", "law_canonical_id", "tax_type"),
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _present_expr(column: str) -> str:
    return f"SUM(CASE WHEN {column} IS NOT NULL AND TRIM({column}) <> '' THEN 1 ELSE 0 END)"


def _pct(part: int, total: int) -> float:
    if total == 0:
        return 100.0
    return round((part / total) * 100, 2)


def _metadata_completeness(
    conn: sqlite3.Connection,
    table: CorpusTable,
    columns: set[str],
) -> dict[str, Any]:
    total = int(conn.execute(f"SELECT COUNT(*) FROM {table.name}").fetchone()[0])
    source_url_present = 0
    if "source_url" in columns:
        source_url_present = int(
            conn.execute(f"SELECT {_present_expr('source_url')} FROM {table.name}").fetchone()[0]
            or 0
        )

    license_present: int | None = None
    if "license" in columns:
        license_present = int(
            conn.execute(f"SELECT {_present_expr('license')} FROM {table.name}").fetchone()[0]
            or 0
        )

    license_missing = None if license_present is None else total - license_present
    license_present_pct = None if license_present is None else _pct(license_present, total)
    return {
        "total_rows": total,
        "source_url_present": source_url_present,
        "source_url_missing": total - source_url_present,
        "source_url_present_pct": _pct(source_url_present, total),
        "license_present": license_present,
        "license_missing": license_missing,
        "license_present_pct": license_present_pct,
        "license_column_present": "license" in columns,
    }


def _dimension_counts(
    conn: sqlite3.Connection,
    table: CorpusTable,
    columns: set[str],
) -> list[dict[str, Any]]:
    if table.dimension_column not in columns:
        return []
    rows = conn.execute(
        f"""SELECT COALESCE(NULLIF(TRIM({table.dimension_column}), ''), '(missing)') AS bucket,
                  COUNT(*) AS rows
             FROM {table.name}
         GROUP BY bucket
         ORDER BY rows DESC, bucket"""
    ).fetchall()
    return [
        {
            table.dimension_label: str(row["bucket"]),
            "rows": int(row["rows"]),
        }
        for row in rows
    ]


def _duplicate_urls_within_table(
    conn: sqlite3.Connection,
    table: CorpusTable,
    columns: set[str],
) -> tuple[int, list[dict[str, Any]]]:
    if "source_url" not in columns:
        return (0, [])
    count = int(
        conn.execute(
            f"""SELECT COUNT(*)
                  FROM (
                    SELECT 1
                      FROM {table.name}
                     WHERE source_url IS NOT NULL AND TRIM(source_url) <> ''
                  GROUP BY TRIM(source_url)
                    HAVING COUNT(*) > 1
                  )"""
        ).fetchone()[0]
        or 0
    )
    rows = conn.execute(
        f"""SELECT TRIM(source_url) AS source_url, COUNT(*) AS rows
              FROM {table.name}
             WHERE source_url IS NOT NULL AND TRIM(source_url) <> ''
          GROUP BY TRIM(source_url)
            HAVING COUNT(*) > 1
          ORDER BY rows DESC, source_url
             LIMIT 50"""
    ).fetchall()
    return (
        count,
        [
            {"table": table.name, "source_url": str(row["source_url"]), "rows": int(row["rows"])}
            for row in rows
        ],
    )


def _duplicate_urls_across_tables(
    conn: sqlite3.Connection,
    available_tables: list[tuple[CorpusTable, set[str]]],
) -> tuple[int, list[dict[str, Any]]]:
    selects = [
        f"SELECT '{table.name}' AS table_name, TRIM(source_url) AS source_url FROM {table.name} "
        "WHERE source_url IS NOT NULL AND TRIM(source_url) <> ''"
        for table, columns in available_tables
        if "source_url" in columns
    ]
    if not selects:
        return (0, [])
    sql = " UNION ALL ".join(selects)
    count = int(
        conn.execute(
            f"""WITH corpus_urls AS ({sql}),
                     grouped AS (
                        SELECT source_url,
                               COUNT(DISTINCT table_name) AS table_count
                          FROM corpus_urls
                      GROUP BY source_url
                     )
                SELECT COUNT(*) FROM grouped WHERE table_count > 1"""
        ).fetchone()[0]
        or 0
    )
    rows = conn.execute(
        f"""WITH corpus_urls AS ({sql})
            SELECT source_url,
                   COUNT(*) AS rows,
                   COUNT(DISTINCT table_name) AS table_count,
                   GROUP_CONCAT(DISTINCT table_name) AS tables
              FROM corpus_urls
          GROUP BY source_url
            HAVING COUNT(DISTINCT table_name) > 1
          ORDER BY rows DESC, source_url
             LIMIT 50"""
    ).fetchall()
    return (
        count,
        [
            {
                "source_url": str(row["source_url"]),
                "rows": int(row["rows"]),
                "table_count": int(row["table_count"]),
                "tables": str(row["tables"] or "").split(","),
            }
            for row in rows
        ],
    )


def _suggest_next_target(report: dict[str, Any]) -> dict[str, Any]:
    table_reports: dict[str, Any] = report["tables"]
    lowest: tuple[int, str, str] | None = None
    for table, item in table_reports.items():
        for row in item["counts_by_dimension"]:
            dimension_value = next(
                str(value)
                for key, value in row.items()
                if key != "rows"
            )
            candidate = (int(row["rows"]), table, dimension_value)
            if lowest is None or candidate < lowest:
                lowest = candidate
    if lowest is None:
        return {
            "target": "nta_corpus",
            "reason": "no corpus rows found",
            "action": "seed_corpus",
        }
    rows, table, bucket = lowest
    return {
        "target": f"{table}:{bucket}",
        "reason": f"lowest populated category/tax bucket has {rows} rows",
        "action": "expand_lowest_coverage_bucket",
    }


def collect_nta_corpus_coverage(conn: sqlite3.Connection) -> dict[str, Any]:
    """Collect the NTA corpus coverage report without writing to SQLite."""
    table_reports: dict[str, Any] = {}
    available_tables: list[tuple[CorpusTable, set[str]]] = []
    for table in CORPUS_TABLES:
        if not _table_exists(conn, table.name):
            table_reports[table.name] = {
                "exists": False,
                "dimension": table.dimension_label,
                "metadata_completeness": {
                    "total_rows": 0,
                    "source_url_present": 0,
                    "source_url_missing": 0,
                    "source_url_present_pct": 100.0,
                    "license_present": None,
                    "license_missing": None,
                    "license_present_pct": None,
                    "license_column_present": False,
                },
                "counts_by_dimension": [],
                "duplicate_source_url_group_count": 0,
                "duplicate_source_url_groups": [],
            }
            continue

        columns = _columns(conn, table.name)
        available_tables.append((table, columns))
        duplicate_groups = _duplicate_urls_within_table(conn, table, columns)
        table_reports[table.name] = {
            "exists": True,
            "dimension": table.dimension_label,
            "metadata_completeness": _metadata_completeness(conn, table, columns),
            "counts_by_dimension": _dimension_counts(conn, table, columns),
            "duplicate_source_url_group_count": duplicate_groups[0],
            "duplicate_source_url_groups": duplicate_groups[1],
        }

    across_count, across_sample = _duplicate_urls_across_tables(conn, available_tables)
    report: dict[str, Any] = {
        "generated_at": _utc_now(),
        "tables": table_reports,
        "duplicates": {
            "within_table_count": sum(
                int(item.get("duplicate_source_url_group_count", 0))
                for item in table_reports.values()
            ),
            "within_table": [
                row
                for item in table_reports.values()
                for row in item["duplicate_source_url_groups"]
            ],
            "across_table_count": across_count,
            "across_table": across_sample,
        },
    }
    report["totals"] = {
        "rows": sum(
            int(item["metadata_completeness"]["total_rows"]) for item in table_reports.values()
        ),
        "source_url_missing": sum(
            int(item["metadata_completeness"]["source_url_missing"])
            for item in table_reports.values()
        ),
        "license_missing": sum(
            int(item["metadata_completeness"]["license_missing"] or 0)
            for item in table_reports.values()
        ),
    }
    report["suggested_next_target"] = _suggest_next_target(report)
    return report


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with _connect_readonly(args.db) as conn:
        report = collect_nta_corpus_coverage(conn)

    if args.write_report:
        write_report(report, args.output)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"rows={report['totals']['rows']}")
        print(f"source_url_missing={report['totals']['source_url_missing']}")
        print(f"license_missing={report['totals']['license_missing']}")
        print(f"suggested_next_target={report['suggested_next_target']}")
        if args.write_report:
            print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
