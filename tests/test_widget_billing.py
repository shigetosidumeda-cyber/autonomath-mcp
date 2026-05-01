from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest


def test_usage_reporter_prefers_metered_overage_subscription_item(monkeypatch):
    from jpintel_mcp.billing import stripe_usage
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    stripe_usage._get_subscription_item_id.cache_clear()

    def _retrieve(_subscription_id):
        return {
            "items": {
                "data": [
                    {
                        "id": "si_widget_base",
                        "price": {
                            "id": "price_widget_base",
                            "lookup_key": "widget_business_base",
                            "recurring": {"usage_type": "licensed"},
                        },
                    },
                    {
                        "id": "si_other_metered",
                        "price": {
                            "id": "price_other_metered",
                            "lookup_key": "some_metered_addon",
                            "recurring": {"usage_type": "metered"},
                        },
                    },
                    {
                        "id": "si_widget_overage",
                        "price": {
                            "id": "price_widget_overage",
                            "lookup_key": "widget_business_overage",
                            "nickname": "Widget overage",
                            "recurring": {"usage_type": "metered"},
                        },
                    },
                ]
            }
        }

    monkeypatch.setattr(stripe_usage.stripe.Subscription, "retrieve", _retrieve)

    assert (
        stripe_usage._get_subscription_item_id("sub_widget_multi_item")
        == "si_widget_overage"
    )


