"""W8-5 finding — Wave24 residual column-name regression smokes.

Three additional `_impl`s carried column-name drift past the W5-5
remediation pass and were emitting ``OperationalError: no such column``
envelopes on every invocation:

  #99  get_program_calendar_12mo      — SELECTed `month` / `round_label`
                                        on `am_program_calendar_12mo`,
                                        whose schema (migration
                                        wave24_128) actually exposes
                                        `month_start` + `round_id_json`.
  #105 match_programs_by_capital      — SELECTed `jsic_major` /
                                        `avg_amount_yen` on
                                        `am_capital_band_program_match`,
                                        whose schema (migration
                                        wave24_134) actually exposes
                                        `capital_band` (CHECK-bounded)
                                        + `avg_amount_man_yen` and has
                                        NO jsic_major column.
                                        `_capital_band_for_yen` also
                                        emitted band labels (`lt_1m`
                                        etc.) that the migration's
                                        CHECK rejected — re-aligned
                                        to `under_1m` / `1m_to_3m` /
                                        … / `1b_plus`.
  #109 find_programs_by_jsic          — SELECT WHERE `excluded = 0`
                                        on `jpi_programs`. Live prod
                                        schema HAS the column (default
                                        0), so this never crashed in
                                        prod; the regression was that
                                        a partial test DB without the
                                        column would crash. Hardened
                                        via `_column_exists` gating.

These smokes seed the minimum schema for each table, invoke the impl,
and assert NO ``error`` envelope (in particular no `db_unavailable` /
`no such column` regressions).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Schema-creation helpers — mirror the live migrations exactly.
# --------------------------------------------------------------------------- #


def _create_program_calendar_12mo(conn: sqlite3.Connection) -> None:
    """Mirror migration wave24_128_am_program_calendar_12mo.sql."""
    conn.executescript(
        """
        CREATE TABLE am_program_calendar_12mo (
            program_unified_id TEXT NOT NULL,
            month_start        TEXT NOT NULL,
            is_open            INTEGER NOT NULL CHECK (is_open IN (0, 1)),
            deadline           TEXT,
            round_id_json      TEXT,
            notes              TEXT,
            computed_at        TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (program_unified_id, month_start)
        );
        """
    )


def _create_application_round(conn: sqlite3.Connection) -> None:
    """Minimal `am_application_round` for round_id → round_label join."""
    conn.executescript(
        """
        CREATE TABLE am_application_round (
            round_id              INTEGER PRIMARY KEY,
            program_entity_id     TEXT NOT NULL,
            round_label           TEXT NOT NULL,
            round_seq             INTEGER,
            application_open_date TEXT,
            application_close_date TEXT,
            announced_date        TEXT,
            disbursement_start_date TEXT,
            budget_yen            INTEGER,
            status                TEXT,
            source_url            TEXT,
            source_fetched_at     TEXT
        );
        """
    )


def _create_capital_band_program_match(conn: sqlite3.Connection) -> None:
    """Mirror migration wave24_134_am_capital_band_program_match.sql.

    Note: the live migration's CHECK constraint enforces the 9-band
    enum (`under_1m` .. `1b_plus`). Tests must seed band labels that
    pass this CHECK or the INSERT itself will trip the regression.
    """
    conn.executescript(
        """
        CREATE TABLE am_capital_band_program_match (
            match_id             INTEGER PRIMARY KEY AUTOINCREMENT,
            capital_band         TEXT NOT NULL CHECK (capital_band IN (
                                    'under_1m','1m_to_3m','3m_to_5m','5m_to_10m',
                                    '10m_to_50m','50m_to_100m','100m_to_300m',
                                    '300m_to_1b','1b_plus'
                                 )),
            program_unified_id   TEXT NOT NULL,
            adoption_count       INTEGER NOT NULL DEFAULT 0,
            adoption_rate        REAL,
            avg_amount_man_yen   REAL,
            percentile_in_band   REAL,
            sample_size          INTEGER NOT NULL DEFAULT 0,
            computed_at          TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (capital_band, program_unified_id)
        );
        """
    )


def _create_jpi_programs(conn: sqlite3.Connection) -> None:
    """Minimal `jpi_programs` carrying the live `excluded` column +
    the wave24_113b jsic_* columns so the find_programs_by_jsic
    impl exercises the full WHERE chain."""
    conn.executescript(
        """
        CREATE TABLE jpi_programs (
            unified_id        TEXT PRIMARY KEY,
            primary_name      TEXT NOT NULL,
            tier              TEXT,
            prefecture        TEXT,
            authority_name    TEXT,
            amount_max_man_yen REAL,
            source_url        TEXT,
            source_fetched_at TEXT,
            excluded          INTEGER DEFAULT 0,
            jsic_major        TEXT,
            jsic_middle       TEXT,
            jsic_minor        TEXT,
            updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )


