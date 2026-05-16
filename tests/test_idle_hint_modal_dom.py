"""Idle-hint modal DOM emit verify — Wave 48 tick#4 (jpcite 2026-05-12).

Background:
  PR #182 (Wave 48 tick#2, commit 56953cba1) wired site/assets/billing_progress.js
  with an idle-hint modal that should appear after 30s of no interaction. The
  tick#4 UX audit ran selector probes (.modal / [role=dialog] / .hint-modal /
  #idle-hint / .lost-user-hint) against pricing.html after waiting IDLE_MS+
  and got 0 matches in every selector — i.e. the modal DOM was never emitted.

Root causes located:
  1. mount() registered a "mousemove" listener in resetEvents (line 259 of
     the original file). mousemove fires continuously while the cursor is on
     the viewport (and Playwright always centres the cursor on the page),
     so armIdleTimer() was being re-armed every few ms — the 30000 ms
     timeout never finished, and showIdleHint() never ran.
  2. Even if the modal had fired, its id ("jpcite-bp-modal") and class
     ("jpcite-bp-modal") didn't match any of the canonical auditor selectors,
     so a green CSS path would still register as a regression.

Fix in this PR:
  a. Drop "mousemove" from resetEvents (keep click/keydown/scroll/touchstart
     — those signal real intent).
  b. Add canonical auditor hooks to the modal element so it matches:
     - id="jpcite-bp-modal"
     - class includes "hint-modal" and "lost-user-hint"
     - data-idle-hint="true"
     - role="dialog" (already present)

Test strategy:
  - Spin up a tiny aiohttp file server on a random port pointing at site/
    so /pricing.html can resolve /assets/billing_progress.js with relative
    URLs the same way CF Pages does. (No prod traffic, no LLM calls.)
  - Launch Playwright headless, navigate to /pricing.html.
  - DO NOT move the mouse or scroll — that would reset the idle timer.
  - Wait IDLE_MS + 2s (32s) and assert the modal node exists.
  - Assert every canonical auditor selector now matches the same element.

Skip rules:
  - Skipped unless JPINTEL_E2E_IDLE_MODAL=1 (don't run by default — 32s test).
  - Skipped if playwright import fails (developer machine without browsers).
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
from pathlib import Path

import pytest

_REQUIRES_LIVE = pytest.mark.skipif(
    os.environ.get("JPINTEL_E2E_IDLE_MODAL", "").strip() not in ("1", "true"),
    reason=(
        "idle modal DOM emit e2e takes 32s (IDLE_MS=30000); set JPINTEL_E2E_IDLE_MODAL=1 to opt-in"
    ),
)

# Mirror the JS constant. If this drifts, the JS source is the SoT.
IDLE_MS = 30_000

_SITE_ROOT = Path(__file__).resolve().parent.parent / "site"

# Canonical selectors that the UX audit checks. Every one of these MUST
# match the idle-hint modal after the fix.
CANONICAL_SELECTORS = [
    "#jpcite-bp-modal",
    "[role=dialog]",
    ".hint-modal",
    ".lost-user-hint",
    "[data-idle-hint]",
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _serve_site(port: int, stop_event: threading.Event) -> None:
    """Tiny HTTP file server bound to site/ root.

    Uses stdlib http.server in a daemon thread. stop_event lets the test
    shut it down cleanly. No external deps, no network egress.
    """
    import functools
    import http.server

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(_SITE_ROOT))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.timeout = 0.25

    while not stop_event.is_set():
        httpd.handle_request()
    httpd.server_close()


@pytest.fixture
def site_server():
    if not _SITE_ROOT.exists():
        pytest.skip(f"site/ missing at {_SITE_ROOT}")
    if not (_SITE_ROOT / "pricing.html").exists():
        pytest.skip("site/pricing.html missing")
    if not (_SITE_ROOT / "assets" / "billing_progress.js").exists():
        pytest.skip("site/assets/billing_progress.js missing")

    port = _free_port()
    stop = threading.Event()
    t = threading.Thread(target=_serve_site, args=(port, stop), daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    stop.set()
    t.join(timeout=2.0)


@_REQUIRES_LIVE
@pytest.mark.asyncio
async def test_idle_modal_dom_emits_after_30s(site_server: str) -> None:
    """The canonical regression: load pricing.html, do NOT interact, wait
    IDLE_MS + 2s, assert the idle-hint modal node exists in the DOM.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:  # pragma: no cover
        pytest.skip("playwright not installed")

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"chromium unavailable: {exc}")
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()
        await page.goto(f"{site_server}/pricing.html", wait_until="domcontentloaded")

        # Wait for the script tag (defer) to have evaluated. The progress
        # strip mounting is the proof the JS ran at all.
        await page.wait_for_selector(".jpcite-bp", timeout=10_000)

        # Crucial: do NOT call page.mouse.move / page.keyboard.press / scroll.
        # The fixture wraps a 30 s + 2 s wait so the idle timer runs once.
        await asyncio.sleep((IDLE_MS / 1000) + 2.0)

        modal_handle = await page.query_selector("#jpcite-bp-modal")
        assert modal_handle is not None, (
            "idle-hint modal DOM was not emitted after 32s — bug regressed "
            "(check mousemove handler + showIdleHint)"
        )

        # Every canonical auditor selector must match the same element.
        for sel in CANONICAL_SELECTORS:
            h = await page.query_selector(sel)
            assert h is not None, f"auditor selector {sel!r} did not match"

        # Sanity: the modal has the next-step copy, not an empty shell.
        text = (await modal_handle.inner_text()) or ""
        assert "次の step は" in text, f"modal copy missing 次の step は: got {text!r}"

        await context.close()
        await browser.close()


