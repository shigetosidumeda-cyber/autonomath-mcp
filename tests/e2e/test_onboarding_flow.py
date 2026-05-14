"""End-to-end onboarding-flow walk (Wave-18 / E4 launch verification).

Walks the 7 step customer journey on a live local stack and asserts every
step renders the expected primitives:

    Step 1  /index.html              → landing hero loads
    Step 2  scroll to #audiences     → 5 audience pitch cards visible
    Step 3  /audiences/dev.html      → AI-developer deep-dive renders
    Step 4  /pricing.html            → ¥3/req metered card present
    Step 5  GET /v1/programs/search  → API returns ≥1 result for 持続化補助金
    Step 6  /dashboard.html          → API-key sign-in form renders (anon)
    Step 7  /stats.html              → 3 transparency widgets render

The walk uses Playwright **async_api** to align with the rest of `tests/e2e/*`
(`conftest.py` provides `page` / `url_for` / `base_url` fixtures backed by a
session-scoped chromium browser). The /tmp screenshots produced by the
adjacent `analysis_wave18/_e2e_walk_2026-04-25.md` walk are written by a
separate one-shot script — this pytest module *asserts*, it does not paint.

What we deliberately do NOT assert (out of scope here):
  - Stripe checkout side-effects (covered by tests/e2e/test_landing_flow.py)
  - Real 30-day usage history (covered by tests/e2e/test_dashboard_flow.py)
  - MCP stdio behaviour (covered by tests/test_mcp_server*.py)

Why we hit a real API in step 5 instead of stubbing: the staging failure mode
we care about is "the static landing builds, but the API is down" — a stub
would mask that. The walk uses the IP-anon 50/month quota, so a green-CI
run consumes one slot. The prod API target requires both `--run-production`
upstream and `JPINTEL_E2E_ALLOW_PROD_API=true`.

Local two-port setup (Cloudflare Pages mock):
  - JPINTEL_E2E_BASE_URL=http://localhost:8084   ← static site (Pages)
  - JPINTEL_E2E_API_BASE=http://localhost:8083   ← FastAPI (Fly mock)
When `JPINTEL_E2E_API_BASE` is unset we fall back to `base_url` (the prod
shape — single host with API + Pages co-deployed).
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING
from urllib.parse import quote

import pytest
from playwright.async_api import expect

if TYPE_CHECKING:
    from playwright.async_api import Page


# --------------------------------------------------------------------------- #
# Step 1 — landing
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_step01_landing_hero_renders(page: Page, url_for) -> None:
    await page.goto(url_for("/index.html"), wait_until="commit")
    # Hero h1 — substring match keeps us robust to copy edits
    h1 = page.locator("h1").first
    await expect(h1).to_be_visible()
    text = (await h1.inner_text()).strip()
    assert "Evidence Packet" in text or "公的制度" in text or "AutonoMath" in text, (
        f"landing h1 missing expected anchor copy: {text!r}"
    )


# --------------------------------------------------------------------------- #
# Step 2 — audiences section / 5-pitch grid
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_step02_audiences_section_has_five_cards(page: Page, url_for) -> None:
    await page.goto(url_for("/index.html"), wait_until="commit")
    # Section landmark
    section = page.locator("section#audiences")
    await expect(section).to_be_visible()
    # 5 audience-card articles + 1 "あなたは?" fallback = 6 expected.
    cards = page.locator("section#audiences article.audience-card")
    count = await cards.count()
    assert count >= 5, f"expected ≥5 audience cards, got {count}"


# --------------------------------------------------------------------------- #
# Step 3 — audiences/dev.html deep-dive
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_step03_dev_audience_page_renders(page: Page, url_for) -> None:
    await page.goto(url_for("/audiences/dev.html"), wait_until="commit")
    h1 = page.locator("h1").first
    await expect(h1).to_be_visible()
    text = (await h1.inner_text()).strip()
    assert "AI agent" in text or "developer" in text, f"dev audience h1 unexpected: {text!r}"


# --------------------------------------------------------------------------- #
# Step 4 — pricing card
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_step04_pricing_metered_card_renders(page: Page, url_for) -> None:
    await page.goto(url_for("/pricing.html"), wait_until="commit")
    # H1 = 料金
    await expect(page.locator("h1").first).to_have_text(re.compile(r"(料金|billable unit|¥3)"))
    # ≥1 price-card with ¥3.30 / 従量 copy somewhere on the page
    body = await page.locator("body").inner_text()
    assert "従量" in body or "metered" in body.lower(), "pricing missing 従量"
    assert "¥3" in body or "3.30" in body, "pricing missing ¥3 / 3.30 copy"


# --------------------------------------------------------------------------- #
# Step 5 — /v1/programs/search anon (50/mo IP quota)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_step05_api_search_returns_results(page: Page, base_url: str) -> None:
    # We use Playwright's request fixture indirectly via APIRequestContext on
    # the browser context. This guarantees the call honours the same locale +
    # timezone as the browser walk, and fits the "real network round-trip"
    # contract of the e2e suite.
    api_base = os.environ.get("JPINTEL_E2E_API_BASE", "").rstrip("/") or base_url
    allow_prod_api = os.environ.get("JPINTEL_E2E_ALLOW_PROD_API", "").strip().lower()
    if "api.jpcite.com" in api_base and allow_prod_api not in ("1", "true", "yes"):
        pytest.skip("prod API smoke requires JPINTEL_E2E_ALLOW_PROD_API=true")
    api_url = f"{api_base}/v1/programs/search?q={quote('持続化補助金')}&limit=3"
    resp = await page.request.get(api_url)
    assert resp.ok, f"GET {api_url} → {resp.status}"
    data = await resp.json()
    assert isinstance(data.get("results"), list), f"missing results list: {data}"
    assert data.get("total", 0) >= 1, (
        f"expected ≥1 hit for 持続化補助金, got total={data.get('total')}"
    )


# --------------------------------------------------------------------------- #
# Step 6 — dashboard.html (anon)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_step06_dashboard_signin_form_renders_for_anon(page: Page, url_for) -> None:
    await page.goto(url_for("/dashboard.html"), wait_until="commit")
    # The unauth view shows a sign-in card with an api_key paste input.
    # We assert *some* input element with `jc_` placeholder is present —
    # the dashboard.js DOM may swap between v1 and v2 layouts.
    placeholder_input = page.locator("#dash2-key-input, input[placeholder*='jc_']")
    await expect(placeholder_input.first).to_be_visible(timeout=10_000)


# --------------------------------------------------------------------------- #
# Step 7 — stats.html transparency widgets
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_step07_stats_page_renders_three_widgets(page: Page, url_for) -> None:
    await page.goto(url_for("/stats.html"), wait_until="commit")
    body = await page.locator("body").inner_text()
    # 3 widget headings — the page might show "失敗" copy if the API base
    # isn't reachable from this origin (CORS / cross-host setup), but the
    # widget *frames* should still render.
    for keyword in ("Coverage", "Freshness", "Usage"):
        assert keyword in body, f"stats page missing widget heading: {keyword}"
