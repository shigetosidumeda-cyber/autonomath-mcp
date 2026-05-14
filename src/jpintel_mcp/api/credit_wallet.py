"""REST router for the Agent Credit Wallet (Wave 48 tick#7, Dim U).

Wires the Wave 47 / PR-storage-layer migration 281 (
``am_credit_wallet`` + ``am_credit_transaction_log`` +
``am_credit_spending_alert`` + ``v_credit_wallet_topup_due``) onto five
operator-internal REST endpoints per
``feedback_agent_credit_wallet_design.md``:

  * GET  ``/v1/wallet/balance``       — current balance + auto-topup config
  * POST ``/v1/wallet/topup``         — set auto-topup threshold + amount
  * GET  ``/v1/wallet/transactions``  — paginated transaction ledger
  * GET  ``/v1/wallet/alerts``        — 50/80/100 spending-alert ledger
  * POST ``/v1/wallet/charge``        — internal-only charge (metering-side)

LLM-0 / no-money-transfer discipline
------------------------------------
This module performs ZERO Anthropic / OpenAI / etc. SDK call (memory
`feedback_no_operator_llm_api`). It also performs ZERO real money
transfer — Stripe Portal remains the only path that touches Stripe
secrets (memory: do not overwrite existing Stripe Portal). ``/topup``
records the wallet's auto-topup *intent* for ordinary API-key callers.
Positive immediate credits are accepted only from internal billing/metering
callers after the payment rail has already verified funds. ``/charge`` and
immediate ``/topup`` are restricted via an ``X-Internal-Token`` header check
matching ``METERING_INTERNAL_TOKEN``.

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
journal mode honored by SQLite defaults). The shared ``ApiContextDep``
still resolves ``jpcite.db`` for API-key authentication, but this router
does not write ``usage_events`` rows.

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
``_billing_unit: 0`` — they do NOT bill the caller or emit
``usage_events`` rows. The actual ``¥3/req`` deduction comes from
upstream metering that calls ``/charge``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES
from jpintel_mcp.api.deps import ApiContextDep  # noqa: TC001

logger = logging.getLogger("jpintel.api.credit_wallet")

router = APIRouter(prefix="/v1/wallet", tags=["wallet", "credit"])


_WALLET_DISCLAIMER = (
    "本エンドポイントは jpcite operator-internal の prepaid credit wallet 状態 "
    "(残高 / auto-topup config / 取引ログ / spending alert) を返却します。"
    "実際の Stripe 決済は /v1/billing/portal 経由のみ — このルーターは "
    "金銭授受を行いません (LLM-0 + Stripe-bypass discipline)。"
)

_REQUIRED_WALLET_TABLES = (
    "am_credit_wallet",
    "am_credit_transaction_log",
    "am_credit_spending_alert",
)
_IDEMPOTENCY_MARKER_RE = re.compile(
    r"(?:^|\n)\[wallet-idem:([0-9a-f]{32}):bal=(-?\d+):cycle=(\d{4}-\d{2})\]$"
)
_TOPUP_IDEMPOTENCY_MARKER_RE = re.compile(
    r"(?:^|\n)\[wallet-topup-idem:([0-9a-f]{32}):fp=([0-9a-f]{32}):"
    r"bal=(-?\d+):cycle=(\d{4}-\d{2})\]$"
)
_IDEMPOTENCY_KEY_RE = re.compile(r"^[!-~]{1,255}$")


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
    missing = [name for name in _REQUIRED_WALLET_TABLES if not _table_exists(conn, name)]
    if missing:
        logger.warning("credit_wallet.schema_missing objects=%s", ",".join(missing))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="wallet service unavailable",
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
        "INSERT OR IGNORE INTO am_credit_wallet (owner_token_hash) VALUES (?)",
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
    return fired


def _normalise_idempotency_key(raw: str | None) -> str | None:
    if raw is None:
        return None
    key = raw.strip()
    if not key:
        return None
    if not _IDEMPOTENCY_KEY_RE.fullmatch(key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_idempotency_key",
        )
    return key


def _wallet_idempotency_hash(*candidates: str | None) -> str | None:
    keys = [_normalise_idempotency_key(value) for value in candidates]
    present = [key for key in keys if key is not None]
    if not present:
        return None
    if len(set(present)) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="conflicting_idempotency_key",
        )
    return hashlib.sha256(present[0].encode("utf-8")).hexdigest()[:32]


def _append_idempotency_marker(
    note: str | None,
    *,
    idem_hash: str | None,
    balance_yen: int,
    billing_cycle: str,
) -> str | None:
    if idem_hash is None:
        return note
    marker = f"[wallet-idem:{idem_hash}:bal={balance_yen}:cycle={billing_cycle}]"
    return f"{note}\n{marker}" if note else marker


def _strip_idempotency_marker(note: str | None) -> str | None:
    if note is None:
        return None
    cleaned = _TOPUP_IDEMPOTENCY_MARKER_RE.sub("", note)
    cleaned = _IDEMPOTENCY_MARKER_RE.sub("", cleaned).rstrip("\n")
    return cleaned or None


def _append_topup_idempotency_marker(
    note: str | None,
    *,
    idem_hash: str | None,
    payload_hash: str,
    balance_yen: int,
    billing_cycle: str,
) -> str | None:
    if idem_hash is None:
        return note
    marker = (
        f"[wallet-topup-idem:{idem_hash}:fp={payload_hash}:"
        f"bal={balance_yen}:cycle={billing_cycle}]"
    )
    return f"{note}\n{marker}" if note else marker


def _find_idempotent_topup(
    conn: sqlite3.Connection,
    *,
    wallet_id: int,
    idem_hash: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT txn_id, amount_yen, occurred_at, note "
        "FROM am_credit_transaction_log "
        "WHERE wallet_id = ? AND txn_type = 'topup' AND note LIKE ? "
        "ORDER BY txn_id DESC LIMIT 1",
        (wallet_id, f"%[wallet-topup-idem:{idem_hash}:%"),
    ).fetchone()


def _find_idempotent_charge(
    conn: sqlite3.Connection,
    *,
    wallet_id: int,
    idem_hash: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT txn_id, amount_yen, occurred_at, note "
        "FROM am_credit_transaction_log "
        "WHERE wallet_id = ? AND txn_type = 'charge' AND note LIKE ? "
        "ORDER BY txn_id DESC LIMIT 1",
        (wallet_id, f"%[wallet-idem:{idem_hash}:%"),
    ).fetchone()


def _replay_topup_response(
    row: sqlite3.Row,
    *,
    wallet_id: int,
    body: TopupRequest,
    payload_hash: str,
) -> JSONResponse:
    topup_amount = int(body.immediate_amount)
    if int(row["amount_yen"]) != topup_amount:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotency_key_in_use",
        )

    match = _TOPUP_IDEMPOTENCY_MARKER_RE.search(row["note"] or "")
    if match and match.group(2) != payload_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotency_key_in_use",
        )
    balance_yen = int(match.group(3)) if match else 0
    payload = {
        "wallet_id": wallet_id,
        "balance_yen": balance_yen,
        "auto_topup_threshold": int(body.auto_topup_threshold),
        "auto_topup_amount": int(body.auto_topup_amount),
        "monthly_budget_yen": int(body.monthly_budget_yen),
        "enabled": True,
        "updated_at": row["occurred_at"],
        "topup_requested_yen": topup_amount,
        "topup_recorded_yen": topup_amount,
        "idempotent_replay": True,
        "_billing_unit": 0,
        "_disclaimer": _WALLET_DISCLAIMER,
    }
    return JSONResponse(
        content=payload,
        status_code=200,
        headers={"X-Idempotent-Replay": "1"},
    )


def _replay_charge_response(
    row: sqlite3.Row,
    *,
    wallet_id: int,
    charge_amount: int,
) -> JSONResponse:
    if int(row["amount_yen"]) != -charge_amount:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotency_key_in_use",
        )

    match = _IDEMPOTENCY_MARKER_RE.search(row["note"] or "")
    balance_yen = int(match.group(2)) if match else 0
    billing_cycle = match.group(3) if match else str(row["occurred_at"])[:7]
    payload = {
        "wallet_id": wallet_id,
        "charge_yen": charge_amount,
        "balance_yen": balance_yen,
        "alerts_fired": [],
        "billing_cycle": billing_cycle,
        "idempotent_replay": True,
        "_billing_unit": 0,
        "_disclaimer": _WALLET_DISCLAIMER,
    }
    return JSONResponse(
        content=payload,
        status_code=200,
        headers={"X-Idempotent-Replay": "1"},
    )


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class TopupRequest(BaseModel):
    """Auto-topup configuration plus internal-only immediate credit.

    All amounts are in JPY (integer). Public API-key callers may update
    ``auto_topup_threshold``, ``auto_topup_amount``, and ``monthly_budget_yen``.
    ``immediate_amount > 0`` is reserved for internal billing/metering callers
    after Stripe/x402 has already verified payment.
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
        description=(
            "Internal-only one-shot credit (¥) to record after the payment rail "
            "has already verified funds."
        ),
    )
    note: str | None = Field(None, max_length=256, description="Optional ledger note.")
    idempotency_key: str | None = Field(
        None,
        max_length=255,
        description="Optional retry key; prefer the Idempotency-Key header.",
    )
    request_id: str | None = Field(
        None,
        max_length=255,
        description="Optional legacy retry key used when Idempotency-Key is absent.",
    )


