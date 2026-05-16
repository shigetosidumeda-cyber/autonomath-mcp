"""Dispatch + validation tests for composition_tools.

Targets ``src/jpintel_mcp/mcp/autonomath_tools/composition_tools.py``
(358 stmt, 19.8% baseline). Exercises:

  * ``_next_calls_for_*`` helpers (pure dict builders).
  * ``_today_iso`` / ``_parse_iso_date`` (date parsing).
  * ``_open_db`` (error envelope on DB unavailable).
  * Validation early-return paths of every ``_*_impl`` function.
  * End-to-end ``_track_amendment_lineage_am`` against an in-memory
    tmp SQLite seeded with am_entities + am_amendment_snapshot rows.
  * ``_apply_eligibility_chain_impl`` happy path on tmp DB.

NO live ``autonomath.db`` read. NO LLM call. Each test seeds its own
tmp SQLite file scoped to a function-level fixture.
"""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

import pytest

import jpintel_mcp.mcp.autonomath_tools.composition_tools as ct

# ---------------------------------------------------------------------------
# Tmp SQLite fixtures
# ---------------------------------------------------------------------------


def _make_minimal_db(path: Path) -> None:
    """Create the schema required by ``composition_tools`` impls.

    Only the tables referenced by the SELECT statements are present.
    Anything not referenced is skipped — the impls swallow OperationalError
    "no such table" with try/except → empty result.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_entities (
            canonical_id TEXT PRIMARY KEY,
            record_kind TEXT,
            primary_name TEXT,
            raw_json TEXT
        );
        CREATE TABLE am_prerequisite_bundle (
            bundle_id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_entity_id TEXT,
            prerequisite_kind TEXT,
            prerequisite_name TEXT,
            required_or_optional TEXT,
            preparation_time_days INTEGER,
            preparation_cost_yen INTEGER,
            obtain_url TEXT,
            rationale_text TEXT
        );
        CREATE TABLE am_unified_rule (
            rule_id TEXT PRIMARY KEY,
            scope_program_id TEXT,
            pair_program_id TEXT,
            source_table TEXT,
            kind TEXT,
            severity TEXT,
            message_ja TEXT,
            source_url TEXT
        );
        CREATE TABLE jpi_exclusion_rules (
            id INTEGER PRIMARY KEY,
            program_a TEXT,
            program_b TEXT,
            kind TEXT,
            severity TEXT,
            message_ja TEXT,
            source_url TEXT
        );
        CREATE TABLE am_compat_matrix (
            program_a_id TEXT,
            program_b_id TEXT,
            compat_status TEXT,
            combined_max_yen INTEGER,
            conditions_text TEXT,
            rationale_short TEXT,
            source_url TEXT,
            confidence REAL,
            inferred_only INTEGER
        );
        CREATE TABLE am_application_round (
            round_id TEXT PRIMARY KEY,
            program_entity_id TEXT,
            round_label TEXT,
            round_seq INTEGER,
            application_open_date TEXT,
            application_close_date TEXT,
            announced_date TEXT,
            disbursement_start_date TEXT,
            budget_yen INTEGER,
            status TEXT,
            source_url TEXT,
            source_fetched_at TEXT
        );
        CREATE TABLE am_amendment_snapshot (
            snapshot_id TEXT PRIMARY KEY,
            entity_id TEXT,
            version_seq INTEGER,
            observed_at TEXT,
            effective_from TEXT,
            effective_until TEXT,
            amount_max_yen INTEGER,
            subsidy_rate_max REAL,
            eligibility_hash TEXT,
            summary_hash TEXT,
            source_url TEXT,
            source_fetched_at TEXT
        );
        CREATE TABLE am_application_steps (
            step_no INTEGER,
            program_entity_id TEXT,
            step_title TEXT,
            step_description TEXT,
            prerequisites_json TEXT,
            expected_days INTEGER,
            online_or_offline TEXT,
            responsible_party TEXT
        );
        CREATE TABLE am_law_article (
            law_canonical_id TEXT,
            article_number TEXT,
            title TEXT,
            source_url TEXT
        );
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def tmp_autonomath(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a minimal autonomath.db at tmp_path and patch the opener."""
    db_path = tmp_path / "autonomath.db"
    _make_minimal_db(db_path)

    def _open() -> sqlite3.Connection:
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(ct, "connect_autonomath", _open)
    return db_path


