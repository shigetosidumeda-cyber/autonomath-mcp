"""Append-only JSONL ledger for the Wave 51 credit_wallet scaffolding.

The ledger is the source of truth. Each customer maps 1:1 to a JSONL
file at ``state/wallets/<customer_id>.jsonl``; every txn (topup,
charge, refund, alert) is one line. The current ``WalletAccount`` is
derived by replaying the log from disk.

Why JSONL append-only (mirrors ``predictive_service.registry``):

* Truncation / tampering is detectable post-hoc.
* No DB ATTACH against the 9.4 GB ``autonomath.db``.
* Same-process atomic line write (POSIX < PIPE_BUF guarantee).
* No customer payment data stored — yen amounts + opaque slugs only.

Non-negotiable constraints
--------------------------
* No outbound HTTP (Stripe / Coinbase contact happens elsewhere).
* No LLM imports.
* The 1.0 alert threshold triggers throttle (not stop) per
  ``feedback_agent_credit_wallet_design``.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from jpintel_mcp.credit_wallet.models import (
    DEFAULT_ALERT_THRESHOLDS,
    DEFAULT_DAILY_QUOTA_YEN,
    MAX_SINGLE_CHARGE_YEN,
    WalletAccount,
    WalletLedgerEntry,
    WalletResult,
    WalletTxnType,
)

#: Default state directory. Overridable via the explicit ``state_dir``
#: argument on every public function for per-test isolation.
DEFAULT_STATE_DIR: Final[Path] = Path("state") / "wallets"

#: Filename-safe customer_id pattern. Same as the Pydantic model.
_CUSTOMER_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_\-.]+$")


def _ledger_path_for(customer_id: str, *, state_dir: Path | None = None) -> Path:
    """Return the canonical JSONL path for ``customer_id``."""
    if not _CUSTOMER_ID_RE.fullmatch(customer_id):
        raise ValueError(
            f"customer_id is not filename-safe: {customer_id!r}"
        )
    root = state_dir if state_dir is not None else DEFAULT_STATE_DIR
    return root / f"{customer_id}.jsonl"


def _ensure_parent(path: Path) -> None:
    """Create the parent directory if it does not exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


def _append_entry(path: Path, entry: WalletLedgerEntry) -> None:
    """Append one JSON line to the ledger atomically (line-sized writes)."""
    _ensure_parent(path)
    line = entry.model_dump_json()
    if "\n" in line:
        raise ValueError("ledger line must not contain a newline")
    # POSIX guarantees writes < PIPE_BUF (typically 4 KiB) are atomic;
    # JSON lines for a wallet entry are well under that bound.
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _read_entries(
    path: Path,
    *,
    skip_malformed: bool = False,
) -> list[WalletLedgerEntry]:
    """Read all entries from ``path``. Empty list if file missing.

    When ``skip_malformed`` is False (default), a malformed line raises
    ``ValueError`` — surfacing tampering. Tests / ops tools that want
    to inspect partial state can pass ``skip_malformed=True``.
    """
    if not path.exists():
        return []
    out: list[WalletLedgerEntry] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
                entry = WalletLedgerEntry.model_validate(payload)
            except (json.JSONDecodeError, ValidationError) as exc:
                if skip_malformed:
                    continue
                raise ValueError(
                    f"ledger {path} line {lineno} malformed: {exc}"
                ) from exc
            out.append(entry)
    return out


def _utc_day_key(unix_ts: int) -> str:
    """Return a YYYY-MM-DD bucket key for ``unix_ts`` in UTC."""
    return datetime.fromtimestamp(unix_ts, tz=UTC).strftime("%Y-%m-%d")


def _now_unix() -> int:
    return int(time.time())


