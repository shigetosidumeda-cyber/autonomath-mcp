"""Post-checkout key-reveal page (`site/success.html`).

The real flow is: Stripe Checkout redirects to
`/success.html?session_id=cs_test_...` → the page POSTs to
`/v1/billing/keys/from-checkout` → the API verifies the session and
issues a key → the page renders the key + curl snippet.

We avoid Stripe entirely by intercepting the API call with a Playwright
route that returns a canned `{api_key, tier, customer_id}` body. This
tests the UI *rendering + copy-button* contract without requiring a
real paid Checkout session.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from playwright.async_api import expect

if TYPE_CHECKING:
    from playwright.async_api import Page

_FAKE_KEY = "jc_test_" + "a" * 40
_FAKE_RESPONSE = '{"api_key": "' + _FAKE_KEY + '", "tier": "paid", "customer_id": "cus_test_e2e"}'


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_success_page_renders_key_block_and_curl_when_api_succeeds(
    page: Page, url_for
) -> None:
    async def _handle(route) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=_FAKE_RESPONSE,
        )

    await page.route(re.compile(r".*/v1/billing/keys/from-checkout.*"), _handle)

    # session_id must match /^cs_[a-zA-Z0-9_]+$/ per success.html's regex.
    await page.goto(
        url_for("/success.html?session_id=cs_test_e2e_fake_12345"),
        wait_until="commit",
    )

    # Success state becomes visible after the (stubbed) POST resolves.
    success = page.locator("#state-success")
    await expect(success).to_be_visible()

    # Key block text contains the fake key.
    key_block = page.locator("#api-key-block")
    await expect(key_block).to_have_text(re.compile(re.escape(_FAKE_KEY)))

    # Tier + customer_id populated
    await expect(page.locator("#meta-tier")).to_have_text("paid")
    await expect(page.locator("#meta-customer")).to_have_text("cus_test_e2e")

    # Copy button visible (not strictly clickable in headless mode without
    # clipboard perms, but the button element must exist).
    copy_btn = page.locator("#copy-key-btn")
    await expect(copy_btn).to_be_visible()

    # Curl snippet contains the fake key (the page builds `curl -H "X-API-Key:..."`)
    curl_block = page.locator("#curl-block")
    curl_text = await curl_block.text_content()
    assert curl_text is not None
    assert _FAKE_KEY in curl_text, f"curl snippet should embed the issued key; got {curl_text!r}"
    assert "X-API-Key" in curl_text, f"curl snippet missing X-API-Key header; got {curl_text!r}"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_success_page_shows_missing_session_state_without_query(page: Page, url_for) -> None:
    # No session_id query → success.html should render the "missing" state
    # immediately (the inline script runs getSessionId() and falls through).
    await page.goto(url_for("/success.html"), wait_until="commit")

    missing = page.locator("#state-error-missing")
    await expect(missing).to_be_visible()

    # Pricing CTA to return
    pricing_link = missing.locator("a[href='pricing.html']")
    await expect(pricing_link).to_be_visible()


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_success_page_shows_unpaid_state_on_402(page: Page, url_for) -> None:
    async def _handle(route) -> None:
        await route.fulfill(
            status=402,
            content_type="application/json",
            body='{"detail": "checkout session not paid"}',
        )

    await page.route(re.compile(r".*/v1/billing/keys/from-checkout.*"), _handle)
    await page.goto(
        url_for("/success.html?session_id=cs_test_unpaid_00001"),
        wait_until="commit",
    )

    unpaid = page.locator("#state-error-unpaid")
    await expect(unpaid).to_be_visible()

    # Retry button wired
    retry_btn = page.locator("#retry-btn")
    await expect(retry_btn).to_be_visible()


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_success_page_shows_conflict_state_on_409(page: Page, url_for) -> None:
    async def _handle(route) -> None:
        await route.fulfill(
            status=409,
            content_type="application/json",
            body='{"detail": "key already issued"}',
        )

    await page.route(re.compile(r".*/v1/billing/keys/from-checkout.*"), _handle)
    await page.goto(
        url_for("/success.html?session_id=cs_test_conflict_00001"),
        wait_until="commit",
    )

    conflict = page.locator("#state-error-conflict")
    await expect(conflict).to_be_visible()

    dash_link = conflict.locator("a[href='dashboard.html']")
    await expect(dash_link).to_be_visible()
