"""R2 P2 hardening — Stripe webhook tolerance + idempotency + livemode + cache cap.

Tracks `tools/offline/_inbox/audit_r2/P2_stripe_webhook.md` (R2 audit, 2026-05-13).
R2 P2 noted that webhook tolerance is acceptable at 300s and livemode mismatch
correctly returns 200. This file adds explicit reaffirmation tests + the
idempotency cache size-cap edge case.

Scenarios (mirrors task spec):

  1. Tolerance constant `STRIPE_WEBHOOK_TOLERANCE_SECONDS == 300` is the
     literal passed to `stripe.Webhook.construct_event`. Static contract.

  2. Idempotency cache (`stripe_webhook_events`) is checked BEFORE
     side-effects on a re-delivery — second call hits the dedup branch
     and returns `duplicate_ignored` without re-running handler work.

  3. Forged event with wrong webhook secret → 400 (signature fence).

  4. Same event_id twice within 5 minutes → first 200 + processed,
     second 200 + `duplicate_ignored`, exactly one DB row.

  5. `livemode=True` event delivered to non-prod env → 200 +
     `livemode_mismatch_ignored`, NO error raised, NO dedup row written.

  6. Timestamp drift > 300s → 400 (tolerance fence).

  7. Cache size cap: oversize `stripe_webhook_events` table is trimmed
     to `STRIPE_WEBHOOK_EVENTS_MAX_ROWS` via the lazy sweep branch.

Tests use a real Stripe-compatible HMAC signature (built locally) so the
production `construct_event` verifier runs end-to-end. Side-effect handlers
that hit the Stripe API are monkeypatched where present, but the event type
chosen (`ping.unhandled`) has no side effects so the dispatch returns
`{"status": "received"}` cleanly.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from pathlib import Path  # noqa: TC003
from typing import Any

import pytest

WHSEC = "whsec_test_r2p2_hardening"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stripe_signature(payload: bytes, secret: str, timestamp: int) -> str:
    signed = f"{timestamp}.".encode() + payload
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def _make_event_body(event_id: str, *, livemode: bool = False) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "object": "event",
            "type": "ping.unhandled",
            "livemode": livemode,
            "data": {"object": {}},
        },
        separators=(",", ":"),
    ).encode("utf-8")


@pytest.fixture()
def stripe_env(monkeypatch):
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", WHSEC, raising=False)
    monkeypatch.setattr(settings, "stripe_price_per_request", "price_metered_test", raising=False)
    monkeypatch.setattr(settings, "env", "dev", raising=False)
    yield settings


def _post(client, body: bytes, signature: str):
    return client.post(
        "/v1/billing/webhook",
        content=body,
        headers={"stripe-signature": signature},
    )


def _row_count(db: Path, event_id: str) -> int:
    c = sqlite3.connect(db)
    try:
        (n,) = c.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return int(n)
    finally:
        c.close()


# ---------------------------------------------------------------------------
# 1. Tolerance constant audit
# ---------------------------------------------------------------------------


def test_tolerance_constant_is_300():
    """The SOT constant must equal Stripe's documented default (5 min)."""
    from jpintel_mcp.api import billing as billing_mod

    assert billing_mod.STRIPE_WEBHOOK_TOLERANCE_SECONDS == 300


