"""Single canonical corpus_snapshot_id helper for MCP tool envelopes.

W3-13 finding (2026-05-04): industry_packs / wave24_tools_first_half /
wave24_tools_second_half emit response bodies WITHOUT the
``corpus_snapshot_id`` + ``corpus_checksum`` reproducibility pair.
Wave22 / wave22_tools.py already does this via a duplicated
``_compute_corpus_snapshot()`` + ``_attach_snapshot()`` pair, and
corporate_layer_tools.py does it with yet another duplicate. This module
unifies the contract:

  - ``current_corpus_snapshot()``  → returns (snapshot_id, checksum) using
    a fresh autonomath connection. 5-minute process-local cache. No-DB
    fallback returns a deterministic ``("1970-01-01T00:00:00Z",
    "sha256:0000000000000000")`` pair so the field is always present.
  - ``current_corpus_snapshot_id()`` → convenience wrapper, returns just
    the id (used by ``envelope_wrapper.build_envelope`` where the caller
    has no SQLite connection).
  - ``attach_corpus_snapshot(body)``  → mutates ``body`` in-place to add
    both keys at the top level. Returns the same dict for chaining
    (mirrors wave22 ``_attach_snapshot`` ergonomics).
  - ``attach_corpus_snapshot_with_conn(conn, body)`` → same, but reuses
    an existing connection (preferred when the impl already has one
    open — saves the open/close round trip).

All injection paths are best-effort: any sqlite error collapses to the
fallback pair so the envelope contract holds even on a brand-new
fresh-clone DB.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from typing import Any

logger = logging.getLogger("autonomath.mcp.snapshot_helper")

# Process-local cache: { cache_key: (expiry_unix, snapshot_id, checksum) }
_CACHE: dict[str, tuple[float, str, str]] = {}
_TTL_SECONDS = 300.0

# Canonical fallback pair when no DB is reachable. Deterministic so
# auditors can recognise the "no-data" sentinel and the test suite can
# assert against a stable value.
_FALLBACK_SNAPSHOT_ID = "1970-01-01T00:00:00Z"
_FALLBACK_CHECKSUM = "sha256:0000000000000000"

# Tables sampled for the checksum mix-in. Same set as
# api/_corpus_snapshot.py + wave22_tools so MCP / REST / Wave22 / Wave24
# all converge on the same checksum for the same corpus moment.
_SNAPSHOT_TABLES: tuple[str, ...] = (
    "programs",
    "laws",
    "tax_rulesets",
    "court_decisions",
)

# Same api_version constant the api/_corpus_snapshot.py uses — keeps the
# digest stable across MCP and REST callers.
_API_VERSION = "v0.3.2"


def _compute_with_conn(conn: sqlite3.Connection) -> tuple[str, str]:
    """Compute (snapshot_id, checksum) using an open connection.

    Mirrors ``api/_corpus_snapshot.compute_corpus_snapshot`` semantics so
    MCP and REST surface the same identity for a given moment.

    Never raises — sqlite errors collapse to the fallback pair.
    """
    snapshot_id: str | None = None

    # Best signal: latest am_amendment_diff.detected_at (cron output).
    try:
        row = conn.execute(
            "SELECT MAX(detected_at) FROM am_amendment_diff"
        ).fetchone()
        if row and row[0]:
            snapshot_id = str(row[0])
    except sqlite3.Error:
        pass

    if not snapshot_id:
        candidates: list[str] = []
        for table, expr in (
            ("programs", "MAX(source_fetched_at)"),
            ("laws", "MAX(fetched_at)"),
            ("tax_rulesets", "MAX(fetched_at)"),
            ("court_decisions", "MAX(fetched_at)"),
            ("jpi_tax_rulesets", "MAX(fetched_at)"),
            ("jpi_court_decisions", "MAX(fetched_at)"),
            ("am_entities", "MAX(fetched_at)"),
        ):
            try:
                # B608 false positive: `table` and `expr` are from the
                # controlled internal whitelist above, never from user
                # input.
                row = conn.execute(
                    f"SELECT {expr} FROM {table}"  # nosec B608
                ).fetchone()
                if row and row[0]:
                    candidates.append(str(row[0]))
            except sqlite3.Error:
                continue
        snapshot_id = max(candidates) if candidates else _FALLBACK_SNAPSHOT_ID

    counts: list[int] = []
    for table in _SNAPSHOT_TABLES:
        try:
            # B608 false positive: `table` is from the module-level
            # whitelist above.
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table}"  # nosec B608
            ).fetchone()
            counts.append(int(row[0]) if row and row[0] is not None else 0)
        except sqlite3.Error:
            counts.append(0)

    digest_input = (
        f"{snapshot_id}|{_API_VERSION}|{','.join(str(c) for c in counts)}"
    ).encode("utf-8")
    checksum = "sha256:" + hashlib.sha256(digest_input).hexdigest()[:16]
    return snapshot_id, checksum


def current_corpus_snapshot(
    conn: sqlite3.Connection | None = None,
) -> tuple[str, str]:
    """Return cached (snapshot_id, checksum). Opens autonomath.db if
    no connection is supplied. Falls back to the deterministic pair on
    any failure so the envelope contract always holds.
    """
    cache_key = "autonomath" if conn is None else _conn_key(conn)
    now = time.monotonic()
    cached = _CACHE.get(cache_key)
    if cached is not None and cached[0] > now:
        return cached[1], cached[2]

    snapshot_id = _FALLBACK_SNAPSHOT_ID
    checksum = _FALLBACK_CHECKSUM
    try:
        if conn is None:
            # Lazy import to avoid an autonomath_tools.db import cycle
            # for callers (envelope_wrapper) that previously had no DB
            # dependency. ``connect_autonomath`` returns a thread-local
            # singleton — we must NEVER close it (other callers in the
            # same thread share the handle).
            try:
                from .db import connect_autonomath
                conn = connect_autonomath()
            except Exception:  # pragma: no cover - DB absent
                conn = None
        if conn is not None:
            snapshot_id, checksum = _compute_with_conn(conn)
    except Exception:  # pragma: no cover - defensive
        logger.exception("current_corpus_snapshot: compute failed, using fallback")

    _CACHE[cache_key] = (now + _TTL_SECONDS, snapshot_id, checksum)
    return snapshot_id, checksum


def current_corpus_snapshot_id() -> str:
    """Convenience: return only the snapshot id. Used by
    ``envelope_wrapper.build_envelope`` which has no live conn handle.
    """
    return current_corpus_snapshot()[0]


def attach_corpus_snapshot(body: dict[str, Any]) -> dict[str, Any]:
    """Inject ``corpus_snapshot_id`` + ``corpus_checksum`` keys onto
    ``body`` (in-place) and return the same dict for chaining.

    Idempotent: existing values are NOT overwritten — this matters for
    error-path returns from ``error_envelope.make_error`` that might
    later be enriched at a higher layer.
    """
    if not isinstance(body, dict):
        return body
    if body.get("corpus_snapshot_id") and body.get("corpus_checksum"):
        return body
    snap_id, checksum = current_corpus_snapshot()
    body.setdefault("corpus_snapshot_id", snap_id)
    body.setdefault("corpus_checksum", checksum)
    return body


def attach_corpus_snapshot_with_conn(
    conn: sqlite3.Connection,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Same as ``attach_corpus_snapshot`` but reuses an existing conn.

    Preferred from impls that already have an autonomath.db handle open
    — avoids the per-call connection overhead inside
    ``current_corpus_snapshot``.
    """
    if not isinstance(body, dict):
        return body
    if body.get("corpus_snapshot_id") and body.get("corpus_checksum"):
        return body
    snap_id, checksum = current_corpus_snapshot(conn)
    body.setdefault("corpus_snapshot_id", snap_id)
    body.setdefault("corpus_checksum", checksum)
    return body


def _conn_key(conn: sqlite3.Connection) -> str:
    """Best-effort cache key from the connection's database file path."""
    try:
        row = conn.execute("PRAGMA database_list").fetchone()
        if row is None:
            return "unknown"
        path = row[2] if len(row) > 2 else ""
        return path or "memory"
    except sqlite3.Error:
        return "unknown"


def _reset_cache_for_tests() -> None:
    """Test helper — drop the process-local cache."""
    _CACHE.clear()


__all__ = [
    "attach_corpus_snapshot",
    "attach_corpus_snapshot_with_conn",
    "current_corpus_snapshot",
    "current_corpus_snapshot_id",
]
