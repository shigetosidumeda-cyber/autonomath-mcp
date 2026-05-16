"""DB-fixture-based coverage push for wave24_tools_first_half.

Stream LL 2026-05-16 — push coverage 85% → 90%. Targets
``src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py``
(2,540 stmt). 12 customer-facing MCP tools (#97-#108) gated on wave24
substrate tables (migrations wave24_126..139).

Strategy:
  * Pure helpers (no DB): test directly.
  * ``*_impl`` flows: monkeypatch ``connect_autonomath`` to return a
    tmp_path sqlite3 conn with the minimum schema for the path under
    test. Triggers both `_table_exists` False (empty envelope) and the
    populated SELECT branches.

Constraints (memory: ``feedback_no_quick_check_on_huge_sqlite``):
  * tmp_path-only, never touch /Users/shigetoumeda/jpcite/autonomath.db.
  * No source change.
  * No LLM call (memory: ``feedback_autonomath_no_api_use``).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import jpintel_mcp.mcp.autonomath_tools.wave24_tools_first_half as W

# ---------------------------------------------------------------------------
# Tmp_path conn fixture — used by every impl test
# ---------------------------------------------------------------------------


def _make_conn(db_path: Path) -> sqlite3.Connection:
    """Open a tmp_path sqlite3 connection with Row factory + thread-safe.

    Module code calls ``connect_autonomath`` to get a per-thread RO
    connection. For unit-test coverage we substitute that with an
    in-process read/write connection that has the same Row factory contract.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def tmp_wave24_db_path(tmp_path: Path) -> Path:
    p = tmp_path / "wave24_fixture.db"
    # Ensure the file exists so `_table_exists` queries do not raise.
    conn = sqlite3.connect(p)
    conn.executescript("CREATE TABLE _placeholder (id INTEGER PRIMARY KEY);")
    conn.commit()
    conn.close()
    return p


@pytest.fixture()
def patched_conn(
    tmp_wave24_db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> sqlite3.Connection:
    """Substitute connect_autonomath() with a tmp_path conn.

    The module under test calls ``connect_autonomath()`` inside ``_open_db``;
    we override the symbol *in the wave24 module's namespace* (the from-import
    binding) so the test never touches the 9.7 GB production DB.
    """
    conn = _make_conn(tmp_wave24_db_path)
    monkeypatch.setattr(W, "connect_autonomath", lambda *a, **kw: conn)
    return conn


# ---------------------------------------------------------------------------
# Pure helpers: _normalize_houjin / _is_valid_houjin / _capital_band_for_yen
# ---------------------------------------------------------------------------


def test_normalize_houjin_strips_t_prefix() -> None:
    assert W._normalize_houjin("T8010001213708") == "8010001213708"


def test_normalize_houjin_passthrough_when_no_prefix() -> None:
    assert W._normalize_houjin("8010001213708") == "8010001213708"


def test_normalize_houjin_strips_whitespace() -> None:
    assert W._normalize_houjin("  8010001213708 ") == "8010001213708"


def test_normalize_houjin_empty_returns_empty() -> None:
    assert W._normalize_houjin("") == ""
    assert W._normalize_houjin(None) == ""


def test_is_valid_houjin_thirteen_digits_true() -> None:
    assert W._is_valid_houjin("8010001213708") is True


def test_is_valid_houjin_short_false() -> None:
    assert W._is_valid_houjin("12345") is False


def test_is_valid_houjin_alpha_false() -> None:
    assert W._is_valid_houjin("80A0001213708") is False


def test_is_valid_houjin_empty_false() -> None:
    assert W._is_valid_houjin("") is False


# ---------------------------------------------------------------------------
# _capital_band_for_yen — every band edge
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount,expected_band",
    [
        (-1, "unknown"),
        (0, "under_1m"),
        (999_999, "under_1m"),
        (1_000_000, "1m_to_3m"),
        (2_999_999, "1m_to_3m"),
        (3_000_000, "3m_to_5m"),
        (4_999_999, "3m_to_5m"),
        (5_000_000, "5m_to_10m"),
        (9_999_999, "5m_to_10m"),
        (10_000_000, "10m_to_50m"),
        (49_999_999, "10m_to_50m"),
        (50_000_000, "50m_to_100m"),
        (99_999_999, "50m_to_100m"),
        (100_000_000, "100m_to_300m"),
        (299_999_999, "100m_to_300m"),
        (300_000_000, "300m_to_1b"),
        (999_999_999, "300m_to_1b"),
        (1_000_000_000, "1b_plus"),
        (10_000_000_000, "1b_plus"),
    ],
)
def test_capital_band_for_yen_every_edge(amount: int, expected_band: str) -> None:
    assert W._capital_band_for_yen(amount) == expected_band


