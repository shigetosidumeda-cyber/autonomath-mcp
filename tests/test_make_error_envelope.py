"""W8-5 finding: ``make_error()`` must satisfy the MASTER_PLAN §I
envelope contract on the error path too — every response (success OR
error) must carry the canonical 6-key surface so customer LLMs and
downstream tolerant consumers never key-miss::

    total / limit / offset / results / _billing_unit / _next_calls

Pre-fix, ``make_error()`` returned only ``error / code / message /
_disclaimer``-shaped dicts plus ``total / limit / offset / results`` —
``_billing_unit`` and ``_next_calls`` were missing. This caused
envelope-contract violations whenever a Wave21/22/24 / industry_packs /
composition tool short-circuited via ``make_error()`` instead of going
through its own success-path envelope assembly.

These tests pin the contract so the regression cannot return.
"""

from __future__ import annotations

from jpintel_mcp.mcp.autonomath_tools.error_envelope import (
    ERROR_CODES,
    is_error,
    make_error,
)

# Six fields the envelope contract requires on every response.
REQUIRED_ENVELOPE_FIELDS = (
    "total",
    "limit",
    "offset",
    "results",
    "_billing_unit",
    "_next_calls",
)


def test_make_error_returns_all_required_envelope_fields() -> None:
    """Minimal call: every required envelope field is present and the
    error block also exists alongside them."""
    payload = make_error("internal", "boom")
    for field in REQUIRED_ENVELOPE_FIELDS:
        assert field in payload, f"required envelope field missing: {field}"
    assert "error" in payload
    assert isinstance(payload["error"], dict)


def test_make_error_billing_unit_is_zero_on_error_path() -> None:
    """Error never bills the customer — ``_billing_unit`` MUST be 0
    on every error envelope so the metering layer cannot accidentally
    charge a request that produced no useful output."""
    payload = make_error("db_locked", "DB busy")
    assert payload["_billing_unit"] == 0
    assert isinstance(payload["_billing_unit"], int)


def test_make_error_next_calls_is_empty_list_on_error_path() -> None:
    """``_next_calls`` defaults to an empty list (not None / not missing)
    so consumers can iterate without a None-guard."""
    payload = make_error("no_matching_records", "nothing matched")
    assert payload["_next_calls"] == []
    assert isinstance(payload["_next_calls"], list)


def test_make_error_total_results_offset_limit_shape() -> None:
    """The pre-existing four envelope fields keep their semantics."""
    payload = make_error("invalid_enum", "bad enum", limit=37, offset=12)
    assert payload["total"] == 0
    assert payload["results"] == []
    assert payload["limit"] == 37
    assert payload["offset"] == 12


def test_make_error_limit_is_clamped_to_1_100() -> None:
    """``limit`` clamps to the inclusive [1, 100] range (existing
    behaviour, kept under test so the envelope guarantee holds)."""
    too_low = make_error("internal", "x", limit=0)
    too_high = make_error("internal", "x", limit=999)
    assert too_low["limit"] == 1
    assert too_high["limit"] == 100


def test_make_error_offset_floor_zero() -> None:
    """``offset`` floors at 0 even if a negative is passed in."""
    payload = make_error("internal", "x", offset=-5)
    assert payload["offset"] == 0


def test_make_error_is_error_helper_still_recognises_envelope() -> None:
    """Adding new keys must not break ``is_error()`` detection — the
    envelope_wrapper hot path keys off this. Verify across every code
    in the closed enum."""
    for code in ERROR_CODES:
        payload = make_error(code, f"msg for {code}")
        assert is_error(payload), f"is_error() rejected envelope for code={code}"


def test_make_error_every_canonical_code_has_full_envelope() -> None:
    """Exhaustive sweep: every closed-enum code yields the full
    6-field envelope. Catches any future code that bypasses the
    helper's return path."""
    for code in ERROR_CODES:
        payload = make_error(code, f"msg for {code}")
        for field in REQUIRED_ENVELOPE_FIELDS:
            assert field in payload, f"code={code} missing envelope field={field}"
        assert payload["_billing_unit"] == 0
        assert payload["_next_calls"] == []


def test_make_error_unknown_code_coerced_to_internal_still_full_envelope() -> None:
    """Defensive coercion of unknown codes to ``internal`` must not
    drop any envelope field."""
    payload = make_error("totally_made_up_code", "x")  # type: ignore[arg-type]
    assert payload["error"]["code"] == "internal"
    for field in REQUIRED_ENVELOPE_FIELDS:
        assert field in payload


def test_make_error_extra_does_not_collide_with_envelope_fields() -> None:
    """``extra`` is merged into the ``error`` sub-dict via setdefault,
    NOT into the top-level envelope, so it cannot clobber
    ``_billing_unit`` / ``_next_calls`` / ``results`` etc."""
    payload = make_error(
        "internal",
        "x",
        extra={"_billing_unit": 999, "_next_calls": ["evil"], "seed_name": "ok"},
    )
    # Top-level envelope fields stay at the contractual defaults.
    assert payload["_billing_unit"] == 0
    assert payload["_next_calls"] == []
    # Extras live inside the ``error`` block.
    assert payload["error"]["_billing_unit"] == 999
    assert payload["error"]["_next_calls"] == ["evil"]
    assert payload["error"]["seed_name"] == "ok"
