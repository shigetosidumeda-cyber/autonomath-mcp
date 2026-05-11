"""Yearly prepay plan (Wave 21 D6).

Year-up-front purchase of 40,000 requests for ¥100,000 (= ¥2.5/req effective).
This is a single Stripe one-time invoice + a negative customer_balance grant,
modeled in the same way as the credit pack (``credit_pack.py``), but with
two distinguishing fields:

  * ``valid_until``  — 12 months after grant. Requests consumed past this
    date are billed at ¥3/req (base) and the residual prepay balance is
    written off per ToS §19の5 (non-refundable, no expiry on monetary value
    — but the *prepay rate* expires).
  * ``baseline_qty`` — 40,000 / year. Cron at
    ``scripts/cron/run_yearly_prepay_burndown.py`` reconciles consumption
    monthly; this module exposes the schema + the Stripe invoice helper.

Lifecycle
---------
1. ``create_yearly_prepay_invoice`` issues a Stripe one-time Invoice
   (¥100,000 with ``metadata.kind='yearly_prepay'``).
2. Customer pays via hosted invoice URL.
3. Webhook (``api/billing.py``) routes paid prepay invoices to
   ``apply_yearly_prepay``, which calls
   ``Customer.create_balance_transaction`` (amount=-100,000) AND writes a
   row to ``yearly_prepay_grant`` (migration 165 series — registered with
   the same op-locked reservation pattern used by the credit pack).
4. Each metered request first decrements ``baseline_qty_remaining``; if 0,
   the request falls back to ¥3/req base.

Non-negotiables
---------------
- Annual minimum is **rate-only** — there is no SKU labeled "Yearly Plan"
  and no "Pro tier" / "Free tier". The customer's effective price is
  ¥2.5/req from the day of grant for the first 40,000 reqs of the next 12
  months — nothing else changes.
- ¥3/req remains the canonical sticker price; this is a rebate, not a SKU.
- Pure Python, no Stripe SDK import at module top (we mirror the
  ``credit_pack.py`` injection-style API so tests can substitute a stub).
- No LLM. ``feedback_no_operator_llm_api`` strictly enforced.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import types

logger = logging.getLogger("jpintel.billing.yearly_prepay")

# ---------------------------------------------------------------------------
# Tier constants (locked 2026-05-11 — bump in lockstep with the Stripe
# Product/Price metadata + ToS §19の5).
# ---------------------------------------------------------------------------

PREPAY_AMOUNT_JPY: Final[int] = 100_000
PREPAY_BASELINE_QTY: Final[int] = 40_000
PREPAY_EFFECTIVE_RATE_JPY: Final[Decimal] = Decimal("2.50")
PREPAY_VALIDITY_DAYS: Final[int] = 365

METADATA_KIND: Final[str] = "yearly_prepay"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class YearlyPrepayPurchaseRequest(BaseModel):
    """POST /v1/billing/yearly_prepay/purchase body."""

    customer_id: str = Field(
        ...,
        min_length=1,
        max_length=80,
        pattern=r"^cus_[A-Za-z0-9_]+$",
        description="Stripe Customer id (cus_*).",
    )
    confirm_terms_v0_3_4: bool = Field(
        ...,
        description=(
            "Must be true. Acknowledges ToS §19の5 (prepay rate expires after "
            "365d, residual monetary value remains non-refundable)."
        ),
    )


class YearlyPrepayPurchaseResponse(BaseModel):
    invoice_url: str
    baseline_qty: int = PREPAY_BASELINE_QTY
    effective_rate_jpy: str
    valid_until: str


@dataclass(frozen=True)
class PrepayState:
    """Snapshot of a customer's prepay grant."""

    customer_id: str
    baseline_qty_remaining: int
    valid_until: datetime
    granted_at: datetime
    stripe_balance_txn_id: str | None

    @property
    def is_active(self) -> bool:
        return self.baseline_qty_remaining > 0 and self.valid_until > datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Stripe helpers (caller injects ``stripe`` module / stub).
# ---------------------------------------------------------------------------


