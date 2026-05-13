"""x402 full payment chain integration tests.

Exercises the end-to-end ``HTTP 402 -> proof verify -> 200`` flow that
``src/jpintel_mcp/api/x402_payment.py`` wires onto the canonical
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
+ middleware + dummy paid-route handlers. We do NOT spin up the full
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

GATED_ENDPOINTS = tuple(
    str(endpoint["endpoint_path"]) for endpoint in x402_payment.X402_CANONICAL_ENDPOINT_SEEDS
)
PRIMARY_GATED_PATH = "/v1/programs/prescreen"


# ---------- shared fixtures ----------------------------------------------


@pytest.fixture()
def seeded_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Fresh autonomath.db with migration 282 applied and canonical endpoints seeded."""
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
    monkeypatch.setenv("JPCITE_X402_MOCK_PROOF_ENABLED", "1")
    monkeypatch.delenv("JPCITE_X402_SCHEMA_FAIL_OPEN_DEV", raising=False)
    monkeypatch.delenv("JPCITE_X402_DIAGNOSTIC_SECRET", raising=False)
    return db_path


@pytest.fixture()
def app(seeded_db: pathlib.Path) -> FastAPI:
    """Minimal app: middleware + diagnostic router + dummy gated handlers."""
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
    resp = client.get(PRIMARY_GATED_PATH)
    assert resp.status_code == 402
    body = resp.json()
    assert body["error"] == "payment_required"
    assert body["endpoint_path"] == PRIMARY_GATED_PATH
    assert body["required_amount_usdc"] == pytest.approx(0.001)
    assert body["settle_currency"] == "USDC"
    assert body["settle_chain"] == "base"
    assert len(body["challenge_nonce"]) >= 8
    assert body["proof_header"] == "X-Payment-Proof"
    assert "X-Payment-Required" in resp.headers
    assert resp.headers["X-Payment-Challenge-Nonce"] == body["challenge_nonce"]


