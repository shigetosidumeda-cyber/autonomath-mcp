def test_exclusion_rules_limit_3(client):
    r = client.get("/v1/exclusions/rules?limit=3")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 3

def test_exclusion_rules_limit_1(client):
    r = client.get("/v1/exclusions/rules?limit=1")
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1

def test_exclusion_rules_offset(client):
    full = client.get("/v1/exclusions/rules").json()
    assert len(full) == 3
    r = client.get("/v1/exclusions/rules?limit=2&offset=1")
    assert r.status_code == 200, r.text
    sliced = r.json()
    assert len(sliced) == 2
    assert sliced[0]["rule_id"] == full[1]["rule_id"]

def test_exclusion_rules_no_params_unchanged(client):
    r = client.get("/v1/exclusions/rules")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 3

def test_exclusion_rules_unknown_param_still_rejected(client):
    r = client.get("/v1/exclusions/rules?bogus=1")
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "unknown_query_parameter"

def test_exclusion_rules_limit_too_large(client):
    r = client.get("/v1/exclusions/rules?limit=501")
    assert r.status_code == 422

def test_exclusion_rules_limit_zero(client):
    r = client.get("/v1/exclusions/rules?limit=0")
    assert r.status_code == 422

def test_exclusion_rules_negative_offset(client):
    r = client.get("/v1/exclusions/rules?offset=-1")
    assert r.status_code == 422
