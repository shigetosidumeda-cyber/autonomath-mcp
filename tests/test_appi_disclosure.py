"""Tests for POST /v1/privacy/disclosure_request.

The endpoint is anonymous-accessible. Coverage:

  1. Initial request: row written, response carries request_id + 14d SLA +
     contact, and the email side-effect fires exactly once.
  2. Duplicate request from the same email/houjin: accepted, fresh
     request_id, second row landed, second email fired. Duplicates are
     legitimate (the requester didn't get the first ack and resubmits).

Email layer is stubbed via a monkeypatched `_notify_operator_and_requester`
recorder so we don't reach Postmark; the postmark client itself is also
covered separately in test_email.py.
"""
from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture()
def email_recorder(monkeypatch):
    """Capture every operator/requester notification fired by the endpoint.

    We replace `_notify_operator_and_requester` (not the underlying
    PostmarkClient) so the test asserts on the call shape the endpoint
    promises, regardless of how the email layer happens to dispatch.
    """
    captured: list[dict] = []

    def _fake_notify(**kwargs) -> None:
        captured.append(kwargs)

    from jpintel_mcp.api import appi_disclosure as mod

    monkeypatch.setattr(mod, "_notify_operator_and_requester", _fake_notify)
    return captured


@pytest.fixture(autouse=True)
def _clear_appi_rows(seeded_db):
    """Each test starts with an empty intake table so duplicate-detection
    assertions don't bleed between cases."""
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM appi_disclosure_requests")
        c.commit()
    finally:
        c.close()
    yield


def test_appi_disclosure_initial_request(client, seeded_db, email_recorder):
    body = {
        "requester_email": "yamada@example.com",
        "requester_legal_name": "山田 太郎",
        "target_houjin_bangou": "8010001213708",
        "identity_verification_method": "drivers_license",
    }
    r = client.post("/v1/privacy/disclosure_request", json=body)
    assert r.status_code == 201, r.text

    payload = r.json()
    assert payload["request_id"].startswith("appi-")
    assert len(payload["request_id"]) == len("appi-") + 32
    assert payload["expected_response_within_days"] == 14
    assert payload["contact"] == "info@bookyou.net"
    assert isinstance(payload["received_at"], str)
    # ISO-8601 UTC timestamp ends with the UTC offset.
    assert payload["received_at"].endswith("+00:00")

    # Row landed.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT request_id, requester_email, requester_legal_name, "
            "target_houjin_bangou, identity_verification_method, status "
            "FROM appi_disclosure_requests"
        ).fetchall()
    finally:
        c.close()
    assert len(rows) == 1
    row = rows[0]
    assert row["request_id"] == payload["request_id"]
    assert row["requester_email"] == "yamada@example.com"
    assert row["requester_legal_name"] == "山田 太郎"
    assert row["target_houjin_bangou"] == "8010001213708"
    assert row["identity_verification_method"] == "drivers_license"
    assert row["status"] == "pending"

    # Email side-effect fired exactly once with the right shape.
    assert len(email_recorder) == 1
    sent = email_recorder[0]
    assert sent["request_id"] == payload["request_id"]
    assert sent["requester_email"] == "yamada@example.com"
    assert sent["requester_legal_name"] == "山田 太郎"
    assert sent["target_houjin_bangou"] == "8010001213708"
    assert sent["identity_verification_method"] == "drivers_license"


def test_appi_disclosure_duplicate_request_accepted(client, seeded_db, email_recorder):
    """Same email + houjin twice → both accepted, distinct request_ids,
    both rows persisted, both emails fired.

    APPI §31 doesn't bound the number of requests — a data subject who did
    not receive the first acknowledgement must be able to resubmit.
    Operator dedupes during manual review.
    """
    body = {
        "requester_email": "yamada@example.com",
        "requester_legal_name": "山田 太郎",
        "target_houjin_bangou": "8010001213708",
        "identity_verification_method": "my_number_card",
    }
    r1 = client.post("/v1/privacy/disclosure_request", json=body)
    assert r1.status_code == 201, r1.text
    r2 = client.post("/v1/privacy/disclosure_request", json=body)
    assert r2.status_code == 201, r2.text

    rid1 = r1.json()["request_id"]
    rid2 = r2.json()["request_id"]
    assert rid1 != rid2

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT request_id FROM appi_disclosure_requests ORDER BY received_at"
        ).fetchall()
    finally:
        c.close()
    assert {row["request_id"] for row in rows} == {rid1, rid2}

    # Both emails fired (one per request).
    assert len(email_recorder) == 2
    assert {sent["request_id"] for sent in email_recorder} == {rid1, rid2}
