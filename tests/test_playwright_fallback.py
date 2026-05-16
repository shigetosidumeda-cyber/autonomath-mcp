"""Tests for the Wave 36 Playwright fallback helper.

Covers
------
* Mock httpx failure/short body -> Playwright fallback path triggers.
* Aggregator URL refusal (CLAUDE.md "Data hygiene") fails closed.
* Viewport hard-cap (≤ 1600 px).
* sips resize (best-effort, no-op when sips absent).
* `screenshot_filename` emits stable hashed PNG names.
* All 11 ETL wires import the helper without errors.

The Playwright path itself is mocked — we never actually launch chromium
in the test suite. The mock asserts that `fetch_with_fallback()` routes
to the fallback after the first-pass httpx fetch fails or returns a short
body, but does not require the chromium binary to be present.

LLM API import scan: this test deliberately imports nothing from
`anthropic` / `openai` / `claude_agent_sdk`; the
`tests/test_no_llm_in_production.py` guard catches accidental imports.
"""

from __future__ import annotations

import asyncio
import importlib
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.etl._image_helper import (  # noqa: E402
    MAX_CLI_SAFE_PX,
    is_cli_safe,
    sips_resize_inplace,
)
from scripts.etl._playwright_helper import (  # noqa: E402
    JPCITE_USER_AGENT,
    MAX_RETRIES,
    MAX_SCREENSHOT_EDGE,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
    FetchResult,
    RenderResult,
    fetch_with_fallback,
    fetch_with_fallback_sync,
    is_banned_url,
    render_page,
    screenshot_filename,
)

# ---------------------------------------------------------------------------
# Aggregator URL refusal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://noukaweb.example.jp/subsidy/1",
        "https://www.hojyokin-portal.jp/test",
        "https://biz.stayway.jp/article/abc",
        "https://hojokin-portal.example/r",
    ],
)
def test_aggregator_url_refused(url: str) -> None:
    assert is_banned_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://www.meti.go.jp/sample",
        "https://www.jftc.go.jp/press.rss",
        "https://elaws.e-gov.go.jp/sample",
        "https://www.j-platpat.inpit.go.jp/gazette",
    ],
)
def test_legitimate_url_allowed(url: str) -> None:
    assert is_banned_url(url) is False


def test_fetch_with_fallback_sync_refuses_aggregator() -> None:
    result = fetch_with_fallback_sync("https://noukaweb.example.jp/x")
    assert result.source == "aggregator_refused"
    assert result.status == 0
    assert result.text == ""
    assert result.error == "aggregator_refused"


def test_fetch_with_fallback_async_refuses_aggregator() -> None:
    async def _run() -> FetchResult:
        return await fetch_with_fallback("https://hojyokin-portal.jp/x")

    result = asyncio.run(_run())
    assert result.source == "aggregator_refused"
    assert result.status == 0
    assert result.text == ""


# ---------------------------------------------------------------------------
# Viewport / screenshot ceiling
# ---------------------------------------------------------------------------


def test_viewport_within_cli_safe_bounds() -> None:
    """memory feedback_image_resize: ≤ 1600 px hard ceiling."""
    assert VIEWPORT_WIDTH <= 1600
    assert VIEWPORT_HEIGHT <= 1600
    assert MAX_SCREENSHOT_EDGE <= 1600
    assert MAX_CLI_SAFE_PX <= 1600


def test_banned_source_examples_refused() -> None:
    """CLAUDE.md Data hygiene: core aggregator examples stay refused."""
    assert is_banned_url("https://noukaweb.example.jp/foo") is True
    assert is_banned_url("https://hojyokin-portal.jp/foo") is True
    assert is_banned_url("https://biz.stayway.jp/foo") is True


def test_user_agent_brand_jpcite() -> None:
    """No legacy brand strings in the user-agent."""
    ua = JPCITE_USER_AGENT.lower()
    assert "jpcite" in ua
    assert "zeimu-kaikei" not in ua


# ---------------------------------------------------------------------------
# httpx-first -> Playwright fallback path
# ---------------------------------------------------------------------------


def test_httpx_success_short_circuits() -> None:
    """When httpx succeeds with enough body text, Playwright is never invoked."""
    body = "<html>" + ("OK" * 120) + "</html>"

    async def _run() -> FetchResult:
        def _fake_httpx_get(url: str, *, timeout_s: float, user_agent: str):
            return (200, body, url, None)

        render_mock = AsyncMock()
        with (
            patch(
                "scripts.etl._playwright_helper._httpx_get",
                side_effect=_fake_httpx_get,
            ),
            patch(
                "scripts.etl._playwright_helper._render_async",
                new=render_mock,
            ),
        ):
            result = await fetch_with_fallback("https://www.meti.go.jp/sample")
            assert render_mock.await_count == 0
            return result

    result = asyncio.run(_run())
    assert result.source == "httpx"
    assert result.status == 200
    assert result.text == body


