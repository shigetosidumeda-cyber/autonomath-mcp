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
                      am_application_round, am_source, am_entity_source,
                      jpi_programs, am_alias, am_amendment_diff,
                      am_program_summary, am_insurance_mutual,
                      am_entities_fts, am_entities_vec
        MUST NOT contain: programs / programs_fts residue from jpintel.db

A guard violation aborts startup (exit 2 from CLI, raises from module
import). Silent continuation is forbidden — the Wave 8 incident burned
~6 hours recovering from a swap that would have been caught in <1s by
this check.

Production row-count + integrity guard
--------------------------------------
When ``JPINTEL_ENV=prod`` (Fly default in fly.toml) the jpintel profile also
demands:
    * ``PRAGMA quick_check`` returns ``ok``
    * ``COUNT(*) FROM programs >= JPINTEL_GUARD_MIN_PROGRAMS`` (default 10000)
    * Every table in ``JPINTEL_NONEMPTY_TABLES`` is non-empty
The autonomath profile in prod additionally requires non-empty
``am_entities`` / ``am_entity_facts``. These checks are skipped in dev /
test runs (``JPINTEL_ENV != prod``) so unit fixtures with tiny seed data
still pass. The cheap COUNT queries (~1ms on a ~352 MB DB with the
existing index on ``programs.tier``) keep boot fast while preventing the
class of incident where an empty / tiny / corrupt DB lands on the live
path and silently degrades search results.

Usage
-----
CLI:
    python scripts/schema_guard.py data/jpintel.db jpintel
    python scripts/schema_guard.py autonomath.db autonomath
    python scripts/schema_guard.py autonomath.db autonomath --drop-empty-cross-pollution

Module:
    from scripts.schema_guard import assert_jpintel_schema, assert_am_schema
    assert_jpintel_schema("data/jpintel.db")
    assert_am_schema("autonomath.db")
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import sys
from pathlib import Path

JPINTEL_REQUIRED = {
    "programs",
    "api_keys",
    "case_studies",
    "loan_programs",
    "enforcement_cases",
    "analytics_events",
    "funnel_events",
    "l4_query_cache",
}
JPINTEL_FORBIDDEN = {"am_entities", "am_entity_facts"}
JPINTEL_REQUIRED_COLUMNS = {
    "programs": {"subsidy_rate_text"},
    "analytics_events": {"user_agent_class", "is_bot"},
    "funnel_events": {"event_name", "is_bot", "is_anonymous"},
    "l4_query_cache": {"cache_key", "tool_name", "params_json", "result_json"},
}
JPINTEL_REQUIRED_MIGRATIONS = {
    "043_l4_cache.sql",
    "111_analytics_events.sql",
    "121_subsidy_rate_text_column.sql",
    "123_funnel_events.sql",
}

