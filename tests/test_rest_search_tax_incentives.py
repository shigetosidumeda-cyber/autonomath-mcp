"""W7-8 re-injection: REST `/v1/am/tax_incentives` must accept the
`foreign_capital_eligibility` + `lang` query params (W3-12 UC5 / Foreign
FDI cohort).

Background
----------
W4-7 wired the two args onto the MCP tool side
(`autonomath_tools/tools.py::search_tax_incentives`) but the REST
endpoint in `api/autonomath.py` did not surface the FastAPI Query
declarations. Result: callers passing `?foreign_capital_eligibility=true`
or `?lang=en` got a 422 `unprocessable_entity` from FastAPI's strict
query validation. W5-5 NO-GO blocker #8 traced that gap; this suite
locks in the fix.

The assertions are intentionally narrow:
  * Route accepts both params without 422 reject.
  * Each param echoes through the L4 cache key + envelope so we know
    the value reached the underlying tool (not silently dropped).

We DO NOT assert row content here — the seeded jpintel.db lacks the
9.4 GB autonomath corpus, so the tool may return zero rows / fall
back to a graceful empty envelope. The W3-12 UC5 row-content
contract is exercised against the real DB in
`tests/test_search_tax_incentives_lang.py`.
"""

from __future__ import annotations


def _assert_not_422(response, *, path: str) -> None:
    """422 means FastAPI rejected the query params at the schema layer
    (i.e. the Query() declaration is missing for one of the args we
    just sent). Anything else — including 200 with empty rows or 503
    when autonomath.db is unmounted — is acceptable for this contract.
    """
    assert (
        response.status_code != 422
    ), f"{path} → 422 (params not accepted by FastAPI). body={response.text}"


def test_tax_incentives_accepts_foreign_capital_eligibility(client):
    """`?foreign_capital_eligibility=true` must not 422."""
    r = client.get(
        "/v1/am/tax_incentives",
        params={"foreign_capital_eligibility": "true", "limit": 5},
    )
    _assert_not_422(r, path="/v1/am/tax_incentives?foreign_capital_eligibility=true")
    assert r.status_code in (200, 503), f"unexpected status {r.status_code}: {r.text}"


def test_tax_incentives_accepts_lang_en(client):
    """`?lang=en` must not 422 and should echo lang in meta when 200."""
    r = client.get(
        "/v1/am/tax_incentives",
        params={"lang": "en", "limit": 5},
    )
    _assert_not_422(r, path="/v1/am/tax_incentives?lang=en")
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        body = r.json()
        meta = body.get("meta") or {}
        # The tool surfaces lang in meta; envelope merge preserves it.
        assert meta.get("lang") == "en", f"lang did not propagate to meta: {meta}"


def test_tax_incentives_accepts_lang_ja_default(client):
    """Baseline: `?lang=ja` (explicit default) must also pass."""
    r = client.get(
        "/v1/am/tax_incentives",
        params={"lang": "ja", "limit": 5},
    )
    _assert_not_422(r, path="/v1/am/tax_incentives?lang=ja")
    assert r.status_code in (200, 503)


def test_tax_incentives_rejects_invalid_lang(client):
    """`?lang=fr` must 422 — Literal["ja","en"] enforces the enum."""
    r = client.get(
        "/v1/am/tax_incentives",
        params={"lang": "fr", "limit": 5},
    )
    assert r.status_code == 422, f"invalid lang should 422, got {r.status_code}: {r.text}"


def test_tax_incentives_combined_lang_en_and_fdi_true(client):
    """W3-12 UC5 happy path: both params at once must not 422."""
    r = client.get(
        "/v1/am/tax_incentives",
        params={
            "lang": "en",
            "foreign_capital_eligibility": "true",
            "limit": 5,
        },
    )
    _assert_not_422(r, path="/v1/am/tax_incentives?lang=en&foreign_capital_eligibility=true")
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        body = r.json()
        meta = body.get("meta") or {}
        assert meta.get("lang") == "en"
        assert meta.get("foreign_capital_eligibility_filter") is True
