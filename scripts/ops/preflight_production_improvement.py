#!/usr/bin/env python3
"""Read-only P0 production-improvement preflight.

This script checks the database and migration namespace before new 177+
production-improvement migrations are implemented. It does not apply
migrations and does not write to the database.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_MIGRATIONS_DIR = REPO_ROOT / "scripts" / "migrations"

# CI-only escape hatch. The 9.7 GB autonomath.db lives on Fly volumes and is
# never present on a fresh GitHub Actions runner checkout, so the standard
# database existence audit is meaningless there. When this env-var is set,
# missing-DB is downgraded from a hard `database:missing` issue to a
# `skipped:missing_db_in_ci` marker that keeps `ok=True`. Production boot does
# not export this env-var, so the production path is unchanged.
SKIP_MISSING_DB_ENV = "JPCITE_PREFLIGHT_ALLOW_MISSING_DB"


def _skip_missing_db_enabled() -> bool:
    return os.environ.get(SKIP_MISSING_DB_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


REQUIRED_MIGRATIONS = (
    "172_corpus_snapshot.sql",
    "173_artifact.sql",
    "174_source_document.sql",
    "175_extracted_fact.sql",
    "176_source_foundation_domain_tables.sql",
)

REQUIRED_TABLES_BY_MIGRATION = {
    "172_corpus_snapshot.sql": ("corpus_snapshot",),
    "173_artifact.sql": ("artifact",),
    "174_source_document.sql": ("source_document",),
    "175_extracted_fact.sql": ("extracted_fact",),
    "176_source_foundation_domain_tables.sql": (
        "houjin_change_history",
        "houjin_master_refresh_run",
        "am_enforcement_source_index",
        "law_revisions",
        "law_attachment",
        "procurement_award",
    ),
}

CANONICAL_TABLE_PAIRS = (
    ("programs", "jpi_programs"),
    ("invoice_registrants", "jpi_invoice_registrants"),
)

SOURCE_DOCUMENT_REQUIRED_COLUMNS = (
    "source_url",
    "fetched_at",
    "robots_status",
    "tos_note",
    "artifact_id",
    "corpus_snapshot_id",
    "known_gaps_json",
)
SOURCE_DOCUMENT_FORBIDDEN_COLUMNS = (
    "url",
    "source_fetched_at",
    "robots_note",
)

EXPECTED_177_ACTIVE_FILE = "177_psf_p0_identity_ingest_ops.sql"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def connect_readonly(db: Path) -> sqlite3.Connection:
    if not db.exists():
        raise FileNotFoundError(db)
    conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if not table_exists(conn, table):
        return []
    return [
        str(row["name"]) for row in conn.execute(f"PRAGMA table_info({_quote_identifier(table)})")
    ]


def safe_count(conn: sqlite3.Connection, table: str) -> int | None:
    if not table_exists(conn, table):
        return None
    row = conn.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}").fetchone()
    return int(row[0])


def audit_migration_files(migrations_dir: Path) -> dict[str, Any]:
    files = (
        sorted(p.name for p in migrations_dir.glob("177_*.sql")) if migrations_dir.is_dir() else []
    )
    wave_files = (
        sorted(p.name for p in migrations_dir.glob("wave*_177_*.sql"))
        if migrations_dir.is_dir()
        else []
    )
    active_files = [name for name in files if not name.endswith("_rollback.sql")]
    issues: list[str] = []
    if len(active_files) > 1:
        issues.append("migration_files:177_active_collision")
    if active_files and EXPECTED_177_ACTIVE_FILE not in active_files:
        issues.append("migration_files:177_active_unexpected_name")
    return {
        "path": str(migrations_dir),
        "exists": migrations_dir.is_dir(),
        "glob": "177_*.sql",
        "files": files,
        "active_files": active_files,
        "wave_files_ignored": wave_files,
        "expected_active_file": EXPECTED_177_ACTIVE_FILE,
        "issues": issues,
    }


def audit_schema_migrations(conn: sqlite3.Connection) -> dict[str, Any]:
    if not table_exists(conn, "schema_migrations"):
        return {
            "table_exists": False,
            "required": {
                migration_id: {"applied": False, "applied_at": None}
                for migration_id in REQUIRED_MIGRATIONS
            },
            "issues": ["schema_migrations:missing_table"],
        }

    placeholders = ",".join("?" for _ in REQUIRED_MIGRATIONS)
    rows = conn.execute(
        f"""
        SELECT id, applied_at
          FROM schema_migrations
         WHERE id IN ({placeholders})
        """,
        REQUIRED_MIGRATIONS,
    ).fetchall()
    applied_at = {str(row["id"]): row["applied_at"] for row in rows}
    required = {
        migration_id: {
            "applied": migration_id in applied_at,
            "applied_at": applied_at.get(migration_id),
        }
        for migration_id in REQUIRED_MIGRATIONS
    }
    issues = [
        f"schema_migrations:missing:{migration_id}"
        for migration_id, state in required.items()
        if not state["applied"]
    ]
    return {"table_exists": True, "required": required, "issues": issues}


def audit_required_tables(conn: sqlite3.Connection) -> dict[str, Any]:
    by_migration: dict[str, dict[str, bool]] = {}
    issues: list[str] = []
    for migration_id, tables in REQUIRED_TABLES_BY_MIGRATION.items():
        by_migration[migration_id] = {}
        for table in tables:
            exists = table_exists(conn, table)
            by_migration[migration_id][table] = exists
            if not exists:
                issues.append(f"tables:missing:{table}")
    return {"by_migration": by_migration, "issues": issues}


def audit_source_document_contract(conn: sqlite3.Connection) -> dict[str, Any]:
    columns = table_columns(conn, "source_document")
    column_set = set(columns)
    required = {column: column in column_set for column in SOURCE_DOCUMENT_REQUIRED_COLUMNS}
    forbidden = {column: column in column_set for column in SOURCE_DOCUMENT_FORBIDDEN_COLUMNS}
    issues = [
        f"source_document:missing_column:{column}"
        for column, present in required.items()
        if not present
    ]
    issues.extend(
        f"source_document:forbidden_column_present:{column}"
        for column, present in forbidden.items()
        if present
    )
    return {
        "table_exists": table_exists(conn, "source_document"),
        "columns": columns,
        "required_columns": required,
        "forbidden_columns": forbidden,
        "issues": issues,
    }


def audit_canonical_pairs(conn: sqlite3.Connection) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    issues: list[str] = []
    for base_table, jpi_table in CANONICAL_TABLE_PAIRS:
        base_count = safe_count(conn, base_table)
        jpi_count = safe_count(conn, jpi_table)
        state = "unknown"
        if base_count is None or jpi_count is None:
            state = "missing_table"
            if base_count is None:
                issues.append(f"canonical_pair:missing_table:{base_table}")
            if jpi_count is None:
                issues.append(f"canonical_pair:missing_table:{jpi_table}")
        elif base_count == 0 and jpi_count > 0:
            state = "jpi_populated_base_empty"
        elif base_count > 0 and jpi_count == 0:
            state = "base_populated_jpi_empty"
            issues.append(f"canonical_pair:base_populated_jpi_empty:{base_table}:{jpi_table}")
        elif base_count > 0 and jpi_count > 0:
            state = "both_populated"
        else:
            state = "both_empty"
            issues.append(f"canonical_pair:both_empty:{base_table}:{jpi_table}")
        pairs.append(
            {
                "base_table": base_table,
                "jpi_table": jpi_table,
                "base_count": base_count,
                "jpi_count": jpi_count,
                "state": state,
            }
        )
    return {"pairs": pairs, "issues": issues}


def build_report(
    db: Path,
    *,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "scope": "P0-01 production improvement preflight; read-only, no migration apply",
        "generated_at": _utc_now(),
        "database": str(db),
        "migrations_dir": str(migrations_dir),
        "ok": False,
        "issues": [],
    }

    migration_files = audit_migration_files(migrations_dir)
    report["migration_files_177"] = migration_files
    report["issues"].extend(migration_files["issues"])

    try:
        with connect_readonly(db) as conn:
            schema_migrations = audit_schema_migrations(conn)
            required_tables = audit_required_tables(conn)
            source_document = audit_source_document_contract(conn)
            canonical_pairs = audit_canonical_pairs(conn)
    except FileNotFoundError:
        report["database_exists"] = False
        if _skip_missing_db_enabled():
            # CI runner does not (and should not) carry the 9.7 GB autonomath.db
            # — `JPCITE_PREFLIGHT_ALLOW_MISSING_DB=1` declares that the caller
            # accepts a degraded preflight that still considers the run OK.
            report["skipped"] = "missing_db_in_ci"
            report["skip_reason_env"] = SKIP_MISSING_DB_ENV
            report["ok"] = not report["issues"]
            return report
        report["issues"].append("database:missing")
        report["ok"] = False
        return report
    except sqlite3.Error as exc:
        report["database_exists"] = db.exists()
        report["issues"].append(f"database:sqlite_error:{exc}")
        report["ok"] = False
        return report

    report.update(
        {
            "database_exists": True,
            "schema_migrations": schema_migrations,
            "required_tables": required_tables,
            "source_document_contract": source_document,
            "canonical_table_pairs": canonical_pairs,
        }
    )
    for section in (schema_migrations, required_tables, source_document, canonical_pairs):
        report["issues"].extend(section["issues"])
    report["ok"] = not report["issues"]
    return report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--migrations-dir", type=Path, default=DEFAULT_MIGRATIONS_DIR)
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="report issues but exit 0",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_report(args.db, migrations_dir=args.migrations_dir)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")

    if args.json:
        print(payload)
    else:
        print(f"ok={report['ok']}")
        print(f"db={report['database']}")
        if "skipped" in report:
            print(f"skipped={report['skipped']} env={report.get('skip_reason_env', '')}")
        print(f"required_migrations={REQUIRED_MIGRATIONS}")
        print(f"177_active_files={report['migration_files_177']['active_files']}")
        for pair in report.get("canonical_table_pairs", {}).get("pairs", []):
            print(
                "canonical_pair="
                f"{pair['base_table']}:{pair['base_count']} "
                f"{pair['jpi_table']}:{pair['jpi_count']} "
                f"state={pair['state']}"
            )
        print(f"issues={report['issues']}")
        if args.output:
            print(f"output={args.output}")

    if args.warn_only:
        return 0
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