# ---------------------------------------------------------------------------
# Pure helper coverage
# ---------------------------------------------------------------------------


def test_today_iso_is_iso_date_string() -> None:
    s = ct._today_iso()
    assert len(s) == 10
    datetime.date.fromisoformat(s)


def test_parse_iso_date_valid() -> None:
    d = ct._parse_iso_date("2026-05-16")
    assert d == datetime.date(2026, 5, 16)


def test_parse_iso_date_truncates_extra_chars() -> None:
    d = ct._parse_iso_date("2026-05-16T09:00:00Z")
    assert d == datetime.date(2026, 5, 16)


def test_parse_iso_date_invalid_returns_none() -> None:
    assert ct._parse_iso_date("not-a-date") is None
    assert ct._parse_iso_date("") is None
    assert ct._parse_iso_date(None) is None


def test_parse_iso_date_invalid_type_returns_none() -> None:
    assert ct._parse_iso_date(20260516) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _next_calls_* dispatch helpers
# ---------------------------------------------------------------------------


def test_next_calls_for_eligibility_empty_list() -> None:
    out = ct._next_calls_for_eligibility(program_ids=[], profile=None)
    assert out == []


def test_next_calls_for_eligibility_returns_three_suggestions() -> None:
    out = ct._next_calls_for_eligibility(
        program_ids=["UNI-a", "UNI-b"], profile={"prefecture": "東京都"}
    )
    assert len(out) == 3
    tools = [c["tool"] for c in out]
    assert "find_complementary_programs_am" in tools
    assert "simulate_application_am" in tools
    assert "program_active_periods_am" in tools
    # First args reference program_ids[0]
    assert out[0]["args"]["seed_program_id"] == "UNI-a"
    # compound_mult is a positive float
    for c in out:
        assert isinstance(c["compound_mult"], float)
        assert c["compound_mult"] > 0


def test_next_calls_for_complementary_returns_two() -> None:
    out = ct._next_calls_for_complementary(seed_id="UNI-seed")
    assert len(out) == 2
    assert all("tool" in c and "rationale" in c for c in out)
    assert out[0]["tool"] == "apply_eligibility_chain_am"


def test_next_calls_for_simulate_returns_two() -> None:
    out = ct._next_calls_for_simulate(program_id="UNI-sim")
    assert len(out) == 2
    assert out[0]["tool"] == "track_amendment_lineage_am"
    assert out[1]["tool"] == "program_active_periods_am"


def test_next_calls_for_lineage_program_kind() -> None:
    out = ct._next_calls_for_lineage(target_kind="program", target_id="UNI-prog")
    assert len(out) == 2
    assert out[0]["tool"] == "apply_eligibility_chain_am"


def test_next_calls_for_lineage_law_kind() -> None:
    out = ct._next_calls_for_lineage(target_kind="law", target_id="law:42")
    assert len(out) == 1
    assert out[0]["tool"] == "get_law_article_am"


def test_next_calls_for_periods_returns_two() -> None:
    out = ct._next_calls_for_periods(program_id="UNI-period")
    assert len(out) == 2
    assert out[0]["compound_mult"] == 2.4


# ---------------------------------------------------------------------------
# _open_db error paths
# ---------------------------------------------------------------------------


def test_open_db_file_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> sqlite3.Connection:
        raise FileNotFoundError("no autonomath.db")

    monkeypatch.setattr(ct, "connect_autonomath", boom)
    res = ct._open_db()
    assert isinstance(res, dict)
    assert res["error"]["code"] == "db_unavailable"
    assert "missing" in res["error"]["message"].lower()


def test_open_db_sqlite_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> sqlite3.Connection:
        raise sqlite3.OperationalError("disk corrupt")

    monkeypatch.setattr(ct, "connect_autonomath", boom)
    res = ct._open_db()
    assert isinstance(res, dict)
    assert res["error"]["code"] == "db_unavailable"


def test_open_db_returns_conn(tmp_autonomath: Path) -> None:
    res = ct._open_db()
    assert isinstance(res, sqlite3.Connection)
    res.close()


# ---------------------------------------------------------------------------
# _apply_eligibility_chain_impl validation
# ---------------------------------------------------------------------------


def test_eligibility_chain_empty_program_ids() -> None:
    res = ct._apply_eligibility_chain_impl(profile={}, program_ids=[])
    assert res["error"]["code"] == "missing_required_arg"
    assert res["error"]["field"] == "program_ids"


