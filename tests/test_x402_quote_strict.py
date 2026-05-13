"""R2 P1-2 hardening — strict-typing fuzz tests for X402QuotePayload.

The `_verify_x402_quote` path on `src/jpintel_mcp/api/billing_v2.py` used to
parse `amount` and `expires` via `int(payload[...])` / `int(str(payload[...]))`,
which silently accepted whitespace, leading zeros, negatives, and oversize
integers up to Python's unbounded int range. R2 P1-2 audit flagged this as
P1 audit-level: tighten with strict Pydantic v2 typing of the inner 8-key
payload.

These tests fuzz the `X402QuotePayload` model and the `_decode_quote_payload`
+ `_verify_x402_quote` call paths against:

  - extra keys (model rejects)
  - missing keys (model rejects)
  - oversized integers (>= 2**63, and > 10**12 for the amount field)
  - leading zeros (`"007"`)
  - whitespace (`" 1 "`, `"\t1"`, `"1\n"`)
  - negative integers (`-1`)
  - hex case-sensitivity (uppercase / mixed-case EVM addresses are tolerated
    by the regex `[0-9a-fA-F]` but folded to lowercase downstream)
  - expiry far past (already expired -> 422 `expired_quote_id`)
  - expiry far future (within `2**63-1`, accepted)
  - bool injection (`True` must NOT pass for `u` even though bool is an int
    subclass in Python)
  - Unicode digit shenanigans (`"٣"`, `"１"` ASCII-only guard)
  - bool / null / float for numerics

All fuzz failures map to HTTP 422 with `invalid_quote_id` from the public
`_verify_x402_quote` entry point. Direct `X402QuotePayload.model_validate`
tests assert a `ValidationError` so we capture both the model contract and
the end-to-end mapping.

NO LLM imports, NO Anthropic SDK imports, NO real Stripe / RPC calls.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from jpintel_mcp.api.billing_v2 import (
    X402IssueKeyRequest,
    X402QuotePayload,
    _decode_quote_payload,
    _verify_x402_quote,
)

_X402_QUOTE_SECRET = "fuzz-quote-secret"
_X402_RECIPIENT = "0x" + "2" * 40
_X402_PAYER = "0x" + "1" * 40
_X402_TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
_X402_TX_HASH = "0x" + "a" * 64


# ---------- helpers ------------------------------------------------------


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    """Return a wire-shape payload that passes the model."""
    payload: dict[str, Any] = {
        "v": 1,
        "u": "3000",
        "r": _X402_RECIPIENT,
        "p": _X402_PAYER,
        "a": "agent_fuzz_1",
        "e": int(time.time()) + 300,
        "c": "8453",
        "t": _X402_TOKEN,
    }
    payload.update(overrides)
    return payload


def _encode_payload(payload: dict[str, Any]) -> str:
    """Base64url-encode a dict the same way the edge does."""
    return (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )


def _sign(encoded: str) -> str:
    return hmac.new(
        _X402_QUOTE_SECRET.encode("utf-8"),
        encoded.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]


def _quote_id_from(payload: dict[str, Any]) -> str:
    encoded = _encode_payload(payload)
    return f"{encoded}.{_sign(encoded)}"


def _verify(payload: dict[str, Any], *, agent_id: str | None = None) -> dict[str, Any]:
    """End-to-end: sign + verify. Returns the verified dict or raises."""
    if agent_id is None:
        agent_id = str(payload["a"])
    body = X402IssueKeyRequest(
        tx_hash=_X402_TX_HASH,
        quote_id=_quote_id_from(payload),
        agent_id=agent_id,
    )
    return _verify_x402_quote(body)


@pytest.fixture(autouse=True)
def _x402_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JPCITE_X402_QUOTE_SECRET", _X402_QUOTE_SECRET)
    monkeypatch.setenv("JPCITE_X402_ADDRESS", _X402_RECIPIENT)


# ---------- happy path ---------------------------------------------------


def test_happy_path_accepts_edge_wire_shape() -> None:
    """Sanity: the canonical edge wire shape passes end-to-end."""
    out = _verify(_valid_payload())
    assert out["agent_id"] == "agent_fuzz_1"
    assert out["amount_usdc_micro"] == 3000
    assert out["payer_address"] == _X402_PAYER


def test_model_validate_happy_path() -> None:
    """Direct `model_validate` round-trips a valid payload to typed fields."""
    payload = _valid_payload()
    model = X402QuotePayload.model_validate(payload)
    assert model.v == 1
    assert model.u == 3000
    assert model.a == "agent_fuzz_1"
    assert model.p == _X402_PAYER
    assert model.r == _X402_RECIPIENT
    assert model.t == _X402_TOKEN
    assert model.c == "8453"
    assert isinstance(model.e, int)


# ---------- 1. extra keys ------------------------------------------------


def test_fuzz_rejects_extra_key_on_model() -> None:
    payload = _valid_payload(extra="should_not_pass")
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_extra_key_end_to_end() -> None:
    payload = _valid_payload(extra="should_not_pass")
    with pytest.raises(HTTPException) as exc:
        _verify(payload)
    assert exc.value.status_code == 422
    assert exc.value.detail == "invalid_quote_id"


def test_fuzz_rejects_multiple_extra_keys() -> None:
    payload = _valid_payload(foo=1, bar="x", baz=[1, 2, 3])
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


# ---------- 2. missing keys ----------------------------------------------


@pytest.mark.parametrize("missing", ["v", "u", "r", "p", "a", "e", "c", "t"])
def test_fuzz_rejects_missing_key_on_model(missing: str) -> None:
    payload = _valid_payload()
    del payload[missing]
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


@pytest.mark.parametrize("missing", ["v", "u", "r", "p", "a", "e", "c", "t"])
def test_fuzz_rejects_missing_key_end_to_end(missing: str) -> None:
    payload = _valid_payload()
    del payload[missing]
    with pytest.raises(HTTPException) as exc:
        _verify(payload, agent_id="agent_fuzz_1")
    assert exc.value.status_code == 422
    assert exc.value.detail == "invalid_quote_id"


# ---------- 3. oversized integers ----------------------------------------


def test_fuzz_rejects_amount_over_10pow12_as_int() -> None:
    payload = _valid_payload(u=10**12 + 1)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_amount_over_10pow12_as_string() -> None:
    payload = _valid_payload(u=str(10**12 + 1))
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_amount_far_oversize_string() -> None:
    # 2**128 — would have parsed silently with the legacy int(str(...)) path.
    payload = _valid_payload(u=str(2**128))
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_expires_over_int64_max() -> None:
    payload = _valid_payload(e=2**63)  # one past INT64_MAX
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_version_over_int64_max() -> None:
    payload = _valid_payload(v=2**63)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_amount_exactly_at_cap_is_accepted() -> None:
    payload = _valid_payload(u=10**12)
    model = X402QuotePayload.model_validate(payload)
    assert model.u == 10**12


def test_fuzz_amount_exactly_at_cap_as_string_is_accepted() -> None:
    payload = _valid_payload(u=str(10**12))
    model = X402QuotePayload.model_validate(payload)
    assert model.u == 10**12


# ---------- 4. leading zeros ---------------------------------------------


@pytest.mark.parametrize(
    "leading_zero_value",
    ["007", "001", "0001000", "0" + str(10**9)],
)
def test_fuzz_rejects_leading_zero_on_amount_string(leading_zero_value: str) -> None:
    payload = _valid_payload(u=leading_zero_value)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_leading_zero_amount_end_to_end() -> None:
    payload = _valid_payload(u="007")
    with pytest.raises(HTTPException) as exc:
        _verify(payload)
    assert exc.value.status_code == 422


def test_fuzz_rejects_single_zero_amount() -> None:
    # "0" itself is below the `ge=1` floor regardless of leading-zero rule.
    payload = _valid_payload(u="0")
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


# ---------- 5. whitespace ------------------------------------------------


@pytest.mark.parametrize(
    "ws_value",
    [" 1 ", "\t3000", "3000\n", " 3000", "3000 ", "30 00", " 3000"],
)
def test_fuzz_rejects_whitespace_in_amount_string(ws_value: str) -> None:
    payload = _valid_payload(u=ws_value)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_whitespace_in_amount_end_to_end() -> None:
    payload = _valid_payload(u=" 3000 ")
    with pytest.raises(HTTPException) as exc:
        _verify(payload)
    assert exc.value.status_code == 422


# ---------- 6. negatives -------------------------------------------------


@pytest.mark.parametrize("neg_value", [-1, -1000, -(2**63)])
def test_fuzz_rejects_negative_amount_int(neg_value: int) -> None:
    payload = _valid_payload(u=neg_value)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


@pytest.mark.parametrize("neg_str", ["-1", "-3000", "-0", "+3000"])
def test_fuzz_rejects_signed_amount_string(neg_str: str) -> None:
    """Both `-N` and `+N` strings must be rejected by the strict-digit guard."""
    payload = _valid_payload(u=neg_str)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_negative_expires() -> None:
    payload = _valid_payload(e=-1)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_negative_version() -> None:
    payload = _valid_payload(v=-1)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


# ---------- 7. hex case-sensitivity tolerance ----------------------------


def test_fuzz_accepts_uppercase_evm_address_in_payer() -> None:
    """Uppercase hex is wire-legal; downstream folds to lowercase."""
    uppercase_payer = "0x" + "A" * 40
    payload = _valid_payload(p=uppercase_payer)
    model = X402QuotePayload.model_validate(payload)
    assert model.p == uppercase_payer  # raw preserved on the model


def test_fuzz_uppercase_payer_lowers_in_verify_output() -> None:
    uppercase_payer = "0x" + "A" * 40
    payload = _valid_payload(p=uppercase_payer)
    out = _verify(payload)
    assert out["payer_address"] == "0x" + "a" * 40


def test_fuzz_mixed_case_evm_address_accepted() -> None:
    mixed = "0xAbCdEf0123456789aBcDeF0123456789AbCdEf01"
    payload = _valid_payload(p=mixed)
    model = X402QuotePayload.model_validate(payload)
    assert model.p == mixed


def test_fuzz_rejects_too_short_evm_address() -> None:
    payload = _valid_payload(p="0x" + "a" * 39)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_too_long_evm_address() -> None:
    payload = _valid_payload(p="0x" + "a" * 41)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_non_hex_char_in_evm_address() -> None:
    payload = _valid_payload(p="0x" + "g" * 40)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_evm_address_without_0x_prefix() -> None:
    payload = _valid_payload(p="a" * 40)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


# ---------- 8. expiry far past + far future ------------------------------


def test_fuzz_rejects_far_past_expiry() -> None:
    """Expiry one hour in the past trips the time check (not the model)."""
    payload = _valid_payload(e=int(time.time()) - 3600)
    with pytest.raises(HTTPException) as exc:
        _verify(payload)
    assert exc.value.status_code == 422
    assert exc.value.detail == "expired_quote_id"


def test_fuzz_rejects_epoch_zero_expiry() -> None:
    """Epoch-zero is a long-past timestamp."""
    payload = _valid_payload(e=0)
    with pytest.raises(HTTPException) as exc:
        _verify(payload)
    assert exc.value.status_code == 422
    assert exc.value.detail == "expired_quote_id"


def test_fuzz_accepts_far_future_expiry_within_int64() -> None:
    """Far future (10 years out) but still within INT64 is accepted."""
    payload = _valid_payload(e=int(time.time()) + 10 * 365 * 86400)
    out = _verify(payload)
    assert out["expires_at_unix"] > int(time.time())


def test_fuzz_rejects_expiry_past_int64() -> None:
    payload = _valid_payload(e=2**63 + 1)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


# ---------- 9. type-confusion + bool injection ---------------------------


def test_fuzz_rejects_bool_for_amount() -> None:
    """`True` is an `int` subclass; the validator must explicitly reject."""
    payload = _valid_payload(u=True)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_bool_for_expires() -> None:
    """`strict=True` rejects `True` for an int field."""
    payload = _valid_payload(e=True)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_none_for_required_fields() -> None:
    for field in ("v", "u", "r", "p", "a", "e", "c", "t"):
        payload = _valid_payload(**{field: None})
        with pytest.raises(ValidationError):
            X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_float_for_amount() -> None:
    payload = _valid_payload(u=3000.5)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_float_for_expires() -> None:
    payload = _valid_payload(e=float(int(time.time()) + 300))
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_list_for_string_field() -> None:
    payload = _valid_payload(a=["agent_fuzz_1"])
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_dict_for_string_field() -> None:
    payload = _valid_payload(c={"chain": "8453"})
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_unicode_digit_amount() -> None:
    """Arabic-Indic digit U+0663 must NOT pass — `isdigit()` is too lax."""
    payload = _valid_payload(u="٣٠٠٠")  # arabic-indic 3000
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_fullwidth_digit_amount() -> None:
    """Fullwidth digit U+FF13 must NOT pass."""
    payload = _valid_payload(u="３０００")  # ３０００
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_empty_amount_string() -> None:
    payload = _valid_payload(u="")
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


# ---------- 10. agent_id length + content -------------------------------


def test_fuzz_rejects_agent_id_over_64_chars() -> None:
    payload = _valid_payload(a="x" * 65)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_accepts_agent_id_at_exactly_64_chars() -> None:
    payload = _valid_payload(a="x" * 64)
    model = X402QuotePayload.model_validate(payload)
    assert len(model.a) == 64


def test_fuzz_rejects_empty_agent_id() -> None:
    payload = _valid_payload(a="")
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_fuzz_rejects_chain_over_32_chars() -> None:
    payload = _valid_payload(c="x" * 33)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


@pytest.mark.parametrize("chain", ["1", "8454", "84532", "base-sepolia", " 8453"])
def test_fuzz_rejects_non_base_chain(chain: str) -> None:
    payload = _valid_payload(c=chain)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


# ---------- 11. end-to-end coverage: every fuzz category triggers 422 ----


@pytest.mark.parametrize(
    "label,overrides",
    [
        ("extra_key", {"extra": "x"}),
        ("oversize_amount_int", {"u": 10**13}),
        ("oversize_amount_str", {"u": str(10**13)}),
        ("leading_zero_amount", {"u": "007"}),
        ("whitespace_amount", {"u": " 3000 "}),
        ("negative_amount", {"u": -1}),
        ("signed_amount_str", {"u": "-3000"}),
        ("negative_expires", {"e": -1}),
        ("float_amount", {"u": 3000.5}),
        ("bool_amount", {"u": True}),
        ("oversize_version", {"v": 2**63}),
        ("oversize_expires", {"e": 2**63}),
        ("bad_payer_format", {"p": "0xshort"}),
        ("bad_recipient_format", {"r": "not-hex"}),
        ("bad_token_format", {"t": "0x" + "g" * 40}),
        ("over_long_agent", {"a": "x" * 65}),
        ("over_long_chain", {"c": "x" * 33}),
        ("numeric_chain", {"c": 8453}),
        ("unsupported_chain", {"c": "84532"}),
        ("whitespace_chain", {"c": " 8453"}),
        ("unicode_digit_amount", {"u": "٣"}),
    ],
)
def test_fuzz_invalid_quote_id_422(label: str, overrides: dict[str, Any]) -> None:
    """Every reject case lands on 422 `invalid_quote_id` end-to-end."""
    payload = _valid_payload(**overrides)
    with pytest.raises(HTTPException) as exc:
        _verify(payload, agent_id=str(payload.get("a", "agent_fuzz_1")))
    assert exc.value.status_code == 422, label
    assert exc.value.detail == "invalid_quote_id", label


def test_fuzz_decoder_rejects_non_dict_top_level() -> None:
    """A signed array (non-dict) must fail with 422."""
    arr_payload = [1, 2, 3]
    encoded = (
        base64.urlsafe_b64encode(json.dumps(arr_payload).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )
    with pytest.raises(HTTPException) as exc:
        _decode_quote_payload(encoded)
    assert exc.value.status_code == 422


def test_fuzz_decoder_rejects_malformed_base64() -> None:
    """Garbage base64 also lands on 422 `invalid_quote_id`."""
    with pytest.raises(HTTPException) as exc:
        _decode_quote_payload("!!!not-base64!!!")
    assert exc.value.status_code == 422


def test_fuzz_decoder_rejects_malformed_json() -> None:
    """Valid base64 but not JSON must fail with 422."""
    encoded = base64.urlsafe_b64encode(b"not json at all").decode("ascii").rstrip("=")
    with pytest.raises(HTTPException) as exc:
        _decode_quote_payload(encoded)
    assert exc.value.status_code == 422


# ---------- 12. agent_id rebind in verify ---------------------------------


def test_fuzz_rejects_agent_id_mismatch_with_request_body() -> None:
    """The model accepts any 1..64 char agent_id, but `_verify_x402_quote`
    additionally checks it matches the request body's `agent_id`."""
    payload = _valid_payload(a="agent_in_quote")
    body = X402IssueKeyRequest(
        tx_hash=_X402_TX_HASH,
        quote_id=_quote_id_from(payload),
        agent_id="agent_in_request",  # mismatch
    )
    with pytest.raises(HTTPException) as exc:
        _verify_x402_quote(body)
    assert exc.value.status_code == 422
    assert exc.value.detail == "invalid_quote_id"


