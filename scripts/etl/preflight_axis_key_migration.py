#!/usr/bin/env python3
"""Read-only preflight for a future D6 ``am_entity_facts.axis_key`` migration.

This helper does not perform the migration. It opens SQLite in read-only,
query-only mode, reports whether ``axis_key`` already exists, estimates how
``__dupN`` field-name suffixes would map to axis keys, checks duplicate risk
for the proposed unique key, and prints SQL that can be reviewed separately.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "axis_key_preflight_2026-05-01.json"

DUPE_SUFFIX_RE = re.compile(r"^(?P<base>.+)__dup(?P<n>[1-9][0-9]*)$")
PROPOSED_UNIQUE_KEY = (
    "entity_id, field_name, axis_key, COALESCE(field_value_text, '')"
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def axis_base(field_name: str | None) -> str:
    if field_name is None:
        return ""
    match = DUPE_SUFFIX_RE.match(field_name)
    return match.group("base") if match else field_name


def axis_key_from_field(field_name: str | None) -> str:
    if field_name is None:
        return ""
    match = DUPE_SUFFIX_RE.match(field_name)
    return f"dup{match.group('n')}" if match else ""


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.create_function("_axis_base", 1, axis_base, deterministic=True)
    conn.create_function("_axis_key_from_field", 1, axis_key_from_field, deterministic=True)
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")]


def _fetch_dicts(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _proposed_axis_expr(has_axis_key: bool) -> str:
    if has_axis_key:
        return "COALESCE(NULLIF(axis_key, ''), _axis_key_from_field(field_name), '')"
    return "COALESCE(_axis_key_from_field(field_name), '')"


def _count_dup_suffix_rows(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
              FROM am_entity_facts
             WHERE field_name LIKE '%__dup%'
               AND _axis_key_from_field(field_name) != ''
            """
        ).fetchone()[0]
    )


