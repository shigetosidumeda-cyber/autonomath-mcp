"""Tests for the onboarding email scheduler (enqueue + run_due).

Strategy
--------
* Each test creates a fresh SQLite DB via `init_db()` in `tmp_path`, so the
  `email_schedule` rows never leak between tests.
* "Wall clock" is controlled by the `now` parameter both helpers accept, so
  we do not need `freezegun`.
* Postmark is exercised through `httpx.MockTransport` (same pattern as
  `tests/test_email.py`) so assertions can inspect payload shape.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest

from jpintel_mcp.db.session import init_db
from jpintel_mcp.email.onboarding import (
    TEMPLATE_DAY1,
    TEMPLATE_DAY3,
    TEMPLATE_DAY7,
    TEMPLATE_DAY14,
    TEMPLATE_DAY30,
)
from jpintel_mcp.email.postmark import POSTMARK_BASE_URL, PostmarkClient
from jpintel_mcp.email.scheduler import (
    ALL_KINDS,
    enqueue_onboarding_sequence,
    run_due,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "sched.db"
    init_db(db_path)
    c = sqlite3.connect(db_path, isolation_level=None)
    c.row_factory = sqlite3.Row
    # Seed an api_keys row so _resolve_tier finds something.
    c.execute(
        """INSERT INTO api_keys(key_hash, customer_id, tier, stripe_subscription_id, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("hash_abcd1234", "cus_test", "paid", "sub_t", "2026-04-23T00:00:00+00:00"),
    )
    yield c
    c.close()


def _mock_client(captured: list[httpx.Request]) -> PostmarkClient:
    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"MessageID": "stub-1", "ErrorCode": 0})

    http = httpx.Client(
        base_url=POSTMARK_BASE_URL,
        transport=httpx.MockTransport(_handler),
        headers={"X-Postmark-Server-Token": "test-token"},
    )
    return PostmarkClient(
        api_token="test-token",
        from_transactional="no-reply@example.test",
        from_reply="hello@example.test",
        env="prod",
        _http=http,
    )


def _failing_client(captured: list[httpx.Request]) -> PostmarkClient:
    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(500, json={"ErrorCode": 999, "Message": "boom"})

    http = httpx.Client(
        base_url=POSTMARK_BASE_URL,
        transport=httpx.MockTransport(_handler),
        headers={"X-Postmark-Server-Token": "test-token"},
    )
    return PostmarkClient(
        api_token="test-token",
        from_transactional="no-reply@example.test",
        from_reply="hello@example.test",
        env="prod",
        _http=http,
    )


# ---------------------------------------------------------------------------
# enqueue_onboarding_sequence
# ---------------------------------------------------------------------------


def test_enqueue_inserts_all_cron_kinds(conn: sqlite3.Connection):
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    inserted = enqueue_onboarding_sequence(
        conn,
        api_key_id="hash_abcd1234",
        email="alice@example.com",
        now=base,
    )
    assert sorted(inserted) == sorted(ALL_KINDS)

    rows = conn.execute(
        "SELECT kind, send_at FROM email_schedule WHERE api_key_id = ? ORDER BY kind",
        ("hash_abcd1234",),
    ).fetchall()
    assert len(rows) == len(ALL_KINDS)
    kinds = {r["kind"] for r in rows}
    assert kinds == set(ALL_KINDS)

    # Offsets are exact days from `now`. D+0 is NOT in this map because
    # the welcome path fires synchronously from billing.py.
    offsets = {"day1": 1, "day3": 3, "day7": 7, "day14": 14, "day30": 30}
    for r in rows:
        expected = (base + timedelta(days=offsets[r["kind"]])).isoformat()
        assert r["send_at"] == expected


def test_enqueue_is_idempotent(conn: sqlite3.Connection):
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    first = enqueue_onboarding_sequence(
        conn, api_key_id="hash_abcd1234", email="alice@example.com", now=base
    )
    second = enqueue_onboarding_sequence(
        conn, api_key_id="hash_abcd1234", email="alice@example.com", now=base
    )
    assert sorted(first) == sorted(ALL_KINDS)
    assert second == []  # UNIQUE(api_key_id,kind) blocks every kind
    (n,) = conn.execute(
        "SELECT COUNT(*) FROM email_schedule WHERE api_key_id = ?",
        ("hash_abcd1234",),
    ).fetchone()
    assert n == len(ALL_KINDS)


