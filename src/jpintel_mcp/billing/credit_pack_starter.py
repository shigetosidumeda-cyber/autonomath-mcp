"""Starter credit pack (¥25,000 = 10,000 req @ ¥2.5/req) — Wave 21 D5.

The original credit pack lineup (300K / 1M / 3M ¥, see ``credit_pack.py``)
targets enterprise procurement that signs ONE 稟議 and pays a lump sum.
For early-stage adopters (税理士事務所 1 名 / SMB owner) the ¥300K floor
is too tall for a first commitment.

Starter pack:

  * ¥25,000 one-time → 10,000 req credit (¥2.5/req — same effective rate
    as the 300K tier so we are not undercutting our own enterprise pricing,
    just lowering the entry bar)
  * Same Stripe one-time invoice + ``Customer.create_balance_transaction``
    pattern as ``credit_pack.py``
  * Same idempotency reservation table (``credit_pack_reservation`` mig
    165) + idempotency cache (``idempotency_cache`` mig 087)
  * **Stacks** with volume rebate (``volume_rebate.py``) and yearly prepay
    (``yearly_prepay.py``) — if a customer has both a starter pack and a
    yearly prepay, the prepay burns first, starter pack second, then the
    metered rate applies with volume rebate.

Eligibility:

  * Customer cannot have already purchased the ¥25,000 starter (one per
    Stripe Customer, enforced via `am_starter_pack_used` row).
  * Customer can later upgrade to 300K / 1M / 3M packs; starter does
    not auto-renew.

Pure Python, no Stripe SDK import at module top — caller injects ``stripe``
module same as the parent ``credit_pack.create_credit_pack_invoice``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import types


logger = logging.getLogger("jpintel.billing.credit_pack_starter")

# ---------------------------------------------------------------------------
# Constants — bump in lockstep with the Stripe Product metadata + ToS §19の4.
# ---------------------------------------------------------------------------

STARTER_AMOUNT_JPY: Final[int] = 25_000
STARTER_BASELINE_QTY: Final[int] = 10_000
STARTER_EFFECTIVE_RATE_JPY: Final[float] = 2.5
METADATA_KIND: Final[str] = "credit_pack_starter"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class StarterPackPurchaseRequest(BaseModel):
    """POST /v1/billing/credit/starter body."""

    customer_id: str = Field(
        ...,
        min_length=1,
        max_length=80,
        pattern=r"^cus_[A-Za-z0-9_]+$",
        description="Stripe Customer id (cus_*).",
    )
    confirm_starter_once: bool = Field(
        ...,
        description=(
            "Must be true. Acknowledges the starter pack is single-purchase "
            "per Customer (ToS §19の4の2)."
        ),
    )


class StarterPackPurchaseResponse(BaseModel):
    invoice_url: str
    baseline_qty: int = STARTER_BASELINE_QTY
    effective_rate_jpy: float = STARTER_EFFECTIVE_RATE_JPY


# ---------------------------------------------------------------------------
# Stripe wire (caller injects ``stripe``)
# ---------------------------------------------------------------------------


def create_starter_pack_invoice(stripe_client: types.ModuleType, customer_id: str) -> Any:
    """Create the ¥25,000 one-time invoice for the starter pack."""
    description = (
        f"jpcite starter credit pack — {STARTER_BASELINE_QTY:,} req @ "
        f"¥{STARTER_EFFECTIVE_RATE_JPY}/req"
    )
    metadata = {
        "kind": METADATA_KIND,
        "amount_jpy": str(STARTER_AMOUNT_JPY),
        "baseline_qty": str(STARTER_BASELINE_QTY),
    }
    stripe_client.InvoiceItem.create(
        customer=customer_id,
        amount=STARTER_AMOUNT_JPY,
        currency="jpy",
        description=description,
        metadata=metadata,
    )
    invoice = stripe_client.Invoice.create(
        customer=customer_id,
        collection_method="send_invoice",
        days_until_due=14,  # shorter than enterprise (30d) — starter is small
        metadata=metadata,
        description=description,
        auto_advance=False,
    )
    invoice_id = invoice["id"] if isinstance(invoice, dict) else invoice.id
    return stripe_client.Invoice.finalize_invoice(invoice_id)


def apply_starter_pack(
    stripe_client: types.ModuleType,
    customer_id: str,
    *,
    idempotency_key: str | None = None,
) -> Any:
    """Apply paid starter pack as a -¥25,000 customer balance entry."""
    create_kwargs: dict[str, Any] = {
        "amount": -STARTER_AMOUNT_JPY,
        "currency": "jpy",
        "description": (
            f"jpcite starter credit pack applied — {STARTER_BASELINE_QTY:,} req baseline"
        ),
        "metadata": {
            "kind": METADATA_KIND,
            "amount_jpy": str(STARTER_AMOUNT_JPY),
            "baseline_qty": str(STARTER_BASELINE_QTY),
        },
    }
    if idempotency_key:
        create_kwargs["idempotency_key"] = idempotency_key
    return stripe_client.Customer.create_balance_transaction(customer_id, **create_kwargs)


def starter_pack_idempotency_key(stripe_invoice_id: str) -> str:
    if not stripe_invoice_id:
        raise ValueError("starter pack grant requires invoice_id")
    return f"credit_pack_starter:{stripe_invoice_id}"


# ---------------------------------------------------------------------------
# Local mirror — starter_pack_grant + once-per-customer enforcement.
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


def ensure_starter_pack_table(conn: sqlite3.Connection) -> None:
    """Create the once-per-customer grant table when migrations are not pre-applied."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS starter_pack_grant (
            idempotency_key        TEXT PRIMARY KEY,
            customer_id            TEXT NOT NULL UNIQUE,  -- ONE per Customer
            baseline_qty           INTEGER NOT NULL DEFAULT 10000,
            baseline_qty_remaining INTEGER NOT NULL DEFAULT 10000,
            granted_at             TEXT NOT NULL DEFAULT (datetime('now')),
            stripe_balance_txn_id  TEXT,
            status                 TEXT NOT NULL DEFAULT 'active'
              CHECK (status IN ('active', 'exhausted'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_starter_pack_customer_active "
        "ON starter_pack_grant(customer_id, status) WHERE status = 'active'"
    )


def has_used_starter(conn: sqlite3.Connection, customer_id: str) -> bool:
    """Return True if the customer has already purchased a starter pack."""
    row = conn.execute(
        "SELECT 1 FROM starter_pack_grant WHERE customer_id = ?",
        (customer_id,),
    ).fetchone()
    return row is not None


def record_grant(
    conn: sqlite3.Connection,
    *,
    idempotency_key: str,
    customer_id: str,
    stripe_balance_txn_id: str | None,
) -> bool:
    """Insert the grant; idempotent. Returns True on fresh insert."""
    cur = conn.execute(
        "INSERT INTO starter_pack_grant "
        "(idempotency_key, customer_id, baseline_qty, baseline_qty_remaining, stripe_balance_txn_id) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(idempotency_key) DO NOTHING",
        (
            idempotency_key,
            customer_id,
            STARTER_BASELINE_QTY,
            STARTER_BASELINE_QTY,
            stripe_balance_txn_id,
        ),
    )
    return cur.rowcount == 1


def burn_one(conn: sqlite3.Connection, customer_id: str) -> bool:
    """Decrement remaining by 1 if active grant exists. Returns True if burned."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT idempotency_key, baseline_qty_remaining "
            "FROM starter_pack_grant "
            "WHERE customer_id = ? AND status = 'active' "
            "ORDER BY granted_at ASC LIMIT 1",
            (customer_id,),
        ).fetchone()
        if row is None or row["baseline_qty_remaining"] <= 0:
            conn.execute("COMMIT")
            return False
        new_qty = int(row["baseline_qty_remaining"]) - 1
        new_status = "exhausted" if new_qty <= 0 else "active"
        conn.execute(
            "UPDATE starter_pack_grant SET baseline_qty_remaining = ?, status = ? "
            "WHERE idempotency_key = ?",
            (new_qty, new_status, row["idempotency_key"]),
        )
        conn.execute("COMMIT")
        return True
    except Exception:
        with contextlib.suppress(Exception):
            conn.execute("ROLLBACK")
        raise


def describe_plan_ja() -> str:
    return (
        f"スターターパック ¥{STARTER_AMOUNT_JPY:,} で {STARTER_BASELINE_QTY:,} req "
        f"(¥{STARTER_EFFECTIVE_RATE_JPY}/req 効率、税込 ¥{int(STARTER_AMOUNT_JPY * 1.1):,})。"
        "1 Customer 1 回限り、yearly prepay / volume rebate と stack 可"
    )


__all__ = [
    "METADATA_KIND",
    "STARTER_AMOUNT_JPY",
    "STARTER_BASELINE_QTY",
    "STARTER_EFFECTIVE_RATE_JPY",
    "StarterPackPurchaseRequest",
    "StarterPackPurchaseResponse",
    "apply_starter_pack",
    "burn_one",
    "create_starter_pack_invoice",
    "describe_plan_ja",
    "ensure_starter_pack_table",
    "has_used_starter",
    "record_grant",
    "starter_pack_idempotency_key",
]
