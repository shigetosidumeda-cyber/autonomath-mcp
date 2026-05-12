"""Wave 48 — x402 full payment chain integration tests.

Exercises the end-to-end ``HTTP 402 -> proof verify -> 200`` flow that
``src/jpintel_mcp/api/x402_payment.py`` wires onto the 5 canonical
endpoints registered in ``am_x402_endpoint_config`` (migration 282).

Layered scenarios
-----------------
  1. No header                    => 402 + challenge payload
  2. Header present, no payer     => 401 missing_payer_or_nonce
  3. Header present, wrong proof  => 402 + verify_failed (NOT 401)
  4. Header + payer + valid proof => 200 + payment_id + audit row written
  5. Replay valid proof on same   => 200 + same payment_id (idempotent
     via UNIQUE(txn_hash))
  6. Pass-through path (not gated)=> 200 (middleware does NOT intercept)
  7. Middleware ordering          => x402 middleware sits AFTER
     IdempotencyMiddleware in main.py (added later → runs earlier in LIFO)
  8. LLM-0                        => new file has zero LLM SDK imports
  9. Brand discipline             => no legacy 税務会計AI / zeimu-kaikei.ai

All tests use a throwaway FastAPI app that mounts ONLY the x402 router
+ middleware + a dummy "/v1/search" handler. We do NOT spin up the full
``api.main:app`` because that triggers the 9 GB autonomath.db warmup.

NO real RPC / on-chain call. NO LLM import anywhere in this file.
"""

from __future__ import annotations

import pathlib
import sqlite3
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jpintel_mcp.api import x402_payment

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_282 = REPO_ROOT / "scripts" / "migrations" / "282_x402_payment.sql"
X402_SRC = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "x402_payment.py"
MAIN_SRC = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "main.py"

GATED_ENDPOINTS = (
    "/v1/search",
    "/v1/programs",
    "/v1/cases",
    "/v1/audit_workpaper",
    "/v1/semantic_search",
)


# ---------- shared fixtures ----------------------------------------------