class WalletLedger:
    """File-backed append-only ledger for ONE customer.

    The ledger does NOT enforce concurrency control across processes;
    callers that need that should serialise via an external lock
    (Fly volume + single worker is the canonical jpcite topology).
    """

    def __init__(
        self,
        customer_id: str,
        *,
        state_dir: Path | None = None,
        auto_topup_threshold: int = 0,
        daily_quota_yen: int = DEFAULT_DAILY_QUOTA_YEN,
        alert_thresholds: tuple[float, ...] = DEFAULT_ALERT_THRESHOLDS,
    ) -> None:
        if not _CUSTOMER_ID_RE.fullmatch(customer_id):
            raise ValueError(
                f"customer_id is not filename-safe: {customer_id!r}"
            )
        self.customer_id = customer_id
        self.path = _ledger_path_for(customer_id, state_dir=state_dir)
        self.auto_topup_threshold = auto_topup_threshold
        self.daily_quota_yen = daily_quota_yen
        self.alert_thresholds = alert_thresholds

    # -- accessors --------------------------------------------------------

    def read_entries(self, *, skip_malformed: bool = False) -> list[WalletLedgerEntry]:
        return _read_entries(self.path, skip_malformed=skip_malformed)

    def account(self) -> WalletAccount:
        """Project the current account state from the ledger replay."""
        balance = 0
        for entry in self.read_entries():
            balance += entry.amount_yen
        balance = max(balance, 0)
        return WalletAccount(
            customer_id=self.customer_id,
            balance_yen=balance,
            auto_topup_threshold=self.auto_topup_threshold,
            daily_quota_yen=self.daily_quota_yen,
            alert_thresholds=self.alert_thresholds,
        )

    # -- mutations --------------------------------------------------------

    def _find_idempotent(
        self,
        idempotency_key: str | None,
    ) -> WalletLedgerEntry | None:
        if not idempotency_key:
            return None
        for entry in self.read_entries():
            if entry.idempotency_key == idempotency_key:
                return entry
        return None

    def _spent_today(self, now_unix: int) -> int:
        """Return absolute yen charged within the current UTC day."""
        today = _utc_day_key(now_unix)
        spent = 0
        for entry in self.read_entries():
            if entry.txn_type != WalletTxnType.CHARGE:
                continue
            if _utc_day_key(entry.occurred_at_unix) != today:
                continue
            # charge amounts are stored negative; spent is positive
            spent += -entry.amount_yen
        return spent

    def _alerts_fired_today(self, now_unix: int) -> set[float]:
        """Return alert thresholds already fired today (UTC)."""
        today = _utc_day_key(now_unix)
        fired: set[float] = set()
        for entry in self.read_entries():
            if entry.txn_type != WalletTxnType.ALERT:
                continue
            if _utc_day_key(entry.occurred_at_unix) != today:
                continue
            # Alert notes use the marker "[alert:<threshold>]"
            if entry.note and entry.note.startswith("[alert:"):
                try:
                    threshold = float(entry.note[len("[alert:") : -1])
                except (ValueError, IndexError):
                    continue
                fired.add(threshold)
        return fired

    def _maybe_fire_alerts(
        self,
        *,
        spent_after: int,
        balance_after: int,
        now_unix: int,
    ) -> tuple[tuple[float, ...], bool]:
        """Insert any alert rows that just became due. Returns (fired, throttle)."""
        if self.daily_quota_yen <= 0:
            return ((), False)
        fired_today = self._alerts_fired_today(now_unix)
        fresh: list[float] = []
        for threshold in self.alert_thresholds:
            if threshold in fired_today:
                continue
            threshold_yen = int(self.daily_quota_yen * threshold)
            if spent_after < threshold_yen:
                continue
            _append_entry(
                self.path,
                WalletLedgerEntry(
                    customer_id=self.customer_id,
                    txn_type=WalletTxnType.ALERT,
                    amount_yen=0,
                    balance_after_yen=balance_after,
                    occurred_at_unix=now_unix,
                    note=f"[alert:{threshold}]",
                ),
            )
            fresh.append(threshold)
        throttle = any(threshold >= 1.0 for threshold in fresh) and balance_after < self.daily_quota_yen
        return (tuple(fresh), throttle)

    def record_topup(
        self,
        amount_yen: int,
        *,
        note: str | None = None,
        idempotency_key: str | None = None,
        now_unix: int | None = None,
    ) -> WalletResult:
        """Record a positive credit. Idempotent on ``idempotency_key``."""
        if amount_yen <= 0:
            raise ValueError(f"topup amount_yen must be positive, got {amount_yen}")
        replay = self._find_idempotent(idempotency_key)
        if replay is not None:
            if replay.txn_type != WalletTxnType.TOPUP:
                raise ValueError(
                    f"idempotency_key {idempotency_key!r} already used "
                    f"for {replay.txn_type}"
                )
            return WalletResult(
                ok=True,
                customer_id=self.customer_id,
                txn_type=WalletTxnType.TOPUP,
                amount_yen=replay.amount_yen,
                balance_after_yen=replay.balance_after_yen,
                idempotent_replay=True,
            )

        now = now_unix if now_unix is not None else _now_unix()
        current = self.account().balance_yen
        new_balance = current + amount_yen
        entry = WalletLedgerEntry(
            customer_id=self.customer_id,
            txn_type=WalletTxnType.TOPUP,
            amount_yen=amount_yen,
            balance_after_yen=new_balance,
            occurred_at_unix=now,
            note=note,
            idempotency_key=idempotency_key,
        )
        _append_entry(self.path, entry)
        return WalletResult(
            ok=True,
            customer_id=self.customer_id,
            txn_type=WalletTxnType.TOPUP,
            amount_yen=amount_yen,
            balance_after_yen=new_balance,
        )

    def record_charge(
        self,
        amount_yen: int,
        *,
        note: str | None = None,
        idempotency_key: str | None = None,
        now_unix: int | None = None,
    ) -> WalletResult:
        """Record a charge. Fails closed if balance is insufficient."""
        if amount_yen <= 0:
            raise ValueError(f"charge amount_yen must be positive, got {amount_yen}")
        if amount_yen > MAX_SINGLE_CHARGE_YEN:
            raise ValueError(
                f"charge amount_yen exceeds MAX_SINGLE_CHARGE_YEN "
                f"({MAX_SINGLE_CHARGE_YEN}): {amount_yen}"
            )
        replay = self._find_idempotent(idempotency_key)
        if replay is not None:
            if replay.txn_type != WalletTxnType.CHARGE:
                raise ValueError(
                    f"idempotency_key {idempotency_key!r} already used "
                    f"for {replay.txn_type}"
                )
            return WalletResult(
                ok=True,
                customer_id=self.customer_id,
                txn_type=WalletTxnType.CHARGE,
                amount_yen=-replay.amount_yen,
                balance_after_yen=replay.balance_after_yen,
                idempotent_replay=True,
            )

        now = now_unix if now_unix is not None else _now_unix()
        current = self.account().balance_yen
        if current < amount_yen:
            return WalletResult(
                ok=False,
                customer_id=self.customer_id,
                txn_type=WalletTxnType.CHARGE,
                amount_yen=amount_yen,
                balance_after_yen=current,
                reason="insufficient_balance",
            )
        new_balance = current - amount_yen
        entry = WalletLedgerEntry(
            customer_id=self.customer_id,
            txn_type=WalletTxnType.CHARGE,
            amount_yen=-amount_yen,
            balance_after_yen=new_balance,
            occurred_at_unix=now,
            note=note,
            idempotency_key=idempotency_key,
        )
        _append_entry(self.path, entry)

        spent_after = self._spent_today(now)
        fired, throttle = self._maybe_fire_alerts(
            spent_after=spent_after,
            balance_after=new_balance,
            now_unix=now,
        )
        return WalletResult(
            ok=True,
            customer_id=self.customer_id,
            txn_type=WalletTxnType.CHARGE,
            amount_yen=amount_yen,
            balance_after_yen=new_balance,
            alerts_fired=fired,
            should_throttle=throttle,
        )


