"""REST router for the Agent Credit Wallet (Wave 48 tick#7, Dim U).

Wires the Wave 47 / PR-storage-layer migration 281 (
``am_credit_wallet`` + ``am_credit_transaction_log`` +
``am_credit_spending_alert`` + ``v_credit_wallet_topup_due``) onto five
operator-internal REST endpoints per
``feedback_agent_credit_wallet_design.md``:

  * GET  ``/v1/wallet/balance``       — current balance + auto-topup config
  * POST ``/v1/wallet/topup``         — set auto-topup threshold + amount (+ optional one-shot)
  * GET  ``/v1/wallet/transactions``  — paginated transaction ledger
  * GET  ``/v1/wallet/alerts``        — 50/80/100 spending-alert ledger
  * POST ``/v1/wallet/charge``        — internal-only charge (metering-side)

LLM-0 / no-money-transfer discipline
------------------------------------
This module performs ZERO Anthropic / OpenAI / etc. SDK call (memory
`feedback_no_operator_llm_api`). It also performs ZERO real money
transfer — Stripe Portal remains the only path that touches Stripe
secrets (memory: do not overwrite existing Stripe Portal). ``/topup``
records the wallet's auto-topup *intent* + an optional in-wallet
``topup`` ledger row that the cron picks up; it does NOT call Stripe.
``/charge`` is restricted to internal callers via an
``X-Internal-Token`` header check matching
``settings.metering_internal_token``; without it, the endpoint returns
403 to prevent end-agents from minting negative balance.

Auth contract
-------------
Every endpoint requires the standard ``X-API-Key`` header (resolved
through :func:`jpintel_mcp.api.deps.require_key` → ``ApiContextDep``).
``ctx.key_hash`` is a 64-char HMAC-SHA256 hex digest (see
:func:`jpintel_mcp.api.deps.hash_api_key`); this satisfies migration
281's ``CHECK (length(owner_token_hash) = 64)`` and is used directly
as ``owner_token_hash``. Anonymous callers (``ctx.key_hash is None``)
get 401.

Database
--------
Wallet data lives in ``autonomath.db`` (the operator-internal mirror)
to match the migration's ``-- target_db: autonomath`` header. We use a
short-lived read-write connection per request (5s timeout, WAL-friendly
journal mode honored by SQLite defaults). The shared ``DbDep`` resolves
``jpcite.db`` and is used only for ``log_usage`` (usage_events table).

Spending alerts
---------------
``GET /alerts`` returns historical alert firings. ``POST /charge``
piggybacks on the ETL alert processor in
``scripts/etl/process_credit_wallet_alerts.py`` for inline alert
detection: when a charge crosses the 50% / 80% / 100% monthly_budget
threshold for the current ``YYYY-MM`` billing cycle, a row is inserted
into ``am_credit_spending_alert`` via the UNIQUE-protected idempotent
upsert. The cron processor still owns the bulk hourly sweep; this
handler only ensures the alert is visible immediately for the
in-progress charge.

Pricing
-------
All five endpoints are operator-internal accounting plumbing and carry
``_billing_unit: 0`` — they do NOT bill the caller. The actual ``¥3/req``
deduction comes from upstream metering that calls ``/charge``.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.credit_wallet")

router = APIRouter(prefix="/v1/wallet", tags=["wallet", "credit"])


_WALLET_DISCLAIMER = (
    "本エンドポイントは jpcite operator-internal の prepaid credit wallet 状態 "
    "(残高 / auto-topup config / 取引ログ / spending alert) を返却します。"
    "実際の Stripe 決済は /v1/billing/portal 経由のみ — このルーターは "
    "金銭授受を行いません (LLM-0 + Stripe-bypass discipline)。"
)


# ---------------------------------------------------------------------------
# DB helpers — autonomath.db read-write (short-lived, per-request)
# ---------------------------------------------------------------------------


def _autonomath_db_path() -> str:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return raw
    return str(Path(__file__).resolve().parents[3] / "autonomath.db")


def _open_am_rw() -> sqlite3.Connection:
    """Open autonomath.db in read-write mode (short-lived)."""
    path = _autonomath_db_path()
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _require_wallet_schema(conn: sqlite3.Connection) -> None:
    """503 if migration 281 hasn't been applied."""
    if not _table_exists(conn, "am_credit_wallet"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "credit_wallet schema not provisioned — migration 281 "
                "(am_credit_wallet) is missing from autonomath.db. Run "
                "`sqlite3 autonomath.db < scripts/migrations/281_credit_wallet.sql`."
            ),
        )


