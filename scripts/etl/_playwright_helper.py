"""Playwright-backed fetch fallback for jpcite ETL.

Purpose
-------
The 3 v2 promote ETLs (`promote_compat_matrix_v2`, `verify_amount_conditions_v2`,
`datafill_amendment_snapshot_v2`) rely on first-pass urllib3 / httpx
fetches against authoritative public sources (.go.jp / .lg.jp / etc.).
When those fetches fail with 4xx / 5xx or render the substantive
content client-side, this helper performs a second-pass Playwright
render and returns the DOM text.

Constraints
-----------
* **No LLM API.** Text extracted via Playwright's accessibility tree
  (`page.accessibility.snapshot()`) and DOM `innerText` — structural only.
* **Screenshot ≤1600px hard limit.** Viewport 1280×1600 + sips resize.
* **Browser walk + screenshot + Vision LLM** is the canonical
  information-collection pattern (memory `feedback_collection_browser_first`).
* **Retry 3 + exponential backoff.** 1.5s × 2^(n-1).
* **9.7GB DB foot-gun avoidance.** This module never touches the DB.

Aggregator URL refusal
----------------------
Per CLAUDE.md "Data hygiene" + memory `feedback_no_fake_data`, banned
aggregator hostnames (noukaweb, hojyokin-portal, biz.stayway, etc.)
are refused up-front and return an empty payload.

Public surface
--------------
    render_page(url, screenshot_dir=None, timeout_ms=15_000) -> RenderResult
        Sync entry point. Never raises.

    is_aggregator(url)  -> bool
    is_banned_url(url)  -> bool   (alias of is_aggregator)
    screenshot_filename(url) -> str
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_AGGREGATOR_HOSTS = (
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "hojyokin-info",
    "hojokin-portal",
    "subsidy-port.jp",
    "hojo-navi",
    "mirai-joho",
)

VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 1600
MAX_SCREENSHOT_EDGE = 1600
MAX_RETRIES = 3
RETRY_BACKOFF_BASE_S = 1.5

JPCITE_USER_AGENT = (
    "jpcite-etl/0.3 (+https://jpcite.com/about/etl) "
    "Playwright/HeadlessChromium operator-side fetch"
)


@dataclass(frozen=True)
class RenderResult:
    """Bundled return for `render_page()`."""

    text: str
    screenshot_path: Path | None
    status: int
    final_url: str
    fetched_at: str
    extractor: str
    error: str | None = None


def is_aggregator(url: str | None) -> bool:
    if not url:
        return True
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return True
    if not host:
        return True
    return any(bad in host for bad in _AGGREGATOR_HOSTS)


# Alias for Wave 36 horizontal-wire callers.
is_banned_url = is_aggregator


def screenshot_filename(url: str) -> str:
    sha = hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return f"{sha}.png"


def _resize_with_sips(png_path: Path, max_edge: int = MAX_SCREENSHOT_EDGE) -> None:
    sips = "/usr/bin/sips"
    if not Path(sips).exists():
        return
    try:
        subprocess.run(
            [sips, "-Z", str(max_edge), str(png_path)],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.debug("sips resize skipped for %s: %s", png_path, exc)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _err_result(url: str, error: str) -> RenderResult:
    return RenderResult(
        text="",
        screenshot_path=None,
        status=0,
        final_url=url,
        fetched_at=_now_iso(),
        extractor="",
        error=error,
    )


def render_page(
    url: str,
    *,
    screenshot_dir: Path | None = None,
    timeout_ms: int = 15_000,
    max_retries: int = MAX_RETRIES,
) -> RenderResult:
    """Sync entrypoint — never raises."""
    if is_aggregator(url):
        return _err_result(url, "aggregator_refused")

    try:
        return asyncio.run(
            _render_async(
                url,
                screenshot_dir=screenshot_dir,
                timeout_ms=timeout_ms,
                max_retries=max_retries,
            )
        )
    except RuntimeError as exc:
        if "asyncio.run() cannot be called" in str(exc):
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    _render_async(
                        url,
                        screenshot_dir=screenshot_dir,
                        timeout_ms=timeout_ms,
                        max_retries=max_retries,
                    )
                )
            finally:
                loop.close()
        return _err_result(url, f"asyncio: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("render_page hard fail %s: %s", url, exc)
        return _err_result(url, str(exc))


async def _render_async(
    url: str,
    *,
    screenshot_dir: Path | None,
    timeout_ms: int,
    max_retries: int,
) -> RenderResult:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        logger.warning("playwright not installed: %s", exc)
        return _err_result(url, "playwright_not_installed")

    last_error: str | None = None
    for attempt in range(1, max_retries + 1):
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-gpu",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
                try:
                    context = await browser.new_context(
                        user_agent=JPCITE_USER_AGENT,
                        viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                        ignore_https_errors=False,
                        locale="ja-JP",
                    )
                    page = await context.new_page()
                    response = await page.goto(
                        url, timeout=timeout_ms, wait_until="domcontentloaded"
                    )
                    status = response.status if response else 0
                    final_url = page.url or url

                    with contextlib.suppress(Exception):
                        await page.wait_for_load_state(
                            "networkidle", timeout=min(timeout_ms, 8000)
                        )

                    text = await _extract_text(page)
                    extractor = _classify_extractor(text)

                    screenshot_path: Path | None = None
                    if screenshot_dir is not None:
                        screenshot_dir.mkdir(parents=True, exist_ok=True)
                        screenshot_path = screenshot_dir / screenshot_filename(url)
                        await page.screenshot(
                            path=str(screenshot_path),
                            full_page=False,
                            type="png",
                        )
                        _resize_with_sips(screenshot_path)

                    return RenderResult(
                        text=text,
                        screenshot_path=screenshot_path,
                        status=status,
                        final_url=final_url,
                        fetched_at=_now_iso(),
                        extractor=extractor,
                        error=None,
                    )
                finally:
                    await browser.close()
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            logger.info(
                "render_page attempt %d/%d failed for %s: %s",
                attempt,
                max_retries,
                url,
                last_error,
            )
            if attempt < max_retries:
                backoff = RETRY_BACKOFF_BASE_S * (2 ** (attempt - 1))
                await asyncio.sleep(backoff)

    return _err_result(url, last_error or "exhausted_retries")


async def _extract_text(page) -> str:
    # Pass 1: accessibility tree
    try:
        snapshot = await page.accessibility.snapshot()
        if snapshot:
            parts: list[str] = []
            _walk_a11y(snapshot, parts)
            text = "\n".join(p for p in parts if p)
            if text and len(text) > 100:
                return text
    except Exception:  # noqa: BLE001
        pass

    # Pass 2: innerText
    try:
        text = await page.evaluate("() => document.body && document.body.innerText")
        if text and len(text) > 50:
            return text
    except Exception:  # noqa: BLE001
        pass

    # Pass 3: textContent fallback
    try:
        text = await page.evaluate(
            "() => document.documentElement && document.documentElement.textContent"
        )
        return text or ""
    except Exception:  # noqa: BLE001
        return ""


def _walk_a11y(node: dict, out: list[str]) -> None:
    if not isinstance(node, dict):
        return
    name = (node.get("name") or "").strip()
    if name:
        out.append(name)
    for child in node.get("children") or []:
        _walk_a11y(child, out)


def _classify_extractor(text: str) -> str:
    if not text:
        return ""
    if "\n" in text and len(text) > 200:
        return "accessibility"
    if len(text) > 50:
        return "innertext"
    return "dom_text"


def fetch_text(url: str, timeout_ms: int = 15_000) -> str:
    """Shorthand: returns just the text (or '' on failure)."""
    return render_page(url, timeout_ms=timeout_ms).text