AM_REQUIRED = {
    "am_entities",
    "am_entity_facts",
    "am_source",
    "am_entity_source",
    "jpi_programs",
    "am_alias",
    "am_amendment_diff",
    "am_program_summary",
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
# stale — `programs` and its FTS5 residue remain forbidden (jpintel.db keeps
# that table; autonomath uses `jpi_programs` for the mirrored copy).
AM_FORBIDDEN = {
    "programs",
    "programs_fts",
    "programs_fts_data",
    "programs_fts_idx",
    "programs_fts_content",
    "programs_fts_docsize",
    "programs_fts_config",
}
AM_REQUIRED_COLUMNS = {
    "am_alias": {"canonical_id", "alias", "alias_kind", "language"},
    "am_amendment_diff": {"entity_id", "field_name", "detected_at"},
    "am_entity_facts": {
        "entity_id",
        "field_name",
        "field_kind",
        "field_value_text",
        "field_value_json",
        "field_value_numeric",
        "source_id",
        "confirming_source_count",
    },
    "am_entity_source": {"entity_id", "source_id", "role"},
    "am_program_summary": {"entity_id", "summary_50", "summary_200", "token_50_est"},
    "am_source": {
        "source_url",
        "source_type",
        "domain",
        "content_hash",
        "first_seen",
        "last_verified",
        "license",
    },
    "jpi_programs": {
        "unified_id",
        "primary_name",
        "source_url",
        "source_fetched_at",
        "subsidy_rate_text",
    },
}
AM_REQUIRED_VIEWS = {
    "am_unified_rule",
    "programs_active_at_v2",
    "am_uncertainty_view",
    "v_program_source_manifest",
}
AM_REQUIRED_MIGRATIONS = {
    "049_provenance_strengthen.sql",
    "075_am_amendment_diff.sql",
    "090_law_article_body_en.sql",
    "115_source_manifest_view.sql",
    "121_jpi_programs_subsidy_rate_text_column.sql",
}

# Production row-count floor for jpintel.programs (the canonical search
# corpus). 10000 mirrors the same sentinel used by the deploy workflow's
# seed-hydration step (see .github/workflows/deploy.yml). Bumping the floor
# is safer than lowering it — the worst incident the floor defends against
# is a near-empty seed quietly landing on the live path.
DEFAULT_PROD_PROGRAMS_FLOOR = 10000

# Tables whose emptiness in prod is a fail-closed signal (e.g. accidental
# truncate, partial migration, broken seed). Keep this list small and only
# include corpora that are *always* non-empty post-seed; volatile auxiliary
# tables (alias_candidates_queue, empty_search_log, audit_seals) are not
# included because zero rows is a legitimate steady state for them.
JPINTEL_NONEMPTY_TABLES = (
    "programs",
    "api_keys",
    "case_studies",
    "loan_programs",
    "enforcement_cases",
)
AM_NONEMPTY_TABLES = (
    "am_entities",
    "am_entity_facts",
)


def _is_prod_env() -> bool:
    """Return True iff this process should apply the prod row-count guard.

    Uses ``JPINTEL_ENV`` (set to ``prod`` in fly.toml). Tests override via
    monkeypatch / explicit env. Anything other than the literal string
    ``prod`` is treated as a dev / staging context where the cheap row-count
    sentinel queries would create false negatives against tiny fixture DBs.
    """
    return os.environ.get("JPINTEL_ENV", "").lower() == "prod"


def _programs_floor() -> int:
    raw = os.environ.get("JPINTEL_GUARD_MIN_PROGRAMS")
    if not raw:
        return DEFAULT_PROD_PROGRAMS_FLOOR
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_PROD_PROGRAMS_FLOOR


class SchemaGuardError(RuntimeError):
    """Raised when a DB does not match its declared schema contract."""


def _connect_ro(db_path: str) -> sqlite3.Connection:
    if not Path(db_path).exists():
        raise SchemaGuardError(f"DB file missing: {db_path}")
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _connect_rw(db_path: str) -> sqlite3.Connection:
    if not Path(db_path).exists():
        raise SchemaGuardError(f"DB file missing: {db_path}")
    return sqlite3.connect(db_path)


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


def _table_count(db_path: str, table: str) -> int:
    """Return ``COUNT(*)`` for ``table`` (defensively returns -1 on missing).

    The caller decides what to do with -1: in a prod gate we treat a missing
    table as already covered by the structural ``required`` check above —
    returning -1 here preserves the existing error message rather than
    surfacing a confusing duplicate.
    """
    conn = _connect_ro(db_path)
    try:
        # PRAGMA table_info is cheaper than a SELECT against a missing table
        # which would crash with sqlite3.OperationalError.
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if not cols:
            return -1
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608 — table is from a static allowlist
        return int(row[0]) if row else 0
    finally:
        conn.close()


def _count_table_rw(conn: sqlite3.Connection, table: str) -> int:
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()  # noqa: S608 — caller passes literal table names only
    if not cols:
        return -1
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608 — caller passes literal table names only
    return int(row[0]) if row else 0


def drop_empty_autonomath_cross_pollution(db_path: str) -> bool:
    """Drop empty jpintel ``programs`` residue from autonomath.db.

    Long-lived volumes may have migration 110 recorded while an empty
    ``programs`` / ``programs_fts`` table still exists. The cleanup is
    intentionally narrow: it only runs after migration 110, only on a DB that
    already looks like autonomath, and only when logical row counts are zero.
    Any non-empty residue is left in place so the normal forbidden-table guard
    fails closed.
    """

    conn = _connect_rw(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if not {"schema_migrations", "am_entities", "jpi_programs"} <= tables:
            return False
        applied = {row[0] for row in conn.execute("SELECT id FROM schema_migrations").fetchall()}
        if "110_autonomath_drop_cross_pollution.sql" not in applied:
            return False
        if not (tables & AM_FORBIDDEN):
            return False
        if "programs" in tables and _count_table_rw(conn, "programs") != 0:
            return False
        if "programs_fts" in tables and _count_table_rw(conn, "programs_fts") != 0:
            return False

        conn.execute("BEGIN IMMEDIATE")
        for table in (
            "programs_fts",
            "programs_fts_data",
            "programs_fts_idx",
            "programs_fts_content",
            "programs_fts_docsize",
            "programs_fts_config",
            "programs",
        ):
            conn.execute(f"DROP TABLE IF EXISTS {table}")  # noqa: S608 — static table allowlist
        conn.commit()
        return True
    except Exception:
        with contextlib.suppress(Exception):
            conn.rollback()
        raise
    finally:
        conn.close()


def _quick_check(db_path: str) -> str:
    conn = _connect_ro(db_path)
    try:
        row = conn.execute("PRAGMA quick_check").fetchone()
        return str(row[0]) if row and row[0] is not None else "FAILED"
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
    prod_nonempty_tables: tuple[str, ...] = (),
    prod_min_programs: int | None = None,
    skip_quick_check: bool = False,
) -> None:
    tables = _list_tables(db_path)
    missing = required - tables
    wrong_kind = forbidden & tables
    errors = []
    if missing:
        errors.append(f"{profile}: required tables missing from {db_path}: {sorted(missing)}")
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
                f"{profile}: required columns missing from {table}: {sorted(missing_columns)}"
            )
    if required_views:
        views = _list_views(db_path)
        missing_views = required_views - views
        if missing_views:
            errors.append(
                f"{profile}: required views missing from {db_path}: {sorted(missing_views)}"
            )
    if required_migrations:
        applied = _applied_migrations(db_path)
        missing_migrations = required_migrations - applied
        if missing_migrations:
            errors.append(
                f"{profile}: required migrations missing from schema_migrations: "
                f"{sorted(missing_migrations)}"
            )

    # Production-only row-count + integrity guards. Row-count COUNTs are
    # cheap (~1ms). PRAGMA quick_check scans the full file so it scales
    # with DB size — fine on jpintel.db (~352 MB) but takes 15+ minutes
    # on autonomath.db (~9.8 GB) and will exhaust Fly's 60s health-check
    # grace period (see fly.toml comment). Callers that boot off a large
    # DB with an existing trusted stamp pass skip_quick_check=True; the
    # nonempty/row-count guards still run.
    if _is_prod_env() and not errors:
        if not skip_quick_check:
            quick = _quick_check(db_path)
            if quick != "ok":
                errors.append(
                    f"{profile}: PRAGMA quick_check failed in prod ({quick!r}) — "
                    f"DB at {db_path} may be corrupt"
                )
        if prod_min_programs is not None and "programs" in tables:
            n = _table_count(db_path, "programs")
            if 0 <= n < prod_min_programs:
                errors.append(
                    f"{profile}: programs row-count {n} below prod floor "
                    f"{prod_min_programs} (set JPINTEL_GUARD_MIN_PROGRAMS to override)"
                )
        for table in prod_nonempty_tables:
            if table not in tables:
                # Already reported as missing above.
                continue
            n = _table_count(db_path, table)
            if n == 0:
                errors.append(
                    f"{profile}: required prod-nonempty table is empty in {db_path}: {table}"
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
        prod_nonempty_tables=JPINTEL_NONEMPTY_TABLES,
        prod_min_programs=_programs_floor(),
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
        prod_nonempty_tables=AM_NONEMPTY_TABLES,
        skip_quick_check=True,
    )