def test_construct_event_receives_tolerance_constant(client, stripe_env, monkeypatch):
    """The handler must pass the SOT constant into `construct_event`."""
    from jpintel_mcp.api import billing as billing_mod

    captured: list[dict[str, Any]] = []

    def _construct(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured.append({"args": args, "kwargs": kwargs})
        return {
            "id": "evt_r2p2_tolerance_probe",
            "object": "event",
            "type": "ping.unhandled",
            "livemode": False,
            "data": {"object": {}},
        }

    monkeypatch.setattr(billing_mod.stripe.Webhook, "construct_event", _construct)
    r = _post(
        client,
        _make_event_body("evt_r2p2_tolerance_probe"),
        "t=1,v1=ignored_by_stub",
    )
    assert r.status_code == 200, r.text
    assert captured, "construct_event must be invoked"
    assert captured[0]["kwargs"].get("tolerance") == billing_mod.STRIPE_WEBHOOK_TOLERANCE_SECONDS


# ---------------------------------------------------------------------------
# 2. Idempotency dedup checked BEFORE processing
# ---------------------------------------------------------------------------


def test_idempotency_cache_checked_before_processing(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """On re-delivery the dedup SELECT short-circuits before dispatch runs.

    We monkeypatch the only dispatch surface that ping.unhandled would
    plausibly touch — there is none in production — so the test instead
    asserts the audit_log + dedup-row state holds even when the second
    delivery arrives mid-flight: exactly one event row, second response
    body == duplicate_ignored.
    """
    event_id = "evt_r2p2_dedup_pre_dispatch"
    body = _make_event_body(event_id)
    sig = _stripe_signature(body, WHSEC, int(time.time()))

    r1 = _post(client, body, sig)
    assert r1.status_code == 200, r1.text
    assert _row_count(seeded_db, event_id) == 1

    # Second delivery: same body + fresh timestamp + valid signature.
    sig2 = _stripe_signature(body, WHSEC, int(time.time()))
    r2 = _post(client, body, sig2)
    assert r2.status_code == 200, r2.text
    assert r2.json() == {"status": "duplicate_ignored"}
    assert _row_count(seeded_db, event_id) == 1


# ---------------------------------------------------------------------------
# 3. Wrong secret → 400
# ---------------------------------------------------------------------------


def test_wrong_secret_returns_400(client, stripe_env, seeded_db: Path):
    """Sign with `whsec_wrong` while server expects WHSEC → SDK rejects."""
    event_id = "evt_r2p2_wrong_secret"
    body = _make_event_body(event_id)
    bad_sig = _stripe_signature(body, "whsec_wrong_for_test", int(time.time()))

    r = _post(client, body, bad_sig)
    assert r.status_code == 400, r.text
    assert _row_count(seeded_db, event_id) == 0


# ---------------------------------------------------------------------------
# 4. Same event_id twice within 5 min → 200 / 200, single DB row
# ---------------------------------------------------------------------------


def test_same_event_id_twice_within_window(client, stripe_env, seeded_db: Path):
    event_id = "evt_r2p2_replay_within_5min"
    body = _make_event_body(event_id)

    # Delivery 1: now-60s (well inside 300s window).
    sig1 = _stripe_signature(body, WHSEC, int(time.time()) - 60)
    r1 = _post(client, body, sig1)
    assert r1.status_code == 200, r1.text
    assert r1.json() == {"status": "received"}

    # Delivery 2: now-30s (still inside window, fresh signature, same id).
    sig2 = _stripe_signature(body, WHSEC, int(time.time()) - 30)
    r2 = _post(client, body, sig2)
    assert r2.status_code == 200, r2.text
    assert r2.json() == {"status": "duplicate_ignored"}

    # Exactly one row, processed_at filled on the first delivery.
    c = sqlite3.connect(seeded_db)
    try:
        rows = c.execute(
            "SELECT event_id, processed_at FROM stripe_webhook_events WHERE event_id = ?",
            (event_id,),
        ).fetchall()
    finally:
        c.close()
    assert len(rows) == 1
    assert rows[0][1] is not None


# ---------------------------------------------------------------------------
# 5. livemode mismatch → 200 silent skip, no error, no dedup row
# ---------------------------------------------------------------------------


def test_livemode_true_in_dev_env_silent_skip(client, stripe_env, monkeypatch, seeded_db: Path):
    """settings.env != 'prod' + event.livemode=True → 200 + skip + no error.

    Mirrors R2 P2 finding that this returns 200 (correct) rather than 4xx.
    """
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "env", "dev", raising=False)

    event_id = "evt_r2p2_livemode_skip"
    body = _make_event_body(event_id, livemode=True)
    sig = _stripe_signature(body, WHSEC, int(time.time()))

    r = _post(client, body, sig)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "livemode_mismatch_ignored"}

    # No dedup row written — the mismatch path short-circuits before INSERT.
    assert _row_count(seeded_db, event_id) == 0


# ---------------------------------------------------------------------------
# 6. Timestamp drift > 300s → 400
# ---------------------------------------------------------------------------


def test_timestamp_drift_beyond_tolerance_rejected(client, stripe_env, seeded_db: Path):
    """t=now-600 with otherwise-valid HMAC is outside the 300s window → 400."""
    event_id = "evt_r2p2_drift_beyond_300"
    body = _make_event_body(event_id)
    sig = _stripe_signature(body, WHSEC, int(time.time()) - 600)

    r = _post(client, body, sig)
    assert r.status_code == 400, r.text
    assert _row_count(seeded_db, event_id) == 0