def test_usage_report_failure_leaves_ledger_unsynced(
    seeded_db: Path, monkeypatch
):
    from jpintel_mcp.api.deps import hash_api_key
    from jpintel_mcp.billing import stripe_usage
    from jpintel_mcp.billing.keys import issue_key
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(
        stripe_usage, "_get_subscription_item_id", lambda _sub_id: "si_widget_overage"
    )

    def _raise(*_args, **_kwargs):
        raise RuntimeError("stripe unavailable")

    monkeypatch.setattr(
        stripe_usage.stripe.SubscriptionItem,
        "create_usage_record",
        _raise,
        raising=False,
    )

    conn = sqlite3.connect(seeded_db)
    try:
        raw = issue_key(
            conn,
            customer_id="cus_usage_failure",
            tier="paid",
            stripe_subscription_id="sub_usage_failure",
        )
        key_hash = hash_api_key(raw)
        cur = conn.execute(
            "INSERT INTO usage_events(key_hash, endpoint, ts, status, metered, quantity) "
            "VALUES (?,?,?,?,?,?)",
            (
                key_hash,
                "widget.overage.test",
                datetime.now(UTC).isoformat(),
                200,
                1,
                1,
            ),
        )
        usage_event_id = int(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()

    stripe_usage._report_sync(
        "sub_usage_failure",
        quantity=1,
        usage_event_id=usage_event_id,
    )

    conn = sqlite3.connect(seeded_db)
    try:
        row = conn.execute(
            "SELECT stripe_record_id, stripe_synced_at FROM usage_events WHERE id = ?",
            (usage_event_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row == (None, None)


@pytest.fixture()
def widget_schema(seeded_db: Path):
    repo = Path(__file__).resolve().parent.parent
    migration = repo / "scripts" / "migrations" / "022_widget_keys.sql"
    conn = sqlite3.connect(seeded_db)
    try:
        conn.executescript(migration.read_text(encoding="utf-8"))
        conn.execute("DELETE FROM widget_keys")
        conn.execute("DELETE FROM bg_task_queue WHERE dedup_key LIKE 'widget_overage:%'")
        conn.execute("DELETE FROM stripe_webhook_events WHERE event_id LIKE 'evt_widget_%'")
        conn.execute(
            "DELETE FROM stripe_webhook_events WHERE event_id LIKE 'widget:evt_widget_%'"
        )
        conn.commit()
    finally:
        conn.close()
    yield
    conn = sqlite3.connect(seeded_db)
    try:
        conn.execute("DELETE FROM widget_keys")
        conn.execute("DELETE FROM bg_task_queue WHERE dedup_key LIKE 'widget_overage:%'")
        conn.execute("DELETE FROM stripe_webhook_events WHERE event_id LIKE 'evt_widget_%'")
        conn.execute(
            "DELETE FROM stripe_webhook_events WHERE event_id LIKE 'widget:evt_widget_%'"
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def widget_stripe_env(monkeypatch):
    from jpintel_mcp.api import billing, widget_auth
    from jpintel_mcp.config import settings

    for target in (settings, billing.settings, widget_auth.settings):
        monkeypatch.setattr(
            target, "stripe_secret_key", "sk_test_dummy", raising=False
        )
        monkeypatch.setattr(
            target, "stripe_webhook_secret", "whsec_dummy", raising=False
        )
        monkeypatch.setattr(target, "env", "test", raising=False)
    return settings


def _patch_widget_construct_event(monkeypatch, event: dict) -> None:
    import stripe

    def _construct(_body, _sig, _secret):
        return event

    monkeypatch.setattr(stripe.Webhook, "construct_event", _construct)


def _post_widget_webhook(client, event: dict):
    return client.post(
        "/v1/widget/stripe-webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )


def test_widget_signup_plan_accepts_metered_and_legacy_alias():
    from jpintel_mcp.api.widget_auth import PLAN_BUSINESS, WidgetSignupRequest

    current = WidgetSignupRequest(
        email="owner@example.com",
        origins=["https://example.com"],
        plan="metered",
        success_url="https://example.com/success",
        cancel_url="https://example.com/cancel",
    )
    legacy = WidgetSignupRequest(
        email="owner@example.com",
        origins=["https://example.com"],
        plan="business",
        success_url="https://example.com/success",
        cancel_url="https://example.com/cancel",
    )

    assert current.plan == PLAN_BUSINESS
    assert legacy.plan == PLAN_BUSINESS


def _insert_widget_key(
    db_path: Path,
    *,
    key_id: str = "wgt_live_" + "a" * 32,
    allowed_origins: list[str] | None = None,
    included: int = 10_000,
    used: int = 0,
    total: int = 0,
    bucket_month: str = "2026-05",
) -> str:
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO widget_keys("
            "key_id, owner_email, label, allowed_origins_json, "
            "stripe_customer_id, stripe_subscription_id, plan, "
            "included_reqs_mtd, reqs_used_mtd, reqs_total, "
            "branding_removed, bucket_month, created_at, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                key_id,
                "owner@example.com",
                "Widget",
                json.dumps(allowed_origins or ["https://jpcite.com"]),
                "cus_widget",
                "sub_widget",
                "business",
                included,
                used,
                total,
                0,
                bucket_month,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return key_id


def _widget_checkout_event(event_id: str, sub_id: str, *, livemode: bool = False) -> dict:
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "livemode": livemode,
        "data": {
            "object": {
                "id": f"cs_{event_id}",
                "subscription": sub_id,
                "customer": "cus_widget",
                "customer_email": "owner@example.com",
                "customer_details": {"email": "owner@example.com"},
                "metadata": {
                    "autonomath_product": "widget",
                    "autonomath_plan": "business",
                    "autonomath_origins": json.dumps(["https://example.com"]),
                    "autonomath_label": "Widget",
                },
            }
        },
    }


def test_widget_webhook_livemode_mismatch_is_ignored(
    client,
    widget_schema,
    widget_stripe_env,
    monkeypatch,
    seeded_db: Path,
):
    event = _widget_checkout_event(
        "evt_widget_livemode_mismatch",
        "sub_widget_livemode_mismatch",
        livemode=True,
    )
    _patch_widget_construct_event(monkeypatch, event)

    response = _post_widget_webhook(client, event)

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "livemode_mismatch_ignored"}

    conn = sqlite3.connect(seeded_db)
    try:
        (n_keys,) = conn.execute(
            "SELECT COUNT(*) FROM widget_keys WHERE stripe_subscription_id = ?",
            ("sub_widget_livemode_mismatch",),
        ).fetchone()
        (n_events,) = conn.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id = ?",
            ("evt_widget_livemode_mismatch",),
        ).fetchone()
    finally:
        conn.close()
    assert n_keys == 0
    assert n_events == 0


def test_widget_webhook_dedups_event_id(
    client,
    widget_schema,
    widget_stripe_env,
    monkeypatch,
    seeded_db: Path,
):
    event = _widget_checkout_event(
        "evt_widget_checkout_dedup",
        "sub_widget_checkout_dedup",
    )
    _patch_widget_construct_event(monkeypatch, event)

    first = _post_widget_webhook(client, event)
    second = _post_widget_webhook(client, event)

    assert first.status_code == 200, first.text
    assert first.json() == {"status": "received"}
    assert second.status_code == 200, second.text
    assert second.json() == {"status": "duplicate_ignored"}

    conn = sqlite3.connect(seeded_db)
    try:
        (n_keys,) = conn.execute(
            "SELECT COUNT(*) FROM widget_keys WHERE stripe_subscription_id = ?",
            ("sub_widget_checkout_dedup",),
        ).fetchone()
        event_row = conn.execute(
            "SELECT event_type, livemode, processed_at FROM stripe_webhook_events "
            "WHERE event_id = ?",
            ("widget:evt_widget_checkout_dedup",),
        ).fetchone()
    finally:
        conn.close()
    assert n_keys == 1
    assert event_row is not None
    assert event_row[0] == "checkout.session.completed"
    assert event_row[1] == 0
    assert event_row[2] is not None


def test_widget_invoice_lookup_failure_returns_503_without_dedup(
    client,
    widget_schema,
    widget_stripe_env,
    monkeypatch,
    seeded_db: Path,
):
    import stripe

    event = {
        "id": "evt_widget_invoice_lookup_fail",
        "type": "invoice.payment_failed",
        "livemode": False,
        "data": {
            "object": {
                "id": "in_widget_lookup_fail",
                "subscription": "sub_widget_lookup_fail",
            }
        },
    }
    _patch_widget_construct_event(monkeypatch, event)

    def _raise_retrieve(_sub_id):
        raise RuntimeError("stripe unavailable")

    monkeypatch.setattr(stripe.Subscription, "retrieve", _raise_retrieve)

    response = _post_widget_webhook(client, event)

    assert response.status_code == 503, response.text
    conn = sqlite3.connect(seeded_db)
    try:
        (n_events,) = conn.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id = ?",
            ("widget:evt_widget_invoice_lookup_fail",),
        ).fetchone()
    finally:
        conn.close()
    assert n_events == 0


def test_main_webhook_dedup_does_not_block_widget_provisioning(
    client,
    widget_schema,
    widget_stripe_env,
    monkeypatch,
    seeded_db: Path,
):
    event = _widget_checkout_event(
        "evt_widget_seen_by_main_first",
        "sub_widget_seen_by_main_first",
    )
    _patch_widget_construct_event(monkeypatch, event)

    main_response = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    widget_response = _post_widget_webhook(client, event)

    assert main_response.status_code == 200, main_response.text
    assert widget_response.status_code == 200, widget_response.text
    assert widget_response.json() == {"status": "received"}

    conn = sqlite3.connect(seeded_db)
    try:
        (n_keys,) = conn.execute(
            "SELECT COUNT(*) FROM widget_keys WHERE stripe_subscription_id = ?",
            ("sub_widget_seen_by_main_first",),
        ).fetchone()
        rows = conn.execute(
            "SELECT event_id FROM stripe_webhook_events "
            "WHERE event_id IN (?, ?) ORDER BY event_id",
            (
                "evt_widget_seen_by_main_first",
                "widget:evt_widget_seen_by_main_first",
            ),
        ).fetchall()
    finally:
        conn.close()

    assert n_keys == 1
    assert [row[0] for row in rows] == [
        "evt_widget_seen_by_main_first",
        "widget:evt_widget_seen_by_main_first",
    ]


def test_widget_search_failure_does_not_increment_usage(
    client,
    widget_schema,
    seeded_db: Path,
    monkeypatch,
):
    key_id = _insert_widget_key(seeded_db, allowed_origins=["https://example.com"])

    from jpintel_mcp.api import programs

    def _raise_search(*_args, **_kwargs):
        raise RuntimeError("search backend unavailable")

    monkeypatch.setattr(programs, "search_programs", _raise_search)

    response = client.get(
        "/v1/widget/search",
        params={"key": key_id, "q": "テスト"},
        headers={"origin": "https://example.com"},
    )

    assert response.status_code == 500
    conn = sqlite3.connect(seeded_db)
    try:
        row = conn.execute(
            "SELECT reqs_used_mtd, reqs_total FROM widget_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row == (0, 0)


def test_widget_origin_enforcement_defers_to_widget_allowlist(
    client,
    widget_schema,
    seeded_db: Path,
    monkeypatch,
):
    key_id = _insert_widget_key(seeded_db, allowed_origins=["https://example.com"])

    from fastapi.responses import JSONResponse

    from jpintel_mcp.api import programs

    def _fake_search(*_args, **_kwargs):
        return JSONResponse({"total": 0, "results": [], "limit": 5, "offset": 0})

    monkeypatch.setattr(programs, "search_programs", _fake_search)

    response = client.get(
        "/v1/widget/search",
        params={"key": key_id, "q": "テスト"},
        headers={"origin": "https://example.com"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == "https://example.com"
    assert response.json()["widget"]["reqs_used_mtd"] == 1


def test_widget_overage_uses_unique_idempotency_key(
    widget_schema,
    seeded_db: Path,
    monkeypatch,
):
    from jpintel_mcp.api import widget_auth

    key_id = _insert_widget_key(seeded_db, included=0)
    seen: list[tuple[str, str]] = []

    def _fake_report(
        _conn: sqlite3.Connection, subscription_id: str, *, idempotency_key: str
    ) -> None:
        seen.append((subscription_id, idempotency_key))

    monkeypatch.setattr(widget_auth, "_report_overage", _fake_report)

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM widget_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
        wk = widget_auth.WidgetKeyRow(row)
        widget_auth._enforce_quota_and_increment(conn, wk)
        widget_auth._enforce_quota_and_increment(conn, wk)
        stored = conn.execute(
            "SELECT reqs_used_mtd, reqs_total FROM widget_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
    finally:
        conn.close()

    assert stored["reqs_used_mtd"] == 2
    assert stored["reqs_total"] == 2
    assert seen == [
        ("sub_widget", f"widget_{key_id}_1"),
        ("sub_widget", f"widget_{key_id}_2"),
    ]


def test_widget_overage_stale_rows_use_returned_counter(
    widget_schema,
    seeded_db: Path,
    monkeypatch,
):
    from jpintel_mcp.api import widget_auth

    key_id = _insert_widget_key(seeded_db, included=1, used=1, total=41)
    seen: list[str] = []

    def _fake_report(
        _conn: sqlite3.Connection, _subscription_id: str, *, idempotency_key: str
    ) -> None:
        seen.append(idempotency_key)

    monkeypatch.setattr(widget_auth, "_report_overage", _fake_report)

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        row1 = conn.execute(
            "SELECT * FROM widget_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
        row2 = conn.execute(
            "SELECT * FROM widget_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
        widget_auth._enforce_quota_and_increment(
            conn, widget_auth.WidgetKeyRow(row1)
        )
        widget_auth._enforce_quota_and_increment(
            conn, widget_auth.WidgetKeyRow(row2)
        )
        stored = conn.execute(
            "SELECT reqs_used_mtd, reqs_total FROM widget_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
    finally:
        conn.close()

    assert stored["reqs_used_mtd"] == 3
    assert stored["reqs_total"] == 43
    assert seen == [
        f"widget_{key_id}_42",
        f"widget_{key_id}_43",
    ]


def test_widget_overage_enqueues_durable_usage_sync(
    widget_schema,
    seeded_db: Path,
    monkeypatch,
):
    from jpintel_mcp.api import _bg_task_worker, widget_auth

    key_id = _insert_widget_key(seeded_db, included=0, used=0, total=0)
    handled: list[dict] = []
    monkeypatch.setitem(
        _bg_task_worker._HANDLERS,
        "stripe_usage_sync",
        lambda payload: handled.append(payload),
    )

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM widget_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
        widget_auth._enforce_quota_and_increment(conn, widget_auth.WidgetKeyRow(row))
        queued = conn.execute(
            "SELECT kind, payload_json, status, dedup_key FROM bg_task_queue "
            "WHERE dedup_key = ?",
            (f"widget_overage:widget_{key_id}_1",),
        ).fetchone()
    finally:
        conn.close()

    assert queued is not None
    assert queued["kind"] == "stripe_usage_sync"
    assert queued["status"] == "done"
    payload = json.loads(queued["payload_json"])
    assert payload == {
        "subscription_id": "sub_widget",
        "quantity": 1,
        "idempotency_key": f"widget_{key_id}_1",
    }
    assert handled == [payload]


def test_widget_overage_counter_and_queue_insert_are_atomic(
    widget_schema,
    seeded_db: Path,
    monkeypatch,
):
    from fastapi import HTTPException

    from jpintel_mcp.api import widget_auth

    key_id = _insert_widget_key(seeded_db, included=0, used=0, total=0)

    def _raise_report(*_args, **_kwargs) -> None:
        raise RuntimeError("queue down")

    monkeypatch.setattr(widget_auth, "_report_overage", _raise_report)

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM widget_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
        with pytest.raises(HTTPException) as exc:
            widget_auth._enforce_quota_and_increment(
                conn,
                widget_auth.WidgetKeyRow(row),
            )
        stored = conn.execute(
            "SELECT reqs_used_mtd, reqs_total FROM widget_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
    finally:
        conn.close()

    assert exc.value.status_code == 503
    assert stored["reqs_used_mtd"] == 0
    assert stored["reqs_total"] == 0


def test_widget_overage_missing_subscription_id_rolls_back_and_503(
    widget_schema,
    seeded_db: Path,
):
    from fastapi import HTTPException

    from jpintel_mcp.api import widget_auth

    key_id = _insert_widget_key(seeded_db, included=0, used=0, total=0)
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "UPDATE widget_keys SET stripe_subscription_id = '' WHERE key_id = ?",
            (key_id,),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM widget_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
        with pytest.raises(HTTPException) as exc:
            widget_auth._enforce_quota_and_increment(
                conn,
                widget_auth.WidgetKeyRow(row),
            )
        stored = conn.execute(
            "SELECT reqs_used_mtd, reqs_total FROM widget_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
        queued_count = conn.execute(
            "SELECT COUNT(*) FROM bg_task_queue "
            "WHERE dedup_key = ?",
            (f"widget_overage:widget_{key_id}_1",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert exc.value.status_code == 503
    assert stored["reqs_used_mtd"] == 0
    assert stored["reqs_total"] == 0
    assert queued_count == 0


def test_widget_month_rollover_stale_rows_use_current_counter(
    widget_schema,
    seeded_db: Path,
):
    from jpintel_mcp.api import widget_auth

    key_id = _insert_widget_key(
        seeded_db,
        included=10_000,
        used=9,
        total=40,
        bucket_month="2026-04",
    )
    now = datetime(2026, 5, 1, 1, 0, tzinfo=UTC)

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        row1 = conn.execute(
            "SELECT * FROM widget_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
        row2 = conn.execute(
            "SELECT * FROM widget_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
        wk1 = widget_auth.WidgetKeyRow(row1)
        wk2 = widget_auth.WidgetKeyRow(row2)

        widget_auth._roll_month_if_needed(conn, wk1, now=now)
        widget_auth._enforce_quota_and_increment(conn, wk1)
        widget_auth._roll_month_if_needed(conn, wk2, now=now)
        widget_auth._enforce_quota_and_increment(conn, wk2)

        stored = conn.execute(
            "SELECT reqs_used_mtd, reqs_total, bucket_month "
            "FROM widget_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
    finally:
        conn.close()

    assert stored["reqs_used_mtd"] == 2
    assert stored["reqs_total"] == 42
    assert stored["bucket_month"] == "2026-05"
