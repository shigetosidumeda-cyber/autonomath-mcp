"""Dashboard flow: paste-key sign-in → usage → rotate-key → logout.

Covers:
  - `/v1/session` POST bootstraps an HMAC-signed cookie
  - `/v1/me` returns tier + key_hash_prefix
  - `/v1/me/usage` feeds the 30-day chart (non-empty when we seed events)
  - `POST /v1/me/rotate-key` returns a new key, and the previous key
    fails a session-creation attempt with 401
  - `POST /v1/me/billing-portal` button redirects (stubbed — we don't
    hit real Stripe)
  - `POST /v1/session/logout` clears the cookie

Fixtures `seeded_api_key` + `seeded_usage_events` are local-only; they
skip when pointing at staging/prod.
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
async def test_dashboard_signin_with_seeded_key_shows_tier_and_prefix(
    page: Page, url_for, seeded_api_key: dict[str, str]
) -> None:
    await page.goto(url_for("/dashboard.html"))

    # The signed-out card is injected by dashboard.js after load; wait for it.
    signin_form = page.locator("#dash-signin-form")
    await expect(signin_form).to_be_visible()

    await page.locator("#dash-signin-key").fill(seeded_api_key["raw_key"])
    await page.locator("#dash-signin-submit").click()

    # After successful sign-in the tier badge + "signed in as" line update.
    badge = page.locator(".tier-badge")
    # Tier label is capitalised by dashboard.js (plus -> "Plus")
    await expect(badge).to_have_text(re.compile(r"^Plus$", re.IGNORECASE))

    # "signed in as <prefix…>" line — the prefix is 8 hex chars
    sub = page.locator(".dash .sub code")
    await expect(sub).to_be_visible()
    prefix_text = await sub.text_content()
    assert prefix_text and len(prefix_text.strip()) >= 6


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_dashboard_usage_chart_renders_bars_with_seeded_events(
    page: Page, url_for, seeded_api_key: dict[str, str], seeded_usage_events
) -> None:
    await page.goto(url_for("/dashboard.html"))
    await page.locator("#dash-signin-key").fill(seeded_api_key["raw_key"])
    await page.locator("#dash-signin-submit").click()

    # Wait for the chart to render — dashboard.js replaces the SVG <rect>s
    # after `/v1/me/usage` returns. Peak annotation gets populated too.
    chart_title = page.locator(".chart-title .muted")
    # Predicate wait: text becomes "peak N calls on MM-DD" or "no calls yet"
    await expect(chart_title).to_have_text(
        re.compile(r"(peak \d+ calls on \d{2}-\d{2}|no calls yet)")
    )

    # We seeded non-zero events, so the peak branch should fire.
    title_text = await chart_title.text_content()
    assert title_text is not None
    assert "peak" in title_text, (
        f"expected peak-annotation after seeding events; got {title_text!r}"
    )

    # SVG rects exist
    rects = page.locator(".chart-svg rect")
    count = await rects.count()
    # We seed 30 days, so at least a dozen bars should render.
    assert count >= 10, f"expected >=10 chart bars; got {count}"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_rotate_key_invalidates_old_key(
    page: Page, url_for, seeded_api_key: dict[str, str]
) -> None:
    # Pre-confirm the window.confirm dialog that onRotate() throws up.
    page.on("dialog", lambda d: d.accept())

    await page.goto(url_for("/dashboard.html"))
    await page.locator("#dash-signin-key").fill(seeded_api_key["raw_key"])
    await page.locator("#dash-signin-submit").click()

    # Wait for post-login UI (keybox visible).
    await expect(page.locator(".keybox")).to_be_visible()

    # Capture the rotate-key API response to fish out the new key. The
    # frontend does NOT persist the raw key anywhere in the DOM except as
    # textContent of .keybox .key after revealNewKey() runs — read it
    # from the network instead to avoid DOM-read timing.
    async with page.expect_response(
        lambda r: "/v1/me/rotate-key" in r.url and r.status == 200
    ) as resp_info:
        await page.locator("#dash-rotate-btn").click()
    resp = await resp_info.value
    body = await resp.json()
    new_key = body["api_key"]
    assert new_key and new_key != seeded_api_key["raw_key"]

    # The old key must now fail sign-in. We test this by logging out and
    # retrying the paste-key flow.
    # Logout link is injected with id=dash-logout-link by dashboard.js.
    await page.locator("#dash-logout-link").click()

    # After logout, dashboard.js re-reveals the sign-in card.
    await expect(page.locator("#dash-signin-form")).to_be_visible()

    # Try the OLD key — should 401.
    async with page.expect_response(
        lambda r: "/v1/session" in r.url and r.request.method == "POST"
    ) as old_resp_info:
        await page.locator("#dash-signin-key").fill(seeded_api_key["raw_key"])
        await page.locator("#dash-signin-submit").click()
    old_resp = await old_resp_info.value
    assert old_resp.status == 401, (
        f"expected 401 when signing in with the rotated-out key; got "
        f"{old_resp.status}"
    )


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_billing_portal_button_redirects(
    page: Page, url_for, seeded_api_key: dict[str, str]
) -> None:
    """Stub the billing-portal endpoint — it calls Stripe which we avoid."""
    async def _handle(route) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body='{"url": "https://example.com/stubbed-billing-portal"}',
        )

    await page.route(
        re.compile(r".*/v1/me/billing-portal.*"), _handle
    )

    await page.goto(url_for("/dashboard.html"))
    await page.locator("#dash-signin-key").fill(seeded_api_key["raw_key"])
    await page.locator("#dash-signin-submit").click()
    await expect(page.locator(".keybox")).to_be_visible()

    # The billing button is id=dash-billing-btn. For tier=plus it's enabled.
    # Clicking issues a POST /v1/me/billing-portal and dashboard.js then
    # `window.location = body.url`.
    #
    # We only assert the request fires and a navigation attempt follows.
    seen: list[str] = []

    async def _rec(req) -> None:
        if "/v1/me/billing-portal" in req.url:
            seen.append(req.url)

    page.on("request", _rec)

    # The redirect target is off-origin; prevent the browser from actually
    # leaving our origin by hooking window.location.
    await page.evaluate(
        "() => { window.__lastLocation = null; "
        "Object.defineProperty(window, 'location', "
        "{ writable: true, value: { assign(u){ window.__lastLocation = u; }, "
        "replace(u){ window.__lastLocation = u; }, "
        "set href(u){ window.__lastLocation = u; }, get href(){ return ''; } } }); }"
    )

    await page.locator("#dash-billing-btn").click()

    # At least the POST must have been observed.
    # Give the click a brief window to fire (bounded by the default timeout).
    await page.wait_for_function("() => window.__lastLocation !== null", timeout=5000)
    assert seen, "no POST to /v1/me/billing-portal was observed"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_logout_clears_session_cookie(
    page: Page, url_for, seeded_api_key: dict[str, str]
) -> None:
    await page.goto(url_for("/dashboard.html"))
    await page.locator("#dash-signin-key").fill(seeded_api_key["raw_key"])
    await page.locator("#dash-signin-submit").click()
    await expect(page.locator(".keybox")).to_be_visible()

    # Cookie present
    cookies_before = await page.context.cookies()
    assert any(c["name"] == "jpintel_session" for c in cookies_before), (
        "jpintel_session cookie should be set after sign-in"
    )

    await page.locator("#dash-logout-link").click()

    # Sign-in card returns
    await expect(page.locator("#dash-signin-form")).to_be_visible()

    # Cookie cleared
    cookies_after = await page.context.cookies()
    jp_cookie = [c for c in cookies_after if c["name"] == "jpintel_session"]
    # Cookie is either gone or value emptied — accept both outcomes (FastAPI
    # set-cookie with delete() sends an expiry in the past).
    assert not jp_cookie or not jp_cookie[0].get("value"), (
        f"jpintel_session cookie should be cleared; got {jp_cookie!r}"
    )