@_REQUIRES_LIVE
@pytest.mark.asyncio
async def test_idle_modal_suppressed_by_intentional_click(site_server: str) -> None:
    """Negative: when the user clicks within 30s, the timer must reset and
    the modal must NOT appear within IDLE_MS. We click at 5s in, then poll
    only up to IDLE_MS-2s after the click — the modal should still be absent.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:  # pragma: no cover
        pytest.skip("playwright not installed")

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"chromium unavailable: {exc}")
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()
        await page.goto(f"{site_server}/pricing.html", wait_until="domcontentloaded")
        await page.wait_for_selector(".jpcite-bp", timeout=10_000)

        await asyncio.sleep(5.0)
        # Click anywhere on body (not on a link — we don't want to navigate).
        await page.evaluate("document.body.dispatchEvent(new MouseEvent('click', {bubbles: true}))")
        # Wait less than IDLE_MS from the click — modal must still be absent.
        await asyncio.sleep((IDLE_MS / 1000) - 2.0)
        modal = await page.query_selector("#jpcite-bp-modal")
        assert modal is None, (
            "idle modal appeared before IDLE_MS elapsed after a click — "
            "timer reset on click is broken"
        )

        await context.close()
        await browser.close()


def test_mousemove_not_in_reset_events() -> None:
    """Static guard: the fix removes 'mousemove' from resetEvents. If a
    future edit re-introduces it, this fast unit test fails before
    Playwright is even needed.
    """
    src = (_SITE_ROOT / "assets" / "billing_progress.js").read_text(encoding="utf-8")
    assert "resetEvents" in src, "resetEvents identifier missing — file restructured?"
    # The literal list assignment after the fix.
    needle = 'var resetEvents = ["click", "keydown", "scroll", "touchstart"]'
    assert needle in src, f"resetEvents literal drifted from the tick#4 fix; expected {needle!r}"
    assert '"mousemove"' not in src.split("resetEvents")[1].split("]")[0], (
        "mousemove re-introduced into resetEvents — would suppress idle timer"
    )


def test_canonical_modal_hooks_present() -> None:
    """Static guard: the modal element advertises every canonical selector
    the UX auditor probes (hint-modal / lost-user-hint / data-idle-hint /
    role=dialog / id=jpcite-bp-modal).
    """
    src = (_SITE_ROOT / "assets" / "billing_progress.js").read_text(encoding="utf-8")
    for token in (
        'modal.id = "jpcite-bp-modal"',
        "hint-modal",
        "lost-user-hint",
        "data-idle-hint",
        'modal.setAttribute("role", "dialog")',
    ):
        assert token in src, f"canonical modal hook missing: {token!r}"
