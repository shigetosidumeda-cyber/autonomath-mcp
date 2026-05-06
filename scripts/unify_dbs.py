#!/usr/bin/env python3
# One-shot DB unification: jpintel.db -> autonomath.db with jpi_ prefix.
# Run with --dry-run first. After success, code switches DB_PATH to autonomath.db.
#
# Pre-conditions:
#   - autonomath.db at repo root (8.0 GB, 53 base tables)
#   - data/jpintel.db at 316 MB (80 tables incl FTS shadow)
#   - autonomath.db.bak.pre_unify must NOT exist (safety: we won't overwrite)
# Post-conditions:
#   - autonomath.db gains jpi_<table> for every base table from jpintel.db
#   - all rows preserved, indexes mirrored, FTS shadow tables skipped
#   - identity test: SELECT COUNT(*) per table matches pre-migration
#
# Idempotent: re-running is a no-op (CREATE TABLE will fail; script aborts that table).

import argparse
import shutil
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
JPINTEL = REPO / "data" / "jpintel.db"
AUTONOMATH = REPO / "autonomath.db"
BACKUP = REPO / "autonomath.db.bak.pre_unify"

# Tables we never copy (FTS / vec shadow tables, auxiliary indexes).
SKIP_PATTERNS = (
    "_fts",
    "_vec",
    "_config",
    "_content",
    "_data",
    "_docsize",
    "_idx",
    "_segdir",
    "_segments",
    "_stat",
)

# Names that collide between the two DBs. Map jpi -> renamed inside dst.
# api_keys: jpintel has billing rows (2), autonomath has 0 unused rows.
COLLISION_RENAMES = {
    "api_keys": "jpi_api_keys",
}


def is_skippable(name: str) -> bool:
    if name.startswith("sqlite_"):
        return True
    return any(name.endswith(p) for p in SKIP_PATTERNS)


