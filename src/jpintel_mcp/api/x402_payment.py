"""Wave 48 — x402 payment chain middleware.

Closes the gap between Wave 47 Dim V x402 *storage* (migration 282
`am_x402_endpoint_config` + `am_x402_payment_log`) and a working in-process
**HTTP 402 -> verified settlement -> 200** chain. The canonical settlement
path remains on-chain (USDC on Base, verified by `functions/x402_handler.ts`
at the CF Pages edge). A deterministic mock verifier is available only when
explicitly enabled for tests/dev with ``JPCITE_X402_MOCK_PROOF_ENABLED=1`` so
the production origin cannot be satisfied by a self-computed proof.

  * tests can exercise the full 402 -> 200 flow without an RPC dependency,
  * dev / staging can demo `curl -H "X-Payment-Proof: ..."` against the
    origin without funding a Base wallet,
  * the middleware contract (header name, status codes, error envelope,
    payment-log write semantics) is locked before edge wiring lands.

Contract
--------
For every endpoint registered in ``am_x402_endpoint_config`` (canonical
seeds include ``/v1/case-studies/search``, ``/v1/programs/prescreen``,
``/v1/audit/workpaper``, and ``/v1/search/semantic``):

  Request                                              | Response
  -----------------------------------------------------+------------------
  GET <path>          (no header)                      | 402 + challenge
  GET <path>  X-Payment-Proof: <bad>                   | 402 + verify_failed
  GET <path>  X-Payment-Proof: <wellformed-but-empty>  | 401 missing_payer
  GET <path>  X-Payment-Proof: <valid mock proof>      | 200 + payment_id
                                                      | only when mock flag is on

A "mock proof" is a JSON-then-sha256-tagged string of shape::

    sha256(<challenge_nonce>|<endpoint_path>|<payer_address>|<amount_usdc>)

The middleware:

  1. Looks up the endpoint in ``am_x402_endpoint_config``. If the x402
     schema is unavailable for a canonical paid path, fail closed with 503
     unless the explicit dev/test schema fail-open flag is enabled.
  2. If no ``X-Payment-Proof`` header => issue 402 with a fresh
     ``challenge_nonce`` (returned in body + ``X-Payment-Required`` header).
  3. If the header is present, parse the structured proof. On parse error
     or sha256 mismatch => 402 with ``verify_failed``.
  4. On verify success => append-only insert into ``am_x402_payment_log``
     (UNIQUE on txn_hash makes it idempotent), then pass through.

Brand / discipline
------------------
  * NO LLM SDK import (billing path; ``feedback_no_operator_llm_api``).
  * NO real RPC / Stripe / on-chain call from this module.
  * Brand: jpcite only. No legacy brand markers (see brand audit guard
    in tests/test_x402_payment_chain.py for the canonical disallow list).
  * Reads only the canonical ``am_x402_*`` tables; never writes to
    ``x402_tx_bind`` (owned by ``billing_v2.x402_issue_key``).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from jpintel_mcp.config import settings

if TYPE_CHECKING:
    from starlette.types import ASGIApp

logger = logging.getLogger("jpintel.x402.payment")

router = APIRouter(prefix="/v1/x402", tags=["x402-payment"])

_X402_DIAGNOSTIC_SECRET_ENV = "JPCITE_X402_DIAGNOSTIC_SECRET"
_X402_DIAGNOSTIC_SECRET_HEADER = "X-JPCITE-X402-Diagnostic-Secret"
_X402_MOCK_PROOF_ENV = "JPCITE_X402_MOCK_PROOF_ENABLED"
_X402_SCHEMA_FAIL_OPEN_ENV = "JPCITE_X402_SCHEMA_FAIL_OPEN_DEV"
X402_CANONICAL_ENDPOINT_SEEDS: tuple[dict[str, object], ...] = (
    {
        "endpoint_path": "/v1/audit/workpaper",
        "required_amount_usdc": 0.01,
        "expires_after_seconds": 600,
    },
    {
        "endpoint_path": "/v1/case-studies/search",
        "required_amount_usdc": 0.002,
        "expires_after_seconds": 3600,
    },
    {
        "endpoint_path": "/v1/programs/prescreen",
        "required_amount_usdc": 0.002,
        "expires_after_seconds": 3600,
    },
    {
        "endpoint_path": "/v1/search/semantic",
        "required_amount_usdc": 0.005,
        "expires_after_seconds": 1800,
    },
)
_X402_CANONICAL_PAID_ENDPOINTS = frozenset(
    str(endpoint["endpoint_path"]) for endpoint in X402_CANONICAL_ENDPOINT_SEEDS
)
_ROUTE_OWNED_PAYMENT_GATES = frozenset({"/v1/programs/search"})


def _has_valid_auth_shape(request: Request) -> bool:
    """Return True only for credential shapes that downstream auth accepts."""
    x_api_key = request.headers.get("X-API-Key")
    if x_api_key and x_api_key.strip():
        return True

    authorization = request.headers.get("Authorization")
    if not authorization:
        return False
    parts = authorization.split(None, 1)
    return (
        len(parts) == 2
        and parts[0].lower() == "bearer"
        and bool(parts[1].strip())
    )


class X402ConfigUnavailableError(RuntimeError):
    """Raised when a paid x402 path cannot safely read its registry."""


# ---------- db helpers ----------------------------------------------------


def _autonomath_db_path() -> Path:
    return Path(os.environ.get("AUTONOMATH_DB_PATH", str(settings.autonomath_db_path)))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_autonomath_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


def _missing_x402_schema(exc: sqlite3.OperationalError) -> bool:
    msg = str(exc).lower()
    return (
        "no such table: v_x402_endpoint_enabled" in msg
        or "no such table: am_x402_endpoint_config" in msg
        or "no such table: am_x402_payment_log" in msg
    )


def _require_diagnostic_auth(header_value: str | None) -> None:
    expected = os.environ.get(_X402_DIAGNOSTIC_SECRET_ENV, "").strip()
    if not expected:
        raise HTTPException(status_code=404, detail="x402_diagnostic_disabled")
    if not header_value or not hmac.compare_digest(header_value, expected):
        raise HTTPException(status_code=403, detail="x402_diagnostic_auth_failed")


def _mock_proof_enabled() -> bool:
    """Return true only for explicit test/dev mock-proof mode.

    **Production NEVER accepts mock proofs.** The middleware synthesises a
    deterministic ``txn_hash`` from the proof string when the caller omits
    the header (see middleware §"txn_hash is required" at line ~425); that
    branch only runs when this helper returns True. The contract: this
    helper returns True iff BOTH ``JPCITE_X402_MOCK_PROOF_ENABLED`` is
    truthy AND the runtime env label resolves to one of {dev,test,local,ci}.

    A defence-in-depth boot gate in ``api/main.py:_assert_production_secrets``
    independently asserts ``_mock_proof_enabled() is False`` when
    ``JPINTEL_ENV`` is prod/production, so a drift between ``JPCITE_ENV``
    and ``JPINTEL_ENV`` (or a stray ``JPCITE_X402_MOCK_PROOF_ENABLED=1`` in
    a Fly secret) cannot silently re-activate the mock path in production.
    """

    return _truthy_env(_X402_MOCK_PROOF_ENV) and _runtime_env() in {
        "dev",
        "test",
        "local",
        "ci",
    }


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _runtime_env() -> str:
    return (
        (os.environ.get("JPCITE_ENV") or os.environ.get("JPINTEL_ENV") or settings.env or "dev")
        .strip()
        .lower()
    )


def _schema_fail_open_allowed() -> bool:
    """Return true only for explicit local/test schema bypass."""

    if not _truthy_env(_X402_SCHEMA_FAIL_OPEN_ENV):
        return False
    return _runtime_env() in {"dev", "test", "local", "ci"}


def _is_canonical_paid_endpoint(path: str) -> bool:
    return path in _X402_CANONICAL_PAID_ENDPOINTS


def _route_owns_payment_gate(path: str) -> bool:
    """Return true when the FastAPI route owns finer-grained payment logic.

    ``/v1/programs/search`` intentionally keeps default/minimal anonymous
    discovery open and gates only ``fields=full`` inside the route handler.
    The middleware must ignore stale x402 registry rows for this path so
    route validation, anonymous quota handling, and the ``fields=full``
    upgrade response stay reachable.
    """

    return path in _ROUTE_OWNED_PAYMENT_GATES


def _fail_closed_response(path: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": "x402_config_unavailable",
            "endpoint_path": path,
            "hint": "Payment configuration is unavailable; retry after migration/seed repair.",
        },
        headers={"X-Payment-Required": "true"},
    )


# ---------- public response models ----------------------------------------


class X402Challenge(BaseModel):
    """Body returned on a 402 challenge response."""

    error: str = Field(default="payment_required")
    endpoint_path: str
    required_amount_usdc: float
    settle_chain: str = Field(default="base")
    settle_currency: str = Field(default="USDC")
    challenge_nonce: str
    expires_at_unix: int
    proof_header: str = Field(default="X-Payment-Proof")
    proof_format: str = Field(
        default="sha256(challenge_nonce|endpoint_path|payer_address|amount_usdc)",
    )
    txn_hash_header: str = Field(default="X-Payment-Txn-Hash")
    payer_header: str = Field(default="X-Payment-Payer")


class X402Settled(BaseModel):
    """Body returned on a successful settled call."""

    settled: bool = True
    payment_id: int
    endpoint_path: str
    amount_usdc: float
    payer_address: str
    challenge_nonce: str


# ---------- proof verification --------------------------------------------


def _expected_proof(
    challenge_nonce: str,
    endpoint_path: str,
    payer_address: str,
    amount_usdc: float,
) -> str:
    """Compute the canonical proof string the agent must present."""
    raw = f"{challenge_nonce}|{endpoint_path}|{payer_address}|{amount_usdc:.6f}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fresh_challenge_nonce() -> str:
    # 16 bytes of urlsafe randomness => 22 chars, well above the
    # migration-282 CHECK length floor (8) and ceiling (128).
    return secrets.token_urlsafe(16)


def _load_endpoint_config(path: str) -> dict[str, Any] | None:
    """Return enabled endpoint config row or None if not x402-gated."""
    if _route_owns_payment_gate(path):
        return None

    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT endpoint_path, required_amount_usdc, expires_after_seconds "
                "FROM v_x402_endpoint_enabled WHERE endpoint_path = ?",
                (path,),
            ).fetchone()
    except sqlite3.OperationalError as exc:
        if _missing_x402_schema(exc):
            if _is_canonical_paid_endpoint(path) and not _schema_fail_open_allowed():
                logger.error(
                    "x402 schema absent for paid endpoint; failing closed path=%s",
                    path,
                )
                raise X402ConfigUnavailableError(path) from exc
            logger.warning(
                "x402 schema absent; payment middleware failing open path=%s env=%s",
                path,
                _runtime_env(),
            )
            return None
        raise
    if row:
        return dict(row)
    if _is_canonical_paid_endpoint(path) and not _schema_fail_open_allowed():
        logger.error(
            "x402 endpoint config absent for paid endpoint; failing closed path=%s",
            path,
        )
        raise X402ConfigUnavailableError(path)
    return None


def _record_payment(
    challenge_nonce: str,
    endpoint_path: str,
    amount_usdc: float,
    payer_address: str,
    txn_hash: str,
) -> int:
    """Insert a settled payment row. Idempotent on txn_hash."""
    with _connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO am_x402_payment_log "
                "(http_status_402_id, endpoint_path, amount_usdc, payer_address, txn_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                (challenge_nonce, endpoint_path, amount_usdc, payer_address, txn_hash),
            )
            conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            # txn_hash UNIQUE collision => already settled; surface the
            # original row id (idempotent replay).
            row = conn.execute(
                "SELECT payment_id FROM am_x402_payment_log WHERE txn_hash = ?",
                (txn_hash,),
            ).fetchone()
            if row is None:  # pragma: no cover — defensive
                raise
            return int(row["payment_id"])


# ---------- 402 challenge factory -----------------------------------------


def build_challenge(
    endpoint_path: str,
    cfg: dict[str, Any],
) -> X402Challenge:
    nonce = _fresh_challenge_nonce()
    expires = int(time.time()) + int(cfg["expires_after_seconds"])
    return X402Challenge(
        endpoint_path=endpoint_path,
        required_amount_usdc=float(cfg["required_amount_usdc"]),
        challenge_nonce=nonce,
        expires_at_unix=expires,
    )


# ---------- middleware ----------------------------------------------------


class X402PaymentMiddleware(BaseHTTPMiddleware):
    """Gate registered endpoints behind HTTP 402.

    Wires the canonical paths from ``am_x402_endpoint_config`` to the
    402-or-200 flow. Pass-through for any path not in the registry.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if _has_valid_auth_shape(request):
            return await call_next(request)

        try:
            cfg = _load_endpoint_config(request.url.path)
        except X402ConfigUnavailableError:
            return _fail_closed_response(request.url.path)
        if cfg is None:
            # Not an x402-gated endpoint — pass through.
            return await call_next(request)

        proof = request.headers.get("X-Payment-Proof")
        if not proof:
            # No proof presented => fresh 402 challenge.
            ch = build_challenge(request.url.path, cfg)
            return JSONResponse(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                content=ch.model_dump(),
                headers={
                    "X-Payment-Required": "true",
                    "X-Payment-Challenge-Nonce": ch.challenge_nonce,
                },
            )

        payer = request.headers.get("X-Payment-Payer", "")
        txn_hash = request.headers.get("X-Payment-Txn-Hash", "")
        challenge_nonce = request.headers.get("X-Payment-Challenge-Nonce", "")

        # 401: header present but identity missing — agent must replay
        # with the original payer + nonce. This is a *protocol* error,
        # distinct from a 402 unfunded-challenge.
        if not payer or not challenge_nonce:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error": "missing_payer_or_nonce",
                    "hint": "Resend with X-Payment-Payer and X-Payment-Challenge-Nonce.",
                },
            )

        if not _mock_proof_enabled():
            ch = build_challenge(request.url.path, cfg)
            return JSONResponse(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                content={
                    **ch.model_dump(),
                    "error": "edge_verification_required",
                    "hint": "Use the /x402 edge settlement flow; origin mock proofs are disabled.",
                },
                headers={"X-Payment-Required": "true"},
            )

        # Compute expected proof; on mismatch => 402 verify_failed (NOT 401),
        # because the canonical x402 surface keeps "show me money" responses
        # on 402 even when the prior attempt was malformed.
        expected = _expected_proof(
            challenge_nonce=challenge_nonce,
            endpoint_path=request.url.path,
            payer_address=payer,
            amount_usdc=float(cfg["required_amount_usdc"]),
        )
        if proof != expected:
            ch = build_challenge(request.url.path, cfg)
            return JSONResponse(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                content={
                    **ch.model_dump(),
                    "error": "verify_failed",
                    "previous_nonce": challenge_nonce,
                },
                headers={"X-Payment-Required": "true"},
            )

        # txn_hash is required to insert the audit row; if absent we
        # synthesise a deterministic mock hash from the proof so dev
        # callers can omit it. Production agents MUST send the real one.
        if not txn_hash:
            txn_hash = "0x" + hashlib.sha256(proof.encode()).hexdigest()

        try:
            payment_id = _record_payment(
                challenge_nonce=challenge_nonce,
                endpoint_path=request.url.path,
                amount_usdc=float(cfg["required_amount_usdc"]),
                payer_address=payer,
                txn_hash=txn_hash,
            )
        except sqlite3.IntegrityError as exc:
            logger.warning("x402 payment_log write rejected: %s", exc)
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "audit_write_rejected", "detail": str(exc)},
            )

        # Attach the payment id to the request scope so downstream handlers
        # can include it in the response envelope if they want.
        request.state.x402_payment_id = payment_id
        request.state.x402_amount_usdc = float(cfg["required_amount_usdc"])
        request.state.x402_payer_address = payer

        return await call_next(request)


