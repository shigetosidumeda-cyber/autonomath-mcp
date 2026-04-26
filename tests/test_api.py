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
    assert d["total_programs"] == 4
    assert d["tier_counts"]["S"] == 1
    # Three fixture rules: legacy mutex / legacy prereq / migration-051
    # uid-keyed mutex (added so the dual-key path can be exercised).
    assert d["exclusion_rules_count"] == 3


def test_search_default_excludes_excluded(client):
    r = client.get("/v1/programs/search", params={"limit": 100})
    d = r.json()
    ids = [x["unified_id"] for x in d["results"]]
    assert "UNI-test-x-1" not in ids
    assert len(ids) == 3


def test_search_include_excluded(client):
    r = client.get("/v1/programs/search", params={"include_excluded": True, "limit": 100})
    d = r.json()
    ids = [x["unified_id"] for x in d["results"]]
    assert "UNI-test-x-1" in ids
    assert d["total"] == 4


def test_search_filter_tier(client):
    r = client.get("/v1/programs/search", params={"tier": ["S", "A"], "limit": 100})
    d = r.json()
    tiers = {x["tier"] for x in d["results"]}
    assert tiers == {"S", "A"}
    assert d["total"] == 2


def test_search_tier_order(client):
    r = client.get("/v1/programs/search", params={"limit": 100})
    d = r.json()
    tiers = [x["tier"] for x in d["results"]]
    assert tiers.index("S") < tiers.index("A") < tiers.index("B")


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