# ---------------------------------------------------------------------------
# run_due
# ---------------------------------------------------------------------------


def test_run_due_sends_rows_past_send_at_and_marks_them(conn: sqlite3.Connection):
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    enqueue_onboarding_sequence(
        conn, api_key_id="hash_abcd1234", email="alice@example.com", now=base
    )

    # Advance to D+8 — day1, day3 and day7 are due; day14 / day30 are not.
    advanced = base + timedelta(days=8)
    captured: list[httpx.Request] = []
    summary = run_due(
        conn,
        now=advanced,
        client=_mock_client(captured),
        usage_count_fn=lambda _c, _k: 5,  # force day14 skip if it ever got picked
    )

    assert summary["picked"] == 3
    assert summary["sent"] == 3
    assert summary["failed"] == 0

    aliases_sent = [json.loads(r.content)["TemplateAlias"] for r in captured]
    assert sorted(aliases_sent) == sorted([TEMPLATE_DAY1, TEMPLATE_DAY3, TEMPLATE_DAY7])

    # day1 + day3 + day7 marked sent; day14 + day30 still pending.
    rows = conn.execute(
        "SELECT kind, sent_at FROM email_schedule WHERE api_key_id = ? ORDER BY kind",
        ("hash_abcd1234",),
    ).fetchall()
    by_kind = {r["kind"]: r["sent_at"] for r in rows}
    assert by_kind["day1"] is not None
    assert by_kind["day3"] is not None
    assert by_kind["day7"] is not None
    assert by_kind["day14"] is None
    assert by_kind["day30"] is None


def test_run_due_is_idempotent_on_rerun(conn: sqlite3.Connection):
    """A second run_due() at the same `now` must NOT re-send already-sent rows."""
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    enqueue_onboarding_sequence(
        conn, api_key_id="hash_abcd1234", email="alice@example.com", now=base
    )
    advanced = base + timedelta(days=31)  # everything due
    captured: list[httpx.Request] = []
    summary_1 = run_due(
        conn,
        now=advanced,
        client=_mock_client(captured),
        usage_count_fn=lambda _c, _k: 0,
    )
    # All cron-scheduled kinds picked in a single run.
    assert summary_1["sent"] + summary_1["skipped"] == len(ALL_KINDS)
    first_call_count = len(captured)

    summary_2 = run_due(
        conn,
        now=advanced,
        client=_mock_client(captured),
        usage_count_fn=lambda _c, _k: 0,
    )
    assert summary_2["picked"] == 0
    # No additional HTTP calls triggered on the rerun.
    assert len(captured) == first_call_count


def test_run_due_day14_active_skip_marks_sent_without_http(conn: sqlite3.Connection):
    """When usage_count > 0 at D+14 time, the send helper skips and the row
    is still stamped with sent_at so the cron stops picking it."""
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    enqueue_onboarding_sequence(
        conn, api_key_id="hash_abcd1234", email="alice@example.com", now=base
    )
    advanced = base + timedelta(days=15)
    captured: list[httpx.Request] = []
    summary = run_due(
        conn,
        now=advanced,
        client=_mock_client(captured),
        usage_count_fn=lambda _c, _k: 10,  # active customer — day14 skipped
    )

    # day1 + day3 + day7 sent (HTTP), day14 skipped (no HTTP), day30 not due
    assert summary["picked"] == 4
    assert summary["sent"] == 3
    assert summary["skipped"] == 1
    aliases_sent = [json.loads(r.content)["TemplateAlias"] for r in captured]
    assert TEMPLATE_DAY14 not in aliases_sent

    day14_row = conn.execute(
        "SELECT sent_at FROM email_schedule WHERE api_key_id = ? AND kind = 'day14'",
        ("hash_abcd1234",),
    ).fetchone()
    assert day14_row["sent_at"] is not None


