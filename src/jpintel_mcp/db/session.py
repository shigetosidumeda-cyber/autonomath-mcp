import logging
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from jpintel_mcp.config import settings

_log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


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