# ---------------------------------------------------------------------------
# Module-level convenience wrappers
# ---------------------------------------------------------------------------


def record_topup(
    customer_id: str,
    amount_yen: int,
    *,
    state_dir: Path | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
    now_unix: int | None = None,
    auto_topup_threshold: int = 0,
    daily_quota_yen: int = DEFAULT_DAILY_QUOTA_YEN,
    alert_thresholds: tuple[float, ...] = DEFAULT_ALERT_THRESHOLDS,
) -> WalletResult:
    """Module-level convenience wrapper for ``WalletLedger.record_topup``."""
    ledger = WalletLedger(
        customer_id,
        state_dir=state_dir,
        auto_topup_threshold=auto_topup_threshold,
        daily_quota_yen=daily_quota_yen,
        alert_thresholds=alert_thresholds,
    )
    return ledger.record_topup(
        amount_yen,
        note=note,
        idempotency_key=idempotency_key,
        now_unix=now_unix,
    )


def record_charge(
    customer_id: str,
    amount_yen: int,
    *,
    state_dir: Path | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
    now_unix: int | None = None,
    auto_topup_threshold: int = 0,
    daily_quota_yen: int = DEFAULT_DAILY_QUOTA_YEN,
    alert_thresholds: tuple[float, ...] = DEFAULT_ALERT_THRESHOLDS,
) -> WalletResult:
    """Module-level convenience wrapper for ``WalletLedger.record_charge``."""
    ledger = WalletLedger(
        customer_id,
        state_dir=state_dir,
        auto_topup_threshold=auto_topup_threshold,
        daily_quota_yen=daily_quota_yen,
        alert_thresholds=alert_thresholds,
    )
    return ledger.record_charge(
        amount_yen,
        note=note,
        idempotency_key=idempotency_key,
        now_unix=now_unix,
    )