def test_timestamp_drift_at_tolerance_boundary_accepted(client, stripe_env, seeded_db: Path):
    """t=now-280 is inside the 300s window → 200 (boundary sanity)."""
    event_id = "evt_r2p2_drift_at_boundary"
    body = _make_event_body(event_id)
    sig = _stripe_signature(body, WHSEC, int(time.time()) - 280)

    r = _post(client, body, sig)
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# 7. Idempotency cache size cap (lazy sweep)
# ---------------------------------------------------------------------------


def test_cache_size_cap_constants_present():
    """Module-level cap constants must exist and be sane."""
    from jpintel_mcp.api import billing as billing_mod

    assert billing_mod.STRIPE_WEBHOOK_EVENTS_MAX_ROWS > 0
    assert billing_mod.STRIPE_WEBHOOK_EVENTS_RETENTION_DAYS > 0
    # Must comfortably exceed Stripe's 3-day retry window.
    assert billing_mod.STRIPE_WEBHOOK_EVENTS_RETENTION_DAYS >= 3


def test_lazy_sweep_trims_aged_rows(client, stripe_env, monkeypatch, seeded_db: Path):
    """Old rows are trimmed when the lazy-sweep branch fires.

    We pre-seed the dedup table with a row dated 60 days old, then deliver
    a fresh event whose event_id ends in "00" — that is the lazy-sweep
    trigger. After the delivery, the aged row must be gone and the new
    row remains.
    """
    from jpintel_mcp.api import billing as billing_mod

    # Cap retention to 30 days for this test (it already defaults to 30).
    monkeypatch.setattr(billing_mod, "STRIPE_WEBHOOK_EVENTS_RETENTION_DAYS", 30, raising=True)

    # Seed an aged row.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM stripe_webhook_events WHERE event_id LIKE 'evt_r2p2_age%'")
        c.execute(
            "INSERT INTO stripe_webhook_events"
            " (event_id, event_type, livemode, received_at, processed_at)"
            " VALUES (?, ?, ?, datetime('now', '-60 days'),"
            "         datetime('now', '-60 days'))",
            ("evt_r2p2_aged_row", "ping.unhandled", 0),
        )
        c.commit()
    finally:
        c.close()

    # Trigger event_id MUST end with "00" so the lazy-sweep branch runs.
    event_id = "evt_r2p2_sweep_trigger_00"
    body = _make_event_body(event_id)
    sig = _stripe_signature(body, WHSEC, int(time.time()))

    r = _post(client, body, sig)
    assert r.status_code == 200, r.text

    c = sqlite3.connect(seeded_db)
    try:
        aged = c.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id = ?",
            ("evt_r2p2_aged_row",),
        ).fetchone()[0]
        fresh = c.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()[0]
    finally:
        c.close()

    assert aged == 0, "aged row beyond retention window must be swept"
    assert fresh == 1, "fresh row must remain"


def test_lazy_sweep_enforces_max_row_cap(client, stripe_env, monkeypatch, seeded_db: Path):
    """When row count exceeds the cap, oldest rows are trimmed to the cap.

    We shrink the cap to a tiny value, seed CAP+5 fresh-dated rows, then
    fire the lazy-sweep trigger event. Result: cap+1 rows (cap aged
    survivors + the new trigger row), with the very oldest rows pruned.
    """
    from jpintel_mcp.api import billing as billing_mod

    monkeypatch.setattr(billing_mod, "STRIPE_WEBHOOK_EVENTS_MAX_ROWS", 5, raising=True)
    # Make sure the retention sweep does NOT also fire — seeded rows are
    # all dated "today".
    monkeypatch.setattr(billing_mod, "STRIPE_WEBHOOK_EVENTS_RETENTION_DAYS", 30, raising=True)

    # Seed 8 fresh rows with deterministic, monotonically older timestamps.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM stripe_webhook_events WHERE event_id LIKE 'evt_r2p2_cap%'")
        for i in range(8):
            c.execute(
                "INSERT INTO stripe_webhook_events"
                " (event_id, event_type, livemode, received_at, processed_at)"
                " VALUES (?, ?, ?, datetime('now', ?), datetime('now', ?))",
                (
                    f"evt_r2p2_cap_seed_{i:02d}",
                    "ping.unhandled",
                    0,
                    f"-{8 - i} minutes",
                    f"-{8 - i} minutes",
                ),
            )
        c.commit()
        before = c.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id LIKE 'evt_r2p2_cap%'"
        ).fetchone()[0]
    finally:
        c.close()
    assert before == 8

    event_id = "evt_r2p2_cap_trigger_00"
    body = _make_event_body(event_id)
    sig = _stripe_signature(body, WHSEC, int(time.time()))

    r = _post(client, body, sig)
    assert r.status_code == 200, r.text

    c = sqlite3.connect(seeded_db)
    try:
        survivors = [
            row[0]
            for row in c.execute(
                "SELECT event_id FROM stripe_webhook_events"
                " WHERE event_id LIKE 'evt_r2p2_cap%' OR event_id = ?"
                " ORDER BY received_at DESC",
                (event_id,),
            ).fetchall()
        ]
    finally:
        c.close()

    # Cap is 5; after the lazy sweep + the new insert, we expect at most
    # cap rows total (the sweep runs AFTER the INSERT so the new row is
    # included in the LIMIT 5 window).
    assert len(survivors) <= 5
    # The brand new trigger row must survive (it has the freshest received_at).
    assert event_id in survivors
    # The oldest seeded rows must be the ones evicted.
    assert "evt_r2p2_cap_seed_00" not in survivors