# ---------- diagnostic router --------------------------------------------


@router.get(
    "/payment/preview",
    summary="Issue a 402 challenge for any registered path",
    include_in_schema=False,
)
async def preview_challenge(endpoint_path: str) -> X402Challenge:
    """Return a 402 challenge body for ``endpoint_path``.

    Lets an agent retrieve the current challenge nonce + price without
    needing to hit the gated endpoint first. Returns 404 if the path is
    not x402-gated.
    """
    try:
        cfg = _load_endpoint_config(endpoint_path)
    except X402ConfigUnavailableError as exc:
        raise HTTPException(status_code=503, detail="x402_config_unavailable") from exc
    if cfg is None:
        raise HTTPException(status_code=404, detail="endpoint_not_x402_gated")
    return build_challenge(endpoint_path, cfg)


@router.get(
    "/payment/quote",
    summary="Compute the expected proof for a candidate payer + nonce",
    include_in_schema=False,
)
async def quote_proof(
    endpoint_path: str,
    payer_address: str,
    challenge_nonce: str,
    x402_diagnostic_secret: str | None = Header(
        default=None,
        alias=_X402_DIAGNOSTIC_SECRET_HEADER,
    ),
) -> dict[str, Any]:
    """Dev helper: return the proof an honest payer would have to present.

    Protected by an operator-only diagnostic secret because the response
    includes the proof value used by the mock verifier.
    """
    _require_diagnostic_auth(x402_diagnostic_secret)

    try:
        cfg = _load_endpoint_config(endpoint_path)
    except X402ConfigUnavailableError as exc:
        raise HTTPException(status_code=503, detail="x402_config_unavailable") from exc
    if cfg is None:
        raise HTTPException(status_code=404, detail="endpoint_not_x402_gated")
    proof = _expected_proof(
        challenge_nonce=challenge_nonce,
        endpoint_path=endpoint_path,
        payer_address=payer_address,
        amount_usdc=float(cfg["required_amount_usdc"]),
    )
    return {
        "endpoint_path": endpoint_path,
        "required_amount_usdc": float(cfg["required_amount_usdc"]),
        "challenge_nonce": challenge_nonce,
        "payer_address": payer_address,
        "expected_proof": proof,
        "proof_header_value": proof,
    }


@router.get(
    "/payment/log/recent",
    summary="Recent settled x402 payments (audit view)",
    include_in_schema=False,
)
async def recent_payments(
    limit: int = 20,
    x402_diagnostic_secret: str | None = Header(
        default=None,
        alias=_X402_DIAGNOSTIC_SECRET_HEADER,
    ),
) -> dict[str, Any]:
    """Return the most recent settled x402 payments for ops visibility."""
    _require_diagnostic_auth(x402_diagnostic_secret)

    if limit <= 0 or limit > 200:
        raise HTTPException(status_code=422, detail="limit_out_of_range")
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT payment_id, http_status_402_id, endpoint_path, "
                "amount_usdc, payer_address, txn_hash, occurred_at "
                "FROM am_x402_payment_log ORDER BY payment_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if _missing_x402_schema(exc):
            raise HTTPException(status_code=404, detail="x402_schema_not_installed") from exc
        raise
    return {
        "count": len(rows),
        "payments": [dict(r) for r in rows],
    }


__all__ = [
    "X402Challenge",
    "X402PaymentMiddleware",
    "X402Settled",
    "build_challenge",
    "router",
]
