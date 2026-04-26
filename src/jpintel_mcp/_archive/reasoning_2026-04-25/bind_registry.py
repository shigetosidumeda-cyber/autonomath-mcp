"""Bind registry — dispatcher + shared read-only DB connection pool.

Wave-2 policy: the canonical SQLite (autonomath.db) and graph SQLite
(graph/graph.sqlite) are being ingested in parallel by other agents. We open
them **read-only** via URI, share one connection per DB per process, and
tolerate partial / absent tables.

Every bind_iXX.py returns a dict of the form:
    {
        "bound_ok": bool,                # True if we put something useful in ctx
        "ctx": {<placeholder_name>: <str value>, ...},
        "source_urls": [ ... ],
        "notes": [ ... ],                # human debug trail
    }
match.py merges ``ctx`` into the skeleton render context before
``_PLACEHOLDER_RE`` substitution. Anything NOT added here falls back to
``<<<missing:KEY>>>`` (the whole point — no hallucination).

Graceful fallback: if the canonical DB is missing, schema is old, or a specific
query raises, the bind returns ``bound_ok=False`` with a note and the skeleton
keeps its placeholders. That's the correct user-facing outcome — the LLM sees
the gap, not an imaginary answer.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .precompute import PrecomputedCache


# ---------------------------------------------------------------------------
# Paths (mirrors the Wave-1 layout under /tmp/autonomath_infra_2026-04-24/)
# ---------------------------------------------------------------------------

INFRA_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_DB = INFRA_ROOT / "autonomath.db"
GRAPH_DB = INFRA_ROOT / "graph" / "graph.sqlite"


# ---------------------------------------------------------------------------
# Read-only connection cache. We keep one sqlite3.Connection per DB path.
# ---------------------------------------------------------------------------

_CONN_CACHE: Dict[str, Optional[sqlite3.Connection]] = {}


def _open_ro(path: Path) -> Optional[sqlite3.Connection]:
    """Open SQLite in read-only mode. Returns None if file missing."""
    key = str(path)
    if key in _CONN_CACHE:
        return _CONN_CACHE[key]
    if not path.exists():
        _CONN_CACHE[key] = None
        return None
    try:
        uri = f"file:{path}?mode=ro&immutable=0"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        _CONN_CACHE[key] = conn
        return conn
    except sqlite3.Error:
        _CONN_CACHE[key] = None
        return None


def get_canonical_conn() -> Optional[sqlite3.Connection]:
    return _open_ro(CANONICAL_DB)


def get_graph_conn() -> Optional[sqlite3.Connection]:
    return _open_ro(GRAPH_DB)


def db_has_table(conn: Optional[sqlite3.Connection], name: str) -> bool:
    if conn is None:
        return False
    try:
        cur = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        return cur.fetchone() is not None
    except sqlite3.Error:
        return False


def safe_rows(conn: Optional[sqlite3.Connection], sql: str,
              params: tuple = ()) -> List[sqlite3.Row]:
    if conn is None:
        return []
    try:
        return list(conn.execute(sql, params))
    except sqlite3.Error:
        return []


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

# Registered at import-time by each bind_*.py module
_BINDERS: Dict[str, Callable[..., Dict[str, Any]]] = {}


def register(intent_id: str, fn: Callable[..., Dict[str, Any]]) -> None:
    _BINDERS[intent_id] = fn


def bind(intent_id: str, slots: Dict[str, Any],
         cache: PrecomputedCache) -> Dict[str, Any]:
    """Dispatch to the per-intent binder. Returns the usual
    ``{bound_ok, ctx, source_urls, notes}`` dict — or a stub if no binder is
    registered for this intent."""
    fn = _BINDERS.get(intent_id)
    if fn is None:
        return {
            "bound_ok": False,
            "ctx": {},
            "source_urls": [],
            "notes": [f"no bind_{intent_id}.py registered"],
        }
    try:
        return fn(slots, cache)
    except Exception as e:  # broad on purpose — bind layer must never crash match()
        return {
            "bound_ok": False,
            "ctx": {},
            "source_urls": [],
            "notes": [f"bind error: {type(e).__name__}: {e}"],
        }


# Import side-effects: each module calls ``register()`` on import.
from . import bind_i01  # noqa: E402,F401
from . import bind_i02  # noqa: E402,F401
from . import bind_i03  # noqa: E402,F401
from . import bind_i04  # noqa: E402,F401
from . import bind_i05  # noqa: E402,F401
from . import bind_i06  # noqa: E402,F401
from . import bind_i07  # noqa: E402,F401
from . import bind_i08  # noqa: E402,F401
from . import bind_i09  # noqa: E402,F401
from . import bind_i10  # noqa: E402,F401


__all__ = [
    "bind",
    "register",
    "get_canonical_conn",
    "get_graph_conn",
    "db_has_table",
    "safe_rows",
    "CANONICAL_DB",
    "GRAPH_DB",
]
