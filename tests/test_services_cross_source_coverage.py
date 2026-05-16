"""Coverage tests for ``src/jpintel_mcp/services/cross_source.py``.

The module is small (63 stmts, 0% coverage baseline) and is the per-entity /
per-field cross-source agreement verdict layer behind ``/v1/cross_source/*``.
Tests use a real sqlite3 in-memory connection (NO MOCKED DB per CLAUDE.md
constraint) to exercise:

- ``_verdict()`` helper across all 4 branches.
- ``compute_cross_source_agreement`` happy paths (single field, all fields,
  agreement, disagreement, single source, no rows).
- ``_jpi_programs_fallback`` triggered when ``am_entity_facts`` is absent.
- ``refresh_confirming_source_counts`` over a populated EAV table including
  the missing-column degradation path and the limit clause.
"""

from __future__ import annotations

import sqlite3

import pytest

from jpintel_mcp.services.cross_source import (
    _jpi_programs_fallback,
    _verdict,
    compute_cross_source_agreement,
    refresh_confirming_source_counts,
)


def _connect_with_facts(*, with_csc_column: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    csc_col = ", confirming_source_count INTEGER" if with_csc_column else ""
    conn.execute(
        f"""
        CREATE TABLE am_entity_facts (
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            value TEXT,
            source_id TEXT{csc_col}
        )
        """
    )
    return conn


def _connect_with_jpi_programs(table_name: str = "jpi_programs") -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        f"""
        CREATE TABLE {table_name} (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT,
            source_url TEXT
        )
        """
    )
    return conn


# ---------------------------------------------------------------------------
# _verdict
# ---------------------------------------------------------------------------


def test_verdict_no_data_when_zero_sources() -> None:
    assert _verdict(0, 0) == "no_data"
    assert _verdict(-1, 5) == "no_data"


def test_verdict_single_source_branch() -> None:
    assert _verdict(1, 1) == "single_source"
    assert _verdict(1, 0) == "single_source"


def test_verdict_agreement_branch() -> None:
    assert _verdict(2, 1) == "agreement"
    assert _verdict(7, 1) == "agreement"


def test_verdict_disagreement_branch() -> None:
    assert _verdict(2, 2) == "disagreement"
    assert _verdict(4, 5) == "disagreement"


# ---------------------------------------------------------------------------
# compute_cross_source_agreement — agreement path
# ---------------------------------------------------------------------------


def test_compute_agreement_two_sources_same_value() -> None:
    conn = _connect_with_facts()
    conn.executemany(
        "INSERT INTO am_entity_facts (entity_id, field_name, value, source_id, "
        "confirming_source_count) VALUES (?, ?, ?, ?, ?)",
        [
            ("ent-1", "deadline", "2026-12-31", "src_nta", None),
            ("ent-1", "deadline", "2026-12-31", "src_meti", None),
        ],
    )
    out = compute_cross_source_agreement(conn, "ent-1")
    assert out is not None
    assert out["entity_id"] == "ent-1"
    assert out["summary"]["max_distinct_sources"] == 2
    assert out["summary"]["any_disagreement"] is False
    assert out["summary"]["verdict"] == "agreement"
    assert out["summary"]["human_label"].startswith("✓ 2 sources")
    assert out["fields"][0]["verdict"] == "agreement"


def test_compute_disagreement_two_sources_two_values() -> None:
    conn = _connect_with_facts()
    conn.executemany(
        "INSERT INTO am_entity_facts (entity_id, field_name, value, source_id, "
        "confirming_source_count) VALUES (?, ?, ?, ?, ?)",
        [
            ("ent-2", "amount_max_yen", "5000000", "src_nta", 2),
            ("ent-2", "amount_max_yen", "10000000", "src_meti", 2),
        ],
    )
    out = compute_cross_source_agreement(conn, "ent-2")
    assert out is not None
    assert out["summary"]["any_disagreement"] is True
    assert out["summary"]["verdict"] == "disagreement"
    assert "⚠" in out["summary"]["human_label"]
    field = out["fields"][0]
    assert field["confirming_source_count"] == 2
    assert field["distinct_values"] == 2