def list_base_tables(conn: sqlite3.Connection, schema: str = "main") -> list[str]:
    rows = conn.execute(
        f"SELECT name FROM {schema}.sqlite_master "
        f"WHERE type='table' AND sql IS NOT NULL ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows if not is_skippable(r[0])]


def get_table_ddl(conn: sqlite3.Connection, schema: str, table: str) -> str:
    row = conn.execute(
        f"SELECT sql FROM {schema}.sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if not row or not row[0]:
        raise RuntimeError(f"no DDL for {schema}.{table}")
    return row[0]


def get_table_indexes(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    rows = conn.execute(
        f"SELECT sql FROM {schema}.sqlite_master "
        f"WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
        (table,),
    ).fetchall()
    return [r[0] for r in rows]


def rewrite_ddl(ddl: str, old_name: str, new_name: str) -> str:
    # Robust against quoted/unquoted forms. Only the first occurrence (the table name).
    for variant in (
        f'CREATE TABLE IF NOT EXISTS "{old_name}"',
        f"CREATE TABLE IF NOT EXISTS {old_name}",
        f'CREATE TABLE "{old_name}"',
        f"CREATE TABLE {old_name}",
    ):
        if variant in ddl:
            replacement = variant.replace(old_name, new_name).replace('"', "")
            return ddl.replace(variant, replacement, 1)
    raise RuntimeError(f"could not rewrite DDL for {old_name}: {ddl[:100]}")


def rewrite_index(idx_sql: str, old_table: str, new_table: str) -> str:
    return idx_sql.replace(f" ON {old_table}", f" ON {new_table}").replace(
        f' ON "{old_table}"', f" ON {new_table}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only, no writes")
    ap.add_argument("--force", action="store_true", help="overwrite existing backup")
    args = ap.parse_args()

    if not JPINTEL.exists():
        print(f"FATAL: {JPINTEL} not found", file=sys.stderr)
        return 2
    if not AUTONOMATH.exists():
        print(f"FATAL: {AUTONOMATH} not found", file=sys.stderr)
        return 2

    print(f"src: {JPINTEL} ({JPINTEL.stat().st_size / 1e6:.1f} MB)")
    print(f"dst: {AUTONOMATH} ({AUTONOMATH.stat().st_size / 1e9:.2f} GB)")

    # Step 1 — Backup.
    if BACKUP.exists() and not args.force:
        print(f"FATAL: backup {BACKUP} exists. Re-run with --force or remove it.", file=sys.stderr)
        return 2
    if not args.dry_run:
        print(f"copying backup → {BACKUP}")
        shutil.copy2(AUTONOMATH, BACKUP)
    else:
        print(f"[dry-run] would copy → {BACKUP}")

    # Step 2 — Open dst, ATTACH src.
    conn = sqlite3.connect(AUTONOMATH, isolation_level=None, timeout=300)
    conn.execute("PRAGMA busy_timeout = 300000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"ATTACH DATABASE '{JPINTEL}' AS jpi")

    # Step 3 — Enumerate jpintel base tables.
    src_tables = list_base_tables(conn, "jpi")
    print(f"jpintel base tables to copy: {len(src_tables)}")

    # Step 4 — For each: target name, DDL, INSERT, indexes.
    pre_counts: dict[str, int] = {}
    post_counts: dict[str, int] = {}
    failures: list[tuple[str, str]] = []

    for tbl in src_tables:
        target = COLLISION_RENAMES.get(tbl, f"jpi_{tbl}")
        # Check target absence in main schema.
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (target,)
        ).fetchone()
        if exists:
            print(f"  SKIP {tbl} (target {target} already exists in dst)")
            continue

        try:
            src_count = conn.execute(f"SELECT COUNT(*) FROM jpi.{tbl}").fetchone()[0]
            pre_counts[tbl] = src_count

            ddl = get_table_ddl(conn, "jpi", tbl)
            new_ddl = rewrite_ddl(ddl, tbl, target)

            indexes = get_table_indexes(conn, "jpi", tbl)
            new_indexes = [rewrite_index(s, tbl, target) for s in indexes]

            if args.dry_run:
                print(f"  [dry-run] {tbl} → {target} ({src_count} rows, {len(indexes)} idx)")
                post_counts[tbl] = src_count  # assume identity
                continue

            t0 = time.time()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(new_ddl)
            conn.execute(f"INSERT INTO {target} SELECT * FROM jpi.{tbl}")
            for idx_sql in new_indexes:
                try:
                    conn.execute(idx_sql)
                except sqlite3.OperationalError as e:
                    if "already exists" not in str(e):
                        raise
            conn.execute("COMMIT")
            cnt = conn.execute(f"SELECT COUNT(*) FROM {target}").fetchone()[0]
            post_counts[tbl] = cnt
            elapsed = time.time() - t0
            print(f"  OK   {tbl} → {target} ({cnt} rows, {len(indexes)} idx, {elapsed:.1f}s)")
        except Exception as e:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            failures.append((tbl, str(e)))
            print(f"  FAIL {tbl}: {e}", file=sys.stderr)

    # Step 5 — Verify.
    print("\n=== verification ===")
    mismatches = [
        (t, pre_counts[t], post_counts.get(t))
        for t in pre_counts
        if pre_counts[t] != post_counts.get(t)
    ]
    if mismatches:
        print(f"MISMATCH count {len(mismatches)}:", file=sys.stderr)
        for t, pre, post in mismatches:
            print(f"  {t}: pre={pre} post={post}", file=sys.stderr)
        return 1
    print(f"identity OK: {len(pre_counts)} tables copied, total {sum(pre_counts.values())} rows")

    if failures:
        print(f"\n{len(failures)} table(s) failed:", file=sys.stderr)
        for t, msg in failures:
            print(f"  {t}: {msg}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("\n[dry-run complete] re-run without --dry-run to apply.")
    else:
        print("\nDONE. Backup retained at:", BACKUP)
        print("Next: switch src/jpintel_mcp/db/connect.py DB_PATH to autonomath.db")

    return 0


if __name__ == "__main__":
    sys.exit(main())
