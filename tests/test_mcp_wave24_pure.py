"""Pure-function coverage tests for ``mcp.autonomath_tools.wave24_tools_*``.

Targets two large modules:
  * ``wave24_tools_first_half.py`` (2,540 stmt)
  * ``wave24_tools_second_half.py`` (2,193 stmt)

The 24 Wave-24 MCP tools share a small pool of pure helpers that need
no DB / LLM:
  * ``_normalize_houjin`` + ``_is_valid_houjin``
  * ``_to_unified``
  * ``_capital_band_for_yen`` (first-half only)
  * ``_safe_json_loads`` (first-half)
  * ``_delta_from_prev`` (first-half)
  * ``_today_jst`` (second-half)
  * ``_empty_envelope`` (first-half)
  * ``make_error`` wrappers (both halves)

NO live DB / LLM. Pure function I/O.

Stream CC tick (coverage 76% → 80% target).
"""

from __future__ import annotations

import datetime

import jpintel_mcp.mcp.autonomath_tools.wave24_tools_first_half as wf
import jpintel_mcp.mcp.autonomath_tools.wave24_tools_second_half as ws

# ---------------------------------------------------------------------------
# _normalize_houjin / _is_valid_houjin (mirrored in both halves)
# ---------------------------------------------------------------------------


def test_first_half_normalize_houjin_strips_t_prefix() -> None:
    assert wf._normalize_houjin(" T8010001213708 ") == "8010001213708"


def test_first_half_normalize_houjin_none_input() -> None:
    assert wf._normalize_houjin(None) == ""


def test_first_half_is_valid_houjin_13_digits() -> None:
    assert wf._is_valid_houjin("8010001213708") is True
    assert wf._is_valid_houjin("12345") is False
    assert wf._is_valid_houjin("ABCDEFGHIJKLM") is False


def test_second_half_normalize_houjin_strips_t_prefix() -> None:
    assert ws._normalize_houjin(" T8010001213708 ") == "8010001213708"


def test_second_half_normalize_houjin_lowercase_t() -> None:
    assert ws._normalize_houjin("t8010001213708") == "8010001213708"


# ---------------------------------------------------------------------------
# _capital_band_for_yen — band mapper (first-half only)
# ---------------------------------------------------------------------------


def test_capital_band_for_yen_negative_unknown() -> None:
    assert wf._capital_band_for_yen(-1) == "unknown"


def test_capital_band_for_yen_zero_under_1m() -> None:
    assert wf._capital_band_for_yen(0) == "under_1m"


def test_capital_band_for_yen_boundary_1m() -> None:
    # 999_999 → under_1m, 1_000_000 → 1m_to_3m
    assert wf._capital_band_for_yen(999_999) == "under_1m"
    assert wf._capital_band_for_yen(1_000_000) == "1m_to_3m"


def test_capital_band_for_yen_mid_bands() -> None:
    assert wf._capital_band_for_yen(2_999_999) == "1m_to_3m"
    assert wf._capital_band_for_yen(3_000_000) == "3m_to_5m"
    assert wf._capital_band_for_yen(5_000_000) == "5m_to_10m"
    assert wf._capital_band_for_yen(10_000_000) == "10m_to_50m"
    assert wf._capital_band_for_yen(50_000_000) == "50m_to_100m"
    assert wf._capital_band_for_yen(100_000_000) == "100m_to_300m"
    assert wf._capital_band_for_yen(300_000_000) == "300m_to_1b"


def test_capital_band_for_yen_1b_plus() -> None:
    assert wf._capital_band_for_yen(1_000_000_000) == "1b_plus"
    assert wf._capital_band_for_yen(10_000_000_000) == "1b_plus"


# ---------------------------------------------------------------------------
# _safe_json_loads
# ---------------------------------------------------------------------------


def test_safe_json_loads_decodes_valid_json() -> None:
    assert wf._safe_json_loads('{"x":1}') == {"x": 1}


def test_safe_json_loads_passes_through_dict() -> None:
    payload = {"a": 1}
    assert wf._safe_json_loads(payload) is payload


