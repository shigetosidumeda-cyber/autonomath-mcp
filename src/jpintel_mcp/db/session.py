import logging
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from jpintel_mcp.config import settings

_log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Tables that live ONLY in jpintel.db (the program shard). If a connection
# opened against autonomath.db ever issues a SELECT against one of these,
# we deny the read at the SQLite authorizer layer so the query fails loudly
# instead of silently returning 0 rows. autonomath.db carries the same
# logical content under the `jpi_*` mirror prefix (migration 032) — callers
# must use `jpi_programs` etc. when talking to autonomath.db.
#
# autonomath.db.programs IS intentionally an empty placeholder; the
# authorizer below makes that intent enforceable instead of a footgun.
# See P0-2 (DB正本不一致) audit, 2026-04-30.
_JPINTEL_ONLY_TABLES: frozenset[str] = frozenset(
    {
        "programs",
        "case_studies",
        "loan_programs",
        "enforcement_cases",
    }
)


def _path_is_autonomath(path: Path) -> bool:
    """Return True iff `path` resolves to the autonomath.db file.

    Compares basename only (case-insensitive) so dev (`./autonomath.db`),
    prod (`/data/autonomath.db`), and the various dated backups
    (`autonomath.db.bak.*`) are all caught. The backup files should never
    be opened by `connect()`, but if they are, we still want the authorizer
    in place — they share the same `programs` placeholder schema.
    """
    return path.name.lower().startswith("autonomath.db")


def _autonomath_authorizer(
    action: int,
    arg1: str | None,
    arg2: str | None,
    db_name: str | None,
    trigger: str | None,
) -> int:
    """sqlite3 authorizer that denies reads on jpintel-only tables.

    Returns SQLITE_OK (0) for everything except SELECT/READ ops on a table
    in `_JPINTEL_ONLY_TABLES`, in which case it returns SQLITE_DENY (1).
    Denied queries raise `sqlite3.DatabaseError: not authorized` at prepare
    time, so the caller sees a hard failure instead of an empty result set.

    The autonomath.db `programs` table is intentionally an empty placeholder
    (the canonical row set lives in jpintel.db `programs` AND in autonomath.db
    `jpi_programs`). Without this guard, a misrouted `SELECT * FROM programs`
    against autonomath.db would silently return 0 rows — a fraud-risk for a
    production API that ships eligibility data.
    """
    # SQLITE_READ = 20 (column-level read authorisation, called for every
    # column referenced by a SELECT). arg1=table, arg2=column, db_name=main.
    if action == sqlite3.SQLITE_READ and arg1 in _JPINTEL_ONLY_TABLES:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def init_db(db_path: Path | None = None) -> None:
    path = db_path or settings.db_path
    _ensure_parent(path)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with sqlite3.connect(path) as conn:
        conn.executescript(schema)
        conn.commit()


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    _ensure_parent(path)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # P0-2 defensive guard (2026-04-30). When this helper is mis-pointed at
    # autonomath.db (e.g. AUTONOMATH_DB_PATH leaking into JPINTEL_DB_PATH),
    # any SELECT against the empty `programs` placeholder must fail hard,
    # not silently return 0 rows. The authorizer layer below denies reads
    # on the four jpintel-only tables; callers wanting the autonomath
    # mirror must explicitly query `jpi_programs` etc. See module docstring.
    if _path_is_autonomath(path):
        _log.warning(
            "session.connect() opened against autonomath.db (%s); "
            "installing read-deny authorizer for jpintel-only tables %s",
            path,
            sorted(_JPINTEL_ONLY_TABLES),
        )
        conn.set_authorizer(_autonomath_authorizer)

    # --- sqlite-vec runtime load (Wave18 Q1, 2026-04-25) -------------------
    # Image bakes vec0.so at /opt/vec0.so; env var set in Dockerfile:95.
    # Pattern mirrors src/jpintel_mcp/_archive/embedding_2026-04-25/db.py.
    # Graceful degrade: load failure must not break API/MCP.
    _vec0 = os.environ.get("AUTONOMATH_VEC0_PATH")
    if _vec0 and Path(_vec0).exists():
        try:
            conn.enable_load_extension(True)
            conn.load_extension(_vec0)
            conn.enable_load_extension(False)
        except (sqlite3.OperationalError, AttributeError) as exc:
            _log.warning("vec0 load failed (%s): %s", _vec0, exc)
    # -----------------------------------------------------------------------

    # WAL + sync=NORMAL: standard durable-but-fast pairing.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    # 300s busy timeout: data-collection CLI sometimes holds the writer lock
    # for tens of seconds during bulk merge. 5s default was too tight.
    conn.execute("PRAGMA busy_timeout = 300000")
    conn.execute("PRAGMA foreign_keys = ON")
    # --- perf tuning (dd_v3_05 / dd_v6_05 / v8 P5-α, 2026-04-25) -------------
    # 512MB mmap window. jpintel.db is 188MB so the whole file fits, with
    # headroom for WAL pages. mmap_size only sets a ceiling; mapping is lazy.
    conn.execute("PRAGMA mmap_size = 536870912")
    # 256MB page cache (negative = KB; portable across page sizes).
    conn.execute("PRAGMA cache_size = -262144")
    # Temp B-trees in RAM (matters for ORDER BY without covering index).
    conn.execute("PRAGMA temp_store = MEMORY")
    # Checkpoint every ~4MB of WAL (1000 * 4KB pages) to keep WAL bounded.
    conn.execute("PRAGMA wal_autocheckpoint = 1000")
    return conn


@contextmanager
def txn(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