def should_throttle(
    customer_id: str,
    *,
    state_dir: Path | None = None,
    daily_quota_yen: int = DEFAULT_DAILY_QUOTA_YEN,
    alert_thresholds: tuple[float, ...] = DEFAULT_ALERT_THRESHOLDS,
    now_unix: int | None = None,
) -> bool:
    """Return True if the wallet has crossed any threshold AND balance < quota.

    Per ``feedback_agent_credit_wallet_design``: the 1.0 threshold
    triggers throttle (not stop). This helper returns True when:

    * any alert threshold fired today (spending exceeded that pct of
      the daily quota), AND
    * the current balance is less than the daily quota (the wallet
      cannot service one more full quota's worth of calls).

    Returning True is a HINT — callers may choose to slow / partial-
    response rather than reject outright.
    """
    ledger = WalletLedger(
        customer_id,
        state_dir=state_dir,
        daily_quota_yen=daily_quota_yen,
        alert_thresholds=alert_thresholds,
    )
    now = now_unix if now_unix is not None else _now_unix()
    fired_today = ledger._alerts_fired_today(now)  # noqa: SLF001
    if not fired_today:
        return False
    balance = ledger.account().balance_yen
    return balance < daily_quota_yen


def get_account(
    customer_id: str,
    *,
    state_dir: Path | None = None,
    auto_topup_threshold: int = 0,
    daily_quota_yen: int = DEFAULT_DAILY_QUOTA_YEN,
    alert_thresholds: tuple[float, ...] = DEFAULT_ALERT_THRESHOLDS,
) -> WalletAccount:
    """Return the projected ``WalletAccount`` for ``customer_id``."""
    ledger = WalletLedger(
        customer_id,
        state_dir=state_dir,
        auto_topup_threshold=auto_topup_threshold,
        daily_quota_yen=daily_quota_yen,
        alert_thresholds=alert_thresholds,
    )
    return ledger.account()


__all__ = [
    "DEFAULT_STATE_DIR",
    "WalletLedger",
    "get_account",
    "record_charge",
    "record_topup",
    "should_throttle",
]


# ---------------------------------------------------------------------------
# Defensive guard: refuse to import if accidentally invoked from offline LLM
# tools (mirrors the predictive_service stance). The CI guard
# `tests/test_no_llm_in_production.py` catches imports of LLM SDKs; this
# explicit assertion adds a runtime tripwire so a stray monkeypatch in
# tests cannot smuggle an LLM call into the wallet path.
# ---------------------------------------------------------------------------


def _assert_no_llm_env_leak() -> None:
    """Light-touch tripwire: not a security boundary, just a smell test.

    The Wave 50 RC1 contract layer keeps customer payment flows
    completely off the LLM path. If a future refactor accidentally
    plumbs an LLM env var into wallet code, this tripwire flags it
    at the first import attempt under a strict env.
    """
    if os.environ.get("JPCITE_STRICT_NO_LLM_ASSERT") == "1":
        forbidden = (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
        )
        leaked = [name for name in forbidden if os.environ.get(name)]
        if leaked:
            raise RuntimeError(
                f"credit_wallet detected leaked LLM env vars: {leaked!r}; "
                "remove them before importing the wallet module"
            )


_assert_no_llm_env_leak()
