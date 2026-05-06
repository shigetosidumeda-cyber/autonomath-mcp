"""Tests for jpintel_mcp.db.id_translator (W3-12 fix).

The translator routes ``program_id`` between two ID spaces that share
``autonomath.db``:

  * ``am_entities.canonical_id`` — ``program:04_program_documents:000000:23_25d25bdfe8``
  * ``programs.unified_id``      — ``UNI-ext-b98165dd96``

We exercise both directions, the LRU cache, the identity passthroughs,
and the ``am_alias`` fallback path. The autonomath connection helper is
monkeypatched onto a tiny in-memory SQLite seeded with just enough rows
to drive each branch — keeps the test independent of the 9.4 GB live DB.
"""

from __future__ import annotations

import sqlite3

import pytest

from jpintel_mcp.db import id_translator

# ---------------------------------------------------------------------------
# Tiny seeded in-memory DB shared by the test session.
# ---------------------------------------------------------------------------


def _build_seeded_conn() -> sqlite3.Connection:
    """Return an in-memory sqlite with the two link surfaces the translator reads."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE entity_id_map (
            jpi_unified_id  TEXT NOT NULL,
            am_canonical_id TEXT NOT NULL,
            match_method    TEXT,
            confidence      REAL DEFAULT 1.0,
            PRIMARY KEY (jpi_unified_id, am_canonical_id)
        );
        CREATE TABLE am_alias (
            entity_table TEXT NOT NULL,
            canonical_id TEXT NOT NULL,
            alias        TEXT NOT NULL,
            alias_kind   TEXT
        );
        """
    )
    # Primary mapping (the W3-12 example).
    conn.execute(
        "INSERT INTO entity_id_map VALUES (?, ?, ?, ?)",
        (
            "UNI-ext-b98165dd96",
            "program:04_program_documents:000000:23_25d25bdfe8",
            "exact_name+pref",
            0.97,
        ),
    )
    # Lower-confidence rival row to verify ORDER BY confidence DESC picks the
    # canonical winner.
    conn.execute(
        "INSERT INTO entity_id_map VALUES (?, ?, ?, ?)",
        (
            "UNI-ext-b98165dd96",
            "program:noise:never_returned:00",
            "fuzzy",
            0.41,
        ),
    )
    # Second pair to verify cache hits stay correct across distinct keys.
    conn.execute(
        "INSERT INTO entity_id_map VALUES (?, ?, ?, ?)",
        (
            "UNI-jpi-a1b2c3",
            "program:99_other:000001:99_aabbccddee",
            "exact_name+pref",
            0.95,
        ),
    )
    # am_alias-only fallback: canonical → unified resolved without
    # entity_id_map presence.
    conn.execute(
        "INSERT INTO am_alias VALUES (?, ?, ?, ?)",
        (
            "am_entities",
            "program:fallback_only:000001:55_deadbeef00",
            "UNI-fallback-only-1",
            "unified_id",
        ),
    )
    conn.commit()
    return conn


@pytest.fixture(autouse=True)
def _patch_connect(monkeypatch):
    """Route id_translator._get_conn → seeded in-memory DB and clear caches.

    Autouse so every test starts with a fresh cache; otherwise the LRU
    pinned values from the previous test would mask wrong-direction
    regressions.
    """
    conn = _build_seeded_conn()
    monkeypatch.setattr(id_translator, "_get_conn", lambda: conn)
    id_translator.cache_clear()
    yield
    id_translator.cache_clear()
    conn.close()


# ---------------------------------------------------------------------------
# Direction 1 — UNI-... → program:...
# ---------------------------------------------------------------------------


def test_unified_to_canonical_returns_highest_confidence_link() -> None:
    canonical = id_translator.program_unified_to_canonical("UNI-ext-b98165dd96")
    assert canonical == "program:04_program_documents:000000:23_25d25bdfe8"


def test_unified_to_canonical_returns_none_for_unknown_id() -> None:
    assert id_translator.program_unified_to_canonical("UNI-does-not-exist") is None


def test_unified_to_canonical_rejects_canonical_shape_input() -> None:
    """Identity-direction protection: a ``program:`` shape must not flow here."""
    assert (
        id_translator.program_unified_to_canonical(
            "program:04_program_documents:000000:23_25d25bdfe8"
        )
        is None
    )