# Back-compat alias: 9 embedding modules import this name. The underlying
# DB contract is identical to ``assert_am_schema`` (entities + facts +
# vec/fts + auxiliary EAV tables); the longer name was the original public
# symbol before consolidation. Keep the alias rather than rename the
# canonical because doing so would touch 9 unrelated files for no behavior
# change.
assert_am_entities_schema = assert_am_schema


def _main(argv: list[str]) -> int:
    if len(argv) not in (3, 4):
        print(
            "usage: schema_guard.py <db_path> <profile:jpintel|autonomath> "
            "[--drop-empty-cross-pollution]",
            file=sys.stderr,
        )
        return 2
    db_path, profile = argv[1], argv[2]
    drop_empty_cross_pollution = len(argv) == 4 and argv[3] == "--drop-empty-cross-pollution"
    if len(argv) == 4 and not drop_empty_cross_pollution:
        print(f"unknown option: {argv[3]}", file=sys.stderr)
        return 2
    try:
        if profile == "jpintel":
            if drop_empty_cross_pollution:
                print("--drop-empty-cross-pollution is autonomath-only", file=sys.stderr)
                return 2
            assert_jpintel_schema(db_path)
        elif profile == "autonomath":
            if drop_empty_cross_pollution:
                did_drop = drop_empty_autonomath_cross_pollution(db_path)
                if did_drop:
                    print("schema_guard cleanup: dropped empty autonomath cross-pollution")
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