def create_yearly_prepay_invoice(stripe_client: types.ModuleType, customer_id: str) -> Any:
    """Create the ¥100,000 hosted invoice. See ``credit_pack.create_credit_pack_invoice``."""
    description = (
        f"jpcite yearly prepay — {PREPAY_BASELINE_QTY:,} req / 12mo "
        f"@ ¥{PREPAY_EFFECTIVE_RATE_JPY}/req"
    )
    metadata = {
        "kind": METADATA_KIND,
        "amount_jpy": str(PREPAY_AMOUNT_JPY),
        "baseline_qty": str(PREPAY_BASELINE_QTY),
    }
    stripe_client.InvoiceItem.create(
        customer=customer_id,
        amount=PREPAY_AMOUNT_JPY,
        currency="jpy",
        description=description,
        metadata=metadata,
    )
    invoice = stripe_client.Invoice.create(
        customer=customer_id,
        collection_method="send_invoice",
        days_until_due=30,
        metadata=metadata,
        description=description,
        auto_advance=False,
    )
    invoice_id = invoice["id"] if isinstance(invoice, dict) else invoice.id
    return stripe_client.Invoice.finalize_invoice(invoice_id)


def apply_yearly_prepay(
    stripe_client: types.ModuleType,
    customer_id: str,
    *,
    idempotency_key: str | None = None,
) -> Any:
    """Apply paid yearly prepay to the customer balance (negative ¥100,000)."""
    create_kwargs: dict[str, Any] = {
        "amount": -PREPAY_AMOUNT_JPY,
        "currency": "jpy",
        "description": (
            f"jpcite yearly prepay applied — {PREPAY_BASELINE_QTY:,} req baseline"
        ),
        "metadata": {
            "kind": METADATA_KIND,
            "amount_jpy": str(PREPAY_AMOUNT_JPY),
            "baseline_qty": str(PREPAY_BASELINE_QTY),
            "valid_until": _valid_until_iso(),
        },
    }
    if idempotency_key:
        create_kwargs["idempotency_key"] = idempotency_key
    return stripe_client.Customer.create_balance_transaction(customer_id, **create_kwargs)


def yearly_prepay_idempotency_key(stripe_invoice_id: str) -> str:
    """Business key for prepay grant idempotency."""
    if not stripe_invoice_id:
        raise ValueError("yearly prepay grant requires invoice_id")
    return f"yearly_prepay:{stripe_invoice_id}"


# ---------------------------------------------------------------------------
# Local SQLite mirror (yearly_prepay_grant). Same pattern as credit_pack.
# ---------------------------------------------------------------------------


def _db_path(override: str | Path | None = None) -> Path:
    if override is not None:
        return Path(override)
    raw = os.environ.get("JPINTEL_DB_PATH") or os.environ.get("AUTONOMATH_DB_PATH")
    return Path(raw) if raw else Path("jpintel.db")


