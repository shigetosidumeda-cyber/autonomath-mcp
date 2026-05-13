"""Wave 49 tick#2: MkDocs Material override 4-element contract.

Pre-tick state (STATE_w49_docs_mkdocs_override_pr.md):
    site/docs/api-reference/index.html (one of 75+ mkdocs-built sub-pages)
    contained 0/4 elements:
      1. billing_progress.js   (script tag in <head>)
      2. rum_funnel_collector.js (script tag in <head>)
      3. data-billing-progress  (visible div mount point in <body>)
      4. breadcrumb            (CSS class / textual marker on the nav)

    The pages-deploy-main.yml workflow runs `mkdocs build` which overwrites
    the hand-crafted static `site/docs/index.html` (CWV-HARDENED hub, all
    4 elements present) with a Material-templated index that lacks them
    all. Every sub-page in the nav tree inherits that gap.

This tick injects the 4 elements via two theme partials so the contract is
satisfied on every mkdocs-built page without changing any docs/*.md source:

    - overrides/main.html         {% block extrahead %}
        injects the two <script> tags so audit scripts grep'ing the rendered
        HTML find them in the page <head>.
    - overrides/partials/content.html
        injects the <div data-billing-progress> mount point so
        billing_progress.js has a stable selector to populate. Also adds
        `class="breadcrumb"` to the pre-existing PR #185 nav so the bare
        `breadcrumb` selector matches without relying on Material's
        internal `md-path` class name.

Tests below verify the 4 elements at the partial-source level (cheap, no
mkdocs build required in CI). A separate live audit script
(STATE_w49_lost_zero_*) walks the deployed pages on Cloudflare Pages.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_HTML = REPO_ROOT / "overrides" / "main.html"
CONTENT_HTML = REPO_ROOT / "overrides" / "partials" / "content.html"
MKDOCS_YML = REPO_ROOT / "mkdocs.yml"


def test_overrides_dir_exists() -> None:
    """Sanity: overrides/ must exist and contain the two partials we touch."""
    assert MAIN_HTML.exists(), f"missing override: {MAIN_HTML}"
    assert CONTENT_HTML.exists(), f"missing override: {CONTENT_HTML}"


def test_main_html_injects_billing_progress_script() -> None:
    """Element 1/4: billing_progress.js script tag in <head>."""
    src = MAIN_HTML.read_text(encoding="utf-8")
    # absolute path so the same tag works on /docs/, /docs/api-reference/, etc
    assert "/assets/billing_progress.js" in src, (
        "billing_progress.js script tag missing from overrides/main.html "
        "<head>; mkdocs sub-pages will fail the 4-element contract"
    )
    # script tag must be defer so CWV isn't hurt
    assert re.search(
        r"<script[^>]*src=\"/assets/billing_progress\.js\"[^>]*defer", src
    ), "billing_progress.js must be loaded with defer (CWV contract)"


def test_main_html_injects_rum_funnel_collector_script() -> None:
    """Element 2/4: rum_funnel_collector.js script tag in <head>."""
    src = MAIN_HTML.read_text(encoding="utf-8")
    assert "/assets/rum_funnel_collector.js" in src, (
        "rum_funnel_collector.js script tag missing from overrides/main.html "
        "<head>; mkdocs sub-pages will not emit RUM beacons"
    )
    assert re.search(
        r"<script[^>]*src=\"/assets/rum_funnel_collector\.js\"[^>]*defer",
        src,
    ), "rum_funnel_collector.js must be loaded with defer (CWV contract)"


def test_main_html_injects_docs_hreflang_alternates() -> None:
    """Docs are ja-only, so every canonical MkDocs page self-declares ja + x-default."""
    src = MAIN_HTML.read_text(encoding="utf-8")
    assert "page.canonical_url" in src, (
        "docs hreflang alternates must derive from Material's canonical URL "
        "so sitemap pages stay aligned after mkdocs build"
    )
    assert 'hreflang="ja" href="{{ page.canonical_url }}"' in src
    assert 'hreflang="x-default" href="{{ page.canonical_url }}"' in src


def test_content_html_injects_billing_progress_div() -> None:
    """Element 3/4: <div data-billing-progress> mount point on every page."""
    src = CONTENT_HTML.read_text(encoding="utf-8")
    # the attribute must be bare (data-billing-progress) — JS treats any
    # element matching `[data-billing-progress]` as a mount point
    assert "data-billing-progress" in src, (
        "data-billing-progress mount-point div missing from "
        "overrides/partials/content.html; billing_progress.js has nowhere to render"
    )
    # the variant must match the static landing-page contract so the JS
    # branch that fires there also fires here
    assert "data-cta-variant=\"docs-progress\"" in src, (
        "data-cta-variant=\"docs-progress\" missing — billing_progress.js "
        "branches by variant; mismatched variants render the wrong copy"
    )
    # hidden by default so unauthenticated visitors don't see an empty
    # rectangle; JS removes the attribute once data is available
    assert re.search(r"<div[^>]*data-billing-progress[^>]*\bhidden\b", src), (
        "billing-progress div must be hidden by default; visible-when-empty "
        "is a UX regression"
    )


def test_content_html_carries_breadcrumb_class() -> None:
    """Element 4/4: stable `class="breadcrumb"` selector on the nav."""
    src = CONTENT_HTML.read_text(encoding="utf-8")
    # tick#2 added the `breadcrumb` class to the existing PR #185 nav so
    # the 4-element audit script's bare CSS selector matches without
    # depending on Material's internal `md-path` class
    assert re.search(r"class=\"[^\"]*\bbreadcrumb\b", src), (
        "no `breadcrumb` class on the jpcite-doc-nav — audit scripts grep "
        "for this selector; matching only `md-path` is fragile across "
        "Material version bumps"
    )


def test_mkdocs_keeps_custom_dir_overrides() -> None:
    """Sanity: mkdocs.yml must keep `custom_dir: overrides` so our partials run."""
    src = MKDOCS_YML.read_text(encoding="utf-8")
    assert "custom_dir: overrides" in src, (
        "mkdocs.yml lost `custom_dir: overrides` — our 4-element injection "
        "would silently regress to Material default"
    )


def test_main_html_still_inherits_base() -> None:
    """Regression: overrides/main.html must still extend base.html.

    A common foot-gun is replacing `{% extends "base.html" %}` with raw
    markup which strips out all Material features (search, palette toggle,
    nav drawer, ...). Keep the extends contract.
    """
    src = MAIN_HTML.read_text(encoding="utf-8")
    assert "{% extends \"base.html\" %}" in src, (
        "overrides/main.html must extend base.html — replacing with raw "
        "HTML drops Material's entire theme"
    )
    assert "{% block extrahead %}" in src, (
        "{% block extrahead %} missing — the 2 script tags must live "
        "inside this block to land in <head>, not below </html>"
    )


def test_main_html_does_not_add_google_fonts_stylesheet() -> None:
    """Regression: avoid override-level render-blocking third-party font CSS."""
    src = MAIN_HTML.read_text(encoding="utf-8")
    offenders = [
        needle
        for needle in (
            "fonts.googleapis.com",
            "fonts.gstatic.com",
            "https://fonts.googleapis.com/css2",
        )
        if needle in src
    ]
    assert offenders == [], (
        "overrides/main.html must not add Google Fonts preconnects or "
        "stylesheets; MkDocs Material owns font.text/font.code loading"
    )


def test_jsonld_index_include_preserved() -> None:
    """Regression: pre-existing index_jsonld.html include must still fire on homepage.

    The original purpose of overrides/main.html was to inject
    SoftwareApplication + WebSite JSON-LD into the homepage <head>. Tick#2
    is purely additive; the JSON-LD include must remain.
    """
    src = MAIN_HTML.read_text(encoding="utf-8")
    assert "partials/index_jsonld.html" in src, (
        "index_jsonld.html include removed — SoftwareApplication + WebSite "
        "Schema.org graph would drop off the docs homepage"
    )
    assert "page.is_homepage" in src, (
        "is_homepage guard removed — JSON-LD would render on every page "
        "(duplicate Schema.org → SEO penalty)"
    )
