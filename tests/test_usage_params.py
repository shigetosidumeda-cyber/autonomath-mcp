"""Tests for the params_digest column on usage_events.

Ensures:
1. The schema has the column (migration 005 / schema.sql).
2. Authed calls to whitelisted endpoints write a non-null digest.
3. Two identical queries produce the same digest (the whole point of the
   column — W7 digest cron can GROUP BY).
4. Endpoints outside the whitelist / calls without params write NULL.
5. The compute helper is deterministic on key ordering and canonicalizes
   JSON so `?tier=A&tier=S` == `?tier=S&tier=A`.
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.deps import compute_params_digest, hash_api_key
from jpintel_mcp.billing.keys import issue_key

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def plus_key(seeded_db: Path) -> str:
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_params_digest_test",
        tier="paid",
        stripe_subscription_id="sub_params_digest_test",
    )
    c.commit()
    c.close()
    return raw


def _clear_usage(db_path: Path, key_hash: str) -> None:
    c = sqlite3.connect(db_path)
    try:
        c.execute("DELETE FROM usage_events WHERE key_hash = ?", (key_hash,))
        c.commit()
    finally:
        c.close()


def _fetch_usage(db_path: Path, key_hash: str, endpoint: str) -> list[sqlite3.Row]:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT endpoint, params_digest, ts FROM usage_events "
            "WHERE key_hash = ? AND endpoint = ? ORDER BY id",
            (key_hash, endpoint),
        ).fetchall()
        return list(rows)
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Schema / migration
# ---------------------------------------------------------------------------


def test_usage_events_has_params_digest_column(seeded_db: Path):
    """Schema must expose params_digest (added in 005_usage_params.sql)."""
    c = sqlite3.connect(seeded_db)
    try:
        cols = {row[1] for row in c.execute("PRAGMA table_info(usage_events)")}
    finally:
        c.close()
    assert "params_digest" in cols


def test_idx_usage_events_key_params_exists(seeded_db: Path):
    """The grouping index is what makes the digest cron cheap — must exist."""
    c = sqlite3.connect(seeded_db)
    try:
        idx = {row[1] for row in c.execute("PRAGMA index_list(usage_events)")}
    finally:
        c.close()
    assert "idx_usage_events_key_params" in idx


# ---------------------------------------------------------------------------
# compute_params_digest — pure function behaviour
# ---------------------------------------------------------------------------


def test_compute_digest_whitelisted_returns_16_hex():
    d = compute_params_digest("programs.search", {"q": "hello"})
    assert d is not None
    assert len(d) == 16
    assert all(c in "0123456789abcdef" for c in d)


def test_compute_digest_identical_inputs_identical_output():
    a = compute_params_digest("programs.search", {"q": "rice", "prefecture": "東京都"})
    b = compute_params_digest("programs.search", {"prefecture": "東京都", "q": "rice"})
    assert a == b


def test_compute_digest_differs_on_different_input():
    a = compute_params_digest("programs.search", {"q": "rice"})
    b = compute_params_digest("programs.search", {"q": "wheat"})
    assert a != b


def test_compute_digest_strips_none_values():
    # `?q=foo&prefecture=` (absent) must digest the same as `?q=foo`.
    a = compute_params_digest("programs.search", {"q": "foo"})
    b = compute_params_digest("programs.search", {"q": "foo", "prefecture": None})
    assert a == b


def test_compute_digest_non_whitelisted_endpoint_returns_none():
    # /v1/me/* etc carry PII — must NEVER produce a digest.
    assert compute_params_digest("me.session", {"api_key": "foo"}) is None
    assert compute_params_digest("feedback.post", {"message": "bug"}) is None
    assert compute_params_digest("subscribers.subscribe", {"email": "x@y"}) is None


def test_compute_digest_empty_params_returns_none():
    assert compute_params_digest("meta", None) is None
    assert compute_params_digest("meta", {}) is None
    # All-None also collapses to None after cleaning.
    assert compute_params_digest("programs.search", {"q": None, "prefecture": None}) is None


# ---------------------------------------------------------------------------
# End-to-end — HTTP request produces the row we expect
# ---------------------------------------------------------------------------


def test_search_populates_params_digest(client, plus_key, seeded_db: Path):
    kh = hash_api_key(plus_key)
    _clear_usage(seeded_db, kh)

    r = client.get(
        "/v1/programs/search",
        params={"q": "認定新規就農者", "prefecture": "青森県"},
        headers={"X-API-Key": plus_key},
    )
    assert r.status_code == 200, r.text

    rows = _fetch_usage(seeded_db, kh, "programs.search")
    assert len(rows) == 1
    assert rows[0]["params_digest"] is not None
    assert len(rows[0]["params_digest"]) == 16


def test_two_identical_searches_produce_same_digest(client, plus_key, seeded_db: Path):
    """The whole point of the column: equivalent queries group together."""
    kh = hash_api_key(plus_key)
    _clear_usage(seeded_db, kh)

    params = {"q": "補助金", "prefecture": "東京都"}
    for _ in range(2):
        r = client.get(
            "/v1/programs/search", params=params, headers={"X-API-Key": plus_key}
        )
        assert r.status_code == 200, r.text

    rows = _fetch_usage(seeded_db, kh, "programs.search")
    assert len(rows) == 2
    assert rows[0]["params_digest"] == rows[1]["params_digest"]
    assert rows[0]["params_digest"] is not None


def test_different_searches_produce_different_digests(
    client, plus_key, seeded_db: Path
):
    kh = hash_api_key(plus_key)
    _clear_usage(seeded_db, kh)

    client.get(
        "/v1/programs/search",
        params={"prefecture": "東京都"},
        headers={"X-API-Key": plus_key},
    )
    client.get(
        "/v1/programs/search",
        params={"prefecture": "青森県"},
        headers={"X-API-Key": plus_key},
    )

    rows = _fetch_usage(seeded_db, kh, "programs.search")
    assert len(rows) == 2
    assert rows[0]["params_digest"] != rows[1]["params_digest"]


def test_meta_endpoint_without_params_writes_null_digest(
    client, plus_key, seeded_db: Path
):
    """/meta has no user-controlled params — digest must be NULL so the
    digest cron doesn't try to personalize on an empty bucket."""
    kh = hash_api_key(plus_key)
    _clear_usage(seeded_db, kh)

    r = client.get("/meta", headers={"X-API-Key": plus_key})
    assert r.status_code == 200

    rows = _fetch_usage(seeded_db, kh, "meta")
    assert len(rows) == 1
    assert rows[0]["params_digest"] is None