def _get_or_create_wallet(
    conn: sqlite3.Connection, owner_token_hash: str
) -> sqlite3.Row:
    """Return the wallet row for the caller, creating one (balance=0) on miss."""
    row = conn.execute(
        "SELECT wallet_id, owner_token_hash, balance_yen, auto_topup_threshold, "
        "       auto_topup_amount, monthly_budget_yen, enabled, created_at, updated_at "
        "FROM am_credit_wallet WHERE owner_token_hash = ? LIMIT 1",
        (owner_token_hash,),
    ).fetchone()
    if row is not None:
        return row
    conn.execute(
        "INSERT INTO am_credit_wallet (owner_token_hash) VALUES (?)",
        (owner_token_hash,),
    )
    conn.commit()
    row = conn.execute(
        "SELECT wallet_id, owner_token_hash, balance_yen, auto_topup_threshold, "
        "       auto_topup_amount, monthly_budget_yen, enabled, created_at, updated_at "
        "FROM am_credit_wallet WHERE owner_token_hash = ? LIMIT 1",
        (owner_token_hash,),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to create wallet row",
        )
    return row


def _require_owner_token_hash(ctx: Any) -> str:
    """Reject anonymous callers; return the 64-char HMAC-SHA256 token hash."""
    key_hash = getattr(ctx, "key_hash", None)
    if not key_hash or len(key_hash) != 64:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "credit_wallet endpoints require X-API-Key (anonymous callers "
                "have no wallet). Provision a key via /v1/billing/checkout."
            ),
        )
    return key_hash


def _current_billing_cycle() -> str:
    """YYYY-MM bucket (UTC)."""
    return datetime.now(UTC).strftime("%Y-%m")


def _cycle_spent_yen(conn: sqlite3.Connection, wallet_id: int, cycle: str) -> int:
    """Sum |charge_amount| for the current billing cycle."""
    row = conn.execute(
        "SELECT COALESCE(SUM(-amount_yen), 0) AS spent FROM am_credit_transaction_log "
        "WHERE wallet_id = ? AND txn_type = 'charge' AND substr(occurred_at, 1, 7) = ?",
        (wallet_id, cycle),
    ).fetchone()
    return int(row["spent"]) if row else 0


def _maybe_fire_alerts(
    conn: sqlite3.Connection,
    wallet_id: int,
    monthly_budget_yen: int,
    cycle: str,
) -> list[int]:
    """Insert any 50/80/100 alert rows that just became due. Idempotent.

    Returns list of threshold_pct that fired in this invocation.
    """
    fired: list[int] = []
    if monthly_budget_yen <= 0:
        return fired
    spent = _cycle_spent_yen(conn, wallet_id, cycle)
    for threshold_pct in (50, 80, 100):
        threshold_yen = (monthly_budget_yen * threshold_pct) // 100
        if spent < threshold_yen:
            continue
        try:
            conn.execute(
                "INSERT INTO am_credit_spending_alert "
                "(wallet_id, threshold_pct, billing_cycle, spent_yen, budget_yen) "
                "VALUES (?, ?, ?, ?, ?)",
                (wallet_id, threshold_pct, cycle, spent, monthly_budget_yen),
            )
            fired.append(threshold_pct)
        except sqlite3.IntegrityError:
            # UNIQUE(wallet_id, threshold_pct, billing_cycle) — already fired this cycle
            continue
    if fired:
        conn.commit()
    return fired


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class TopupRequest(BaseModel):
    """Auto-topup configuration + optional immediate top-up.

    All amounts are in JPY (integer). ``immediate_amount > 0`` records a
    ``topup`` ledger row immediately (i.e. simulating a cron-side
    auto-topup credit); operator scripts call this after the actual
    Stripe payment has cleared. This handler does NOT touch Stripe.
    """

    auto_topup_threshold: int = Field(
        0, ge=0, le=10_000_000, description="Threshold (¥) below which auto-topup fires."
    )
    auto_topup_amount: int = Field(
        0, ge=0, le=10_000_000, description="Amount (¥) to credit on auto-topup."
    )
    monthly_budget_yen: int = Field(
        0,
        ge=0,
        le=100_000_000,
        description="Soft monthly cap (¥); 0 = disabled. Used for 50/80/100 alerts.",
    )
    immediate_amount: int = Field(
        0,
        ge=0,
        le=10_000_000,
        description="Optional one-shot credit (¥) to record now as a topup txn.",
    )
    note: str | None = Field(None, max_length=256, description="Optional ledger note.")


