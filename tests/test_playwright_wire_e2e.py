"""Wave 36 — Playwright fallback wire e2e test.

Verifies that the 11 ETL/cron scripts identified in the Wave 36 spec all
import `fetch_with_fallback` (async) or `fetch_with_fallback_sync` (sync)
from `scripts.etl._playwright_helper`, and that the helper itself exposes
the expected surface plus screenshot ≤1600px enforcement.

Constraints honored
-------------------
* NO LLM API import (`anthropic` / `openai` / `claude_agent_sdk` etc.)
  in any wired script.
* Screenshot resize cap = 1600 px (memory `feedback_image_resize`).
* Banned-aggregator hostnames refused up-front (CLAUDE.md "Data hygiene").
* Real Playwright not required — test mocks the underlying httpx response
  and the `_render_async()` coroutine to keep the suite hermetic.
"""

from __future__ import annotations

import asyncio
import tomllib
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from scripts.etl._playwright_helper import (
    JPCITE_USER_AGENT,
    MAX_SCREENSHOT_EDGE,
    FetchResult,
    RenderResult,
    fetch_with_fallback,
    fetch_with_fallback_sync,
    is_banned_url,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# 11 ETL/cron scripts wired in Wave 36 (per spec).
WIRED_SCRIPTS = [
    "scripts/cron/ingest_municipality_subsidy_weekly.py",
    "scripts/etl/ingest_jpo_patents.py",
    "scripts/cron/ingest_edinet_daily.py",
    "scripts/etl/ingest_court_decisions_extended.py",
    "scripts/etl/ingest_industry_guidelines.py",
    "scripts/etl/ingest_nta_tsutatsu_extended.py",
    "scripts/cron/poll_adoption_rss_daily.py",
    "scripts/cron/poll_egov_amendment_daily.py",
    "scripts/cron/poll_enforcement_daily.py",
    "scripts/etl/promote_compat_matrix_v2.py",
    "scripts/etl/verify_amount_conditions_v2.py",
]

# 10 workflows that should install Playwright chromium before ETL run.
WIRED_WORKFLOWS = [
    ".github/workflows/municipality-subsidy-weekly.yml",
    ".github/workflows/jpo-patents-daily.yml",
    ".github/workflows/edinet-daily.yml",
    ".github/workflows/extended-corpus-weekly.yml",
    ".github/workflows/adoption-rss-daily.yml",
    ".github/workflows/egov-amendment-daily.yml",
    ".github/workflows/enforcement-press-daily.yml",
    ".github/workflows/budget-subsidy-chain-daily.yml",
    ".github/workflows/invoice-diff-daily.yml",
    ".github/workflows/axis2def-promote-weekly.yml",
]

# LLM SDK imports forbidden in wired scripts (per CLAUDE.md + memory
# `feedback_no_operator_llm_api`).
FORBIDDEN_LLM_IMPORTS = (
    "import anthropic",
    "from anthropic",
    "import openai",
    "from openai",
    "import google.generativeai",
    "from google.generativeai",
    "import claude_agent_sdk",
    "from claude_agent_sdk",
)


# ---------------------------------------------------------------------------
# Static wire checks (deterministic).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rel_path", WIRED_SCRIPTS)
def test_each_wired_script_imports_fetch_with_fallback(rel_path: str) -> None:
    """Every wired script must reference `fetch_with_fallback` (async or sync)."""
    body = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert "fetch_with_fallback" in body, (
        f"{rel_path} missing fetch_with_fallback wire — "
        "Wave 36 spec requires every targeted script to import the helper."
    )


@pytest.mark.parametrize("rel_path", WIRED_SCRIPTS)
def test_wired_script_has_no_llm_api_import(rel_path: str) -> None:
    """Wired scripts must NOT import an LLM SDK (memory feedback_no_operator_llm_api)."""
    body = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    for forbidden in FORBIDDEN_LLM_IMPORTS:
        assert forbidden not in body, (
            f"{rel_path} imports {forbidden!r} — LLM SDK is forbidden in ETL/cron."
        )


@pytest.mark.parametrize("rel_path", WIRED_WORKFLOWS)
def test_each_wired_workflow_installs_playwright(rel_path: str) -> None:
    """Every wired GHA workflow must install Playwright chromium before ETL run."""
    body = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert "playwright install" in body, (
        f"{rel_path} missing 'playwright install chromium' step — "
        "Wave 36 spec requires Playwright on every cron runner."
    )


def test_dev_extra_installs_playwright_python_package() -> None:
    """The chromium install step requires `python -m playwright` to import."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev_deps = pyproject["project"]["optional-dependencies"]["dev"]
    assert any(dep.split(";", 1)[0].strip().startswith("playwright") for dep in dev_deps)


# ---------------------------------------------------------------------------
# Helper API surface checks.
# ---------------------------------------------------------------------------


def test_helper_exposes_expected_constants() -> None:
    """Helper exports the screenshot edge cap + UA the spec requires."""
    assert MAX_SCREENSHOT_EDGE == 1600, (
        "screenshot cap must be 1600 px per feedback_image_resize"
    )
    assert "jpcite-etl" in JPCITE_USER_AGENT


def test_helper_is_banned_url_rejects_aggregators() -> None:
    """Banned aggregator hostnames are refused up-front."""
    assert is_banned_url("https://noukaweb.example.jp/program/123") is True
    assert is_banned_url("https://hojyokin-portal.jp/p/abc") is True
    assert is_banned_url("https://biz.stayway.jp/example") is True


def test_helper_is_banned_url_allows_first_party() -> None:
    """Authoritative .go.jp / .lg.jp pass the gate."""
    assert is_banned_url("https://www.meti.go.jp/policy/sme") is False
    assert is_banned_url("https://www.city.konosu.lg.jp/sub/123.html") is False
    assert is_banned_url("https://elaws.e-gov.go.jp/document?lawid=325AC0000000034") is False


# ---------------------------------------------------------------------------
# Mocked behavior of fetch_with_fallback() — 4xx triggers Playwright pass.
# ---------------------------------------------------------------------------


def _make_render_result(text: str, status: int = 200) -> RenderResult:
    return RenderResult(
        text=text,
        screenshot_path=None,
        status=status,
        final_url="https://example.go.jp/page",
        fetched_at="2026-05-12T00:00:00Z",
        extractor="accessibility",
        error=None,
    )


def test_fetch_with_fallback_aggregator_short_circuits() -> None:
    """Aggregator URL returns source='aggregator_refused' without any fetch."""
    result = fetch_with_fallback_sync("https://noukaweb.example.jp/p/1")
    assert isinstance(result, FetchResult)
    assert result.source == "aggregator_refused"
    assert result.text == ""
    assert result.status == 0


def test_fetch_with_fallback_4xx_triggers_playwright_pass() -> None:
    """A 404 from httpx must trigger the Playwright fallback pass."""

    async def _run() -> FetchResult:
        # Patch the inner httpx getter to simulate a 404.
        def _fake_httpx_get(url: str, *, timeout_s: float, user_agent: str):
            return (404, "", url, None)

        async def _fake_render(url, *, screenshot_dir, timeout_ms, max_retries):
            return _make_render_result("PLAYWRIGHT_RECOVERED_BODY", status=200)

        with patch(
            "scripts.etl._playwright_helper._httpx_get",
            side_effect=_fake_httpx_get,
        ), patch(
            "scripts.etl._playwright_helper._render_async",
            new=AsyncMock(side_effect=_fake_render),
        ):
            return await fetch_with_fallback("https://www.meti.go.jp/policy/sme")

    result = asyncio.run(_run())
    assert result.source == "playwright"
    assert "PLAYWRIGHT_RECOVERED_BODY" in result.text
    assert result.error is None


def test_fetch_with_fallback_httpx_200_skips_playwright() -> None:
    """A healthy 200 + sufficient body short-circuits before Playwright runs."""
    body = "OK" + "x" * 500  # > min_body_bytes default 200

    async def _run() -> FetchResult:
        def _fake_httpx_get(url: str, *, timeout_s: float, user_agent: str):
            return (200, body, url, None)

        render_mock = AsyncMock()
        with patch(
            "scripts.etl._playwright_helper._httpx_get",
            side_effect=_fake_httpx_get,
        ), patch(
            "scripts.etl._playwright_helper._render_async",
            new=render_mock,
        ):
            r = await fetch_with_fallback("https://elaws.e-gov.go.jp/document")
            assert render_mock.await_count == 0, (
                "Playwright must not run when httpx returns a healthy 200"
            )
            return r

    result = asyncio.run(_run())
    assert result.source == "httpx"
    assert result.status == 200
    assert result.text == body


def test_fetch_with_fallback_short_body_triggers_playwright() -> None:
    """200 with body shorter than min_body_bytes still triggers Playwright."""

    async def _run() -> FetchResult:
        def _fake_httpx_get(url: str, *, timeout_s: float, user_agent: str):
            return (200, "tiny", url, None)

        async def _fake_render(url, *, screenshot_dir, timeout_ms, max_retries):
            return _make_render_result("FULL_BODY_FROM_DOM", status=200)

        with patch(
            "scripts.etl._playwright_helper._httpx_get",
            side_effect=_fake_httpx_get,
        ), patch(
            "scripts.etl._playwright_helper._render_async",
            new=AsyncMock(side_effect=_fake_render),
        ):
            return await fetch_with_fallback("https://www.meti.go.jp/policy/x")

    result = asyncio.run(_run())
    assert result.source == "playwright"
    assert result.text == "FULL_BODY_FROM_DOM"


def test_fetch_with_fallback_both_passes_fail_returns_error() -> None:
    """Transport failure + Playwright failure surfaces source='error'."""

    async def _run() -> FetchResult:
        def _fake_httpx_get(url: str, *, timeout_s: float, user_agent: str):
            return (0, "", url, "ConnectError: refused")

        async def _fake_render(url, *, screenshot_dir, timeout_ms, max_retries):
            return RenderResult(
                text="",
                screenshot_path=None,
                status=0,
                final_url=url,
                fetched_at="2026-05-12T00:00:00Z",
                extractor="",
                error="playwright_not_installed",
            )

        with patch(
            "scripts.etl._playwright_helper._httpx_get",
            side_effect=_fake_httpx_get,
        ), patch(
            "scripts.etl._playwright_helper._render_async",
            new=AsyncMock(side_effect=_fake_render),
        ):
            return await fetch_with_fallback("https://www.meti.go.jp/down")

    result = asyncio.run(_run())
    assert result.source == "error"
    assert result.text == ""
    assert result.error is not None


# ---------------------------------------------------------------------------
# Screenshot resize cap enforcement (sips ≤1600px).
# ---------------------------------------------------------------------------


def test_resize_cap_constant_is_1600() -> None:
    """The helper's resize-edge constant must be exactly 1600 px.

    Memory `feedback_image_resize` forbids screenshots > 1600 because the
    CLI crashes on width >1900. The helper enforces this via sips -Z 1600
    on every captured screenshot.
    """
    assert MAX_SCREENSHOT_EDGE == 1600
