"""Webhook delivery idempotency-header tests for `scripts/cron/dispatch_webhooks.py`.

These tests assert that customer webhook deliveries carry an
`Idempotency-Key` HTTP header so subscribers can dedupe retries on their
own side. The dispatcher uses an exponential retry schedule (60s / 300s /
1800s) and on 5xx / timeout will re-POST the same (event_type, event_id)
to the customer URL. Without a stable per-event header the customer
cannot tell a retry from a fresh event of the same shape — they have to
fall back to deep payload diffing.

Contract (Stripe / x402 / industry-standard webhook delivery):
  1. The 1st POST for an event carries some Idempotency-Key value X.
  2. Any retry of the SAME event_id carries the EXACT SAME X.
  3. A POST for a DIFFERENT event_id carries a DIFFERENT key Y != X.

Construction expectation: the dispatcher hashes ``event_type:event_id`` so
the header is stable across retries and opaque to downstream logs. The JSON
payload also carries ``event_id`` for subscribers that dedupe from the body.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from pathlib import Path

import pytest

from jpintel_mcp.billing.keys import issue_key

# ---------------------------------------------------------------------------
# Fixtures (mirrors test_dispatch_webhooks.py so we share the seeded_db
# migration pattern and the (paid) api_key issuance flow).
# ---------------------------------------------------------------------------


@pytest.fixture()
def idem_key(seeded_db: Path) -> str:
    """Authenticated paid key for the idempotency-header tests."""
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_idem_test",
        tier="paid",
        stripe_subscription_id="sub_idem_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _ensure_webhook_table(seeded_db: Path):
    """Apply migration 080 (customer_webhooks + webhook_deliveries) to the
    test DB and clear rows between cases so each test starts clean."""
    repo = Path(__file__).resolve().parent.parent
    sql = (repo / "scripts" / "migrations" / "080_customer_webhooks.sql").read_text(
        encoding="utf-8"
    )
    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(sql)
        c.commit()
    finally:
        c.close()

    c = sqlite3.connect(seeded_db)
    try:
        # Children before parents: webhook_deliveries FK on customer_webhooks.
        c.execute("DELETE FROM webhook_deliveries")
        c.execute("DELETE FROM customer_webhooks")
        c.commit()
    finally:
        c.close()
    yield


# ---------------------------------------------------------------------------
# Test doubles — same shape as test_dispatch_webhooks.py so behaviour
# under monkeypatch matches the existing dispatcher test conventions.
# ---------------------------------------------------------------------------


class _MockResponse:
    def __init__(self, status_code: int = 200, text: str = ""):
        self.status_code = status_code
        self.text = text
        self.is_success = 200 <= status_code < 300


class _MockClient:
    """Capturing httpx.Client double.

    Records every POST call as (url, body_bytes, headers_dict) and returns
    pre-seeded status codes in order. Mirrors the _MockClient pattern in
    `test_dispatch_webhooks.py` so a single dispatcher implementation
    change is reflected by both suites.
    """

    def __init__(self, responses=None):
        self._responses = list(responses or [(200, "")])
        self._idx = 0
        self.calls: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass

    def post(self, url, *, content=None, headers=None, timeout=None, **_):
        self.calls.append((url, content, dict(headers or {})))
        idx = min(self._idx, len(self._responses) - 1)
        self._idx += 1
        resp = self._responses[idx]
        if isinstance(resp, Exception):
            raise resp
        return _MockResponse(*resp)


def _register_webhook(
    db_path: Path,
    api_key_hash: str,
    url: str,
    event_types: list[str],
    secret: str = "whsec_idem",
) -> int:
    c = sqlite3.connect(db_path)
    try:
        cur = c.execute(
            "INSERT INTO customer_webhooks(api_key_hash, url, event_types_json, "
            "secret_hmac, status, failure_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'active', 0, datetime('now'), datetime('now'))",
            (api_key_hash, url, json.dumps(event_types), secret),
        )
        c.commit()
        return int(cur.lastrowid or 0)
    finally:
        c.close()


def _seed_program(
    db_path: Path,
    unified_id: str,
    primary_name: str,
) -> None:
    """Seed one in-window program so the dispatcher emits program.created."""
    c = sqlite3.connect(db_path)
    try:
        c.execute(
            "INSERT OR REPLACE INTO programs("
            "  unified_id, primary_name, official_url, source_url, prefecture,"
            "  program_kind, tier, excluded, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, 0, datetime('now'))",
            (
                unified_id,
                primary_name,
                f"https://example.gov/{unified_id}",
                f"https://example.gov/{unified_id}/source",
                "全国",
                "subsidy",
                "A",
            ),
        )
        c.commit()
    finally:
        c.close()


def _patch_dispatcher(monkeypatch, mock_client):
    """Monkeypatch httpx / sleep / billing / URL safety so the dispatcher
    loop runs synchronously with our mock client and never touches the
    real Stripe / DNS paths.
    """
    import httpx as _httpx

    monkeypatch.setattr(_httpx, "Client", lambda *a, **k: mock_client)
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks.time.sleep",
        lambda _s: None,
    )
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._bill_one_delivery",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._is_safe_webhook",
        lambda url: (True, None),
    )


def _idempotency_header(headers: dict) -> str | None:
    """Case-insensitive lookup. The contract is `Idempotency-Key` (Stripe
    casing) but HTTP headers are case-insensitive, so accept any casing.
    """
    for k, v in headers.items():
        if k.lower() == "idempotency-key":
            return v
    return None


def _expected_idempotency_key(event_type: str, event_id: str) -> str:
    return hashlib.sha256(f"{event_type}:{event_id}".encode()).hexdigest()


def _expected_body_signature(secret: str, body: bytes) -> str:
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"hmac-sha256={sig}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_first_delivery_emits_idempotency_key_header(
    seeded_db,
    idem_key,
    monkeypatch,
):
    """First POST for a new event must carry an `Idempotency-Key` header.

    This is the bare-minimum customer-facing dedup contract: without ANY
    such header customers cannot tell a retry from a fresh event of the
    same shape. The dispatcher's internal DB UNIQUE(webhook_id,
    event_type, event_id) gate is invisible from the customer side.
    """
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    key_hash = hash_api_key(idem_key)
    _register_webhook(
        seeded_db,
        key_hash,
        "https://hooks.example.com/idem-first",
        ["program.created"],
    )

    # Backdate existing seeded rows out of window so we only see the new one.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("UPDATE programs SET updated_at = '1990-01-01T00:00:00+00:00'")
        c.commit()
    finally:
        c.close()

    _seed_program(seeded_db, "P-IDEM-FIRST", "Idempotency First")

    mock = _MockClient(responses=[(200, "")])
    _patch_dispatcher(monkeypatch, mock)

    dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )

    assert len(mock.calls) == 1, "expected exactly one POST for one in-window event"
    _url, body, headers = mock.calls[0]
    payload = json.loads(body.decode("utf-8"))
    assert payload["event_id"] == "P-IDEM-FIRST"
    key = _idempotency_header(headers)
    assert key is not None, (
        "DEFECT: scripts/cron/dispatch_webhooks.py _deliver_one (lines "
        "703-711) does not emit an `Idempotency-Key` header. Customers "
        "cannot dedupe retries without it."
    )
    assert key, "Idempotency-Key must be non-empty"
    assert key == _expected_idempotency_key("program.created", "P-IDEM-FIRST")


def test_idempotency_key_is_not_part_of_hmac_signature(monkeypatch):
    """The current customer-webhook signature contract signs the raw JSON body.

    `Idempotency-Key` is an HTTP delivery header, not part of the signed
    payload. Adding it must not change the existing HMAC verification contract
    for subscribers that recompute the signature from the request body.
    """
    from scripts.cron import dispatch_webhooks as dw

    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._is_safe_webhook",
        lambda url: (True, None),
    )
    mock = _MockClient(responses=[(200, "")])
    payload = {
        "event_type": "program.created",
        "event_id": "P-IDEM-SIGNED-BODY",
        "timestamp": "2026-05-13T00:00:00+00:00",
        "data": {"unified_id": "P-IDEM-SIGNED-BODY"},
    }

    status_code, error = dw._deliver_one(
        client=mock,
        url="https://hooks.example.com/signed-body",
        secret="whsec_signed_body",
        event_type="program.created",
        event_id="P-IDEM-SIGNED-BODY",
        payload=payload,
        dry_run=False,
    )

    assert (status_code, error) == (200, None)
    assert len(mock.calls) == 1
    _url, body, headers = mock.calls[0]
    key = _idempotency_header(headers)
    assert key == _expected_idempotency_key("program.created", "P-IDEM-SIGNED-BODY")
    assert headers["X-Jpcite-Signature"] == _expected_body_signature(
        "whsec_signed_body",
        body,
    )

    header_signed_body = (
        body
        + b"\nidempotency-key:"
        + key.encode()
    )
    assert headers["X-Jpcite-Signature"] != _expected_body_signature(
        "whsec_signed_body",
        header_signed_body,
    )


def test_retry_of_same_event_id_sends_same_idempotency_key(
    seeded_db,
    idem_key,
    monkeypatch,
):
    """The 2nd POST (a retry of the SAME event_id) must carry the EXACT
    SAME `Idempotency-Key` as the 1st. This is the core contract: the
    customer dedupes by key, so a retry that mutates the key is
    indistinguishable from a fresh event and would be processed twice.

    To trigger a real retry inside the dispatcher loop we return a 500 on
    the first POST and 200 on the second; the per-event retry loop in
    `_deliver_one` will then call POST twice for the SAME (event_type,
    event_id). Both POSTs must carry the same Idempotency-Key.
    """
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    key_hash = hash_api_key(idem_key)
    _register_webhook(
        seeded_db,
        key_hash,
        "https://hooks.example.com/idem-retry",
        ["program.created"],
    )

    c = sqlite3.connect(seeded_db)
    try:
        c.execute("UPDATE programs SET updated_at = '1990-01-01T00:00:00+00:00'")
        c.commit()
    finally:
        c.close()

    _seed_program(seeded_db, "P-IDEM-RETRY", "Idempotency Retry")

    # First POST 500 → retry → second POST 200. Sleep is monkeypatched
    # to a no-op in _patch_dispatcher, so the 60s backoff completes
    # instantly.
    mock = _MockClient(responses=[(500, "server err"), (200, "")])
    _patch_dispatcher(monkeypatch, mock)

    dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )

    assert len(mock.calls) >= 2, (
        "expected at least 2 POSTs (initial + retry) for the same event_id; "
        f"got {len(mock.calls)} — retry loop may not have fired"
    )

    # The two POSTs must address the SAME (event_type, event_id) and so
    # MUST carry the same Idempotency-Key.
    body_first = json.loads(mock.calls[0][1].decode("utf-8"))
    body_retry = json.loads(mock.calls[1][1].decode("utf-8"))
    assert body_first["event_type"] == body_retry["event_type"] == "program.created"
    assert body_first["data"]["unified_id"] == body_retry["data"]["unified_id"] == "P-IDEM-RETRY"

    key_first = _idempotency_header(mock.calls[0][2])
    key_retry = _idempotency_header(mock.calls[1][2])
    assert key_first is not None and key_retry is not None, (
        "DEFECT: dispatcher does not emit Idempotency-Key on retries — "
        "customers cannot dedupe and will process the same event twice."
    )
    assert key_first == key_retry, (
        "Idempotency-Key MUST be stable across retries of the same event_id."
        f" Got 1st={key_first!r}, retry={key_retry!r}"
    )


def test_different_event_ids_send_different_idempotency_keys(
    seeded_db,
    idem_key,
    monkeypatch,
):
    """Two DIFFERENT events must carry DIFFERENT `Idempotency-Key` values.

    Otherwise the customer would dedupe legitimate distinct events as a
    single one — the inverse of the retry-stability requirement above.
    Construction must depend on (event_type, event_id) or event_id alone
    so distinct event_ids produce distinct keys.
    """
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    key_hash = hash_api_key(idem_key)
    _register_webhook(
        seeded_db,
        key_hash,
        "https://hooks.example.com/idem-distinct",
        ["program.created"],
    )

    c = sqlite3.connect(seeded_db)
    try:
        c.execute("UPDATE programs SET updated_at = '1990-01-01T00:00:00+00:00'")
        c.commit()
    finally:
        c.close()

    _seed_program(seeded_db, "P-IDEM-A", "Idempotency A")
    _seed_program(seeded_db, "P-IDEM-B", "Idempotency B")

    mock = _MockClient(responses=[(200, ""), (200, "")])
    _patch_dispatcher(monkeypatch, mock)

    dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )

    assert len(mock.calls) == 2, (
        f"expected one POST per distinct event_id (2 total); got {len(mock.calls)}"
    )

    # Map each POST's Idempotency-Key to its event_id.
    seen: dict[str, str] = {}
    for _url, body, headers in mock.calls:
        payload = json.loads(body.decode("utf-8"))
        event_id = payload["data"]["unified_id"]
        key = _idempotency_header(headers)
        assert key is not None, (
            "DEFECT: dispatcher does not emit Idempotency-Key — "
            "see file docstring."
        )
        seen[event_id] = key

    assert set(seen.keys()) == {"P-IDEM-A", "P-IDEM-B"}, (
        f"expected both event_ids represented; got {set(seen.keys())}"
    )
    assert seen["P-IDEM-A"] != seen["P-IDEM-B"], (
        "Idempotency-Key MUST differ across distinct event_ids — "
        f"got both = {seen['P-IDEM-A']!r}. Customer would collapse "
        "legitimate distinct events into one."
    )
