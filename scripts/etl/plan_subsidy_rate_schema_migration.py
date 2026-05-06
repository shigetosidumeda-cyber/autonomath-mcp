#!/usr/bin/env python3
"""Generate a read-only D5 schema migration readiness plan.

The D5 data cleaner keeps ``subsidy_rate`` numeric and preserves original
display strings in ``subsidy_rate_text``. This helper does not migrate either
database. It opens the live SQLite files read-only/query-only, counts current
``subsidy_rate`` type contamination, and emits SQL strings for a reviewed
future migration.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DEFAULT_OUTPUT = (
    REPO_ROOT / "analysis_wave18" / "subsidy_rate_schema_migration_plan_2026-05-01.json"
)

SUBSIDY_RATE_TEXT_COLUMN = "subsidy_rate_text"
CHECK_EXPR = "subsidy_rate IS NULL OR typeof(subsidy_rate) IN ('real', 'integer')"
TEXT_CONTAMINATION_WHERE = (
    "typeof(subsidy_rate) = 'text' "
    "AND subsidy_rate IS NOT NULL "
    "AND TRIM(CAST(subsidy_rate AS TEXT)) != ''"
)
REBUILD_SUFFIX = "__subsidy_rate_check_rebuild"


@dataclass(frozen=True)
class DbTarget:
    label: str
    path: Path
    table_name: str


DEFAULT_TARGETS = (
    DbTarget("jpintel", JPINTEL_DB, "programs"),
    DbTarget("autonomath", AUTONOMATH_DB, "jpi_programs"),
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _fetch_dicts(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_schema WHERE type IN ('table', 'view') AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_sql(conn: sqlite3.Connection, table_name: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return None if row is None else row["sql"]


def _table_columns(conn: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    return _fetch_dicts(conn, f"PRAGMA table_info({_quote_ident(table_name)})")


def _schema_objects(
    conn: sqlite3.Connection,
    table_name: str,
    object_type: str,
) -> list[str]:
    rows = conn.execute(
        """
        SELECT sql
          FROM sqlite_schema
         WHERE tbl_name = ?
           AND type = ?
           AND sql IS NOT NULL
         ORDER BY name
        """,
        (table_name, object_type),
    ).fetchall()
    return [str(row["sql"]).strip().rstrip(";") + ";" for row in rows]


def _column_names(columns: list[dict[str, Any]]) -> list[str]:
    return [str(column["name"]) for column in columns]


def _column_declared_type(columns: list[dict[str, Any]], name: str) -> str | None:
    for column in columns:
        if column["name"] == name:
            return None if column["type"] is None else str(column["type"])
    return None


def _has_numeric_subsidy_rate_check(create_sql: str | None) -> bool:
    if create_sql is None:
        return False
    normalized = re.sub(r"\s+", " ", create_sql).lower()
    return "check" in normalized and "typeof(subsidy_rate)" in normalized


def _target_counts(
    conn: sqlite3.Connection,
    table_name: str,
    *,
    has_subsidy_rate_text: bool,
    sample_limit: int,
) -> dict[str, Any]:
    table = _quote_ident(table_name)
    totals = conn.execute(
        f"""
        SELECT COUNT(*) AS total_rows,
               SUM(CASE WHEN subsidy_rate IS NOT NULL THEN 1 ELSE 0 END)
                   AS subsidy_rate_non_null_rows,
               SUM(CASE WHEN typeof(subsidy_rate) = 'text' THEN 1 ELSE 0 END)
                   AS subsidy_rate_text_type_rows,
               SUM(CASE WHEN {TEXT_CONTAMINATION_WHERE} THEN 1 ELSE 0 END)
                   AS contaminated_subsidy_rate_rows
          FROM {table}
        """
    ).fetchone()
    type_counts = _fetch_dicts(
        conn,
        f"""
        SELECT typeof(subsidy_rate) AS value_type, COUNT(*) AS rows
          FROM {table}
         GROUP BY typeof(subsidy_rate)
         ORDER BY value_type
        """,
    )
    contaminated_values = _fetch_dicts(
        conn,
        f"""
        SELECT CAST(subsidy_rate AS TEXT) AS subsidy_rate_raw, COUNT(*) AS rows
          FROM {table}
         WHERE {TEXT_CONTAMINATION_WHERE}
         GROUP BY CAST(subsidy_rate AS TEXT)
         ORDER BY rows DESC, subsidy_rate_raw
         LIMIT ?
        """,
        (sample_limit,),
    )
    text_column_counts: dict[str, Any]
    if has_subsidy_rate_text:
        text_column_counts = dict(
            conn.execute(
                f"""
                SELECT SUM(CASE WHEN {SUBSIDY_RATE_TEXT_COLUMN} IS NOT NULL THEN 1 ELSE 0 END)
                           AS subsidy_rate_text_non_null_rows,
                       SUM(CASE
                               WHEN {SUBSIDY_RATE_TEXT_COLUMN} IS NOT NULL
                                AND TRIM(CAST({SUBSIDY_RATE_TEXT_COLUMN} AS TEXT)) != ''
                               THEN 1 ELSE 0
                           END) AS subsidy_rate_text_nonblank_rows
                  FROM {table}
                """
            ).fetchone()
        )
    else:
        text_column_counts = {
            "subsidy_rate_text_non_null_rows": None,
            "subsidy_rate_text_nonblank_rows": None,
        }

    return {
        "total_rows": int(totals["total_rows"] or 0),
        "subsidy_rate_non_null_rows": int(totals["subsidy_rate_non_null_rows"] or 0),
        "subsidy_rate_text_type_rows": int(totals["subsidy_rate_text_type_rows"] or 0),
        "contaminated_subsidy_rate_rows": int(totals["contaminated_subsidy_rate_rows"] or 0),
        "subsidy_rate_type_counts": {
            str(row["value_type"]): int(row["rows"]) for row in type_counts
        },
        "contaminated_value_samples": contaminated_values,
        **text_column_counts,
    }


def _replace_create_table_name(create_sql: str, table_name: str, temp_table: str) -> str:
    pattern = re.compile(
        rf"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        rf"(?P<name>{re.escape(table_name)}|{re.escape(_quote_ident(table_name))})\b",
        re.IGNORECASE,
    )
    replacement = f"CREATE TABLE {_quote_ident(temp_table)}"
    replaced, count = pattern.subn(replacement, create_sql.strip().rstrip(";"), count=1)
    if count == 0:
        raise ValueError(f"could not rewrite CREATE TABLE statement for {table_name}")
    return replaced


def _create_table_with_check_sql(
    *,
    create_sql: str,
    table_name: str,
    temp_table: str,
    has_subsidy_rate_text: bool,
    has_numeric_check: bool,
) -> str:
    rewritten = _replace_create_table_name(create_sql, table_name, temp_table)
    insertions: list[str] = []
    if not has_subsidy_rate_text:
        insertions.append(f"{SUBSIDY_RATE_TEXT_COLUMN} TEXT")
    if not has_numeric_check:
        insertions.append(f"CHECK ({CHECK_EXPR})")
    if not insertions:
        return rewritten + ";"

    close_idx = rewritten.rfind(")")
    if close_idx == -1:
        raise ValueError(f"could not locate closing parenthesis for {table_name}")
    prefix = rewritten[:close_idx].rstrip()
    suffix = rewritten[close_idx:]
    return prefix + ",\n    " + ",\n    ".join(insertions) + suffix + ";"


def _copy_expression(column: str, *, has_subsidy_rate_text: bool) -> str:
    if column != SUBSIDY_RATE_TEXT_COLUMN:
        return _quote_ident(column)
    if has_subsidy_rate_text:
        return (
            "CASE "
            f"WHEN {SUBSIDY_RATE_TEXT_COLUMN} IS NOT NULL THEN {SUBSIDY_RATE_TEXT_COLUMN} "
            f"WHEN {TEXT_CONTAMINATION_WHERE} THEN CAST(subsidy_rate AS TEXT) "
            "ELSE NULL END AS subsidy_rate_text"
        )
    return (
        "CASE "
        f"WHEN {TEXT_CONTAMINATION_WHERE} THEN CAST(subsidy_rate AS TEXT) "
        "ELSE NULL END AS subsidy_rate_text"
    )


def _insert_copy_sql(
    table_name: str,
    temp_table: str,
    columns: list[str],
    *,
    has_subsidy_rate_text: bool,
) -> str:
    target_columns = list(columns)
    if not has_subsidy_rate_text:
        target_columns.append(SUBSIDY_RATE_TEXT_COLUMN)
    column_sql = ", ".join(_quote_ident(column) for column in target_columns)
    expression_sql = ",\n       ".join(
        _copy_expression(column, has_subsidy_rate_text=has_subsidy_rate_text)
        for column in target_columns
    )
    return (
        f"INSERT INTO {_quote_ident(temp_table)} ({column_sql})\n"
        f"SELECT {expression_sql}\n"
        f"  FROM {_quote_ident(table_name)};"
    )


def _additive_sql(table_name: str, *, has_subsidy_rate_text: bool) -> list[str]:
    table = _quote_ident(table_name)
    statements = [
        "-- Phase 1: additive text column and raw-display preservation.",
        "BEGIN IMMEDIATE;",
    ]
    if has_subsidy_rate_text:
        statements.append(
            f"-- {table_name}.{SUBSIDY_RATE_TEXT_COLUMN} already exists; no ADD COLUMN needed."
        )
    else:
        statements.append(f"ALTER TABLE {table} ADD COLUMN {SUBSIDY_RATE_TEXT_COLUMN} TEXT;")
    statements.extend(
        [
            (
                f"UPDATE {table}\n"
                f"   SET {SUBSIDY_RATE_TEXT_COLUMN} = CAST(subsidy_rate AS TEXT)\n"
                f" WHERE {SUBSIDY_RATE_TEXT_COLUMN} IS NULL\n"
                f"   AND {TEXT_CONTAMINATION_WHERE};"
            ),
            (
                "-- After this preservation step, run the reviewed D5 data cleanup "
                "to convert subsidy_rate text values to REAL/NULL before Phase 2."
            ),
            "COMMIT;",
        ]
    )
    return statements


def _rebuild_check_sql(
    *,
    table_name: str,
    columns: list[str],
    create_sql: str,
    indexes: list[str],
    triggers: list[str],
    has_subsidy_rate_text: bool,
    has_numeric_check: bool,
) -> list[str]:
    temp_table = table_name + REBUILD_SUFFIX
    table = _quote_ident(table_name)
    temp = _quote_ident(temp_table)
    statements = [
        "-- Phase 2: SQLite cannot ALTER an existing table to add this CHECK.",
        "-- Run only after the guard SELECT below returns 0 rows.",
        (
            f"SELECT COUNT(*) AS blocking_subsidy_rate_text_rows\n"
            f"  FROM {table}\n"
            f" WHERE {TEXT_CONTAMINATION_WHERE};"
        ),
        "PRAGMA foreign_keys = OFF;",
        "BEGIN IMMEDIATE;",
        f"DROP TABLE IF EXISTS {temp};",
        _create_table_with_check_sql(
            create_sql=create_sql,
            table_name=table_name,
            temp_table=temp_table,
            has_subsidy_rate_text=has_subsidy_rate_text,
            has_numeric_check=has_numeric_check,
        ),
        _insert_copy_sql(
            table_name,
            temp_table,
            columns,
            has_subsidy_rate_text=has_subsidy_rate_text,
        ),
        f"DROP TABLE {table};",
        f"ALTER TABLE {temp} RENAME TO {table};",
    ]
    statements.extend(indexes)
    statements.extend(triggers)
    statements.extend(["PRAGMA foreign_key_check;", "COMMIT;", "PRAGMA foreign_keys = ON;"])
    return statements


def _rollback_sql(table_name: str, *, has_subsidy_rate_text: bool) -> list[str]:
    table = _quote_ident(table_name)
    statements = [
        "-- Rollback preference: restore the pre-migration SQLite backup/snapshot.",
        "-- Removing the CHECK constraint requires another rebuild-table migration.",
    ]
    if has_subsidy_rate_text:
        statements.append(
            "-- subsidy_rate_text already exists in the inspected schema; do not drop it "
            "unless this migration was the change that added it."
        )
    statements.extend(
        [
            "-- If only the additive column was applied and SQLite >= 3.35 is confirmed:",
            f"ALTER TABLE {table} DROP COLUMN {SUBSIDY_RATE_TEXT_COLUMN};",
        ]
    )
    return statements


def _target_plan(
    conn: sqlite3.Connection,
    target: DbTarget,
    *,
    sample_limit: int,
) -> dict[str, Any]:
    if not _table_exists(conn, target.table_name):
        return {
            "target": {
                "label": target.label,
                "db_path": str(target.path),
                "table_name": target.table_name,
            },
            "ok": False,
            "issues": [f"missing_table:{target.table_name}"],
        }

    columns = _table_columns(conn, target.table_name)
    column_names = _column_names(columns)
    create_sql = _table_sql(conn, target.table_name)
    if "subsidy_rate" not in column_names or create_sql is None:
        return {
            "target": {
                "label": target.label,
                "db_path": str(target.path),
                "table_name": target.table_name,
            },
            "ok": False,
            "schema": {
                "columns": column_names,
                "has_subsidy_rate": "subsidy_rate" in column_names,
                "has_subsidy_rate_text": SUBSIDY_RATE_TEXT_COLUMN in column_names,
            },
            "issues": ["missing_column:subsidy_rate"],
        }

    has_subsidy_rate_text = SUBSIDY_RATE_TEXT_COLUMN in column_names
    has_numeric_check = _has_numeric_subsidy_rate_check(create_sql)
    counts = _target_counts(
        conn,
        target.table_name,
        has_subsidy_rate_text=has_subsidy_rate_text,
        sample_limit=sample_limit,
    )
    indexes = _schema_objects(conn, target.table_name, "index")
    triggers = _schema_objects(conn, target.table_name, "trigger")
    ready_for_check_rebuild = counts["contaminated_subsidy_rate_rows"] == 0
    issues: list[str] = []
    if not ready_for_check_rebuild:
        issues.append("blocking_text_contamination:subsidy_rate")

    return {
        "target": {
            "label": target.label,
            "db_path": str(target.path),
            "table_name": target.table_name,
        },
        "ok": not issues,
        "issues": issues,
        "schema": {
            "columns": column_names,
            "subsidy_rate_declared_type": _column_declared_type(columns, "subsidy_rate"),
            "has_subsidy_rate_text": has_subsidy_rate_text,
            "has_numeric_subsidy_rate_check": has_numeric_check,
            "index_count": len(indexes),
            "trigger_count": len(triggers),
        },
        "counts": counts,
        "readiness": {
            "needs_subsidy_rate_text_column": not has_subsidy_rate_text,
            "needs_numeric_check_rebuild": not has_numeric_check,
            "ready_for_check_rebuild": ready_for_check_rebuild,
        },
        "data_preservation_sql": _additive_sql(
            target.table_name,
            has_subsidy_rate_text=has_subsidy_rate_text,
        ),
        "check_rebuild_sql": _rebuild_check_sql(
            table_name=target.table_name,
            columns=column_names,
            create_sql=create_sql,
            indexes=indexes,
            triggers=triggers,
            has_subsidy_rate_text=has_subsidy_rate_text,
            has_numeric_check=has_numeric_check,
        ),
        "rollback_sql": _rollback_sql(
            target.table_name,
            has_subsidy_rate_text=has_subsidy_rate_text,
        ),
    }


def build_plan(targets: list[DbTarget], *, sample_limit: int = 20) -> dict[str, Any]:
    target_plans: list[dict[str, Any]] = []
    sqlite_versions: dict[str, str] = {}
    for target in targets:
        with _connect_readonly(target.path) as conn:
            sqlite_versions[target.label] = str(
                conn.execute("SELECT sqlite_version()").fetchone()[0]
            )
            target_plans.append(_target_plan(conn, target, sample_limit=sample_limit))

    total_rows = sum(plan.get("counts", {}).get("total_rows", 0) for plan in target_plans)
    contaminated_rows = sum(
        plan.get("counts", {}).get("contaminated_subsidy_rate_rows", 0) for plan in target_plans
    )
    missing_text_targets = sum(
        1
        for plan in target_plans
        if plan.get("readiness", {}).get("needs_subsidy_rate_text_column")
    )
    plans_with_issues = [plan for plan in target_plans if plan.get("issues")]
    return {
        "scope": (
            "D5 subsidy_rate numeric/text split migration readiness; "
            "read-only report, no live migration"
        ),
        "generated_at": _utc_now(),
        "ok": not plans_with_issues,
        "sqlite_versions": sqlite_versions,
        "summary_counts": {
            "target_count": len(target_plans),
            "total_rows": int(total_rows),
            "contaminated_subsidy_rate_rows": int(contaminated_rows),
            "targets_missing_subsidy_rate_text": missing_text_targets,
            "targets_with_issues": len(plans_with_issues),
        },
        "targets": target_plans,
    }


def _targets_from_args(args: argparse.Namespace) -> list[DbTarget]:
    targets = [
        DbTarget("jpintel", args.jpintel_db, "programs"),
        DbTarget("autonomath", args.autonomath_db, "jpi_programs"),
    ]
    if args.only:
        wanted = set(args.only)
        targets = [target for target in targets if target.label in wanted]
    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jpintel-db", type=Path, default=JPINTEL_DB)
    parser.add_argument("--autonomath-db", type=Path, default=AUTONOMATH_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument(
        "--only",
        action="append",
        choices=("jpintel", "autonomath"),
        help="Limit to one target; may be passed more than once.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    plan = build_plan(_targets_from_args(args), sample_limit=args.sample_limit)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"ok={plan['ok']}")
        print(f"targets={plan['summary_counts']['target_count']}")
        print(
            "contaminated_subsidy_rate_rows="
            f"{plan['summary_counts']['contaminated_subsidy_rate_rows']}"
        )
        print(
            "targets_missing_subsidy_rate_text="
            f"{plan['summary_counts']['targets_missing_subsidy_rate_text']}"
        )
        if args.output:
            print(f"output={args.output}")
    return 0 if plan["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
