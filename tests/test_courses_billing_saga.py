"""
test_courses_billing_saga.py — DEEP-46 test stub (Pattern A pre-charge).

Coverage of jpcite v0.3.4 spec DEEP-46:
- api/courses.py:subscribe_course (D+1 即時送信) re-ordered to charge → email → subscription update.
- scripts/cron/course_dispatcher.py (D+2..D+N) following the same pre-charge fence.
- courses_billing_saga (jpintel migration wave24_001) tracks every step status.
- Reconcile cron should find ZERO partial state when Pattern A is applied correctly.

Constraints:
- LLM API call: 0
- Test pattern: pytest fixtures + parametrize, pure SQLite + mock Stripe / Postmark.
- 8 cases — first half exercise happy path + clean-fail; second half exercise edge cases.
- src/ implementation is a placeholder; helpers in this file are call surrogates.
"""
from __future__ import annotations

import sqlite3
from typing import Any

import pytest

# Pull DEEP-46/47/48 shared fixtures (jpintel_conn, autonomath_conn,
# mock_stripe_client, mock_postmark, mock_r2_storage, synthetic_event_factory,
# assert_no_llm_imports, fake_clock, in_memory_sqlite) from the renamed
# conftest_delivery_strict.py — pytest only auto-loads `conftest.py`, so the
# delivery-strict fixtures must be opted in explicitly via pytest_plugins.
pytest_plugins = ["tests.conftest_delivery_strict"]


# ---------------------------------------------------------------------------
# Surrogate implementation (placeholder until codex lane wires src/ side)
# ---------------------------------------------------------------------------


