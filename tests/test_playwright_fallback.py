"""Tests for the Wave 36 Playwright fallback helper.

Covers
------
* Mock static-fetch failure → Playwright fallback path triggers.
* Aggregator URL refusal (CLAUDE.md "Data hygiene").
* Viewport hard-cap (≤ 1600 px).
* sips resize (best-effort, no-op when sips absent).
* `screenshot_path_for` emits stable timestamped path under
  `/tmp/etl_screenshots/`.
* All 11 ETL wires import the helper without errors.

The Playwright path itself is mocked — we never actually launch chromium
in the test suite. The mock asserts that `fetch_with_fallback()` routes
to the fallback after `RETRY_ATTEMPTS` static failures, but does not
require the chromium binary to be present.

LLM API import scan: this test deliberately imports nothing from
`anthropic` / `openai` / `claude_agent_sdk`; the
`tests/test_no_llm_in_production.py` guard catches accidental imports.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.etl._image_helper import (  # noqa: E402
    MAX_CLI_SAFE_PX,
    is_cli_safe,
    sips_resize_inplace,
)
from scripts.etl._playwright_helper import (  # noqa: E402
    AggregatorRefusedError,
    BANNED_SOURCE_HOSTS,
    FetchResult,
    JPCITE_USER_AGENT,
    MAX_SCREENSHOT_EDGE,
    PlaywrightFallbackError,
    RenderResult,
    RETRY_ATTEMPTS,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
    fetch_with_fallback,
    fetch_with_fallback_sync,
    is_banned_url,
    render_page,
    screenshot_path_for,
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
    with pytest.raises(AggregatorRefusedError):
        fetch_with_fallback_sync(
            "https://noukaweb.example.jp/x",
            static_fetcher=lambda u: "<html></html>",
        )


def test_fetch_with_fallback_async_refuses_aggregator() -> None:
    async def _run() -> None:
        with pytest.raises(AggregatorRefusedError):
            await fetch_with_fallback(
                "https://hojyokin-portal.jp/x",
                static_fetcher=None,
            )

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Viewport / screenshot ceiling
# ---------------------------------------------------------------------------


def test_viewport_within_cli_safe_bounds() -> None:
    """memory feedback_image_resize: ≤ 1600 px hard ceiling."""
    assert VIEWPORT_WIDTH <= 1600
    assert VIEWPORT_HEIGHT <= 1600
    assert MAX_SCREENSHOT_EDGE <= 1600
    assert MAX_CLI_SAFE_PX <= 1600


def test_banned_source_hosts_seeded() -> None:
    """CLAUDE.md Data hygiene: aggregator deny-list non-empty."""
    assert len(BANNED_SOURCE_HOSTS) >= 3
    assert "noukaweb" in BANNED_SOURCE_HOSTS
    assert "hojyokin-portal" in BANNED_SOURCE_HOSTS
    assert "biz.stayway" in BANNED_SOURCE_HOSTS


def test_user_agent_brand_jpcite() -> None:
    """No legacy brand strings in the user-agent."""
    ua = JPCITE_USER_AGENT.lower()
    assert "jpcite" in ua
    assert "zeimu-kaikei" not in ua


# ---------------------------------------------------------------------------
# Static-first → Playwright fallback path
# ---------------------------------------------------------------------------


def test_static_success_short_circuits() -> None:
    """When static succeeds on first try, Playwright is never invoked."""

    async def _run() -> FetchResult:
        return await fetch_with_fallback(
            "https://www.meti.go.jp/sample",
            static_fetcher=lambda u: "<html>OK</html>",
        )

    result = asyncio.run(_run())
    assert result.source == "static"
    assert result.status_code == 200
    assert result.body == "<html>OK</html>"


def test_static_retry_then_fallback_invoked() -> None:
    """RETRY_ATTEMPTS exhausted → Playwright path triggers."""
    attempts: list[int] = []

    def _broken(_url: str) -> str:
        attempts.append(1)
        raise RuntimeError("static fetch failed")

    async def _mock_render(url, **kw):  # noqa: ANN001, ARG001
        return RenderResult(
            text="<html>rendered</html>",
            screenshot_path=None,
            status=200,
            final_url=url,
            fetched_at="2026-05-12T00:00:00Z",
            extractor="innertext",
            error=None,
        )

    with patch(
        "scripts.etl._playwright_helper._render_async",
        side_effect=_mock_render,
    ):

        async def _run() -> FetchResult:
            return await fetch_with_fallback(
                "https://www.meti.go.jp/sample-broken",
                static_fetcher=_broken,
            )

        result = asyncio.run(_run())

    assert len(attempts) == RETRY_ATTEMPTS
    assert result.source == "playwright"
    assert "rendered" in result.body


def test_playwright_failure_raises_helper_error() -> None:
    """Both static + Playwright fail → PlaywrightFallbackError."""

    def _broken(_u: str) -> str:
        raise RuntimeError("static down")

    async def _mock_render(url, **kw):  # noqa: ANN001, ARG001
        raise RuntimeError("chromium crashed")

    with patch(
        "scripts.etl._playwright_helper._render_async",
        side_effect=_mock_render,
    ):

        async def _run() -> FetchResult:
            return await fetch_with_fallback(
                "https://www.meti.go.jp/double-down",
                static_fetcher=_broken,
            )

        with pytest.raises(PlaywrightFallbackError):
            asyncio.run(_run())


# ---------------------------------------------------------------------------
# screenshot_path_for
# ---------------------------------------------------------------------------


def test_screenshot_path_format() -> None:
    p = screenshot_path_for("jpo_patents")
    assert p.startswith("/tmp/etl_screenshots/jpo_patents_")
    assert p.endswith(".png")


def test_screenshot_path_for_custom_root() -> None:
    p = screenshot_path_for("invoice_diff_daily", root="/tmp/custom")
    assert p.startswith("/tmp/custom/invoice_diff_daily_")
    assert p.endswith(".png")


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