def _topup_payload_hash(body: TopupRequest) -> str:
    payload = (
        body.auto_topup_threshold,
        body.auto_topup_amount,
        body.monthly_budget_yen,
        body.immediate_amount,
        body.note or "",
    )
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()[:32]


class ChargeRequest(BaseModel):
    """Internal-only charge against the wallet (metering side).

    Inserts a ``charge`` row (amount < 0) and updates balance. Refuses
    to drive balance negative — returns 402 if insufficient.
    """

    amount_yen: int = Field(
        ..., gt=0, le=1_000_000, description="Positive charge amount (¥); signed flip in storage."
    )
    note: str | None = Field(None, max_length=256)
    idempotency_key: str | None = Field(
        None,
        max_length=255,
        description="Optional retry key; prefer the Idempotency-Key header.",
    )
    request_id: str | None = Field(
        None,
        max_length=255,
        description="Optional legacy retry key used when Idempotency-Key is absent.",
    )


# ---------------------------------------------------------------------------
# GET /v1/wallet/balance
# ---------------------------------------------------------------------------


@router.get(
    "/balance",
    summary="Current wallet balance + auto-topup config",
    description=(
        "Returns the caller's prepaid credit wallet state. Creates a "
        "zero-balance wallet row on first call. ``_billing_unit: 0`` — "
        "accounting metadata, not metered."
    ),
    responses={**COMMON_ERROR_RESPONSES, 200: {"description": "Wallet balance envelope."}},
)
def get_wallet_balance(ctx: ApiContextDep) -> JSONResponse:
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

    return JSONResponse(content=payload, status_code=200)