class ChargeRequest(BaseModel):
    """Internal-only charge against the wallet (metering side).

    Inserts a ``charge`` row (amount < 0) and updates balance. Refuses
    to drive balance negative — returns 402 if insufficient.
    """

    amount_yen: int = Field(
        ..., gt=0, le=1_000_000, description="Positive charge amount (¥); signed flip in storage."
    )
    note: str | None = Field(None, max_length=256)


# ---------------------------------------------------------------------------
# GET /v1/wallet/balance
# ---------------------------------------------------------------------------


@router.get(
    "/balance",
    summary="Current wallet balance + auto-topup config",
    description=(
        "Returns the caller's prepaid credit wallet state from "
        "``am_credit_wallet`` (migration 281). Creates a zero-balance "
        "wallet row on first call. ``_billing_unit: 0`` — accounting "
        "metadata, not metered."
    ),
    responses={**COMMON_ERROR_RESPONSES, 200: {"description": "Wallet balance envelope."}},
)
def get_wallet_balance(conn: DbDep, ctx: ApiContextDep) -> JSONResponse:
    t0 = time.perf_counter()
    owner_token_hash = _require_owner_token_hash(ctx)

    am = _open_am_rw()
    try:
        _require_wallet_schema(am)
        row = _get_or_create_wallet(am, owner_token_hash)
        cycle = _current_billing_cycle()
        spent = _cycle_spent_yen(am, int(row["wallet_id"]), cycle)
    finally:
        with suppress(Exception):
            am.close()

    payload = {
        "wallet_id": int(row["wallet_id"]),
        "balance_yen": int(row["balance_yen"]),
        "auto_topup_threshold": int(row["auto_topup_threshold"]),
        "auto_topup_amount": int(row["auto_topup_amount"]),
        "monthly_budget_yen": int(row["monthly_budget_yen"]),
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "current_cycle": cycle,
        "current_cycle_spent_yen": spent,
        "_billing_unit": 0,
        "_disclaimer": _WALLET_DISCLAIMER,
    }

    latency_ms = int((time.perf_counter() - t0) * 1000)
    log_usage(
        conn,
        ctx,
        "wallet_balance",
        latency_ms=latency_ms,
        result_count=1,
        params={},
        strict_metering=False,
    )
    return JSONResponse(content=payload, status_code=200)


# ---------------------------------------------------------------------------
# POST /v1/wallet/topup
# ---------------------------------------------------------------------------


