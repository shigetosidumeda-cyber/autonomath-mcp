"""_playwright_helper.py — Playwright-based fallback fetcher for ETL scripts.

Wave 36 horizontal wire. Every ETL / cron ingest script can call
`fetch_with_fallback()` (async) or `fetch_with_fallback_sync()` instead
of raw `httpx.get()` / `urllib.urlopen()`. The default path is the
caller's static fetcher; on 4xx / 5xx / timeout / empty body we retry
3 × with exponential backoff and then fall through to a Playwright
render. The structural DOM is extracted via the accessibility tree +
innerText — purely deterministic, no LLM call.

Constraints
-----------
* **No LLM API.** Pure structural DOM extraction. The CI guard
  `tests/test_no_llm_in_production.py` enforces this; do **not** add
  any `anthropic` / `openai` / `claude_agent_sdk` import here.
* **No aggregator URLs.** `noukaweb`, `hojyokin-portal`, `biz.stayway`,
  `hojo-navi`, `mirai-joho`, plus a handful of subsidy mirrors are
  refused at the entry — even if a static fetcher upstream let one
  through, the Playwright fallback re-validates.
* **Viewport 1280 × 1600.** memory `feedback_image_resize` documents
  that CLI screenshots > 1900 px crash Claude Code's image read tool,
  so the helper hard-caps viewport height at 1600 px and post-resizes
  every screenshot via `_image_helper.sips_resize_inplace`.
* **Retry 3 + exponential backoff.** 1.5s × 2^(n-1).
* **Browser walk + screenshot + Vision LLM** is the canonical
  information-collection pattern (memory `feedback_collection_browser_first`).
  The screenshot path is returned so operator-side flows can pipe
  the PNG into a manual Vision review when the regex disagrees.

Aggregator URL refusal
----------------------
Per CLAUDE.md "Data hygiene" + memory `feedback_no_fake_data`,
aggregator hostnames are **banned** from jpcite citations. The helper
refuses these URLs up-front; callers must skip the row instead of
laundering it through the fallback.

Public surface
--------------
    fetch_with_fallback(url, static_fetcher=None, screenshot_path=None, ...)
        Async static-first → Playwright fallback fetch.

    fetch_with_fallback_sync(url, ...)
        Sync wrapper around the async core for legacy callers.

    render_page(url, screenshot_dir=None, timeout_ms=15_000)
        Legacy "always Playwright" sync entry point. Returns a
        `RenderResult` (text + screenshot + meta). Never raises.

    is_banned_url(url)
        True iff `url` matches the aggregator deny-list.

    screenshot_path_for(etl_name, root="/tmp/etl_screenshots")
        Build a timestamped screenshot path.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("jpcite.etl.playwright_fallback")

# ---------------------------------------------------------------------------
# Aggregator deny-list — mirrored from scripts/etl/ingest_industry_guidelines.py.
# ---------------------------------------------------------------------------

BANNED_SOURCE_HOSTS: tuple[str, ...] = (
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "hojo-navi",
    "mirai-joho",
    "hojyokin-info",
    "hojokin-portal",
    "subsidy-port.jp",
    "subsidy.j-finance.go.jp.cache",
)

# Backwards-compat alias for the original API.
_AGGREGATOR_HOSTS = BANNED_SOURCE_HOSTS

# ---------------------------------------------------------------------------
# Viewport — hard-capped to keep screenshots readable by Claude Code's Read
# (memory feedback_image_resize: > 1900 px crashes CLI).
# ---------------------------------------------------------------------------

VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 1600
MAX_SCREENSHOT_EDGE = 1600

# Retry policy.
MAX_RETRIES = 3
RETRY_ATTEMPTS = MAX_RETRIES
RETRY_BACKOFF_BASE_S = 1.5

# Navigation timeout.
NAV_TIMEOUT_MS = 30_000
HELPER_TIMEOUT_SEC = float(os.environ.get("JPCITE_PLAYWRIGHT_TIMEOUT_SEC", "60"))

# User-Agent — explicitly identify as jpcite operator ETL.
JPCITE_USER_AGENT = (
    "jpcite-etl/0.3.5 (+https://jpcite.com/about/etl) "
    "Playwright/HeadlessChromium operator-side fetch"
)
DEFAULT_UA = JPCITE_USER_AGENT


# ---------------------------------------------------------------------------
# Errors + result types
# ---------------------------------------------------------------------------


class AggregatorRefusedError(ValueError):
    """Raised when an aggregator host slips past the static layer."""


class PlaywrightFallbackError(RuntimeError):
    """Raised when both static + Playwright paths fail."""


@dataclass(frozen=True)
class FetchResult:
    """Result of a fallback fetch (Wave 36 wire)."""

    body: str
    source: str  # "static" | "playwright"
    status_code: int  # 200 on static success; -1 on Playwright path
    url: str
    screenshot_path: str | None = None


@dataclass(frozen=True)
class RenderResult:
    """Legacy "always Playwright" return type."""

    text: str
    screenshot_path: Path | None
    status: int
    final_url: str
    fetched_at: str
    extractor: str
    error: str | None = None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def is_aggregator(url: str | None) -> bool:
    """Refuse aggregator hostnames — they are banned from source_url."""
    if not url:
        return True
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return True
    if not host:
        return True
    return any(bad in host for bad in BANNED_SOURCE_HOSTS)


def is_banned_url(url: str) -> bool:
    """Wave 36 wire alias for `is_aggregator`."""
    return is_aggregator(url)


def screenshot_path_for(etl_name: str, *, root: str = "/tmp/etl_screenshots") -> str:
    """Build a timestamped screenshot path under `/tmp/etl_screenshots/`."""
    ts = int(time.time())
    return f"{root}/{etl_name}_{ts}.png"


def screenshot_filename(url: str) -> str:
    """Stable PNG filename derived from a sha1 of the URL."""
    sha = hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return f"{sha}.png"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _resize_with_sips(png_path: Path, max_edge: int = MAX_SCREENSHOT_EDGE) -> None:
    """Best-effort sips resize. Silently skips on Linux (no sips)."""
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


def _classify_extractor(text: str) -> str:
    if not text:
        return ""
    if "\n" in text and len(text) > 200:
        return "accessibility"
    if len(text) > 50:
        return "innertext"
    return "dom_text"


def _walk_a11y(node: dict, out: list[str]) -> None:
    if not isinstance(node, dict):
        return
    name = (node.get("name") or "").strip()
    if name:
        out.append(name)
    for child in node.get("children") or []:
        _walk_a11y(child, out)


# ---------------------------------------------------------------------------
# Async core — Playwright render
# ---------------------------------------------------------------------------


async def _render_async(
    url: str,
    *,
    screenshot_dir: Path | None,
    timeout_ms: int,
    max_retries: int,
) -> RenderResult:
    """Async Playwright render — lazy-imports playwright."""
    try:
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        logger.warning("playwright not installed; render_page falling back: %s", exc)
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

                    try:
                        await page.wait_for_load_state(
                            "networkidle", timeout=min(timeout_ms, 8000)
                        )
                    except Exception:  # noqa: BLE001
                        pass

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
                        # Defer-import to keep _image_helper optional.
                        try:
                            from scripts.etl._image_helper import sips_resize_inplace

                            sips_resize_inplace(screenshot_path, max_width=MAX_SCREENSHOT_EDGE)
                        except ImportError:
                            pass

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
    """Three-pass text extraction, structured-first."""
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

    try:
        text = await page.evaluate("() => document.body && document.body.innerText")
        if text and len(text) > 50:
            return text
    except Exception:  # noqa: BLE001
        pass

    try:
        text = await page.evaluate(
            "() => document.documentElement && document.documentElement.textContent"
        )
        return text or ""
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Legacy entry point
# ---------------------------------------------------------------------------


def render_page(
    url: str,
    *,
    screenshot_dir: Path | None = None,
    timeout_ms: int = 15_000,
    max_retries: int = MAX_RETRIES,
) -> RenderResult:
    """Sync entry-point — always drives Playwright. Never raises.

    Aggregator URLs are refused with `error='aggregator_refused'`;
    callers branch on `result.text` truthiness.
    """
    if is_aggregator(url):
        return RenderResult(
            text="",
            screenshot_path=None,
            status=0,
            final_url=url,
            fetched_at=_now_iso(),
            extractor="",
            error="aggregator_refused",
        )

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


def fetch_text(url: str, timeout_ms: int = 15_000) -> str:
    """Shorthand: returns just `text` (or '' on failure)."""
    return render_page(url, timeout_ms=timeout_ms).text


# ---------------------------------------------------------------------------
# Wave 36 wire: static-first → Playwright fallback
# ---------------------------------------------------------------------------


async def fetch_with_fallback(
    url: str,
    *,
    static_fetcher: Callable[[str], Awaitable[str] | str] | None = None,
    screenshot_path: str | None = None,
    timeout_ms: int = NAV_TIMEOUT_MS,
) -> FetchResult:
    """Static-first, Playwright-fallback fetch entry point.

    The caller passes its own `static_fetcher` (sync or async). On
    any `Exception` (4xx, 5xx, timeout, DNS, decode), we retry up to
    `RETRY_ATTEMPTS` with exponential backoff and then drive the
    Playwright walk for the structural DOM. Screenshots are
    auto-resized to ≤ 1600 px so the operator can `Read` them.
    """
    if is_banned_url(url):
        raise AggregatorRefusedError(f"banned aggregator host: {url}")

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported scheme: {url}")

    static_errors: list[str] = []

    if static_fetcher is not None:
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                if asyncio.iscoroutinefunction(static_fetcher):
                    body = await static_fetcher(url)
                else:
                    body = static_fetcher(url)
                if isinstance(body, str) and body:
                    return FetchResult(
                        body=body,
                        source="static",
                        status_code=200,
                        url=url,
                    )
                static_errors.append(f"attempt={attempt} empty body")
            except Exception as exc:  # noqa: BLE001
                static_errors.append(f"attempt={attempt} {type(exc).__name__}: {exc}")
                if attempt < RETRY_ATTEMPTS:
                    await asyncio.sleep(RETRY_BACKOFF_BASE_S * (2 ** (attempt - 1)))

    logger.warning(
        "static fetch failed for %s after %d attempts; trying Playwright",
        url,
        RETRY_ATTEMPTS,
    )

    screenshot_dir = Path(screenshot_path).parent if screenshot_path else None
    try:
        result = await _render_async(
            url,
            screenshot_dir=screenshot_dir,
            timeout_ms=timeout_ms,
            max_retries=RETRY_ATTEMPTS,
        )
    except Exception as exc:  # noqa: BLE001
        raise PlaywrightFallbackError(
            f"both static and Playwright failed for {url}; "
            f"static_chain={static_errors!r}; playwright={type(exc).__name__}: {exc}",
        ) from exc

    if not result.text:
        raise PlaywrightFallbackError(
            f"Playwright returned empty body for {url}; "
            f"static_chain={static_errors!r}; playwright_err={result.error}",
        )

    final_screenshot: str | None = None
    if result.screenshot_path is not None and screenshot_path is not None:
        try:
            target = Path(screenshot_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            result.screenshot_path.rename(target)
            final_screenshot = str(target)
        except OSError as exc:
            logger.debug(
                "screenshot rename %s -> %s skipped: %s",
                result.screenshot_path,
                screenshot_path,
                exc,
            )
            final_screenshot = str(result.screenshot_path)
    elif result.screenshot_path is not None:
        final_screenshot = str(result.screenshot_path)

    if final_screenshot is not None:
        try:
            from scripts.etl._image_helper import sips_resize_inplace

            sips_resize_inplace(Path(final_screenshot), max_width=MAX_SCREENSHOT_EDGE)
        except ImportError:
            pass

    return FetchResult(
        body=result.text,
        source="playwright",
        status_code=result.status or -1,
        url=result.final_url or url,
        screenshot_path=final_screenshot,
    )


def fetch_with_fallback_sync(
    url: str,
    *,
    static_fetcher: Callable[[str], str] | None = None,
    screenshot_path: str | None = None,
    timeout_ms: int = NAV_TIMEOUT_MS,
) -> FetchResult:
    """Sync wrapper around `fetch_with_fallback` for legacy callers."""
    return asyncio.run(
        fetch_with_fallback(
            url,
            static_fetcher=static_fetcher,
            screenshot_path=screenshot_path,
            timeout_ms=timeout_ms,
        ),
    )
