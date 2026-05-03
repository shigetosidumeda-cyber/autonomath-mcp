"""Tests for the houjin_watch (mig 088) overlay in dispatch_webhooks.

R14 (analysis_wave18/research_R14_ma_cohort_2026-05-03.md §1.4) flagged
the M&A cohort launch blocker: the dispatcher advertised houjin_watch as
the real-time amendment surface but never actually read `customer_watches`.
The collector and per-key fan-out below close that gap.

Coverage:
  * houjin watch fan-out by kind (enforcement / invoice / amendment)
  * watch-scoped events do NOT broadcast to non-watching keys
  * non-watch event types (program.created) keep the legacy global fan-out
  * `last_event_at` is bumped on successful delivery
  * absent customer_watches table degrades gracefully (no crash)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from jpintel_mcp.billing.keys import issue_key

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_TEST_HOUJIN_A = "1234567890123"
_TEST_HOUJIN_B = "9876543210987"
_TEST_HOUJIN_C = "5555555555555"


@pytest.fixture()
def watch_key(seeded_db: Path) -> str:
    """Authenticated paid key for watch tests."""
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_watch_test",
        tier="paid",
        stripe_subscription_id="sub_watch_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture()
def other_key(seeded_db: Path) -> str:
    """Second paid key — used to assert per-key scoping."""
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_watch_other",
        tier="paid",
        stripe_subscription_id="sub_watch_other",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _ensure_watch_tables(seeded_db: Path):
    """Apply migrations 080 + 088 onto the test DB and clear rows between cases."""
    repo = Path(__file__).resolve().parent.parent
    for mig in ("080_customer_webhooks.sql", "088_houjin_watch.sql"):
        sql = (repo / "scripts" / "migrations" / mig).read_text(encoding="utf-8")
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
        c.execute("DELETE FROM customer_watches")
        # Wipe corpora rows that other dispatcher tests may have seeded.
        c.execute("DELETE FROM enforcement_cases")
        c.execute(
            "DELETE FROM invoice_registrants "
            "WHERE invoice_registration_number LIKE 'T999%'"
        )
        c.commit()
    finally:
        c.close()
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockResponse:
    def __init__(self, status_code: int = 200, text: str = ""):
        self.status_code = status_code
        self.text = text
        self.is_success = 200 <= status_code < 300


class _MockClient:
    """Capturing httpx.Client double — same pattern as test_customer_webhooks."""

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
    secret: str = "whsec_test",
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


def _register_watch(
    db_path: Path,
    api_key_hash: str,
    watch_kind: str,
    target_id: str,
) -> int:
    c = sqlite3.connect(db_path)
    try:
        cur = c.execute(
            "INSERT INTO customer_watches(api_key_hash, watch_kind, target_id, "
            "registered_at, status, created_at, updated_at) "
            "VALUES (?, ?, ?, datetime('now'), 'active', "
            "datetime('now'), datetime('now'))",
            (api_key_hash, watch_kind, target_id),
        )
        c.commit()
        return int(cur.lastrowid or 0)
    finally:
        c.close()


def _seed_enforcement_for_houjin(
    db_path: Path,
    case_id: str,
    houjin_bangou: str | None,
) -> None:
    c = sqlite3.connect(db_path)
    try:
        c.execute(
            "INSERT OR REPLACE INTO enforcement_cases("
            "  case_id, event_type, recipient_houjin_bangou, recipient_name,"
            "  ministry, prefecture, amount_yen, reason_excerpt,"
            "  source_url, disclosed_date, fetched_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))",
            (
                case_id,
                "subsidy_exclude",
                houjin_bangou,
                "テスト被処分法人",
                "農林水産省",
                "東京都",
                3_000_000,
                "目的外使用",
                f"https://example.gov.jp/enf/{case_id}",
                "2025-09-01",
            ),
        )
        c.commit()
    finally:
        c.close()


def _seed_invoice_for_houjin(
    db_path: Path,
    invoice_no: str,
    houjin_bangou: str,
) -> None:
    c = sqlite3.connect(db_path)
    try:
        c.execute(
            "INSERT OR REPLACE INTO invoice_registrants("
            "  invoice_registration_number, houjin_bangou, normalized_name,"
            "  prefecture, registered_date, registrant_kind, source_url,"
            "  fetched_at, updated_at"
            ") VALUES (?,?,?,?,?,?,?, datetime('now'), datetime('now'))",
            (
                invoice_no,
                houjin_bangou,
                "テスト法人",
                "東京都",
                "2024-01-01",
                "corporation",
                f"https://example.gov.jp/invoice/{invoice_no}",
            ),
        )
        c.commit()
    finally:
        c.close()


def _patch_dispatcher(monkeypatch, mock_client):
    """Common monkeypatches: httpx, sleep, billing, URL safety."""
    import httpx as _httpx

    monkeypatch.setattr(_httpx, "Client", lambda *a, **k: mock_client)
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks.time.sleep", lambda _s: None,
    )
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._bill_one_delivery",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._is_safe_webhook",
        lambda url: (True, None),
    )


# ---------------------------------------------------------------------------
# Tests — kind-based fan-out
# ---------------------------------------------------------------------------


def test_houjin_watch_fans_out_enforcement_only_to_watching_key(
    seeded_db, watch_key, other_key, monkeypatch,
):
    """A 'houjin' watch on bangou A fires enforcement.added for A-targeted
    rows ONLY to the watching key. The non-watching key (with the same
    enforcement.added subscription) must NOT receive the watched houjin's
    event — preventing the over-billing R14 flagged.

    A separate enforcement row for an unwatched bangou is seeded to
    confirm the LEGACY global path still works for non-watched houjins
    (delivered to BOTH keys).
    """
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    watcher_hash = hash_api_key(watch_key)
    other_hash = hash_api_key(other_key)

    # Both keys subscribe to enforcement.added.
    _register_webhook(
        seeded_db, watcher_hash, "https://hooks.example.com/watcher",
        ["enforcement.added"], secret="whsec_watcher",
    )
    _register_webhook(
        seeded_db, other_hash, "https://hooks.example.com/other",
        ["enforcement.added"], secret="whsec_other",
    )
    # Only the first key registers a houjin watch on A.
    _register_watch(seeded_db, watcher_hash, "houjin", _TEST_HOUJIN_A)

    # Seed an enforcement row for the watched houjin.
    _seed_enforcement_for_houjin(seeded_db, "ENF-A-1", _TEST_HOUJIN_A)
    # And one with an unrelated houjin to confirm legacy fan-out still
    # works for non-watched bangous.
    _seed_enforcement_for_houjin(seeded_db, "ENF-B-1", _TEST_HOUJIN_B)

    mock = _MockClient(responses=[(200, "")] * 8)
    _patch_dispatcher(monkeypatch, mock)

    summary = dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )

    # Watch surface metric reported separately so future drift surfaces
    # in the dispatcher heartbeat.
    assert summary["houjin_watch_events"] >= 1

    # Map each delivery to (url, payload).
    deliveries = []
    for url, body, _hdrs in mock.calls:
        payload = json.loads(body.decode())
        deliveries.append((url, payload))

    # ENF-A-1 (watched houjin): delivered ONLY to the watcher, with watch
    # metadata. Must NOT appear at the non-watching URL.
    watched_payloads_at_watcher = [
        p for u, p in deliveries
        if u == "https://hooks.example.com/watcher"
        and p["data"].get("recipient_houjin_bangou") == _TEST_HOUJIN_A
    ]
    assert len(watched_payloads_at_watcher) == 1
    assert watched_payloads_at_watcher[0]["data"]["watch_kind"] == "houjin"
    assert watched_payloads_at_watcher[0]["data"]["watch_target_id"] == _TEST_HOUJIN_A

    watched_payloads_at_other = [
        p for u, p in deliveries
        if u == "https://hooks.example.com/other"
        and p["data"].get("recipient_houjin_bangou") == _TEST_HOUJIN_A
    ]
    assert watched_payloads_at_other == [], (
        "the non-watching key must NOT receive enforcement events "
        "for a houjin that the OTHER key registered as a watch — "
        "this is the R14 launch blocker"
    )

    # ENF-B-1 (unwatched houjin): delivered to BOTH keys via the legacy
    # global fan-out path (no watch metadata).
    legacy_b_payloads = [
        p for _u, p in deliveries
        if p["data"].get("recipient_houjin_bangou") == _TEST_HOUJIN_B
    ]
    assert len(legacy_b_payloads) == 2
    for p in legacy_b_payloads:
        assert "watch_kind" not in p["data"]


def test_houjin_watch_fans_out_invoice_registrant(
    seeded_db, watch_key, monkeypatch,
):
    """The 'houjin' watch surface delivers invoice_registrant.matched even
    though the global collector is still a placeholder. R14: the M&A
    cohort needs invoice inflection on a known houjin.
    """
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    watcher_hash = hash_api_key(watch_key)
    _register_webhook(
        seeded_db, watcher_hash, "https://hooks.example.com/inv",
        ["invoice_registrant.matched"], secret="whsec_inv",
    )
    _register_watch(seeded_db, watcher_hash, "houjin", _TEST_HOUJIN_C)

    _seed_invoice_for_houjin(seeded_db, f"T999{_TEST_HOUJIN_C[:10]}", _TEST_HOUJIN_C)
    # Decoy invoice for an unwatched houjin.
    _seed_invoice_for_houjin(seeded_db, f"T999{_TEST_HOUJIN_B[:10]}", _TEST_HOUJIN_B)

    mock = _MockClient(responses=[(200, "")])
    _patch_dispatcher(monkeypatch, mock)

    summary = dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )

    assert summary["deliveries_succeeded"] == 1
    sent_url, sent_body, sent_headers = mock.calls[0]
    payload = json.loads(sent_body.decode())
    assert payload["event_type"] == "invoice_registrant.matched"
    assert payload["data"]["watch_kind"] == "houjin"
    assert payload["data"]["houjin_bangou"] == _TEST_HOUJIN_C


def test_kind_fan_out_per_event_type(seeded_db, watch_key, monkeypatch):
    """Single watch on bangou A subscribed to BOTH enforcement.added and
    invoice_registrant.matched receives one delivery per matching corpus row.
    """
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    watcher_hash = hash_api_key(watch_key)
    _register_webhook(
        seeded_db, watcher_hash, "https://hooks.example.com/multi",
        ["enforcement.added", "invoice_registrant.matched"],
        secret="whsec_multi",
    )
    _register_watch(seeded_db, watcher_hash, "houjin", _TEST_HOUJIN_A)

    _seed_enforcement_for_houjin(seeded_db, "ENF-A-2", _TEST_HOUJIN_A)
    _seed_invoice_for_houjin(seeded_db, f"T999{_TEST_HOUJIN_A[:10]}", _TEST_HOUJIN_A)

    mock = _MockClient(responses=[(200, ""), (200, "")])
    _patch_dispatcher(monkeypatch, mock)

    summary = dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )

    assert summary["deliveries_succeeded"] == 2
    delivered_event_types = sorted(
        json.loads(b.decode())["event_type"] for _u, b, _h in mock.calls
    )
    assert delivered_event_types == [
        "enforcement.added",
        "invoice_registrant.matched",
    ]


def test_houjin_watch_does_not_affect_program_created_global_fanout(
    seeded_db, watch_key, monkeypatch,
):
    """Non-watch event types (program.created) keep the legacy global
    fan-out — registering a houjin watch must NOT suppress unrelated
    deliveries.
    """
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    watcher_hash = hash_api_key(watch_key)
    _register_webhook(
        seeded_db, watcher_hash, "https://hooks.example.com/global",
        ["program.created"], secret="whsec_global",
    )
    # Even though we register a houjin watch, program.created events have
    # no `_target_api_key_hashes` so the legacy path applies.
    _register_watch(seeded_db, watcher_hash, "houjin", _TEST_HOUJIN_A)

    # Backdate the seeded programs and seed a fresh one in-window.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("UPDATE programs SET updated_at = '1990-01-01T00:00:00+00:00'")
        c.execute(
            "INSERT OR REPLACE INTO programs("
            "  unified_id, primary_name, official_url, source_url, prefecture,"
            "  program_kind, tier, excluded, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, 0, datetime('now'))",
            (
                "P-WATCH-GLOBAL",
                "Test Program global",
                "https://example.gov/p",
                "https://example.gov/p/source",
                "全国",
                "subsidy",
                "A",
            ),
        )
        c.commit()
    finally:
        c.close()

    mock = _MockClient(responses=[(200, "")])
    _patch_dispatcher(monkeypatch, mock)

    summary = dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )

    assert summary["deliveries_succeeded"] == 1
    # program.created has NO watch envelope.
    payload = json.loads(mock.calls[0][1].decode())
    assert payload["event_type"] == "program.created"
    assert "watch_kind" not in payload["data"]


def test_houjin_watch_bumps_last_event_at_on_success(
    seeded_db, watch_key, monkeypatch,
):
    """Successful delivery updates customer_watches.last_event_at so the
    /v1/me/watches dashboard reflects the most recent event firing.
    """
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    watcher_hash = hash_api_key(watch_key)
    _register_webhook(
        seeded_db, watcher_hash, "https://hooks.example.com/bump",
        ["enforcement.added"], secret="whsec_bump",
    )
    watch_id = _register_watch(seeded_db, watcher_hash, "houjin", _TEST_HOUJIN_A)
    _seed_enforcement_for_houjin(seeded_db, "ENF-BUMP-1", _TEST_HOUJIN_A)

    # Pre-condition: last_event_at is NULL.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    pre = c.execute(
        "SELECT last_event_at FROM customer_watches WHERE id = ?", (watch_id,),
    ).fetchone()
    c.close()
    assert pre["last_event_at"] is None

    mock = _MockClient(responses=[(200, "")])
    _patch_dispatcher(monkeypatch, mock)

    summary = dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )

    assert summary["deliveries_succeeded"] == 1

    # Post-condition: last_event_at is set to a non-empty ISO timestamp.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    post = c.execute(
        "SELECT last_event_at FROM customer_watches WHERE id = ?", (watch_id,),
    ).fetchone()
    c.close()
    assert post["last_event_at"] is not None
    assert len(post["last_event_at"]) >= 10  # ISO date-ish


def test_disabled_watch_is_ignored(seeded_db, watch_key, monkeypatch):
    """A watch with status='disabled' must NOT scope events.

    The watcher's webhook still subscribes to enforcement.added, so the
    legacy global fan-out path also does NOT apply (no _target_api_key_hashes
    on the global enforcement collector — wait, it DOES go global). Confirm
    the disabled watch is not consulted: the legacy enforcement collector
    fans out globally, so the watcher receives the event via the global
    path, NOT via the watch overlay (i.e. no watch metadata in payload).
    """
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    watcher_hash = hash_api_key(watch_key)
    _register_webhook(
        seeded_db, watcher_hash, "https://hooks.example.com/disabled",
        ["enforcement.added"], secret="whsec_disabled",
    )
    watch_id = _register_watch(seeded_db, watcher_hash, "houjin", _TEST_HOUJIN_A)
    # Disable the watch.
    c = sqlite3.connect(seeded_db)
    c.execute(
        "UPDATE customer_watches SET status = 'disabled', "
        "disabled_at = datetime('now'), disabled_reason = 'test' "
        "WHERE id = ?",
        (watch_id,),
    )
    c.commit()
    c.close()

    _seed_enforcement_for_houjin(seeded_db, "ENF-DIS-1", _TEST_HOUJIN_A)

    mock = _MockClient(responses=[(200, "")])
    _patch_dispatcher(monkeypatch, mock)

    summary = dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )

    # Watch surface emits zero events because the watch is disabled.
    assert summary["houjin_watch_events"] == 0
    # Legacy global enforcement.added still delivers (one row, one webhook).
    assert summary["deliveries_succeeded"] == 1
    payload = json.loads(mock.calls[0][1].decode())
    assert "watch_kind" not in payload["data"]


def test_missing_customer_watches_table_does_not_crash(
    seeded_db, watch_key, monkeypatch,
):
    """If migration 088 is not yet applied (cold DB), the dispatcher must
    keep working — `_load_active_watches` swallows OperationalError.
    """
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    watcher_hash = hash_api_key(watch_key)
    _register_webhook(
        seeded_db, watcher_hash, "https://hooks.example.com/cold",
        ["enforcement.added"], secret="whsec_cold",
    )
    _seed_enforcement_for_houjin(seeded_db, "ENF-COLD-1", _TEST_HOUJIN_A)

    # Drop customer_watches mid-test to simulate the migration-pending case.
    c = sqlite3.connect(seeded_db)
    c.execute("DROP TABLE customer_watches")
    c.commit()
    c.close()

    mock = _MockClient(responses=[(200, "")])
    _patch_dispatcher(monkeypatch, mock)

    summary = dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )
    assert summary["houjin_watch_events"] == 0
    assert summary["deliveries_succeeded"] == 1


# ---------------------------------------------------------------------------
# Unit tests — collector helpers
# ---------------------------------------------------------------------------


def test_load_active_watches_groups_by_kind_and_target(seeded_db, watch_key, other_key):
    """`_load_active_watches` groups api_key_hashes by (kind, target_id)."""
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron.dispatch_webhooks import _load_active_watches

    a_hash = hash_api_key(watch_key)
    b_hash = hash_api_key(other_key)
    # Two keys watching the same houjin + a 'program' watch on a separate id.
    _register_watch(seeded_db, a_hash, "houjin", _TEST_HOUJIN_A)
    _register_watch(seeded_db, b_hash, "houjin", _TEST_HOUJIN_A)
    _register_watch(seeded_db, a_hash, "program", "UNI-test-s-1")

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        watches = _load_active_watches(c)
    finally:
        c.close()

    assert "houjin" in watches
    assert "program" in watches
    assert watches["houjin"][_TEST_HOUJIN_A] == {a_hash, b_hash}
    assert watches["program"]["UNI-test-s-1"] == {a_hash}


def test_collect_houjin_watch_events_no_active_watches_returns_empty(seeded_db):
    """No active 'houjin' watches → collector short-circuits to []."""
    from scripts.cron.dispatch_webhooks import _collect_houjin_watch_events

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        events = _collect_houjin_watch_events(
            c, Path("/tmp/__no_such_autonomath.db__"),
            "2000-01-01T00:00:00+00:00",
        )
    finally:
        c.close()
    assert events == []
