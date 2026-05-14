"""Tier 3 alert subscription UI flow (P5-ι++ / dd_v8_08 H/I — E5).

Covers the dashboard.html alerts section wired to /v1/me/alerts/* in
src/jpintel_mcp/api/alerts.py and rendered by site/dashboard_v2.js.

Flow:
  1. seed an authenticated API key
  2. inject it into localStorage.am_api_key (the Bearer key the v2 flow uses)
  3. open /dashboard.html and wait for the alerts section to become visible
  4. submit the new-subscribe form (filter_type=law_id, severity=critical,
     webhook_url=https://hooks.example.com, email=ops@example.com)
  5. assert one row appears in the active-subscriptions table
  6. attempt a second submit with an internal-IP webhook (https://10.0.0.5/),
     assert client-side validation rejects it before round-trip
  7. click 削除, accept the confirm() dialog, assert the row disappears

This test is skipped against staging/prod by `_require_local_db` (it
seeds and revokes a real DB row).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.async_api import expect

if TYPE_CHECKING:
    from playwright.async_api import Page


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_alerts_subscribe_list_delete_flow(
    page: Page, url_for, seeded_api_key: dict[str, str], base_url: str
) -> None:
    if seeded_api_key.get("external") == "1":
        pytest.skip("alert subscription mutation requires a locally seeded throwaway key")

    # Inject the seeded key into localStorage BEFORE the page's JS runs.
    # The dashboard_v2.js boot reads localStorage at DOMContentLoaded.
    api_key = seeded_api_key["raw_key"]
    await page.context.add_init_script(
        f"try {{ window.localStorage.setItem('am_api_key', {api_key!r}); }} catch(e) {{}}"
    )
    await page.goto(url_for("/dashboard.html"))

    # The alerts section starts hidden (display:none + hidden=""); v2's
    # showSections(true) clears both once loadAll() succeeds.
    alerts_section = page.locator("#dash2-alerts")
    await expect(alerts_section).to_be_visible(timeout=15_000)

    # ----- 1. empty state -------------------------------------------------
    empty_row = page.locator("#dash2-alerts-tbody tr td[colspan]")
    await expect(empty_row).to_contain_text("登録中の subscription はありません")

    # ----- 2. fill form + submit -----------------------------------------
    await page.locator("#dash2-alerts-filter-type").select_option("law_id")
    await page.locator("#dash2-alerts-filter-value").fill("law_345AC0000000050")
    await page.locator("#dash2-alerts-severity").select_option("critical")
    await page.locator("#dash2-alerts-webhook").fill("https://hooks.example.com/autonomath/e5-test")
    await page.locator("#dash2-alerts-email").fill("ops@example.com")
    await page.locator("#dash2-alerts-submit").click()

    # ----- 3. row should appear ------------------------------------------
    row = page.locator("#dash2-alerts-tbody tr[data-sub-id]").first
    await expect(row).to_be_visible(timeout=5000)
    sub_id = await row.get_attribute("data-sub-id")
    assert sub_id is not None and sub_id.isdigit()

    # The success banner should be visible too.
    banner = page.locator("#dash2-alerts-banner")
    await expect(banner).to_contain_text(f"subscription #{sub_id} を登録しました")

    # ----- 4. internal-IP rejection (client-side guard) ------------------
    # We can't easily fail HTML5 pattern with a non-https url here because
    # the input has pattern="https://.*" — instead use https://10.0.0.5/
    # which passes HTML pattern but our JS validator should block.
    await page.locator("#dash2-alerts-filter-value").fill("law_dummy")
    await page.locator("#dash2-alerts-webhook").fill("https://10.0.0.5/hook")
    await page.locator("#dash2-alerts-submit").click()
    await expect(banner).to_contain_text("internal/loopback IP", timeout=3000)
    # The row count must NOT have increased.
    assert await page.locator("#dash2-alerts-tbody tr[data-sub-id]").count() == 1

    # ----- 5. delete (auto-accept confirm()) -----------------------------
    page.once("dialog", lambda d: d.accept())
    await page.locator(".dash2-alerts-delete").first.click()

    # After delete, table should be empty again.
    await expect(empty_row).to_be_visible(timeout=5000)
    await expect(banner).to_contain_text(f"subscription #{sub_id} を削除しました")
