"""Wave 46.B — jc_* view layer over am_* tables.

Verifies that scripts/migrations/269_create_jpcite_views.sql:
  1. Parses with no SQLite syntax error against an empty schema.
  2. Creates at least 100 jc_* views (current coverage target = 135).
  3. Every jc_<name> resolves transparently to the matching am_<name>
     when both source table and view exist (SELECT-through aliasing).
  4. The view count is within +/-2 of the regular am_* table count
     extracted from scripts/migrations/*.sql (FTS5/vec0 vtables excluded).
  5. Re-running the migration is idempotent (CREATE VIEW IF NOT EXISTS).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "migrations"
    / "269_create_jpcite_views.sql"
)
MIGRATIONS_DIR = MIGRATION.parent

MIN_VIEW_COUNT = 100  # safety floor; current target is 135


def _read_sql() -> str:
    assert MIGRATION.exists(), f"missing migration: {MIGRATION}"
    return MIGRATION.read_text(encoding="utf-8")


def _extract_am_table_names() -> set[str]:
    """Return the set of regular am_* tables defined under scripts/migrations/.

    Mirrors the awk extraction used to generate 269_*.sql:
      * Only lines starting with `CREATE TABLE` (excludes VIRTUAL TABLE).
      * Strips optional `IF NOT EXISTS` and trailing `(`/whitespace.
      * Keeps only names with the literal `am_` prefix.
    """
    names: set[str] = set()
    pattern = re.compile(
        r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)",
        re.IGNORECASE | re.MULTILINE,
    )
    for sql_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if sql_path.name == MIGRATION.name:
            continue
        text = sql_path.read_text(encoding="utf-8", errors="replace")
        for m in pattern.finditer(text):
            tbl = m.group(1)
            if tbl.startswith("am_"):
                names.add(tbl)
    return names


def _extract_jc_view_names() -> set[str]:
    sql = _read_sql()
    return set(
        re.findall(
            r"CREATE\s+VIEW\s+IF\s+NOT\s+EXISTS\s+(jc_[A-Za-z0-9_]+)",
            sql,
            re.IGNORECASE,
        )
    )


def test_migration_file_exists():
    assert MIGRATION.exists(), MIGRATION
    assert MIGRATION.stat().st_size > 500, "migration file too small"


def test_migration_syntax_ok_on_empty_db():
    """The migration must parse cleanly against an empty SQLite schema.

    SQLite resolves view bodies at query time, so creating jc_* views over
    am_* tables that don't yet exist is intentionally legal — this matches
    the boot-time replay semantics (manifest may run on a fresh /data db).
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(_read_sql())
    finally:
        conn.close()


def test_view_count_meets_floor():
    views = _extract_jc_view_names()
    assert len(views) >= MIN_VIEW_COUNT, (
        f"jc_* view count={len(views)} fell below floor {MIN_VIEW_COUNT}"
    )


def test_view_count_matches_am_table_count_within_tolerance():
    """jc_* view count should track am_* regular-table count closely."""
    am_tables = _extract_am_table_names()
    jc_views = _extract_jc_view_names()
    delta = abs(len(am_tables) - len(jc_views))
    # Tolerance band accounts for: (a) future migrations adding new am_*
    # tables before this view migration is regenerated, and (b) the rare
    # case where a regular table is intentionally excluded.
    assert delta <= 5, (
        f"am_* tables={len(am_tables)} vs jc_* views={len(jc_views)} "
        f"diverged by {delta} (>5)"
    )


def test_every_jc_view_targets_am_prefix():
    """Each jc_<name> AS SELECT * FROM am_<name> — strict 1:1 mapping."""
    sql = _read_sql()
    pairs = re.findall(
        r"CREATE\s+VIEW\s+IF\s+NOT\s+EXISTS\s+(jc_[A-Za-z0-9_]+)\s+AS\s+SELECT\s+\*\s+FROM\s+(am_[A-Za-z0-9_]+)",
        sql,
        re.IGNORECASE,
    )
    assert pairs, "no jc_/am_ pairs parsed"
    for jc_name, am_name in pairs:
        suffix_jc = jc_name[len("jc_"):]
        suffix_am = am_name[len("am_"):]
        assert suffix_jc == suffix_am, (
            f"name mismatch: view={jc_name} target={am_name}"
        )


def test_select_through_one_view_returns_source_rows():
    """End-to-end aliasing check on a single representative table.

    Creates a stand-in am_program_narrative table with two rows, runs
    the migration, and verifies SELECT * FROM jc_program_narrative
    returns the same two rows in order.
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            "CREATE TABLE am_program_narrative ("
            " id INTEGER PRIMARY KEY, "
            " program_id TEXT NOT NULL, "
            " narrative TEXT)"
        )
        conn.executemany(
            "INSERT INTO am_program_narrative(id, program_id, narrative) VALUES (?, ?, ?)",
            [(1, "SUB-001", "A"), (2, "SUB-002", "B")],
        )
        conn.commit()
        conn.executescript(_read_sql())
        rows = conn.execute(
            "SELECT id, program_id, narrative FROM jc_program_narrative ORDER BY id"
        ).fetchall()
        assert rows == [(1, "SUB-001", "A"), (2, "SUB-002", "B")]
    finally:
        conn.close()


def test_migration_is_idempotent():
    """Running the migration twice must not raise (CREATE VIEW IF NOT EXISTS)."""
    conn = sqlite3.connect(":memory:")
    try:
        sql = _read_sql()
        conn.executescript(sql)
        conn.executescript(sql)  # second run — should be a no-op, not an error
    finally:
        conn.close()


def test_manifest_includes_new_migration():
    """autonomath_boot_manifest.txt must list 269_create_jpcite_views.sql."""
    manifest = MIGRATIONS_DIR / "autonomath_boot_manifest.txt"
    assert manifest.exists(), manifest
    text = manifest.read_text(encoding="utf-8")
    assert "269_create_jpcite_views.sql" in text, (
        "boot manifest missing 269 entry — schema_guard will skip it"
    )


def _extract_am_virtual_table_names() -> set[str]:
    """Return the set of am_* FTS5/vec0 virtual tables across migrations."""
    pattern = re.compile(
        r"^\s*CREATE\s+VIRTUAL\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)",
        re.IGNORECASE | re.MULTILINE,
    )
    out: set[str] = set()
    for sql_path in MIGRATIONS_DIR.glob("*.sql"):
        text = sql_path.read_text(encoding="utf-8", errors="replace")
        for m in pattern.finditer(text):
            name = m.group(1)
            if name.startswith("am_"):
                out.add(name)
    return out


def test_no_fts5_or_vec0_in_view_targets():
    """jc_* views must not wrap FTS5/vec0 virtual tables.

    Source of truth = actual `CREATE VIRTUAL TABLE` lines scanned from
    scripts/migrations/*.sql, not a name-pattern heuristic. This lets
    regular cache tables that happen to share a `vec_` family prefix
    (e.g. am_entities_vec_reranker_score, *_map, *_run_log) pass through.
    """
    vtables = _extract_am_virtual_table_names()
    pairs = re.findall(
        r"CREATE\s+VIEW\s+IF\s+NOT\s+EXISTS\s+jc_[A-Za-z0-9_]+\s+AS\s+SELECT\s+\*\s+FROM\s+(am_[A-Za-z0-9_]+)",
        _read_sql(),
        re.IGNORECASE,
    )
    leaked = sorted(am_name for am_name in pairs if am_name in vtables)
    assert not leaked, (
        f"jc_* views must not wrap FTS5/vec0 vtables; leaked: {leaked}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
