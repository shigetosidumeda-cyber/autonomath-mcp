"""Schema integrity guard for AutonoMath databases.

Runs at startup to detect the class of failure that caused the Wave 8 DB
swap incident (2026-04-24, repo `/tmp/autonomath_infra_2026-04-24/`):
another process writing a `programs`-schema DB to the `autonomath.db`
path, or vice versa, silently corrupting query behaviour.

Two databases, two schema contracts — neither may be substituted for the
other, even accidentally.

    data/jpintel.db
        MUST contain: programs, api_keys, case_studies, loan_programs,
                      enforcement_cases, laws, tax_rulesets,
                      invoice_registrants
        MUST NOT contain: am_entities, am_entity_facts

    autonomath.db
        MUST contain: am_entities, am_entity_facts, am_amount_condition,
                      am_relation, am_authority, am_region, am_tax_rule,
                      am_loan_product, am_acceptance_stat,
                      am_application_round, am_insurance_mutual,
                      am_entities_fts, am_entities_vec
        MUST NOT contain: programs

A guard violation aborts startup (exit 2 from CLI, raises from module
import). Silent continuation is forbidden — the Wave 8 incident burned
~6 hours recovering from a swap that would have been caught in <1s by
this check.

Usage
-----
CLI:
    python scripts/schema_guard.py data/jpintel.db jpintel
    python scripts/schema_guard.py autonomath.db autonomath

Module:
    from scripts.schema_guard import assert_jpintel_schema, assert_am_schema
    assert_jpintel_schema("data/jpintel.db")
    assert_am_schema("autonomath.db")
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

JPINTEL_REQUIRED = {
    "programs",
    "api_keys",
    "case_studies",
    "loan_programs",
    "enforcement_cases",
}
JPINTEL_FORBIDDEN = {"am_entities", "am_entity_facts"}
JPINTEL_REQUIRED_COLUMNS = {
    "programs": {"subsidy_rate_text"},
}
JPINTEL_REQUIRED_MIGRATIONS = {
    "121_subsidy_rate_text_column.sql",
}

AM_REQUIRED = {
    "am_entities",
    "am_entity_facts",
    "am_amount_condition",
    "am_relation",
    "am_authority",
    "am_region",
    "am_tax_rule",
    "am_loan_product",
    "am_acceptance_stat",
    "am_application_round",
}
# Migration 032 (2026-04-25) intentionally merged jpintel.db tables into
# autonomath.db as the unified primary DB. `api_keys` lives directly at the
# top-level (not jpi-namespaced) so REST/MCP can read quota/auth from a
# single connection. The pre-merge "api_keys means a swap happened" rule is
# stale — only `programs` remains forbidden (jpintel.db keeps that table;
# autonomath uses `jpi_programs` for the mirrored copy).
AM_FORBIDDEN = {"programs"}
AM_REQUIRED_COLUMNS = {
    "jpi_programs": {"subsidy_rate_text"},
}
AM_REQUIRED_VIEWS = {
    "am_unified_rule",
    "programs_active_at_v2",
    "am_uncertainty_view",
    "v_program_source_manifest",
}
AM_REQUIRED_MIGRATIONS = {
    "121_jpi_programs_subsidy_rate_text_column.sql",
}


class SchemaGuardError(RuntimeError):
    """Raised when a DB does not match its declared schema contract."""


def _connect_ro(db_path: str) -> sqlite3.Connection:
    if not Path(db_path).exists():
        raise SchemaGuardError(f"DB file missing: {db_path}")
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _list_objects(db_path: str, object_type: str) -> set[str]:
    conn = _connect_ro(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type=?", (object_type,)
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def _list_tables(db_path: str) -> set[str]:
    return _list_objects(db_path, "table")


def _list_views(db_path: str) -> set[str]:
    return _list_objects(db_path, "view")


def _table_columns(db_path: str, table: str) -> set[str]:
    conn = _connect_ro(db_path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def _applied_migrations(db_path: str) -> set[str]:
    conn = _connect_ro(db_path)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if not exists:
            return set()
        rows = conn.execute("SELECT id FROM schema_migrations").fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def _assert(
    db_path: str,
    profile: str,
    required: set[str],
    forbidden: set[str],
    *,
    required_columns: dict[str, set[str]] | None = None,
    required_views: set[str] | None = None,
    required_migrations: set[str] | None = None,
) -> None:
    tables = _list_tables(db_path)
    missing = required - tables
    wrong_kind = forbidden & tables
    errors = []
    if missing:
        errors.append(
            f"{profile}: required tables missing from {db_path}: "
            f"{sorted(missing)}"
        )
    if wrong_kind:
        errors.append(
            f"{profile}: FORBIDDEN tables present in {db_path} "
            f"(Wave 8 swap detected?): {sorted(wrong_kind)}"
        )
    for table, columns in (required_columns or {}).items():
        if table not in tables:
            continue
        present = _table_columns(db_path, table)
        missing_columns = columns - present
        if missing_columns:
            errors.append(
                f"{profile}: required columns missing from {table}: "
                f"{sorted(missing_columns)}"
            )
    if required_views:
        views = _list_views(db_path)
        missing_views = required_views - views
        if missing_views:
            errors.append(
                f"{profile}: required views missing from {db_path}: "
                f"{sorted(missing_views)}"
            )
    if required_migrations:
        applied = _applied_migrations(db_path)
        missing_migrations = required_migrations - applied
        if missing_migrations:
            errors.append(
                f"{profile}: required migrations missing from schema_migrations: "
                f"{sorted(missing_migrations)}"
            )
    if errors:
        raise SchemaGuardError(" | ".join(errors))


def assert_jpintel_schema(db_path: str) -> None:
    """Assert the primary REST/MCP DB has the expected flat schema."""
    _assert(
        db_path,
        "jpintel",
        JPINTEL_REQUIRED,
        JPINTEL_FORBIDDEN,
        required_columns=JPINTEL_REQUIRED_COLUMNS,
        required_migrations=JPINTEL_REQUIRED_MIGRATIONS,
    )


def assert_am_schema(db_path: str) -> None:
    """Assert the autonomath EAV+vec DB has the expected am_* schema."""
    _assert(
        db_path,
        "autonomath",
        AM_REQUIRED,
        AM_FORBIDDEN,
        required_columns=AM_REQUIRED_COLUMNS,
        required_views=AM_REQUIRED_VIEWS,
        required_migrations=AM_REQUIRED_MIGRATIONS,
    )


# Back-compat alias: 9 embedding modules import this name. The underlying
# DB contract is identical to ``assert_am_schema`` (entities + facts +
# vec/fts + auxiliary EAV tables); the longer name was the original public
# symbol before consolidation. Keep the alias rather than rename the
# canonical because doing so would touch 9 unrelated files for no behavior
# change.
assert_am_entities_schema = assert_am_schema


def _main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: schema_guard.py <db_path> <profile:jpintel|autonomath>",
            file=sys.stderr,
        )
        return 2
    db_path, profile = argv[1], argv[2]
    try:
        if profile == "jpintel":
            assert_jpintel_schema(db_path)
        elif profile == "autonomath":
            assert_am_schema(db_path)
        else:
            print(f"unknown profile: {profile}", file=sys.stderr)
            return 2
    except SchemaGuardError as e:
        print(f"schema_guard FAIL: {e}", file=sys.stderr)
        return 2
    print(f"schema_guard OK: {db_path} [{profile}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