def _top_dup_bases(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    return _fetch_dicts(
        conn,
        """
        SELECT _axis_base(field_name) AS field_name_base,
               COUNT(*) AS rows
          FROM am_entity_facts
         WHERE field_name LIKE '%__dup%'
           AND _axis_key_from_field(field_name) != ''
         GROUP BY field_name_base
         ORDER BY rows DESC, field_name_base
         LIMIT ?
        """,
        (limit,),
    )


def _amount_multi_axis_summary(
    conn: sqlite3.Connection,
    *,
    has_axis_key: bool,
    limit: int = 20,
) -> dict[str, Any]:
    axis_expr = _proposed_axis_expr(has_axis_key)
    grouped_sql = f"""
        WITH proposed AS (
            SELECT entity_id,
                   _axis_base(field_name) AS field_name_base,
                   {axis_expr} AS proposed_axis_key
              FROM am_entity_facts
             WHERE lower(_axis_base(field_name)) LIKE '%amount%'
        ),
        grouped AS (
            SELECT entity_id,
                   field_name_base,
                   COUNT(*) AS rows,
                   COUNT(DISTINCT proposed_axis_key) AS axis_count,
                   group_concat(DISTINCT proposed_axis_key) AS axis_keys
              FROM proposed
             GROUP BY entity_id, field_name_base
            HAVING COUNT(DISTINCT proposed_axis_key) > 1
        )
    """
    totals = conn.execute(
        grouped_sql
        + """
        SELECT COUNT(*) AS group_count,
               COALESCE(SUM(rows), 0) AS row_count
          FROM grouped
        """
    ).fetchone()
    samples = _fetch_dicts(
        conn,
        grouped_sql
        + """
        SELECT entity_id, field_name_base, rows, axis_count, axis_keys
          FROM grouped
         ORDER BY rows DESC, entity_id, field_name_base
         LIMIT ?
        """,
        (limit,),
    )
    return {
        "group_count": int(totals["group_count"]),
        "row_count": int(totals["row_count"]),
        "sample_groups": samples,
    }


def _duplicate_violation_summary(
    conn: sqlite3.Connection,
    *,
    has_axis_key: bool,
    limit: int = 20,
) -> dict[str, Any]:
    if not has_axis_key:
        return {
            "proposed_unique_key": PROPOSED_UNIQUE_KEY,
            "group_count": 0,
            "row_count": 0,
            "sample_groups": [],
            "note": (
                "axis_key is absent; the current unique index on "
                "(entity_id, field_name, COALESCE(field_value_text, '')) plus "
                "strict __dupN-derived axis keys means proposed-key collisions "
                "cannot be introduced by suffix normalization alone."
            ),
        }

    axis_expr = _proposed_axis_expr(has_axis_key)
    grouped_sql = f"""
        WITH proposed AS (
            SELECT entity_id,
                   _axis_base(field_name) AS proposed_field_name,
                   {axis_expr} AS proposed_axis_key,
                   COALESCE(field_value_text, '') AS proposed_value_text,
                   id
              FROM am_entity_facts
             WHERE axis_key != ''
                OR field_name LIKE '%__dup%'
        ),
        grouped AS (
            SELECT entity_id,
                   proposed_field_name,
                   proposed_axis_key,
                   proposed_value_text,
                   COUNT(*) AS rows,
                   MIN(id) AS min_id,
                   MAX(id) AS max_id
              FROM proposed
             GROUP BY entity_id,
                      proposed_field_name,
                      proposed_axis_key,
                      proposed_value_text
            HAVING COUNT(*) > 1
        )
    """
    totals = conn.execute(
        grouped_sql
        + """
        SELECT COUNT(*) AS group_count,
               COALESCE(SUM(rows), 0) AS row_count
          FROM grouped
        """
    ).fetchone()
    samples = _fetch_dicts(
        conn,
        grouped_sql
        + """
        SELECT entity_id,
               proposed_field_name,
               proposed_axis_key,
               proposed_value_text,
               rows,
               min_id,
               max_id
          FROM grouped
         ORDER BY rows DESC, entity_id, proposed_field_name, proposed_axis_key
         LIMIT ?
        """,
        (limit,),
    )
    return {
        "proposed_unique_key": PROPOSED_UNIQUE_KEY,
        "group_count": int(totals["group_count"]),
        "row_count": int(totals["row_count"]),
        "sample_groups": samples,
    }


def _proposed_sql(*, has_axis_key: bool) -> list[str]:
    statements: list[str] = [
        "-- Review this SQL only after duplicate_violations.group_count is 0.",
        "BEGIN IMMEDIATE;",
    ]
    if not has_axis_key:
        statements.append(
            "ALTER TABLE am_entity_facts ADD COLUMN axis_key TEXT NOT NULL DEFAULT '';"
        )
    statements.extend(
        [
            (
                "UPDATE am_entity_facts "
                "SET axis_key = substr(field_name, instr(field_name, '__dup') + 2) "
                "WHERE axis_key = '' "
                "AND field_name GLOB '*__dup[1-9]*';"
            ),
            (
                "UPDATE am_entity_facts "
                "SET field_name = substr(field_name, 1, instr(field_name, '__dup') - 1) "
                "WHERE field_name GLOB '*__dup[1-9]*';"
            ),
            "DROP INDEX IF EXISTS uq_am_facts_entity_field_text;",
            (
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_am_facts_entity_field_axis_text "
                "ON am_entity_facts("
                "entity_id, field_name, axis_key, COALESCE(field_value_text, '')"
                ");"
            ),
            "COMMIT;",
        ]
    )
    return statements


def build_report(db: Path, *, sample_limit: int = 20) -> dict[str, Any]:
    report: dict[str, Any] = {
        "scope": "D6 axis_key migration preflight; read-only report, no live migration",
        "generated_at": _utc_now(),
        "database": str(db),
        "ok": False,
        "issues": [],
    }
    with _connect_readonly(db) as conn:
        if not _table_exists(conn, "am_entity_facts"):
            report["issues"].append("missing_table:am_entity_facts")
            return report

        columns = _table_columns(conn, "am_entity_facts")
        has_axis_key = "axis_key" in columns
        duplicate_violations = _duplicate_violation_summary(
            conn,
            has_axis_key=has_axis_key,
            limit=sample_limit,
        )
        report.update(
            {
                "schema": {
                    "am_entity_facts_columns": columns,
                    "has_axis_key": has_axis_key,
                },
                "counts": {
                    "am_entity_facts_rows": int(
                        conn.execute("SELECT COUNT(*) FROM am_entity_facts").fetchone()[0]
                    ),
                    "dup_suffix_rows": _count_dup_suffix_rows(conn),
                },
                "dup_suffix_top_bases": _top_dup_bases(conn, limit=sample_limit),
                "amount_multi_axis_groups": _amount_multi_axis_summary(
                    conn,
                    has_axis_key=has_axis_key,
                    limit=sample_limit,
                ),
                "duplicate_violations": duplicate_violations,
                "proposed_sql": _proposed_sql(has_axis_key=has_axis_key),
            }
        )

    if duplicate_violations["group_count"]:
        report["issues"].append("duplicate_violations:proposed_unique_key")
    report["ok"] = not report["issues"]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(args.db, sample_limit=args.sample_limit)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"ok={report['ok']}")
        print(f"db={report['database']}")
        print(f"has_axis_key={report.get('schema', {}).get('has_axis_key')}")
        print(f"rows={report.get('counts', {}).get('am_entity_facts_rows')}")
        print(f"dup_suffix_rows={report.get('counts', {}).get('dup_suffix_rows')}")
        print(
            "amount_multi_axis_groups="
            f"{report.get('amount_multi_axis_groups', {}).get('group_count')}"
        )
        print(
            "duplicate_violation_groups="
            f"{report.get('duplicate_violations', {}).get('group_count')}"
        )
        print(f"issues={report['issues']}")
        if args.output:
            print(f"output={args.output}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