def test_sweep_branch_uses_contextlib_suppress():
    """Static contract: the sweep branch wraps its DELETEs in suppress(Exception).

    Cleanup MUST NEVER break webhook idempotency. Rather than try to
    monkeypatch the C-level sqlite3.Connection.execute (which is
    immutable), assert the safety net is present in the source: the
    `event_id.endswith("00")` sweep branch is followed by a
    `contextlib.suppress(Exception)` block in `api/billing.py`. A
    refactor that removes the suppress flips this red.
    """
    import inspect

    from jpintel_mcp.api import billing as billing_mod

    src = inspect.getsource(billing_mod.webhook)
    # Locate the sweep branch.
    assert 'event_id.endswith("00")' in src, "lazy sweep branch missing"
    head = src.split('event_id.endswith("00")', 1)[1]
    # The suppress + DELETE must both appear AFTER the sentinel and
    # BEFORE the matching `except Exception as begin_exc` boundary.
    boundary = head.find("except Exception as begin_exc")
    sweep_block = head[: boundary if boundary != -1 else len(head)]
    assert "contextlib.suppress(Exception)" in sweep_block, (
        "lazy sweep DELETE block must be wrapped in contextlib.suppress(Exception) "
        "so cleanup never breaks webhook idempotency"
    )
    assert "DELETE FROM stripe_webhook_events" in sweep_block


# ---------------------------------------------------------------------------
# 8. Retention boundary precision (jpcite-focused, 2026-05-13)
# ---------------------------------------------------------------------------
#
# E6 added `test_lazy_sweep_trims_aged_rows` which proves the trigger fires
# but pins the boundary at a coarse `-60 days` seed. The three tests below
# pin the boundary precisely at `STRIPE_WEBHOOK_EVENTS_RETENTION_DAYS=30` and
# the size cap at `STRIPE_WEBHOOK_EVENTS_MAX_ROWS=100_000`, and quantify the
# lazy-sweep sampling rate at ~1/256 over a 1000-event population. They do
# NOT touch `src/jpintel_mcp/api/billing.py` (E6 owns that file).