def test_run_due_records_failure_without_marking_sent(conn: sqlite3.Connection):
    """Postmark 5xx → sent_at stays NULL, attempts increments, last_error set."""
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    enqueue_onboarding_sequence(
        conn, api_key_id="hash_abcd1234", email="alice@example.com", now=base
    )
    advanced = base + timedelta(days=4)  # day1 + day3 due
    captured: list[httpx.Request] = []
    summary = run_due(
        conn,
        now=advanced,
        client=_failing_client(captured),
        usage_count_fn=lambda _c, _k: 0,
    )
    assert summary["picked"] == 2
    assert summary["failed"] == 2
    assert summary["sent"] == 0

    # Both rows must remain unsent with last_error populated.
    for kind in ("day1", "day3"):
        row = conn.execute(
            "SELECT sent_at, attempts, last_error FROM email_schedule "
            "WHERE api_key_id = ? AND kind = ?",
            ("hash_abcd1234", kind),
        ).fetchone()
        assert row["sent_at"] is None, kind
        assert row["attempts"] == 1, kind
        assert row["last_error"] is not None, kind
        assert "error" in row["last_error"].lower(), kind


def test_run_due_honors_unsubscribed_recipients(conn: sqlite3.Connection):
    """A subscribers row with unsubscribed_at set suppresses the send."""
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    enqueue_onboarding_sequence(
        conn, api_key_id="hash_abcd1234", email="alice@example.com", now=base
    )
    # Mark alice as unsubscribed via the subscribers table.
    conn.execute(
        """INSERT INTO subscribers(email, source, created_at, unsubscribed_at)
           VALUES (?, ?, ?, ?)""",
        (
            "alice@example.com",
            "suppress:bounce",
            "2026-04-23T00:00:00+00:00",
            "2026-04-23T00:00:01+00:00",
        ),
    )
    advanced = base + timedelta(days=4)
    captured: list[httpx.Request] = []
    summary = run_due(
        conn,
        now=advanced,
        client=_mock_client(captured),
        usage_count_fn=lambda _c, _k: 0,
    )
    # day1 + day3 picked, both suppressed.
    assert summary["picked"] == 2
    assert summary["suppressed"] == 2
    assert summary["sent"] == 0
    assert captured == []  # no Postmark call
    for kind in ("day1", "day3"):
        row = conn.execute(
            "SELECT sent_at, last_error FROM email_schedule "
            "WHERE api_key_id = ? AND kind = ?",
            ("hash_abcd1234", kind),
        ).fetchone()
        assert row["sent_at"] is not None, kind
        assert "suppressed" in (row["last_error"] or "").lower(), kind


def test_run_due_template_model_includes_examples_for_day3(conn: sqlite3.Connection):
    """Day3 dispatch through scheduler carries the 3 pinned example unified_ids."""
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    enqueue_onboarding_sequence(
        conn, api_key_id="hash_abcd1234", email="alice@example.com", now=base
    )
    advanced = base + timedelta(days=4)
    captured: list[httpx.Request] = []
    run_due(
        conn,
        now=advanced,
        client=_mock_client(captured),
        usage_count_fn=lambda _c, _k: 0,
    )
    # day1 + day3 are both due; find the day3 envelope specifically.
    bodies = [json.loads(r.content) for r in captured]
    aliases = [b["TemplateAlias"] for b in bodies]
    assert TEMPLATE_DAY3 in aliases
    body = next(b for b in bodies if b["TemplateAlias"] == TEMPLATE_DAY3)
    ids = [e["unified_id"] for e in body["TemplateModel"]["examples"]]
    assert ids == ["UNI-14e57fbf79", "UNI-40bc849d45", "UNI-08d8284aae"]
    assert body["TemplateModel"]["tier"] == "paid"


def test_run_due_day30_fires_even_for_inactive_users(conn: sqlite3.Connection):
    """D+30 feedback ask is NOT gated on usage_count."""
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    enqueue_onboarding_sequence(
        conn, api_key_id="hash_abcd1234", email="alice@example.com", now=base
    )
    advanced = base + timedelta(days=31)
    captured: list[httpx.Request] = []
    run_due(
        conn,
        now=advanced,
        client=_mock_client(captured),
        usage_count_fn=lambda _c, _k: 0,
    )
    aliases = [json.loads(r.content)["TemplateAlias"] for r in captured]
    assert TEMPLATE_DAY30 in aliases
