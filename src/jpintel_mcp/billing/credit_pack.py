"""Stripe credit pack prepay (¥300K / ¥1M / ¥3M one-time top-up).

Lets enterprise procurement sign ONE 稟議 instead of N monthly invoices —
the customer pays a lump sum, Stripe records it as a negative
``customer_balance``, and subsequent ¥3/req metered usage is consumed
from that balance until it reaches zero.

Lifecycle
---------
1. ``create_credit_pack_invoice`` issues a Stripe one-time Invoice
   (lookup-key-less ad-hoc InvoiceItem, line description ``"API credit
   pack ¥XXX,XXX"``). The hosted invoice URL is returned to the caller.
2. The customer pays the invoice via the hosted URL. Stripe fires
   ``invoice.paid`` with the same invoice id.
3. The webhook handler (api/billing.py) routes credit-pack invoices
   (identified by ``metadata.kind="credit_pack"``) to
   ``apply_credit_pack``, which calls
   ``Customer.create_balance_transaction`` with a negative ``amount``
   so the customer balance is debited (Stripe applies the credit
   against subsequent invoices).
4. The local ``am_credit_pack_purchase`` row (migration 148) is updated
   with ``status='paid'``, ``stripe_balance_txn_id``, ``paid_at``.

Refund / expiry policy
----------------------
Per ToS §19の4 (non-refundable, no expiry). The schema CHECK on
``status`` accepts ``refunded`` / ``expired`` for operator-side manual
overrides only — the API never auto-issues either transition.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import types


logger = logging.getLogger("jpintel.billing.credit_pack")

# Published pack tiers. Mirrored in the migration 148 CHECK constraint and
# in the ToS §19の4 enumeration; bumping requires updates in lockstep.
ALLOWED_AMOUNTS_JPY: frozenset[int] = frozenset({300_000, 1_000_000, 3_000_000})

# Stripe metadata key that identifies a credit-pack invoice in the webhook
# branch. Plain string — Stripe metadata values are case-sensitive UTF-8.
CREDIT_PACK_METADATA_KIND: str = "credit_pack"

# Retry stale local reservations only while Stripe's idempotency cache should
# still be available. Stripe documents idempotency keys as prunable after 24h,
# so rows older than this are left for operator reconciliation.
CREDIT_PACK_RESERVED_RETRY_AFTER_SECONDS: int = 300
CREDIT_PACK_RESERVED_OPERATOR_REVIEW_SECONDS: int = 23 * 60 * 60


class CreditPackPurchaseRequest(BaseModel):
    """POST /v1/billing/credit/purchase body."""

    amount_jpy: Literal[300_000, 1_000_000, 3_000_000] = Field(
        ..., description="Pack tier in JPY. One of 300K / 1M / 3M."
    )
    customer_id: str = Field(
        ...,
        min_length=1,
        max_length=80,
        pattern=r"^cus_[A-Za-z0-9_]+$",
        description="Stripe Customer id (cus_*). Stripe ids may include underscores in test mode.",
    )


class CreditPackPurchaseResponse(BaseModel):
    """POST /v1/billing/credit/purchase response."""

    invoice_url: str
    balance_after: int
    expires_at: str | None = None


def create_credit_pack_invoice(
    stripe_client: types.ModuleType,
    customer_id: str,
    amount_jpy: int,
) -> Any:
    """Create a one-time Stripe Invoice for a credit pack.

    Steps:
      1. ``InvoiceItem.create`` — pending invoice item with the pack amount
         and a description carrying the JPY value (line item shown on the
         hosted invoice + 適格請求書 PDF).
      2. ``Invoice.create`` — collect the pending item, set
         ``collection_method='send_invoice'`` so Stripe hosts a payment URL
         (no auto-charge), and stamp ``metadata.kind='credit_pack'`` plus
         ``metadata.amount_jpy=<int>`` so the webhook branch can re-derive
         the pack value without re-reading the line items.
      3. ``Invoice.finalize_invoice`` — promotes draft → open and exposes
         ``hosted_invoice_url``.

    All three calls raise the underlying ``stripe.error.StripeError``
    family on failure; the caller (route handler) translates to a 502
    upstream-error envelope.
    """
    if amount_jpy not in ALLOWED_AMOUNTS_JPY:
        raise ValueError(
            f"amount_jpy must be one of {sorted(ALLOWED_AMOUNTS_JPY)}, got {amount_jpy}"
        )
    description = f"API credit pack ¥{amount_jpy:,}"
    metadata = {
        "kind": CREDIT_PACK_METADATA_KIND,
        "amount_jpy": str(amount_jpy),
    }
    # InvoiceItem first — must be customer-scoped, currency=jpy, no quantity
    # (Stripe JPY is zero-decimal so unit_amount IS the yen value).
    stripe_client.InvoiceItem.create(
        customer=customer_id,
        amount=amount_jpy,
        currency="jpy",
        description=description,
        metadata=metadata,
    )
    # Invoice collects the pending item. send_invoice → hosted URL,
    # no automatic card charge so procurement can pay via 振込 if they
    # configured that on the Customer.
    invoice = stripe_client.Invoice.create(
        customer=customer_id,
        collection_method="send_invoice",
        days_until_due=30,
        metadata=metadata,
        description=description,
        auto_advance=False,
    )
    # Finalize so hosted_invoice_url is populated.
    invoice = stripe_client.Invoice.finalize_invoice(_invoice_id(invoice))
    return invoice


def apply_credit_pack(
    stripe_client: types.ModuleType,
    customer_id: str,
    amount_jpy: int,
    *,
    idempotency_key: str | None = None,
) -> Any:
    """Apply paid credit pack to the Stripe customer balance.

    Calls ``Customer.create_balance_transaction`` with a NEGATIVE
    ``amount`` so Stripe records a credit on the customer (negative
    customer_balance = the customer is owed money, applied automatically
    against subsequent invoices). Returns the resulting
    ``CustomerBalanceTransaction`` so the caller can record
    ``stripe_balance_txn_id`` locally.

    Callers should provide the reservation idempotency key so a webhook retry
    after a worker crash reuses the same Stripe result instead of creating a
    second customer-balance transaction.
    """
    if amount_jpy not in ALLOWED_AMOUNTS_JPY:
        raise ValueError(
            f"amount_jpy must be one of {sorted(ALLOWED_AMOUNTS_JPY)}, got {amount_jpy}"
        )
    description = f"API credit pack ¥{amount_jpy:,} applied to balance"
    create_kwargs: dict[str, Any] = {
        "amount": -amount_jpy,
        "currency": "jpy",
        "description": description,
        "metadata": {
            "kind": CREDIT_PACK_METADATA_KIND,
            "amount_jpy": str(amount_jpy),
        },
    }
    if idempotency_key:
        create_kwargs["idempotency_key"] = idempotency_key
    txn = stripe_client.Customer.create_balance_transaction(
        customer_id,
        **create_kwargs,
    )
    return txn


def credit_pack_idempotency_key(
    stripe_invoice_id: str | None,
    payment_intent_id: str | None = None,
) -> str:
    """Business-key idempotency key for a paid credit-pack grant."""
    if stripe_invoice_id:
        return f"credit_pack:{stripe_invoice_id}"
    if payment_intent_id:
        return f"credit_pack:{payment_intent_id}"
    raise ValueError("credit pack grant requires invoice_id or payment_intent_id")


def _reservation_db_path(db_path: str | Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    raw = os.environ.get("JPINTEL_DB_PATH") or os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path("jpintel.db")


def _connect_reservation_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = _reservation_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 300000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_credit_pack_reservation_table(conn: sqlite3.Connection) -> None:
    """Create the DD-04 reservation table when migrations are not pre-applied."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS credit_pack_reservation (
            idempotency_key TEXT PRIMARY KEY,
            customer_id     TEXT NOT NULL,
            pack_size       INTEGER NOT NULL CHECK (pack_size IN (300000, 1000000, 3000000)),
            status          TEXT NOT NULL CHECK (status IN ('reserved', 'granted', 'failed')),
            reserved_at     TEXT NOT NULL DEFAULT (datetime('now')),
            granted_at      TEXT,
            stripe_balance_txn_id TEXT,
            error_reason    TEXT
        )
        """
    )
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(credit_pack_reservation)")}
    if "stripe_balance_txn_id" not in cols:
        conn.execute("ALTER TABLE credit_pack_reservation ADD COLUMN stripe_balance_txn_id TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_credit_pack_reservation_customer_status "
        "ON credit_pack_reservation(customer_id, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_credit_pack_reservation_status_reserved_at "
        "ON credit_pack_reservation(status, reserved_at) WHERE status = 'reserved'"
    )


def _reservation_error_reason(exc: BaseException) -> str:
    return f"{exc.__class__.__name__}: {str(exc)[:200]}"


def _reserve_credit_pack_grant(
    conn: sqlite3.Connection,
    *,
    key: str,
    customer_id: str,
    pack_size: int,
    reserved_retry_after_seconds: int,
    reserved_operator_review_seconds: int,
) -> tuple[bool, str, str | None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "INSERT INTO credit_pack_reservation "
            "(idempotency_key, customer_id, pack_size, status, reserved_at) "
            "VALUES (?, ?, ?, 'reserved', datetime('now')) "
            "ON CONFLICT(idempotency_key) DO NOTHING",
            (key, customer_id, pack_size),
        )
        if cur.rowcount == 1:
            conn.execute("COMMIT")
            return True, "reserved", None

        row = conn.execute(
            "SELECT status, customer_id, pack_size, stripe_balance_txn_id, "
            "CAST(strftime('%s', 'now') AS INTEGER) - "
            "CAST(strftime('%s', reserved_at) AS INTEGER) AS reserved_age_seconds "
            "FROM credit_pack_reservation WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"credit pack reservation disappeared key={key}")
        status = str(row["status"])
        existing_txn_id = row["stripe_balance_txn_id"]
        if row["customer_id"] != customer_id or int(row["pack_size"]) != pack_size:
            raise RuntimeError(
                f"credit pack reservation key collision with different customer/pack key={key}"
            )
        if status == "failed":
            conn.execute(
                "UPDATE credit_pack_reservation "
                "SET status = 'reserved', customer_id = ?, pack_size = ?, "
                "reserved_at = datetime('now'), granted_at = NULL, "
                "stripe_balance_txn_id = NULL, error_reason = NULL "
                "WHERE idempotency_key = ? AND status = 'failed'",
                (customer_id, pack_size, key),
            )
            conn.execute("COMMIT")
            return True, "reserved", None
        if status == "reserved":
            age_seconds = row["reserved_age_seconds"]
            age_seconds = int(age_seconds) if age_seconds is not None else 0
            if age_seconds >= reserved_operator_review_seconds:
                conn.execute("COMMIT")
                return False, "reserved_operator_review", existing_txn_id
            if age_seconds >= reserved_retry_after_seconds:
                conn.execute(
                    "UPDATE credit_pack_reservation "
                    "SET reserved_at = datetime('now'), error_reason = ? "
                    "WHERE idempotency_key = ? AND status = 'reserved'",
                    (f"retrying stale reservation after {age_seconds}s", key),
                )
                conn.execute("COMMIT")
                return True, "reserved_retry", existing_txn_id
        conn.execute("COMMIT")
        return False, status, existing_txn_id
    except Exception:
        with contextlib.suppress(Exception):
            conn.execute("ROLLBACK")
        raise


def _mark_credit_pack_granted(
    conn: sqlite3.Connection,
    *,
    key: str,
    stripe_balance_txn_id: str | None,
) -> bool:
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "UPDATE credit_pack_reservation "
            "SET status = 'granted', granted_at = datetime('now'), "
            "stripe_balance_txn_id = COALESCE(?, stripe_balance_txn_id), "
            "error_reason = NULL "
            "WHERE idempotency_key = ? AND status = 'reserved'",
            (stripe_balance_txn_id, key),
        )
        conn.execute("COMMIT")
        return cur.rowcount == 1
    except Exception:
        with contextlib.suppress(Exception):
            conn.execute("ROLLBACK")
        raise


def _mark_credit_pack_failed(
    conn: sqlite3.Connection,
    *,
    key: str,
    exc: BaseException,
) -> None:
    conn.execute(
        "UPDATE credit_pack_reservation "
        "SET status = 'failed', error_reason = ? "
        "WHERE idempotency_key = ? AND status = 'reserved'",
        (_reservation_error_reason(exc), key),
    )


def grant_credit_pack_idempotent(
    stripe_client: types.ModuleType,
    *,
    stripe_invoice_id: str | None,
    customer_id: str,
    pack_size: int,
    payment_intent_id: str | None = None,
    db_path: str | Path | None = None,
    reserved_retry_after_seconds: int = CREDIT_PACK_RESERVED_RETRY_AFTER_SECONDS,
    reserved_operator_review_seconds: int = CREDIT_PACK_RESERVED_OPERATOR_REVIEW_SECONDS,
) -> dict[str, Any]:
    """Apply a credit pack at most once per invoice/payment-intent key."""
    if pack_size not in ALLOWED_AMOUNTS_JPY:
        raise ValueError(f"pack_size must be one of {sorted(ALLOWED_AMOUNTS_JPY)}, got {pack_size}")
    key = credit_pack_idempotency_key(stripe_invoice_id, payment_intent_id)
    conn = _connect_reservation_db(db_path)
    try:
        ensure_credit_pack_reservation_table(conn)
        should_grant, status, existing_txn_id = _reserve_credit_pack_grant(
            conn,
            key=key,
            customer_id=customer_id,
            pack_size=pack_size,
            reserved_retry_after_seconds=reserved_retry_after_seconds,
            reserved_operator_review_seconds=reserved_operator_review_seconds,
        )
        if not should_grant:
            return {
                "status": status,
                "fresh": False,
                "idempotency_key": key,
                "stripe_balance_txn_id": existing_txn_id,
                "retryable": status == "reserved",
                "manual_reconciliation_required": status == "reserved_operator_review",
            }

        try:
            txn = apply_credit_pack(
                stripe_client,
                customer_id,
                pack_size,
                idempotency_key=key,
            )
        except Exception as exc:
            _mark_credit_pack_failed(conn, key=key, exc=exc)
            raise

        txn_id = balance_txn_id(txn)
        marked = _mark_credit_pack_granted(
            conn,
            key=key,
            stripe_balance_txn_id=txn_id,
        )
        if not marked:
            logger.warning("credit_pack_reservation_grant_update_lost key=%s", key)
        return {
            "status": "granted",
            "fresh": True,
            "idempotency_key": key,
            "stripe_balance_txn_id": txn_id,
            "retryable": False,
            "manual_reconciliation_required": False,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helpers (Stripe SDK objects are dict-like; tests substitute plain dicts).
# ---------------------------------------------------------------------------


def _invoice_id(invoice: Any) -> str:
    """Read ``id`` from a Stripe Invoice or test double."""
    if isinstance(invoice, dict):
        return str(invoice["id"])
    return str(invoice.id)


def hosted_invoice_url(invoice: Any) -> str | None:
    if isinstance(invoice, dict):
        return invoice.get("hosted_invoice_url")
    return getattr(invoice, "hosted_invoice_url", None)


def balance_txn_id(txn: Any) -> str | None:
    if isinstance(txn, dict):
        return txn.get("id")
    return getattr(txn, "id", None)


def metadata_kind(obj: Any) -> str | None:
    """Read ``metadata.kind`` from a Stripe object / dict."""
    md: Any
    if isinstance(obj, dict):
        md = obj.get("metadata") or {}
    else:
        md = getattr(obj, "metadata", None) or {}
    if isinstance(md, dict):
        return md.get("kind")
    return getattr(md, "kind", None)


def metadata_amount_jpy(obj: Any) -> int | None:
    """Read ``metadata.amount_jpy`` from a Stripe object / dict."""
    md: Any
    if isinstance(obj, dict):
        md = obj.get("metadata") or {}
    else:
        md = getattr(obj, "metadata", None) or {}
    raw: Any = md.get("amount_jpy") if isinstance(md, dict) else getattr(md, "amount_jpy", None)
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


__all__ = [
    "ALLOWED_AMOUNTS_JPY",
    "CREDIT_PACK_METADATA_KIND",
    "CREDIT_PACK_RESERVED_OPERATOR_REVIEW_SECONDS",
    "CREDIT_PACK_RESERVED_RETRY_AFTER_SECONDS",
    "CreditPackPurchaseRequest",
    "CreditPackPurchaseResponse",
    "apply_credit_pack",
    "balance_txn_id",
    "create_credit_pack_invoice",
    "credit_pack_idempotency_key",
    "ensure_credit_pack_reservation_table",
    "grant_credit_pack_idempotent",
    "hosted_invoice_url",
    "metadata_amount_jpy",
    "metadata_kind",
]