def test_authenticated_request_bypasses_x402_challenge(client: TestClient) -> None:
    resp = client.get(PRIMARY_GATED_PATH, headers={"Authorization": "Bearer jc_paid_test"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Payment-Required") is None
    assert resp.json()["ok"] is True


@pytest.mark.parametrize(
    "path",
    (
        "/v1/programs/prescreen",
        "/v1/audit/workpaper",
        "/v1/search/semantic",
    ),
)
@pytest.mark.parametrize(
    "headers",
    (
        {"Authorization": "Basic junk"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer   "},
    ),
)
def test_malformed_authorization_does_not_bypass_x402_challenge(
    client: TestClient,
    path: str,
    headers: dict[str, str],
) -> None:
    resp = client.get(path, headers=headers)
    assert resp.status_code == 402
    assert resp.headers["X-Payment-Required"] == "true"
    assert resp.json()["error"] == "payment_required"


def test_x_api_key_shape_bypasses_x402_challenge(client: TestClient) -> None:
    resp = client.get(PRIMARY_GATED_PATH, headers={"X-API-Key": "jc_paid_test"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Payment-Required") is None
    assert resp.json()["ok"] is True


# ---------- 2. Header without payer => 401 -------------------------------


def test_header_without_payer_returns_401(client: TestClient) -> None:
    resp = client.get(
        "/v1/programs/prescreen",
        headers={"X-Payment-Proof": "some-proof-string"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "missing_payer_or_nonce"


def test_header_with_payer_but_no_nonce_returns_401(client: TestClient) -> None:
    resp = client.get(
        "/v1/case-studies/search",
        headers={
            "X-Payment-Proof": "some-proof-string",
            "X-Payment-Payer": "0x" + "a" * 40,
        },
    )
    assert resp.status_code == 401


# ---------- 3. Bad proof => 402 verify_failed (NOT 401) -------------------


def test_wrong_proof_returns_402_verify_failed(client: TestClient) -> None:
    # First, harvest a valid challenge nonce.
    challenge_resp = client.get("/v1/audit/workpaper")
    nonce = challenge_resp.json()["challenge_nonce"]
    # Replay with a tampered proof.
    resp = client.get(
        "/v1/audit/workpaper",
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


def test_mock_proof_rejected_without_explicit_dev_flag(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Origin must not accept a self-computed mock proof unless explicitly enabled."""

    challenge = client.get(PRIMARY_GATED_PATH).json()
    nonce = challenge["challenge_nonce"]
    payer = "0x" + "1" * 40
    proof = x402_payment._expected_proof(nonce, PRIMARY_GATED_PATH, payer, 0.001)
    monkeypatch.delenv("JPCITE_X402_MOCK_PROOF_ENABLED", raising=False)

    resp = client.get(
        PRIMARY_GATED_PATH,
        headers={
            "X-Payment-Proof": proof,
            "X-Payment-Payer": payer,
            "X-Payment-Challenge-Nonce": nonce,
            "X-Payment-Txn-Hash": "0x" + "d" * 64,
        },
    )

    assert resp.status_code == 402
    assert resp.json()["error"] == "edge_verification_required"


def test_mock_proof_flag_is_ignored_in_prod(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production origin must never accept self-computed mock proofs."""

    monkeypatch.setenv("JPCITE_ENV", "prod")
    monkeypatch.setenv("JPCITE_X402_MOCK_PROOF_ENABLED", "1")
    challenge = client.get(PRIMARY_GATED_PATH).json()
    nonce = challenge["challenge_nonce"]
    payer = "0x" + "1" * 40
    proof = x402_payment._expected_proof(nonce, PRIMARY_GATED_PATH, payer, 0.001)

    resp = client.get(
        PRIMARY_GATED_PATH,
        headers={
            "X-Payment-Proof": proof,
            "X-Payment-Payer": payer,
            "X-Payment-Challenge-Nonce": nonce,
            "X-Payment-Txn-Hash": "0x" + "e" * 64,
        },
    )

    assert resp.status_code == 402
    assert resp.json()["error"] == "edge_verification_required"


# ---------- 4. Valid proof => 200 + payment_log row written --------------


def _valid_proof(client: TestClient, path: str) -> tuple[str, str, str]:
    """Run a full 402 -> compute proof -> return (nonce, payer, proof)."""
    challenge = client.get(path).json()
    nonce = challenge["challenge_nonce"]
    payer = "0x" + "1" * 40
    proof = x402_payment._expected_proof(nonce, path, payer, 0.001)
    return nonce, payer, proof


def test_valid_proof_returns_200(client: TestClient, seeded_db: pathlib.Path) -> None:
    nonce, payer, proof = _valid_proof(client, PRIMARY_GATED_PATH)
    resp = client.get(
        PRIMARY_GATED_PATH,
        headers={
            "X-Payment-Proof": proof,
            "X-Payment-Payer": payer,
            "X-Payment-Challenge-Nonce": nonce,
            "X-Payment-Txn-Hash": "0x" + "a" * 64,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ok": True, "path": PRIMARY_GATED_PATH}

    # Audit row written.
    conn = sqlite3.connect(str(seeded_db))
    try:
        rows = conn.execute(
            "SELECT endpoint_path, amount_usdc, payer_address, txn_hash FROM am_x402_payment_log"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0] == (PRIMARY_GATED_PATH, pytest.approx(0.001), payer, "0x" + "a" * 64)


def test_valid_proof_works_for_all_canonical_endpoints(
    client: TestClient,
    seeded_db: pathlib.Path,
) -> None:
    """All canonical x402-gated paths accept a valid proof."""
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

    # One distinct audit row per canonical endpoint.
    conn = sqlite3.connect(str(seeded_db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_x402_payment_log").fetchone()[0]
    finally:
        conn.close()
    assert n == len(GATED_ENDPOINTS)


# ---------- 5. Replay same valid proof => idempotent ----------------------


def test_replay_same_txn_hash_is_idempotent(
    client: TestClient,
    seeded_db: pathlib.Path,
) -> None:
    nonce, payer, proof = _valid_proof(client, "/v1/search/semantic")
    headers = {
        "X-Payment-Proof": proof,
        "X-Payment-Payer": payer,
        "X-Payment-Challenge-Nonce": nonce,
        "X-Payment-Txn-Hash": "0x" + "b" * 64,
    }
    r1 = client.get("/v1/search/semantic", headers=headers)
    r2 = client.get("/v1/search/semantic", headers=headers)
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


def test_programs_search_stale_x402_row_still_passes_through(
    seeded_db: pathlib.Path,
) -> None:
    """Retired search rows in old DBs must not re-gate anonymous discovery."""
    conn = sqlite3.connect(str(seeded_db))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO am_x402_endpoint_config "
            "(endpoint_path, required_amount_usdc, enabled) VALUES (?, ?, 1)",
            ("/v1/programs/search", 0.001),
        )
        conn.commit()
    finally:
        conn.close()

    application = FastAPI()
    application.add_middleware(x402_payment.X402PaymentMiddleware)

    @application.get("/v1/programs/search")
    async def _search() -> dict[str, Any]:
        return {"ok": True}

    resp = TestClient(application).get("/v1/programs/search")
    assert resp.status_code == 200
    assert resp.headers.get("X-Payment-Required") is None
    assert resp.json() == {"ok": True}


def test_diagnostic_preview_returns_challenge(client: TestClient) -> None:
    resp = client.get(
        "/v1/x402/payment/preview",
        params={"endpoint_path": "/v1/case-studies/search"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["endpoint_path"] == "/v1/case-studies/search"
    assert body["required_amount_usdc"] == pytest.approx(0.001)


def test_diagnostic_preview_404_for_unregistered(client: TestClient) -> None:
    resp = client.get(
        "/v1/x402/payment/preview",
        params={"endpoint_path": "/v1/never-gated"},
    )
    assert resp.status_code == 404


def test_x402_diagnostic_routes_are_not_public_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/v1/x402/payment/preview" not in schema["paths"]
    assert "/v1/x402/payment/quote" not in schema["paths"]
    assert "/v1/x402/payment/log/recent" not in schema["paths"]


def test_quote_endpoint_is_not_public(client: TestClient) -> None:
    resp = client.get(
        "/v1/x402/payment/quote",
        params={
            "endpoint_path": PRIMARY_GATED_PATH,
            "payer_address": "0x" + "1" * 40,
            "challenge_nonce": "nonce-abc-1234",
        },
    )
    assert resp.status_code in {403, 404}
    assert "expected_proof" not in resp.text


def test_recent_log_endpoint_returns_settled_when_authenticated(
    client: TestClient,
    seeded_db: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JPCITE_X402_DIAGNOSTIC_SECRET", "diag-secret")
    nonce, payer, proof = _valid_proof(client, "/v1/programs/prescreen")
    client.get(
        "/v1/programs/prescreen",
        headers={
            "X-Payment-Proof": proof,
            "X-Payment-Payer": payer,
            "X-Payment-Challenge-Nonce": nonce,
            "X-Payment-Txn-Hash": "0x" + "c" * 64,
        },
    )
    public_resp = client.get("/v1/x402/payment/log/recent", params={"limit": 5})
    assert public_resp.status_code == 403

    resp = client.get(
        "/v1/x402/payment/log/recent",
        params={"limit": 5},
        headers={"X-JPCITE-X402-Diagnostic-Secret": "diag-secret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1
    assert any(p["txn_hash"] == "0x" + "c" * 64 for p in body["payments"])


def test_missing_x402_schema_does_not_500_unrelated_route(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "autonomath_without_x402.db"
    sqlite3.connect(str(db_path)).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))

    application = FastAPI()
    application.add_middleware(x402_payment.X402PaymentMiddleware)

    @application.get("/v1/openapi.json")
    async def _openapi() -> dict[str, Any]:
        return {"openapi": "3.1.0"}

    resp = TestClient(application).get("/v1/openapi.json")
    assert resp.status_code == 200
    assert resp.json() == {"openapi": "3.1.0"}


def test_missing_x402_schema_fails_closed_for_paid_endpoint_in_prod(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "autonomath_without_x402.db"
    sqlite3.connect(str(db_path)).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_ENV", "prod")
    monkeypatch.delenv("JPCITE_X402_SCHEMA_FAIL_OPEN_DEV", raising=False)

    application = FastAPI()
    application.add_middleware(x402_payment.X402PaymentMiddleware)
    called = {"handler": False}

    @application.get(PRIMARY_GATED_PATH)
    async def _prescreen() -> dict[str, Any]:
        called["handler"] = True
        return {"ok": True}

    resp = TestClient(application).get(PRIMARY_GATED_PATH)
    assert resp.status_code == 503
    assert resp.json()["error"] == "x402_config_unavailable"
    assert resp.headers["X-Payment-Required"] == "true"
    assert called["handler"] is False


def test_missing_x402_config_row_fails_closed_for_paid_endpoint_in_prod(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "autonomath_empty_x402_config.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(MIG_282.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_ENV", "prod")
    monkeypatch.delenv("JPCITE_X402_SCHEMA_FAIL_OPEN_DEV", raising=False)

    application = FastAPI()
    application.add_middleware(x402_payment.X402PaymentMiddleware)

    @application.get(PRIMARY_GATED_PATH)
    async def _prescreen() -> dict[str, Any]:
        return {"ok": True}

    resp = TestClient(application).get(PRIMARY_GATED_PATH)
    assert resp.status_code == 503
    assert resp.json()["error"] == "x402_config_unavailable"


def test_missing_x402_schema_dev_fail_open_requires_explicit_flag(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "autonomath_without_x402.db"
    sqlite3.connect(str(db_path)).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_ENV", "test")
    monkeypatch.setenv("JPCITE_X402_SCHEMA_FAIL_OPEN_DEV", "1")

    application = FastAPI()
    application.add_middleware(x402_payment.X402PaymentMiddleware)

    @application.get(PRIMARY_GATED_PATH)
    async def _prescreen() -> dict[str, Any]:
        return {"ok": True}

    resp = TestClient(application).get(PRIMARY_GATED_PATH)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_missing_x402_schema_fail_open_flag_ignored_in_prod(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "autonomath_without_x402.db"
    sqlite3.connect(str(db_path)).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_ENV", "prod")
    monkeypatch.setenv("JPCITE_X402_SCHEMA_FAIL_OPEN_DEV", "1")

    application = FastAPI()
    application.add_middleware(x402_payment.X402PaymentMiddleware)

    @application.get(PRIMARY_GATED_PATH)
    async def _prescreen() -> dict[str, Any]:
        return {"ok": True}

    resp = TestClient(application).get(PRIMARY_GATED_PATH)
    assert resp.status_code == 503
    assert resp.json()["error"] == "x402_config_unavailable"


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


def test_x402_endpoint_seed_is_single_source() -> None:
    from scripts.etl import seed_x402_endpoints

    assert seed_x402_endpoints._ENDPOINTS == x402_payment.X402_CANONICAL_ENDPOINT_SEEDS
    assert "X402_CANONICAL_ENDPOINT_SEEDS" in (
        REPO_ROOT / "scripts" / "etl" / "seed_x402_endpoints.py"
    ).read_text(encoding="utf-8")
    assert (
        tuple(
            str(endpoint["endpoint_path"])
            for endpoint in x402_payment.X402_CANONICAL_ENDPOINT_SEEDS
        )
        == GATED_ENDPOINTS
    )


def test_x402_canonical_paths_match_runtime_route_sources() -> None:
    route_sources = {
        "/v1/audit/workpaper": (
            REPO_ROOT / "src" / "jpintel_mcp" / "api" / "audit_workpaper_v2.py",
            'APIRouter(prefix="/v1/audit"',
            '"/workpaper"',
        ),
        "/v1/case-studies/search": (
            REPO_ROOT / "src" / "jpintel_mcp" / "api" / "case_studies.py",
            'APIRouter(prefix="/v1/case-studies"',
            '"/search"',
        ),
        "/v1/programs/prescreen": (
            REPO_ROOT / "src" / "jpintel_mcp" / "api" / "prescreen.py",
            'APIRouter(prefix="/v1/programs"',
            '"/prescreen"',
        ),
        "/v1/search/semantic": (
            REPO_ROOT / "src" / "jpintel_mcp" / "api" / "semantic_search_v2.py",
            'APIRouter(prefix="/v1"',
            '"/search/semantic"',
        ),
    }
    assert set(GATED_ENDPOINTS) == set(route_sources)
    for path, (source, prefix, suffix) in route_sources.items():
        body = source.read_text(encoding="utf-8")
        assert prefix in body, f"{path} prefix missing from {source.name}"
        assert suffix in body, f"{path} route suffix missing from {source.name}"


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
    a = x402_payment._expected_proof("nonce-abc-1234", PRIMARY_GATED_PATH, "0x" + "1" * 40, 0.001)
    b = x402_payment._expected_proof("nonce-abc-1234", PRIMARY_GATED_PATH, "0x" + "1" * 40, 0.001)
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_expected_proof_differs_for_different_payer() -> None:
    a = x402_payment._expected_proof("nonce-abc-1234", PRIMARY_GATED_PATH, "0x" + "1" * 40, 0.001)
    b = x402_payment._expected_proof("nonce-abc-1234", PRIMARY_GATED_PATH, "0x" + "2" * 40, 0.001)
    assert a != b


def test_fresh_challenge_nonce_is_unique() -> None:
    seen = {x402_payment._fresh_challenge_nonce() for _ in range(50)}
    assert len(seen) == 50  # vanishingly small collision probability