def test_grouping_sql_works_with_digest(client, plus_key, seeded_db: Path):
    """Simulate the W7 digest cron's grouping query — it's the end use case."""
    kh = hash_api_key(plus_key)
    _clear_usage(seeded_db, kh)

    # 3x same query, 2x different query.
    for _ in range(3):
        client.get(
            "/v1/programs/search",
            params={"prefecture": "東京都"},
            headers={"X-API-Key": plus_key},
        )
    for _ in range(2):
        client.get(
            "/v1/programs/search",
            params={"prefecture": "青森県"},
            headers={"X-API-Key": plus_key},
        )

    c = sqlite3.connect(seeded_db)
    try:
        buckets = c.execute(
            "SELECT params_digest, COUNT(*) AS n FROM usage_events "
            "WHERE key_hash = ? AND params_digest IS NOT NULL "
            "GROUP BY params_digest ORDER BY n DESC",
            (kh,),
        ).fetchall()
    finally:
        c.close()

    counts = [n for (_d, n) in buckets]
    assert counts == [3, 2]


def test_me_usage_still_returns_list_shape(client, plus_key, seeded_db: Path):
    """Regression: /v1/me/usage must still return list[UsageDay] — the new
    column is additive and must not leak into the response shape."""
    kh = hash_api_key(plus_key)
    _clear_usage(seeded_db, kh)
    # One call so there's at least one row today.
    client.get("/meta", headers={"X-API-Key": plus_key})

    # /v1/me/usage needs a session cookie, not X-API-Key. Establish one.
    r = client.post("/v1/session", json={"api_key": plus_key})
    assert r.status_code == 200

    r = client.get("/v1/me/usage", params={"days": 7})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    # Each day must still be {date, calls} — no params_digest leakage.
    for day in data:
        assert set(day.keys()) == {"date", "calls"}