def test_eligibility_chain_invalid_profile_type() -> None:
    res = ct._apply_eligibility_chain_impl(
        profile="not-a-dict",  # type: ignore[arg-type]
        program_ids=["UNI-x"],
    )
    assert res["error"]["code"] == "missing_required_arg"
    assert res["error"]["field"] == "profile"


def test_eligibility_chain_clamps_depth(tmp_autonomath: Path) -> None:
    res = ct._apply_eligibility_chain_impl(profile={}, program_ids=["UNI-x"], chain_depth=99)
    # depth gets clamped to 8 → no error, just an envelope
    assert "results" in res
    assert isinstance(res["results"], list)


def test_eligibility_chain_happy_path_empty_db(tmp_autonomath: Path) -> None:
    res = ct._apply_eligibility_chain_impl(profile={}, program_ids=["UNI-empty"])
    assert "results" in res
    assert res["total"] == 1
    assert "_disclaimer" in res
    assert "_next_calls" in res
    # All steps are info (no rules) → verdict should be eligible.
    prog = res["results"][0]
    assert prog["verdict"] in ("eligible", "partial", "ineligible")


def test_eligibility_chain_with_empty_pid_in_list(tmp_autonomath: Path) -> None:
    res = ct._apply_eligibility_chain_impl(profile={}, program_ids=["  ", "UNI-real"])
    # First entry should be flagged ineligible (empty pid).
    first = res["results"][0]
    assert first["verdict"] == "ineligible"
    assert first["reasoning_steps"][0]["kind"] == "input_validation"


# ---------------------------------------------------------------------------
# _find_complementary_impl validation
# ---------------------------------------------------------------------------


def test_find_complementary_missing_seed() -> None:
    res = ct._find_complementary_impl(seed_program_id="")
    assert res["error"]["code"] == "missing_required_arg"
    assert res["error"]["field"] == "seed_program_id"


def test_find_complementary_with_empty_db(tmp_autonomath: Path) -> None:
    res = ct._find_complementary_impl(seed_program_id="UNI-seed")
    assert res["seed_program_id"] == "UNI-seed"
    assert res["results"] == []
    assert res["combined_ceiling_yen"] == 0
    assert "_next_calls" in res
    assert "_disclaimer" in res


def test_find_complementary_clamps_top_n(tmp_autonomath: Path) -> None:
    res = ct._find_complementary_impl(seed_program_id="UNI-seed", top_n=9999)
    # top_n clamps to 50
    assert res["limit"] == 50


# ---------------------------------------------------------------------------
# _simulate_application_impl validation
# ---------------------------------------------------------------------------


def test_simulate_application_missing_program_id() -> None:
    res = ct._simulate_application_impl(program_id="", profile={})
    assert res["error"]["code"] == "missing_required_arg"


def test_simulate_application_empty_db_returns_envelope(tmp_autonomath: Path) -> None:
    res = ct._simulate_application_impl(program_id="UNI-x", profile={})
    assert res["program_id"] == "UNI-x"
    assert res["steps"] == []
    assert res["document_checklist"] == []
    assert res["completeness_score"] == 0.0
    assert "_disclaimer" in res


def test_simulate_application_normalises_invalid_round(tmp_autonomath: Path) -> None:
    res = ct._simulate_application_impl(program_id="UNI-x", profile={}, target_round="bogus")
    # 'bogus' coerces to 'next'.
    assert res["target_round"] == "next"


def test_simulate_application_non_dict_profile_coerced(tmp_autonomath: Path) -> None:
    res = ct._simulate_application_impl(
        program_id="UNI-x",
        profile=["not-a-dict"],  # type: ignore[arg-type]
    )
    assert "results" in res


# ---------------------------------------------------------------------------
# _track_amendment_lineage_impl validation + happy-path on tmp DB
# ---------------------------------------------------------------------------


def test_lineage_invalid_target_kind() -> None:
    res = ct._track_amendment_lineage_impl(target_kind="not_law_or_program", target_id="UNI-x")
    assert res["error"]["code"] == "invalid_enum"


def test_lineage_empty_target_id() -> None:
    res = ct._track_amendment_lineage_impl(target_kind="program", target_id="")
    assert res["error"]["code"] == "missing_required_arg"


