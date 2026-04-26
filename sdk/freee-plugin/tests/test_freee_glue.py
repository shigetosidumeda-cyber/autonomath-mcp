"""Mock-only tests for the freee → AutonoMath glue layer.

No real freee or AutonoMath calls are made. We use httpx.MockTransport to
intercept both endpoints and assert the glue's stateless behavior + the
``source_url`` filter.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import httpx
import pytest

# Allow running from the repo root: ``pytest sdk/freee-plugin/tests/``
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from freee_to_autonomath import (  # noqa: E402
    PREFECTURE_BY_CODE,
    CompanyContext,
    ProgramRecommendation,
    _build_search_params,
    call_autonomath_search,
    fetch_company_context,
    recommend,
)


# ----- helpers ------------------------------------------------------------

FREEE_COMPANY_PAYLOAD = {
    "company": {
        "id": 999001,
        "name": "テスト株式会社",
        "company_type": "zk",
        "prefecture_code": 13,  # 東京都
        "business_industry_code": "G3911",  # 情報サービス業
        "employees_number": 12,
        "sales": 250_000_000,
        "expense_categories": ["設備投資", "人件費", "研究開発"],
    }
}

AUTONOMATH_OK_PAYLOAD = {
    "items": [
        {
            "unified_id": "P-001",
            "title": "ものづくり補助金",
            "authority": "中小企業庁",
            "tier": "S",
            "source_url": "https://portal.monodukuri-hojo.jp/",
        },
        {
            "unified_id": "P-002",
            "title": "事業再構築補助金",
            "authority": "経産省",
            "tier": "A",
            "source_url": "https://jigyou-saikouchiku.go.jp/",
        },
        {
            # Should be DROPPED — no source_url
            "unified_id": "P-BAD",
            "title": "怪しい補助金",
            "tier": "B",
        },
        {
            # Should be DROPPED — relative URL is not http(s)
            "unified_id": "P-BAD2",
            "title": "微妙な補助金",
            "tier": "B",
            "source_url": "/foo/bar",
        },
        {
            "unified_id": "P-003",
            "title": "IT導入補助金",
            "authority": "中小企業庁",
            "tier": "S",
            "source_url": "https://www.it-hojo.jp/",
        },
        {
            "unified_id": "P-004",
            "title": "省エネ補助金",
            "tier": "A",
            "source_url": "https://sii.or.jp/",
        },
    ]
}


def _freee_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.startswith("/api/1/companies/"):
        # Token must be forwarded verbatim
        assert request.headers.get("Authorization", "").startswith("Bearer ")
        return httpx.Response(200, json=FREEE_COMPANY_PAYLOAD)
    return httpx.Response(404)


def _autonomath_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/programs/search":
        # API key forwarded as X-API-Key, never in body / URL
        assert request.headers.get("X-API-Key", "")
        assert b"api_key" not in request.url.query
        return httpx.Response(200, json=AUTONOMATH_OK_PAYLOAD)
    return httpx.Response(404)


def _make_freee_client() -> httpx.Client:
    return httpx.Client(
        base_url="https://api.freee.co.jp",
        transport=httpx.MockTransport(_freee_handler),
        timeout=5.0,
    )


def _make_autonomath_client() -> httpx.Client:
    return httpx.Client(
        base_url="https://api.autonomath.jp",
        transport=httpx.MockTransport(_autonomath_handler),
        timeout=5.0,
    )


# ----- unit tests ---------------------------------------------------------


def test_prefecture_lookup_complete():
    assert len(PREFECTURE_BY_CODE) == 47
    assert PREFECTURE_BY_CODE[13] == "東京都"
    assert PREFECTURE_BY_CODE[27] == "大阪府"


def test_fetch_company_context_normalizes_freee_payload():
    with _make_freee_client() as client:
        ctx = fetch_company_context(
            freee_access_token="dummy_token_AAA",
            company_id=999001,
            http_client=client,
        )
    assert isinstance(ctx, CompanyContext)
    assert ctx.prefecture == "東京都"
    assert ctx.corporate_class == "houjin"
    assert ctx.industry_jsic == "G3911"
    assert ctx.employee_count == 12
    assert ctx.revenue_yen == 250_000_000
    assert ctx.expense_categories == ["設備投資", "人件費", "研究開発"]


def test_fetch_company_context_rejects_empty_token():
    with pytest.raises(ValueError):
        fetch_company_context(freee_access_token="", company_id=1)


def test_build_search_params_shape():
    ctx = CompanyContext(
        prefecture="東京都",
        corporate_class="houjin",
        expense_categories=["設備投資", "人件費"],
    )
    p = _build_search_params(ctx, limit=5)
    assert p["limit"] == 5
    assert p["prefecture"] == "東京都"
    assert p["tier"] == ["S", "A", "B"]
    assert p["target_type"] == ["houjin"]
    assert p["funding_purpose"] == ["設備投資", "人件費"]


def test_build_search_params_minimal_context():
    ctx = CompanyContext()
    p = _build_search_params(ctx, limit=3)
    assert p == {"limit": 3, "tier": ["S", "A", "B"]}


def test_call_autonomath_rejects_empty_key():
    with pytest.raises(ValueError):
        call_autonomath_search(autonomath_api_key="", params={})


def test_call_autonomath_returns_items():
    with _make_autonomath_client() as client:
        items = call_autonomath_search(
            autonomath_api_key="am_test_KEY",
            params={"limit": 5, "tier": ["S", "A"]},
            http_client=client,
        )
    assert len(items) == 6  # raw — drop happens in recommend()
    assert items[0]["unified_id"] == "P-001"


# ----- integration via mock ----------------------------------------------


def test_recommend_end_to_end_drops_rows_without_source_url():
    with _make_freee_client() as fc, _make_autonomath_client() as ac:
        out = recommend(
            freee_access_token="dummy_token_BBB",
            company_id=999001,
            autonomath_api_key="am_test_KEY",
            limit=5,
            freee_client=fc,
            autonomath_client=ac,
        )
    assert all(isinstance(x, ProgramRecommendation) for x in out)
    # 6 raw → 2 dropped (P-BAD no url, P-BAD2 relative) → 4 kept
    assert len(out) == 4
    ids = [r.unified_id for r in out]
    assert "P-BAD" not in ids
    assert "P-BAD2" not in ids
    assert ids == ["P-001", "P-002", "P-003", "P-004"]
    for r in out:
        assert r.source_url.startswith("https://")


def test_recommend_caps_at_limit():
    with _make_freee_client() as fc, _make_autonomath_client() as ac:
        out = recommend(
            freee_access_token="dummy_token_CCC",
            company_id=999001,
            autonomath_api_key="am_test_KEY",
            limit=2,
            freee_client=fc,
            autonomath_client=ac,
        )
    assert len(out) == 2
    assert [r.unified_id for r in out] == ["P-001", "P-002"]


def test_recommend_rejects_invalid_limit():
    with pytest.raises(ValueError):
        recommend(
            freee_access_token="x",
            company_id=1,
            autonomath_api_key="y",
            limit=0,
        )
    with pytest.raises(ValueError):
        recommend(
            freee_access_token="x",
            company_id=1,
            autonomath_api_key="y",
            limit=10,
        )


# ----- security invariants -----------------------------------------------


def test_glue_does_not_log_tokens(caplog):
    """Tokens must never appear in log output (zero-touch / no leak)."""
    secret_freee = "FREEE_SECRET_xyz_DO_NOT_LEAK"
    secret_am = "AM_SECRET_xyz_DO_NOT_LEAK"
    with caplog.at_level(logging.DEBUG):
        with _make_freee_client() as fc, _make_autonomath_client() as ac:
            recommend(
                freee_access_token=secret_freee,
                company_id=999001,
                autonomath_api_key=secret_am,
                limit=3,
                freee_client=fc,
                autonomath_client=ac,
            )
    full_log = "\n".join(rec.getMessage() for rec in caplog.records)
    assert secret_freee not in full_log
    assert secret_am not in full_log


def test_glue_module_has_no_module_level_state():
    """The glue must be stateless — no caches / globals / DB handles."""
    import freee_to_autonomath as mod

    # Allow constants and types; reject anything that smells like state
    forbidden_names = ("_cache", "_token", "_session", "_pool", "_db", "_storage")
    for name in dir(mod):
        if name.startswith("__") and name.endswith("__"):
            continue  # ignore Python dunder attributes
        for needle in forbidden_names:
            assert needle not in name, "unexpected stateful symbol: " + name


def test_recommend_returns_json_serializable():
    """Plugin will likely re-emit results as JSON to the freee UI bridge."""
    with _make_freee_client() as fc, _make_autonomath_client() as ac:
        out = recommend(
            freee_access_token="t",
            company_id=999001,
            autonomath_api_key="k",
            limit=5,
            freee_client=fc,
            autonomath_client=ac,
        )
    payload = [r.model_dump() for r in out]
    blob = json.dumps(payload, ensure_ascii=False)
    assert "P-001" in blob
    assert "source_url" in blob
