"""W5-5 NO-GO blocker #1-4 — Wave24 column-name regression smokes.

The first-half wave24 tools historically SELECTed columns that did not
exist on their backing tables, causing every call to return
``OperationalError: no such column: ...`` packaged as
``db_unavailable``. Each `_impl` was patched to align with the actual
schema in `scripts/migrations/wave24_{127,129,131,133}.sql` and to
safe-gate optional columns (e.g. `am_compat_matrix.visibility` from
`wave24_107`).

These smokes pin the four touched tool bodies so the regressions cannot
recur:

  #98  find_combinable_programs        — no `visibility`/`evidence_json` on
                                         am_program_combinations; visibility
                                         filter only applies when joinable.
  #100 forecast_enforcement_risk       — incident_count + percentile_in_industry
                                         + trend_3yr_json (NOT enforcement_count_5y
                                         / propagation_probability / sample_authorities
                                         / evidence_url).
  #102 get_houjin_360_snapshot_history — payload_json (NOT snapshot_json /
                                         state_json).
  #104 infer_invoice_buyer_seller      — seller_houjin_bangou /
                                         buyer_houjin_bangou + source_url_json
                                         (NOT seller / buyer / evidence_url).

Each test seeds the minimum schema + a few rows, invokes the impl, and
asserts NO ``error`` envelope returned.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Schema-creation helpers — mirror the four migration files exactly.
# --------------------------------------------------------------------------- #


def _create_program_combinations(conn: sqlite3.Connection) -> None:
    """Mirror migration wave24_127."""
    conn.executescript(
        """
        CREATE TABLE am_program_combinations (
            pair_id              INTEGER PRIMARY KEY AUTOINCREMENT,
            program_a_unified_id TEXT NOT NULL,
            program_b_unified_id TEXT NOT NULL,
            combinable           INTEGER NOT NULL CHECK (combinable IN (0, 1, 2)),
            confidence           TEXT,
            reason               TEXT,
            source_url           TEXT,
            source_kind          TEXT,
            computed_at          TEXT NOT NULL DEFAULT (datetime('now')),
            CHECK (program_a_unified_id < program_b_unified_id),
            UNIQUE (program_a_unified_id, program_b_unified_id)
        );
        """
    )


def _create_compat_matrix_with_visibility(conn: sqlite3.Connection) -> None:
    """Minimal `am_compat_matrix` carrying visibility (post-wave24_107)."""
    conn.executescript(
        """
        CREATE TABLE am_compat_matrix (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            program_a_unified_id TEXT NOT NULL,
            program_b_unified_id TEXT NOT NULL,
            inferred_only        INTEGER NOT NULL DEFAULT 1,
            source_url           TEXT,
            visibility           TEXT NOT NULL DEFAULT 'internal'
        );
        """
    )


def _create_enforcement_industry_risk(conn: sqlite3.Connection) -> None:
    """Mirror migration wave24_129."""
    conn.executescript(
        """
        CREATE TABLE am_enforcement_industry_risk (
            risk_id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            jsic_major              TEXT NOT NULL,
            jsic_middle             TEXT,
            region_code             TEXT,
            risk_category           TEXT NOT NULL,
            incident_count          INTEGER NOT NULL DEFAULT 0,
            total_amount_yen        INTEGER,
            percentile_in_industry  REAL,
            trend_3yr_json          TEXT,
            source_snapshot_id      TEXT,
            computed_at             TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (jsic_major, jsic_middle, region_code, risk_category)
        );
        """
    )


def _create_invoice_graph(conn: sqlite3.Connection) -> None:
    """Mirror migration wave24_133."""
    conn.executescript(
        """
        CREATE TABLE am_invoice_buyer_seller_graph (
            edge_id              INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_houjin_bangou TEXT NOT NULL,
            buyer_houjin_bangou  TEXT NOT NULL,
            confidence           REAL NOT NULL,
            confidence_band      TEXT NOT NULL,
            inferred_industry    TEXT,
            evidence_kind        TEXT NOT NULL,
            evidence_count       INTEGER NOT NULL DEFAULT 1,
            source_url_json      TEXT,
            first_seen_at        TEXT,
            last_seen_at         TEXT,
            computed_at          TEXT NOT NULL DEFAULT (datetime('now')),
            CHECK (seller_houjin_bangou != buyer_houjin_bangou)
        );
        """
    )


def _create_houjin_360_snapshot(conn: sqlite3.Connection) -> None:
    """Mirror migration wave24_131."""
    conn.executescript(
        """
        CREATE TABLE am_houjin_360_snapshot (
            snapshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            houjin_bangou   TEXT NOT NULL,
            snapshot_month  TEXT NOT NULL,
            payload_json    TEXT,
            computed_at     TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (houjin_bangou, snapshot_month)
        );
        """
    )


# --------------------------------------------------------------------------- #
# Fixture: build a tmp autonomath.db with all four wave24 tables.
# --------------------------------------------------------------------------- #


@pytest.fixture()
def seeded_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tmp autonomath.db with wave24_{127,129,131,133} schemas + a few rows."""
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        _create_program_combinations(conn)
        _create_compat_matrix_with_visibility(conn)
        _create_enforcement_industry_risk(conn)
        _create_invoice_graph(conn)
        _create_houjin_360_snapshot(conn)

        # Seed one combinable pair (sourced) + one heuristic pair.
        conn.executemany(
            """
            INSERT INTO am_program_combinations
              (program_a_unified_id, program_b_unified_id, combinable,
               confidence, reason, source_url, source_kind)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "UNI-AAAA",
                    "UNI-BBBB",
                    1,
                    "high",
                    "両者は補完関係",
                    "https://example.go.jp/notice/1",
                    "compat_matrix",
                ),
                ("UNI-AAAA", "UNI-CCCC", 0, "medium", "排他規定 §3", None, "exclusion_rule"),
            ],
        )
        # Seed compat_matrix rows so the visibility join is exercised.
        conn.executemany(
            """
            INSERT INTO am_compat_matrix
              (program_a_unified_id, program_b_unified_id, inferred_only,
               source_url, visibility)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("UNI-AAAA", "UNI-BBBB", 0, "https://example.go.jp/notice/1", "public"),
                ("UNI-AAAA", "UNI-CCCC", 1, None, "internal"),
            ],
        )
        # Seed enforcement risk rows.
        conn.executemany(
            """
            INSERT INTO am_enforcement_industry_risk
              (jsic_major, jsic_middle, region_code, risk_category,
               incident_count, total_amount_yen, percentile_in_industry,
               trend_3yr_json, source_snapshot_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "D",
                    "06",
                    "13000",
                    "fine",
                    12,
                    4_500_000,
                    0.82,
                    json.dumps({"y2024": 4, "y2025": 3, "y2026": 5}),
                    "snap-2026-04",
                ),
                ("D", None, "JP-NATION", "subsidy_exclude", 3, 0, 0.40, None, "snap-2026-04"),
            ],
        )
        # Seed invoice graph rows.
        conn.executemany(
            """
            INSERT INTO am_invoice_buyer_seller_graph
              (seller_houjin_bangou, buyer_houjin_bangou, confidence,
               confidence_band, inferred_industry, evidence_kind,
               evidence_count, source_url_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "4010001234567",
                    "5010001234568",
                    0.92,
                    "high",
                    "D",
                    "public_disclosure",
                    3,
                    json.dumps(["https://example.go.jp/disclosure/a"]),
                ),
                (
                    "4010001234567",
                    "6010001234569",
                    0.55,
                    "medium",
                    "K",
                    "joint_adoption",
                    1,
                    json.dumps(["https://example.go.jp/adoption/b"]),
                ),
            ],
        )
        # Seed houjin 360 snapshot rows.
        conn.executemany(
            """
            INSERT INTO am_houjin_360_snapshot
              (houjin_bangou, snapshot_month, payload_json)
            VALUES (?, ?, ?)
            """,
            [
                ("4010001234567", "2026-02", json.dumps({"adoption_count": 1, "risk_score": 0.10})),
                ("4010001234567", "2026-03", json.dumps({"adoption_count": 2, "risk_score": 0.12})),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    return db_path


# --------------------------------------------------------------------------- #
# Late-bind helpers (impl picks up AUTONOMATH_DB_PATH at first use).
# --------------------------------------------------------------------------- #


def _impls():
    from jpintel_mcp.mcp.autonomath_tools.wave24_tools_first_half import (
        _find_combinable_programs_impl,
        _forecast_enforcement_risk_impl,
        _get_houjin_360_snapshot_history_impl,
        _infer_invoice_buyer_seller_impl,
    )

    return (
        _find_combinable_programs_impl,
        _forecast_enforcement_risk_impl,
        _get_houjin_360_snapshot_history_impl,
        _infer_invoice_buyer_seller_impl,
    )


# --------------------------------------------------------------------------- #
# #98 find_combinable_programs
# --------------------------------------------------------------------------- #


def test_find_combinable_programs_no_operational_error(seeded_db: Path) -> None:
    impl = _impls()[0]
    out = impl(program_id="UNI-AAAA", visibility="public", limit=20)
    assert "error" not in out, f"unexpected error envelope: {out}"
    assert out["program_id"] == "UNI-AAAA"
    assert out["visibility"] == "public"
    # visibility filter joined through am_compat_matrix.visibility
    assert out["visibility_basis"] == "compat_matrix.visibility"
    # Public visibility filters down to the sourced pair only.
    partner_ids = sorted(r["partner_program_id"] for r in out["results"])
    assert partner_ids == ["UNI-BBBB"]
    assert out["results"][0]["source_kind"] == "compat_matrix"


def test_find_combinable_programs_visibility_all_returns_both(
    seeded_db: Path,
) -> None:
    impl = _impls()[0]
    out = impl(program_id="UNI-AAAA", visibility="all", limit=20)
    assert "error" not in out, f"unexpected error envelope: {out}"
    partner_ids = sorted(r["partner_program_id"] for r in out["results"])
    assert partner_ids == ["UNI-BBBB", "UNI-CCCC"]


# --------------------------------------------------------------------------- #
# #100 forecast_enforcement_risk
# --------------------------------------------------------------------------- #


def test_forecast_enforcement_risk_no_operational_error(seeded_db: Path) -> None:
    impl = _impls()[1]
    out = impl(jsic_major="D", limit=20)
    assert "error" not in out, f"unexpected error envelope: {out}"
    assert out["total"] == 2
    # Highest percentile_in_industry first.
    assert out["results"][0]["percentile_in_industry"] == 0.82
    assert out["results"][0]["incident_count"] == 12
    assert isinstance(out["results"][0]["trend_3yr"], dict)
    assert out["results"][0]["trend_3yr"]["y2025"] == 3


def test_forecast_enforcement_risk_filter_by_region(seeded_db: Path) -> None:
    impl = _impls()[1]
    out = impl(jsic_major="D", region_code="13000", limit=20)
    assert "error" not in out, f"unexpected error envelope: {out}"
    assert out["total"] == 1
    assert out["results"][0]["region_code"] == "13000"
    assert out["results"][0]["risk_category"] == "fine"


# --------------------------------------------------------------------------- #
# #102 get_houjin_360_snapshot_history (covered by test_wave24_get_houjin_360
# already; this is a redundant smoke pinned next to the other three).
# --------------------------------------------------------------------------- #


def test_get_houjin_360_snapshot_history_no_operational_error(
    seeded_db: Path,
) -> None:
    impl = _impls()[2]
    out = impl(houjin_bangou="4010001234567", months=12)
    assert "error" not in out, f"unexpected error envelope: {out}"
    assert out["total"] == 2
    months = [r["snapshot_month"] for r in out["results"]]
    assert months == ["2026-03", "2026-02"]  # newest first


# --------------------------------------------------------------------------- #
# #104 infer_invoice_buyer_seller
# --------------------------------------------------------------------------- #


def test_infer_invoice_buyer_seller_no_operational_error(seeded_db: Path) -> None:
    impl = _impls()[3]
    out = impl(houjin_bangou="4010001234567", direction="seller", limit=50)
    assert "error" not in out, f"unexpected error envelope: {out}"
    assert out["total"] == 2
    # Highest confidence first.
    assert out["results"][0]["confidence"] == 0.92
    # source_url_json was decoded into evidence_urls (list of citation URLs).
    assert isinstance(out["results"][0]["evidence_urls"], list)
    assert out["results"][0]["evidence_urls"][0].startswith("https://")
    # Both rows have partner_role='buyer' under direction='seller'.
    for r in out["results"]:
        assert r["partner_role"] == "buyer"


def test_infer_invoice_buyer_seller_both_directions(seeded_db: Path) -> None:
    impl = _impls()[3]
    # Houjin appears only as seller in the seed, so 'both' still returns 2.
    out = impl(houjin_bangou="4010001234567", direction="both", limit=50)
    assert "error" not in out, f"unexpected error envelope: {out}"
    assert out["total"] == 2
