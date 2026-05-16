"""Pydantic models for the Wave 51 Credit Wallet scaffolding.

Mirrors the design in ``feedback_agent_credit_wallet_design`` (prepaid
credits + auto-topup + 50/80/100 spending alerts with throttle). The
scaffolding stores wallets in a file-backed JSONL ledger under
``state/wallets/<customer_id>.jsonl`` — no DB ATTACH, no Stripe
contact, no LLM imports.

The Wave 48 router at ``src/jpintel_mcp/api/credit_wallet.py`` is the
production surface (SQLite-backed against migration 281). This package
is the **router-agnostic scaffolding** added in Wave 51 so MCP tools,
ETL probes, and offline CLI scripts can record charges + topups
without depending on the FastAPI router internals or SQLite.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Canonical default daily quota in yen for a wallet that has never
#: been topped up. ¥3/req × 3 free req/day = ¥9 implicit quota,
#: rounded to a defensible ¥100/day. Override per-customer if needed.
DEFAULT_DAILY_QUOTA_YEN: Final[int] = 100

#: Canonical alert thresholds — match the design memo verbatim.
DEFAULT_ALERT_THRESHOLDS: Final[tuple[float, ...]] = (0.5, 0.8, 1.0)

#: Maximum balance accepted by any single account. Defensive ceiling.
MAX_BALANCE_YEN: Final[int] = 100_000_000

#: Maximum single charge amount. Defensive ceiling per the design memo.
MAX_SINGLE_CHARGE_YEN: Final[int] = 1_000_000


class WalletTxnType(StrEnum):
    """Canonical ledger txn types."""

    TOPUP = "topup"
    CHARGE = "charge"
    REFUND = "refund"
    ALERT = "alert"


class WalletAccount(BaseModel):
    """A customer's wallet state envelope.

    The ledger is the source of truth — this envelope is a projection
    derived from replaying the JSONL log. ``balance_yen`` is what
    remains after all charges and topups; ``auto_topup_threshold`` is
    the balance below which an external topup webhook should fire.

    ``alert_thresholds`` is a tuple of floats in [0, 1] indicating the
    fraction of ``daily_quota_yen`` consumed at which a 50/80/100
    alert row is written. Per the design memo, the 100% threshold
    triggers throttle (not stop) so partial degradation is preferred
    over hard fail.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    customer_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_\-.]+$",
        description=(
            "Opaque customer slug. Used as the file basename for "
            "the JSONL ledger so MUST be filename-safe ASCII."
        ),
    )
    balance_yen: int = Field(
        ...,
        ge=0,
        le=MAX_BALANCE_YEN,
        description="Current wallet balance in JPY. Never negative.",
    )
    auto_topup_threshold: int = Field(
        default=0,
        ge=0,
        le=MAX_BALANCE_YEN,
        description=(
            "Balance below which an external auto-topup webhook "
            "SHOULD fire. 0 disables auto-topup."
        ),
    )
    daily_quota_yen: int = Field(
        default=DEFAULT_DAILY_QUOTA_YEN,
        ge=0,
        le=MAX_BALANCE_YEN,
        description=(
            "Soft daily spending budget. Drives the 50/80/100 alert "
            "thresholds. 0 disables alerts."
        ),
    )
    alert_thresholds: tuple[float, ...] = Field(
        default=DEFAULT_ALERT_THRESHOLDS,
        min_length=1,
        max_length=8,
        description=(
            "Sorted ascending sequence of [0, 1] alert thresholds. "
            "The 1.0 threshold implies throttle (not stop) per the "
            "design memo."
        ),
    )

    @field_validator("alert_thresholds")
    @classmethod
    def _validate_alert_thresholds(
        cls,
        value: tuple[float, ...],
    ) -> tuple[float, ...]:
        if not value:
            raise ValueError("alert_thresholds must not be empty")
        for threshold in value:
            if not 0 <= threshold <= 1:
                raise ValueError(
                    f"alert_thresholds must be in [0, 1], got {threshold}"
                )
        sorted_values = tuple(sorted(value))
        if sorted_values != value:
            raise ValueError(
                "alert_thresholds must be sorted ascending; "
                f"got {value}"
            )
        if len(set(value)) != len(value):
            raise ValueError("alert_thresholds must not contain duplicates")
        return value


class WalletLedgerEntry(BaseModel):
    """One row in the append-only JSONL ledger."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    customer_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_\-.]+$",
    )
    txn_type: WalletTxnType
    amount_yen: int = Field(
        ...,
        description=(
            "Signed amount in JPY. Positive for topup/refund, negative "
            "for charge. Zero allowed only for alert rows."
        ),
    )
    balance_after_yen: int = Field(
        ...,
        ge=0,
        le=MAX_BALANCE_YEN,
        description="Wallet balance after this txn was applied.",
    )
    occurred_at_unix: int = Field(
        ...,
        gt=0,
        description="Unix epoch seconds at which the txn was recorded.",
    )
    note: str | None = Field(
        default=None,
        max_length=256,
        description="Optional human-readable note for ops trace.",
    )
    idempotency_key: str | None = Field(
        default=None,
        max_length=255,
        description=(
            "Optional client-supplied retry key. Duplicate keys for "
            "the same customer are no-ops."
        ),
    )


class WalletResult(BaseModel):
    """Return value from ``record_charge`` / ``record_topup``.

    ``ok`` reflects whether the txn was applied. On a failed charge
    (insufficient balance) the ledger is NOT touched and ``ok`` is
    False with ``reason`` populated.

    ``alerts_fired`` lists thresholds (in [0, 1]) that crossed during
    this txn. Each threshold fires AT MOST ONCE per day per wallet —
    the ledger replay enforces this. ``should_throttle`` is True iff
    the 1.0 threshold (or higher) fired and the wallet is now over
    its daily quota.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    ok: bool
    customer_id: str
    txn_type: WalletTxnType
    amount_yen: int
    balance_after_yen: int
    alerts_fired: tuple[float, ...] = Field(default_factory=tuple)
    should_throttle: bool = False
    reason: str | None = None
    idempotent_replay: bool = False


__all__ = [
    "DEFAULT_ALERT_THRESHOLDS",
    "DEFAULT_DAILY_QUOTA_YEN",
    "MAX_BALANCE_YEN",
    "MAX_SINGLE_CHARGE_YEN",
    "WalletAccount",
    "WalletLedgerEntry",
    "WalletResult",
    "WalletTxnType",
]