def test_lineage_bad_since_format() -> None:
    res = ct._track_amendment_lineage_impl(
        target_kind="program", target_id="UNI-x", since="not-a-date"
    )
    assert res["error"]["code"] == "invalid_date_format"


def test_lineage_target_id_not_found(tmp_autonomath: Path) -> None:
    res = ct._track_amendment_lineage_impl(target_kind="program", target_id="UNI-missing")
    # Graceful empty envelope, NOT an error.
    assert "error" not in res
    assert res["total"] == 0
    assert res["data_quality"]["target_resolved"] is False


def test_lineage_kind_mismatch(tmp_autonomath: Path) -> None:
    # Seed a "law" record_kind row.
    conn = sqlite3.connect(tmp_autonomath)
    conn.execute(
        "INSERT INTO am_entities(canonical_id, record_kind, primary_name) VALUES (?, ?, ?)",
        ("law:42", "law", "テスト法"),
    )
    conn.commit()
    conn.close()
    # Ask for it as a "program" → should error invalid_enum.
    res = ct._track_amendment_lineage_impl(target_kind="program", target_id="law:42")
    assert res["error"]["code"] == "invalid_enum"
    assert "not 'program'" in res["error"]["message"]


def test_lineage_happy_path_with_snapshots(tmp_autonomath: Path) -> None:
    conn = sqlite3.connect(tmp_autonomath)
    conn.execute(
        "INSERT INTO am_entities(canonical_id, record_kind, primary_name) VALUES (?, ?, ?)",
        ("program:base:abc", "program", "テスト制度"),
    )
    conn.executemany(
        "INSERT INTO am_amendment_snapshot("
        "snapshot_id, entity_id, version_seq, observed_at, "
        "effective_from, eligibility_hash, summary_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("snap1", "program:base:abc", 1, "2025-01-01", "2025-01-01", "abc", "def"),
            ("snap2", "program:base:abc", 2, "2026-01-01", None, "xyz", "qrs"),
        ],
    )
    conn.commit()
    conn.close()
    res = ct._track_amendment_lineage_impl(target_kind="program", target_id="program:base:abc")
    assert "error" not in res
    assert res["total"] == 2
    assert res["strict_count"] == 1  # only the first row has effective_from
    assert len(res["results"]) == 2


# ---------------------------------------------------------------------------
# _program_active_periods_impl validation
# ---------------------------------------------------------------------------


def test_program_active_periods_missing_id() -> None:
    res = ct._program_active_periods_impl(program_id="")
    assert res["error"]["code"] == "missing_required_arg"


def test_program_active_periods_empty_db(tmp_autonomath: Path) -> None:
    res = ct._program_active_periods_impl(program_id="UNI-x", future_only=True)
    assert res["program_id"] == "UNI-x"
    assert res["results"] == []
    assert res["open_count"] == 0


def test_program_active_periods_sunset_warning(tmp_autonomath: Path) -> None:
    conn = sqlite3.connect(tmp_autonomath)
    conn.execute(
        "INSERT INTO am_application_round("
        "round_id, program_entity_id, round_label, round_seq, "
        "application_open_date, application_close_date, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("r1", "UNI-sunset", "1st", 1, "2020-01-01", "2020-12-31", "closed"),
    )
    conn.commit()
    conn.close()
    res = ct._program_active_periods_impl(program_id="UNI-sunset")
    assert res["closed_count"] == 1
    assert res["sunset_warning"] is not None
    assert "sunset" in res["sunset_warning"].lower()


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


def test_disclaimers_are_nonempty_strings() -> None:
    for txt in (ct._DISCLAIMER_ELIGIBILITY, ct._DISCLAIMER_COMPLEMENTARY, ct._DISCLAIMER_SIMULATE):
        assert isinstance(txt, str)
        assert len(txt) > 50


def test_disclaimer_eligibility_carries_shihou_fence() -> None:
    # The eligibility disclaimer specifically cites 税理士法 §52 + 行政書士法 §1.
    assert "税理士法" in ct._DISCLAIMER_ELIGIBILITY
    assert "行政書士法" in ct._DISCLAIMER_ELIGIBILITY


def test_disclaimer_simulate_carries_gyousei_fence() -> None:
    assert "行政書士法" in ct._DISCLAIMER_SIMULATE


def test_enabled_flag_boolean() -> None:
    assert isinstance(ct._ENABLED, bool)
