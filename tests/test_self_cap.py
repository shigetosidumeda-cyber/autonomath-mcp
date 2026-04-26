"""P3-W: customer self-serve monthly spend cap (analysis_wave18 dd_v8_09).

Verifies the three contract clauses stated in the merge plan:

  1. POST /v1/me/cap with `{monthly_cap_yen: N}` persists N to api_keys.
  2. Once month-to-date metered+successful usage * ¥3 reaches N, requests on
     non-control-plane endpoints return 503 with `cap_reached: true` and the
     full spec body. The router never runs (no usage_events row created).
  3. POST /v1/me/cap with `{monthly_cap_yen: null}` clears the cap and
     uncaps the same customer.

Isolation contract:
  Each test uses a fresh `paid_key` so the cache and usage_events of one test
  cannot affect another. The cap middleware cache is reset between tests via
  an autouse fixture.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.deps import hash_api_key
from jpintel_mcp.billing.keys import issue_key

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


_JST = timezone(timedelta(hours=9))


@pytest.fixture(autouse=True)
def _reset_cap_cache():
    """Drop the in-process cap-cache between tests so a stale entry from one
    test cannot mask a different cap configuration in the next.
    """
    from jpintel_mcp.api import middleware as _mw

    _mw._reset_cap_cache_state()
    yield
    _mw._reset_cap_cache_state()


@pytest.fixture()
def fresh_paid_key(seeded_db: Path) -> str:
    """One-shot paid key for a single test (prevents quota / count bleed)."""
    import uuid

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    sub_id = f"sub_cap_{uuid.uuid4().hex[:8]}"
    raw = issue_key(
        c,
        customer_id=f"cus_cap_{uuid.uuid4().hex[:8]}",
        tier="paid",
        stripe_subscription_id=sub_id,
    )
    c.commit()
    c.close()
    return raw


def _seed_metered_successes(
    db_path: Path, key_hash: str, count: int
) -> None:
    """Insert `count` metered+successful usage_events rows for the current
    JST month so the cap middleware's COUNT(*) sees a known value.
    """
    now_jst = datetime.now(_JST)
    # Place the rows mid-month so they are unambiguously within the JST month.
    base = now_jst.replace(day=1, hour=12, minute=0, second=0, microsecond=0)
    rows = []
    for i in range(count):
        ts = (base + timedelta(seconds=i)).astimezone(UTC).isoformat()
        rows.append((key_hash, "programs.search", ts, 200, 1))
    c = sqlite3.connect(db_path)
    try:
        c.executemany(
            "INSERT INTO usage_events(key_hash, endpoint, ts, status, metered) "
            "VALUES (?,?,?,?,?)",
            rows,
        )
        c.commit()
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Case 1: POST /v1/me/cap persists the cap
# ---------------------------------------------------------------------------


def test_set_cap_persists_to_api_keys(
    client: TestClient, fresh_paid_key: str, seeded_db: Path
) -> None:
    """POST /v1/me/cap writes monthly_cap_yen into the api_keys row."""
    r = client.post(
        "/v1/me/cap",
        json={"monthly_cap_yen": 5000},
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"ok": True, "monthly_cap_yen": 5000}

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        row = c.execute(
            "SELECT monthly_cap_yen FROM api_keys WHERE key_hash = ?",
            (hash_api_key(fresh_paid_key),),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    assert row["monthly_cap_yen"] == 5000


# ---------------------------------------------------------------------------
# Case 2: cap reached -> 503 + cap_reached body, router never runs
# ---------------------------------------------------------------------------


def test_cap_reached_returns_503_with_spec_body(
    client: TestClient, fresh_paid_key: str, seeded_db: Path
) -> None:
    """Once month-to-date billable >= cap, requests get 503 + cap_reached.

    Uses cap=¥15 (so 5 metered successes at ¥3 each = ¥15, exactly at cap).
    The plan body says "cap_yen <= month_to_date_yen" -> 503, so equal counts.
    """
    # Set cap to ¥15 (5 reqs worth).
    r = client.post(
        "/v1/me/cap",
        json={"monthly_cap_yen": 15},
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code == 200, r.text

    # Seed 5 successful metered calls in the current JST month.
    _seed_metered_successes(seeded_db, hash_api_key(fresh_paid_key), 5)

    # A subsequent paid request (any non-control-plane path) must 503.
    r = client.get(
        "/v1/programs/search",
        params={"q": "テスト"},
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code == 503, r.text
    body = r.json()
    err = body["error"]
    assert err["code"] == "monthly_cap_reached"
    assert err["cap_reached"] is True
    assert err["cap_yen"] == 15
    assert err["month_to_date_yen"] == 15  # 5 * ¥3
    assert "resets_at" in err
    assert err["message"].startswith("月次上限 ¥15")

    # No usage_events row created for the rejected request — only the 5
    # we seeded should be present.
    c = sqlite3.connect(seeded_db)
    try:
        (n,) = c.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ?",
            (hash_api_key(fresh_paid_key),),
        ).fetchone()
    finally:
        c.close()
    assert n == 5, "cap-rejected request must not create a usage_events row"


# ---------------------------------------------------------------------------
# Case 3: cap=NULL -> uncapped, endpoint reachable
# ---------------------------------------------------------------------------


def test_cap_null_means_unlimited(
    client: TestClient, fresh_paid_key: str, seeded_db: Path
) -> None:
    """A key with monthly_cap_yen IS NULL is never gated by the cap middleware.

    Verified by setting a cap, hitting it, removing the cap (null), and
    confirming subsequent requests pass through.
    """
    # Set cap, accumulate usage to exceed it
    r = client.post(
        "/v1/me/cap",
        json={"monthly_cap_yen": 9},
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code == 200
    _seed_metered_successes(seeded_db, hash_api_key(fresh_paid_key), 5)

    # Confirm we ARE capped
    r = client.get(
        "/v1/programs/search",
        params={"q": "テスト"},
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code == 503, "precondition: should be capped"

    # Remove the cap
    r = client.post(
        "/v1/me/cap",
        json={"monthly_cap_yen": None},
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "monthly_cap_yen": None}

    # Same endpoint must now succeed (200) — not 503. We don't care about the
    # exact response payload, just that the cap layer isn't blocking us.
    r = client.get(
        "/v1/programs/search",
        params={"q": "テスト"},
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code != 503, r.text
    assert r.status_code < 500, r.text


# ---------------------------------------------------------------------------
# Bonus invariants: control-plane carve-out + anon skip
# ---------------------------------------------------------------------------


def test_anonymous_callers_are_not_capped(
    client: TestClient, seeded_db: Path
) -> None:
    """An anonymous caller (no X-API-Key) must never be subject to the cap.

    No api_keys row exists for an anon caller, so cap_yen is meaningless.
    The 50 req/月 anon quota is enforced separately by AnonIpLimitDep.
    """
    r = client.get("/v1/programs/search", params={"q": "テスト"})
    # Either 200 (rows found) or 4xx/2xx from validation — but never 503
    # cap_reached, since the cap middleware MUST skip anon.
    assert r.status_code != 503
    if r.status_code == 503:
        body = r.json()
        # If somehow 503, it must NOT be cap_reached
        assert (
            body.get("error", {}).get("code") != "monthly_cap_reached"
        ), body


def test_me_endpoints_remain_reachable_when_capped(
    client: TestClient, fresh_paid_key: str, seeded_db: Path
) -> None:
    """Even at cap-reached, /v1/me/cap must remain reachable so the customer
    can raise / remove their own cap. Otherwise they're locked out of the
    dashboard until JST 月初.
    """
    # Tiny cap, exhaust it
    r = client.post(
        "/v1/me/cap",
        json={"monthly_cap_yen": 3},
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code == 200
    _seed_metered_successes(seeded_db, hash_api_key(fresh_paid_key), 1)

    # /v1/me/cap (control-plane) MUST still respond 200 — no 503.
    r = client.post(
        "/v1/me/cap",
        json={"monthly_cap_yen": None},
        headers={"X-API-Key": fresh_paid_key},
    )
    assert r.status_code == 200, r.text