def test_compute_single_source_single_field() -> None:
    conn = _connect_with_facts()
    conn.execute(
        "INSERT INTO am_entity_facts (entity_id, field_name, value, source_id, "
        "confirming_source_count) VALUES (?, ?, ?, ?, ?)",
        ("ent-3", "deadline", "2027-03-31", "src_nta", 1),
    )
    out = compute_cross_source_agreement(conn, "ent-3")
    assert out is not None
    assert out["summary"]["verdict"] == "single_source"
    assert out["summary"]["human_label"] == "single source"


def test_compute_field_filter_narrows_breakdown() -> None:
    conn = _connect_with_facts()
    conn.executemany(
        "INSERT INTO am_entity_facts (entity_id, field_name, value, source_id, "
        "confirming_source_count) VALUES (?, ?, ?, ?, ?)",
        [
            ("ent-4", "deadline", "2026-09-30", "src_a", None),
            ("ent-4", "deadline", "2026-09-30", "src_b", None),
            ("ent-4", "amount_max_yen", "1000000", "src_a", None),
        ],
    )
    out = compute_cross_source_agreement(conn, "ent-4", field_name="amount_max_yen")
    assert out is not None
    # Filter narrowed the breakdown to one field.
    assert len(out["fields"]) == 1
    assert out["fields"][0]["field"] == "amount_max_yen"


def test_compute_returns_none_when_no_facts_no_program() -> None:
    conn = _connect_with_facts()
    out = compute_cross_source_agreement(conn, "ent-missing")
    # Falls back into jpi_programs lookup which also raises → None.
    assert out is None


def test_compute_degrades_when_confirming_source_count_column_missing() -> None:
    # Simulate pre-mig-101 schema: no confirming_source_count column.
    conn = _connect_with_facts(with_csc_column=False)
    conn.executemany(
        "INSERT INTO am_entity_facts (entity_id, field_name, value, source_id) VALUES (?, ?, ?, ?)",
        [
            ("ent-5", "deadline", "2026-12-31", "src_a"),
            ("ent-5", "deadline", "2026-12-31", "src_b"),
        ],
    )
    out = compute_cross_source_agreement(conn, "ent-5")
    assert out is not None
    field = out["fields"][0]
    # column_csc unavailable → confirming_source_count falls back to live count.
    assert field["confirming_source_count"] == field["distinct_sources"] == 2


# ---------------------------------------------------------------------------
# _jpi_programs_fallback
# ---------------------------------------------------------------------------


def test_jpi_programs_fallback_returns_single_source_when_url_present() -> None:
    conn = _connect_with_jpi_programs()
    conn.execute(
        "INSERT INTO jpi_programs (unified_id, primary_name, source_url) VALUES (?, ?, ?)",
        ("prog-1", "テスト補助金", "https://www.meti.go.jp/policy/program/1"),
    )
    out = _jpi_programs_fallback(conn, "prog-1")
    assert out is not None
    assert out["summary"]["verdict"] == "single_source"
    assert out["summary"]["max_distinct_sources"] == 1
    assert "_meta" in out and "jpi_programs" in out["_meta"]["fallback"]


def test_jpi_programs_fallback_no_url_yields_no_data() -> None:
    conn = _connect_with_jpi_programs()
    conn.execute(
        "INSERT INTO jpi_programs (unified_id, primary_name, source_url) VALUES (?, ?, ?)",
        ("prog-2", "テスト2", ""),
    )
    out = _jpi_programs_fallback(conn, "prog-2")
    assert out is not None
    assert out["summary"]["verdict"] == "no_data"
    assert out["summary"]["max_distinct_sources"] == 0


def test_jpi_programs_fallback_missing_row_returns_none() -> None:
    conn = _connect_with_jpi_programs()
    out = _jpi_programs_fallback(conn, "prog-missing")
    assert out is None


def test_jpi_programs_fallback_uses_programs_table_when_jpi_absent() -> None:
    conn = _connect_with_jpi_programs(table_name="programs")
    conn.execute(
        "INSERT INTO programs (unified_id, primary_name, source_url) VALUES (?, ?, ?)",
        ("prog-3", "name3", "https://example.com"),
    )
    out = _jpi_programs_fallback(conn, "prog-3")
    assert out is not None
    assert out["summary"]["verdict"] == "single_source"


