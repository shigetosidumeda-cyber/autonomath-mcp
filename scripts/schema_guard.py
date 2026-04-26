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
        MUST NOT contain: programs, api_keys

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
AM_FORBIDDEN = {"programs", "api_keys"}


class SchemaGuardError(RuntimeError):
    """Raised when a DB does not match its declared schema contract."""


def _list_tables(db_path: str) -> set[str]:
    if not Path(db_path).exists():
        raise SchemaGuardError(f"DB file missing: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def _assert(
    db_path: str,
    profile: str,
    required: set[str],
    forbidden: set[str],
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
    if errors:
        raise SchemaGuardError(" | ".join(errors))


def assert_jpintel_schema(db_path: str) -> None:
    """Assert the primary REST/MCP DB has the expected flat schema."""
    _assert(db_path, "jpintel", JPINTEL_REQUIRED, JPINTEL_FORBIDDEN)


def assert_am_schema(db_path: str) -> None:
    """Assert the autonomath EAV+vec DB has the expected am_* schema."""
    _assert(db_path, "autonomath", AM_REQUIRED, AM_FORBIDDEN)


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
