"""Smoke tests for the jpcite email digest cron.

Pure-mock: every jpcite REST call routes through ``httpx.MockTransport``;
no SendGrid / SES / Mailchimp request is ever issued (the transport
stubs only construct payloads).
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

import httpx
import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

from email_digest import (  # noqa: E402
    DigestSection,
    PreparedSend,
    RenderedDigest,
    SavedSearch,
    build_digest_for_customer,
    execute_saved_search,
    fetch_saved_searches,
    iter_recent_results,
    prepare_mailchimp_send,
    prepare_sendgrid_send,
    prepare_ses_send,
    render_digest,
)

# ---- helpers ---------------------------------------------------------------


def _client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


SAVED_SEARCH_PAYLOAD = {
    "results": [
        {
            "id": "ss_001",
            "name": "東京都 設備投資 (補助金)",
            "endpoint": "/v1/programs/search",
            "params": {"q": "東京都 設備投資"},
        },
        {
            "id": "ss_002",
            "name": "ものづくり (製造業)",
            "endpoint": "/v1/programs/search",
            "params": {"q": "ものづくり 製造"},
        },
    ]
}

PROGRAMS_OK = {
    "results": [
        {
            "name": "ものづくり補助金",
            "authority": "中小企業庁",
            "source_url": "https://portal.monodukuri-hojo.jp/",
        },
        # Should be dropped — neither source_url nor authority.
        {"name": "怪しい補助金"},
        {
            "name": "事業再構築補助金",
            "authority": "経産省",
            "source_url": "https://jigyou-saikouchiku.go.jp/",
        },
    ]
}


# ---- saved-search list -----------------------------------------------------


def test_fetch_saved_searches_normalizes_rows():
    def handler(req: httpx.Request) -> httpx.Response:
        assert "/v1/me/saved_searches" in str(req.url)
        return httpx.Response(200, json=SAVED_SEARCH_PAYLOAD)

    with _client_for(handler) as client:
        rows = fetch_saved_searches(api_key="k", client=client)
    assert len(rows) == 2
    assert rows[0].id == "ss_001"
    assert rows[0].endpoint == "/v1/programs/search"
    assert rows[0].params["q"] == "東京都 設備投資"


def test_fetch_saved_searches_drops_malformed_rows():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": "x"},  # missing name
                    {"name": "y"},  # missing id
                    {
                        "id": "z",
                        "name": "valid",
                        "endpoint": "/v1/programs/search",
                    },
                ]
            },
        )

    with _client_for(handler) as client:
        rows = fetch_saved_searches(api_key="k", client=client)
    assert [r.id for r in rows] == ["z"]


# ---- saved-search execution ------------------------------------------------


def test_execute_saved_search_filters_aggregator_rows():
    def handler(req: httpx.Request) -> httpx.Response:
        assert "/v1/programs/search" in str(req.url)
        return httpx.Response(200, json=PROGRAMS_OK)

    saved = SavedSearch(
        id="ss_001",
        name="東京都 設備投資",
        endpoint="/v1/programs/search",
        params={"q": "東京都 設備投資"},
    )
    with _client_for(handler) as client:
        section = execute_saved_search(saved, api_key="k", client=client)
    assert section.error_code is None
    assert len(section.items) == 2
    names = [r["name"] for r in section.items]
    assert "怪しい補助金" not in names


@pytest.mark.parametrize(
    "status, expected",
    [
        (401, "AUTH_ERROR"),
        (403, "AUTH_ERROR"),
        (404, "NOT_FOUND"),
        (429, "RATE_LIMITED"),
        (500, "HTTP_500"),
    ],
)
def test_execute_saved_search_maps_http_errors(status, expected):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "x"})

    saved = SavedSearch(
        id="ss_001",
        name="x",
        endpoint="/v1/programs/search",
        params={},
    )
    with _client_for(handler) as client:
        section = execute_saved_search(saved, api_key="k", client=client)
    assert section.error_code == expected
    assert section.items == []


# ---- template rendering ----------------------------------------------------


@pytest.fixture
def two_section_digest() -> RenderedDigest:
    sections = [
        DigestSection(
            saved_search=SavedSearch(
                id="s1",
                name="東京都 補助金",
                endpoint="/v1/programs/search",
                params={"q": "東京都"},
            ),
            items=[
                {
                    "name": "ものづくり補助金",
                    "authority": "中小企業庁",
                    "source_url": "https://portal.monodukuri-hojo.jp/",
                }
            ],
        ),
        DigestSection(
            saved_search=SavedSearch(
                id="s2",
                name="ものづくり (404 系)",
                endpoint="/v1/programs/search",
                params={},
            ),
            items=[],
            error_code="NOT_FOUND",
        ),
    ]
    return render_digest(
        customer_name="テスト顧客",
        sections=sections,
        generated_at=_dt.datetime(2026, 5, 1, 0, 0, 0, tzinfo=_dt.UTC),
    )


def test_render_digest_html_contains_links_and_brand(two_section_digest):
    html = two_section_digest.html_body
    assert "ものづくり補助金" in html
    assert "https://portal.monodukuri-hojo.jp/" in html
    assert "Bookyou" in html
    assert "T8010001213708" in html
    assert "¥3/req" in html
    assert "テスト顧客" in html


def test_render_digest_text_carries_error_section(two_section_digest):
    txt = two_section_digest.text_body
    assert "ものづくり (404 系)" in txt
    assert "NOT_FOUND" in txt
    assert "テスト顧客" in txt


def test_render_digest_subject_includes_year_month(two_section_digest):
    assert "2026-05" in two_section_digest.subject


def test_iter_recent_results_returns_names(two_section_digest):
    first = list(iter_recent_results(two_section_digest.sections[0]))
    assert first == ["ものづくり補助金"]


# ---- transport stubs (no real send) ----------------------------------------


def test_prepare_sendgrid_does_not_send_and_carries_both_bodies(two_section_digest):
    prepared = prepare_sendgrid_send(
        digest=two_section_digest,
        to_email="customer@example.co.jp",
        from_email="info@bookyou.net",
        api_key="SG.fake",
    )
    assert isinstance(prepared, PreparedSend)
    assert prepared.transport == "sendgrid"
    assert prepared.url == "https://api.sendgrid.com/v3/mail/send"
    assert prepared.headers["Authorization"] == "Bearer SG.fake"
    types = [c["type"] for c in prepared.body["content"]]
    assert "text/plain" in types and "text/html" in types
    assert prepared.body["personalizations"][0]["to"][0]["email"] == "customer@example.co.jp"


def test_prepare_ses_targets_tokyo_region(two_section_digest):
    prepared = prepare_ses_send(
        digest=two_section_digest,
        to_email="customer@example.co.jp",
        from_email="info@bookyou.net",
    )
    assert "ap-northeast-1" in prepared.url
    assert prepared.transport == "ses"
    assert prepared.body["FromEmailAddress"] == "info@bookyou.net"
    simple = prepared.body["Content"]["Simple"]
    assert simple["Subject"]["Charset"] == "UTF-8"
    assert simple["Body"]["Html"]["Data"] == two_section_digest.html_body


def test_prepare_mailchimp_carries_html_and_text(two_section_digest):
    prepared = prepare_mailchimp_send(
        digest=two_section_digest,
        to_email="customer@example.co.jp",
        from_email="info@bookyou.net",
        api_key="md-key",
    )
    assert prepared.transport == "mailchimp"
    assert prepared.body["key"] == "md-key"
    msg = prepared.body["message"]
    assert msg["from_email"] == "info@bookyou.net"
    assert msg["to"][0]["email"] == "customer@example.co.jp"
    assert msg["html"] == two_section_digest.html_body
    assert msg["text"] == two_section_digest.text_body


@pytest.mark.parametrize(
    "kw",
    [
        {"to_email": "not-an-email", "from_email": "info@bookyou.net", "api_key": "k"},
        {"to_email": "x@y.z", "from_email": "broken", "api_key": "k"},
        {"to_email": "x@y.z", "from_email": "info@bookyou.net", "api_key": ""},
    ],
)
def test_prepare_sendgrid_validates_inputs(kw, two_section_digest):
    with pytest.raises((ValueError,)):
        prepare_sendgrid_send(digest=two_section_digest, **kw)


# ---- end-to-end (mocked) ---------------------------------------------------


def test_build_digest_for_customer_e2e_mocked():
    """Single-call entrypoint: list saved searches, run them, render."""
    call_log: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        call_log.append(path)
        if path.endswith("/v1/me/saved_searches"):
            return httpx.Response(200, json=SAVED_SEARCH_PAYLOAD)
        if path.endswith("/v1/programs/search"):
            return httpx.Response(200, json=PROGRAMS_OK)
        return httpx.Response(404, json={"error": "x"})

    with _client_for(handler) as client:
        digest = build_digest_for_customer(
            customer_name="テスト顧客",
            api_key="k",
            client=client,
            generated_at=_dt.datetime(2026, 5, 1, tzinfo=_dt.UTC),
        )
    assert "/v1/me/saved_searches" in call_log[0]
    # 2 saved searches → 2 search calls
    assert sum(1 for p in call_log if p.endswith("/v1/programs/search")) == 2
    assert digest.subject.startswith("[jpcite]")
    assert "ものづくり補助金" in digest.html_body
    assert "テスト顧客" in digest.text_body


# ---- module hygiene --------------------------------------------------------


def test_no_llm_imports():
    body = (PLUGIN_ROOT / "email_digest.py").read_text(encoding="utf-8")
    for forbidden in (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "claude_agent_sdk",
        "google.generativeai",
    ):
        assert forbidden not in body, f"email_digest.py must not embed {forbidden!r} (CLAUDE.md)"


def test_readme_brand_disclaimers_present():
    body = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Bookyou" in body
    assert "T8010001213708" in body
    assert "¥3/req" in body
    assert "info@bookyou.net" in body