# ---------------------------------------------------------------------------
# POST /v1/wallet/topup
# ---------------------------------------------------------------------------


@router.post(
    "/topup",
    summary="Update auto-topup config",
    description=(
        "Updates ``auto_topup_threshold`` + ``auto_topup_amount`` + "
        "``monthly_budget_yen`` on the caller's wallet. Positive "
        "``immediate_amount`` credits are internal-only and require "
        "``X-Internal-Token`` after Stripe/x402 payment verification. "
        "**This handler does NOT call Stripe.**"
    ),
    responses={**COMMON_ERROR_RESPONSES, 200: {"description": "Updated wallet snapshot."}},
)
def update_wallet_topup(
    ctx: ApiContextDep,
    body: TopupRequest,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", description="Required for immediate topup retries."),
    ] = None,
    x_idempotency_key: Annotated[
        str | None,
        Header(alias="X-Idempotency-Key", description="Optional immediate topup retry key."),
    ] = None,
    x_internal_token: Annotated[
        str | None,
        Header(
            alias="X-Internal-Token",
            description="Internal billing token; required only for immediate credits.",
        ),
    ] = None,
) -> JSONResponse:
    owner_token_hash = _require_owner_token_hash(ctx)
    topup_amount = int(body.immediate_amount)
    idem_hash = _wallet_idempotency_hash(
        idempotency_key,
        x_idempotency_key,
        body.idempotency_key,
        body.request_id,
    )
    if topup_amount > 0:
        _check_internal_token(x_internal_token, action="topup")
        if idem_hash is None:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail="idempotency_key_required",
            )
    payload_hash = _topup_payload_hash(body) if topup_amount > 0 else None

    am = _open_am_rw()
    try:
        _require_wallet_schema(am)
        row = _get_or_create_wallet(am, owner_token_hash)
        wallet_id = int(row["wallet_id"])

        am.execute("BEGIN IMMEDIATE")
        if topup_amount > 0 and idem_hash is not None and payload_hash is not None:
            replay_row = _find_idempotent_topup(
                am,
                wallet_id=wallet_id,
                idem_hash=idem_hash,
            )
            if replay_row is not None:
                am.rollback()
                return _replay_topup_response(
                    replay_row,
                    wallet_id=wallet_id,
                    body=body,
                    payload_hash=payload_hash,
                )

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
        if topup_amount > 0:
            am.execute(
                "UPDATE am_credit_wallet SET balance_yen = balance_yen + ?, "
                "  updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE wallet_id = ?",
                (topup_amount, wallet_id),
            )

        refreshed = am.execute(
            "SELECT wallet_id, balance_yen, auto_topup_threshold, auto_topup_amount, "
            "       monthly_budget_yen, enabled, updated_at FROM am_credit_wallet "
            "WHERE wallet_id = ?",
            (wallet_id,),
        ).fetchone()
        if refreshed is None:
            am.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="wallet topup failed",
            )
        if topup_amount > 0 and payload_hash is not None:
            cycle = _current_billing_cycle()
            stored_note = _append_topup_idempotency_marker(
                body.note,
                idem_hash=idem_hash,
                payload_hash=payload_hash,
                balance_yen=int(refreshed["balance_yen"]),
                billing_cycle=cycle,
            )
            am.execute(
                "INSERT INTO am_credit_transaction_log "
                "(wallet_id, amount_yen, txn_type, note) VALUES (?, ?, 'topup', ?)",
                (wallet_id, topup_amount, stored_note),
            )
        am.commit()
    except Exception:
        with suppress(Exception):
            am.rollback()
        raise
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
        "topup_requested_yen": topup_amount,
        "topup_recorded_yen": topup_amount,
        "idempotent_replay": False,
        "_billing_unit": 0,
        "_disclaimer": _WALLET_DISCLAIMER,
    }

    return JSONResponse(content=payload, status_code=200)