def test_safe_json_loads_passes_through_list() -> None:
    payload = [1, 2, 3]
    assert wf._safe_json_loads(payload) is payload


def test_safe_json_loads_none_returns_none() -> None:
    assert wf._safe_json_loads(None) is None


def test_safe_json_loads_empty_string_returns_none() -> None:
    assert wf._safe_json_loads("") is None


def test_safe_json_loads_invalid_returns_original() -> None:
    assert wf._safe_json_loads("not_json{") == "not_json{"


# ---------------------------------------------------------------------------
# _delta_from_prev
# ---------------------------------------------------------------------------


def test_delta_from_prev_first_snapshot_flagged() -> None:
    out = wf._delta_from_prev({"score": 1.0}, None)
    assert out["is_first"] is True
    assert out["changed_keys"] == []


def test_delta_from_prev_changed_value_recorded() -> None:
    curr = {"score": 1.5, "tier": "A"}
    prev = {"score": 1.0, "tier": "A"}
    out = wf._delta_from_prev(curr, prev)
    assert out["is_first"] is False
    changed = {entry["key"]: entry for entry in out["changed_keys"]}
    assert "score" in changed
    assert changed["score"]["prev"] == 1.0
    assert changed["score"]["curr"] == 1.5


def test_delta_from_prev_skips_underscore_and_houjin_keys() -> None:
    curr = {"_meta": "new", "houjin_bangou": "X", "snapshot_month": "2026-04", "score": 1.0}
    prev = {"_meta": "old", "houjin_bangou": "Y", "snapshot_month": "2026-03", "score": 0.5}
    out = wf._delta_from_prev(curr, prev)
    keys = {entry["key"] for entry in out["changed_keys"]}
    assert "_meta" not in keys
    assert "houjin_bangou" not in keys
    assert "snapshot_month" not in keys
    assert "score" in keys


# ---------------------------------------------------------------------------
# _empty_envelope (first-half)
# ---------------------------------------------------------------------------


def test_empty_envelope_default_shape() -> None:
    body = wf._empty_envelope()
    assert body["total"] == 0
    assert body["results"] == []
    assert body["_billing_unit"] == 1
    assert body["_next_calls"] == []
    assert body["limit"] >= 1
    assert body["offset"] == 0


def test_empty_envelope_respects_overrides() -> None:
    body = wf._empty_envelope(
        billing_unit=3,
        limit=50,
        offset=10,
        next_calls=[{"tool": "x", "args": {}}],
        extra={"data_quality": {"caveat": "table_missing"}},
    )
    assert body["_billing_unit"] == 3
    assert body["limit"] == 50
    assert body["offset"] == 10
    assert body["_next_calls"][0]["tool"] == "x"
    assert body["data_quality"]["caveat"] == "table_missing"


def test_empty_envelope_limit_clamped_to_max() -> None:
    body = wf._empty_envelope(limit=10_000)
    assert body["limit"] == 500  # hard cap


def test_empty_envelope_negative_offset_clamped_to_zero() -> None:
    body = wf._empty_envelope(offset=-5)
    assert body["offset"] == 0


# ---------------------------------------------------------------------------
# _today_jst (second-half)
# ---------------------------------------------------------------------------


def test_today_jst_returns_date() -> None:
    out = ws._today_jst()
    assert isinstance(out, datetime.date)


# ---------------------------------------------------------------------------
# make_error wrapper attaches corpus_snapshot fields
# ---------------------------------------------------------------------------


def test_make_error_returns_error_envelope() -> None:
    out = wf.make_error(code="invalid_enum", message="bad", field="x")
    # corpus_snapshot wrapper preserves the error envelope shape.
    assert isinstance(out, dict)
    assert "error" in out
    assert out["error"]["code"] == "invalid_enum"


def test_second_half_make_error_returns_envelope() -> None:
    out = ws.make_error(code="db_unavailable", message="x")
    assert "error" in out
    assert out["error"]["code"] == "db_unavailable"