@router.post(
    "/topup",
    summary="Update auto-topup config + optional one-shot credit",
    description=(
        "Updates ``auto_topup_threshold`` + ``auto_topup_amount`` + "
        "``monthly_budget_yen`` on the caller's wallet. If "
        "``immediate_amount > 0`` is supplied, records one ``topup`` "
        "ledger row + updates balance — operator scripts call this "
        "post Stripe-settle. **This handler does NOT call Stripe.**"
    ),
    responses={**COMMON_ERROR_RESPONSES, 200: {"description": "Updated wallet snapshot."}},
)
def update_wallet_topup(
    conn: DbDep, ctx: ApiContextDep, body: TopupRequest
) -> JSONResponse:
    t0 = time.perf_counter()
    owner_token_hash = _require_owner_token_hash(ctx)

    am = _open_am_rw()
    try:
        _require_wallet_schema(am)
        row = _get_or_create_wallet(am, owner_token_hash)
        wallet_id = int(row["wallet_id"])

        am.execute(
            "UPDATE am_credit_wallet SET "
            "  auto_topup_threshold = ?, "
            "  auto_topup_amount = ?, "
            "  monthly_budget_yen = ?, "
            "  updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE wallet_id = ?",
            (
                body.auto_topup_threshold,
                body.auto_topup_amount,
                body.monthly_budget_yen,
                wallet_id,
            ),
        )
        if body.immediate_amount > 0:
            am.execute(
                "INSERT INTO am_credit_transaction_log "
                "(wallet_id, amount_yen, txn_type, note) VALUES (?, ?, 'topup', ?)",
                (wallet_id, int(body.immediate_amount), body.note),
            )
            am.execute(
                "UPDATE am_credit_wallet SET balance_yen = balance_yen + ?, "
                "  updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE wallet_id = ?",
                (int(body.immediate_amount), wallet_id),
            )
        am.commit()

        refreshed = am.execute(
            "SELECT wallet_id, balance_yen, auto_topup_threshold, auto_topup_amount, "
            "       monthly_budget_yen, enabled, updated_at FROM am_credit_wallet "
            "WHERE wallet_id = ?",
            (wallet_id,),
        ).fetchone()
    finally:
        with suppress(Exception):
            am.close()

    payload = {
        "wallet_id": int(refreshed["wallet_id"]),
        "balance_yen": int(refreshed["balance_yen"]),
        "auto_topup_threshold": int(refreshed["auto_topup_threshold"]),
        "auto_topup_amount": int(refreshed["auto_topup_amount"]),
        "monthly_budget_yen": int(refreshed["monthly_budget_yen"]),
        "enabled": bool(refreshed["enabled"]),
        "updated_at": refreshed["updated_at"],
        "topup_recorded_yen": int(body.immediate_amount),
        "_billing_unit": 0,
        "_disclaimer": _WALLET_DISCLAIMER,
    }

    latency_ms = int((time.perf_counter() - t0) * 1000)
    log_usage(
        conn,
        ctx,
        "wallet_topup",
        latency_ms=latency_ms,
        result_count=1,
        params={
            "auto_topup_threshold": body.auto_topup_threshold,
            "auto_topup_amount": body.auto_topup_amount,
            "monthly_budget_yen": body.monthly_budget_yen,
            "immediate_amount": body.immediate_amount,
        },
        strict_metering=False,
    )
    return JSONResponse(content=payload, status_code=200)


# ---------------------------------------------------------------------------
# GET /v1/wallet/transactions
# ---------------------------------------------------------------------------


