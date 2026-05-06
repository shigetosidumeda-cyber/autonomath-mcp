"""Customer-cap middleware fail-CLOSED contract (MASTER_PLAN_v1 §4 §A2).

When the cap evaluation cannot complete (DB lock, broken cache, schema
mismatch, hash failure), the middleware MUST return 503 with
``error=cap_unavailable`` instead of letting the request through to the
router. Letting it through would emit a Stripe-billable usage_events row
the customer's cap was supposed to prevent — a 赤字 (loss) structure at
¥0.5/req marginal cost.

This file pins the new behavior so a future refactor cannot silently
re-introduce the fail-OPEN path that previously did
``await call_next(request)`` on every except branch.
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.deps import hash_api_key
from jpintel_mcp.api.middleware import customer_cap as cap_mod
from jpintel_mcp.billing.keys import issue_key

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_cap_cache():
    """Drop the in-process cap cache between tests so a stale entry from
    one test cannot mask the failure path under test in another.
    """
    from jpintel_mcp.api import middleware as _mw

    _mw._reset_cap_cache_state()
    yield
    _mw._reset_cap_cache_state()


@pytest.fixture()
def fresh_paid_key(seeded_db: Path) -> str:
    """A one-shot paid key so each test owns its own cap-cache slot."""
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    sub_id = f"sub_capfc_{uuid.uuid4().hex[:8]}"
    raw = issue_key(
        c,
        customer_id=f"cus_capfc_{uuid.uuid4().hex[:8]}",
        tier="paid",
        stripe_subscription_id=sub_id,
    )
    c.commit()
    c.close()
    return raw


# ---------------------------------------------------------------------------
# Fail-closed: _cap_status raises (DB lock simulated) -> 503 cap_unavailable
# ---------------------------------------------------------------------------


def test_cap_status_dblock_returns_503_cap_unavailable(
    client: TestClient,
    fresh_paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If _cap_status raises (e.g. SQLite database is locked), the request
    must 503 with cap_unavailable and the router must NOT run.

    This pins the fail-CLOSED contract introduced in MASTER_PLAN_v1 §4 §A2.
    Pre-fix behavior was ``await call_next(request)`` which served the
    request uncapped and emitted a Stripe usage_events row.
    """

    def _boom(_conn, _key_hash):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cap_mod, "_cap_status", _boom)

    r = client.get(
        "/v1/programs/search",
        params={"q": "テスト"},
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["error"] == "cap_unavailable", body
    assert "コスト上限" in body["message"], body


def test_cap_status_connect_failure_returns_503_cap_unavailable(
    client: TestClient,
    fresh_paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If db.session.connect() itself raises, the request must 503
    cap_unavailable rather than fall through to the router.
    """

    def _boom_connect(*_a, **_kw):
        raise sqlite3.OperationalError("database is locked")

    # connect() is imported lazily inside dispatch(); patch at the source
    # module so the lazy import sees the boom.
    import jpintel_mcp.db.session as _sess

    monkeypatch.setattr(_sess, "connect", _boom_connect)

    r = client.get(
        "/v1/programs/search",
        params={"q": "テスト"},
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["error"] == "cap_unavailable", body
    assert "コスト上限" in body["message"], body


def test_cap_status_hash_failure_returns_503_cap_unavailable(
    client: TestClient,
    fresh_paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If hash_api_key raises, the middleware must 503 cap_unavailable
    instead of bypassing the cap check entirely.
    """

    def _boom_hash(_raw: str) -> str:
        raise RuntimeError("hash backend offline")

    import jpintel_mcp.api.deps as _deps

    monkeypatch.setattr(_deps, "hash_api_key", _boom_hash)

    r = client.get(
        "/v1/programs/search",
        params={"q": "テスト"},
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["error"] == "cap_unavailable", body
    assert "コスト上限" in body["message"], body


# ---------------------------------------------------------------------------
# Side-effect: a fail-closed 503 must NOT create a usage_events row.
# (Router never ran, so log_usage was never called.)
# ---------------------------------------------------------------------------


def test_fail_closed_does_not_create_usage_events_row(
    client: TestClient,
    fresh_paid_key: str,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 503 cap_unavailable must NOT bill the customer. Verify usage_events
    is empty for the key after the failed request.
    """

    def _boom(_conn, _key_hash):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cap_mod, "_cap_status", _boom)

    r = client.get(
        "/v1/programs/search",
        params={"q": "テスト"},
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code == 503, r.text

    c = sqlite3.connect(seeded_db)
    try:
        (n,) = c.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ?",
            (hash_api_key(fresh_paid_key),),
        ).fetchone()
    finally:
        c.close()
    assert n == 0, "fail-closed 503 must not bill the customer"


# ---------------------------------------------------------------------------
# Carve-out: control-plane endpoints stay reachable even if cap eval breaks.
# /v1/me/cap is matched BEFORE the failure-prone block; user must still be
# able to lower / clear their cap.
# ---------------------------------------------------------------------------


def test_control_plane_remains_reachable_under_dblock(
    client: TestClient,
    fresh_paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even when _cap_status would raise, /v1/me/cap stays reachable.

    The dispatcher's path-based carve-out runs before the cap evaluation,
    so a customer can still raise / clear their own cap during a transient
    DB issue.
    """

    def _boom(_conn, _key_hash):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cap_mod, "_cap_status", _boom)

    r = client.post(
        "/v1/me/cap",
        json={"monthly_cap_yen": None},
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "monthly_cap_yen": None}


# ---------------------------------------------------------------------------
# DD-01: post-authorize increment failure must NOT 5xx the customer.
# The cap check passed, the router served the response, the customer paid for
# what they got. A failure inside note_cap_usage (cache eviction race / lock
# contention) is operational noise, not a billing event. Verify 200 OK is
# returned and a WARNING is logged so ops can investigate.
# ---------------------------------------------------------------------------


def test_increment_failure_after_authorize_returns_200(
    client: TestClient,
    fresh_paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cap check authorizes -> router runs -> note_cap_usage raises.

    DD-01 contract: don't double-jeopardize the customer who already paid.
    The cap-cache increment is a tightener for the next request, not a
    billing source. Failure here is logged at WARNING and swallowed; the
    next request will re-read from DB.
    """

    def _boom_note(*_a, **_kw):
        raise RuntimeError("cap cache out of sync")

    monkeypatch.setattr(cap_mod, "note_cap_usage", _boom_note)

    with caplog.at_level("WARNING", logger="jpintel.cap"):
        r = client.get(
            "/v1/programs/search",
            params={"q": "テスト"},
            headers={"X-API-Key": fresh_paid_key},
        )
    assert r.status_code == 200, r.text
    # The exact log message ("cap_cache_increment_failed") is the post-DD-01
    # contract. Until the production patch lands, this assertion stays RED:
    # note_cap_usage call sites do not yet wrap in try/except + WARNING log.
    assert any("cap_cache_increment_failed" in (rec.message or "") for rec in caplog.records), [
        rec.message for rec in caplog.records
    ]