@pytest.fixture()
def seeded_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Fresh autonomath.db with migration 282 applied and 5 endpoints seeded."""
    db_path = tmp_path / "autonomath_x402.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(MIG_282.read_text(encoding="utf-8"))
        for path in GATED_ENDPOINTS:
            conn.execute(
                "INSERT INTO am_x402_endpoint_config "
                "(endpoint_path, required_amount_usdc) VALUES (?, ?)",
                (path, 0.001),
            )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    return db_path


@pytest.fixture()
def app(seeded_db: pathlib.Path) -> FastAPI:
    """Minimal app: middleware + diagnostic router + 5 dummy gated handlers."""
    application = FastAPI()
    application.add_middleware(x402_payment.X402PaymentMiddleware)
    application.include_router(x402_payment.router)

    # Dummy handlers — when the middleware passes a request through,
    # these confirm the handler actually ran.
    for path in GATED_ENDPOINTS:
        def _make(p: str):
            async def _h() -> dict[str, Any]:
                return {"ok": True, "path": p}

            return _h

        application.get(path)(_make(path))

    # Non-gated path for the pass-through test.
    @application.get("/v1/openapi.json")
    async def _openapi() -> dict[str, Any]:
        return {"openapi": "3.1.0"}

    return application


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---------- 1. No header => 402 challenge --------------------------------


def test_no_header_returns_402(client: TestClient) -> None:
    resp = client.get("/v1/search")
    assert resp.status_code == 402
    body = resp.json()
    assert body["error"] == "payment_required"
    assert body["endpoint_path"] == "/v1/search"
    assert body["required_amount_usdc"] == pytest.approx(0.001)
    assert body["settle_currency"] == "USDC"
    assert body["settle_chain"] == "base"
    assert len(body["challenge_nonce"]) >= 8
    assert body["proof_header"] == "X-Payment-Proof"
    assert "X-Payment-Required" in resp.headers
    assert resp.headers["X-Payment-Challenge-Nonce"] == body["challenge_nonce"]


# ---------- 2. Header without payer => 401 -------------------------------


def test_header_without_payer_returns_401(client: TestClient) -> None:
    resp = client.get(
        "/v1/programs",
        headers={"X-Payment-Proof": "some-proof-string"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "missing_payer_or_nonce"


def test_header_with_payer_but_no_nonce_returns_401(client: TestClient) -> None:
    resp = client.get(
        "/v1/cases",
        headers={
            "X-Payment-Proof": "some-proof-string",
            "X-Payment-Payer": "0x" + "a" * 40,
        },
    )
    assert resp.status_code == 401


# ---------- 3. Bad proof => 402 verify_failed (NOT 401) -------------------


def test_wrong_proof_returns_402_verify_failed(client: TestClient) -> None:
    # First, harvest a valid challenge nonce.
    challenge_resp = client.get("/v1/audit_workpaper")
    nonce = challenge_resp.json()["challenge_nonce"]
    # Replay with a tampered proof.
    resp = client.get(
        "/v1/audit_workpaper",
        headers={
            "X-Payment-Proof": "0x" + "f" * 64,  # not the real sha256
            "X-Payment-Payer": "0x" + "1" * 40,
            "X-Payment-Challenge-Nonce": nonce,
        },
    )
    assert resp.status_code == 402
    body = resp.json()
    assert body["error"] == "verify_failed"
    assert body["previous_nonce"] == nonce


# ---------- 4. Valid proof => 200 + payment_log row written --------------


def _valid_proof(client: TestClient, path: str) -> tuple[str, str, str]:
    """Run a full 402 -> compute proof -> return (nonce, payer, proof)."""
    challenge = client.get(path).json()
    nonce = challenge["challenge_nonce"]
    payer = "0x" + "1" * 40
    quote = client.get(
        "/v1/x402/payment/quote",
        params={
            "endpoint_path": path,
            "payer_address": payer,
            "challenge_nonce": nonce,
        },
    ).json()
    return nonce, payer, quote["expected_proof"]


def test_valid_proof_returns_200(client: TestClient, seeded_db: pathlib.Path) -> None:
    nonce, payer, proof = _valid_proof(client, "/v1/search")
    resp = client.get(
        "/v1/search",
        headers={
            "X-Payment-Proof": proof,
            "X-Payment-Payer": payer,
            "X-Payment-Challenge-Nonce": nonce,
            "X-Payment-Txn-Hash": "0x" + "a" * 64,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ok": True, "path": "/v1/search"}

    # Audit row written.
    conn = sqlite3.connect(str(seeded_db))
    try:
        rows = conn.execute(
            "SELECT endpoint_path, amount_usdc, payer_address, txn_hash "
            "FROM am_x402_payment_log"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0] == ("/v1/search", pytest.approx(0.001), payer, "0x" + "a" * 64)


def test_valid_proof_works_for_all_5_endpoints(
    client: TestClient,
    seeded_db: pathlib.Path,
) -> None:
    """All 5 canonical x402-gated paths accept a valid proof."""
    for i, path in enumerate(GATED_ENDPOINTS):
        nonce, payer, proof = _valid_proof(client, path)
        resp = client.get(
            path,
            headers={
                "X-Payment-Proof": proof,
                "X-Payment-Payer": payer,
                "X-Payment-Challenge-Nonce": nonce,
                # Distinct txn hashes so they don't collide on UNIQUE.
                "X-Payment-Txn-Hash": "0x" + f"{i:064x}",
            },
        )
        assert resp.status_code == 200, f"{path} should accept valid proof"

    # Five distinct audit rows.
    conn = sqlite3.connect(str(seeded_db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_x402_payment_log").fetchone()[0]
    finally:
        conn.close()
    assert n == 5


# ---------- 5. Replay same valid proof => idempotent ----------------------


def test_replay_same_txn_hash_is_idempotent(
    client: TestClient,
    seeded_db: pathlib.Path,
) -> None:
    nonce, payer, proof = _valid_proof(client, "/v1/semantic_search")
    headers = {
        "X-Payment-Proof": proof,
        "X-Payment-Payer": payer,
        "X-Payment-Challenge-Nonce": nonce,
        "X-Payment-Txn-Hash": "0x" + "b" * 64,
    }
    r1 = client.get("/v1/semantic_search", headers=headers)
    r2 = client.get("/v1/semantic_search", headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200

    conn = sqlite3.connect(str(seeded_db))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM am_x402_payment_log WHERE txn_hash = ?",
            ("0x" + "b" * 64,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 1, "UNIQUE(txn_hash) must prevent duplicate audit rows"


# ---------- 6. Non-gated path => pass-through ----------------------------


def test_non_gated_path_passes_through(client: TestClient) -> None:
    """A path not registered in am_x402_endpoint_config must NOT 402."""
    resp = client.get("/v1/openapi.json")
    assert resp.status_code == 200
    assert resp.json() == {"openapi": "3.1.0"}


def test_diagnostic_preview_returns_challenge(client: TestClient) -> None:
    resp = client.get(
        "/v1/x402/payment/preview",
        params={"endpoint_path": "/v1/cases"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["endpoint_path"] == "/v1/cases"
    assert body["required_amount_usdc"] == pytest.approx(0.001)


def test_diagnostic_preview_404_for_unregistered(client: TestClient) -> None:
    resp = client.get(
        "/v1/x402/payment/preview",
        params={"endpoint_path": "/v1/never-gated"},
    )
    assert resp.status_code == 404


def test_recent_log_endpoint_returns_settled(
    client: TestClient,
    seeded_db: pathlib.Path,
) -> None:
    nonce, payer, proof = _valid_proof(client, "/v1/programs")
    client.get(
        "/v1/programs",
        headers={
            "X-Payment-Proof": proof,
            "X-Payment-Payer": payer,
            "X-Payment-Challenge-Nonce": nonce,
            "X-Payment-Txn-Hash": "0x" + "c" * 64,
        },
    )
    resp = client.get("/v1/x402/payment/log/recent", params={"limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1
    assert any(p["txn_hash"] == "0x" + "c" * 64 for p in body["payments"])


# ---------- 7. Middleware ordering invariant -----------------------------


def test_middleware_added_after_idempotency_in_main() -> None:
    """In `main.py`, X402PaymentMiddleware must sit AFTER
    IdempotencyMiddleware (i.e. LATER `app.add_middleware(...)` call) so
    Starlette's LIFO chain runs it BEFORE the idempotency cache stores a
    402 challenge against an Idempotency-Key.
    """
    src = MAIN_SRC.read_text(encoding="utf-8")
    idem_idx = src.find("app.add_middleware(IdempotencyMiddleware)")
    x402_idx = src.find("app.add_middleware(X402PaymentMiddleware)")
    rate_idx = src.find("app.add_middleware(RateLimitMiddleware)")
    assert idem_idx > 0
    assert x402_idx > idem_idx, "X402 middleware must be added AFTER Idempotency"
    assert x402_idx < rate_idx, "X402 middleware must be added BEFORE RateLimit"


def test_router_included_in_main() -> None:
    src = MAIN_SRC.read_text(encoding="utf-8")
    assert "x402_payment_router" in src
    assert "app.include_router(x402_payment_router)" in src


# ---------- 8. LLM-0 verify ----------------------------------------------


_FORBIDDEN_LLM_TOKENS = ("anthropic", "openai", "google.generativeai")


def test_no_llm_import_in_x402_payment() -> None:
    """Billing / payment path stays LLM-free per feedback_no_operator_llm_api."""
    src = X402_SRC.read_text(encoding="utf-8")
    for bad in _FORBIDDEN_LLM_TOKENS:
        assert f"import {bad}" not in src
        assert f"from {bad}" not in src


def test_no_llm_import_in_test_file() -> None:
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    for bad in _FORBIDDEN_LLM_TOKENS:
        assert f"import {bad}" not in src
        assert f"from {bad}" not in src


# ---------- 9. Brand discipline ------------------------------------------


def test_no_legacy_brand_in_x402_payment() -> None:
    """No 税務会計AI / zeimu-kaikei.ai legacy brand in the new file."""
    src = X402_SRC.read_text(encoding="utf-8")
    for bad in ("税務会計AI", "zeimu-kaikei.ai"):
        assert bad not in src, f"legacy brand `{bad}` found in x402_payment.py"


# ---------- 10. Proof-verify primitive sanity -----------------------------


def test_expected_proof_is_deterministic() -> None:
    a = x402_payment._expected_proof("nonce-abc-1234", "/v1/search", "0x" + "1" * 40, 0.001)
    b = x402_payment._expected_proof("nonce-abc-1234", "/v1/search", "0x" + "1" * 40, 0.001)
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_expected_proof_differs_for_different_payer() -> None:
    a = x402_payment._expected_proof("nonce-abc-1234", "/v1/search", "0x" + "1" * 40, 0.001)
    b = x402_payment._expected_proof("nonce-abc-1234", "/v1/search", "0x" + "2" * 40, 0.001)
    assert a != b


def test_fresh_challenge_nonce_is_unique() -> None:
    seen = {x402_payment._fresh_challenge_nonce() for _ in range(50)}
    assert len(seen) == 50  # vanishingly small collision probability