def test_jpi_programs_fallback_returns_none_when_no_tables() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    out = _jpi_programs_fallback(conn, "prog-X")
    assert out is None


def test_compute_routes_into_fallback_when_am_entity_facts_missing() -> None:
    conn = _connect_with_jpi_programs()
    conn.execute(
        "INSERT INTO jpi_programs (unified_id, primary_name, source_url) VALUES (?, ?, ?)",
        ("prog-fb", "name", "https://nta.go.jp/x"),
    )
    out = compute_cross_source_agreement(conn, "prog-fb")
    assert out is not None
    assert out["summary"]["max_distinct_sources"] == 1
    assert out["_meta"]["fallback"].startswith("jpi_programs")


# ---------------------------------------------------------------------------
# refresh_confirming_source_counts
# ---------------------------------------------------------------------------


def test_refresh_confirming_counts_updates_rows() -> None:
    conn = _connect_with_facts()
    conn.executemany(
        "INSERT INTO am_entity_facts (entity_id, field_name, value, source_id, "
        "confirming_source_count) VALUES (?, ?, ?, ?, ?)",
        [
            ("ent-A", "deadline", "2026-12-31", "src_a", None),
            ("ent-A", "deadline", "2026-12-31", "src_b", None),
        ],
    )
    out = refresh_confirming_source_counts(conn)
    assert out["checked"] == 1
    assert out["updated"] == 2  # 2 rows of (ent-A, deadline)
    rows = conn.execute(
        "SELECT confirming_source_count FROM am_entity_facts WHERE entity_id = 'ent-A'"
    ).fetchall()
    assert all(r["confirming_source_count"] == 2 for r in rows)


def test_refresh_confirming_counts_detects_mismatch() -> None:
    conn = _connect_with_facts()
    conn.executemany(
        "INSERT INTO am_entity_facts (entity_id, field_name, value, source_id, "
        "confirming_source_count) VALUES (?, ?, ?, ?, ?)",
        [
            ("ent-B", "deadline", "2026-12-31", "src_a", 99),
            ("ent-B", "deadline", "2026-12-31", "src_b", 99),
        ],
    )
    out = refresh_confirming_source_counts(conn)
    assert out["mismatches"] == 1


def test_refresh_confirming_counts_respects_limit() -> None:
    conn = _connect_with_facts()
    conn.executemany(
        "INSERT INTO am_entity_facts (entity_id, field_name, value, source_id) VALUES (?, ?, ?, ?)",
        [
            ("ent-1", "f", "x", "s"),
            ("ent-2", "f", "x", "s"),
            ("ent-3", "f", "x", "s"),
        ],
    )
    out = refresh_confirming_source_counts(conn, limit_entities=2)
    # Limit clamps the GROUP BY scan to 2 rows.
    assert out["checked"] == 2


def test_refresh_confirming_counts_returns_baseline_when_table_missing() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    out = refresh_confirming_source_counts(conn)
    assert out == {"checked": 0, "updated": 0, "mismatches": 0}


def test_refresh_confirming_counts_baseline_when_column_missing() -> None:
    # When confirming_source_count column is absent, the GROUP BY SELECT itself
    # raises OperationalError → function returns the empty baseline (early exit).
    conn = _connect_with_facts(with_csc_column=False)
    conn.execute(
        "INSERT INTO am_entity_facts (entity_id, field_name, value, source_id) VALUES (?, ?, ?, ?)",
        ("ent-X", "f", "v", "s"),
    )
    out = refresh_confirming_source_counts(conn)
    assert out == {"checked": 0, "updated": 0, "mismatches": 0}


@pytest.mark.parametrize(
    "ds, vs, expected",
    [
        (0, 0, "no_data"),
        (1, 1, "single_source"),
        (3, 1, "agreement"),
        (3, 2, "disagreement"),
    ],
)
def test_verdict_parametric(ds: int, vs: int, expected: str) -> None:
    assert _verdict(ds, vs) == expected
