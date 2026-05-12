"""Wave 49 tick: 迷子ゼロ 100% — 4 page x 4 element matrix verify.

Verifies that all 4 funnel-relevant pages contain the 4 wiring elements:
  1. <script src=".../billing_progress.js">
  2. <script src=".../rum_funnel_collector.js">
  3. data-billing-progress attribute (widget mount point)
  4. breadcrumb nav (loss-prevention navigation)

Pages (4):
  - site/index.html (home)
  - site/pricing.html (already wired in PR #182)
  - site/onboarding.html (already wired in PR #182)
  - site/docs/index.html (new in this tick — was 404 before)

Total matrix: 4 x 4 = 16 invariants. All must pass.

This test is intentionally structural (string-grep based, no HTML parser
required) so it stays cheap and stable across CSS / copy churn. It does
NOT enforce the order or attribute styling.

Run:
  pytest tests/test_lost_zero_100_4page.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"

PAGES = [
    SITE / "index.html",
    SITE / "pricing.html",
    SITE / "onboarding.html",
    SITE / "docs" / "index.html",
]

# Each element is (label, list-of-acceptable-substrings).
# Any substring match counts (OR semantics) — accommodates minor href / quote
# style differences across pages without being brittle.
ELEMENTS = [
    (
        "billing_progress.js script tag",
        ['src="/assets/billing_progress.js"', "src='/assets/billing_progress.js'"],
    ),
    (
        "rum_funnel_collector.js script tag",
        [
            'src="/assets/rum_funnel_collector.js"',
            "src='/assets/rum_funnel_collector.js'",
        ],
    ),
    (
        "data-billing-progress widget mount",
        ["data-billing-progress"],
    ),
    (
        "breadcrumb nav",
        ['class="breadcrumb"', "class='breadcrumb'"],
    ),
]


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_page_exists(page: Path) -> None:
    """Each of the 4 pages must exist on disk."""
    assert page.is_file(), f"missing page: {page.relative_to(REPO_ROOT)}"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
@pytest.mark.parametrize("element", ELEMENTS, ids=lambda e: e[0])
def test_page_has_element(page: Path, element: tuple[str, list[str]]) -> None:
    """16-cell matrix: each page must contain each of the 4 elements."""
    label, needles = element
    assert page.is_file(), f"missing page: {page.relative_to(REPO_ROOT)}"
    text = page.read_text(encoding="utf-8")
    matched = any(needle in text for needle in needles)
    assert matched, (
        f"{page.relative_to(REPO_ROOT)} missing element '{label}' "
        f"(looked for any of: {needles})"
    )


def test_no_duplicate_billing_progress_script() -> None:
    """billing_progress.js must appear at most once per page (no dup wiring)."""
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        count = text.count("billing_progress.js")
        assert count <= 1, (
            f"{page.relative_to(REPO_ROOT)} has billing_progress.js x{count} "
            "(duplicate wiring would double-fire analytics)"
        )


def test_no_duplicate_rum_funnel_collector_script() -> None:
    """rum_funnel_collector.js must appear at most once per page."""
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        count = text.count("rum_funnel_collector.js")
        assert count <= 1, (
            f"{page.relative_to(REPO_ROOT)} has rum_funnel_collector.js x{count}"
        )


def test_breadcrumb_links_to_home() -> None:
    """Non-home pages' breadcrumb must include a link back to /."""
    non_home = [p for p in PAGES if p.name != "index.html" or p.parent.name == "docs"]
    for page in non_home:
        text = page.read_text(encoding="utf-8")
        # Either the breadcrumb anchor or the home href must be present in
        # the breadcrumb region. Conservative: just require an href="/" near
        # the breadcrumb keyword.
        if 'class="breadcrumb"' not in text and "class='breadcrumb'" not in text:
            continue  # element test already covers presence
        # Find region after first "breadcrumb" up to closing </nav>
        idx = text.find("breadcrumb")
        snippet = text[idx : idx + 600]
        assert 'href="/"' in snippet or "href='/'" in snippet, (
            f"{page.relative_to(REPO_ROOT)} breadcrumb missing 'href=/' anchor "
            "(home link required for loss-prevention nav)"
        )
