"""W9-3 UC5 follow-up — verify `_safe_envelope` decorator emits the full
MASTER_PLAN §I envelope contract on BOTH error paths and the success path.

The decorator (autonomath_wrappers.py:_safe_envelope) wraps 5 MCP tools:

  - search_gx_programs_am
  - search_loans_am
  - check_enforcement_am
  - search_mutual_plans_am
  - get_law_article_am

Per §I every response must carry:

  total : int
  results : list
  _billing_unit : int (0 on error, ≥1 on success)
  _next_calls : list[dict]

Plus on error path: ``error`` (dict with code + message + hint + retry_with).

These tests exercise the decorator surface directly via a synthetic wrapped
function — they DO NOT need autonomath.db, so they run on every CI shard.
A second class smoke-tests the live wrappers against autonomath.db when the
snapshot is present (skipped otherwise so CI without fixture stays green).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

# Server import first to break the autonomath_tools <-> server circular
# import (server.py registers the @mcp.tool decorators).
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.autonomath_wrappers import (  # noqa: E402
    _safe_envelope,
)

# ---------------------------------------------------------------------------
# Decorator-level tests (no DB required)
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {"total", "results", "_billing_unit", "_next_calls"}


def _assert_envelope_keys(payload, *, error_path: bool):
    assert isinstance(payload, dict), f"envelope must be dict, got {type(payload)}"
    missing = REQUIRED_KEYS - set(payload.keys())
    assert not missing, f"envelope missing required keys: {missing}"
    # Type contracts.
    assert isinstance(payload["total"], int)
    assert isinstance(payload["results"], list)
    assert isinstance(payload["_billing_unit"], int)
    assert isinstance(payload["_next_calls"], list)
    if error_path:
        assert "error" in payload
        assert isinstance(payload["error"], dict)
        assert {"code", "message", "hint", "retry_with"} <= set(payload["error"].keys())
        # Error never bills; never has compound follow-ups by default.
        assert payload["_billing_unit"] == 0
        assert payload["_next_calls"] == []


def test_safe_envelope_db_unavailable_path_has_required_fields():
    """sqlite3.OperationalError → db_unavailable envelope with §I fields."""

    @_safe_envelope(retry_with=["fallback_a"])
    def _broken():
        raise sqlite3.OperationalError("no such table: am_xyz")

    payload = _broken()
    _assert_envelope_keys(payload, error_path=True)
    assert payload["error"]["code"] == "db_unavailable"
    assert payload["error"]["retry_with"] == ["fallback_a"]


def test_safe_envelope_invalid_enum_path_has_required_fields():
    """ValueError → invalid_enum envelope with §I fields."""

    @_safe_envelope(retry_with=["fallback_b"])
    def _bad_enum():
        raise ValueError("unknown loan_kind: foo")

    payload = _bad_enum()
    _assert_envelope_keys(payload, error_path=True)
    assert payload["error"]["code"] == "invalid_enum"
    assert "ValueError" in payload["error"]["message"]
    assert payload["error"]["retry_with"] == ["fallback_b"]


def test_safe_envelope_keyerror_path_has_required_fields():
    """KeyError → invalid_enum envelope (same handler) with §I fields."""

    @_safe_envelope(retry_with=["fallback_c"])
    def _missing_key():
        raise KeyError("missing arg: theme")

    payload = _missing_key()
    _assert_envelope_keys(payload, error_path=True)
    assert payload["error"]["code"] == "invalid_enum"
    assert "KeyError" in payload["error"]["message"]


def test_safe_envelope_long_error_message_is_trimmed():
    """Long ValueError messages are trimmed to 120 chars to avoid leaking
    accidental internal context from validators that f-string into the
    error message."""

    @_safe_envelope(retry_with=["fallback_d"])
    def _long():
        raise ValueError("x" * 500)

    payload = _long()
    _assert_envelope_keys(payload, error_path=True)
    # Decorator format: "ValueError: <raw[:117]>..." → message length ≤
    # len("ValueError: ") + 120 ish; assert no untrimmed leak.
    assert payload["error"]["message"].endswith("...")
    assert len(payload["error"]["message"]) < 200


def test_safe_envelope_success_default_billing_unit_and_next_calls():
    """Legacy success returns get _billing_unit=1, _next_calls=[] defaults."""

    @_safe_envelope(retry_with=["fallback_e"])
    def _ok():
        return {"total": 3, "results": [{"a": 1}, {"a": 2}, {"a": 3}]}

    payload = _ok()
    _assert_envelope_keys(payload, error_path=False)
    assert payload["_billing_unit"] == 1
    assert payload["_next_calls"] == []
    assert payload["total"] == 3


def test_safe_envelope_success_passthrough_when_already_present():
    """When the underlying tool function already injected
    _billing_unit / _next_calls, the decorator must pass them through
    unchanged (setdefault, not overwrite)."""

    @_safe_envelope(retry_with=["fallback_f"])
    def _ok_with_billing():
        return {
            "total": 1,
            "results": [{"a": 1}],
            "_billing_unit": 5,
            "_next_calls": [{"tool": "next_tool", "args": {}}],
        }

    payload = _ok_with_billing()
    _assert_envelope_keys(payload, error_path=False)
    assert payload["_billing_unit"] == 5
    assert payload["_next_calls"] == [{"tool": "next_tool", "args": {}}]


def test_safe_envelope_success_non_dict_returns_passthrough():
    """If the wrapped fn returns a non-dict (defensive — should not happen
    in practice for the 5 wrapped tools), the decorator does not crash."""

    @_safe_envelope(retry_with=["fallback_g"])
    def _odd():
        return None  # non-dict; setdefault would AttributeError if naive

    payload = _odd()
    assert payload is None  # passes through; envelope contract enforcement
    # only applies to dict returns (the 5 tools always return dicts).


# ---------------------------------------------------------------------------
# Integration smoke against live wrappers (skipped when DB absent)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"
_DB_PATH = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_DB)))


@pytest.mark.skipif(
    not _DB_PATH.exists(),
    reason=f"autonomath.db ({_DB_PATH}) not present; skipping wrapper smoke.",
)
class TestWrappedToolsLiveEnvelope:
    """Each of the 5 wrapped tools must round-trip the §I envelope on the
    success path (or graceful-empty path). Error paths are exercised in the
    decorator-level tests above; here we only assert that the integration
    plumbing (underlying tool → wrapper → response) preserves the contract."""

    @classmethod
    def setup_class(cls):
        os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
        os.environ.setdefault("AUTONOMATH_ENABLED", "1")
        from jpintel_mcp.mcp.autonomath_tools.autonomath_wrappers import (
            check_enforcement_am,
            get_law_article_am,
            search_gx_programs_am,
            search_loans_am,
            search_mutual_plans_am,
        )

        cls.search_gx_programs_am = staticmethod(search_gx_programs_am)
        cls.search_loans_am = staticmethod(search_loans_am)
        cls.check_enforcement_am = staticmethod(check_enforcement_am)
        cls.search_mutual_plans_am = staticmethod(search_mutual_plans_am)
        cls.get_law_article_am = staticmethod(get_law_article_am)

    def _assert_required(self, payload):
        assert isinstance(payload, dict)
        for k in ("_billing_unit", "_next_calls"):
            assert k in payload, f"missing §I key: {k}"
        assert isinstance(payload["_billing_unit"], int)
        assert isinstance(payload["_next_calls"], list)

    def test_search_gx_programs_am_envelope_complete(self):
        payload = self.search_gx_programs_am(theme="ghg_reduction", limit=3)
        self._assert_required(payload)

    def test_search_loans_am_envelope_complete(self):
        payload = self.search_loans_am(no_collateral=True, limit=3)
        self._assert_required(payload)

    def test_check_enforcement_am_envelope_complete(self):
        # Use a deliberately unmatched houjin so the call exercises the
        # graceful-empty branch (still must carry §I fields).
        payload = self.check_enforcement_am(houjin_bangou="0000000000000")
        self._assert_required(payload)

    def test_search_mutual_plans_am_envelope_complete(self):
        payload = self.search_mutual_plans_am(plan_kind="dc_pension", limit=3)
        self._assert_required(payload)

    def test_get_law_article_am_envelope_complete(self):
        payload = self.get_law_article_am(
            law_name_or_canonical_id="租税特別措置法",
            article_number="第41条の19",
        )
        self._assert_required(payload)

    def test_get_law_article_am_unknown_law_envelope_complete(self):
        """Error / not-found path on the live wrapper still carries §I keys."""
        payload = self.get_law_article_am(
            law_name_or_canonical_id="存在しない法律XYZ",
            article_number="第1条",
        )
        self._assert_required(payload)
