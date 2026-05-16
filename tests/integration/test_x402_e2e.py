"""Wave 59 Stream D — end-to-end smoke for the Wave 51 x402_payment scaffolding.

The Wave 51 ``src/jpintel_mcp/x402_payment/`` package ships a router-agnostic
challenge factory + Pydantic envelope contract, but had no end-to-end HTTP
smoke proving the **402 -> proof verify -> 200 outcome** chain works against
a real FastAPI request stack. This module wires a minimal in-test harness
(scoped to this file, not exported) and asserts the five canonical scenarios
the x402 protocol must satisfy.

Scenarios
---------

1. **402 challenge response valid** — GET /v1/outcomes/<id> with no payment
   token returns HTTP 402, ``X-Payment-Required: true`` header, and a body
   that round-trips through ``X402Challenge`` (resource_url / price_yen /
   accepted_payment_methods / expires_at / challenge_nonce all present and
   well-formed).

2. **invalid token -> 402 retry** — GET /v1/outcomes/<id> with a malformed
   ``X-Payment-Token`` header returns HTTP 402 again (NOT 401 / 403). The
   protocol contract is "show me money" stays on 402 even for malformed
   prior attempts, mirroring the production middleware in
   ``api/x402_payment.py`` (verify_failed branch).

3. **valid token (mocked) -> 200 outcome JSON** — GET /v1/outcomes/<id> with
   a well-formed ``X-Payment-Token`` (mocked USDC payment proof per the
   scaffolding ``verify_payment`` contract) returns HTTP 200 with the
   outcome JSON envelope. Asserts the nonce / amount validation path is
   actually exercised, not just shape-checked.

4. **idempotency key replay** — replaying the same ``X-Idempotency-Key``
   with the same valid proof against the same outcome returns the same
   ``payment_id`` (no double-charge). The mock ledger records exactly ONE
   settlement row.

5. **settlement timeout (2-sec SLA)** — the full 402 -> proof -> 200 chain
   completes in under 2 seconds end-to-end. This is the x402 protocol
   target ("decisive 2 second under settlement" per
   feedback_agent_x402_protocol). The smoke harness is in-process (no
   network) so the SLA is a lower bound on the production budget.

Constraints
-----------

* **No real Coinbase / Base testnet calls** — USDC settlement is mocked via
  the scaffolding ``verify_payment`` signature-shape verifier. A real chain
  RPC would require funded Base wallets + network access; the scaffolding
  exists precisely to keep CI hermetic.
* **No LLM imports** anywhere on the request path (the production rule
  ``feedback_no_operator_llm_api``).
* **No DB writes** — the harness uses an in-memory dict ledger scoped to the
  fixture so the 9.4 GB production ``autonomath.db`` is never touched.
* **Uses the scaffolding package, not the FastAPI router** — the production
  middleware at ``src/jpintel_mcp/api/x402_payment.py`` is DB-coupled and
  settings-coupled; this smoke proves the router-agnostic envelope contract
  is sufficient for a working 402 -> 200 flow.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pytest
from fastapi import FastAPI, Header, Request, status
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from jpintel_mcp.x402_payment import (
    DEFAULT_CHALLENGE_TTL_SEC,
    X402Challenge,
    X402PaymentMethod,
    X402PaymentProof,
    generate_402_response,
    verify_payment,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# --- harness ---------------------------------------------------------------
#
# An in-process FastAPI app that wraps the scaffolding into a working
# 402 -> proof -> 200 chain. Each test gets a fresh app + fresh state so the
# nonce / idempotency / ledger bookkeeping is hermetic.


_OUTCOME_PRICE_YEN: int = 300  # canonical outcome price band (¥300-¥900).


def _build_harness() -> tuple[FastAPI, dict[str, Any]]:
    """Build a fresh FastAPI harness + per-test mutable state.

    The state dict carries:

    * ``challenges``: nonce -> X402Challenge issued by the harness.
    * ``ledger``: txn_hash -> dict (mock settlement row, idempotent).
    * ``idempotency``: idempotency_key -> payment_id (replay table).
    """

    app = FastAPI()
    state: dict[str, Any] = {
        "challenges": {},
        "ledger": {},
        "idempotency": {},
        "next_payment_id": 1,
    }

    @app.get("/v1/outcomes/{outcome_id}")
    async def get_outcome(
        outcome_id: str,
        request: Request,
        x_payment_token: str | None = Header(default=None, alias="X-Payment-Token"),
        x_payment_payer: str | None = Header(default=None, alias="X-Payment-Payer"),
        x_payment_nonce: str | None = Header(default=None, alias="X-Payment-Nonce"),
        x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    ) -> JSONResponse:
        resource_url = str(request.url.path)

        # No token => fresh 402 challenge.
        if not x_payment_token:
            challenge = generate_402_response(
                resource_url,
                billing_hint={"price_yen": _OUTCOME_PRICE_YEN},
            )
            state["challenges"][challenge.challenge_nonce] = challenge
            return JSONResponse(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                content=challenge.model_dump(mode="json"),
                headers={
                    "X-Payment-Required": "true",
                    "X-Payment-Challenge-Nonce": challenge.challenge_nonce,
                },
            )

        # Idempotency replay short-circuits BEFORE re-verifying so the
        # ledger row is not double-written.
        if x_idempotency_key and x_idempotency_key in state["idempotency"]:
            payment_id = state["idempotency"][x_idempotency_key]
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "outcome_id": outcome_id,
                    "payment_id": payment_id,
                    "idempotent_replay": True,
                    "amount_yen": _OUTCOME_PRICE_YEN,
                },
            )

        # Token present => parse + verify as a scaffolding proof envelope.
        # The "token" here mocks USDC on Base — production wires a real
        # signature; the scaffolding only checks envelope shape.
        if not x_payment_nonce or not x_payment_payer:
            return _verify_failed_response(resource_url)

        challenge = state["challenges"].get(x_payment_nonce)
        if challenge is None:
            # Unknown nonce => 402 retry (not 401), per the protocol.
            return _verify_failed_response(resource_url)

        try:
            proof = X402PaymentProof(
                challenge_nonce=x_payment_nonce,
                payment_method=X402PaymentMethod.USDC_BASE,
                payer_id=x_payment_payer,
                amount_yen=_OUTCOME_PRICE_YEN,
                signature=x_payment_token,
            )
        except ValueError:
            return _verify_failed_response(resource_url)

        if not verify_payment(
            proof,
            expected_challenge_nonce=challenge.challenge_nonce,
            expected_amount_yen=challenge.price_yen,
        ):
            return _verify_failed_response(resource_url)

        # Verified => settle (mock) and return outcome JSON.
        txn_hash = f"0x{x_payment_token}"
        if txn_hash in state["ledger"]:
            # Same txn already settled — surface the original payment_id.
            payment_id = state["ledger"][txn_hash]["payment_id"]
        else:
            payment_id = int(state["next_payment_id"])
            state["next_payment_id"] = payment_id + 1
            state["ledger"][txn_hash] = {
                "payment_id": payment_id,
                "amount_yen": _OUTCOME_PRICE_YEN,
                "payer_id": x_payment_payer,
                "challenge_nonce": x_payment_nonce,
                "settled_at_unix": int(time.time()),
            }

        if x_idempotency_key:
            state["idempotency"][x_idempotency_key] = payment_id

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "outcome_id": outcome_id,
                "payment_id": payment_id,
                "idempotent_replay": False,
                "amount_yen": _OUTCOME_PRICE_YEN,
            },
        )

    return app, state


def _verify_failed_response(resource_url: str) -> JSONResponse:
    """Issue a fresh 402 with a verify_failed marker — protocol stays on 402."""
    challenge = generate_402_response(
        resource_url,
        billing_hint={"price_yen": _OUTCOME_PRICE_YEN},
    )
    body = challenge.model_dump(mode="json")
    body["error"] = "verify_failed"
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content=body,
        headers={
            "X-Payment-Required": "true",
            "X-Payment-Challenge-Nonce": challenge.challenge_nonce,
        },
    )


# --- fixtures --------------------------------------------------------------


@pytest.fixture()
def harness() -> Iterator[tuple[TestClient, dict[str, Any]]]:
    """Yield a fresh ``(TestClient, state)`` per test for full isolation."""
    app, state = _build_harness()
    with TestClient(app) as client:
        yield client, state


# --- scenarios -------------------------------------------------------------


def test_scenario_1_402_challenge_response_valid(
    harness: tuple[TestClient, dict[str, Any]],
) -> None:
    """Scenario 1: GET without token returns 402 + well-formed challenge."""
    client, state = harness

    response = client.get("/v1/outcomes/outcome_program_search")

    assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
    assert response.headers.get("X-Payment-Required") == "true"
    assert response.headers.get("X-Payment-Challenge-Nonce")

    body = response.json()
    # Round-trip through the scaffolding envelope to prove shape.
    challenge = X402Challenge.model_validate(body)
    assert challenge.resource_url == "/v1/outcomes/outcome_program_search"
    assert challenge.price_yen == _OUTCOME_PRICE_YEN
    assert X402PaymentMethod.USDC_BASE in challenge.accepted_payment_methods
    assert len(challenge.challenge_nonce) >= 8
    # TTL window must be in the future + within the canonical envelope.
    now = int(time.time())
    assert challenge.expires_at > now
    assert challenge.expires_at <= now + DEFAULT_CHALLENGE_TTL_SEC + 5
    # Server recorded the nonce so future verify calls can match it.
    assert challenge.challenge_nonce in state["challenges"]


def test_scenario_2_invalid_token_returns_402_retry(
    harness: tuple[TestClient, dict[str, Any]],
) -> None:
    """Scenario 2: malformed token => 402 retry, NOT 401/403.

    Three invalid-token shapes must all stay on 402:

    * unknown nonce (server never issued it)
    * missing payer header
    * empty / too-short signature
    """
    client, state = harness

    # Sub-case A: unknown nonce.
    response = client.get(
        "/v1/outcomes/outcome_program_search",
        headers={
            "X-Payment-Token": "0xdeadbeefcafef00d",
            "X-Payment-Payer": "0x1111111111111111111111111111111111111111",
            "X-Payment-Nonce": "totally-not-a-real-nonce",
        },
    )
    assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
    assert response.json().get("error") == "verify_failed"

    # Sub-case B: missing payer header (token + nonce present).
    response = client.get(
        "/v1/outcomes/outcome_program_search",
        headers={
            "X-Payment-Token": "0xdeadbeefcafef00d",
            "X-Payment-Nonce": "totally-not-a-real-nonce",
        },
    )
    assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
    assert response.json().get("error") == "verify_failed"

    # Sub-case C: empty / too-short signature — fails X402PaymentProof
    # validation (min_length=8) and routes to verify_failed.
    bootstrap = client.get("/v1/outcomes/outcome_program_search")
    nonce = bootstrap.headers["X-Payment-Challenge-Nonce"]
    response = client.get(
        "/v1/outcomes/outcome_program_search",
        headers={
            "X-Payment-Token": "x",  # too short
            "X-Payment-Payer": "0x2222222222222222222222222222222222222222",
            "X-Payment-Nonce": nonce,
        },
    )
    assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
    assert response.json().get("error") == "verify_failed"

    # No ledger row ever written across the three sub-cases.
    assert state["ledger"] == {}


def test_scenario_3_valid_token_returns_200_outcome(
    harness: tuple[TestClient, dict[str, Any]],
) -> None:
    """Scenario 3: valid token (mocked USDC proof) => 200 outcome JSON."""
    client, state = harness

    # Step 1: fetch a fresh challenge to learn the nonce.
    challenge_response = client.get("/v1/outcomes/outcome_case_search")
    assert challenge_response.status_code == status.HTTP_402_PAYMENT_REQUIRED
    nonce = challenge_response.headers["X-Payment-Challenge-Nonce"]
    assert nonce in state["challenges"]

    # Step 2: present a well-formed token (mock USDC Base proof).
    valid_token = "0xabcdef0123456789abcdef0123456789abcdef01"
    payer = "0x3333333333333333333333333333333333333333"

    response = client.get(
        "/v1/outcomes/outcome_case_search",
        headers={
            "X-Payment-Token": valid_token,
            "X-Payment-Payer": payer,
            "X-Payment-Nonce": nonce,
        },
    )
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["outcome_id"] == "outcome_case_search"
    assert isinstance(body["payment_id"], int)
    assert body["payment_id"] >= 1
    assert body["idempotent_replay"] is False
    assert body["amount_yen"] == _OUTCOME_PRICE_YEN

    # Settlement ledger has exactly one row for this txn.
    txn_hash = f"0x{valid_token}"
    assert txn_hash in state["ledger"]
    assert state["ledger"][txn_hash]["payer_id"] == payer


def test_scenario_4_idempotency_key_replay(
    harness: tuple[TestClient, dict[str, Any]],
) -> None:
    """Scenario 4: same idempotency key => same payment_id, no double-charge."""
    client, state = harness

    # Step 1: bootstrap nonce.
    bootstrap = client.get("/v1/outcomes/outcome_audit_pack")
    nonce = bootstrap.headers["X-Payment-Challenge-Nonce"]

    valid_token = "0x1234567890abcdef1234567890abcdef12345678"
    payer = "0x4444444444444444444444444444444444444444"
    idempotency_key = "client-tx-2026-05-16-00001"

    # Step 2: first call settles + records payment_id.
    first = client.get(
        "/v1/outcomes/outcome_audit_pack",
        headers={
            "X-Payment-Token": valid_token,
            "X-Payment-Payer": payer,
            "X-Payment-Nonce": nonce,
            "X-Idempotency-Key": idempotency_key,
        },
    )
    assert first.status_code == status.HTTP_200_OK
    first_body = first.json()
    assert first_body["idempotent_replay"] is False
    first_payment_id = first_body["payment_id"]

    # Step 3: replay with the same idempotency key — same payment_id,
    # ``idempotent_replay=True``, ledger stays at one row.
    replay = client.get(
        "/v1/outcomes/outcome_audit_pack",
        headers={
            "X-Payment-Token": valid_token,
            "X-Payment-Payer": payer,
            "X-Payment-Nonce": nonce,
            "X-Idempotency-Key": idempotency_key,
        },
    )
    assert replay.status_code == status.HTTP_200_OK
    replay_body = replay.json()
    assert replay_body["payment_id"] == first_payment_id
    assert replay_body["idempotent_replay"] is True

    # Ledger still has exactly one settlement row.
    assert len(state["ledger"]) == 1
    # Idempotency table records the key.
    assert state["idempotency"][idempotency_key] == first_payment_id


def test_scenario_5_settlement_timeout_2_sec_sla(
    harness: tuple[TestClient, dict[str, Any]],
) -> None:
    """Scenario 5: end-to-end 402 -> proof -> 200 finishes under 2 seconds.

    This is the x402 protocol target ("decisive 2 second under settlement").
    The smoke is in-process so the SLA is a lower bound; production has the
    additional Fly + CF edge + Base RPC budget on top.
    """
    client, _state = harness

    valid_token = "0xfeedfacefeedfacefeedfacefeedfacefeedface"
    payer = "0x5555555555555555555555555555555555555555"

    started_at = time.monotonic()

    # Step 1: 402 challenge.
    challenge_response = client.get("/v1/outcomes/outcome_loan_match")
    assert challenge_response.status_code == status.HTTP_402_PAYMENT_REQUIRED
    nonce = challenge_response.headers["X-Payment-Challenge-Nonce"]

    # Step 2: settlement.
    settlement = client.get(
        "/v1/outcomes/outcome_loan_match",
        headers={
            "X-Payment-Token": valid_token,
            "X-Payment-Payer": payer,
            "X-Payment-Nonce": nonce,
        },
    )
    assert settlement.status_code == status.HTTP_200_OK

    elapsed = time.monotonic() - started_at
    assert elapsed < 2.0, (
        f"x402 settlement exceeded 2-sec SLA: elapsed={elapsed:.3f}s "
        "(scaffolding harness should finish in <100ms; "
        "investigate before relaxing this threshold)"
    )
