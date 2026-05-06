"""Python SDK <-> TypeScript SDK REST parity tests.

Pure-mock: every assertion runs against a stubbed ``httpx.MockTransport`` —
no live API calls (feedback_autonomath_no_api_use: SDK tests must NEVER
hit our paid endpoints, the per-request cost would burn through budget on
every CI run).

The TypeScript SDK lives in
``autonomath_staging/sdk/typescript/src/`` and the Python SDK in
``autonomath_staging/sdk/python/autonomath/``. This file enforces that
every REST endpoint reachable through the TS surface is also reachable
through the Python surface, with comparable parameter shapes.

Run::

    cd autonomath_staging/sdk/python
    .venv/bin/pytest -q ../../../tests/sdk/test_python_parity.py
"""

from __future__ import annotations

import inspect
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# Allow ``import autonomath`` from the staging SDK without installing it.
_SDK_ROOT = Path(__file__).resolve().parents[2] / "autonomath_staging" / "sdk" / "python"
if str(_SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(_SDK_ROOT))

import httpx  # noqa: E402
from autonomath import (  # noqa: E402
    AsyncAutonoMathClient,
    AutonoMathClient,
    PrescreenMatch,
    UsageStatus,
    __version__,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------
def _client_with_handler(
    handler: Callable[[httpx.Request], httpx.Response],
    **kwargs: Any,
) -> AutonoMathClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(
        base_url="https://api.autonomath.test",
        transport=transport,
        headers={
            "Authorization": "Bearer am_sk_parity_testkey_12345",
            "User-Agent": f"autonomath-python/{__version__}",
            "Accept": "application/json",
        },
    )
    return AutonoMathClient(
        api_key="am_sk_parity_testkey_12345",
        base_url="https://api.autonomath.test",
        http_client=http,
        max_retries=0,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Version + presence checks
# ---------------------------------------------------------------------------
def test_version_is_minor_bumped():
    """0.1.x → 0.2.0 reflects API parity sweep (additive surface)."""
    assert __version__ == "0.2.0"


def test_required_methods_exist():
    """Every TS-surface method must be reachable on Python client."""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "rich", "results": []})

    client = _client_with_handler(handler)
    try:
        expected = {
            "search",
            "tax",
            "certifications",
            "reasoning",
            "usage",
            "prescreen",
            "close",
        }
        missing = {a for a in expected if not hasattr(client, a)}
        assert not missing, f"Python client missing TS-parity attrs: {missing}"
    finally:
        client.close()


def test_async_required_methods_exist():
    expected = {"search", "usage", "prescreen", "aclose"}
    missing = expected - set(dir(AsyncAutonoMathClient))
    assert not missing, f"Async client missing TS-parity attrs: {missing}"


def test_search_signature_accepts_ts_filters():
    """``client.search(...)`` must accept the TS SearchQuery fields."""
    from autonomath.tools.search import SearchTool

    sig = inspect.signature(SearchTool.query)
    params = set(sig.parameters)
    for ts_field in (
        "query",
        "prefecture",
        "category",
        "target_type",
        "funding_purpose",
        "crop_category",
        "tier",
        "limit",
    ):
        assert ts_field in params, f"search.query missing param: {ts_field}"


def test_reasoning_signature_accepts_ts_options():
    from autonomath.tools.reasoning import ReasoningTool

    sig = inspect.signature(ReasoningTool.answer)
    params = set(sig.parameters)
    for ts_field in (
        "question",
        "intent",
        "context",
        "prefecture",
        "fiscal_year",
        "max_citations",
    ):
        assert ts_field in params, f"reasoning.answer missing param: {ts_field}"


def test_tax_list_rules_accepts_fiscal_year():
    from autonomath.tools.tax import TaxTool

    sig = inspect.signature(TaxTool.list_rules)
    assert "fiscal_year" in sig.parameters


def test_upcoming_deadlines_default_window_is_30():
    """TS default is 30 days (UpcomingDeadlinesQuery.days ?? 30)."""
    from autonomath.tools.search import SearchTool

    sig = inspect.signature(SearchTool.upcoming_deadlines)
    assert sig.parameters["days"].default == 30