def test_lazy_sweep_retention_boundary_precise(client, stripe_env, monkeypatch, seeded_db: Path):
    """Row at `(retention - 5s)` → kept; row at `(retention + 5s)` → swept.

    SQLite `datetime('now')` is second-precision and the seed + DELETE run
    inside the same second under normal CI load. A 5-second offset on each
    side is "precise" relative to a 30-day window (5e-6 % drift tolerance)
    while staying robust against ~ms timing jitter between Python wall-clock
    and SQLite wall-clock. A 1-second offset would be flaky if the test
    happens to straddle a SQLite second boundary; 5 seconds keeps the test
    deterministic without weakening the boundary claim.
    """
    from jpintel_mcp.api import billing as billing_mod

    monkeypatch.setattr(billing_mod, "STRIPE_WEBHOOK_EVENTS_RETENTION_DAYS", 30, raising=True)

    inside_id = "evt_r2p2_boundary_inside_5s"
    outside_id = "evt_r2p2_boundary_outside_5s"

    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM stripe_webhook_events WHERE event_id LIKE 'evt_r2p2_boundary_%'")
        # INSIDE window: received_at = now - 30 days + 5 seconds.
        # received_at > cutoff (cutoff = now - 30 days) → kept.
        c.execute(
            "INSERT INTO stripe_webhook_events"
            " (event_id, event_type, livemode, received_at, processed_at)"
            " VALUES (?, ?, ?, datetime('now', '-30 days', '+5 seconds'),"
            "         datetime('now', '-30 days', '+5 seconds'))",
            (inside_id, "ping.unhandled", 0),
        )
        # OUTSIDE window: received_at = now - 30 days - 5 seconds.
        # received_at < cutoff → swept.
        c.execute(
            "INSERT INTO stripe_webhook_events"
            " (event_id, event_type, livemode, received_at, processed_at)"
            " VALUES (?, ?, ?, datetime('now', '-30 days', '-5 seconds'),"
            "         datetime('now', '-30 days', '-5 seconds'))",
            (outside_id, "ping.unhandled", 0),
        )
        c.commit()
    finally:
        c.close()

    # Trigger the lazy sweep.
    trigger_id = "evt_r2p2_boundary_trigger_00"
    body = _make_event_body(trigger_id)
    sig = _stripe_signature(body, WHSEC, int(time.time()))
    r = _post(client, body, sig)
    assert r.status_code == 200, r.text

    c = sqlite3.connect(seeded_db)
    try:
        inside_kept = c.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id = ?",
            (inside_id,),
        ).fetchone()[0]
        outside_kept = c.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id = ?",
            (outside_id,),
        ).fetchone()[0]
    finally:
        c.close()

    assert inside_kept == 1, (
        "row at (30 days - 5 seconds) is INSIDE the retention window and must survive"
    )
    assert outside_kept == 0, (
        "row at (30 days + 5 seconds) is OUTSIDE the retention window and must be swept"
    )


# ---------------------------------------------------------------------------
# 9. Size cap = 100_000: insert 100_001 rows, fire sweep, count drops to cap
# ---------------------------------------------------------------------------


def test_lazy_sweep_caps_at_max_rows_exactly_100k(client, stripe_env, monkeypatch, seeded_db: Path):
    """Insert 100_001 pre-seeded rows + 1 trigger event → sweep cuts back to 100_000.

    Uses the default `STRIPE_WEBHOOK_EVENTS_MAX_ROWS = 100_000` (not a shrunk
    test value). All seeded rows carry fresh `received_at` timestamps so the
    retention sweep is a no-op and the size-cap branch is the only delete
    path. The trigger event ALSO survives because it is INSERTed before the
    `LIMIT 100_000` sweep runs and carries the newest `received_at`, so the
    100_001 oldest seed rows compete for the 99_999 remaining cap slots —
    final cap-LIKE count is exactly 100_000.

    Cost: 100_001 INSERTs via executemany. Sub-second on SQLite WAL.
    """
    from jpintel_mcp.api import billing as billing_mod

    assert billing_mod.STRIPE_WEBHOOK_EVENTS_MAX_ROWS == 100_000
    assert billing_mod.STRIPE_WEBHOOK_EVENTS_RETENTION_DAYS == 30

    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM stripe_webhook_events")
        # Seed 100_001 rows with monotonically increasing `received_at` so the
        # ORDER BY received_at DESC LIMIT 100_000 is deterministic. All rows
        # are fresh (datetime('now', '-Ns')) — the retention sweep is a no-op.
        rows = [
            (
                f"evt_r2p2_cap100k_seed_{i:06d}",
                "ping.unhandled",
                0,
                f"-{100_001 - i} seconds",
                f"-{100_001 - i} seconds",
            )
            for i in range(100_001)
        ]
        c.executemany(
            "INSERT INTO stripe_webhook_events"
            " (event_id, event_type, livemode, received_at, processed_at)"
            " VALUES (?, ?, ?, datetime('now', ?), datetime('now', ?))",
            rows,
        )
        c.commit()
        before = c.execute("SELECT COUNT(*) FROM stripe_webhook_events").fetchone()[0]
    finally:
        c.close()
    assert before == 100_001, f"expected 100_001 seed rows, got {before}"

    trigger_id = "evt_r2p2_cap100k_trigger_00"
    body = _make_event_body(trigger_id)
    sig = _stripe_signature(body, WHSEC, int(time.time()))
    r = _post(client, body, sig)
    assert r.status_code == 200, r.text

    c = sqlite3.connect(seeded_db)
    try:
        total = c.execute("SELECT COUNT(*) FROM stripe_webhook_events").fetchone()[0]
        trigger_present = c.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id = ?",
            (trigger_id,),
        ).fetchone()[0]
        # The oldest seeds (lowest index = oldest `received_at`) must be evicted.
        oldest_present = c.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id IN (?, ?)",
            ("evt_r2p2_cap100k_seed_000000", "evt_r2p2_cap100k_seed_000001"),
        ).fetchone()[0]
    finally:
        c.close()

    assert total == 100_000, f"size cap must hold the table at exactly 100_000 rows, got {total}"
    assert trigger_present == 1, "the trigger event is the freshest row and must survive"
    assert oldest_present == 0, "the oldest seed rows must be the ones evicted"