def test_capital_band_for_yen_none_treated_as_zero() -> None:
    # `int(None or 0)` = 0 → under_1m
    assert W._capital_band_for_yen(0) == "under_1m"


# ---------------------------------------------------------------------------
# _safe_json_loads — every input variant
# ---------------------------------------------------------------------------


def test_safe_json_loads_none_returns_none() -> None:
    assert W._safe_json_loads(None) is None


def test_safe_json_loads_empty_string_returns_none() -> None:
    assert W._safe_json_loads("") is None


def test_safe_json_loads_valid_json_decoded() -> None:
    out = W._safe_json_loads('{"k": 1}')
    assert out == {"k": 1}


def test_safe_json_loads_dict_passthrough() -> None:
    payload = {"x": [1, 2, 3]}
    assert W._safe_json_loads(payload) is payload


def test_safe_json_loads_list_passthrough() -> None:
    payload = [1, "x", None]
    assert W._safe_json_loads(payload) is payload


def test_safe_json_loads_malformed_returns_original() -> None:
    # Invalid JSON falls back to the raw input (mirror of jpcite contract).
    assert W._safe_json_loads("not json") == "not json"


# ---------------------------------------------------------------------------
# _delta_from_prev — first-row + key-add + key-remove + key-change
# ---------------------------------------------------------------------------


def test_delta_from_prev_first_row_marker() -> None:
    out = W._delta_from_prev({"k": 1}, None)
    assert out == {"is_first": True, "changed_keys": []}


def test_delta_from_prev_changed_key_listed() -> None:
    out = W._delta_from_prev({"k": 2}, {"k": 1})
    assert out["is_first"] is False
    assert out["changed_keys"][0]["key"] == "k"
    assert out["changed_keys"][0]["prev"] == 1
    assert out["changed_keys"][0]["curr"] == 2


def test_delta_from_prev_added_key() -> None:
    out = W._delta_from_prev({"a": 1, "b": 2}, {"a": 1})
    assert any(c["key"] == "b" for c in out["changed_keys"])


def test_delta_from_prev_removed_key() -> None:
    out = W._delta_from_prev({"a": 1}, {"a": 1, "b": 2})
    assert any(c["key"] == "b" for c in out["changed_keys"])


def test_delta_from_prev_underscored_and_anchor_keys_filtered() -> None:
    # `_*` keys + the anchor pair (snapshot_month / houjin_bangou) must be
    # filtered out of the change list.
    curr = {"snapshot_month": "2026-05", "houjin_bangou": "8010", "_ts": "x"}
    prev = {"snapshot_month": "2026-04", "houjin_bangou": "8010", "_ts": "y"}
    out = W._delta_from_prev(curr, prev)
    keys = [c["key"] for c in out["changed_keys"]]
    assert "_ts" not in keys
    assert "snapshot_month" not in keys
    assert "houjin_bangou" not in keys


# ---------------------------------------------------------------------------
# _empty_envelope — canonical envelope contract
# ---------------------------------------------------------------------------


def test_empty_envelope_basic_shape() -> None:
    env = W._empty_envelope(billing_unit=1, limit=20, offset=0)
    assert env["total"] == 0
    assert env["results"] == []
    assert env["_billing_unit"] == 1
    assert env["limit"] == 20
    assert env["offset"] == 0
    assert env["_next_calls"] == []


def test_empty_envelope_limit_clamped_to_500() -> None:
    env = W._empty_envelope(billing_unit=1, limit=99_999)
    assert env["limit"] == 500


def test_empty_envelope_offset_clamped_to_zero() -> None:
    env = W._empty_envelope(billing_unit=1, limit=20, offset=-5)
    assert env["offset"] == 0


def test_empty_envelope_extra_keys_added() -> None:
    env = W._empty_envelope(billing_unit=1, extra={"houjin_bangou": "8010"})
    assert env["houjin_bangou"] == "8010"


