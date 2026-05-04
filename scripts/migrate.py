#!/usr/bin/env python3
"""Idempotent SQL migration runner for jpintel-mcp.

Reads scripts/migrations/*.sql in lexicographic order. Applied migrations
are recorded in the `schema_migrations` table so re-running is a no-op.

Usage:
    python scripts/migrate.py                 # use JPINTEL_DB_PATH / ./data/jpintel.db
    python scripts/migrate.py --db path.db    # explicit target
    python scripts/migrate.py --dry-run       # print planned migrations, no changes
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_LOG = logging.getLogger("jpintel.migrate")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _default_db_path() -> Path:
    env = os.environ.get("JPINTEL_DB_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data" / "jpintel.db"


def _configure_logging() -> None:
    root = logging.getLogger("jpintel.migrate")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )"""
    )


def _applied_ids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT id FROM schema_migrations").fetchall()
    return {r[0] for r in rows}


def _load_migrations() -> list[tuple[str, Path, str]]:
    out: list[tuple[str, Path, str]] = []
    if not MIGRATIONS_DIR.is_dir():
        return out
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = p.read_text(encoding="utf-8")
        if p.name.endswith("_rollback.sql") or _sql_has_header_marker(sql, "boot_time", "manual"):
            _LOG.info("skipping_manual_migration id=%s", p.name)
            continue
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        out.append((p.name, p, checksum))
    return out


def _connection_db_filename(conn: sqlite3.Connection) -> str:
    """Return the filename of the main database attached to `conn`.

    Uses `PRAGMA database_list` so we don't need to thread the path through
    every call. Returns "" for in-memory / unattached connections.
    """
    for row in conn.execute("PRAGMA database_list"):
        # row = (seq, name, file). The 'main' DB is always seq=0.
        if row[1] == "main":
            return os.path.basename(row[2] or "")
    return ""


def _sql_has_target_marker(sql: str, target: str) -> bool:
    """True iff one of the first ~5 lines is `-- target_db: <target>`.

    The marker is conservative on purpose: only a header comment counts so
    the same string buried in a CREATE TRIGGER body can't trip the gate.
    """
    needle = f"-- target_db: {target}"
    return any(line.strip() == needle for line in sql.splitlines()[:5])


def _sql_target_marker(sql: str) -> str | None:
    """Return normalized `target_db` header value if present."""
    for line in sql.splitlines()[:5]:
        stripped = line.strip()
        if not stripped.startswith("-- target_db:"):
            continue
        target = stripped.split(":", 1)[1].strip().lower()
        if target in {"jpintel", "jpintel.db"}:
            return "jpintel"
        if target in {"autonomath", "autonomath.db"}:
            return "autonomath"
        return target
    return None


def _connection_db_target(conn: sqlite3.Connection) -> str:
    """Return the logical DB target for migration header checks."""
    db_filename = _connection_db_filename(conn)
    if db_filename.endswith("autonomath.db"):
        return "autonomath"
    return "jpintel"


def _sql_has_header_marker(sql: str, key: str, value: str) -> bool:
    """True iff one of the first ~5 lines is `-- <key>: <value>`."""
    needle = f"-- {key}: {value}"
    return any(line.strip() == needle for line in sql.splitlines()[:5])


def _apply_one(conn: sqlite3.Connection, mig_id: str, sql: str, checksum: str) -> None:
    now = datetime.now(UTC).isoformat()
    # V4 absorption migrations (046/047/049) ALTER am_-prefixed tables that
    # only exist in autonomath.db. Skip them when the connection points at
    # jpintel.db so the same migrations/ directory works for both DBs.
    # Still record-as-applied so re-runs don't retry.
    target = _sql_target_marker(sql)
    if target:
        db_target = _connection_db_target(conn)
        if target != db_target:
            _LOG.info(
                "skipping_targeted_migration id=%s target=%s db_target=%s db=%s reason=target_db_marker",
                mig_id,
                target,
                db_target,
                _connection_db_filename(conn) or "<memory>",
            )
            conn.execute(
                "INSERT INTO schema_migrations(id, checksum, applied_at) VALUES (?,?,?)",
                (mig_id, checksum, now),
            )
            return
    # Note: sqlite3.Connection.executescript() issues an implicit COMMIT before
    # running, so we cannot wrap DDL + bookkeeping in a single user transaction
    # via BEGIN/COMMIT. Apply statement-by-statement so an already-present
    # ALTER TABLE ADD COLUMN does not abort the rest of a multi-column
    # migration and then get recorded as fully applied.
    for stmt in _iter_sql_statements(sql):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            stmt_lower = stmt.lower()
            is_add_column = "alter table" in stmt_lower and "add column" in stmt_lower
            if "duplicate column" in msg and is_add_column:
                _LOG.warning(
                    "duplicate_column_statement_skipping id=%s err=%s",
                    mig_id,
                    exc,
                )
                continue
            raise
    conn.execute(
        "INSERT INTO schema_migrations(id, checksum, applied_at) VALUES (?,?,?)",
        (mig_id, checksum, now),
    )


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "src" / "jpintel_mcp" / "db" / "schema.sql"