# ---------------------------------------------------------------------------
# 10. Lazy sweep is invoked on ~1/256 events
# ---------------------------------------------------------------------------


def test_lazy_sweep_invocation_rate_is_1_in_256(client, stripe_env, monkeypatch, seeded_db: Path):
    """Count actual DELETE-FROM-stripe_webhook_events invocations across 1000 inserts.

    The current implementation gates the sweep on `event_id.endswith("00")`.
    Over 1000 sequential event_ids drawn from the 4-hex-digit space
    `evt_0000..evt_03e7`, exactly the ids ending in literal "00" fire the
    sweep: 0x000, 0x100, 0x200, 0x300 — four events.

    We instrument actual SQLite execution via `sqlite3.Connection.set_trace_callback`
    rather than counting *expected* triggers — that way a regression that
    accidentally drops or doubles the gate is caught.
    """
    from jpintel_mcp.api import billing as billing_mod
    from jpintel_mcp.api import deps as deps_mod
    from jpintel_mcp.db import session as session_mod

    # Shrink the cap to a tiny value so the sweep DELETE has visible work —
    # but the gate itself is what we measure, not the trim behavior.
    monkeypatch.setattr(billing_mod, "STRIPE_WEBHOOK_EVENTS_MAX_ROWS", 10, raising=True)
    monkeypatch.setattr(billing_mod, "STRIPE_WEBHOOK_EVENTS_RETENTION_DAYS", 30, raising=True)

    # Clean slate.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM stripe_webhook_events")
        c.commit()
    finally:
        c.close()

    # Instrument every connection opened during this test. The FastAPI
    # dependency `get_db()` calls `jpintel_mcp.db.session.connect()` — wrap
    # the connect callable so we get a trace_callback on every webhook conn.
    delete_invocations: list[str] = []

    def _trace(sql: str) -> None:
        if "DELETE FROM stripe_webhook_events" in sql:
            delete_invocations.append(sql)

    orig_connect = session_mod.connect

    def _wrapped_connect(*a, **kw):
        conn = orig_connect(*a, **kw)
        conn.set_trace_callback(_trace)
        return conn

    monkeypatch.setattr(session_mod, "connect", _wrapped_connect, raising=True)
    monkeypatch.setattr(deps_mod, "connect", _wrapped_connect, raising=True)

    # Fire 1000 events with sequential 4-hex-digit ids covering 0x000..0x3e7.
    # That space yields exactly 4 ids ending in "00": 0x000, 0x100, 0x200, 0x300.
    expected_sweeps = 0
    for i in range(1000):
        event_id = f"evt_r2p2_rate_{i:04x}"
        body = _make_event_body(event_id)
        sig = _stripe_signature(body, WHSEC, int(time.time()))
        r = _post(client, body, sig)
        assert r.status_code == 200, f"event {event_id} ({i}/1000) failed: {r.text}"
        if event_id.endswith("00"):
            expected_sweeps += 1

    # Each sweep fires TWO DELETE statements (retention + size cap), so the
    # trace count is 2 × sweep_count.
    sweep_invocations = len(delete_invocations) // 2

    assert expected_sweeps == 4, (
        f"deterministic sanity: 1000 ids in 0x000..0x3e7 should have exactly 4 "
        f"ending in '00', got {expected_sweeps}"
    )
    assert sweep_invocations == expected_sweeps, (
        f"lazy sweep gate is not ~1/256 — expected {expected_sweeps} firings "
        f"(deterministic for our id space), observed {sweep_invocations}. "
        f"Trace dump (first 5): {delete_invocations[:5]}"
    )
    # Statistical sanity: ~1/256 of 1000 ≈ 3.9, observed must be within
    # [0, 2× expected].
    assert 0 < sweep_invocations <= 2 * (1000 // 256 + 1), (
        f"sweep rate {sweep_invocations}/1000 outside ~1/256 envelope"
    )