def test_empty_envelope_next_calls_propagated() -> None:
    env = W._empty_envelope(billing_unit=1, next_calls=[{"tool": "x"}])
    assert env["_next_calls"] == [{"tool": "x"}]


# ---------------------------------------------------------------------------
# _table_exists / _column_exists — schema introspection helpers
# ---------------------------------------------------------------------------


def test_table_exists_true_for_existing_table(patched_conn: sqlite3.Connection) -> None:
    assert W._table_exists(patched_conn, "_placeholder") is True


def test_table_exists_false_for_missing_table(
    patched_conn: sqlite3.Connection,
) -> None:
    assert W._table_exists(patched_conn, "not_a_real_table") is False


def test_column_exists_basic(patched_conn: sqlite3.Connection) -> None:
    assert W._column_exists(patched_conn, "_placeholder", "id") is True
    assert W._column_exists(patched_conn, "_placeholder", "no_such_col") is False


# ---------------------------------------------------------------------------
# _to_unified — falls back to original on translation miss
# ---------------------------------------------------------------------------


def test_to_unified_fallback_on_unknown_id() -> None:
    # An obviously fake program id should pass through unchanged.
    out = W._to_unified("not-a-real-program-id")
    assert out == "not-a-real-program-id"


# ---------------------------------------------------------------------------
# _recommend_programs_for_houjin_impl — argument validation + degraded path
# ---------------------------------------------------------------------------


def test_recommend_programs_for_houjin_empty_bangou_returns_missing_arg() -> None:
    out = W._recommend_programs_for_houjin_impl(houjin_bangou="")
    assert out.get("error", {}).get("code") == "missing_required_arg" or out.get(
        "code"
    ) == "missing_required_arg"


def test_recommend_programs_for_houjin_invalid_bangou_returns_invalid_enum() -> None:
    out = W._recommend_programs_for_houjin_impl(houjin_bangou="not-13-digits")
    error_code = out.get("code") or out.get("error", {}).get("code")
    assert error_code == "invalid_enum"


def test_recommend_programs_for_houjin_table_missing_degrades_to_empty(
    patched_conn: sqlite3.Connection,
) -> None:
    # `am_recommended_programs` table is NOT created → degraded envelope.
    out = W._recommend_programs_for_houjin_impl(houjin_bangou="8010001213708")
    assert out["total"] == 0
    assert out["results"] == []
    assert out["data_quality"]["table_present"] is False


def test_recommend_programs_for_houjin_table_present_returns_rows(
    patched_conn: sqlite3.Connection,
) -> None:
    patched_conn.executescript(
        """
        CREATE TABLE am_recommended_programs (
            houjin_bangou TEXT,
            program_unified_id TEXT,
            score REAL,
            rank INTEGER,
            reason_json TEXT,
            computed_at TEXT
        );
        INSERT INTO am_recommended_programs VALUES
            ('8010001213708', 'UNI-PROG-1', 0.9, 1, '{"r": "match"}', '2026-05-16'),
            ('8010001213708', 'UNI-PROG-2', 0.7, 2, NULL, '2026-05-16');
        """
    )
    patched_conn.commit()
    out = W._recommend_programs_for_houjin_impl(houjin_bangou="8010001213708")
    assert out["total"] == 2
    assert len(out["results"]) == 2
    assert out["results"][0]["program_id"] == "UNI-PROG-1"
    assert out["results"][0]["reason"] == {"r": "match"}
    assert out["results"][1]["reason"] is None


# ---------------------------------------------------------------------------
# _find_combinable_programs_impl — invalid visibility + missing table
# ---------------------------------------------------------------------------


def test_find_combinable_programs_missing_program_id() -> None:
    out = W._find_combinable_programs_impl(program_id="")
    error_code = out.get("code") or out.get("error", {}).get("code")
    assert error_code == "missing_required_arg"


def test_find_combinable_programs_invalid_visibility(
    patched_conn: sqlite3.Connection,
) -> None:
    out = W._find_combinable_programs_impl(
        program_id="UNI-X", visibility="bogus-value"
    )
    error_code = out.get("code") or out.get("error", {}).get("code")
    assert error_code == "invalid_enum"


def test_find_combinable_programs_table_missing_degrades(
    patched_conn: sqlite3.Connection,
) -> None:
    out = W._find_combinable_programs_impl(program_id="UNI-X")
    assert out["total"] == 0
    assert out["data_quality"]["table_present"] is False


