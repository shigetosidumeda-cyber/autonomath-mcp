"""Smoke-check every public-facing static page.

We want D-Day visitors to land on every legal page + status + press and
see a) HTTP 200 and b) the canonical H1 / heading for that page. A broken
link to privacy.html on launch day hurts; a blank tokushoho hurts more.

`press/about.md` is a Markdown source that may be rendered by whatever
static host we're using (Cloudflare Pages, Fly, etc.) — we probe the
page as HTML but fall back to 200 + "About jpintel" in the raw body
when a Markdown-to-HTML step isn't configured.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.async_api import Page

_PUBLIC_PAGES: list[tuple[str, re.Pattern[str]]] = [
    # path                    expected H1 (regex)
    ("/privacy.html", re.compile(r"プライバシーポリシー")),
    ("/tokushoho.html", re.compile(r"特定商取引法")),
    ("/tos.html", re.compile(r"利用規約")),
    ("/status.html", re.compile(r"稼働状況|Status")),
    ("/pricing.html", re.compile(r"料金")),
    ("/index.html", re.compile(r"日本の制度")),
    ("/success.html", re.compile(r"支払い完了|session_id")),
]


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.parametrize(
    "path,expected_heading",
    _PUBLIC_PAGES,
    ids=[p[0] for p in _PUBLIC_PAGES],
)
async def test_public_page_returns_200_and_shows_heading(
    page: Page, url_for, path: str, expected_heading: re.Pattern[str]
) -> None:
    resp = await page.goto(url_for(path), wait_until="commit")
    assert resp is not None, f"no response object for {path}"
    assert resp.status == 200, f"{path} returned HTTP {resp.status}"

    # Some pages (success.html) flip through states via JS — we accept any
    # state whose h1 OR alert message matches the regex.
    # Search the full body text (not just h1) because `success.html` renders
    # the heading inside a hidden state by default; the visible-on-load text
    # is the "session_id" error when accessed without a ?session_id= param.
    body_text = await page.locator("body").text_content()
    assert body_text is not None
    assert expected_heading.search(body_text), (
        f"{path} body did not contain the expected heading pattern "
        f"{expected_heading.pattern!r}; got first 300 chars: "
        f"{body_text[:300]!r}"
    )


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_press_about_returns_200(page: Page, url_for) -> None:
    """The press kit lives at site/press/about.md.

    Accept either rendered HTML (200 with body text) or the raw Markdown
    served as text/plain — depends on the static host config.
    """
    resp = await page.goto(url_for("/press/about.md"), wait_until="commit")
    assert resp is not None
    assert resp.status == 200, f"/press/about.md returned HTTP {resp.status}"
    body_text = await page.locator("body").text_content()
    assert body_text is not None
    # Matches the canonical opening line or its English counterpart.
    assert re.search(r"(プレスキット|Press Kit|jpintel)", body_text), (
        f"press/about content doesn't look right: {body_text[:200]!r}"
    )