@router.get(
    "/transactions",
    summary="Paginated transaction ledger (topup/charge/refund)",
    description=(
        "Returns ``am_credit_transaction_log`` rows for the caller's "
        "wallet, newest first. Supports ``txn_type`` filter + "
        "``limit``/``offset`` pagination. ``_billing_unit: 0``."
    ),
    responses={**COMMON_ERROR_RESPONSES, 200: {"description": "Transaction ledger."}},
)
def list_wallet_transactions(
    conn: DbDep,
    ctx: ApiContextDep,
    txn_type: Annotated[
        Literal["topup", "charge", "refund"] | None,
        Query(description="Filter by txn_type."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="Max rows.")] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000, description="Pagination offset.")] = 0,
) -> JSONResponse:
    t0 = time.perf_counter()
    owner_token_hash = _require_owner_token_hash(ctx)

    am = _open_am_rw()
    try:
        _require_wallet_schema(am)
        row = _get_or_create_wallet(am, owner_token_hash)
        wallet_id = int(row["wallet_id"])

        if txn_type:
            cur = am.execute(
                "SELECT txn_id, amount_yen, txn_type, occurred_at, note "
                "FROM am_credit_transaction_log "
                "WHERE wallet_id = ? AND txn_type = ? "
                "ORDER BY occurred_at DESC, txn_id DESC LIMIT ? OFFSET ?",
                (wallet_id, txn_type, int(limit), int(offset)),
            )
        else:
            cur = am.execute(
                "SELECT txn_id, amount_yen, txn_type, occurred_at, note "
                "FROM am_credit_transaction_log "
                "WHERE wallet_id = ? "
                "ORDER BY occurred_at DESC, txn_id DESC LIMIT ? OFFSET ?",
                (wallet_id, int(limit), int(offset)),
            )
        txns = [
            {
                "txn_id": int(r["txn_id"]),
                "amount_yen": int(r["amount_yen"]),
                "txn_type": r["txn_type"],
                "occurred_at": r["occurred_at"],
                "note": r["note"],
            }
            for r in cur.fetchall()
        ]
        total_row = am.execute(
            "SELECT COUNT(*) AS c FROM am_credit_transaction_log WHERE wallet_id = ?"
            + (" AND txn_type = ?" if txn_type else ""),
            ((wallet_id, txn_type) if txn_type else (wallet_id,)),
        ).fetchone()
    finally:
        with suppress(Exception):
            am.close()

    payload = {
        "wallet_id": wallet_id,
        "transactions": txns,
        "returned": len(txns),
        "total": int(total_row["c"]) if total_row else len(txns),
        "limit": limit,
        "offset": offset,
        "txn_type_filter": txn_type,
        "_billing_unit": 0,
        "_disclaimer": _WALLET_DISCLAIMER,
    }

    latency_ms = int((time.perf_counter() - t0) * 1000)
    log_usage(
        conn,
        ctx,
        "wallet_transactions",
        latency_ms=latency_ms,
        result_count=len(txns),
        params={"txn_type": txn_type, "limit": limit, "offset": offset},
        strict_metering=False,
    )
    return JSONResponse(content=payload, status_code=200)


# ---------------------------------------------------------------------------
# GET /v1/wallet/alerts
# ---------------------------------------------------------------------------


@router.get(
    "/alerts",
    summary="Spending alert ledger (50/80/100 pct firings)",
    description=(
        "Returns ``am_credit_spending_alert`` rows for the caller's "
        "wallet, newest first. Supports ``billing_cycle`` filter "
        "(YYYY-MM). ``_billing_unit: 0``."
    ),
    responses={**COMMON_ERROR_RESPONSES, 200: {"description": "Alert ledger."}},
)
def list_wallet_alerts(
    conn: DbDep,
    ctx: ApiContextDep,
    billing_cycle: Annotated[
        str | None,
        Query(
            min_length=7,
            max_length=7,
            pattern=r"^\d{4}-\d{2}$",
            description="Filter by billing cycle (YYYY-MM).",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JSONResponse:
    t0 = time.perf_counter()
    owner_token_hash = _require_owner_token_hash(ctx)

    am = _open_am_rw()
    try:
        _require_wallet_schema(am)
        row = _get_or_create_wallet(am, owner_token_hash)
        wallet_id = int(row["wallet_id"])

        if billing_cycle:
            cur = am.execute(
                "SELECT alert_id, threshold_pct, billing_cycle, fired_at, "
                "       spent_yen, budget_yen FROM am_credit_spending_alert "
                "WHERE wallet_id = ? AND billing_cycle = ? "
                "ORDER BY fired_at DESC, alert_id DESC LIMIT ?",
                (wallet_id, billing_cycle, int(limit)),
            )
        else:
            cur = am.execute(
                "SELECT alert_id, threshold_pct, billing_cycle, fired_at, "
                "       spent_yen, budget_yen FROM am_credit_spending_alert "
                "WHERE wallet_id = ? "
                "ORDER BY fired_at DESC, alert_id DESC LIMIT ?",
                (wallet_id, int(limit)),
            )
        alerts = [
            {
                "alert_id": int(r["alert_id"]),
                "threshold_pct": int(r["threshold_pct"]),
                "billing_cycle": r["billing_cycle"],
                "fired_at": r["fired_at"],
                "spent_yen": int(r["spent_yen"]),
                "budget_yen": int(r["budget_yen"]),
            }
            for r in cur.fetchall()
        ]
    finally:
        with suppress(Exception):
            am.close()

    payload = {
        "wallet_id": wallet_id,
        "alerts": alerts,
        "returned": len(alerts),
        "billing_cycle_filter": billing_cycle,
        "thresholds_enum": [50, 80, 100],
        "_billing_unit": 0,
        "_disclaimer": _WALLET_DISCLAIMER,
    }

    latency_ms = int((time.perf_counter() - t0) * 1000)
    log_usage(
        conn,
        ctx,
        "wallet_alerts",
        latency_ms=latency_ms,
        result_count=len(alerts),
        params={"billing_cycle": billing_cycle, "limit": limit},
        strict_metering=False,
    )
    return JSONResponse(content=payload, status_code=200)


# ---------------------------------------------------------------------------
# POST /v1/wallet/charge (internal)
# ---------------------------------------------------------------------------


def _check_internal_token(x_internal_token: str | None) -> None:
    """Reject /charge without the operator-internal metering token."""
    expected = os.environ.get("METERING_INTERNAL_TOKEN")
    if not expected:
        # Defensive — if the token isn't configured, /charge is permanently locked.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "METERING_INTERNAL_TOKEN env-var not configured; "
                "/v1/wallet/charge refuses to mint debits without operator auth."
            ),
        )
    if not x_internal_token or x_internal_token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "X-Internal-Token header missing or invalid. /v1/wallet/charge "
                "is restricted to the operator metering pipeline."
            ),
        )