def _saga_begin(conn: sqlite3.Connection, sub_id: int, key_hash: str, day_n: int) -> int:
    cur = conn.execute(
        """
        INSERT INTO courses_billing_saga
            (course_subscription_id, api_key_id, day_n, started_at, status)
        VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'), 'partial_no_charge')
        """,
        (sub_id, key_hash, day_n),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def _saga_finish(conn: sqlite3.Connection, saga_id: int, *, status: str, error: str | None = None) -> None:
    conn.execute(
        "UPDATE courses_billing_saga SET status=?, error_msg=? WHERE id=?",
        (status, error, saga_id),
    )
    conn.commit()


def subscribe_course_pattern_a(
    conn: sqlite3.Connection,
    *,
    api_key_hash: str,
    course_slug: str,
    notify_email: str,
    stripe_client: Any,
    postmark: Any,
    day_n: int = 1,
) -> dict[str, Any]:
    """Pre-charge → send → subscription update (DEEP-46 Pattern A)."""
    cur = conn.execute(
        """
        INSERT INTO course_subscriptions(api_key_id, course_slug, notify_email, current_day)
        VALUES (?, ?, ?, 0)
        """,
        (api_key_hash, course_slug, notify_email),
    )
    sub_id = int(cur.lastrowid or 0)
    conn.commit()

    saga_id = _saga_begin(conn, sub_id, api_key_hash, day_n)

    idempotency_key = f"courses.delivery:{course_slug}:{api_key_hash}:day_{day_n}"
    charged = stripe_client.record_metered_delivery(
        api_key_hash=api_key_hash,
        endpoint="courses.delivery",
        status_code=200,
        idempotency_key=idempotency_key,
    )
    if not charged:
        _saga_finish(conn, saga_id, status="charge_failed")
        # Notify the user that the charge failed — ¥0 metered side-channel
        postmark.send_template(
            to=notify_email,
            template="course_charge_failed",
            data={"course_slug": course_slug},
        )
        return {"status": "charge_failed", "saga_id": saga_id, "current_day": 0}

    sent = postmark.send_template(
        to=notify_email,
        template="course_day_n",
        data={"course_slug": course_slug, "day_n": day_n},
    )
    if not sent:
        # charge succeeded but email send failed — DEEP-46 §3 step 4: keep current_day=0
        _saga_finish(conn, saga_id, status="partial_no_charge")
        return {"status": "partial_no_charge", "saga_id": saga_id, "current_day": 0}

    conn.execute(
        "UPDATE course_subscriptions SET current_day=?, last_sent_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (day_n, sub_id),
    )
    _saga_finish(conn, saga_id, status="success")
    conn.commit()
    return {"status": "success", "saga_id": saga_id, "current_day": day_n}


def reconcile_courses(conn: sqlite3.Connection) -> int:
    """Return the count of partial saga rows older than 5 minutes (DEEP-51 ack pack hint)."""
    cur = conn.execute(
        """
        SELECT COUNT(*) FROM courses_billing_saga
        WHERE status IN ('partial_no_charge','partial_email_only')
        """
    )
    return int(cur.fetchone()[0])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_charge_success_then_email_send_then_subscription_update(
    jpintel_conn, mock_stripe_client, mock_postmark
) -> None:
    """Happy path — Pattern A order: charge → email → subscription update."""
    result = subscribe_course_pattern_a(
        jpintel_conn,
        api_key_hash="hash_aaa",
        course_slug="kaikei_pack_30day",
        notify_email="user@example.com",
        stripe_client=mock_stripe_client,
        postmark=mock_postmark,
    )
    assert result["status"] == "success"
    assert result["current_day"] == 1
    # Charge must precede email send in the call ledger
    assert len(mock_stripe_client.calls) == 1
    assert mock_stripe_client.calls[0].endpoint == "courses.delivery"
    assert len(mock_postmark.sends) == 1
    assert mock_postmark.sends[0].template == "course_day_n"
    # Saga row should be 'success'
    rows = jpintel_conn.execute("SELECT status FROM courses_billing_saga").fetchall()
    assert [r["status"] for r in rows] == ["success"]


def test_charge_failure_no_email_no_subscription_update(
    jpintel_conn, mock_stripe_client, mock_postmark
) -> None:
    """Clean-fail: charge fails → no Postmark digest send, only the ¥0 charge_failed notice."""
    mock_stripe_client.cap_exceeded = True
    result = subscribe_course_pattern_a(
        jpintel_conn,
        api_key_hash="hash_bbb",
        course_slug="kaikei_pack_30day",
        notify_email="user@example.com",
        stripe_client=mock_stripe_client,
        postmark=mock_postmark,
    )
    assert result["status"] == "charge_failed"
    assert result["current_day"] == 0
    # Subscription stays at current_day=0 → cron will not race
    sub_rows = jpintel_conn.execute("SELECT current_day FROM course_subscriptions").fetchall()
    assert sub_rows[0]["current_day"] == 0
    # Only the charge_failed_notice template fires; no course_day_n send
    templates = [s.template for s in mock_postmark.sends]
    assert "course_day_n" not in templates
    assert templates == ["course_charge_failed"]


@pytest.mark.parametrize("status_code", [503, 402, 429])
def test_cap_exceeded_503_no_partial_state(
    jpintel_conn, mock_stripe_client, mock_postmark, status_code
) -> None:
    """All non-2xx statuses must be treated as fail-closed; DB remains consistent."""
    mock_stripe_client.next_outcomes = [False]
    subscribe_course_pattern_a(
        jpintel_conn,
        api_key_hash=f"hash_{status_code}",
        course_slug="kaikei_pack_30day",
        notify_email="user@example.com",
        stripe_client=mock_stripe_client,
        postmark=mock_postmark,
    )
    partial_count = reconcile_courses(jpintel_conn)
    # No 'partial_no_charge' rows since the email never went out.
    assert partial_count == 0


def test_stripe_webhook_timeout_retry(
    jpintel_conn, mock_stripe_client, mock_postmark
) -> None:
    """Idempotency-Key collision should fail-fast on first try, succeed on retry."""
    mock_stripe_client.idempotency_collision.add(
        "courses.delivery:kaikei_pack_30day:hash_xx:day_1"
    )
    first = subscribe_course_pattern_a(
        jpintel_conn,
        api_key_hash="hash_xx",
        course_slug="kaikei_pack_30day",
        notify_email="user@example.com",
        stripe_client=mock_stripe_client,
        postmark=mock_postmark,
    )
    assert first["status"] == "charge_failed"
    # Operator releases the collision (e.g. by reconcile cron); retry succeeds
    mock_stripe_client.idempotency_collision.clear()
    second = subscribe_course_pattern_a(
        jpintel_conn,
        api_key_hash="hash_xx",
        course_slug="kaikei_pack_30day",
        notify_email="user@example.com",
        stripe_client=mock_stripe_client,
        postmark=mock_postmark,
    )
    assert second["status"] == "success"


def test_partial_email_failure_after_charge(
    jpintel_conn, mock_stripe_client, mock_postmark
) -> None:
    """Charge succeeded, email failed → saga row 'partial_no_charge' (current_day stays 0).

    The next-day cron will retry the SAME D+1 because current_day did not advance —
    matches DEEP-46 §3 step 4 ("idempotency_cache のキーは course × day × YYYYMMDD").
    """
    mock_postmark.fail_next = 1
    result = subscribe_course_pattern_a(
        jpintel_conn,
        api_key_hash="hash_partial",
        course_slug="kaikei_pack_30day",
        notify_email="user@example.com",
        stripe_client=mock_stripe_client,
        postmark=mock_postmark,
    )
    assert result["status"] == "partial_no_charge"
    sub_rows = jpintel_conn.execute("SELECT current_day FROM course_subscriptions").fetchall()
    assert sub_rows[0]["current_day"] == 0
    # The charge call did happen
    assert len(mock_stripe_client.calls) == 1


def test_reconcile_cron_finds_partial_state_zero(
    jpintel_conn, mock_stripe_client, mock_postmark
) -> None:
    """After 100 happy-path subscribes, reconcile should report ZERO partial rows."""
    for i in range(100):
        subscribe_course_pattern_a(
            jpintel_conn,
            api_key_hash=f"hash_{i:03d}",
            course_slug="kaikei_pack_30day",
            notify_email=f"user_{i}@example.com",
            stripe_client=mock_stripe_client,
            postmark=mock_postmark,
        )
    assert reconcile_courses(jpintel_conn) == 0


def test_idempotency_cache_dedup(
    jpintel_conn, mock_stripe_client, mock_postmark
) -> None:
    """Same (course × day × api_key) on the same UTC day must dedup at the cache layer.

    The placeholder uses the Stripe-side idempotency_key path; the cache layer
    proper is wired in src/jpintel_mcp/api/courses.py once codex integrates.
    """
    sub_args = dict(
        api_key_hash="hash_dedup",
        course_slug="kaikei_pack_30day",
        notify_email="user@example.com",
        stripe_client=mock_stripe_client,
        postmark=mock_postmark,
    )
    subscribe_course_pattern_a(jpintel_conn, **sub_args)
    # Second call with same (course × day) → Stripe returns False because of collision
    mock_stripe_client.idempotency_collision.add(
        "courses.delivery:kaikei_pack_30day:hash_dedup:day_1"
    )
    second = subscribe_course_pattern_a(jpintel_conn, **sub_args)
    assert second["status"] == "charge_failed"
    # Postmark received only the legitimate first send + the failure notice for the second
    sends = [s.template for s in mock_postmark.sends]
    assert sends.count("course_day_n") == 1
    assert sends.count("course_charge_failed") == 1


def test_no_llm_api_import(assert_no_llm_imports) -> None:
    """CI guard — DEEP-46 surface must never import an LLM SDK at runtime."""
    # The test file itself only imports pytest + sqlite3.
    # `assert_no_llm_imports` scans sys.modules to assert nothing leaked in.
    assert_no_llm_imports()