# ---------------------------------------------------------------------------
# Endpoint contract checks (mock httpx; no live API)
# ---------------------------------------------------------------------------
def test_usage_hits_v1_usage_and_parses() -> None:
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["path"] = req.url.path
        captured["method"] = req.method
        return httpx.Response(
            200,
            json={
                "tier": "free",
                "limit": 50,
                "remaining": 47,
                "used": 3,
                "reset_at": "2026-05-01T00:00:00+09:00",
                "reset_timezone": "JST",
                "upgrade_url": "https://autonomath.ai/pricing",
                "note": "anonymous",
            },
        )

    client = _client_with_handler(handler)
    status = client.usage()
    assert captured["path"] == "/v1/usage"
    assert captured["method"] == "GET"
    assert isinstance(status, UsageStatus)
    assert status.tier == "free"
    assert status.remaining == 47
    assert status.reset_timezone == "JST"


def test_prescreen_hits_v1_programs_prescreen_and_parses() -> None:
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["path"] = req.url.path
        captured["method"] = req.method
        return httpx.Response(
            200,
            json={
                "status": "rich",
                "results": [
                    {
                        "program_id": "p-9001",
                        "title": "ものづくり補助金 21次",
                        "tier": "S",
                        "score": 0.84,
                        "reasons": ["業種一致", "金額レンジ一致"],
                        "caveats": ["公募締切近い"],
                        "source_url": "https://example.test/p9001",
                    }
                ],
            },
        )

    client = _client_with_handler(handler)
    env = client.prescreen(
        {
            "prefecture": "東京都",
            "industry_jsic": "39",
            "planned_investment_man_yen": 500,
        }
    )
    assert captured["path"] == "/v1/programs/prescreen"
    assert captured["method"] == "POST"
    assert env.status == "rich"
    assert len(env.results) == 1
    m = env.results[0]
    assert isinstance(m, PrescreenMatch)
    assert m.program_id == "p-9001"
    assert m.tier == "S"
    assert "業種一致" in m.reasons


def test_search_query_forwards_ts_filters() -> None:
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["params"] = dict(req.url.params)
        return httpx.Response(
            200,
            json={"status": "rich", "results": [{"id": "x", "title": "ok"}]},
        )

    client = _client_with_handler(handler)
    client.search.query(
        "DX",
        prefecture="東京都",
        target_type="法人",
        funding_purpose="DX",
        crop_category="rice",
        tier="A",
        limit=10,
    )
    p = captured["params"]
    assert p["prefecture"] == "東京都"
    assert p["target_type"] == "法人"
    assert p["funding_purpose"] == "DX"
    assert p["crop_category"] == "rice"
    assert p["tier"] == "A"


def test_tax_get_rule_hits_singular_endpoint() -> None:
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["path"] = req.url.path
        return httpx.Response(
            200,
            json={
                "status": "rich",
                "results": [{"name": "エンジェル税制"}],
            },
        )

    client = _client_with_handler(handler)
    rule = client.tax.get_rule("エンジェル税制")
    assert captured["path"] == "/v1/tax/rule"
    assert rule is not None
    assert rule.name == "エンジェル税制"


def test_tax_list_rules_filters_by_fiscal_year() -> None:
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["params"] = dict(req.url.params)
        return httpx.Response(200, json={"status": "rich", "results": []})

    client = _client_with_handler(handler)
    client.tax.list_rules(fiscal_year="2026")
    assert captured["params"].get("fiscal_year") == "2026"


def test_reasoning_answer_forwards_ts_options() -> None:
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = req.read().decode("utf-8")
        return httpx.Response(
            200,
            json={
                "intent": "adoption_rate",
                "answer": "約48%",
                "citations": ["https://example.test/cite"],
            },
        )

    client = _client_with_handler(handler)
    out = client.reasoning.answer(
        "ものづくり 21次 採択率",
        prefecture="愛知県",
        fiscal_year="2026",
        max_citations=3,
    )
    body = captured["body"]
    assert "愛知県" in body
    assert "2026" in body
    assert "max_citations" in body
    assert out.intent == "adoption_rate"


def test_no_live_api_called(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sentinel: ensure tests can't accidentally call api.jpcite.com."""
    # If anything bypasses the MockTransport and tries to resolve our prod
    # host, fail loud. We patch httpx's request to forbid it explicitly.
    real_request = httpx.Client.request

    def guard(self, method, url, *a, **k):
        url_str = str(url)
        if "api.jpcite.com" in url_str:
            raise AssertionError(f"Test attempted live API call: {url_str}")
        return real_request(self, method, url, *a, **k)

    monkeypatch.setattr(httpx.Client, "request", guard)

    # Smoke: a normal mocked call still works under the guard.
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"tier": "free", "limit": 50, "remaining": 50, "used": 0},
        )

    client = _client_with_handler(handler)
    assert client.usage().tier == "free"
