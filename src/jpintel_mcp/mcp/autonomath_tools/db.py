"""AutonoMath DB connection layer for the 8 new MCP tools.

Thread-safe, read-only connection helpers against two SQLite files:

- ``autonomath.db``  — 190K normalized entities + EAV facts + FTS5 trigram
- ``graph.sqlite``   — 13K+ edges across ~13K nodes (program/authority/law/
  region/industry/target_size kinds)

Design notes
------------
1. **Read-only URI**. Both files are opened via `file:...?mode=ro` URI so
   concurrent write sessions (Wave 2 agent still ingesting) cannot lock
   our reads. Writers hold WAL reader snapshots; readers cannot block
   writers and vice-versa in practice.

2. **Retry on locked**. If a `sqlite3.OperationalError: database is
   locked` slips through (rare: WAL checkpoint races), we retry up to
   ``_MAX_RETRIES`` times with exponential backoff (25ms → 200ms).

3. **Per-thread connections**. sqlite3 module objects are not safe to
   share across threads; we therefore keep a ``threading.local`` pool
   and open a fresh connection the first time a thread touches each DB.
   Connections are closed when the thread exits or when
   ``close_all()`` is called explicitly.

4. **Row factory = dict-like**. Callers get `sqlite3.Row` objects so
   they can do both ``row["primary_name"]`` and ``dict(row)``.

5. **No schema coupling**. This file knows the file paths and pragma
   setup only. Tool modules (``tools.py``) own SQL strings — keeping
   DB setup orthogonal to query logic so the file is reusable beyond
   the 8 new tools (e.g. future benchmark scripts).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Literal

logger = logging.getLogger("jpintel.mcp.new.db")

# ---------------------------------------------------------------------------
# File paths (absolute). Override via env vars for CI / alt wiring.
# ---------------------------------------------------------------------------

# Repo root (../../../../ from this file: autonomath_tools/db.py
# -> mcp/ -> jpintel_mcp/ -> src/ -> repo root).
_REPO_ROOT = Path(__file__).resolve().parents[4]

AUTONOMATH_DB_PATH = Path(
    os.environ.get(
        "AUTONOMATH_DB_PATH",
        str(_REPO_ROOT / "autonomath.db"),
    )
)
GRAPH_DB_PATH = Path(
    os.environ.get(
        "AUTONOMATH_GRAPH_DB_PATH",
        str(_REPO_ROOT / "graph.sqlite"),
    )
)

# ---------------------------------------------------------------------------
# Retry policy (for rare WAL checkpoint races).
# ---------------------------------------------------------------------------

_MAX_RETRIES = 5
_BACKOFF_MS = (25, 50, 100, 150, 200)


# ---------------------------------------------------------------------------
# Per-thread connection pool.
# ---------------------------------------------------------------------------

_local = threading.local()


# ---------------------------------------------------------------------------
# Per-connection tuning (perf pass, 2026-04-24; bumped 2026-04-25 per
# dd_v3_05 / dd_v6_05 / v8 P5-α).
#
# The autonomath DB is 7.4GB with heavy JSON-extract / LIKE workloads. Default
# SQLite cache (2000 pages * 4KB = 8MB) is far too small; most queries cold-
# read from disk. mmap_size lets SQLite memory-map the DB file so reads go
# through the page cache directly.
#
# cache_size is negative to mean "KB" (SQLite convention). -262144 = 256MB.
# mmap_size=2GB is conservative for a 7.4GB DB (typical hot working set —
# FTS5 postings, idx_am_entities_*, am_entities header — fits well under 2GB).
# Larger mappings risk address-space pressure on 32-bit ARM CI runners.
# ---------------------------------------------------------------------------
_CACHE_KB = 262144  # 256 MB page cache per connection
_MMAP_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB mmap window
_BUSY_TIMEOUT_MS = 300000  # 300s; ingest CLI can hold writer lock for tens of s


def _open_ro(path: Path) -> sqlite3.Connection:
    """Open a read-only connection with sensible pragmas.

    Uses the `file:...?mode=ro&cache=shared` URI so WAL readers are
    enabled. ``cache=shared`` lets multiple per-thread connections in this
    process share the SQLite page cache -- cuts cold-start latency on the
    second+ connection when the tool layer spins up workers.
    """
    if not path.exists():
        raise FileNotFoundError(f"sqlite file not found: {path}")
    # cache=shared: in-process shared page cache across per-thread conns.
    # immutable=0 implicit: keep WAL semantics for live-writer snapshots.
    uri = f"file:{path}?mode=ro&cache=shared"
    last_err: BaseException | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            conn = sqlite3.connect(
                uri,
                uri=True,
                timeout=5.0,
                check_same_thread=True,
                isolation_level=None,  # autocommit / read-only anyway
            )
            conn.row_factory = sqlite3.Row
            # --- sqlite-vec runtime load (Wave18 Q1, 2026-04-25) -------------
            # Image bakes vec0.so at /opt/vec0.so; env var set in Dockerfile:95.
            # vec0 module registration only — no DB writes. Graceful degrade:
            # load failure must not break MCP/REST autonomath tools.
            _vec0 = os.environ.get("AUTONOMATH_VEC0_PATH")
            if _vec0 and Path(_vec0).exists():
                try:
                    conn.enable_load_extension(True)
                    conn.load_extension(_vec0)
                    conn.enable_load_extension(False)
                except (sqlite3.OperationalError, AttributeError) as exc:
                    logger.warning("vec0 load failed (%s): %s", _vec0, exc)
            # -----------------------------------------------------------------
            # Long busy handler for WAL racers (300s). The ingest CLI can hold
            # the writer lock for tens of seconds during bulk merges; the old
            # 5s timeout caused intermittent "database is locked" on readers.
            conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
            # Enable query planner to use the FTS5 table if present.
            conn.execute("PRAGMA query_only=1")
            # --- perf tuning (must precede any data query) -------------------
            # NOTE: journal_mode=WAL, synchronous=NORMAL, and wal_autocheckpoint
            # are intentionally NOT set here. The connection is opened in
            # mode=ro + query_only=1; setting WAL-mutating pragmas on an RO
            # handle either fails with "attempt to write a readonly database"
            # or is silently ignored. The DB's WAL state is configured by the
            # writer (jpintel_mcp/db/session.py and the ingest CLI).
            #
            # Temp tables in memory -- important for ORDER BY without covering
            # index (planner uses TEMP B-TREE for our kind+name sorts etc.).
            conn.execute("PRAGMA temp_store=MEMORY")
            # 256MB page cache (negative = KB). Default 2MB is too small for
            # 7.4GB DB. Each connection gets its own, but with cache=shared
            # they share pages in practice.
            conn.execute(f"PRAGMA cache_size=-{_CACHE_KB}")
            # 2GB mmap window (bumped from 1GB per dd_v3_05/v6_05/v8 P5-α).
            # macOS handles this fine; Linux likewise. Gives the OS discretion
            # to keep hot pages resident without SQLite managing its own cache.
            conn.execute(f"PRAGMA mmap_size={_MMAP_BYTES}")
            return conn
        except sqlite3.OperationalError as e:
            last_err = e
            if "locked" in str(e).lower() and attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_MS[attempt] / 1000.0)
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError("unreachable")  # pragma: no cover


def connect_autonomath(
    mode: Literal["ro"] = "ro",
) -> sqlite3.Connection:
    """Return a read-only connection to ``autonomath.db`` for the current thread.

    ``mode`` is currently ``'ro'`` only — the stub explicitly forbids
    write access during Wave 3 because the Wave 2 ingest agent may still
    be writing. Attempting to pass any other value raises ``ValueError``.
    """
    if mode != "ro":
        raise ValueError(
            f"connect_autonomath: only mode='ro' supported in Wave 3 "
            f"(got {mode!r}). Write access must go through the ingest "
            f"pipeline in /tmp/autonomath_infra_2026-04-24/ingest/."
        )
    path = Path(os.environ.get("AUTONOMATH_DB_PATH", str(AUTONOMATH_DB_PATH)))
    conn = getattr(_local, "autonomath", None)
    conn_path = getattr(_local, "autonomath_path", None)
    if conn is None or conn_path != path:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # pragma: no cover
                pass
        conn = _open_ro(path)
        _local.autonomath = conn
        _local.autonomath_path = path
        logger.debug(
            "opened autonomath.db RO connection on thread %s", threading.current_thread().name
        )
    return conn


def connect_graph(
    mode: Literal["ro"] = "ro",
) -> sqlite3.Connection:
    """Return a read-only connection to ``graph.sqlite`` for the current thread."""
    if mode != "ro":
        raise ValueError(f"connect_graph: only mode='ro' supported in Wave 3 (got {mode!r}).")
    path = Path(os.environ.get("AUTONOMATH_GRAPH_DB_PATH", str(GRAPH_DB_PATH)))
    conn = getattr(_local, "graph", None)
    conn_path = getattr(_local, "graph_path", None)
    if conn is None or conn_path != path:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # pragma: no cover
                pass
        conn = _open_ro(path)
        _local.graph = conn
        _local.graph_path = path
        logger.debug(
            "opened graph.sqlite RO connection on thread %s", threading.current_thread().name
        )
    return conn


def close_all() -> None:
    """Close per-thread connections. Safe to call multiple times."""
    for attr in ("autonomath", "graph"):
        conn = getattr(_local, attr, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # pragma: no cover
                pass
            setattr(_local, attr, None)
            setattr(_local, f"{attr}_path", None)


# ---------------------------------------------------------------------------
# Tiny helpers shared across tools.
# ---------------------------------------------------------------------------


def execute_with_retry(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple | list = (),
) -> list[sqlite3.Row]:
    """Execute a SELECT and return rows, retrying on transient lock.

    Callers should prefer the raw ``conn.execute(...)`` for simplicity;
    this wrapper exists for paths that occasionally see `database is
    locked` on macOS WAL racers and want defense-in-depth.
    """
    last_err: BaseException | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            cur = conn.execute(sql, params)
            return cur.fetchall()
        except sqlite3.OperationalError as e:
            last_err = e
            if "locked" in str(e).lower() and attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_MS[attempt] / 1000.0)
                continue
            raise
    if last_err:
        raise last_err
    return []  # pragma: no cover


__all__ = [
    "AUTONOMATH_DB_PATH",
    "GRAPH_DB_PATH",
    "close_all",
    "connect_autonomath",
    "connect_graph",
    "execute_with_retry",
]
