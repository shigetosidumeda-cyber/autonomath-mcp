#!/usr/bin/env python3
"""Generate the D6 ``axis_key`` migration plan without applying it.

The planner consumes the read-only preflight JSON when available, inspects the
local SQLite schema in read-only/query-only mode, and emits reviewable SQL
strings. It never executes DDL or DML against the target database.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_DATE = "2026-05-01"
DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_PREFLIGHT = REPO_ROOT / "analysis_wave18" / f"axis_key_preflight_{REPORT_DATE}.json"
DEFAULT_OUTPUT = (
    REPO_ROOT / "analysis_wave18" / f"axis_key_migration_plan_{REPORT_DATE}.json"
)

AXIS_INDEX_NAME = "uq_am_facts_entity_field_axis_text"
LEGACY_INDEX_NAME = "uq_am_facts_entity_field_text"
PROPOSED_UNIQUE_KEY = [
    "entity_id",
    "field_name",
    "axis_key",
    "COALESCE(field_value_text, '')",
]
REQUIRED_FACT_COLUMNS = {"entity_id", "field_name", "field_value_text"}

NETWORK_FETCH_PERFORMED = False
DB_MUTATION_PERFORMED = False
LIVE_MIGRATION_PERFORMED = False


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _qident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _suffix_expr(field_expr: str = "field_name") -> str:
    return f"substr({field_expr}, instr({field_expr}, '__dup') + length('__dup'))"


def _axis_key_expr(field_expr: str = "field_name") -> str:
    return f"substr({field_expr}, instr({field_expr}, '__dup') + 2)"


def _axis_base_expr(field_expr: str = "field_name") -> str:
    return f"substr({field_expr}, 1, instr({field_expr}, '__dup') - 1)"


def _strict_dup_predicate(field_expr: str = "field_name") -> str:
    suffix = _suffix_expr(field_expr)
    return " AND ".join(
        [
            f"{field_expr} LIKE '%__dup%'",
            f"instr({field_expr}, '__dup') > 1",
            f"{suffix} != ''",
            f"substr({suffix}, 1, 1) BETWEEN '1' AND '9'",
            f"{suffix} NOT GLOB '*[^0-9]*'",
        ]
    )


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row["name"]) for row in conn.execute(f"PRAGMA table_info({_qident(table)})")]


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {_qident(table)}").fetchone()[0])


def _strict_dup_count(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*)
              FROM am_entity_facts
             WHERE {_strict_dup_predicate()}
            """
        ).fetchone()[0]
    )


def _index_details(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for row in conn.execute(f"PRAGMA index_list({_qident(table)})").fetchall():
        name = str(row["name"])
        sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            (name,),
        ).fetchone()
        xinfo = conn.execute(f"PRAGMA index_xinfo({_qident(name)})").fetchall()
        details.append(
            {
                "name": name,
                "unique": bool(row["unique"]),
                "origin": row["origin"],
                "partial": bool(row["partial"]),
                "columns": [
                    xrow["name"]
                    for xrow in xinfo
                    if xrow["key"] and xrow["name"] is not None
                ],
                "has_expression": any(xrow["key"] and xrow["name"] is None for xrow in xinfo),
                "sql": sql_row["sql"] if sql_row else None,
            }
        )
    return details


def inspect_autonomath_schema(db: Path) -> dict[str, Any]:
    """Inspect only the schema and low-cost counts needed for the plan."""
    report: dict[str, Any] = {
        "database": str(db),
        "exists": db.exists(),
        "am_entity_facts": {
            "exists": False,
            "columns": [],
            "has_axis_key": False,
            "row_count": None,
            "strict_dup_suffix_rows": None,
            "indexes": [],
        },
        "errors": [],
    }
    if not db.exists():
        return report

    try:
        with _connect_readonly(db) as conn:
            if not _table_exists(conn, "am_entity_facts"):
                return report
            columns = _table_columns(conn, "am_entity_facts")
            facts = report["am_entity_facts"]
            facts.update(
                {
                    "exists": True,
                    "columns": columns,
                    "has_axis_key": "axis_key" in columns,
                    "row_count": _table_count(conn, "am_entity_facts"),
                    "indexes": _index_details(conn, "am_entity_facts"),
                }
            )
            if "field_name" in columns:
                facts["strict_dup_suffix_rows"] = _strict_dup_count(conn)
    except sqlite3.Error as exc:
        report["errors"].append(f"sqlite:{type(exc).__name__}:{exc}")
    return report