# ---------- 13. anti-regression: legacy parse pitfalls ------------------


def test_fuzz_legacy_int_str_strip_no_longer_silently_succeeds() -> None:
    """`int(str(" 1 "))` would have parsed silently in the legacy code.

    Anchor: the legacy parser `int(str(payload.get("u")))` returned `1` for
    `" 1 "`. With strict typing, the same payload now 422s.
    """
    payload = _valid_payload(u=" 1 ")
    with pytest.raises(HTTPException) as exc:
        _verify(payload)
    assert exc.value.status_code == 422


def test_fuzz_legacy_leading_zero_no_longer_silently_succeeds() -> None:
    payload = _valid_payload(u="000007")
    with pytest.raises(HTTPException) as exc:
        _verify(payload)
    assert exc.value.status_code == 422


def test_fuzz_legacy_negative_no_longer_silently_succeeds() -> None:
    """`int("-1")` parses to -1; the legacy `or amount <= 0` guard caught
    that, but only after the cast. With strict typing the cast itself fails.
    """
    payload = _valid_payload(u="-1")
    with pytest.raises(HTTPException) as exc:
        _verify(payload)
    assert exc.value.status_code == 422


def test_fuzz_no_llm_imports_in_this_module() -> None:
    """Anti-regression: this module never imports an LLM SDK.

    We check the *imported module's* runtime state rather than grepping the
    source file (because this test would otherwise grep itself and trip on
    the very strings it is checking for).
    """
    import sys

    for forbidden_mod in ("anthropic", "openai", "google.generativeai", "claude_agent_sdk"):
        # Allow incidental loaded copies in other paths (pytest sometimes
        # eagerly imports site-packages); we only care that *this* module
        # didn't import them. Confirm via globals() instead.
        assert forbidden_mod.split(".")[0] not in globals(), (
            f"{forbidden_mod} unexpectedly bound at module scope"
        )
    # And: this module did not capture an LLM API key at import time.
    import os as _os

    for forbidden_env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        assert not _os.environ.get(forbidden_env, ""), f"{forbidden_env} leaked into test env"
    # Sanity: the SUT module itself does not import any LLM SDK. Use a
    # precise `import` token match so the "Anthropic Commerce Protocol"
    # ACP brand label in docstrings doesn't trip the guard.
    sut = sys.modules["jpintel_mcp.api.billing_v2"]
    sut_src = sut.__file__
    assert sut_src is not None
    with open(sut_src, encoding="utf-8") as fh:
        sut_text = fh.read()
    for forbidden_import in (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "claude_agent_sdk",
    ):
        assert forbidden_import not in sut_text, (
            f"billing_v2.py imports forbidden LLM SDK: {forbidden_import}"
        )


