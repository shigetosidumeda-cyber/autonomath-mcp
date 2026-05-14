"""REST endpoint tests for the Agent Credit Wallet (Wave 48 tick#7).

Covers the 5 endpoints in :mod:`jpintel_mcp.api.credit_wallet`:

  * GET  /v1/wallet/balance       — 200 + zero-balance on first call
  * POST /v1/wallet/topup         — config update + internal-only immediate top-up
  * GET  /v1/wallet/transactions  — paginated ledger + txn_type filter
  * GET  /v1/wallet/alerts        — alert ledger + billing_cycle filter
  * POST /v1/wallet/charge        — internal-token gate + 50/80/100 alert trigger

Verifications:
  1. anonymous (no X-API-Key) → 401 on every endpoint.
  2. /charge without X-Internal-Token → 403.
  3. /charge with insufficient balance → 402.
  4. /charge crossing 50/80/100 thresholds fires exactly those alerts, once per cycle.
  5. /topup immediate_amount is forbidden to public callers and token-gated for internal callers.
  6. /transactions filter + pagination works.
  7. LLM SDK import = 0 in the new module.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.conftest import TestClient

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_281 = REPO_ROOT / "scripts" / "migrations" / "281_credit_wallet.sql"
CREDIT_WALLET_PY = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "credit_wallet.py"


@pytest.fixture()
def wallet_am_db(tmp_path, monkeypatch):
    """Fresh autonomath.db with migration 281 applied + AUTONOMATH_DB_PATH pointed at it."""
    db_path = tmp_path / "autonomath_wallet_test.db"
    sql = MIG_281.read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    conn.executescript(sql)
    conn.commit()
    conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("METERING_INTERNAL_TOKEN", "test-internal-token-secret")
    return db_path


def _sole_wallet_id(db_path: pathlib.Path) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT wallet_id FROM am_credit_wallet").fetchone()
    assert row is not None, "expected wallet row to be created by API call"
    return int(row[0])


def _set_wallet_balance(db_path: pathlib.Path, balance_yen: int) -> None:
    wallet_id = _sole_wallet_id(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE am_credit_wallet SET balance_yen = ? WHERE wallet_id = ?",
            (balance_yen, wallet_id),
        )


def _seed_wallet_txn(
    db_path: pathlib.Path,
    *,
    amount_yen: int,
    txn_type: str,
    note: str,
    occurred_at: str,
) -> None:
    wallet_id = _sole_wallet_id(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO am_credit_transaction_log "
            "(wallet_id, amount_yen, txn_type, note, occurred_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (wallet_id, amount_yen, txn_type, note, occurred_at),
        )


# ---------------------------------------------------------------------------
# 1. GET /v1/wallet/balance
# ---------------------------------------------------------------------------


def test_balance_anonymous_returns_401(client: TestClient, wallet_am_db) -> None:
    r = client.get("/v1/wallet/balance")
    assert r.status_code == 401, r.text


def test_balance_zero_on_first_call(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    r = client.get("/v1/wallet/balance", headers={"X-API-Key": paid_key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balance_yen"] == 0
    assert body["auto_topup_threshold"] == 0
    assert body["auto_topup_amount"] == 0
    assert body["monthly_budget_yen"] == 0
    assert body["enabled"] is True
    assert body["_billing_unit"] == 0
    assert "_disclaimer" in body
    assert body["current_cycle_spent_yen"] == 0


def test_wallet_schema_missing_returns_generic_503(
    client: TestClient, paid_key: str, tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "empty_autonomath.db"
    sqlite3.connect(db_path).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))

    r = client.get("/v1/wallet/balance", headers={"X-API-Key": paid_key})

    assert r.status_code == 503, r.text
    assert r.json()["detail"] == "wallet service unavailable"
    public_text = r.text.lower()
    assert "migration" not in public_text
    assert "sqlite" not in public_text
    assert "am_credit" not in public_text


# ---------------------------------------------------------------------------
# 2. POST /v1/wallet/topup
# ---------------------------------------------------------------------------


def test_topup_anonymous_returns_401(client: TestClient, wallet_am_db) -> None:
    r = client.post("/v1/wallet/topup", json={"auto_topup_threshold": 100})
    assert r.status_code == 401, r.text


def test_topup_sets_config_without_public_credit(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    payload = {
        "auto_topup_threshold": 500,
        "auto_topup_amount": 3000,
        "monthly_budget_yen": 10_000,
        "note": "initial pre-pay",
    }
    r = client.post(
        "/v1/wallet/topup",
        json=payload,
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balance_yen"] == 0
    assert body["auto_topup_threshold"] == 500
    assert body["auto_topup_amount"] == 3000
    assert body["monthly_budget_yen"] == 10_000
    assert body["topup_requested_yen"] == 0
    assert body["topup_recorded_yen"] == 0
    assert body["idempotent_replay"] is False
    assert body["_billing_unit"] == 0

    # The balance endpoint should reflect the same state.
    r2 = client.get("/v1/wallet/balance", headers={"X-API-Key": paid_key})
    assert r2.status_code == 200
    assert r2.json()["balance_yen"] == 0
    assert r2.json()["_billing_unit"] == 0

    with sqlite3.connect(wallet_am_db) as conn:
        balance, topups = conn.execute(
            "SELECT w.balance_yen, COUNT(t.txn_id) "
            "FROM am_credit_wallet w "
            "LEFT JOIN am_credit_transaction_log t "
            "  ON t.wallet_id = w.wallet_id AND t.txn_type = 'topup' "
            "GROUP BY w.wallet_id"
        ).fetchone()
    assert balance == 0
    assert topups == 0


def test_topup_immediate_forbidden_without_internal_token(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    r = client.post(
        "/v1/wallet/topup",
        json={"immediate_amount": 2_500},
        headers={"X-API-Key": paid_key, "Idempotency-Key": "wallet-topup-public"},
    )

    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "wallet_topup_forbidden"


def test_topup_immediate_internal_requires_idempotency_key(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    r = client.post(
        "/v1/wallet/topup",
        json={"immediate_amount": 2_500},
        headers={
            "X-API-Key": paid_key,
            "X-Internal-Token": "test-internal-token-secret",
        },
    )

    assert r.status_code == 428, r.text
    assert r.json()["detail"] == "idempotency_key_required"


def test_topup_internal_credits_immediate_once(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    payload = {
        "auto_topup_threshold": 500,
        "auto_topup_amount": 3000,
        "monthly_budget_yen": 10_000,
        "immediate_amount": 2_500,
        "note": "initial pre-pay",
    }
    r = client.post(
        "/v1/wallet/topup",
        json=payload,
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 403, r.text

    r = client.post(
        "/v1/wallet/topup",
        json=payload,
        headers={
            "X-API-Key": paid_key,
            "X-Internal-Token": "test-internal-token-secret",
            "Idempotency-Key": "wallet-topup-initial",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balance_yen"] == 2_500
    assert body["topup_requested_yen"] == 2_500
    assert body["topup_recorded_yen"] == 2_500
    with sqlite3.connect(wallet_am_db) as conn:
        balance, topups = conn.execute(
            "SELECT w.balance_yen, COUNT(t.txn_id) "
            "FROM am_credit_wallet w "
            "LEFT JOIN am_credit_transaction_log t "
            "  ON t.wallet_id = w.wallet_id AND t.txn_type = 'topup' "
            "GROUP BY w.wallet_id"
        ).fetchone()
    assert balance == 2_500
    assert topups == 1


def test_topup_idempotency_key_dedupes_body_retry(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    payload = {
        "auto_topup_threshold": 500,
        "auto_topup_amount": 3000,
        "monthly_budget_yen": 10_000,
        "immediate_amount": 2_500,
        "note": "retryable topup",
    }
    headers = {
        "X-API-Key": paid_key,
        "X-Internal-Token": "test-internal-token-secret",
        "Idempotency-Key": "wallet-topup-retry",
    }

    first = client.post("/v1/wallet/topup", json=payload, headers=headers)
    second = client.post("/v1/wallet/topup", json=payload, headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["balance_yen"] == 2_500
    assert second.json()["balance_yen"] == 2_500
    assert second.json()["idempotent_replay"] is True
    assert second.headers["X-Idempotent-Replay"] == "1"

    with sqlite3.connect(wallet_am_db) as conn:
        balance, topups = conn.execute(
            "SELECT w.balance_yen, COUNT(t.txn_id) "
            "FROM am_credit_wallet w "
            "LEFT JOIN am_credit_transaction_log t "
            "  ON t.wallet_id = w.wallet_id AND t.txn_type = 'topup' "
            "GROUP BY w.wallet_id"
        ).fetchone()
    assert balance == 2_500
    assert topups == 1

    txns = client.get(
        "/v1/wallet/transactions?txn_type=topup",
        headers={"X-API-Key": paid_key},
    )
    assert txns.status_code == 200, txns.text
    assert txns.json()["transactions"][0]["note"] == "retryable topup"
    assert "wallet-topup-idem" not in txns.text


def test_topup_same_idempotency_key_rejects_changed_payload(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    headers = {
        "X-API-Key": paid_key,
        "X-Internal-Token": "test-internal-token-secret",
        "Idempotency-Key": "wallet-topup-conflict",
    }
    first = client.post(
        "/v1/wallet/topup",
        json={"immediate_amount": 2_500, "note": "first topup"},
        headers=headers,
    )
    second = client.post(
        "/v1/wallet/topup",
        json={"immediate_amount": 3_000, "note": "first topup"},
        headers=headers,
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    assert second.json()["detail"] == "idempotency_key_in_use"


def test_topup_rejects_negative_amount(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    r = client.post(
        "/v1/wallet/topup",
        json={"auto_topup_amount": -1},
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# 3. GET /v1/wallet/transactions
# ---------------------------------------------------------------------------


def test_transactions_anonymous_returns_401(
    client: TestClient, wallet_am_db
) -> None:
    r = client.get("/v1/wallet/transactions")
    assert r.status_code == 401, r.text


def test_transactions_filter_and_pagination(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    headers = {"X-API-Key": paid_key}
    # /topup is config-only, so seed ledger rows directly for pagination coverage.
    r = client.get("/v1/wallet/balance", headers=headers)
    assert r.status_code == 200, r.text
    for i, amount in enumerate([1000, 2000, 3000], start=1):
        _seed_wallet_txn(
            wallet_am_db,
            amount_yen=amount,
            txn_type="topup",
            note=f"seed topup #{i}",
            occurred_at=f"2026-05-12T00:00:0{i}.000Z",
        )

    # Unfiltered: 3 rows, newest first.
    r = client.get("/v1/wallet/transactions", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert body["returned"] == 3
    amounts = [t["amount_yen"] for t in body["transactions"]]
    assert amounts == [3000, 2000, 1000]
    assert all(t["txn_type"] == "topup" for t in body["transactions"])

    # Pagination: limit=2, offset=1 → middle + oldest.
    r = client.get(
        "/v1/wallet/transactions?limit=2&offset=1", headers=headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["returned"] == 2
    assert [t["amount_yen"] for t in body["transactions"]] == [2000, 1000]

    # txn_type filter: charge → empty (nothing charged yet).
    r = client.get(
        "/v1/wallet/transactions?txn_type=charge", headers=headers
    )
    assert r.status_code == 200
    assert r.json()["total"] == 0


# ---------------------------------------------------------------------------
# 4. GET /v1/wallet/alerts
# ---------------------------------------------------------------------------


def test_alerts_anonymous_returns_401(client: TestClient, wallet_am_db) -> None:
    r = client.get("/v1/wallet/alerts")
    assert r.status_code == 401, r.text


def test_alerts_empty_when_no_budget(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    r = client.get("/v1/wallet/alerts", headers={"X-API-Key": paid_key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["alerts"] == []
    assert body["thresholds_enum"] == [50, 80, 100]


def test_alerts_billing_cycle_filter_validation(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    # Malformed YYYY-MM → 422 (pattern mismatch).
    r = client.get(
        "/v1/wallet/alerts?billing_cycle=2026", headers={"X-API-Key": paid_key}
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 5. POST /v1/wallet/charge (internal) + alert trigger
# ---------------------------------------------------------------------------


def test_charge_anonymous_returns_401(client: TestClient, wallet_am_db) -> None:
    r = client.post(
        "/v1/wallet/charge",
        json={"amount_yen": 3},
        headers={"X-Internal-Token": "test-internal-token-secret"},
    )
    assert r.status_code == 401, r.text


def test_charge_requires_internal_token(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    r = client.post(
        "/v1/wallet/charge",
        json={"amount_yen": 3},
        headers={"X-API-Key": paid_key},  # no X-Internal-Token
    )
    assert r.status_code == 403, r.text


def test_charge_rejects_wrong_internal_token(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    r = client.post(
        "/v1/wallet/charge",
        json={"amount_yen": 3},
        headers={
            "X-API-Key": paid_key,
            "X-Internal-Token": "wrong-token",
        },
    )
    assert r.status_code == 403


def test_charge_insufficient_balance_returns_402(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    r = client.post(
        "/v1/wallet/charge",
        json={"amount_yen": 100},  # balance=0 → 402
        headers={
            "X-API-Key": paid_key,
            "X-Internal-Token": "test-internal-token-secret",
        },
    )
    assert r.status_code == 402, r.text


def test_charge_idempotency_key_dedupes_body_retry(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    headers = {
        "X-API-Key": paid_key,
        "X-Internal-Token": "test-internal-token-secret",
    }
    r = client.get("/v1/wallet/balance", headers={"X-API-Key": paid_key})
    assert r.status_code == 200, r.text
    _set_wallet_balance(wallet_am_db, 1000)

    payload = {
        "amount_yen": 75,
        "note": "retryable charge",
        "idempotency_key": "wallet-charge-retry-1",
    }
    first = client.post("/v1/wallet/charge", json=payload, headers=headers)
    second = client.post("/v1/wallet/charge", json=payload, headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["balance_yen"] == 925
    assert second.json()["balance_yen"] == 925
    assert second.json()["idempotent_replay"] is True
    assert second.headers["X-Idempotent-Replay"] == "1"

    with sqlite3.connect(wallet_am_db) as conn:
        balance, charges = conn.execute(
            "SELECT w.balance_yen, COUNT(t.txn_id) "
            "FROM am_credit_wallet w "
            "LEFT JOIN am_credit_transaction_log t "
            "  ON t.wallet_id = w.wallet_id AND t.txn_type = 'charge' "
            "GROUP BY w.wallet_id"
        ).fetchone()
    assert balance == 925
    assert charges == 1

    txns = client.get(
        "/v1/wallet/transactions?txn_type=charge",
        headers={"X-API-Key": paid_key},
    )
    assert txns.status_code == 200, txns.text
    assert txns.json()["transactions"][0]["note"] == "retryable charge"
    assert "wallet-idem" not in txns.text


def test_charge_same_idempotency_key_rejects_changed_amount(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    headers = {
        "X-API-Key": paid_key,
        "X-Internal-Token": "test-internal-token-secret",
    }
    r = client.get("/v1/wallet/balance", headers={"X-API-Key": paid_key})
    assert r.status_code == 200, r.text
    _set_wallet_balance(wallet_am_db, 1000)

    first = client.post(
        "/v1/wallet/charge",
        json={"amount_yen": 75, "request_id": "charge-request-1"},
        headers=headers,
    )
    second = client.post(
        "/v1/wallet/charge",
        json={"amount_yen": 76, "request_id": "charge-request-1"},
        headers=headers,
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    assert second.json()["detail"] == "idempotency_key_in_use"

    with sqlite3.connect(wallet_am_db) as conn:
        balance, charges = conn.execute(
            "SELECT w.balance_yen, COUNT(t.txn_id) "
            "FROM am_credit_wallet w "
            "LEFT JOIN am_credit_transaction_log t "
            "  ON t.wallet_id = w.wallet_id AND t.txn_type = 'charge' "
            "GROUP BY w.wallet_id"
        ).fetchone()
    assert balance == 925
    assert charges == 1


def test_charge_concurrent_debits_cannot_overspend(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    headers = {
        "X-API-Key": paid_key,
        "X-Internal-Token": "test-internal-token-secret",
    }
    r = client.get("/v1/wallet/balance", headers={"X-API-Key": paid_key})
    assert r.status_code == 200, r.text
    _set_wallet_balance(wallet_am_db, 100)

    def charge_once() -> int:
        response = client.post(
            "/v1/wallet/charge",
            json={"amount_yen": 75},
            headers=headers,
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(lambda _: charge_once(), range(2)))

    assert statuses == [200, 402]
    with sqlite3.connect(wallet_am_db) as conn:
        balance, charges = conn.execute(
            "SELECT w.balance_yen, COUNT(t.txn_id) "
            "FROM am_credit_wallet w "
            "LEFT JOIN am_credit_transaction_log t "
            "  ON t.wallet_id = w.wallet_id AND t.txn_type = 'charge' "
            "GROUP BY w.wallet_id"
        ).fetchone()
    assert balance == 25
    assert charges == 1


def test_charge_alert_trigger_50_80_100(
    client: TestClient, paid_key: str, wallet_am_db
) -> None:
    """Crossing each threshold fires that alert exactly once per cycle."""
    headers = {"X-API-Key": paid_key}
    internal_headers = {
        "X-API-Key": paid_key,
        "X-Internal-Token": "test-internal-token-secret",
    }

    # Pre-fund 1000 yen + monthly_budget 100 yen → 50 yen = 50%, 80 = 80%, 100 = 100%.
    r = client.post(
        "/v1/wallet/topup",
        json={
            "auto_topup_threshold": 0,
            "auto_topup_amount": 0,
            "monthly_budget_yen": 100,
            "immediate_amount": 1000,
        },
        headers={
            **headers,
            "X-Internal-Token": "test-internal-token-secret",
            "Idempotency-Key": "wallet-alert-prefund",
        },
    )
    assert r.status_code == 200, r.text

    # Charge 50 → spent=50 == 50% → fires 50 alert only.
    r = client.post(
        "/v1/wallet/charge",
        json={"amount_yen": 50, "note": "to 50%"},
        headers=internal_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balance_yen"] == 950
    assert body["alerts_fired"] == [50]

    # Charge 30 → spent=80 == 80% → fires 80 alert only.
    r = client.post(
        "/v1/wallet/charge",
        json={"amount_yen": 30, "note": "to 80%"},
        headers=internal_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balance_yen"] == 920
    assert body["alerts_fired"] == [80]

    # Charge 20 → spent=100 == 100% → fires 100 alert only.
    r = client.post(
        "/v1/wallet/charge",
        json={"amount_yen": 20, "note": "to 100%"},
        headers=internal_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balance_yen"] == 900
    assert body["alerts_fired"] == [100]

    # Charge 10 more → no new alert (idempotent UNIQUE constraint).
    r = client.post(
        "/v1/wallet/charge",
        json={"amount_yen": 10, "note": "past 100%"},
        headers=internal_headers,
    )
    assert r.status_code == 200
    assert r.json()["alerts_fired"] == []

    # Verify alerts ledger has exactly 3 rows for this cycle.
    r = client.get("/v1/wallet/alerts", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["returned"] == 3
    thresholds = sorted(a["threshold_pct"] for a in body["alerts"])
    assert thresholds == [50, 80, 100]

    # Verify charge txns recorded with negative amount_yen.
    r = client.get("/v1/wallet/transactions?txn_type=charge", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert all(t["amount_yen"] < 0 for t in body["transactions"])


# ---------------------------------------------------------------------------
# 6. LLM-0 verify — credit_wallet.py imports no LLM SDK.
# ---------------------------------------------------------------------------


def test_credit_wallet_module_imports_no_llm_sdk() -> None:
    src = CREDIT_WALLET_PY.read_text(encoding="utf-8")
    forbidden = (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
        "import cohere",
        "from cohere",
    )
    for needle in forbidden:
        assert needle not in src, f"forbidden LLM SDK import found: {needle}"

    # Sanity: module is importable.
    spec = importlib.util.spec_from_file_location(
        "_w48_credit_wallet_probe", str(CREDIT_WALLET_PY)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "router")
    routes = [r.path for r in module.router.routes]
    assert "/v1/wallet/balance" in routes
    assert "/v1/wallet/topup" in routes
    assert "/v1/wallet/transactions" in routes
    assert "/v1/wallet/alerts" in routes
    assert "/v1/wallet/charge" in routes


def test_wallet_charge_not_in_public_openapi(client: TestClient, wallet_am_db) -> None:
    schema = client.app.openapi()
    assert "/v1/wallet/charge" not in schema["paths"]