def test_unified_to_canonical_handles_empty_and_none() -> None:
    assert id_translator.program_unified_to_canonical("") is None
    assert id_translator.program_unified_to_canonical(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Direction 2 — program:... → UNI-...
# ---------------------------------------------------------------------------


def test_canonical_to_unified_via_entity_id_map() -> None:
    uni = id_translator.program_canonical_to_unified(
        "program:04_program_documents:000000:23_25d25bdfe8"
    )
    assert uni == "UNI-ext-b98165dd96"


def test_canonical_to_unified_falls_back_to_am_alias() -> None:
    """When entity_id_map has no link, am_alias should still resolve."""
    uni = id_translator.program_canonical_to_unified("program:fallback_only:000001:55_deadbeef00")
    assert uni == "UNI-fallback-only-1"


def test_canonical_to_unified_returns_none_for_unknown_id() -> None:
    assert (
        id_translator.program_canonical_to_unified("program:never_seen:000001:00_zzzzzzzzzz")
        is None
    )


def test_canonical_to_unified_rejects_unified_shape_input() -> None:
    assert id_translator.program_canonical_to_unified("UNI-ext-b98165dd96") is None


# ---------------------------------------------------------------------------
# normalize_program_id — the helper wave24 _impl modules call.
# ---------------------------------------------------------------------------


def test_normalize_program_id_unified_input_returns_both_forms() -> None:
    uni, canonical = id_translator.normalize_program_id("UNI-ext-b98165dd96")
    assert uni == "UNI-ext-b98165dd96"
    assert canonical == "program:04_program_documents:000000:23_25d25bdfe8"


def test_normalize_program_id_canonical_input_returns_both_forms() -> None:
    uni, canonical = id_translator.normalize_program_id(
        "program:04_program_documents:000000:23_25d25bdfe8"
    )
    assert uni == "UNI-ext-b98165dd96"
    assert canonical == "program:04_program_documents:000000:23_25d25bdfe8"


def test_normalize_program_id_unknown_id_preserves_input_slot() -> None:
    """Translation miss returns ``None`` for the *other* slot, original kept."""
    uni, canonical = id_translator.normalize_program_id("UNI-no-such-thing")
    assert uni == "UNI-no-such-thing"
    assert canonical is None

    uni2, canonical2 = id_translator.normalize_program_id("program:no:such:00_x")
    assert canonical2 == "program:no:such:00_x"
    assert uni2 is None


def test_normalize_program_id_garbage_returns_double_none() -> None:
    assert id_translator.normalize_program_id("garbage") == (None, None)
    assert id_translator.normalize_program_id("") == (None, None)
    assert id_translator.normalize_program_id(None) == (None, None)


def test_normalize_program_id_strips_whitespace() -> None:
    uni, canonical = id_translator.normalize_program_id("  UNI-ext-b98165dd96  ")
    assert uni == "UNI-ext-b98165dd96"
    assert canonical == "program:04_program_documents:000000:23_25d25bdfe8"


# ---------------------------------------------------------------------------
# LRU cache behavior.
# ---------------------------------------------------------------------------


def test_unified_to_canonical_cache_hit_increments_hits() -> None:
    """First call = miss, second call = hit. Confirms lru_cache is wired."""
    id_translator.cache_clear()
    id_translator.program_unified_to_canonical("UNI-ext-b98165dd96")
    info_after_first = id_translator.cache_info()["u_to_c"]
    # info tuple = (hits, misses, maxsize, currsize)
    assert info_after_first[0] == 0
    assert info_after_first[1] == 1

    id_translator.program_unified_to_canonical("UNI-ext-b98165dd96")
    info_after_second = id_translator.cache_info()["u_to_c"]
    assert info_after_second[0] == 1  # one cache hit on the repeat call
    assert info_after_second[1] == 1  # miss count unchanged


def test_canonical_to_unified_cache_hit_increments_hits() -> None:
    id_translator.cache_clear()
    cid = "program:04_program_documents:000000:23_25d25bdfe8"
    id_translator.program_canonical_to_unified(cid)
    id_translator.program_canonical_to_unified(cid)
    info = id_translator.cache_info()["c_to_u"]
    assert info[0] == 1
    assert info[1] == 1


def test_cache_clear_resets_counters() -> None:
    id_translator.program_unified_to_canonical("UNI-ext-b98165dd96")
    id_translator.program_unified_to_canonical("UNI-ext-b98165dd96")
    id_translator.cache_clear()
    info = id_translator.cache_info()["u_to_c"]
    assert info[0] == 0
    assert info[1] == 0
    assert info[3] == 0  # currsize → 0 after clear


def test_cache_isolates_distinct_keys() -> None:
    """Pulling key A then key B must not return A's value for B."""
    id_translator.cache_clear()
    a = id_translator.program_unified_to_canonical("UNI-ext-b98165dd96")
    b = id_translator.program_unified_to_canonical("UNI-jpi-a1b2c3")
    assert a == "program:04_program_documents:000000:23_25d25bdfe8"
    assert b == "program:99_other:000001:99_aabbccddee"
    assert a != b


# ---------------------------------------------------------------------------
# Resilience — missing connection / SQL error degrades to None, not raise.
# ---------------------------------------------------------------------------


def test_missing_connection_returns_none(monkeypatch) -> None:
    """When autonomath.db is unreachable the translator must NOT raise."""
    monkeypatch.setattr(id_translator, "_get_conn", lambda: None)
    id_translator.cache_clear()
    assert id_translator.program_unified_to_canonical("UNI-ext-b98165dd96") is None
    assert (
        id_translator.program_canonical_to_unified(
            "program:04_program_documents:000000:23_25d25bdfe8"
        )
        is None
    )
    assert id_translator.normalize_program_id("UNI-ext-b98165dd96") == (
        "UNI-ext-b98165dd96",
        None,
    )
