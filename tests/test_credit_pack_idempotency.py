"""Strict idempotency tests for the Stripe credit-pack grant path (DD-04 P0).

Background
----------
The legacy `am_credit_pack_purchase` (migration wave24_148, target_db autonomath)
tracks the local lifecycle of credit-pack purchases — `pending → paid`. The
webhook handler at `src/jpintel_mcp/api/billing.py:1297-1354` dispatches
`invoice.paid` events whose `metadata.kind == "credit_pack"` to
`apply_credit_pack`, which calls Stripe's NON-idempotent
`Customer.create_balance_transaction`. The legacy guard (SELECT-then-INSERT
keyed on `stripe_invoice_id`) leaves a race window:

    Worker A                       Worker B
    --------                       --------
    SELECT … WHERE invoice=I       …
    row.status='pending'           SELECT … WHERE invoice=I
                                   row.status='pending'
    apply_credit_pack(...)         …
                                   apply_credit_pack(...)   ← double grant!
    INSERT/UPSERT status='paid'    INSERT/UPSERT status='paid'

DD-04 closes this with a dedicated `credit_pack_reservation` table whose
PRIMARY KEY is `f"credit_pack:{stripe_invoice_id}"` (or `payment_intent_id`).
The atomic INSERT-OR-IGNORE on that key is the dedup point — only the worker
whose INSERT actually inserted (rowcount==1) calls Stripe; everyone else
returns a 200 idempotent response.

Test surface
------------
1. test_grant_succeeds_first_time
2. test_replay_does_not_double_grant
3. test_concurrent_grants_serialized
4. test_failed_grant_can_retry
5. test_different_invoice_ids_grant_separately

The test fixtures bind `JPINTEL_DB_PATH` (the conventional jpintel db env var
used by `db.session.connect`) to a per-test temp file and run the migration
SQL inline (no migrate.py — the file is target_db: jpintel and the production
deploy applies it manually per CLAUDE.md gotcha). `AUTONOMATH_DB_PATH` is also
bound to the same temp file because `_credit_pack_db_path()` reads
`AUTONOMATH_DB_PATH` and the existing `am_credit_pack_purchase` table is
auto-created on first open.

Stripe is monkeypatched throughout. No live network IO.
"""

from __future__ import annotations

