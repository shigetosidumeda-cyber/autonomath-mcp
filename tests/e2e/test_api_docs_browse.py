"""Internal-link crawl on the public site.

Philosophy: test the *published* surface — index.html, pricing.html,
dashboard.html, privacy.html, tokushoho.html, tos.html, status.html,
success.html — and every in-origin link they expose. External links
(github.com, mailto:, anything off-origin) are skipped. Markdown
docs are skipped too — the /docs/ hierarchy is rendered separately
(mkdocs / CF Pages) and its own CI task validates internal doc links.

Crawl order is breadth-first with a visited set. A dead internal link
(404, 5xx) fails the test with the referring page + href. Anchors (#foo)
are resolved to the page, not the anchor — we only assert the page loads.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

import pytest

if TYPE_CHECKING:
    from playwright.async_api import Page

_START_PAGES = [
    "/index.html",
    "/pricing.html",
    "/dashboard.html",
    "/privacy.html",
    "/tokushoho.html",
    "/tos.html",
    "/status.html",
    "/success.html",
]


# Known off-site / email / anchor-only prefixes to skip without a fetch.
_SKIP_PREFIXES = ("mailto:", "tel:", "javascript:", "#")


def _is_external(base_url: str, href: str) -> bool:
    if any(href.startswith(p) for p in _SKIP_PREFIXES):
        return True
    if href.startswith("//"):
        return True
    if href.startswith("http://") or href.startswith("https://"):
        base_host = urlparse(base_url).netloc
        target_host = urlparse(href).netloc
        return base_host != target_host
    return False


def _strip_fragment(href: str) -> str:
    return href.split("#", 1)[0]


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_internal_link_crawl_has_no_dead_links(
    page: Page, url_for, base_url: str
) -> None:
    """Crawl each known page + its first-hop internal links; assert all 200.

    Bounded to one hop so the test stays under 30s even on staging — the
    stable set of internal links is small (< 40) and mostly /-rooted.
    """
    visited: set[str] = set()
    failures: list[tuple[str, str, int]] = []  # (referrer, href, status)

    to_visit: list[str] = [url_for(p) for p in _START_PAGES]

    # Collect hrefs from each start page and test them once.
    for start in to_visit:
        if start in visited:
            continue
        visited.add(start)
        resp = await page.goto(start)
        # Some pages may not exist in a staging/prod split — tolerate 404 on
        # the docs hub (tested separately by its own pipeline), but all
        # files under site/*.html must be 200.
        if resp is None or resp.status != 200:
            failures.append(("(start)", start, resp.status if resp else -1))
            continue

        anchors = await page.locator("a[href]").evaluate_all(
            "els => els.map(e => e.getAttribute('href'))"
        )

        for raw_href in anchors:
            if raw_href is None:
                continue
            raw_href = raw_href.strip()
            if not raw_href or _is_external(base_url, raw_href):
                continue
            # Resolve relative → absolute
            target = urljoin(start, raw_href)
            target = _strip_fragment(target)
            # Stay on origin
            if urlparse(target).netloc != urlparse(base_url).netloc:
                continue
            # Don't re-fetch pages we already started from.
            if target in visited:
                continue
            visited.add(target)

            # HEAD would be ideal but many static hosts don't support it; use
            # page.request for a lightweight GET without rendering the DOM.
            try:
                r = await page.request.get(target)
            except Exception:  # pragma: no cover — network flake
                failures.append((start, target, -1))
                continue

            # Accept 200; also accept 204 and 304 (just in case a CDN cache
            # edge returns them). /docs/* may legitimately 404 on the API
            # origin when docs are hosted separately — skip that subtree.
            if target.rstrip("/").endswith("/docs") or "/docs/" in target:
                continue

            if r.status not in (200, 204, 304):
                failures.append((start, target, r.status))

    assert not failures, (
        "dead internal links:\n"
        + "\n".join(
            f"  {ref} -> {href} (HTTP {status})" for ref, href, status in failures
        )
    )
