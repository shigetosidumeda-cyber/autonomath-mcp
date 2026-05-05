"""ID-space translator between ``am_entities.canonical_id`` and ``programs.unified_id``.

W3-12 finding (2026-05-04)
--------------------------

The 8.29 GB unified ``autonomath.db`` carries TWO disjoint identifier
spaces for one logical entity (a 補助金 / 制度 program):

  * ``am_entities.canonical_id`` — e.g. ``program:04_program_documents:000000:23_25d25bdfe8``
    Used by V4 EAV facts (``am_entity_facts.entity_id``), the
    annotation/validation/provenance trio, and the Evidence Graph
    surface.
  * ``jpi_programs.unified_id`` (= ``programs.unified_id`` mirror) —
    e.g. ``UNI-ext-b98165dd96``. Used by the Wave 24 substrate
    (``am_program_documents.program_unified_id``,
    ``am_program_combinations.program_a_unified_id``,
    ``am_program_calendar_12mo.program_unified_id`` etc.).

When an LLM agent walks ``_next_calls`` from one tool whose output is in
canonical-id space (e.g. ``get_provenance``) into a tool whose tables key
on unified-id (e.g. ``get_program_application_documents``), the call
silently returns an empty envelope — the SQL ``WHERE program_unified_id
= 'program:...'`` matches zero rows and the LLM has no signal that the
miss is an ID-space mismatch rather than a genuine "no documents" answer.

The fix is a thin, read-only, LRU-cached translator that the Wave 24
``_impl`` layer routes every incoming ``program_id`` through *before*
issuing SQL. Whichever form the agent passes, the SQL hits the right
form. The translator NEVER calls an LLM — pure SQLite SELECT against
``entity_id_map`` (mig 032 link table) with ``am_alias`` as a fallback
for canonical→unified resolution.

Design rules
------------

1. **Read-only.** Opens the existing per-thread RO connection from
   ``mcp.autonomath_tools.db.connect_autonomath`` so we share the page
   cache and the 300s busy_timeout setup.

2. **Pure SQL.** No LLM, no network. The functions are safe to call from
   inside any tool ``_impl`` without burning Anthropic budget.

3. **LRU-cached.** ``functools.lru_cache(maxsize=10000)`` per direction.
   The hot path (``recommend_programs_for_houjin`` → 10 program_ids →
   downstream calendar / docs / combinations) hits the cache after the
   first invocation. Cache lifetime is process-scoped — fine because
   ``entity_id_map`` is append-only at runtime; reconciliation runs
   offline via ``scripts/reconcile_program_entities.py``.

4. **Identity passthrough on already-correct form.** If a function is
   asked to translate ``X`` and ``X`` is already the desired shape, we
   return it as-is. This lets call-sites blindly invoke the translator
   without first sniffing the prefix.

5. **None on miss.** When no mapping exists, we return ``None`` rather
   than raising. The caller (``_normalize_program_id``) decides whether
   to fall back to the original input or short-circuit with an empty
   envelope. Honest sparse signal — see ``feedback_no_fake_data.md``.

Public surface
--------------

    program_unified_to_canonical(unified_id) -> str | None
    program_canonical_to_unified(canonical_id) -> str | None
    normalize_program_id(program_id) -> tuple[unified_id|None, canonical_id|None]

The third helper is what wave24 ``_impl`` modules import — it returns
both forms so the SQL can be written against whichever column the
target table uses without further branching.
"""
from __future__ import annotations

import logging
import sqlite3
from functools import lru_cache
from typing import Optional

logger = logging.getLogger("jpintel.db.id_translator")

# ---------------------------------------------------------------------------
# Shape detection
# ---------------------------------------------------------------------------

_UNIFIED_PREFIX = "UNI-"
_CANONICAL_DELIM = ":"


def _looks_like_unified(value: str) -> bool:
    """Return True when ``value`` is shaped like ``UNI-<hex>``.

    We do NOT enforce the trailing-hex length here — ingestion has
    historically written several variants (``UNI-ext-b98165dd96``,
    ``UNI-jpi-...``). The prefix check is sufficient for routing.
    """
    return isinstance(value, str) and value.startswith(_UNIFIED_PREFIX)


def _looks_like_canonical(value: str) -> bool:
    """Return True when ``value`` looks like ``<kind>:<...>:<...>``.

    ``am_entities.canonical_id`` always contains at least one ``:`` —
    e.g. ``program:04_program_documents:000000:23_25d25bdfe8``. We
    deliberately accept any ``<kind>`` prefix (program, corporate_entity,
    enforcement, ...) so the helper is reusable beyond the program
    cohort if the W3-12 surface expands later.
    """
    return isinstance(value, str) and _CANONICAL_DELIM in value


# ---------------------------------------------------------------------------
# Per-direction lookups (LRU-cached)
# ---------------------------------------------------------------------------


def _get_conn() -> sqlite3.Connection | None:
    """Lazy-open the autonomath RO connection. None when the file is missing.

    Imported lazily so this module does not pull ``sqlite-vec`` /
    Dockerfile-only paths at unit-test import time.
    """
    try:
        from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath
    except ImportError:
        return None
    try:
        return connect_autonomath()
    except (sqlite3.Error, FileNotFoundError) as exc:
        logger.debug("id_translator: autonomath.db unreachable: %s", exc)
        return None


