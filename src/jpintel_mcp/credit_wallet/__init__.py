"""Wave 51 credit_wallet scaffolding package.

Re-exports the canonical public surface of the file-backed JSONL wallet
ledger so callers do not need to know whether ``record_topup`` lives in
``credit_wallet.ledger`` or in a future ``credit_wallet.api`` shim.

The production REST surface lives in
``src/jpintel_mcp/api/credit_wallet.py`` (SQLite-backed against
migration 281). This package is the **router-agnostic scaffolding**
added in Wave 51 — pure CRUD + state machine over a JSONL log, no
FastAPI, no Stripe, no LLM imports.
"""

from __future__ import annotations

from jpintel_mcp.credit_wallet.ledger import (
    DEFAULT_STATE_DIR,
    WalletLedger,
    get_account,
    record_charge,
    record_topup,
    should_throttle,
)
from jpintel_mcp.credit_wallet.models import (
    DEFAULT_ALERT_THRESHOLDS,
    DEFAULT_DAILY_QUOTA_YEN,
    MAX_BALANCE_YEN,
    MAX_SINGLE_CHARGE_YEN,
    WalletAccount,
    WalletLedgerEntry,
    WalletResult,
    WalletTxnType,
)

__all__ = [
    "DEFAULT_ALERT_THRESHOLDS",
    "DEFAULT_DAILY_QUOTA_YEN",
    "DEFAULT_STATE_DIR",
    "MAX_BALANCE_YEN",
    "MAX_SINGLE_CHARGE_YEN",
    "WalletAccount",
    "WalletLedger",
    "WalletLedgerEntry",
    "WalletResult",
    "WalletTxnType",
    "get_account",
    "record_charge",
    "record_topup",
    "should_throttle",
]