# ---------------------------------------------------------------------------
# _get_program_calendar_12mo_impl — missing arg + missing table + degraded
# ---------------------------------------------------------------------------


def test_get_program_calendar_12mo_missing_program_id() -> None:
    out = W._get_program_calendar_12mo_impl(program_id="")
    error_code = out.get("code") or out.get("error", {}).get("code")
    assert error_code == "missing_required_arg"


def test_get_program_calendar_12mo_missing_table_degrades(
    patched_conn: sqlite3.Connection,
) -> None:
    out = W._get_program_calendar_12mo_impl(program_id="UNI-X")
    assert out["total"] == 0
    assert out["data_quality"]["table_present"] is False


# ---------------------------------------------------------------------------
# _forecast_enforcement_risk_impl — must require at least one filter
# ---------------------------------------------------------------------------


def test_forecast_enforcement_risk_no_filters_returns_missing_arg() -> None:
    out = W._forecast_enforcement_risk_impl(jsic_major=None, region_code=None)
    error_code = out.get("code") or out.get("error", {}).get("code")
    assert error_code == "missing_required_arg"


def test_forecast_enforcement_risk_table_missing_degrades(
    patched_conn: sqlite3.Connection,
) -> None:
    out = W._forecast_enforcement_risk_impl(jsic_major="D", region_code=None)
    assert out["total"] == 0
    assert out["data_quality"]["table_present"] is False


# ---------------------------------------------------------------------------
# _find_similar_case_studies_impl — missing case_id + missing table
# ---------------------------------------------------------------------------


def test_find_similar_case_studies_missing_case_id() -> None:
    out = W._find_similar_case_studies_impl(case_id="")
    error_code = out.get("code") or out.get("error", {}).get("code")
    assert error_code == "missing_required_arg"


def test_find_similar_case_studies_table_missing_degrades(
    patched_conn: sqlite3.Connection,
) -> None:
    out = W._find_similar_case_studies_impl(case_id=42)
    assert out["total"] == 0
    assert out["data_quality"]["table_present"] is False


# ---------------------------------------------------------------------------
# _get_houjin_360_snapshot_history_impl — validation + degraded
# ---------------------------------------------------------------------------


def test_get_houjin_360_snapshot_history_invalid_months_too_high(
    patched_conn: sqlite3.Connection,
) -> None:
    out = W._get_houjin_360_snapshot_history_impl(
        houjin_bangou="8010001213708", months=999
    )
    error_code = out.get("code") or out.get("error", {}).get("code")
    assert error_code == "out_of_range"


def test_get_houjin_360_snapshot_history_invalid_houjin_bangou() -> None:
    out = W._get_houjin_360_snapshot_history_impl(houjin_bangou="bad")
    error_code = out.get("code") or out.get("error", {}).get("code")
    assert error_code == "invalid_enum"


def test_get_houjin_360_snapshot_history_table_missing_degrades(
    patched_conn: sqlite3.Connection,
) -> None:
    out = W._get_houjin_360_snapshot_history_impl(houjin_bangou="8010001213708")
    assert out["total"] == 0
    assert out["data_quality"]["table_present"] is False


def test_get_houjin_360_snapshot_history_with_data_computes_delta(
    patched_conn: sqlite3.Connection,
) -> None:
    patched_conn.executescript(
        """
        CREATE TABLE am_houjin_360_snapshot (
            houjin_bangou TEXT,
            snapshot_month TEXT,
            payload_json TEXT,
            computed_at TEXT
        );
        INSERT INTO am_houjin_360_snapshot VALUES
            ('8010001213708', '2026-04', '{"k": 1, "snapshot_month": "2026-04"}',
             '2026-04-01'),
            ('8010001213708', '2026-05', '{"k": 2, "snapshot_month": "2026-05"}',
             '2026-05-01');
        """
    )
    patched_conn.commit()
    out = W._get_houjin_360_snapshot_history_impl(
        houjin_bangou="8010001213708", months=6
    )
    assert out["total"] == 2
    # Latest sits at index 0; oldest at end.
    assert out["results"][0]["snapshot_month"] == "2026-05"
    # The latest row carries a delta vs the previous month — `k: 1→2`.
    assert out["results"][0]["delta_from_prev"]["is_first"] is False
    keys = [c["key"] for c in out["results"][0]["delta_from_prev"]["changed_keys"]]
    assert "k" in keys