# --------------------------------------------------------------------------- #
# Fixture: tmp autonomath.db with the three schemas + minimum rows.
# --------------------------------------------------------------------------- #


@pytest.fixture()
def seeded_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a tmp autonomath.db carrying the three wave24 tables that
    triggered the W8-5 finding, then point AUTONOMATH_DB_PATH at it."""
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _create_program_calendar_12mo(conn)
        _create_application_round(conn)
        _create_capital_band_program_match(conn)
        _create_jpi_programs(conn)

        # Seed two calendar months for one program; one references a
        # round_id that we also seed in am_application_round so the
        # impl resolves a round_label, the other has no rounds (notes
        # only) so we exercise the empty-rounds branch.
        conn.execute(
            "INSERT INTO am_application_round "
            "(round_id, program_entity_id, round_label, round_seq, "
            "application_open_date, application_close_date, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (101, "UNI-CAL-1", "令和8年度 第1回", 1, "2026-05-01", "2026-06-30", "open"),
        )
        conn.executemany(
            """
            INSERT INTO am_program_calendar_12mo
              (program_unified_id, month_start, is_open, deadline,
               round_id_json, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("UNI-CAL-1", "2026-05-01", 1, "2026-06-30", json.dumps([101]), "公募中"),
                ("UNI-CAL-1", "2026-06-01", 1, "2026-06-30", json.dumps([101]), "締切月"),
                ("UNI-CAL-1", "2026-07-01", 0, None, None, "次回 8月"),
            ],
        )

        # Seed two capital-band rows in the 5m_to_10m band that
        # `_capital_band_for_yen(5_000_000)` now correctly maps to.
        conn.executemany(
            """
            INSERT INTO am_capital_band_program_match
              (capital_band, program_unified_id, adoption_count,
               adoption_rate, avg_amount_man_yen,
               percentile_in_band, sample_size)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("5m_to_10m", "UNI-CAP-A", 12, 0.40, 350.0, 0.85, 30),
                ("5m_to_10m", "UNI-CAP-B", 8, 0.27, 220.0, 0.55, 30),
                ("10m_to_50m", "UNI-CAP-C", 5, 0.15, 500.0, 0.30, 33),
            ],
        )

        # Seed jpi_programs rows in JSIC D for the find_programs_by_jsic
        # filter. One excluded=1 row to verify the excluded-gate filter.
        conn.executemany(
            """
            INSERT INTO jpi_programs
              (unified_id, primary_name, tier, prefecture, authority_name,
               amount_max_man_yen, source_url, source_fetched_at, excluded,
               jsic_major)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "UNI-JSIC-D-1",
                    "建設DX補助金",
                    "S",
                    "東京都",
                    "国土交通省",
                    1000.0,
                    "https://example.go.jp/jsic/d1",
                    "2026-04-01",
                    0,
                    "D",
                ),
                (
                    "UNI-JSIC-D-2",
                    "建築物省エネ補助金",
                    "A",
                    "東京都",
                    "国土交通省",
                    500.0,
                    "https://example.go.jp/jsic/d2",
                    "2026-04-01",
                    0,
                    "D",
                ),
                (
                    "UNI-JSIC-D-X",
                    "撤回された建設補助金",
                    "X",
                    "東京都",
                    "国土交通省",
                    0.0,
                    "https://example.go.jp/jsic/dX",
                    "2026-04-01",
                    1,
                    "D",
                ),
                (
                    "UNI-JSIC-E-1",
                    "ものづくり補助金",
                    "S",
                    "東京都",
                    "経済産業省",
                    1250.0,
                    "https://example.go.jp/jsic/e1",
                    "2026-04-01",
                    0,
                    "E",
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    return db_path


# --------------------------------------------------------------------------- #
# Late-bind helpers (impls pick up AUTONOMATH_DB_PATH at first connect).
# --------------------------------------------------------------------------- #


def _impls():
    from jpintel_mcp.mcp.autonomath_tools.wave24_tools_first_half import (
        _capital_band_for_yen,
        _get_program_calendar_12mo_impl,
        _match_programs_by_capital_impl,
    )
    from jpintel_mcp.mcp.autonomath_tools.wave24_tools_second_half import (
        _find_programs_by_jsic_impl,
    )

    return (
        _get_program_calendar_12mo_impl,
        _match_programs_by_capital_impl,
        _find_programs_by_jsic_impl,
        _capital_band_for_yen,
    )


# --------------------------------------------------------------------------- #
# #99 get_program_calendar_12mo
# --------------------------------------------------------------------------- #


def test_get_program_calendar_12mo_no_operational_error(seeded_db: Path) -> None:
    impl = _impls()[0]
    out = impl(program_id="UNI-CAL-1", limit=12)
    assert "error" not in out, f"unexpected error envelope: {out}"
    assert out["program_id"] == "UNI-CAL-1"
    assert out["total"] == 3
    months = [r["month"] for r in out["results"]]
    assert months == ["2026-05-01", "2026-06-01", "2026-07-01"]
    # round_label resolved from round_id_json → am_application_round join.
    assert out["results"][0]["round_label"] == "令和8年度 第1回"
    assert out["results"][0]["round_ids"] == [101]
    # Empty round_id_json branch: round_label None, round_ids [].
    assert out["results"][2]["round_label"] is None
    assert out["results"][2]["round_ids"] == []
    assert out["results"][2]["notes"] == "次回 8月"


def test_get_program_calendar_12mo_unknown_program_empty(seeded_db: Path) -> None:
    impl = _impls()[0]
    out = impl(program_id="UNI-DOES-NOT-EXIST", limit=12)
    assert "error" not in out, f"unexpected error envelope: {out}"
    assert out["total"] == 0
    assert out["results"] == []


# --------------------------------------------------------------------------- #
# #105 match_programs_by_capital
# --------------------------------------------------------------------------- #


def test_match_programs_by_capital_no_operational_error(seeded_db: Path) -> None:
    impl = _impls()[1]
    out = impl(capital_yen=5_000_000, limit=20)
    assert "error" not in out, f"unexpected error envelope: {out}"
    assert out["capital_band"] == "5m_to_10m"
    # Two seeded rows in the 5m_to_10m band.
    assert out["total"] == 2
    # Highest adoption_rate first.
    assert out["results"][0]["program_id"] == "UNI-CAP-A"
    assert out["results"][0]["adoption_rate"] == 0.40
    # avg_amount_man_yen exposed verbatim, plus convenience yen field.
    assert out["results"][0]["avg_amount_man_yen"] == 350.0
    assert out["results"][0]["avg_amount_yen"] == 3_500_000
    assert out["results"][0]["percentile_in_band"] == 0.85
    assert out["results"][0]["sample_size"] == 30
    # jsic_major column absent in this DB → NULL passthrough.
    assert out["results"][0]["jsic_major"] is None


def test_match_programs_by_capital_jsic_filter_dropped_gracefully(
    seeded_db: Path,
) -> None:
    """jsic_major filter must NOT crash when the column is absent."""
    impl = _impls()[1]
    out = impl(capital_yen=5_000_000, jsic_major="D", limit=20)
    assert "error" not in out, f"unexpected error envelope: {out}"
    # All same-band rows still returned (filter was silently dropped).
    assert out["total"] == 2
    assert out["data_quality"]["jsic_filter_applied"] is False


def test_capital_band_labels_match_check_constraint(seeded_db: Path) -> None:
    """`_capital_band_for_yen` MUST emit only the 9 CHECK-allowed labels."""
    band_for = _impls()[3]
    allowed = {
        "under_1m",
        "1m_to_3m",
        "3m_to_5m",
        "5m_to_10m",
        "10m_to_50m",
        "50m_to_100m",
        "100m_to_300m",
        "300m_to_1b",
        "1b_plus",
    }
    samples = [
        500_000,
        2_000_000,
        4_000_000,
        7_000_000,
        20_000_000,
        70_000_000,
        200_000_000,
        500_000_000,
        2_000_000_000,
    ]
    for n in samples:
        assert band_for(n) in allowed, f"{n} → {band_for(n)} not in CHECK enum"


# --------------------------------------------------------------------------- #
# #109 find_programs_by_jsic — `excluded` gating
# --------------------------------------------------------------------------- #


def test_find_programs_by_jsic_no_operational_error(seeded_db: Path) -> None:
    impl = _impls()[2]
    out = impl(jsic_major="D", limit=10)
    assert "error" not in out, f"unexpected error envelope: {out}"
    # Three D rows seeded but excluded=1 row must be filtered out.
    assert out["total"] == 2
    ids = sorted(r["unified_id"] for r in out["results"])
    assert ids == ["UNI-JSIC-D-1", "UNI-JSIC-D-2"]
    # Excluded row never surfaces.
    assert all(r["unified_id"] != "UNI-JSIC-D-X" for r in out["results"])


def test_find_programs_by_jsic_tier_filter(seeded_db: Path) -> None:
    impl = _impls()[2]
    out = impl(jsic_major="D", tier="S", limit=10)
    assert "error" not in out, f"unexpected error envelope: {out}"
    assert out["total"] == 1
    assert out["results"][0]["unified_id"] == "UNI-JSIC-D-1"


def test_find_programs_by_jsic_survives_missing_excluded_column(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy / partial DBs that lack `jpi_programs.excluded` must
    still work — the impl gates the WHERE clause via _column_exists.

    Uses a sub-directory so the conftest-autouse `seeded_db` fixture
    (which always lays down its full schema in `tmp_path/autonomath.db`)
    does not collide with this test's intentionally-minimal schema.
    """
    sub = tmp_path / "legacy_jpi_only"
    sub.mkdir()
    db_path = sub / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # NOTE: NO `excluded` column.
        conn.executescript(
            """
            CREATE TABLE jpi_programs (
                unified_id        TEXT PRIMARY KEY,
                primary_name      TEXT NOT NULL,
                tier              TEXT,
                prefecture        TEXT,
                authority_name    TEXT,
                amount_max_man_yen REAL,
                source_url        TEXT,
                source_fetched_at TEXT,
                jsic_major        TEXT,
                jsic_middle       TEXT,
                jsic_minor        TEXT,
                updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.execute(
            "INSERT INTO jpi_programs (unified_id, primary_name, tier, "
            "jsic_major) VALUES (?, ?, ?, ?)",
            ("UNI-LEGACY-1", "レガシー補助金", "A", "D"),
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))

    from jpintel_mcp.mcp.autonomath_tools.wave24_tools_second_half import (
        _find_programs_by_jsic_impl,
    )

    out = _find_programs_by_jsic_impl(jsic_major="D", limit=10)
    assert "error" not in out, f"unexpected error envelope: {out}"
    assert out["total"] == 1
    assert out["results"][0]["unified_id"] == "UNI-LEGACY-1"