def _connect(override: str | Path | None = None) -> sqlite3.Connection:
    path = _db_path(override)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 300000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_yearly_prepay_table(conn: sqlite3.Connection) -> None:
    """Create the grant ledger when migrations are not pre-applied."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS yearly_prepay_grant (
            idempotency_key            TEXT PRIMARY KEY,
            customer_id                TEXT NOT NULL,
            baseline_qty               INTEGER NOT NULL DEFAULT 40000,
            baseline_qty_remaining     INTEGER NOT NULL DEFAULT 40000,
            granted_at                 TEXT NOT NULL DEFAULT (datetime('now')),
            valid_until                TEXT NOT NULL,
            stripe_balance_txn_id      TEXT,
            status                     TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'exhausted', 'expired'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_yp_customer_active "
        "ON yearly_prepay_grant(customer_id, status) WHERE status = 'active'"
    )


def _valid_until_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=PREPAY_VALIDITY_DAYS)).isoformat()


def record_grant(
    conn: sqlite3.Connection,
    *,
    idempotency_key: str,
    customer_id: str,
    stripe_balance_txn_id: str | None,
) -> bool:
    """Idempotently insert the grant ledger row.

    Returns True if a new row was inserted; False if the key already existed.
    """
    valid_until = _valid_until_iso()
    cur = conn.execute(
        "INSERT INTO yearly_prepay_grant "
        "(idempotency_key, customer_id, baseline_qty, baseline_qty_remaining, valid_until, stripe_balance_txn_id) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(idempotency_key) DO NOTHING",
        (
            idempotency_key,
            customer_id,
            PREPAY_BASELINE_QTY,
            PREPAY_BASELINE_QTY,
            valid_until,
            stripe_balance_txn_id,
        ),
    )
    return cur.rowcount == 1


def burn_one(conn: sqlite3.Connection, customer_id: str) -> bool:
    """Decrement ``baseline_qty_remaining`` by 1 if the customer has an active grant.

    Returns True if a unit was burned (so the request is priced at ¥2.5),
    False if no active grant remains (caller falls back to ¥3 base + volume_rebate).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT idempotency_key, baseline_qty_remaining, valid_until "
            "FROM yearly_prepay_grant "
            "WHERE customer_id = ? AND status = 'active' AND valid_until > ? "
            "ORDER BY granted_at ASC LIMIT 1",
            (customer_id, now_iso),
        ).fetchone()
        if row is None or row["baseline_qty_remaining"] <= 0:
            conn.execute("COMMIT")
            return False
        new_qty = int(row["baseline_qty_remaining"]) - 1
        new_status = "exhausted" if new_qty <= 0 else "active"
        conn.execute(
            "UPDATE yearly_prepay_grant SET baseline_qty_remaining = ?, status = ? "
            "WHERE idempotency_key = ?",
            (new_qty, new_status, row["idempotency_key"]),
        )
        conn.execute("COMMIT")
        return True
    except Exception:
        with contextlib.suppress(Exception):
            conn.execute("ROLLBACK")
        raise


def get_state(conn: sqlite3.Connection, customer_id: str) -> PrepayState | None:
    """Return the customer's current active prepay state, or None."""
    row = conn.execute(
        "SELECT customer_id, baseline_qty_remaining, valid_until, granted_at, "
        "stripe_balance_txn_id "
        "FROM yearly_prepay_grant WHERE customer_id = ? AND status = 'active' "
        "ORDER BY granted_at ASC LIMIT 1",
        (customer_id,),
    ).fetchone()
    if row is None:
        return None
    return PrepayState(
        customer_id=row["customer_id"],
        baseline_qty_remaining=int(row["baseline_qty_remaining"]),
        valid_until=datetime.fromisoformat(str(row["valid_until"])),
        granted_at=datetime.fromisoformat(str(row["granted_at"])),
        stripe_balance_txn_id=row["stripe_balance_txn_id"],
    )


def expire_stale(conn: sqlite3.Connection) -> int:
    """Mark all grants whose ``valid_until`` has passed as 'expired'.

    Returns the number of rows transitioned. Intended for cron invocation
    from ``scripts/cron/expire_trials.py`` (the same cron that already runs
    daily trial+credit-pack housekeeping).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "UPDATE yearly_prepay_grant SET status = 'expired' "
        "WHERE status = 'active' AND valid_until <= ?",
        (now_iso,),
    )
    return cur.rowcount or 0


def describe_plan_ja() -> str:
    return (
        f"年額一括 ¥{PREPAY_AMOUNT_JPY:,} で {PREPAY_BASELINE_QTY:,} req "
        f"(¥{PREPAY_EFFECTIVE_RATE_JPY}/req 効率、12 ヶ月有効、税込 ¥{int(PREPAY_AMOUNT_JPY * 1.1):,})。"
        "個別 SKU ではなく rate rebate。残量超過分は ¥3/req base + volume_rebate に自動回帰"
    )


__all__ = [
    "METADATA_KIND",
    "PREPAY_AMOUNT_JPY",
    "PREPAY_BASELINE_QTY",
    "PREPAY_EFFECTIVE_RATE_JPY",
    "PREPAY_VALIDITY_DAYS",
    "PrepayState",
    "YearlyPrepayPurchaseRequest",
    "YearlyPrepayPurchaseResponse",
    "apply_yearly_prepay",
    "burn_one",
    "create_yearly_prepay_invoice",
    "describe_plan_ja",
    "ensure_yearly_prepay_table",
    "expire_stale",
    "get_state",
    "record_grant",
    "yearly_prepay_idempotency_key",
]