@router.post(
    "/charge",
    summary="Record a wallet charge (internal metering only)",
    description=(
        "Deducts ``amount_yen`` from the wallet balance and records a "
        "``charge`` ledger row (amount stored negative). Fires any "
        "newly-crossed 50/80/100 alerts inline. Requires "
        "``X-Internal-Token`` header matching "
        "``METERING_INTERNAL_TOKEN``. Returns 402 if balance "
        "insufficient."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {"description": "Charge recorded."},
        402: {"description": "Wallet balance insufficient."},
        403: {"description": "X-Internal-Token missing or invalid."},
    },
)
def post_wallet_charge(
    conn: DbDep,
    ctx: ApiContextDep,
    body: ChargeRequest,
    x_internal_token: Annotated[
        str | None,
        Header(alias="X-Internal-Token", description="Operator metering token."),
    ] = None,
) -> JSONResponse:
    t0 = time.perf_counter()
    _check_internal_token(x_internal_token)
    owner_token_hash = _require_owner_token_hash(ctx)

    am = _open_am_rw()
    try:
        _require_wallet_schema(am)
        row = _get_or_create_wallet(am, owner_token_hash)
        wallet_id = int(row["wallet_id"])
        current_balance = int(row["balance_yen"])
        monthly_budget = int(row["monthly_budget_yen"])
        charge_amount = int(body.amount_yen)

        if current_balance < charge_amount:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"wallet balance insufficient: balance={current_balance}, "
                    f"charge={charge_amount}. Top up via /v1/billing/portal."
                ),
            )

        am.execute(
            "INSERT INTO am_credit_transaction_log "
            "(wallet_id, amount_yen, txn_type, note) VALUES (?, ?, 'charge', ?)",
            (wallet_id, -charge_amount, body.note),
        )
        am.execute(
            "UPDATE am_credit_wallet SET balance_yen = balance_yen - ?, "
            "  updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE wallet_id = ?",
            (charge_amount, wallet_id),
        )
        am.commit()

        cycle = _current_billing_cycle()
        fired = _maybe_fire_alerts(am, wallet_id, monthly_budget, cycle)
        new_balance = current_balance - charge_amount
    finally:
        with suppress(Exception):
            am.close()

    payload = {
        "wallet_id": wallet_id,
        "charge_yen": charge_amount,
        "balance_yen": new_balance,
        "alerts_fired": fired,
        "billing_cycle": _current_billing_cycle(),
        "_billing_unit": 0,
        "_disclaimer": _WALLET_DISCLAIMER,
    }

    latency_ms = int((time.perf_counter() - t0) * 1000)
    log_usage(
        conn,
        ctx,
        "wallet_charge",
        latency_ms=latency_ms,
        result_count=1,
        params={"amount_yen": charge_amount},
        strict_metering=False,
    )
    return JSONResponse(content=payload, status_code=200)


__all__ = ["router"]