# ---------------------------------------------------------------------------
# GET /v1/wallet/transactions
# ---------------------------------------------------------------------------


@router.get(
    "/transactions",
    summary="Paginated transaction ledger (topup/charge/refund)",
    description=(
        "Returns transaction rows for the caller's wallet, newest first. "
        "Supports ``txn_type`` filter + ``limit``/``offset`` pagination. "
        "``_billing_unit: 0``."
    ),
    responses={**COMMON_ERROR_RESPONSES, 200: {"description": "Transaction ledger."}},
)
def list_wallet_transactions(
    ctx: ApiContextDep,
    txn_type: Annotated[
        Literal["topup", "charge", "refund"] | None,
        Query(description="Filter by txn_type."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="Max rows.")] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000, description="Pagination offset.")] = 0,
) -> JSONResponse:
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
                "note": _strip_idempotency_marker(r["note"]),
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

    return JSONResponse(content=payload, status_code=200)


# ---------------------------------------------------------------------------
# GET /v1/wallet/alerts
# ---------------------------------------------------------------------------


@router.get(
    "/alerts",
    summary="Spending alert ledger (50/80/100 pct firings)",
    description=(
        "Returns spending alert rows for the caller's wallet, newest first. "
        "Supports ``billing_cycle`` filter (YYYY-MM). ``_billing_unit: 0``."
    ),
    responses={**COMMON_ERROR_RESPONSES, 200: {"description": "Alert ledger."}},
)
def list_wallet_alerts(
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

    return JSONResponse(content=payload, status_code=200)


# ---------------------------------------------------------------------------
# POST /v1/wallet/charge (internal)
# ---------------------------------------------------------------------------


def _check_internal_token(x_internal_token: str | None, *, action: str = "charge") -> None:
    """Reject internal wallet mutations without the operator metering token."""
    expected = os.environ.get("METERING_INTERNAL_TOKEN")
    if not expected:
        # Defensive — if the token isn't configured, /charge is permanently locked.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"wallet_{action}_unavailable",
        )
    if not x_internal_token or x_internal_token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"wallet_{action}_forbidden",
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
        403: {"description": "Internal token missing or invalid."},
    },
    include_in_schema=False,
)
def post_wallet_charge(
    ctx: ApiContextDep,
    body: ChargeRequest,
    x_internal_token: Annotated[
        str | None,
        Header(alias="X-Internal-Token", description="Internal metering token."),
    ] = None,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", description="Optional charge retry key."),
    ] = None,
    x_idempotency_key: Annotated[
        str | None,
        Header(alias="X-Idempotency-Key", description="Optional charge retry key."),
    ] = None,
) -> JSONResponse:
    _check_internal_token(x_internal_token)
    owner_token_hash = _require_owner_token_hash(ctx)
    idem_hash = _wallet_idempotency_hash(
        idempotency_key,
        x_idempotency_key,
        body.idempotency_key,
        body.request_id,
    )

    am = _open_am_rw()
    try:
        _require_wallet_schema(am)
        row = _get_or_create_wallet(am, owner_token_hash)
        wallet_id = int(row["wallet_id"])
        charge_amount = int(body.amount_yen)

        am.execute("BEGIN IMMEDIATE")

        if idem_hash is not None:
            replay_row = _find_idempotent_charge(
                am,
                wallet_id=wallet_id,
                idem_hash=idem_hash,
            )
            if replay_row is not None:
                am.rollback()
                return _replay_charge_response(
                    replay_row,
                    wallet_id=wallet_id,
                    charge_amount=charge_amount,
                )

        updated = am.execute(
            "UPDATE am_credit_wallet SET "
            "  balance_yen = balance_yen - ?, "
            "  updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE wallet_id = ? AND enabled = 1 AND balance_yen >= ?",
            (charge_amount, wallet_id, charge_amount),
        )
        if updated.rowcount != 1:
            am.rollback()
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="wallet balance insufficient",
            )

        refreshed = am.execute(
            "SELECT balance_yen, monthly_budget_yen FROM am_credit_wallet WHERE wallet_id = ?",
            (wallet_id,),
        ).fetchone()
        if refreshed is None:
            am.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="wallet charge failed",
            )

        new_balance = int(refreshed["balance_yen"])
        monthly_budget = int(refreshed["monthly_budget_yen"])
        cycle = _current_billing_cycle()
        stored_note = _append_idempotency_marker(
            body.note,
            idem_hash=idem_hash,
            balance_yen=new_balance,
            billing_cycle=cycle,
        )

        am.execute(
            "INSERT INTO am_credit_transaction_log "
            "(wallet_id, amount_yen, txn_type, note) VALUES (?, ?, 'charge', ?)",
            (wallet_id, -charge_amount, stored_note),
        )
        fired = _maybe_fire_alerts(am, wallet_id, monthly_budget, cycle)
        am.commit()
    except Exception:
        with suppress(Exception):
            am.rollback()
        raise
    finally:
        with suppress(Exception):
            am.close()

    payload = {
        "wallet_id": wallet_id,
        "charge_yen": charge_amount,
        "balance_yen": new_balance,
        "alerts_fired": fired,
        "billing_cycle": cycle,
        "idempotent_replay": False,
        "_billing_unit": 0,
        "_disclaimer": _WALLET_DISCLAIMER,
    }

    return JSONResponse(content=payload, status_code=200)


__all__ = ["router"]