@lru_cache(maxsize=10_000)
def program_unified_to_canonical(unified_id: str) -> Optional[str]:
    """Translate ``UNI-...`` → ``program:...`` via ``entity_id_map``.

    Returns the highest-confidence ``am_canonical_id`` for the given
    ``jpi_unified_id``. ``None`` when no link row exists OR the input
    is empty / wrong shape.
    """
    if not unified_id or not _looks_like_unified(unified_id):
        return None
    conn = _get_conn()
    if conn is None:
        return None
    try:
        row = conn.execute(
            """SELECT am_canonical_id
                 FROM entity_id_map
                WHERE jpi_unified_id = ?
                ORDER BY confidence DESC
                LIMIT 1""",
            (unified_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.debug("id_translator: u→c lookup failed for %r: %s",
                     unified_id, exc)
        return None
    if row is None:
        return None
    val = row[0] if not hasattr(row, "keys") else row["am_canonical_id"]
    return val if isinstance(val, str) and val else None


@lru_cache(maxsize=10_000)
def program_canonical_to_unified(canonical_id: str) -> Optional[str]:
    """Translate ``program:...`` → ``UNI-...``.

    Two-tier resolution:

      1. ``entity_id_map`` (highest-confidence reverse lookup). This is
         the primary source — populated by
         ``scripts/reconcile_program_entities.py``.
      2. ``am_alias`` fallback (entity_table='am_entities',
         alias_kind='unified_id'). Picks up cases where
         reconciliation has not yet fired but an alias row exists.

    Returns ``None`` when neither path yields a result.
    """
    if not canonical_id or not _looks_like_canonical(canonical_id):
        return None
    conn = _get_conn()
    if conn is None:
        return None
    # Path 1: entity_id_map reverse lookup.
    try:
        row = conn.execute(
            """SELECT jpi_unified_id
                 FROM entity_id_map
                WHERE am_canonical_id = ?
                ORDER BY confidence DESC
                LIMIT 1""",
            (canonical_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.debug("id_translator: c→u entity_id_map failed for %r: %s",
                     canonical_id, exc)
        row = None
    if row is not None:
        val = row[0] if not hasattr(row, "keys") else row["jpi_unified_id"]
        if isinstance(val, str) and val.startswith(_UNIFIED_PREFIX):
            return val
    # Path 2: am_alias fallback. Only fires when entity_id_map missed.
    try:
        row = conn.execute(
            """SELECT alias
                 FROM am_alias
                WHERE entity_table = 'am_entities'
                  AND canonical_id = ?
                  AND alias LIKE 'UNI-%'
                ORDER BY rowid
                LIMIT 1""",
            (canonical_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.debug("id_translator: c→u am_alias failed for %r: %s",
                     canonical_id, exc)
        return None
    if row is None:
        return None
    val = row[0] if not hasattr(row, "keys") else row["alias"]
    return val if isinstance(val, str) and val.startswith(_UNIFIED_PREFIX) else None


# ---------------------------------------------------------------------------
# Convenience: return both forms in one call.
# ---------------------------------------------------------------------------


def normalize_program_id(
    program_id: str | None,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve ``program_id`` (either form) to ``(unified_id, canonical_id)``.

    Either component is ``None`` when translation fails. The original
    form is always preserved in its slot so the caller can choose to
    fall back to "use whatever the user passed" without re-sniffing.

    Examples
    --------
    >>> normalize_program_id("UNI-ext-b98165dd96")
    ('UNI-ext-b98165dd96', 'program:04_program_documents:000000:23_25d25bdfe8')
    >>> normalize_program_id("program:04_program_documents:000000:23_25d25bdfe8")
    ('UNI-ext-b98165dd96', 'program:04_program_documents:000000:23_25d25bdfe8')
    >>> normalize_program_id("garbage")
    (None, None)
    >>> normalize_program_id(None)
    (None, None)
    """
    if not program_id or not isinstance(program_id, str):
        return (None, None)
    pid = program_id.strip()
    if not pid:
        return (None, None)
    if _looks_like_unified(pid):
        return (pid, program_unified_to_canonical(pid))
    if _looks_like_canonical(pid):
        return (program_canonical_to_unified(pid), pid)
    return (None, None)


# ---------------------------------------------------------------------------
# Cache management (operator-side helpers; tests call these too).
# ---------------------------------------------------------------------------


def cache_clear() -> None:
    """Clear both LRU caches. Used in tests + the offline reconcile cron."""
    program_unified_to_canonical.cache_clear()
    program_canonical_to_unified.cache_clear()


def cache_info() -> dict[str, tuple[int, int, int, int]]:
    """Return ``(hits, misses, maxsize, currsize)`` per direction."""
    return {
        "u_to_c": tuple(program_unified_to_canonical.cache_info()),
        "c_to_u": tuple(program_canonical_to_unified.cache_info()),
    }


__all__ = [
    "cache_clear",
    "cache_info",
    "normalize_program_id",
    "program_canonical_to_unified",
    "program_unified_to_canonical",
]