def _iter_sql_statements(sql: str) -> list[str]:
    """Split a SQL script into complete statements.

    `sqlite3.complete_statement` understands BEGIN/END trigger blocks, so
    this correctly keeps a multi-line trigger body together while still
    splitting `CREATE TABLE; CREATE INDEX; ...` sequences.
    """
    out: list[str] = []
    buf = ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            stripped = buf.strip()
            if stripped:
                out.append(stripped)
            buf = ""
    tail = buf.strip()
    if tail:
        out.append(tail)
    return out


def _ensure_base_schema(conn: sqlite3.Connection) -> None:
    # On a fresh volume the DB has no tables. The migrations assume programs/
    # exclusion_rules/etc already exist (001_lineage.sql = ALTER TABLE programs).
    # schema.sql is fully idempotent (CREATE TABLE IF NOT EXISTS) so applying it
    # unconditionally is safe on both fresh and existing databases. Migrations
    # that re-add columns already present are caught by the duplicate-column
    # fallback below.
    #
    # Edge case: an old prod DB can have `programs` / `usage_events` without
    # a column that schema.sql's CREATE INDEX references (source_fetched_at,
    # params_digest, ...). `CREATE TABLE IF NOT EXISTS` is a no-op on the
    # existing narrow table, so those columns aren't backfilled until the
    # relevant migration runs *after* this function. We tolerate per-statement
    # "no such column" errors on CREATE INDEX here; the migration that adds
    # the column will (re-)create the index.
    if not SCHEMA_PATH.is_file():
        return
    raw_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    for stmt in _iter_sql_statements(raw_sql):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            stmt_lower = stmt.lower()
            is_index_stmt = (
                "create index" in stmt_lower
                or "create unique index" in stmt_lower
            )
            if "no such column" in msg and is_index_stmt:
                _LOG.warning("schema_index_deferred stmt=%r err=%s", stmt, e)
                continue
            raise


def run_migrations(db_path: Path, dry_run: bool = False) -> list[str]:
    if not db_path.is_file():
        # We allow the DB to not exist yet — init it by touching via sqlite3.connect.
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        if not dry_run:
            _ensure_base_schema(conn)
        _ensure_migrations_table(conn)
        applied = _applied_ids(conn)
        pending = [
            (mid, path, checksum)
            for (mid, path, checksum) in _load_migrations()
            if mid not in applied
        ]

        if not pending:
            _LOG.info("no_pending_migrations applied=%d", len(applied))
            return []

        applied_now: list[str] = []
        for mid, path, checksum in pending:
            if dry_run:
                _LOG.info("dry_run_would_apply id=%s path=%s", mid, path)
                applied_now.append(mid)
                continue
            _LOG.info("applying id=%s path=%s", mid, path)
            sql = path.read_text(encoding="utf-8")
            try:
                _apply_one(conn, mid, sql, checksum)
            except sqlite3.OperationalError as e:
                # Likely idempotency race: ADD COLUMN on already-present column.
                # Detect and record as applied so repeat runs pass.
                msg = str(e).lower()
                if "duplicate column" in msg:
                    _LOG.warning("duplicate_column_skipping id=%s err=%s", mid, e)
                    now = datetime.now(UTC).isoformat()
                    conn.execute(
                        "INSERT OR IGNORE INTO schema_migrations(id, checksum, applied_at) VALUES (?,?,?)",
                        (mid, checksum, now),
                    )
                else:
                    raise
            applied_now.append(mid)
            _LOG.info("applied id=%s", mid)
        return applied_now
    finally:
        conn.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Idempotent SQL migrations for jpintel-mcp")
    p.add_argument("--db", type=Path, default=None, help="Path to SQLite DB (default: JPINTEL_DB_PATH or ./data/jpintel.db)")
    p.add_argument("--dry-run", action="store_true", help="Print plan, apply nothing")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)
    db_path = args.db if args.db else _default_db_path()
    try:
        applied = run_migrations(db_path, dry_run=args.dry_run)
    except Exception as e:
        _LOG.error("migrate_failed err=%s", e, exc_info=True)
        return 1
    if applied:
        print(f"applied {len(applied)} migration(s): {', '.join(applied)}")
    else:
        print("no pending migrations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
