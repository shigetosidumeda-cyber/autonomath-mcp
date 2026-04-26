"""Tests for the sync + async autonomath client using httpx.MockTransport."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest

from autonomath import (
    AsyncClient,
    AuthError,
    AutonoMathError,
    Client,
    JpintelError,
    NotFoundError,
    RateLimitError,
    ServerError,
)
from autonomath import __version__ as sdk_version

# ---------- fixtures / factories ----------


def _sample_program(unified_id: str = "UNI-1", tier: str = "S") -> dict[str, Any]:
    return {
        "unified_id": unified_id,
        "primary_name": "テスト補助金",
        "aliases": [],
        "authority_level": "国",
        "authority_name": None,
        "prefecture": "東京都",
        "municipality": None,
        "program_kind": "補助金",
        "official_url": None,
        "amount_max_man_yen": 1000.0,
        "amount_min_man_yen": None,
        "subsidy_rate": None,
        "trust_level": None,
        "tier": tier,
        "coverage_score": None,
        "gap_to_tier_s": [],
        "a_to_j_coverage": {},
        "excluded": False,
        "exclusion_reason": None,
        "crop_categories": [],
        "equipment_category": None,
        "target_types": ["corporation"],
        "funding_purpose": ["設備投資"],
        "amount_band": None,
        "application_window": None,
    }


def _make_client(
    handler,
    *,
    api_key: str | None = "am_test",
    max_retries: int = 3,
) -> Client:
    transport = httpx.MockTransport(handler)
    return Client(
        api_key=api_key,
        base_url="https://api.test",
        max_retries=max_retries,
        transport=transport,
    )


def _make_async_client(
    handler,
    *,
    api_key: str | None = "am_test",
    max_retries: int = 3,
) -> AsyncClient:
    transport = httpx.MockTransport(handler)
    return AsyncClient(
        api_key=api_key,
        base_url="https://api.test",
        max_retries=max_retries,
        transport=transport,
    )


# ---------- tests ----------


def test_meta_parses_and_sends_auth_header() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "total_programs": 42,
                "tier_counts": {"S": 1, "A": 2},
                "prefecture_counts": {"東京都": 3},
                "exclusion_rules_count": 7,
                "last_ingested_at": "2026-04-22T00:00:00Z",
                "data_as_of": None,
            },
        )

    with _make_client(handler) as c:
        meta = c.meta()

    assert meta.total_programs == 42
    assert meta.tier_counts["S"] == 1
    assert seen["method"] == "GET"
    assert seen["url"] == "https://api.test/meta"
    assert seen["headers"]["x-api-key"] == "am_test"
    assert seen["headers"]["user-agent"] == f"autonomath-python/{sdk_version}"


def test_search_builds_repeated_query_params() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = parse_qsl(request.url.query.decode("utf-8"), keep_blank_values=True)
        return httpx.Response(
            200,
            json={
                "total": 1,
                "limit": 20,
                "offset": 0,
                "results": [_sample_program()],
            },
        )

    with _make_client(handler) as c:
        resp = c.search_programs(
            q="認定",
            tier=["S", "A"],
            funding_purpose=["設備投資", "継承"],
            amount_min=100,
            limit=20,
        )

    assert resp.total == 1
    assert resp.results[0].unified_id == "UNI-1"
    assert ("tier", "S") in seen["query"]
    assert ("tier", "A") in seen["query"]
    assert ("funding_purpose", "設備投資") in seen["query"]
    assert ("funding_purpose", "継承") in seen["query"]
    assert ("q", "認定") in seen["query"]
    assert ("amount_min", "100") in seen["query"] or ("amount_min", "100.0") in seen["query"]
    # default include_excluded should be sent as "false"
    assert ("include_excluded", "false") in seen["query"]


def test_get_program_404_raises_notfound() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "program not found"})

    with _make_client(handler) as c, pytest.raises(NotFoundError) as excinfo:
        c.get_program("UNI-missing")

    assert excinfo.value.status_code == 404
    assert "not found" in str(excinfo.value)


def test_auth_error_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid api key"})

    with _make_client(handler) as c, pytest.raises(AuthError):
        c.meta()


def test_retries_5xx_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="busy")
        return httpx.Response(
            200,
            json={
                "total_programs": 1,
                "tier_counts": {},
                "prefecture_counts": {},
                "exclusion_rules_count": 0,
                "last_ingested_at": None,
                "data_as_of": None,
            },
        )

    monkeypatch.setattr("autonomath.client.time.sleep", lambda s: sleeps.append(s))

    with _make_client(handler) as c:
        meta = c.meta()

    assert meta.total_programs == 1
    assert calls["n"] == 3
    assert len(sleeps) == 2  # two retries before success
    # exponential backoff: 0.5, 1.0
    assert sleeps[0] == pytest.approx(0.5)
    assert sleeps[1] == pytest.approx(1.0)


def test_rate_limit_retries_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            429,
            headers={"Retry-After": "2"},
            json={"detail": "daily limit exceeded"},
        )

    monkeypatch.setattr("autonomath.client.time.sleep", lambda s: sleeps.append(s))

    with _make_client(handler, max_retries=2) as c, pytest.raises(RateLimitError) as excinfo:
        c.meta()

    assert calls["n"] == 3  # initial + 2 retries
    assert excinfo.value.retry_after == pytest.approx(2.0)
    assert sleeps == [2.0, 2.0]


def test_check_exclusions_post_body() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "program_ids": ["UNI-a", "UNI-b"],
                "hits": [
                    {
                        "rule_id": "excl-1",
                        "kind": "absolute",
                        "severity": "critical",
                        "programs_involved": ["UNI-a", "UNI-b"],
                        "description": "テスト",
                        "source_urls": [],
                    }
                ],
                "checked_rules": 1,
            },
        )

    with _make_client(handler) as c:
        resp = c.check_exclusions(["UNI-a", "UNI-b"])

    assert seen["method"] == "POST"
    assert seen["body"] == {"program_ids": ["UNI-a", "UNI-b"]}
    assert resp.checked_rules == 1
    assert resp.hits[0].rule_id == "excl-1"


def test_check_exclusions_rejects_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("client should not make a request for empty input")

    with _make_client(handler) as c, pytest.raises(ValueError):
        c.check_exclusions([])


def test_server_error_exhausts_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    monkeypatch.setattr("autonomath.client.time.sleep", lambda s: None)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="boom")

    with _make_client(handler, max_retries=2) as c, pytest.raises(ServerError):
        c.meta()

    assert calls["n"] == 3


def test_list_exclusion_rules() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/exclusions/rules"
        return httpx.Response(
            200,
            json=[
                {
                    "rule_id": "r1",
                    "kind": "absolute",
                    "severity": "critical",
                    "program_a": "UNI-a",
                    "program_b": "UNI-b",
                    "program_b_group": [],
                    "description": "d",
                    "source_notes": None,
                    "source_urls": [],
                    "extra": {},
                }
            ],
        )

    with _make_client(handler) as c:
        rules = c.list_exclusion_rules()

    assert len(rules) == 1
    assert rules[0].rule_id == "r1"
    assert rules[0].kind == "absolute"


def test_jpintel_error_alias_still_importable() -> None:
    """JpintelError must remain a working alias of AutonoMathError for backwards compat."""
    assert JpintelError is AutonoMathError
    # Subclasses should satisfy isinstance checks against the deprecated alias too.
    err = AuthError("nope", status_code=401)
    assert isinstance(err, JpintelError)
    assert isinstance(err, AutonoMathError)


# ---------- async ----------


@pytest.mark.asyncio
async def test_async_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "am_test"
        return httpx.Response(
            200,
            json={
                "total_programs": 10,
                "tier_counts": {"S": 1},
                "prefecture_counts": {},
                "exclusion_rules_count": 0,
                "last_ingested_at": None,
                "data_as_of": None,
            },
        )

    async with _make_async_client(handler) as c:
        meta = await c.meta()

    assert meta.total_programs == 10


@pytest.mark.asyncio
async def test_async_retries_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr("autonomath.client_async.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(
            200,
            json={
                "total_programs": 0,
                "tier_counts": {},
                "prefecture_counts": {},
                "exclusion_rules_count": 0,
                "last_ingested_at": None,
                "data_as_of": None,
            },
        )

    async with _make_async_client(handler) as c:
        meta = await c.meta()

    assert meta.total_programs == 0
    assert calls["n"] == 2
    assert sleeps == [pytest.approx(0.5)]