def test_httpx_failure_then_fallback_invoked() -> None:
    """Failed first-pass httpx fetch -> Playwright path triggers."""
    attempts: list[int] = []
    render_kwargs: dict[str, object] = {}

    def _broken(url: str, *, timeout_s: float, user_agent: str):
        attempts.append(1)
        return (0, "", url, "RuntimeError: static fetch failed")

    async def _mock_render(url, **kw):  # noqa: ANN001
        render_kwargs.update(kw)
        return RenderResult(
            text="<html>rendered</html>",
            screenshot_path=None,
            status=200,
            final_url=url,
            fetched_at="2026-05-12T00:00:00Z",
            extractor="innertext",
            error=None,
        )

    with (
        patch(
            "scripts.etl._playwright_helper._httpx_get",
            side_effect=_broken,
        ),
        patch(
            "scripts.etl._playwright_helper._render_async",
            new=AsyncMock(side_effect=_mock_render),
        ),
    ):

        async def _run() -> FetchResult:
            return await fetch_with_fallback("https://www.meti.go.jp/sample-broken")

        result = asyncio.run(_run())

    assert len(attempts) == 1
    assert render_kwargs["max_retries"] == MAX_RETRIES
    assert result.source == "playwright"
    assert "rendered" in result.text


def test_short_httpx_body_triggers_fallback() -> None:
    """A 200 response with too little body text still asks Playwright."""

    def _short(url: str, *, timeout_s: float, user_agent: str):
        return (200, "tiny", url, None)

    async def _mock_render(url, **kw):  # noqa: ANN001, ARG001
        return RenderResult(
            text="FULL_DOM_TEXT",
            screenshot_path=None,
            status=200,
            final_url=url,
            fetched_at="2026-05-12T00:00:00Z",
            extractor="innertext",
            error=None,
        )

    with (
        patch(
            "scripts.etl._playwright_helper._httpx_get",
            side_effect=_short,
        ),
        patch(
            "scripts.etl._playwright_helper._render_async",
            new=AsyncMock(side_effect=_mock_render),
        ),
    ):

        async def _run() -> FetchResult:
            return await fetch_with_fallback("https://www.meti.go.jp/short")

        result = asyncio.run(_run())

    assert result.source == "playwright"
    assert result.text == "FULL_DOM_TEXT"


def test_playwright_failure_returns_error_result() -> None:
    """Both httpx + Playwright fail -> source='error' without raising."""

    def _broken(url: str, *, timeout_s: float, user_agent: str):
        return (0, "", url, "RuntimeError: httpx down")

    async def _mock_render(url, **kw):  # noqa: ANN001, ARG001
        return RenderResult(
            text="",
            screenshot_path=None,
            status=0,
            final_url=url,
            fetched_at="2026-05-12T00:00:00Z",
            extractor="",
            error="RuntimeError: chromium crashed",
        )

    with (
        patch(
            "scripts.etl._playwright_helper._httpx_get",
            side_effect=_broken,
        ),
        patch(
            "scripts.etl._playwright_helper._render_async",
            new=AsyncMock(side_effect=_mock_render),
        ),
    ):

        async def _run() -> FetchResult:
            return await fetch_with_fallback("https://www.meti.go.jp/double-down")

        result = asyncio.run(_run())

    assert result.source == "error"
    assert result.text == ""
    assert result.error == "RuntimeError: chromium crashed"


# ---------------------------------------------------------------------------
# screenshot_filename
# ---------------------------------------------------------------------------


def test_screenshot_filename_format_and_stability() -> None:
    name = screenshot_filename("https://www.jpo.go.jp/sample")
    assert name == screenshot_filename("https://www.jpo.go.jp/sample")
    assert re.fullmatch(r"[0-9a-f]{16}\.png", name)


# ---------------------------------------------------------------------------
# sips resize (best-effort)
# ---------------------------------------------------------------------------


def test_sips_resize_inplace_missing_file_safe(tmp_path: Path) -> None:
    """Missing path is a no-op (no exception)."""
    sips_resize_inplace(tmp_path / "missing.png")


def test_is_cli_safe_missing_file_returns_false(tmp_path: Path) -> None:
    """Defensive: unknown dimensions → unsafe."""
    assert is_cli_safe(tmp_path / "missing.png") is False


# ---------------------------------------------------------------------------
# ETL wire smoke — every target ETL imports the helper without error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_path",
    [
        "scripts.etl.ingest_jpo_patents",
        "scripts.cron.ingest_edinet_daily",
        "scripts.etl.ingest_court_decisions_extended",
        "scripts.etl.ingest_industry_guidelines",
        "scripts.etl.ingest_nta_tsutatsu_extended",
        "scripts.cron.poll_adoption_rss_daily",
        "scripts.cron.poll_egov_amendment_daily",
        "scripts.cron.poll_enforcement_daily",
        "scripts.cron.detect_budget_to_subsidy_chain",
        "scripts.cron.diff_invoice_registrants_daily",
        "scripts.cron.ingest_municipality_subsidy_weekly",
    ],
)
def test_etl_module_imports(module_path: str) -> None:
    """Each of the 11 wired ETL modules imports cleanly with the helper."""
    mod = importlib.import_module(module_path)
    assert mod is not None


def test_render_page_aggregator_refusal() -> None:
    """Legacy `render_page` entry point also refuses aggregator URLs."""
    result = render_page("https://noukaweb.example/x")
    assert result.text == ""
    assert result.error == "aggregator_refused"
