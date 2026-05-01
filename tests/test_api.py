def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz(client):
    # /readyz returns 200 only after lifespan startup flips _ready=True.
    # TestClient-as-context-manager runs the lifespan, so the fixture's
    # returned client should already be ready.
    from fastapi.testclient import TestClient

    from jpintel_mcp.api.main import create_app

    with TestClient(create_app()) as ready_client:
        r = ready_client.get("/readyz")
        assert r.status_code == 200
        assert r.json() == {"status": "ready"}


def test_meta(client):
    r = client.get("/meta")
    assert r.status_code == 200
    d = r.json()
    # Fixture seeds 4 UNI-test-* programs; live conftest may seed more for
    # cross-feature smoke. Lower-bound is what matters: at least the 4 fixture
    # rows must round-trip and tier S must include at least the test-s-1 row.
    assert d["total_programs"] >= 4
    assert d["tier_counts"]["S"] >= 1
    # Three fixture rules: legacy mutex / legacy prereq / migration-051
    # uid-keyed mutex (added so the dual-key path can be exercised).
    assert d["exclusion_rules_count"] >= 3


def test_search_default_excludes_excluded(client):
    r = client.get("/v1/programs/search", params={"limit": 100})
    d = r.json()
    ids = [x["unified_id"] for x in d["results"]]
    assert "UNI-test-x-1" not in ids
    assert {"UNI-test-s-1", "UNI-test-a-1", "UNI-test-b-1"}.issubset(set(ids))


def test_search_include_excluded(client):
    r = client.get("/v1/programs/search", params={"include_excluded": True, "limit": 100})
    d = r.json()
    ids = [x["unified_id"] for x in d["results"]]
    assert "UNI-test-x-1" in ids
    # All 4 fixture rows must be present when include_excluded=True.
    assert {"UNI-test-s-1", "UNI-test-a-1", "UNI-test-b-1", "UNI-test-x-1"}.issubset(set(ids))


def test_search_filter_tier(client):
    r = client.get("/v1/programs/search", params={"tier": ["S", "A"], "limit": 100})
    d = r.json()
    tiers = {x["tier"] for x in d["results"]}
    ids = {x["unified_id"] for x in d["results"]}
    assert tiers == {"S", "A"}
    # Both fixture S/A rows must surface; live conftest may seed more.
    assert {"UNI-test-s-1", "UNI-test-a-1"}.issubset(ids)


def test_search_tier_order(client):
    # Calibrated tier prior weights (C3, 2026-04-30): S=1.07, A=B=1.06,
    # C=0.99, X=0.83. A and B share the same weight by empirical fit, so the
    # ordering contract is now S > {A, B} > C > X — A vs B relative order is
    # not guaranteed (and not load-bearing for the search UX).
    r = client.get("/v1/programs/search", params={"limit": 100})
    d = r.json()
    tiers = [x["tier"] for x in d["results"]]
    assert tiers.index("S") < tiers.index("A")
    assert tiers.index("S") < tiers.index("B")
    if "C" in tiers:
        assert max(tiers.index("A"), tiers.index("B")) < tiers.index("C")


def test_search_prefecture(client):
    r = client.get("/v1/programs/search", params={"prefecture": "東京都"})
    d = r.json()
    assert d["total"] == 1
    assert d["results"][0]["unified_id"] == "UNI-test-s-1"


def test_search_japanese_fts(client):
    r = client.get("/v1/programs/search", params={"q": "認定新規就農者"})
    d = r.json()
    assert d["total"] >= 1
    assert any("認定新規就農者" in x["primary_name"] for x in d["results"])


def test_search_short_query_fallback(client):
    r = client.get("/v1/programs/search", params={"q": "融資"})
    d = r.json()
    assert any("融資" in x["primary_name"] for x in d["results"])


def test_search_amount_filter(client):
    r = client.get("/v1/programs/search", params={"amount_min": 5000, "limit": 100})
    d = r.json()
    for x in d["results"]:
        assert x["amount_max_man_yen"] >= 5000


def test_get_program(client):
    r = client.get("/v1/programs/UNI-test-s-1")
    assert r.status_code == 200
    assert r.json()["primary_name"] == "テスト S-tier 補助金"


def test_get_program_404(client):
    r = client.get("/v1/programs/no-such-id")
    assert r.status_code == 404


def test_post_idempotency_key_replays_without_second_usage_event(
    client, paid_key, seeded_db
):
    import sqlite3

    body = {"unified_ids": ["UNI-test-s-1", "UNI-test-a-1"]}
    headers = {
        "X-API-Key": paid_key,
        "Idempotency-Key": "idem-program-batch-1",
    }
    r1 = client.post("/v1/programs/batch", headers=headers, json=body)
    assert r1.status_code == 200, r1.text
    assert r1.headers.get("X-Idempotency-Replayed") is None

    r2 = client.post("/v1/programs/batch", headers=headers, json=body)
    assert r2.status_code == 200, r2.text
    assert r2.headers.get("X-Idempotency-Replayed") == "true"
    assert r2.headers.get("X-Metered") == "false"
    assert r2.json() == r1.json()

    c = sqlite3.connect(seeded_db)
    try:
        rows = c.execute(
            "SELECT quantity FROM usage_events "
            "WHERE endpoint = 'programs.get' "
            "AND params_digest IS NOT NULL "
            "ORDER BY id DESC LIMIT 10"
        ).fetchall()
    finally:
        c.close()
    assert len(rows) == 1, rows
    assert int(rows[0][0]) == 2