# ---------- 14. patch surface guard --------------------------------------


def test_fuzz_decode_quote_payload_returns_typed_model() -> None:
    """`_decode_quote_payload` returns an `X402QuotePayload`, not a dict."""
    payload = _valid_payload()
    encoded = _encode_payload(payload)
    decoded = _decode_quote_payload(encoded)
    assert isinstance(decoded, X402QuotePayload)
    assert decoded.u == 3000


def test_fuzz_decode_does_not_expose_internal_validation_error() -> None:
    """A `ValidationError` must NOT bubble past `_decode_quote_payload`.

    Surface only `HTTPException(422, invalid_quote_id)` to API callers so
    the error envelope stays stable for buyer-side automation.
    """
    payload = _valid_payload(u=-1)
    encoded = _encode_payload(payload)
    with pytest.raises(HTTPException) as exc:
        _decode_quote_payload(encoded)
    assert exc.value.status_code == 422
    # And: no ValidationError leak path. The body shouldn't carry the
    # Pydantic error structure — the public contract is a stable string.
    assert exc.value.detail == "invalid_quote_id"
    # The ValidationError lives in __cause__ only — fine for ops, not for
    # the JSON body.
    assert isinstance(exc.value.__cause__, ValidationError)


def test_fuzz_e_zero_accepted_at_model_level_but_expired_at_verify() -> None:
    """`e=0` passes the model (`ge=0`) but trips the `expired_quote_id`
    check inside `_verify_x402_quote`. Both reach 422 either way."""
    payload = _valid_payload(e=0)
    model = X402QuotePayload.model_validate(payload)
    assert model.e == 0
    with pytest.raises(HTTPException) as exc:
        _verify(payload)
    assert exc.value.status_code == 422
    assert exc.value.detail == "expired_quote_id"


# ---------- 15. no environmental side-effects on validation -------------


def test_fuzz_model_validate_does_not_call_time() -> None:
    """Model validation is pure — no `time.time()` reach-through.

    `_valid_payload` itself calls `time.time()` to fill `e`. We materialize
    a payload *before* the patch window so the patch only sees calls that
    happen inside `model_validate`.
    """
    payload = _valid_payload()
    calls = {"n": 0}

    def _fake_time() -> float:
        calls["n"] += 1
        return 0.0

    with patch("jpintel_mcp.api.billing_v2.time.time", side_effect=_fake_time):
        X402QuotePayload.model_validate(payload)

    assert calls["n"] == 0
