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


def _sample_evidence_packet(entity_id: str = "UNI-1") -> dict[str, Any]:
    return {
        "packet_id": "ep_test",
        "generated_at": "2026-05-06T00:00:00Z",
        "api_version": "v1",
        "corpus_snapshot_id": "snap_test",
        "query": {"subject_kind": "program"},
        "answer_not_included": True,
        "records": [
            {
                "entity_id": entity_id,
                "primary_name": "テスト補助金",
                "source_url": "https://example.test/source",
            }
        ],
        "quality": {"known_gaps": []},
        "verification": {"replay_endpoint": "/v1/evidence/packets/program/UNI-1"},
        "decision_insights": {
            "schema_version": "v1",
            "generated_from": ["records"],
            "why_review": [],
            "next_checks": [],
            "evidence_gaps": [],
        },
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


def test_get_evidence_packet_builds_query_params() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["query"] = parse_qsl(request.url.query.decode("utf-8"), keep_blank_values=True)
        return httpx.Response(200, json=_sample_evidence_packet())

    with _make_client(handler) as c:
        packet = c.get_evidence_packet(
            "program",
            "UNI-1",
            include_facts=False,
            packet_profile="brief",
            source_tokens_basis="pdf_pages",
            source_pdf_pages=12,
        )

    assert seen["method"] == "GET"
    assert seen["path"] == "/v1/evidence/packets/program/UNI-1"
    assert ("include_facts", "false") in seen["query"]
    assert ("packet_profile", "brief") in seen["query"]
    assert ("source_tokens_basis", "pdf_pages") in seen["query"]
    assert ("source_pdf_pages", "12") in seen["query"]
    assert packet.records[0].entity_id == "UNI-1"
    assert packet.decision_insights is not None


def test_query_evidence_packet_posts_body() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_sample_evidence_packet("UNI-2"))

    with _make_client(handler) as c:
        packet = c.query_evidence_packet(
            query_text="省エネ 東京都",
            filters={"prefecture": "東京都"},
            include_rules=True,
        )

    assert seen["method"] == "POST"
    assert seen["path"] == "/v1/evidence/packets/query"
    assert seen["body"]["query_text"] == "省エネ 東京都"
    assert seen["body"]["filters"] == {"prefecture": "東京都"}
    assert seen["body"]["include_rules"] is True
    assert packet.records[0].entity_id == "UNI-2"


def test_intel_and_funding_methods_call_expected_endpoints() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        seen.append(
            {
                "method": request.method,
                "path": request.url.path,
                "query": parse_qsl(request.url.query.decode("utf-8"), keep_blank_values=True),
                "body": body,
            }
        )
        if request.url.path == "/v1/intel/match":
            return httpx.Response(
                200,
                json={
                    "matched_programs": [{"program_id": "UNI-1", "primary_name": "補助金"}],
                    "total_candidates": 1,
                    "applied_filters": ["prefecture"],
                    "_disclaimer": "verify",
                    "_billing_unit": 1,
                },
            )
        if request.url.path == "/v1/intel/bundle/optimal":
            return httpx.Response(
                200,
                json={
                    "houjin_id": "8010001213708",
                    "bundle": [],
                    "bundle_total": {},
                    "conflict_avoidance": {},
                    "optimization_log": {},
                    "runner_up_bundles": [],
                    "data_quality": {},
                    "decision_support": {},
                    "_billing_unit": 1,
                },
            )
        if request.url.path == "/v1/intel/houjin/8010001213708/full":
            return httpx.Response(
                200,
                json={
                    "houjin_bangou": "8010001213708",
                    "sections_returned": ["meta"],
                    "max_per_section": 2,
                    "decision_support": {},
                    "_billing_unit": 1,
                },
            )
        if request.url.path == "/v1/funding_stack/check":
            return httpx.Response(
                200,
                json={
                    "program_ids": ["UNI-a", "UNI-b"],
                    "all_pairs_status": "compatible",
                    "pairs": [
                        {
                            "program_a": "UNI-a",
                            "program_b": "UNI-b",
                            "verdict": "compatible",
                            "confidence": 1.0,
                            "rule_chain": [],
                            "next_actions": [
                                {
                                    "action_id": "keep_evidence",
                                    "label_ja": "併用可の根拠を保存する",
                                    "detail_ja": "一次資料 URL と確認日を保存する。",
                                    "reason": "後日の照会で根拠を提示するため。",
                                    "source_fields": ["rule_chain"],
                                }
                            ],
                            "_disclaimer": "verify",
                        }
                    ],
                    "blockers": [],
                    "warnings": [],
                    "next_actions": [
                        {
                            "action_id": "keep_evidence",
                            "label_ja": "併用可の根拠を保存する",
                            "detail_ja": "一次資料 URL と確認日を保存する。",
                            "reason": "後日の照会で根拠を提示するため。",
                            "source_fields": ["rule_chain"],
                        }
                    ],
                    "total_pairs": 1,
                    "_billing_unit": 1,
                },
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    with _make_client(handler) as c:
        match = c.intel_match(
            industry_jsic_major="E",
            prefecture_code="13",
            capital_jpy=10_000_000,
            keyword="DX",
        )
        bundle = c.intel_bundle_optimal(houjin_id="8010001213708", bundle_size=3)
        houjin = c.get_intel_houjin_full(
            "8010001213708",
            include_sections=["meta"],
            max_per_section=2,
        )
        funding = c.check_funding_stack(["UNI-a", "UNI-b"])

    assert match.matched_programs[0].program_id == "UNI-1"
    assert match.billing_unit == 1
    assert bundle.houjin_id == "8010001213708"
    assert houjin.sections_returned == ["meta"]
    assert funding.total_pairs == 1
    assert funding.next_actions[0].action_id == "keep_evidence"
    assert funding.pairs[0].next_actions[0].label_ja
    assert seen[0]["body"]["industry_jsic_major"] == "E"
    assert seen[1]["body"]["bundle_size"] == 3
    assert ("include_sections", "meta") in seen[2]["query"]
    assert seen[3]["body"] == {"program_ids": ["UNI-a", "UNI-b"]}


def test_check_funding_stack_rejects_single_program() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("client should not make a request for one program")

    with _make_client(handler) as c, pytest.raises(ValueError):
        c.check_funding_stack(["UNI-a"])


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


@pytest.mark.asyncio
async def test_async_intel_match() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "matched_programs": [{"program_id": "UNI-async"}],
                "total_candidates": 1,
                "applied_filters": [],
                "_billing_unit": 1,
            },
        )

    async with _make_async_client(handler) as c:
        resp = await c.intel_match(industry_jsic_major="E", prefecture_code="13")

    assert seen["path"] == "/v1/intel/match"
    assert seen["body"]["prefecture_code"] == "13"
    assert resp.matched_programs[0].program_id == "UNI-async"
