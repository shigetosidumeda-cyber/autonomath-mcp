"""Wave 59 Stream I — end-to-end smoke for the Wave 51 credit_wallet scaffolding.

The Wave 51 ``src/jpintel_mcp/credit_wallet/`` package was scaffolded but never
exercised end-to-end against an ephemeral state directory. This module wires
the public surface (``record_topup`` / ``record_charge`` / ``should_throttle``
/ ``get_account``) against a per-test ``tmp_path`` JSONL ledger and asserts
the five canonical lifecycle scenarios.

Scenarios
---------

1. **happy path** — fresh wallet, topup ¥10,000, three charges ¥300 / ¥600
   / ¥900 (total ¥1,800), assert final balance ¥8,200, no alert rows in the
   ledger, ``should_throttle`` is False.

2. **topup** — second topup compounds onto a partially-spent wallet; an
   idempotent retry with the same key is a no-op and returns
   ``idempotent_replay=True``.

3. **alerts at 50 / 80** — daily quota ¥10,000, charges that cross 50 %
   (¥5,000) and then 80 % (¥8,000) emit one alert ledger row per
   threshold, in ascending order, and each threshold fires at most once
   for the same UTC day.

4. **idempotency** — replaying a charge with the same idempotency key is a
   no-op; balance is unchanged and ``idempotent_replay=True`` on the
   replayed result. A different idempotency key with the same amount is a
   fresh charge.

5. **throttle at 100 %** — once spending crosses 100 % of ``daily_quota_yen``
   the wallet returns ``should_throttle=True`` AND a subsequent charge that
   would push the balance negative is rejected with
   ``ok=False`` / ``reason='insufficient_balance'`` (fail-closed).

Constraints
-----------

* Uses an **ephemeral** ``tmp_path`` directory — *never* touches the 9.4 GB
  production ``autonomath.db``.
* Pure CRUD + state machine — no LLM imports, no FastAPI router, no Stripe.
* All ``now_unix`` arguments are explicit so the suite is deterministic and
  independent of wall-clock skew.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from jpintel_mcp.credit_wallet import (
    WalletLedger,
    WalletTxnType,
    get_account,
    record_charge,
    record_topup,
    should_throttle,
)

# A fixed Monday-noon UTC instant — 2026-05-11 12:00:00 UTC.
# Charges in the same scenario reuse the same day so the per-day alert
# bookkeeping is exercised; scenarios that re-fire across days advance
# the timestamp by 24 h explicitly.
_FIXED_NOW_UNIX: int = 1_778_500_800
_ONE_DAY_S: int = 86_400


def _alert_thresholds(ledger: WalletLedger) -> list[float]:
    """Return the list of alert thresholds recorded in the ledger.

    Order reflects the order rows were appended to the JSONL file (the
    ledger is append-only) so callers can assert ascending order without
    sorting first.
    """
    pattern = re.compile(r"^\[alert:(?P<threshold>[0-9.]+)\]$")
    fired: list[float] = []
    for entry in ledger.read_entries():
        if entry.txn_type != WalletTxnType.ALERT:
            continue
        if entry.note is None:
            continue
        match = pattern.match(entry.note)
        if match is None:
            continue
        fired.append(float(match.group("threshold")))
    return fired


# ---------------------------------------------------------------------------
# Scenario 1 — happy path
# ---------------------------------------------------------------------------


def test_scenario_1_happy_path(tmp_path: Path) -> None:
    """Topup ¥10,000, charge ¥300 + ¥600 + ¥900, expect ¥8,200 with no alerts."""
    state_dir = tmp_path / "wallets"
    customer_id = "scenario-1-customer"

    # Daily quota is ¥10,000 so 50 % = ¥5,000 — the ¥1,800 total stays well
    # under the first alert threshold and exercises the no-alert branch.
    quota = 10_000

    topup_result = record_topup(
        customer_id,
        10_000,
        state_dir=state_dir,
        daily_quota_yen=quota,
        idempotency_key="scenario-1-topup",
        now_unix=_FIXED_NOW_UNIX,
    )
    assert topup_result.ok is True
    assert topup_result.txn_type == WalletTxnType.TOPUP
    assert topup_result.balance_after_yen == 10_000
    assert topup_result.idempotent_replay is False

    expected_balance = 10_000
    for amount in (300, 600, 900):
        expected_balance -= amount
        charge_result = record_charge(
            customer_id,
            amount,
            state_dir=state_dir,
            daily_quota_yen=quota,
            now_unix=_FIXED_NOW_UNIX,
        )
        assert charge_result.ok is True
        assert charge_result.txn_type == WalletTxnType.CHARGE
        assert charge_result.balance_after_yen == expected_balance
        # 1,800 yen total ≪ 5,000 yen (50 % of 10,000) — no alerts.
        assert charge_result.alerts_fired == ()
        assert charge_result.should_throttle is False

    account = get_account(
        customer_id,
        state_dir=state_dir,
        daily_quota_yen=quota,
    )
    assert account.balance_yen == 8_200
    assert account.daily_quota_yen == quota

    ledger = WalletLedger(
        customer_id,
        state_dir=state_dir,
        daily_quota_yen=quota,
    )
    assert _alert_thresholds(ledger) == []
    assert (
        should_throttle(
            customer_id,
            state_dir=state_dir,
            daily_quota_yen=quota,
            now_unix=_FIXED_NOW_UNIX,
        )
        is False
    )


# ---------------------------------------------------------------------------
# Scenario 2 — topup compounding + idempotent replay
# ---------------------------------------------------------------------------


def test_scenario_2_topup_compounds_and_replays(tmp_path: Path) -> None:
    """A second topup adds to balance; replaying the same key is a no-op."""
    state_dir = tmp_path / "wallets"
    customer_id = "scenario-2-customer"

    first = record_topup(
        customer_id,
        10_000,
        state_dir=state_dir,
        idempotency_key="scenario-2-topup-1",
        now_unix=_FIXED_NOW_UNIX,
    )
    assert first.balance_after_yen == 10_000
    assert first.idempotent_replay is False

    # Mid-cycle charge of ¥1,200 brings balance to ¥8,800 before the second
    # topup so we can prove the second topup compounds on top of the
    # remaining balance instead of replacing it.
    charge = record_charge(
        customer_id,
        1_200,
        state_dir=state_dir,
        now_unix=_FIXED_NOW_UNIX,
    )
    assert charge.ok is True
    assert charge.balance_after_yen == 8_800

    second = record_topup(
        customer_id,
        5_000,
        state_dir=state_dir,
        idempotency_key="scenario-2-topup-2",
        now_unix=_FIXED_NOW_UNIX,
    )
    assert second.balance_after_yen == 13_800
    assert second.idempotent_replay is False

    # Replaying the second topup with the same key is a no-op — balance
    # does NOT advance to 18,800.
    replay = record_topup(
        customer_id,
        5_000,
        state_dir=state_dir,
        idempotency_key="scenario-2-topup-2",
        now_unix=_FIXED_NOW_UNIX + 1,
    )
    assert replay.idempotent_replay is True
    assert replay.balance_after_yen == 13_800

    # The projected account confirms the balance is still 13,800.
    account = get_account(customer_id, state_dir=state_dir)
    assert account.balance_yen == 13_800


# ---------------------------------------------------------------------------
# Scenario 3 — alerts at 50 % and 80 %
# ---------------------------------------------------------------------------


def test_scenario_3_alerts_at_50_and_80(tmp_path: Path) -> None:
    """Crossing 50 % then 80 % of daily quota emits two alert rows in order."""
    state_dir = tmp_path / "wallets"
    customer_id = "scenario-3-customer"
    quota = 10_000  # 50 % = ¥5,000, 80 % = ¥8,000, 100 % = ¥10,000.

    # Top up twice the quota so balance never blocks the alert path.
    record_topup(
        customer_id,
        20_000,
        state_dir=state_dir,
        daily_quota_yen=quota,
        now_unix=_FIXED_NOW_UNIX,
    )

    # First charge of ¥5,100 — crosses 50 % only.
    first_charge = record_charge(
        customer_id,
        5_100,
        state_dir=state_dir,
        daily_quota_yen=quota,
        now_unix=_FIXED_NOW_UNIX,
    )
    assert first_charge.ok is True
    assert first_charge.alerts_fired == (0.5,)
    # spent = 5,100, balance_after = 14,900 ≥ quota — no throttle yet.
    assert first_charge.should_throttle is False

    # Second charge of ¥3,000 — pushes spent to ¥8,100, crosses 80 %.
    second_charge = record_charge(
        customer_id,
        3_000,
        state_dir=state_dir,
        daily_quota_yen=quota,
        now_unix=_FIXED_NOW_UNIX + 60,
    )
    assert second_charge.ok is True
    assert second_charge.alerts_fired == (0.8,)
    assert second_charge.should_throttle is False

    # A third small charge (¥100) does NOT re-fire 50 % or 80 % — each
    # threshold fires at most once per UTC day.
    third_charge = record_charge(
        customer_id,
        100,
        state_dir=state_dir,
        daily_quota_yen=quota,
        now_unix=_FIXED_NOW_UNIX + 120,
    )
    assert third_charge.ok is True
    assert third_charge.alerts_fired == ()

    ledger = WalletLedger(
        customer_id,
        state_dir=state_dir,
        daily_quota_yen=quota,
    )
    fired = _alert_thresholds(ledger)
    # Ordered append: 0.5 first, then 0.8 — never a duplicate.
    assert fired == [0.5, 0.8]


# ---------------------------------------------------------------------------
# Scenario 4 — idempotency key prevents double-charge
# ---------------------------------------------------------------------------


def test_scenario_4_idempotency_prevents_double_charge(tmp_path: Path) -> None:
    """Replaying a charge with the same idempotency key is a no-op."""
    state_dir = tmp_path / "wallets"
    customer_id = "scenario-4-customer"

    record_topup(
        customer_id,
        10_000,
        state_dir=state_dir,
        idempotency_key="scenario-4-topup",
        now_unix=_FIXED_NOW_UNIX,
    )

    first = record_charge(
        customer_id,
        900,
        state_dir=state_dir,
        idempotency_key="scenario-4-charge-A",
        now_unix=_FIXED_NOW_UNIX,
    )
    assert first.ok is True
    assert first.idempotent_replay is False
    assert first.balance_after_yen == 9_100

    # Same key, same amount, later timestamp — must be a no-op replay.
    replay = record_charge(
        customer_id,
        900,
        state_dir=state_dir,
        idempotency_key="scenario-4-charge-A",
        now_unix=_FIXED_NOW_UNIX + 30,
    )
    assert replay.ok is True
    assert replay.idempotent_replay is True
    assert replay.balance_after_yen == 9_100

    # A DIFFERENT idempotency key with the same amount is a fresh charge.
    fresh = record_charge(
        customer_id,
        900,
        state_dir=state_dir,
        idempotency_key="scenario-4-charge-B",
        now_unix=_FIXED_NOW_UNIX + 60,
    )
    assert fresh.ok is True
    assert fresh.idempotent_replay is False
    assert fresh.balance_after_yen == 8_200

    # Final projection: balance is 8,200 after exactly two real charges and
    # one idempotent replay (which must not deduct).
    account = get_account(customer_id, state_dir=state_dir)
    assert account.balance_yen == 8_200

    ledger = WalletLedger(customer_id, state_dir=state_dir)
    charge_rows = [e for e in ledger.read_entries() if e.txn_type == WalletTxnType.CHARGE]
    # Exactly two CHARGE rows on disk — the replay never wrote a third.
    assert len(charge_rows) == 2
    assert {row.idempotency_key for row in charge_rows} == {
        "scenario-4-charge-A",
        "scenario-4-charge-B",
    }


# ---------------------------------------------------------------------------
# Scenario 5 — throttle at 100 % AND fail-closed when balance is depleted
# ---------------------------------------------------------------------------


def test_scenario_5_throttle_at_100_percent(tmp_path: Path) -> None:
    """Reaching 100 % of daily quota flips ``should_throttle`` AND fails closed."""
    state_dir = tmp_path / "wallets"
    customer_id = "scenario-5-customer"
    quota = 10_000

    # Topup ¥10,000 — balance exactly matches the daily quota so a full
    # quota's worth of charges depletes both at once and exercises the
    # ``balance_after < daily_quota_yen`` half of the throttle predicate.
    record_topup(
        customer_id,
        10_000,
        state_dir=state_dir,
        daily_quota_yen=quota,
        now_unix=_FIXED_NOW_UNIX,
    )

    # First charge crosses 50 % at ¥5,000.
    record_charge(
        customer_id,
        5_000,
        state_dir=state_dir,
        daily_quota_yen=quota,
        now_unix=_FIXED_NOW_UNIX,
    )
    # Second charge crosses 80 % at ¥8,000.
    record_charge(
        customer_id,
        3_000,
        state_dir=state_dir,
        daily_quota_yen=quota,
        now_unix=_FIXED_NOW_UNIX + 30,
    )

    # Third charge crosses 100 % at exactly ¥10,000 spent, balance = 0.
    third = record_charge(
        customer_id,
        2_000,
        state_dir=state_dir,
        daily_quota_yen=quota,
        now_unix=_FIXED_NOW_UNIX + 60,
    )
    assert third.ok is True
    assert third.balance_after_yen == 0
    assert third.alerts_fired == (1.0,)
    assert third.should_throttle is True

    # Module-level helper agrees with the result envelope.
    assert (
        should_throttle(
            customer_id,
            state_dir=state_dir,
            daily_quota_yen=quota,
            now_unix=_FIXED_NOW_UNIX + 60,
        )
        is True
    )

    # The next charge attempt must FAIL CLOSED — balance is 0 so even a ¥1
    # charge is rejected without writing a CHARGE row.
    rejected = record_charge(
        customer_id,
        1,
        state_dir=state_dir,
        daily_quota_yen=quota,
        now_unix=_FIXED_NOW_UNIX + 90,
    )
    assert rejected.ok is False
    assert rejected.reason == "insufficient_balance"
    assert rejected.balance_after_yen == 0

    ledger = WalletLedger(
        customer_id,
        state_dir=state_dir,
        daily_quota_yen=quota,
    )
    fired = _alert_thresholds(ledger)
    assert fired == [0.5, 0.8, 1.0]

    # No CHARGE row was appended for the rejected attempt — ledger remains
    # exactly three charges.
    charge_rows = [e for e in ledger.read_entries() if e.txn_type == WalletTxnType.CHARGE]
    assert len(charge_rows) == 3
    assert [row.amount_yen for row in charge_rows] == [-5_000, -3_000, -2_000]


# ---------------------------------------------------------------------------
# Edge guards — sanity checks against the ephemeral DB invariant.
# ---------------------------------------------------------------------------


def test_state_dir_is_ephemeral_per_test(tmp_path: Path) -> None:
    """Each test's ``tmp_path`` is unique; nothing under ``data/`` is touched."""
    state_dir = tmp_path / "wallets"
    customer_id = "ephemeral-customer"

    record_topup(
        customer_id,
        500,
        state_dir=state_dir,
        now_unix=_FIXED_NOW_UNIX,
    )
    expected_path = state_dir / f"{customer_id}.jsonl"
    assert expected_path.is_file()
    # The default ``state/wallets/`` path under the repo MUST NOT exist for
    # this opaque customer — verifies we are not leaking writes outside
    # ``tmp_path``.
    leaked = Path("state") / "wallets" / f"{customer_id}.jsonl"
    assert not leaked.exists(), (
        f"smoke leaked outside tmp_path: {leaked}; the test must NEVER "
        "write to the production state dir or autonomath.db"
    )


def test_unknown_idempotency_key_reuse_across_txn_types_raises(
    tmp_path: Path,
) -> None:
    """Reusing a topup idempotency key on a charge raises ValueError."""
    state_dir = tmp_path / "wallets"
    customer_id = "reuse-customer"
    shared_key = "shared-key"

    record_topup(
        customer_id,
        10_000,
        state_dir=state_dir,
        idempotency_key=shared_key,
        now_unix=_FIXED_NOW_UNIX,
    )

    with pytest.raises(ValueError, match="already used"):
        record_charge(
            customer_id,
            100,
            state_dir=state_dir,
            idempotency_key=shared_key,
            now_unix=_FIXED_NOW_UNIX + _ONE_DAY_S,
        )
