"""Tests for POST /v1/privacy/deletion_request.

The endpoint is anonymous-accessible and symmetrical to §31 disclosure
(see test_appi_disclosure.py). Coverage:

  1. Initial deletion request: row written with the JSON-encoded category
     list, response carries request_id (削除- prefix) + 30d SLA + contact,
     email side-effect fires exactly once.
  2. Invalid category enum -> 422: a category outside the closed enum
     fails Pydantic validation, no row is written, no email is fired.
  3. Duplicate request: same email + houjin twice -> both accepted,
     distinct request_ids, both rows persisted, both emails fired.

Email layer is stubbed via a monkeypatched
`_notify_operator_and_requester` recorder so we don't reach Postmark.
"""
from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path  # noqa: F401  (kept for parallel structure with test_appi_disclosure.py)


@pytest.fixture()
def email_recorder(monkeypatch):
    """Capture every operator/requester notification fired by the endpoint."""
    captured: list[dict] = []

    def _fake_notify(**kwargs) -> None:
        captured.append(kwargs)

    from jpintel_mcp.api import appi_deletion as mod

    monkeypatch.setattr(mod, "_notify_operator_and_requester", _fake_notify)
    return captured


@pytest.fixture(autouse=True)
def _clear_appi_rows(seeded_db):
    """Each test starts with an empty intake table so duplicate-detection
    assertions don't bleed between cases."""
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM appi_deletion_requests")
        c.commit()
    finally:
        c.close()
    yield


def test_appi_deletion_initial_request(client, seeded_db, email_recorder):
    body = {
        "requester_email": "yamada@example.com",
        "requester_legal_name": "山田 太郎",
        "target_houjin_bangou": "8010001213708",
        "target_data_categories": ["representative", "address", "phone"],
        "identity_verification_method": "drivers_license",
        "deletion_reason": "個人事業主であり代表者氏名・所在地が自宅である",
    }
    r = client.post("/v1/privacy/deletion_request", json=body)
    assert r.status_code == 201, r.text

    payload = r.json()
    # 削除- prefix + 32 hex chars.
    assert payload["request_id"].startswith("削除-")
    assert len(payload["request_id"]) == len("削除-") + 32
    assert payload["expected_response_within_days"] == 30
    assert payload["contact"] == "info@bookyou.net"
    assert isinstance(payload["received_at"], str)
    # ISO-8601 UTC timestamp ends with the UTC offset.
    assert payload["received_at"].endswith("+00:00")

    # Row landed with JSON-encoded categories list.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT request_id, requester_email, requester_legal_name, "
            "target_houjin_bangou, target_data_categories, "
            "identity_verification_method, deletion_reason, status "
            "FROM appi_deletion_requests"
        ).fetchall()
    finally:
        c.close()
    assert len(rows) == 1
    row = rows[0]
    assert row["request_id"] == payload["request_id"]
    assert row["requester_email"] == "yamada@example.com"
    assert row["requester_legal_name"] == "山田 太郎"
    assert row["target_houjin_bangou"] == "8010001213708"
    assert json.loads(row["target_data_categories"]) == [
        "representative",
        "address",
        "phone",
    ]
    assert row["identity_verification_method"] == "drivers_license"
    assert row["deletion_reason"] == "個人事業主であり代表者氏名・所在地が自宅である"
    assert row["status"] == "pending"

    # Email side-effect fired exactly once with the right shape.
    assert len(email_recorder) == 1
    sent = email_recorder[0]
    assert sent["request_id"] == payload["request_id"]
    assert sent["requester_email"] == "yamada@example.com"
    assert sent["requester_legal_name"] == "山田 太郎"
    assert sent["target_houjin_bangou"] == "8010001213708"
    assert sent["target_data_categories"] == ["representative", "address", "phone"]
    assert sent["identity_verification_method"] == "drivers_license"
    assert sent["deletion_reason"] == "個人事業主であり代表者氏名・所在地が自宅である"


def test_appi_deletion_invalid_category_returns_422(client, seeded_db, email_recorder):
    """Closed enum: any string outside the canonical list is rejected by
    Pydantic before the handler runs, no row written, no email fired.

    The closed enum is the load-bearing safety property — if a typo lands
    in the DB the operator could mis-scope the manual deletion.
    """
    body = {
        "requester_email": "yamada@example.com",
        "requester_legal_name": "山田 太郎",
        "target_houjin_bangou": "8010001213708",
        # 'phone_number' is NOT a valid category (the canonical name is 'phone').
        "target_data_categories": ["representative", "phone_number"],
        "identity_verification_method": "drivers_license",
    }
    r = client.post("/v1/privacy/deletion_request", json=body)
    assert r.status_code == 422, r.text

    # No row landed.
    c = sqlite3.connect(seeded_db)
    try:
        n = c.execute("SELECT COUNT(*) FROM appi_deletion_requests").fetchone()[0]
    finally:
        c.close()
    assert n == 0

    # No email fired.
    assert email_recorder == []


def test_appi_deletion_duplicate_request_accepted(client, seeded_db, email_recorder):
    """Same email + houjin twice -> both accepted, distinct request_ids,
    both rows persisted, both emails fired.

    APPI §33 doesn't bound the number of requests — a data subject who
    didn't receive the first acknowledgement must be able to resubmit.
    Operator dedupes during manual review.
    """
    body = {
        "requester_email": "yamada@example.com",
        "requester_legal_name": "山田 太郎",
        "target_houjin_bangou": "8010001213708",
        "target_data_categories": ["all_personal_data"],
        "identity_verification_method": "my_number_card",
    }
    r1 = client.post("/v1/privacy/deletion_request", json=body)
    assert r1.status_code == 201, r1.text
    r2 = client.post("/v1/privacy/deletion_request", json=body)
    assert r2.status_code == 201, r2.text

    rid1 = r1.json()["request_id"]
    rid2 = r2.json()["request_id"]
    assert rid1 != rid2

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT request_id FROM appi_deletion_requests ORDER BY received_at"
        ).fetchall()
    finally:
        c.close()
    assert {row["request_id"] for row in rows} == {rid1, rid2}

    # Both emails fired (one per request).
    assert len(email_recorder) == 2
    assert {sent["request_id"] for sent in email_recorder} == {rid1, rid2}
