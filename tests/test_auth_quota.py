import sqlite3
from datetime import UTC, datetime

import pytest

from jpintel_mcp.billing.keys import issue_key


@pytest.fixture()
def paid_api_key(seeded_db):
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(c, customer_id="cus_paid", tier="paid", stripe_subscription_id="sub_paid")
    c.commit()
    c.close()
    return raw


@pytest.fixture()
def fresh_key(seeded_db):
    """Issue a fresh key for a given tier; returns a factory.

    Each call returns a brand-new raw key so test assertions about counts
    do not interfere across tests.
    """
    created: list[str] = []

    def _make(tier: str, *, customer_id: str | None = None, sub_id: str | None = None) -> str:
        c = sqlite3.connect(seeded_db)
        c.row_factory = sqlite3.Row
        sub = sub_id or f"sub_{tier}_{len(created)}"
        cust = customer_id or f"cus_{tier}_{len(created)}"
        raw = issue_key(c, customer_id=cust, tier=tier, stripe_subscription_id=sub)
        c.commit()
        c.close()
        created.append(raw)
        return raw

    return _make


def _seed_usage_events(db_path, key_hash: str, count: int) -> None:
    """Insert `count` usage_events for the given key_hash at 'today'."""
    now = datetime.now(UTC).isoformat()
    c = sqlite3.connect(db_path)
    try:
        c.executemany(
            "INSERT INTO usage_events(key_hash, endpoint, ts, status, metered) VALUES (?,?,?,?,?)",
            [(key_hash, "meta", now, 200, 0) for _ in range(count)],
        )
        c.commit()
    finally:
        c.close()


def test_no_key_works_as_free(client):
    r = client.get("/meta")
    assert r.status_code == 200


def test_paid_key_accepted(client, paid_api_key):
    r = client.get("/meta", headers={"X-API-Key": paid_api_key})
    assert r.status_code == 200


def test_bearer_header_accepted(client, paid_api_key):
    r = client.get("/meta", headers={"Authorization": f"Bearer {paid_api_key}"})
    assert r.status_code == 200


def test_invalid_key_rejected(client):
    r = client.get("/meta", headers={"X-API-Key": "jpintel_not-a-real-key"})
    assert r.status_code == 401


def test_revoked_key_rejected(client, paid_api_key):
    from jpintel_mcp.api.deps import hash_api_key
    from jpintel_mcp.config import settings

    with sqlite3.connect(settings.db_path) as c:
        c.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE key_hash = ?",
            (datetime.now(UTC).isoformat(), hash_api_key(paid_api_key)),
        )
        c.commit()

    r = client.get("/meta", headers={"X-API-Key": paid_api_key})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Rate-limit: free = 100/day hard cap, paid = metered (no hard cap).
# ---------------------------------------------------------------------------


def test_rate_limit_free_tier_429_with_retry_after(client, seeded_db, fresh_key):
    """Free tier key exceeds 100 req/day -> 429 with Retry-After header."""
    from jpintel_mcp.api.deps import hash_api_key

    raw = fresh_key("free")
    _seed_usage_events(seeded_db, hash_api_key(raw), count=100)

    r = client.get("/meta", headers={"X-API-Key": raw})
    assert r.status_code == 429
    assert "free" in r.json()["detail"]
    retry_after = r.headers.get("Retry-After")
    assert retry_after is not None
    assert int(retry_after) > 0


def test_rate_limit_paid_tier_bypasses(client, seeded_db, fresh_key):
    """Paid tier is metered (no hard cap) — never 429 on volume.

    Over-volume paid callers are billed via Stripe usage_records instead.
    """
    from jpintel_mcp.api.deps import hash_api_key

    raw = fresh_key("paid")
    # Far over any per-day cap; metered tier must bypass enforcement.
    _seed_usage_events(seeded_db, hash_api_key(raw), count=50_000)

    r = client.get("/meta", headers={"X-API-Key": raw})
    assert r.status_code == 200
