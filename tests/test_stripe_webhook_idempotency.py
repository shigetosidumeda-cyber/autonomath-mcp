"""Stripe webhook idempotency test."""
# ruff: noqa: N803,N806,SIM115,SIM117,BLE001,E501,F401,F841,PTH123,S301,S314,S603,UP017


import sqlite3

from jpintel_mcp.api.billing_webhook_idempotency import (
    already_processed,
    mark_failure,
    mark_success,
    record_received,
)


def _setup(conn: sqlite3.Connection) -> None:
    conn.executescript(open("scripts/migrations/205_stripe_event_idempotency.sql").read())


def test_idempotency_lifecycle() -> None:
    conn = sqlite3.connect(":memory:")
    _setup(conn)
    assert already_processed(conn, "evt_test_1") is False
    record_received(conn, "evt_test_1", "checkout.session.completed", "cus_xxx")
    assert already_processed(conn, "evt_test_1") is False
    mark_success(conn, "evt_test_1", api_key_id="ak_abc")
    assert already_processed(conn, "evt_test_1") is True
    # duplicate received → not re-processed
    record_received(conn, "evt_test_1", "checkout.session.completed", "cus_xxx")
    row = conn.execute(
        "SELECT processing_outcome, api_key_id_minted FROM stripe_event_idempotency WHERE event_id=?",
        ("evt_test_1",),
    ).fetchone()
    assert row[0] == "success" and row[1] == "ak_abc"


def test_failure_then_retry() -> None:
    conn = sqlite3.connect(":memory:")
    _setup(conn)
    record_received(conn, "evt_test_2", "invoice.payment_failed")
    mark_failure(conn, "evt_test_2", "stripe timeout", permanent=False)
    row = conn.execute(
        "SELECT processing_outcome FROM stripe_event_idempotency WHERE event_id=?", ("evt_test_2",)
    ).fetchone()
    assert row[0] == "retry"
    # subsequent success
    mark_success(conn, "evt_test_2")
    assert already_processed(conn, "evt_test_2") is True
