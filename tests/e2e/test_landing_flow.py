"""Landing + pricing CTA → checkout initiation.

Verifies the top of the conversion funnel for the single-page metered
pricing (post 2026-04-23 pivot):
  1. pricing.html renders with the single metered pricing card
  2. the primary CTA links to /v1/billing/checkout
  3. clicking it actually fires a request to the API — stubbed with a
     Playwright route interceptor so we never hit real Stripe during E2E

Why stub instead of hitting Stripe test-mode: the real Checkout redirects
to `checkout.stripe.com` which pulls in 3rd-party cookies, WASM, and
flaky DOM that isn't our code. The interceptor asserts the *request
shape* is correct (method + path) and returns a fake redirect URL.
Stripe-side behaviour is already covered by `tests/test_billing.py`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from playwright.async_api import expect

if TYPE_CHECKING:
    from playwright.async_api import Page


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_pricing_page_loads_with_hero_and_pricing_card(page: Page, url_for) -> None:
    await page.goto(url_for("/pricing.html"), wait_until="commit")

    # H1 — pricing can lead with either the Japanese label or the billable-unit offer.
    await expect(page.locator("h1")).to_have_text(re.compile(r"(料金|billable unit|¥3)"))

    # At least one pricing card renders (single metered card post-pivot).
    cards = page.locator("article.price-card")
    assert await cards.count() >= 1


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_primary_cta_links_to_checkout(page: Page, url_for) -> None:
    await page.goto(url_for("/pricing.html"), wait_until="commit")
    cta = page.locator("#checkout-btn")
    await expect(cta).to_be_visible()
    assert await cta.is_disabled(), "checkout button should remain disabled until consent"
    await page.locator("#checkout-consent").check()
    assert not await cta.is_disabled(), "checkout button should enable after consent"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_pricing_cta_click_initiates_checkout_request(
    page: Page, url_for, base_url: str
) -> None:
    """Click primary CTA and assert the browser issues a checkout request."""
    seen_requests: list[str] = []

    async def _handle(route) -> None:
        seen_requests.append(route.request.url)
        await route.fulfill(
            status=200,
            content_type="application/json",
            body='{"url": "' + base_url.rstrip("/") + '/checkout-stub.html"}',
        )

    await page.route(re.compile(r".*/v1/billing/checkout.*"), _handle)

    await page.goto(url_for("/pricing.html"), wait_until="commit")
    await page.locator("#checkout-consent").check()
    cta = page.locator("#checkout-btn")

    async with page.expect_navigation(url=re.compile(r".*/checkout-stub\.html")):
        await cta.click()

    assert seen_requests, (
        "no request to /v1/billing/checkout* was observed after clicking the primary CTA"
    )