def load_preflight(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _preflight_summary(path: Path, preflight: dict[str, Any] | None) -> dict[str, Any]:
    if preflight is None:
        return {"path": str(path), "present": False}
    duplicate_violations = preflight.get("duplicate_violations")
    return {
        "path": str(path),
        "present": True,
        "ok": preflight.get("ok"),
        "generated_at": preflight.get("generated_at"),
        "issues": list(preflight.get("issues", [])),
        "counts": dict(preflight.get("counts", {})),
        "duplicate_violations": (
            dict(duplicate_violations) if isinstance(duplicate_violations, dict) else None
        ),
        "schema": dict(preflight.get("schema", {})),
    }


def _precheck_queries(*, has_axis_key: bool) -> list[str]:
    strict = _strict_dup_predicate()
    base = _axis_base_expr()
    axis = _axis_key_expr()
    proposed_field = f"CASE WHEN {strict} THEN {base} ELSE field_name END"
    if has_axis_key:
        proposed_axis = (
            "CASE "
            "WHEN COALESCE(axis_key, '') != '' THEN axis_key "
            f"WHEN {strict} THEN {axis} "
            "ELSE '' END"
        )
    else:
        proposed_axis = f"CASE WHEN {strict} THEN {axis} ELSE '' END"

    return [
        "PRAGMA table_info(am_entity_facts);",
        "PRAGMA index_list(am_entity_facts);",
        f"""
        WITH proposed AS (
            SELECT entity_id,
                   {proposed_field} AS proposed_field_name,
                   {proposed_axis} AS proposed_axis_key,
                   COALESCE(field_value_text, '') AS proposed_value_text
              FROM am_entity_facts
        )
        SELECT entity_id,
               proposed_field_name,
               proposed_axis_key,
               proposed_value_text,
               COUNT(*) AS rows
          FROM proposed
         GROUP BY entity_id,
                  proposed_field_name,
                  proposed_axis_key,
                  proposed_value_text
        HAVING COUNT(*) > 1
         ORDER BY rows DESC, entity_id, proposed_field_name, proposed_axis_key
         LIMIT 50;
        """.strip(),
    ]


def _migration_statements(*, has_axis_key: bool) -> list[str]:
    strict = _strict_dup_predicate()
    axis = _axis_key_expr()
    base = _axis_base_expr()
    statements = [
        "BEGIN IMMEDIATE;",
    ]
    if not has_axis_key:
        statements.append(
            "ALTER TABLE am_entity_facts ADD COLUMN axis_key TEXT NOT NULL DEFAULT '';"
        )
    statements.extend(
        [
            f"""
            UPDATE am_entity_facts
               SET axis_key = {axis}
             WHERE axis_key = ''
               AND {strict};
            """.strip(),
            (
                f"CREATE UNIQUE INDEX IF NOT EXISTS {AXIS_INDEX_NAME} "
                "ON am_entity_facts("
                "entity_id, field_name, axis_key, COALESCE(field_value_text, '')"
                ");"
            ),
            f"DROP INDEX IF EXISTS {LEGACY_INDEX_NAME};",
            f"""
            UPDATE am_entity_facts
               SET field_name = {base}
             WHERE {strict};
            """.strip(),
            "COMMIT;",
        ]
    )
    return statements


def _acceptance_queries() -> list[str]:
    strict = _strict_dup_predicate()
    return [
        """
        SELECT COUNT(*) AS axis_key_column_count
          FROM pragma_table_info('am_entity_facts')
         WHERE name = 'axis_key';
        """.strip(),
        f"""
        SELECT COUNT(*) AS remaining_strict_dup_suffix_rows
          FROM am_entity_facts
         WHERE {strict};
        """.strip(),
        f"""
        SELECT COUNT(*) AS axis_unique_index_count
          FROM sqlite_master
         WHERE type = 'index'
           AND name = '{AXIS_INDEX_NAME}';
        """.strip(),
        f"""
        SELECT COUNT(*) AS legacy_unique_index_count
          FROM sqlite_master
         WHERE type = 'index'
           AND name = '{LEGACY_INDEX_NAME}';
        """.strip(),
        """
        SELECT entity_id,
               field_name,
               axis_key,
               COALESCE(field_value_text, '') AS value_text,
               COUNT(*) AS rows
          FROM am_entity_facts
         GROUP BY entity_id, field_name, axis_key, COALESCE(field_value_text, '')
        HAVING COUNT(*) > 1
         ORDER BY rows DESC, entity_id, field_name, axis_key
         LIMIT 50;
        """.strip(),
        "SELECT COUNT(*) AS am_entity_facts_rows FROM am_entity_facts;",
    ]


def _rollback_sql() -> list[str]:
    axis_suffix = "substr(axis_key, length('dup') + 1)"
    strict_axis = " AND ".join(
        [
            "axis_key LIKE 'dup%'",
            f"{axis_suffix} != ''",
            f"substr({axis_suffix}, 1, 1) BETWEEN '1' AND '9'",
            f"{axis_suffix} NOT GLOB '*[^0-9]*'",
        ]
    )
    return [
        "ROLLBACK;",
        "BEGIN IMMEDIATE;",
        (
            "UPDATE am_entity_facts "
            "SET field_name = field_name || '__' || axis_key "
            f"WHERE {strict_axis};"
        ),
        f"DROP INDEX IF EXISTS {AXIS_INDEX_NAME};",
        (
            f"CREATE UNIQUE INDEX IF NOT EXISTS {LEGACY_INDEX_NAME} "
            "ON am_entity_facts(entity_id, field_name, COALESCE(field_value_text, ''));"
        ),
        "COMMIT;",
    ]


def _data_backfill_policy() -> dict[str, Any]:
    strict = _strict_dup_predicate()
    return {
        "mode": "derive_axis_key_from_strict_field_name_suffix_only",
        "included_suffix_pattern": "__dupN where N is a positive base-10 integer",
        "excluded_suffix_examples": ["__dup0", "__dupx", "__dup01", "__dup1_extra"],
        "axis_key_value": "dupN",
        "field_name_value": "field_name with the trailing __dupN suffix removed",
        "selector_sql": f"SELECT id, field_name FROM am_entity_facts WHERE {strict};",
        "overwrite_policy": (
            "Do not overwrite a non-empty axis_key; rows with existing axis_key values "
            "must be reviewed before running the migration SQL."
        ),
    }


def _unique_index_strategy(schema: dict[str, Any]) -> dict[str, Any]:
    facts = schema.get("am_entity_facts", {})
    indexes = facts.get("indexes") or []
    index_names = {index.get("name") for index in indexes}
    return {
        "new_unique_index": AXIS_INDEX_NAME,
        "legacy_unique_index": LEGACY_INDEX_NAME,
        "proposed_unique_key": PROPOSED_UNIQUE_KEY,
        "legacy_index_present": LEGACY_INDEX_NAME in index_names,
        "axis_index_present": AXIS_INDEX_NAME in index_names,
        "sequence": [
            "add axis_key column when absent",
            "backfill axis_key from strict __dupN suffixes while field_name is unchanged",
            "create axis-aware unique index before dropping the legacy unique index",
            "drop legacy unique index",
            "strip strict __dupN suffixes from field_name",
            "run acceptance queries before releasing the migration",
        ],
    }


def _conflict_handling(preflight: dict[str, Any] | None) -> dict[str, Any]:
    duplicate_violations = {}
    if preflight and isinstance(preflight.get("duplicate_violations"), dict):
        duplicate_violations = dict(preflight["duplicate_violations"])
    group_count = int(duplicate_violations.get("group_count") or 0)
    return {
        "migration_gate": "blocked_until_precheck_zero",
        "preflight_duplicate_violation_groups": group_count,
        "if_precheck_returns_rows": [
            "do not run the migration SQL",
            "assign domain-specific axis_key values or merge duplicate facts in a separate plan",
            "rerun preflight and regenerate this plan",
        ],
        "if_existing_axis_key_is_non_empty": (
            "preserve the existing value and review rows where suffix-derived axis_key would differ"
        ),
        "transaction_behavior": (
            "run the migration statements in one transaction; any unique-index or update "
            "failure should roll back the transaction"
        ),
    }


def _rollback_notes(schema: dict[str, Any]) -> list[str]:
    has_axis_key = bool(schema.get("am_entity_facts", {}).get("has_axis_key"))
    notes = [
        "If failure occurs before COMMIT, use ROLLBACK and rerun precheck queries.",
        (
            "After COMMIT, prefer restoring the pre-migration SQLite backup for full "
            "schema reversal."
        ),
        (
            "A forward-compatible rollback can reconstruct __dupN suffixes from non-empty "
            "axis_key values, recreate the legacy unique index, and leave axis_key unused."
        ),
    ]
    if not has_axis_key:
        notes.append(
            "Do not rely on DROP COLUMN for hot rollback; SQLite version support varies."
        )
    return notes


def _build_blockers(
    *,
    preflight_path: Path,
    preflight: dict[str, Any] | None,
    schema: dict[str, Any],
) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    if preflight is None:
        blockers.append(
            {
                "code": "preflight:missing",
                "message": f"preflight report not found: {preflight_path}",
            }
        )
    else:
        for issue in preflight.get("issues", []):
            blockers.append(
                {
                    "code": f"preflight:{issue}",
                    "message": f"preflight issue must be cleared: {issue}",
                }
            )
        if preflight.get("ok") is False and not preflight.get("issues"):
            blockers.append(
                {
                    "code": "preflight:not_ok",
                    "message": "preflight report is not ok but listed no issue details",
                }
            )
        duplicate_violations = preflight.get("duplicate_violations")
        if (
            isinstance(duplicate_violations, dict)
            and int(duplicate_violations.get("group_count") or 0) > 0
        ):
            blockers.append(
                {
                    "code": "preflight:duplicate_violations:proposed_unique_key",
                    "message": "proposed axis-aware unique key has duplicate groups",
                }
            )

    if not schema.get("exists"):
        blockers.append(
            {
                "code": "autonomath_db:missing",
                "message": f"database not found: {schema.get('database')}",
            }
        )
    for error in schema.get("errors", []):
        blockers.append({"code": "schema:inspect_error", "message": str(error)})

    facts = schema.get("am_entity_facts", {})
    if schema.get("exists") and not facts.get("exists"):
        blockers.append(
            {
                "code": "schema:missing_table:am_entity_facts",
                "message": "am_entity_facts table is required for D6",
            }
        )
    columns = set(facts.get("columns") or [])
    missing = sorted(REQUIRED_FACT_COLUMNS - columns)
    if facts.get("exists") and missing:
        blockers.append(
            {
                "code": "schema:missing_required_columns",
                "message": "am_entity_facts missing columns: " + ", ".join(missing),
            }
        )
    return blockers


def build_plan(
    *,
    db: Path = DEFAULT_DB,
    preflight_path: Path = DEFAULT_PREFLIGHT,
) -> dict[str, Any]:
    preflight = load_preflight(preflight_path)
    schema = inspect_autonomath_schema(db)
    facts = schema.get("am_entity_facts", {})
    has_axis_key = bool(facts.get("has_axis_key"))
    blockers = _build_blockers(
        preflight_path=preflight_path,
        preflight=preflight,
        schema=schema,
    )
    precheck_queries = _precheck_queries(has_axis_key=has_axis_key)
    migration_statements = _migration_statements(has_axis_key=has_axis_key)
    acceptance_queries = _acceptance_queries()
    rollback_sql = _rollback_sql()
    rollback_notes = _rollback_notes(schema)
    report_counts = {
        "blocker_count": len(blockers),
        "precheck_query_count": len(precheck_queries),
        "migration_sql_count": len(migration_statements),
        "acceptance_query_count": len(acceptance_queries),
        "rollback_sql_count": len(rollback_sql),
        "rollback_note_count": len(rollback_notes),
        "strict_dup_suffix_rows": facts.get("strict_dup_suffix_rows"),
        "am_entity_facts_rows": facts.get("row_count"),
    }
    return {
        "ok": not blockers,
        "generated_at": _utc_now(),
        "report_date": REPORT_DATE,
        "scope": "D6 axis_key migration plan generator; no live migration",
        "read_mode": {
            "sqlite_readonly": True,
            "sqlite_query_only": True,
            "preflight_json_only": True,
            "network_fetch_performed": NETWORK_FETCH_PERFORMED,
            "db_mutation_performed": DB_MUTATION_PERFORMED,
            "live_migration_performed": LIVE_MIGRATION_PERFORMED,
            "sql_strings_only": True,
        },
        "completion_status": {
            "D6": "plan_only",
            "complete": False,
        },
        "inputs": {
            "autonomath_db": str(db),
            "preflight": str(preflight_path),
        },
        "preflight": _preflight_summary(preflight_path, preflight),
        "schema": schema,
        "data_backfill_policy": _data_backfill_policy(),
        "unique_index_strategy": _unique_index_strategy(schema),
        "conflict_handling": _conflict_handling(preflight),
        "sql": {
            "precheck_queries": precheck_queries,
            "migration_statements": migration_statements,
            "acceptance_queries": acceptance_queries,
            "rollback_statements": rollback_sql,
        },
        "rollback_notes": rollback_notes,
        "blockers": blockers,
        "report_counts": report_counts,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="print the plan only; do not write --output",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    plan = build_plan(db=args.db, preflight_path=args.preflight)
    payload = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True)
    print(payload)
    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 0 if plan["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
