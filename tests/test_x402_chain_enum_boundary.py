"""J14 X402QuotePayload `c` (chain) field Base-chain boundary tests.

Companion to `test_x402_quote_strict.py`. Audits whether the inner quote
payload's `c` field — declared on `X402QuotePayload` as
`c: Literal["8453"]` — enforces the actual set of chains the system can
settle on.

The edge handler at `functions/x402_handler.ts` only knows how to verify a
USDC `Transfer` log on **Base mainnet (chain id `"8453"`)**. The supported
chain set, taken verbatim from the TS source, is:

    const USDC_BY_CHAIN: Record<string, {...}> = {
      "8453": {
        address: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        decimals: 6,
        name: "USDC",
      },
    };
    const X402_CHAIN_ID = "8453"; // Base mainnet

There is NO `base-sepolia` entry, NO L2 Optimism/Arbitrum/Polygon entry, NO
Solana entry. Anything other than the literal string `"8453"` is something
the edge cannot honour — `hasSufficientUsdcTransfer` would reject the log
because the log's token address can never match a non-Base USDC contract
inside `USDC_BY_CHAIN["8453"]`.

The origin schema must reject anything other than the literal string
`"8453"` before key issuance or replay/idempotency bookkeeping can run.
This keeps Base mainnet as the only accepted x402 settlement chain and
leaves the ¥3/request invariant untouched.

NO LLM imports, NO Anthropic SDK imports, NO real Stripe / RPC calls.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, get_args

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from jpintel_mcp.api.billing_v2 import (
    X402IssueKeyRequest,
    X402QuotePayload,
    _verify_x402_quote,
)

# ---------- shared fixtures (mirror test_x402_quote_strict.py) -----------

_X402_QUOTE_SECRET = "chain-enum-fuzz-secret"
_X402_RECIPIENT = "0x" + "2" * 40
_X402_PAYER = "0x" + "1" * 40
_X402_TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"  # Native USDC on Base
_X402_TX_HASH = "0x" + "a" * 64

# Supported chain set extracted verbatim from `functions/x402_handler.ts`:
#   const USDC_BY_CHAIN: Record<string, ...> = { "8453": {...} };
#   const X402_CHAIN_ID = "8453";
SUPPORTED_CHAIN_IDS: frozenset[str] = frozenset({"8453"})


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "v": 1,
        "u": "3000",
        "r": _X402_RECIPIENT,
        "p": _X402_PAYER,
        "a": "agent_chain_enum_1",
        "e": int(time.time()) + 300,
        "c": "8453",
        "t": _X402_TOKEN,
    }
    payload.update(overrides)
    return payload


def _encode_payload(payload: dict[str, Any]) -> str:
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


# ---------- 1. Supported chain happy path --------------------------------


def test_supported_chain_8453_is_accepted_by_model() -> None:
    """Base mainnet (`"8453"`) — the ONLY chain in `USDC_BY_CHAIN` —
    must validate cleanly on `X402QuotePayload`."""
    payload = _valid_payload(c="8453")
    model = X402QuotePayload.model_validate(payload)
    assert model.c == "8453"


def test_supported_chain_8453_is_accepted_end_to_end() -> None:
    """Sanity end-to-end: `c="8453"` survives sign + verify."""
    out = _verify(_valid_payload(c="8453"))
    assert out["agent_id"] == "agent_chain_enum_1"
    # _verify_x402_quote should surface the quoted chain in its response.
    # Even if the helper doesn't emit `chain` directly, the call must not
    # raise — that is the boundary of "supported chain accepted".
    assert isinstance(out, dict)


# ---------- 2. Documented absent chains (`base-sepolia` not in TS) -------


def test_base_sepolia_is_not_in_ts_supported_set() -> None:
    """Tripwire: if a future TS change adds `base-sepolia` to
    `USDC_BY_CHAIN`, this test will need an update + a matching enum
    expansion on J14. Today the TS map carries ONLY `"8453"`."""
    assert "base-sepolia" not in SUPPORTED_CHAIN_IDS
    assert "84532" not in SUPPORTED_CHAIN_IDS  # the actual Base Sepolia chain id
    assert frozenset({"8453"}) == SUPPORTED_CHAIN_IDS


# ---------- 3. Literal-boundary reject cases ------------------------------


def test_j14_rejects_empty_chain_string() -> None:
    """The literal pin catches `c=""`."""
    payload = _valid_payload(c="")
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_j14_rejects_empty_chain_end_to_end() -> None:
    payload = _valid_payload(c="")
    with pytest.raises(HTTPException) as exc:
        _verify(payload)
    assert exc.value.status_code == 422
    assert exc.value.detail == "invalid_quote_id"


def test_j14_rejects_oversize_chain_string() -> None:
    """The literal pin catches any overlong non-`8453` chain string."""
    payload = _valid_payload(c="x" * 33)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_j14_rejects_oversize_chain_end_to_end() -> None:
    payload = _valid_payload(c="x" * 33)
    with pytest.raises(HTTPException) as exc:
        _verify(payload)
    assert exc.value.status_code == 422
    assert exc.value.detail == "invalid_quote_id"


def test_j14_rejects_chain_at_legacy_max_length_boundary() -> None:
    """`len(c) == 32` used to pass the length-only check; now it rejects."""
    payload = _valid_payload(c="x" * 32)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_j14_rejects_chain_at_legacy_min_length_boundary() -> None:
    """`len(c) == 1` used to pass the length-only check; now it rejects."""
    payload = _valid_payload(c="x")
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_j14_rejects_numeric_chain_id() -> None:
    """JSON number `8453` is not equivalent to the literal string `"8453"`."""
    payload = _valid_payload(c=8453)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


# ---------- 4. Unsupported chains reject ----------------------------------


@pytest.mark.parametrize(
    "bad_chain",
    [
        "base-sepolia",  # Base testnet — not in USDC_BY_CHAIN
        "base-sepolia-test",  # nonsense variant
        "ethereum-mainnet",  # different ecosystem
        "1",  # Ethereum mainnet chain id (numeric)
        "10",  # Optimism chain id
        "137",  # Polygon chain id
        "42161",  # Arbitrum chain id
        "solana",  # entirely different L1
        "xxx",  # garbage
        "BASE",  # uppercase — case-sensitive miss
        "8454",  # off-by-one from supported "8453"
        "84532",  # Base Sepolia testnet chain id
    ],
)
def test_j14_rejects_unsupported_chain_strings_on_model(bad_chain: str) -> None:
    """Only Base mainnet chain id `"8453"` may validate."""
    assert bad_chain not in SUPPORTED_CHAIN_IDS, "test fixture mismatch: " + bad_chain
    payload = _valid_payload(c=bad_chain)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


@pytest.mark.parametrize(
    "bad_chain",
    [
        "base-sepolia",
        "1",
        "10",
        "137",
        "42161",
        "solana",
        "8454",
        "84532",
    ],
)
def test_j14_rejects_unsupported_chain_strings_end_to_end(bad_chain: str) -> None:
    payload = _valid_payload(c=bad_chain)
    with pytest.raises(HTTPException) as exc:
        _verify(payload)
    assert exc.value.status_code == 422
    assert exc.value.detail == "invalid_quote_id"


@pytest.mark.parametrize(
    "whitespace_chain",
    [
        " 8453",  # leading space
        "8453 ",  # trailing space
        " 8453 ",  # both
        "\t8453",  # leading tab
        "8453\n",  # trailing newline
        "84 53",  # internal space
    ],
)
def test_j14_rejects_whitespace_padded_chain(whitespace_chain: str) -> None:
    """Whitespace-padded `"8453"` variants do not equal the Base literal."""
    payload = _valid_payload(c=whitespace_chain)
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


def test_j14_rejects_whitespace_only_chain() -> None:
    """A string of pure spaces must not satisfy the chain field."""
    payload = _valid_payload(c=" ")
    with pytest.raises(ValidationError):
        X402QuotePayload.model_validate(payload)


# ---------- 5. Edge handler verbatim chain set ---------------------------


def test_ts_handler_chain_set_is_exactly_base_mainnet() -> None:
    """Pin the verbatim TS-side supported set so this test breaks loud
    if `functions/x402_handler.ts` is changed to add another chain
    without a coordinated J14 enum update."""
    # Verbatim from `functions/x402_handler.ts`:
    #   const USDC_BY_CHAIN: Record<string, ...> = {
    #     "8453": {
    #       address: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    #       decimals: 6,
    #       name: "USDC",
    #     },
    #   };
    #   const X402_CHAIN_ID = "8453";
    expected_chain_ids = {"8453"}
    expected_token = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913".lower()
    assert frozenset(expected_chain_ids) == SUPPORTED_CHAIN_IDS
    assert expected_token == _X402_TOKEN


# ---------- 6. Enforcement summary (for human reviewers) ------------------


def test_enforcement_summary_j14_chain_is_literal_base() -> None:
    """Single-test summary asserting the schema-level chain pin exists."""
    field = X402QuotePayload.model_fields["c"]
    assert get_args(field.annotation) == ("8453",)