def test_idempotency_replay_revalidates_revoked_key(client, paid_key, seeded_db):
    import sqlite3

    from jpintel_mcp.api.deps import hash_api_key

    body = {"unified_ids": ["UNI-test-s-1"]}
    headers = {
        "X-API-Key": paid_key,
        "Idempotency-Key": "idem-revoked-key-replay",
    }
    r1 = client.post("/v1/programs/batch", headers=headers, json=body)
    assert r1.status_code == 200, r1.text

    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE key_hash = ?",
            ("2026-05-01T00:00:00+00:00", hash_api_key(paid_key)),
        )
        c.commit()
    finally:
        c.close()

    r2 = client.post("/v1/programs/batch", headers=headers, json=body)
    assert r2.status_code == 401
    assert r2.headers.get("X-Idempotency-Replayed") is None
    assert r2.headers.get("X-Metered") == "false"


def test_idempotency_replay_revalidates_trial_expiry(client, seeded_db):
    import sqlite3

    from jpintel_mcp.billing.keys import issue_trial_key

    c = sqlite3.connect(seeded_db)
    try:
        trial_key, key_hash = issue_trial_key(
            c,
            trial_email="idem-expired@example.com",
            duration_days=14,
        )
        c.commit()
    finally:
        c.close()

    body = {"program_ids": ["keiei-kaishi-shikin", "koyo-shuno-shikin"]}
    headers = {
        "X-API-Key": trial_key,
        "Idempotency-Key": "idem-trial-expiry-replay",
    }
    r1 = client.post("/v1/exclusions/check", headers=headers, json=body)
    assert r1.status_code == 200, r1.text

    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "UPDATE api_keys SET trial_expires_at = ? WHERE key_hash = ?",
            ("2026-04-01T00:00:00+00:00", key_hash),
        )
        c.commit()
    finally:
        c.close()

    r2 = client.post("/v1/exclusions/check", headers=headers, json=body)
    assert r2.status_code == 401
    assert r2.headers.get("X-Idempotency-Replayed") is None
    assert r2.headers.get("X-Metered") == "false"

    c = sqlite3.connect(seeded_db)
    try:
        revoked_at = c.execute(
            "SELECT revoked_at FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()[0]
    finally:
        c.close()
    assert revoked_at is not None


def test_post_idempotency_key_not_applied_to_session(client, paid_key):
    headers = {
        "Idempotency-Key": "session-must-not-cache",
        "X-Forwarded-For": "203.0.113.80",
    }
    r1 = client.post("/v1/session", headers=headers, json={"api_key": paid_key})
    assert r1.status_code == 200, r1.text
    assert r1.headers.get("X-Idempotency-Replayed") is None

    r2 = client.post("/v1/session", headers=headers, json={"api_key": paid_key})
    assert r2.status_code == 200, r2.text
    assert r2.headers.get("X-Idempotency-Replayed") is None
    assert r1.cookies.get("am_session") != r2.cookies.get("am_session")


def test_post_idempotency_key_not_applied_to_anonymous_quota(client, seeded_db):
    import sqlite3

    body = {"program_ids": ["keiei-kaishi-shikin", "koyo-shuno-shikin"]}
    headers = {"Idempotency-Key": "anon-must-not-bypass-quota"}

    r1 = client.post("/v1/exclusions/check", headers=headers, json=body)
    assert r1.status_code == 200, r1.text
    assert r1.headers.get("X-Idempotency-Replayed") is None

    r2 = client.post("/v1/exclusions/check", headers=headers, json=body)
    assert r2.status_code == 200, r2.text
    assert r2.headers.get("X-Idempotency-Replayed") is None

    c = sqlite3.connect(seeded_db)
    try:
        count = c.execute("SELECT COALESCE(SUM(call_count), 0) FROM anon_rate_limit").fetchone()[0]
    finally:
        c.close()
    assert int(count) == 2


def test_idempotency_claim_pending_blocks_second_owner(seeded_db):
    import sqlite3

    from jpintel_mcp.api.middleware.idempotency import (
        _claim_or_read_cached,
        _compute_cache_key,
        _read_cached,
        _serialise_response,
        _write_cached,
    )

    cache_key = _compute_cache_key(
        "k:test",
        "/v1/programs/batch",
        b'{"unified_ids":["UNI-test-s-1"]}',
        "concurrent-owner-test",
    )
    conn1 = sqlite3.connect(seeded_db, isolation_level=None)
    conn2 = sqlite3.connect(seeded_db, isolation_level=None)
    try:
        assert _claim_or_read_cached(conn1, cache_key) == ("owner", None)
        assert _claim_or_read_cached(conn2, cache_key) == ("pending", None)
        blob = _serialise_response(200, {"content-type": "application/json"}, b'{"ok":true}')
        _write_cached(conn1, cache_key, blob, ttl_hours=24)
        assert _read_cached(conn2, cache_key) == blob
        assert _claim_or_read_cached(conn2, cache_key) == ("hit", blob)
    finally:
        conn1.close()
        conn2.close()


def test_idempotency_claim_db_lock_fails_closed(seeded_db):
    import contextlib
    import sqlite3

    from jpintel_mcp.api.middleware.idempotency import (
        _claim_or_read_cached,
        _compute_cache_key,
    )

    cache_key = _compute_cache_key(
        "k:test",
        "/v1/programs/batch",
        b'{"unified_ids":["UNI-test-s-1"]}',
        "locked-db-owner-test",
    )
    locker = sqlite3.connect(seeded_db, timeout=0, isolation_level=None)
    contender = sqlite3.connect(seeded_db, timeout=0, isolation_level=None)
    try:
        locker.execute("BEGIN IMMEDIATE")
        assert _claim_or_read_cached(contender, cache_key) == ("busy", None)
    finally:
        with contextlib.suppress(Exception):
            locker.execute("ROLLBACK")
        locker.close()
        contender.close()


def test_idempotency_expired_pending_stays_busy_not_second_owner(seeded_db):
    import sqlite3

    from jpintel_mcp.api.middleware.idempotency import (
        _claim_or_read_cached,
        _compute_cache_key,
    )

    cache_key = _compute_cache_key(
        "k:test",
        "/v1/programs/batch",
        b'{"unified_ids":["UNI-test-s-1"]}',
        "expired-pending-owner-test",
    )
    conn1 = sqlite3.connect(seeded_db, isolation_level=None)
    conn2 = sqlite3.connect(seeded_db, isolation_level=None)
    try:
        assert _claim_or_read_cached(conn1, cache_key) == ("owner", None)
        conn1.execute(
            "UPDATE am_idempotency_cache SET expires_at = ? WHERE cache_key = ?",
            ("2026-01-01T00:00:00+00:00", cache_key),
        )
        assert _claim_or_read_cached(conn2, cache_key) == ("busy", None)
        assert _claim_or_read_cached(conn1, cache_key) == ("pending", None)
    finally:
        conn1.close()
        conn2.close()


def test_idempotency_high_cost_posts_are_cacheable():
    from jpintel_mcp.api.middleware.idempotency import _is_bypass_path

    for path in (
        "/v1/audit/batch_evaluate",
        "/v1/audit/workpaper",
        "/v1/am/dd_batch",
        "/v1/am/dd_export",
    ):
        assert _is_bypass_path(path) is False


def test_list_exclusion_rules(client):
    r = client.get("/v1/exclusions/rules")
    assert r.status_code == 200
    rules = r.json()
    # Three fixture rules: legacy mutex / legacy prereq / migration-051
    # uid-keyed mutex (added so the dual-key path can be exercised).
    assert len(rules) == 3
    assert {x["rule_id"] for x in rules} == {
        "excl-test-mutex",
        "excl-test-prereq",
        "excl-test-uid-mutex",
    }


def test_check_exclusions_mutex_hit(client):
    r = client.post(
        "/v1/exclusions/check",
        json={"program_ids": ["keiei-kaishi-shikin", "koyo-shuno-shikin"]},
    )
    d = r.json()
    assert len(d["hits"]) == 1
    hit = d["hits"][0]
    assert hit["rule_id"] == "excl-test-mutex"
    assert set(hit["programs_involved"]) == {"keiei-kaishi-shikin", "koyo-shuno-shikin"}


def test_check_exclusions_prerequisite_hit(client):
    r = client.post("/v1/exclusions/check", json={"program_ids": ["seinen-shuno-shikin"]})
    d = r.json()
    rule_ids = {h["rule_id"] for h in d["hits"]}
    assert "excl-test-prereq" in rule_ids


def test_check_exclusions_no_conflict(client):
    r = client.post("/v1/exclusions/check", json={"program_ids": ["unrelated-program"]})
    d = r.json()
    assert d["hits"] == []
    # Three fixture rules — keep in sync with test_list_exclusion_rules.
    assert d["checked_rules"] == 3


def test_check_exclusions_empty_body(client):
    r = client.post("/v1/exclusions/check", json={"program_ids": []})
    assert r.status_code == 422


def test_openapi_lists_all_routes(client):
    r = client.get("/openapi.json")
    paths = set(r.json()["paths"].keys())
    # `/meta` is kept as a 308 redirect with include_in_schema=False; the
    # canonical meta endpoint is `/v1/meta`.
    for p in [
        "/healthz",
        "/v1/meta",
        "/v1/programs/search",
        "/v1/programs/{unified_id}",
        "/v1/exclusions/rules",
        "/v1/exclusions/check",
        "/v1/enforcement-cases/search",
        "/v1/enforcement-cases/{case_id}",
        "/v1/case-studies/search",
        "/v1/case-studies/{case_id}",
        "/v1/loan-programs/search",
        "/v1/loan-programs/{loan_id}",
    ]:
        assert p in paths, f"missing route in OpenAPI: {p}"
