"""
test_delivery_idempotent.py — DEEP-48 test stub (Pattern A + B 併用).

Coverage of jpcite v0.3.4 spec DEEP-48:
- scripts/cron/run_saved_searches.py (saved_search digest)
- scripts/cron/dispatch_webhooks.py (customer webhook POST)
Both flows wrap (event_hash, delivery_url_hash) in `delivery_idempotent_log`
(jpintel migration wave24_NNN) and gate external send behind a charge-first
fence so the strict_metering 副作用 can't leak in either direction:
- saved_search: skip duplicates within 24h → no double-send
- webhook: pre-charge so 200 send + non-200 charge can't co-occur

Constraints:
- LLM API call: 0
- Test pattern: pytest fixtures + parametrize + per-event hash assertions.
- 10 test cases, including event-hash collision detection (sha256 false-positive 0).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    import sqlite3

# Pull DEEP-46/47/48 shared fixtures (jpintel_conn, autonomath_conn,
# mock_stripe_client, mock_postmark, mock_r2_storage, synthetic_event_factory,
# assert_no_llm_imports, fake_clock, in_memory_sqlite) from the renamed
# conftest_delivery_strict.py — pytest only auto-loads `conftest.py`, so the
# delivery-strict fixtures must be opted in explicitly via pytest_plugins.
pytest_plugins = ["tests.conftest_delivery_strict"]

# ---------------------------------------------------------------------------
# Surrogate implementation
# ---------------------------------------------------------------------------

_AGGREGATOR_HOST_DENYLIST = {
    "noukaweb.com",
    "hojyokin-portal.jp",
    "biz.stayway.jp",
}


def _now_dt() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _is_aggregator(url: str) -> bool:
    return any(banned in url for banned in _AGGREGATOR_HOST_DENYLIST)


@dataclass
class DeliveryRequest:
    event_hash: str
    delivery_url: str
    kind: str  # 'saved_search' | 'customer_webhook'
    payload: dict[str, Any]


def deliver_with_idempotent_log(
    conn: sqlite3.Connection,
    *,
    request: DeliveryRequest,
    api_key_hash: str,
    stripe_client: Any,
    sender: Any,
    ttl_seconds: int = 24 * 3600,
) -> dict[str, Any]:
    """DEEP-48 Pattern A+B combined send/charge gate."""
    if _is_aggregator(request.delivery_url):
        return {"status": "rejected", "reason": "aggregator_url_denied"}

    url_hash = _url_hash(request.delivery_url)

    # Pattern A — idempotent dedup lookup (24h TTL)
    row = conn.execute(
        """
        SELECT status, ttl_expires_at
        FROM delivery_idempotent_log
        WHERE event_hash=? AND delivery_url_hash=?
        """,
        (request.event_hash, url_hash),
    ).fetchone()
    if row is not None:
        ttl_expires = datetime.strptime(row["ttl_expires_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        ttl_expires = ttl_expires.replace(tzinfo=UTC)
        if ttl_expires > _now_dt():
            return {"status": "skipped_duplicate", "prior_status": row["status"]}

    # Pattern B — charge-first
    charged = stripe_client.record_metered_delivery(
        api_key_hash=api_key_hash,
        endpoint=f"{request.kind}.delivery",
        status_code=200,
        idempotency_key=f"{request.kind}:{request.event_hash}:{url_hash}",
    )
    if not charged:
        # Don't write the dedup row → next cron tick can retry the charge.
        return {"status": "charge_failed"}

    # External send (Postmark / customer URL POST)
    sent = sender(request.delivery_url, request.payload)

    # Different TTL for success (24h) vs send_failed (1h)
    expires_at = _now_dt() + timedelta(seconds=ttl_seconds if sent else 3600)
    conn.execute(
        """
        INSERT INTO delivery_idempotent_log
            (event_hash, delivery_url_hash, kind, status, charge_at, sent_at, ttl_expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_hash, delivery_url_hash) DO UPDATE SET
            status=excluded.status,
            charge_at=excluded.charge_at,
            sent_at=excluded.sent_at,
            ttl_expires_at=excluded.ttl_expires_at
        """,
        (
            request.event_hash,
            url_hash,
            request.kind,
            "success" if sent else "send_failed",
            _iso(_now_dt()),
            _iso(_now_dt()) if sent else None,
            _iso(expires_at),
        ),
    )
    conn.commit()
    return {"status": "success" if sent else "send_failed"}


def reconcile_inconsistency(conn: sqlite3.Connection) -> int:
    """Surrogate reconcile cron: 'sent_at != NULL but charge_at NULL' must be ZERO."""
    row = conn.execute(
        """
        SELECT COUNT(*) FROM delivery_idempotent_log
        WHERE sent_at IS NOT NULL AND charge_at IS NULL
        """
    ).fetchone()
    return int(row[0])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_same_event_consecutive_trigger_one_send_only(
    jpintel_conn, mock_stripe_client, synthetic_event_factory
) -> None:
    """Two consecutive ticks for the same event_hash → exactly one external send."""
    sends: list[str] = []

    def sender(url: str, payload: dict[str, Any]) -> bool:
        sends.append(url)
        return True

    event = synthetic_event_factory.make(event_kind="saved_search.match")
    request = DeliveryRequest(
        event_hash=event.event_hash,
        delivery_url="https://customer.example/webhook",
        kind="saved_search",
        payload=event.payload,
    )
    first = deliver_with_idempotent_log(
        jpintel_conn,
        request=request,
        api_key_hash="hash_aaa",
        stripe_client=mock_stripe_client,
        sender=sender,
    )
    second = deliver_with_idempotent_log(
        jpintel_conn,
        request=request,
        api_key_hash="hash_aaa",
        stripe_client=mock_stripe_client,
        sender=sender,
    )
    assert first["status"] == "success"
    assert second["status"] == "skipped_duplicate"
    assert len(sends) == 1
    # Charge happened exactly once
    assert len(mock_stripe_client.calls) == 1


def test_charge_failure_no_webhook_post(
    jpintel_conn, mock_stripe_client, synthetic_event_factory
) -> None:
    """Charge fails → external sender never invoked, idempotent row not created."""
    sends: list[str] = []

    def sender(url: str, payload: dict[str, Any]) -> bool:
        sends.append(url)
        return True

    mock_stripe_client.cap_exceeded = True
    event = synthetic_event_factory.make()
    request = DeliveryRequest(
        event_hash=event.event_hash,
        delivery_url="https://customer.example/webhook",
        kind="customer_webhook",
        payload=event.payload,
    )
    result = deliver_with_idempotent_log(
        jpintel_conn,
        request=request,
        api_key_hash="hash_charge_fail",
        stripe_client=mock_stripe_client,
        sender=sender,
    )
    assert result["status"] == "charge_failed"
    assert sends == []
    # No idempotent log row → next cron will retry
    rows = jpintel_conn.execute("SELECT COUNT(*) FROM delivery_idempotent_log").fetchone()
    assert rows[0] == 0


def test_cache_ttl_24h_then_retry_ok(
    jpintel_conn, mock_stripe_client, synthetic_event_factory
) -> None:
    """After 24h TTL window, the same event can be re-delivered (e.g. a re-issued course)."""
    sends: list[str] = []

    def sender(url: str, payload: dict[str, Any]) -> bool:
        sends.append(url)
        return True

    event = synthetic_event_factory.make()
    request = DeliveryRequest(
        event_hash=event.event_hash,
        delivery_url="https://customer.example/webhook",
        kind="saved_search",
        payload=event.payload,
    )
    deliver_with_idempotent_log(
        jpintel_conn,
        request=request,
        api_key_hash="hash_ttl",
        stripe_client=mock_stripe_client,
        sender=sender,
    )
    # Force-expire the cache row so the re-deliver path is exercised
    jpintel_conn.execute(
        "UPDATE delivery_idempotent_log SET ttl_expires_at=?",
        (_iso(_now_dt() - timedelta(seconds=1)),),
    )
    jpintel_conn.commit()
    second = deliver_with_idempotent_log(
        jpintel_conn,
        request=request,
        api_key_hash="hash_ttl",
        stripe_client=mock_stripe_client,
        sender=sender,
    )
    assert second["status"] == "success"
    assert len(sends) == 2


def test_different_delivery_url_treated_separately(
    jpintel_conn, mock_stripe_client, synthetic_event_factory
) -> None:
    """Same event_hash but two distinct customer URLs → two charges, two sends."""
    sends: list[str] = []

    def sender(url: str, payload: dict[str, Any]) -> bool:
        sends.append(url)
        return True

    event = synthetic_event_factory.make()
    for url in ("https://a.example/webhook", "https://b.example/webhook"):
        request = DeliveryRequest(
            event_hash=event.event_hash,
            delivery_url=url,
            kind="customer_webhook",
            payload=event.payload,
        )
        result = deliver_with_idempotent_log(
            jpintel_conn,
            request=request,
            api_key_hash="hash_multi_url",
            stripe_client=mock_stripe_client,
            sender=sender,
        )
        assert result["status"] == "success"
    assert len(sends) == 2
    assert len(mock_stripe_client.calls) == 2


def test_idempotency_cache_mig_087_compat(
    jpintel_conn, mock_stripe_client, synthetic_event_factory
) -> None:
    """delivery_idempotent_log (DEEP-48 mig) must coexist with idempotency_cache (mig 087).

    They serve different domains: mig 087 = HTTP POST replay (synchronous user requests);
    DEEP-48 = cron delivery dedup. The two tables share neither rows nor schema.
    """
    # Plant a row in the legacy mig 087 table
    jpintel_conn.execute(
        """
        INSERT INTO idempotency_cache(cache_key, endpoint, status_code, response_body)
        VALUES ('legacy_key', 'POST.programs.search', 200, '{}')
        """
    )
    jpintel_conn.commit()

    sends: list[str] = []

    def sender(url: str, payload: dict[str, Any]) -> bool:
        sends.append(url)
        return True

    event = synthetic_event_factory.make()
    request = DeliveryRequest(
        event_hash=event.event_hash,
        delivery_url="https://customer.example/webhook",
        kind="saved_search",
        payload=event.payload,
    )
    deliver_with_idempotent_log(
        jpintel_conn,
        request=request,
        api_key_hash="hash_compat",
        stripe_client=mock_stripe_client,
        sender=sender,
    )
    # Both tables independently populated, no cross-pollination
    legacy = jpintel_conn.execute("SELECT COUNT(*) FROM idempotency_cache").fetchone()[0]
    new = jpintel_conn.execute("SELECT COUNT(*) FROM delivery_idempotent_log").fetchone()[0]
    assert legacy == 1
    assert new == 1


def test_event_hash_collision_detect(
    jpintel_conn, mock_stripe_client, synthetic_event_factory
) -> None:
    """sha256(event_id || customer_id || event_kind || payload_hash) must distinguish
    distinct events. Asserts ZERO collisions across 1000 synthetic events."""
    hashes: set[str] = set()
    for i in range(1000):
        e = synthetic_event_factory.make(
            event_kind="saved_search.match",
            customer_id=f"cust_{i}",
            payload={"program_id": f"prog_{i}"},
        )
        assert e.event_hash not in hashes, f"sha256 collision at i={i}"
        hashes.add(e.event_hash)
    assert len(hashes) == 1000


def test_reconcile_cron_finds_inconsistency_zero(
    jpintel_conn, mock_stripe_client, synthetic_event_factory
) -> None:
    """After 50 happy-path deliveries, reconcile should find 0 inconsistencies."""

    def sender(url: str, payload: dict[str, Any]) -> bool:
        return True

    for i in range(50):
        event = synthetic_event_factory.make(customer_id=f"cust_{i}")
        request = DeliveryRequest(
            event_hash=event.event_hash,
            delivery_url=f"https://cust{i}.example/hook",
            kind="customer_webhook",
            payload=event.payload,
        )
        deliver_with_idempotent_log(
            jpintel_conn,
            request=request,
            api_key_hash=f"hash_{i:03d}",
            stripe_client=mock_stripe_client,
            sender=sender,
        )
    assert reconcile_inconsistency(jpintel_conn) == 0


@pytest.mark.parametrize(
    "url",
    [
        "https://noukaweb.com/programs/123",
        "https://hojyokin-portal.jp/list",
        "https://biz.stayway.jp/feed",
    ],
)
def test_aggregator_url_reject_pre_send(
    jpintel_conn, mock_stripe_client, synthetic_event_factory, url
) -> None:
    """Aggregator hosts must be rejected BEFORE any charge / send happens (data-hygiene NN)."""

    def sender(url: str, payload: dict[str, Any]) -> bool:  # noqa: ARG001
        raise AssertionError("Aggregator delivery must not call sender")

    event = synthetic_event_factory.make()
    request = DeliveryRequest(
        event_hash=event.event_hash,
        delivery_url=url,
        kind="saved_search",
        payload=event.payload,
    )
    result = deliver_with_idempotent_log(
        jpintel_conn,
        request=request,
        api_key_hash="hash_agg",
        stripe_client=mock_stripe_client,
        sender=sender,
    )
    assert result == {"status": "rejected", "reason": "aggregator_url_denied"}
    assert len(mock_stripe_client.calls) == 0


def test_no_llm_api_import(assert_no_llm_imports) -> None:
    """CI guard — DEEP-48 must remain LLM-import-free."""
    assert_no_llm_imports()


def test_per_event_3yen_charge_confirm(
    jpintel_conn, mock_stripe_client, synthetic_event_factory
) -> None:
    """Each successful delivery charges exactly ¥3 — no batch discount, no tier markup."""

    def sender(url: str, payload: dict[str, Any]) -> bool:
        return True

    for i in range(7):
        event = synthetic_event_factory.make(customer_id=f"cust_{i}")
        request = DeliveryRequest(
            event_hash=event.event_hash,
            delivery_url=f"https://cust{i}.example/hook",
            kind="customer_webhook",
            payload=event.payload,
        )
        deliver_with_idempotent_log(
            jpintel_conn,
            request=request,
            api_key_hash=f"hash_{i:03d}",
            stripe_client=mock_stripe_client,
            sender=sender,
        )
    assert len(mock_stripe_client.calls) == 7
    assert all(call.amount_yen == 3 for call in mock_stripe_client.calls)
    total_yen = sum(call.amount_yen for call in mock_stripe_client.calls)
    assert total_yen == 21  # 7 × ¥3 — fully metered, no plan discount