import contextlib
import sqlite3
import tempfile
import threading
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Migration SQL applied inline (test isolation; production applies via the
# operator-run sqlite3 redirect documented in CLAUDE.md / DD-04 spec).
# ---------------------------------------------------------------------------

CREDIT_PACK_RESERVATION_SQL = """
CREATE TABLE IF NOT EXISTS credit_pack_reservation (
    idempotency_key TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL,
    pack_size       INTEGER NOT NULL CHECK (pack_size IN (300000, 1000000, 3000000)),
    status          TEXT NOT NULL CHECK (status IN ('reserved', 'granted', 'failed')),
    reserved_at     TEXT NOT NULL DEFAULT (datetime('now')),
    granted_at      TEXT,
    stripe_balance_txn_id TEXT,
    error_reason    TEXT
);
CREATE INDEX IF NOT EXISTS idx_credit_pack_reservation_customer_status
    ON credit_pack_reservation(customer_id, status);
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_db_path(monkeypatch) -> Path:
    """Per-test SQLite file with the credit_pack_reservation schema applied."""
    with tempfile.NamedTemporaryFile(
        prefix="jpintel-credit-pack-idem-",
        suffix=".db",
        delete=False,
    ) as tmp:
        path = Path(tmp.name)

    # Apply migration 166.
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(CREDIT_PACK_RESERVATION_SQL)
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(path))
    monkeypatch.setenv("JPINTEL_DB_PATH", str(path))
    yield path
    for ext in ("", "-wal", "-shm"):
        target = Path(str(path) + ext)
        if target.exists():
            with contextlib.suppress(OSError):
                target.unlink()


@pytest.fixture()
def grant_calls():
    """Counts and arguments of `apply_credit_pack` invocations across a test."""
    return {"count": 0, "calls": []}


# ---------------------------------------------------------------------------
# The function under test (placeholder import — DD-04 will land it in
# src/jpintel_mcp/billing/credit_pack.py as `grant_credit_pack_idempotent`).
# Until the implementation lands, the test imports will skip cleanly so this
# file documents the contract without breaking the suite.
# ---------------------------------------------------------------------------


def _try_import_grant():
    try:
        from jpintel_mcp.billing.credit_pack import grant_credit_pack_idempotent

        return grant_credit_pack_idempotent
    except ImportError:
        return None


pytestmark = pytest.mark.skipif(
    _try_import_grant() is None,
    reason="grant_credit_pack_idempotent not yet implemented (DD-04)",
)


# ---------------------------------------------------------------------------
# 1. test_grant_succeeds_first_time
# ---------------------------------------------------------------------------


def test_grant_succeeds_first_time(temp_db_path, grant_calls, monkeypatch):
    """First webhook delivery for a new invoice_id grants exactly once.

    The reservation row transitions reserved → granted, the Stripe
    balance-transaction call fires exactly once with the right amount, and the
    function returns a status indicating "fresh grant".
    """
    grant = _try_import_grant()

    def _fake_apply(stripe_client, customer_id, amount_jpy, *, idempotency_key=None):
        grant_calls["count"] += 1
        grant_calls["calls"].append((customer_id, amount_jpy, idempotency_key))
        return {"id": "cbtxn_first_time", "amount": -amount_jpy, "currency": "jpy"}

    monkeypatch.setattr("jpintel_mcp.billing.credit_pack.apply_credit_pack", _fake_apply)

    result = grant(
        stripe_client=None,
        stripe_invoice_id="in_first_time",
        customer_id="cus_first",
        pack_size=300_000,
    )

    assert result["status"] == "granted"
    assert result["fresh"] is True
    assert grant_calls["count"] == 1
    assert grant_calls["calls"][0] == (
        "cus_first",
        300_000,
        "credit_pack:in_first_time",
    )

    conn = sqlite3.connect(str(temp_db_path))
    try:
        row = conn.execute(
            "SELECT idempotency_key, customer_id, pack_size, status, granted_at, "
            "stripe_balance_txn_id "
            "FROM credit_pack_reservation WHERE idempotency_key=?",
            ("credit_pack:in_first_time",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "credit_pack:in_first_time"
    assert row[1] == "cus_first"
    assert row[2] == 300_000
    assert row[3] == "granted"
    assert row[4] is not None  # granted_at populated
    assert row[5] == "cbtxn_first_time"


# ---------------------------------------------------------------------------
# 2. test_replay_does_not_double_grant
# ---------------------------------------------------------------------------


def test_replay_does_not_double_grant(temp_db_path, grant_calls, monkeypatch):
    """Same invoice_id delivered twice → Stripe call fires exactly once."""
    grant = _try_import_grant()

    def _fake_apply(stripe_client, customer_id, amount_jpy, *, idempotency_key=None):
        grant_calls["count"] += 1
        grant_calls["calls"].append((customer_id, amount_jpy, idempotency_key))
        return {"id": "cbtxn_replay", "amount": -amount_jpy, "currency": "jpy"}

    monkeypatch.setattr("jpintel_mcp.billing.credit_pack.apply_credit_pack", _fake_apply)

    # Delivery 1 — first webhook attempt.
    r1 = grant(
        stripe_client=None,
        stripe_invoice_id="in_replay",
        customer_id="cus_replay",
        pack_size=1_000_000,
    )
    assert r1["status"] == "granted"
    assert r1["fresh"] is True

    # Delivery 2 — Stripe redelivery (network blip / 5xx retry).
    r2 = grant(
        stripe_client=None,
        stripe_invoice_id="in_replay",
        customer_id="cus_replay",
        pack_size=1_000_000,
    )
    assert r2["status"] == "granted"
    assert r2["fresh"] is False  # already-granted short-circuit
    assert r2["stripe_balance_txn_id"] == "cbtxn_replay"

    # Stripe was called exactly once across both deliveries.
    assert grant_calls["count"] == 1

    # Exactly one row exists in the reservation table.
    conn = sqlite3.connect(str(temp_db_path))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM credit_pack_reservation WHERE idempotency_key=?",
            ("credit_pack:in_replay",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


# ---------------------------------------------------------------------------
# 3. test_concurrent_grants_serialized
# ---------------------------------------------------------------------------


def test_concurrent_grants_serialized(temp_db_path, monkeypatch):
    """5 parallel deliveries for the same invoice_id → exactly 1 grant fires.

    This is the canonical DD-04 P0: SQLite's writer lock + the PRIMARY KEY
    UNIQUE constraint on `idempotency_key` are what serialize the workers,
    not application-level mutexes. The test simulates Stripe at-least-once
    delivery where multiple webhook processes are racing on the same key.
    """
    grant = _try_import_grant()
    grant_lock = threading.Lock()
    fired = {"count": 0}

    def _fake_apply(stripe_client, customer_id, amount_jpy, *, idempotency_key=None):
        with grant_lock:
            fired["count"] += 1
        return {
            "id": f"cbtxn_concurrent_{fired['count']}",
            "amount": -amount_jpy,
            "currency": "jpy",
        }

    monkeypatch.setattr("jpintel_mcp.billing.credit_pack.apply_credit_pack", _fake_apply)

    barrier = threading.Barrier(5)
    results: list[dict] = []
    errors: list[BaseException] = []

    def _worker():
        try:
            barrier.wait(timeout=2.0)
            r = grant(
                stripe_client=None,
                stripe_invoice_id="in_concurrent",
                customer_id="cus_concurrent",
                pack_size=3_000_000,
            )
            results.append(r)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=_worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert not errors, f"workers raised: {errors!r}"
    assert len(results) == 5

    # Exactly one fresh=True (the worker that won the INSERT race).
    fresh_count = sum(1 for r in results if r.get("fresh"))
    assert fresh_count == 1, f"expected 1 fresh grant, got {fresh_count}: {results!r}"

    # Stripe called at most once. (Could be exactly 1 if the winning worker
    # finished apply_credit_pack before the others' SELECT-status ran; could
    # be 1 if losers see status='reserved' and idempotently wait/return.)
    assert fired["count"] == 1, f"Stripe fired {fired['count']} times, expected 1"

    # Exactly one row in the reservation table.
    conn = sqlite3.connect(str(temp_db_path))
    try:
        rows = conn.execute(
            "SELECT idempotency_key, status FROM credit_pack_reservation WHERE idempotency_key=?",
            ("credit_pack:in_concurrent",),
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0][1] == "granted"


# ---------------------------------------------------------------------------
# 4. test_failed_grant_can_retry
# ---------------------------------------------------------------------------


def test_failed_grant_can_retry(temp_db_path, grant_calls, monkeypatch):
    """A row in status='failed' (Stripe raised earlier) is upgradable on retry.

    The first webhook attempt seats a 'reserved' row, calls Stripe, the call
    raises, and the handler updates the row to 'failed' with `error_reason`.
    The next webhook retry sees status='failed', re-attempts the Stripe call,
    succeeds, and the row transitions failed → granted (NOT a fresh insert,
    so the legacy `stripe_invoice_id` UNIQUE on `am_credit_pack_purchase` is
    untouched).
    """
    grant = _try_import_grant()

    # First call raises — simulate Stripe API unavailability.
    raise_count = {"n": 0}

    def _flaky_apply(stripe_client, customer_id, amount_jpy, *, idempotency_key=None):
        if raise_count["n"] == 0:
            raise_count["n"] += 1
            raise RuntimeError("Stripe 503 — transient")
        grant_calls["count"] += 1
        grant_calls["calls"].append((customer_id, amount_jpy, idempotency_key))
        return {"id": "cbtxn_retry", "amount": -amount_jpy, "currency": "jpy"}

    monkeypatch.setattr("jpintel_mcp.billing.credit_pack.apply_credit_pack", _flaky_apply)

    # Attempt 1 — Stripe raises; row should land as 'failed'.
    with pytest.raises(RuntimeError):
        grant(
            stripe_client=None,
            stripe_invoice_id="in_retry",
            customer_id="cus_retry",
            pack_size=300_000,
        )

    conn = sqlite3.connect(str(temp_db_path))
    try:
        row = conn.execute(
            "SELECT status, error_reason FROM credit_pack_reservation WHERE idempotency_key=?",
            ("credit_pack:in_retry",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "failed"
    assert row[1] is not None
    assert "503" in row[1] or "transient" in row[1].lower()

    # Attempt 2 — Stripe succeeds; row should upgrade to 'granted'.
    r2 = grant(
        stripe_client=None,
        stripe_invoice_id="in_retry",
        customer_id="cus_retry",
        pack_size=300_000,
    )
    assert r2["status"] == "granted"
    assert r2["fresh"] is True  # the actual Stripe call did happen this time
    assert grant_calls["count"] == 1

    conn = sqlite3.connect(str(temp_db_path))
    try:
        row = conn.execute(
            "SELECT status, granted_at, error_reason FROM credit_pack_reservation "
            "WHERE idempotency_key=?",
            ("credit_pack:in_retry",),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "granted"
    assert row[1] is not None
    # error_reason MAY be cleared or preserved — implementation choice; we
    # don't assert.


# ---------------------------------------------------------------------------
# 5. test_different_invoice_ids_grant_separately
# ---------------------------------------------------------------------------


def test_different_invoice_ids_grant_separately(temp_db_path, grant_calls, monkeypatch):
    """Two distinct invoice_ids → two grants. Idempotency is per-key, not global."""
    grant = _try_import_grant()

    def _fake_apply(stripe_client, customer_id, amount_jpy, *, idempotency_key=None):
        grant_calls["count"] += 1
        grant_calls["calls"].append((customer_id, amount_jpy, idempotency_key))
        return {
            "id": f"cbtxn_separate_{grant_calls['count']}",
            "amount": -amount_jpy,
            "currency": "jpy",
        }

    monkeypatch.setattr("jpintel_mcp.billing.credit_pack.apply_credit_pack", _fake_apply)

    r1 = grant(
        stripe_client=None,
        stripe_invoice_id="in_first_invoice",
        customer_id="cus_separate",
        pack_size=300_000,
    )
    r2 = grant(
        stripe_client=None,
        stripe_invoice_id="in_second_invoice",
        customer_id="cus_separate",
        pack_size=1_000_000,
    )

    assert r1["status"] == "granted"
    assert r1["fresh"] is True
    assert r2["status"] == "granted"
    assert r2["fresh"] is True

    # Two distinct grants fired.
    assert grant_calls["count"] == 2
    assert grant_calls["calls"] == [
        ("cus_separate", 300_000, "credit_pack:in_first_invoice"),
        ("cus_separate", 1_000_000, "credit_pack:in_second_invoice"),
    ]

    # Two distinct reservation rows.
    conn = sqlite3.connect(str(temp_db_path))
    try:
        rows = conn.execute(
            "SELECT idempotency_key, pack_size, status FROM credit_pack_reservation "
            "WHERE customer_id=? ORDER BY pack_size",
            ("cus_separate",),
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 2
    assert rows[0][0] == "credit_pack:in_first_invoice"
    assert rows[0][1] == 300_000
    assert rows[0][2] == "granted"
    assert rows[1][0] == "credit_pack:in_second_invoice"
    assert rows[1][1] == 1_000_000
    assert rows[1][2] == "granted"


# ---------------------------------------------------------------------------
# 6. test_payment_intent_id_alternative_key (covers the non-invoice path)
# ---------------------------------------------------------------------------


def test_payment_intent_id_used_when_invoice_id_missing(temp_db_path, grant_calls, monkeypatch):
    """Some Stripe events route via PaymentIntent rather than Invoice.

    The DD-04 contract: prefer `stripe_invoice_id` when present, else fall
    back to `payment_intent_id`. The idempotency key prefix differs:
        f"credit_pack:{stripe_invoice_id}"     OR
        f"credit_pack:{payment_intent_id}"
    Either form must serve as a valid PRIMARY KEY in
    `credit_pack_reservation`.
    """
    grant = _try_import_grant()

    def _fake_apply(stripe_client, customer_id, amount_jpy, *, idempotency_key=None):
        grant_calls["count"] += 1
        return {"id": "cbtxn_pi", "amount": -amount_jpy, "currency": "jpy"}

    monkeypatch.setattr("jpintel_mcp.billing.credit_pack.apply_credit_pack", _fake_apply)

    r = grant(
        stripe_client=None,
        stripe_invoice_id=None,
        payment_intent_id="pi_test_1",
        customer_id="cus_pi",
        pack_size=300_000,
    )
    assert r["status"] == "granted"
    assert r["fresh"] is True
    assert grant_calls["count"] == 1

    conn = sqlite3.connect(str(temp_db_path))
    try:
        row = conn.execute(
            "SELECT idempotency_key FROM credit_pack_reservation WHERE customer_id=?",
            ("cus_pi",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "credit_pack:pi_test_1"


def test_fresh_reserved_replay_returns_inflight_without_second_grant(
    temp_db_path, grant_calls, monkeypatch
):
    """Immediate duplicate while the first worker is mid-flight is a 200 no-op."""
    grant = _try_import_grant()
    conn = sqlite3.connect(str(temp_db_path))
    try:
        conn.execute(
            "INSERT INTO credit_pack_reservation "
            "(idempotency_key, customer_id, pack_size, status, reserved_at) "
            "VALUES (?, ?, ?, 'reserved', datetime('now'))",
            ("credit_pack:in_midflight", "cus_midflight", 300_000),
        )
        conn.commit()
    finally:
        conn.close()

    def _should_not_apply(stripe_client, customer_id, amount_jpy, *, idempotency_key=None):
        grant_calls["count"] += 1
        raise AssertionError("fresh reserved rows must not call Stripe again")

    monkeypatch.setattr("jpintel_mcp.billing.credit_pack.apply_credit_pack", _should_not_apply)

    result = grant(
        stripe_client=None,
        stripe_invoice_id="in_midflight",
        customer_id="cus_midflight",
        pack_size=300_000,
        reserved_retry_after_seconds=300,
        reserved_operator_review_seconds=23 * 60 * 60,
    )

    assert result["status"] == "reserved"
    assert result["fresh"] is False
    assert result["stripe_balance_txn_id"] is None
    assert grant_calls["count"] == 0


def test_stale_reserved_retries_with_same_stripe_idempotency_key(
    temp_db_path, grant_calls, monkeypatch
):
    """Crash after local reservation but before DB grant update can be retried."""
    grant = _try_import_grant()
    conn = sqlite3.connect(str(temp_db_path))
    try:
        conn.execute(
            "INSERT INTO credit_pack_reservation "
            "(idempotency_key, customer_id, pack_size, status, reserved_at) "
            "VALUES (?, ?, ?, 'reserved', datetime('now', '-10 minutes'))",
            ("credit_pack:in_stale_retry", "cus_stale_retry", 1_000_000),
        )
        conn.commit()
    finally:
        conn.close()

    def _fake_apply(stripe_client, customer_id, amount_jpy, *, idempotency_key=None):
        grant_calls["count"] += 1
        grant_calls["calls"].append((customer_id, amount_jpy, idempotency_key))
        return {"id": "cbtxn_stale_retry", "amount": -amount_jpy, "currency": "jpy"}

    monkeypatch.setattr("jpintel_mcp.billing.credit_pack.apply_credit_pack", _fake_apply)

    result = grant(
        stripe_client=None,
        stripe_invoice_id="in_stale_retry",
        customer_id="cus_stale_retry",
        pack_size=1_000_000,
        reserved_retry_after_seconds=60,
        reserved_operator_review_seconds=23 * 60 * 60,
    )

    assert result["status"] == "granted"
    assert result["fresh"] is True
    assert result["stripe_balance_txn_id"] == "cbtxn_stale_retry"
    assert grant_calls["calls"] == [("cus_stale_retry", 1_000_000, "credit_pack:in_stale_retry")]

    conn = sqlite3.connect(str(temp_db_path))
    try:
        row = conn.execute(
            "SELECT status, stripe_balance_txn_id, error_reason "
            "FROM credit_pack_reservation WHERE idempotency_key=?",
            ("credit_pack:in_stale_retry",),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "granted"
    assert row[1] == "cbtxn_stale_retry"
    assert row[2] is None


def test_very_stale_reserved_requires_operator_review(temp_db_path, grant_calls, monkeypatch):
    """Do not reuse a Stripe idempotency key after its safe cache horizon."""
    grant = _try_import_grant()
    conn = sqlite3.connect(str(temp_db_path))
    try:
        conn.execute(
            "INSERT INTO credit_pack_reservation "
            "(idempotency_key, customer_id, pack_size, status, reserved_at) "
            "VALUES (?, ?, ?, 'reserved', datetime('now', '-2 days'))",
            ("credit_pack:in_operator_review", "cus_operator_review", 3_000_000),
        )
        conn.commit()
    finally:
        conn.close()

    def _should_not_apply(stripe_client, customer_id, amount_jpy, *, idempotency_key=None):
        grant_calls["count"] += 1
        raise AssertionError("operator-review rows must not call Stripe")

    monkeypatch.setattr("jpintel_mcp.billing.credit_pack.apply_credit_pack", _should_not_apply)

    result = grant(
        stripe_client=None,
        stripe_invoice_id="in_operator_review",
        customer_id="cus_operator_review",
        pack_size=3_000_000,
        reserved_retry_after_seconds=60,
        reserved_operator_review_seconds=23 * 60 * 60,
    )

    assert result["status"] == "reserved_operator_review"
    assert result["fresh"] is False
    assert result["stripe_balance_txn_id"] is None
    assert grant_calls["count"] == 0


def test_existing_key_with_different_pack_raises(temp_db_path, monkeypatch):
    """An idempotency key cannot be reused for different grant parameters."""
    grant = _try_import_grant()
    conn = sqlite3.connect(str(temp_db_path))
    try:
        conn.execute(
            "INSERT INTO credit_pack_reservation "
            "(idempotency_key, customer_id, pack_size, status, reserved_at) "
            "VALUES (?, ?, ?, 'reserved', datetime('now'))",
            ("credit_pack:in_collision", "cus_collision", 300_000),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="key collision"):
        grant(
            stripe_client=None,
            stripe_invoice_id="in_collision",
            customer_id="cus_collision",
            pack_size=1_000_000,
        )
