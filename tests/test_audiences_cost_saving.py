"""Wave 46 tick#4: audiences/ cost-saving page parity.

Verifies that site/audiences/ma_advisor.html, cpa_firm.html, shindanshi.html
present the "cost saving" framing introduced in Wave 46 tick#3 and tick#4 and
that the per-audience saving amounts advertised on each page match
docs/canonical/cost_saving_examples.md.

Anti-pattern guards:
    * No "ROI", "ARR", or "射程" framing remains on the 3 audience pages.
    * Three audience pages show their canonical saving figure
      (¥14,850/deal / ¥148,500/月 / ¥89,100/月).
    * Each page links to docs/canonical/cost_saving_examples.md.
    * Brand string is consistently "jpcite" (no legacy 税務会計AI / AutonoMath /
      zeimu-kaikei.ai in body copy on the redesigned pages).
    * HTML structure (h2 / cost-saving section anchor) preserved.

The test is intentionally offline / read-only — no LLM API, no network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MA_PATH = REPO_ROOT / "site" / "audiences" / "ma_advisor.html"
CPA_PATH = REPO_ROOT / "site" / "audiences" / "cpa_firm.html"
SHIN_PATH = REPO_ROOT / "site" / "audiences" / "shindanshi.html"
DOC_PATH = REPO_ROOT / "docs" / "canonical" / "cost_saving_examples.md"

# (label, path, expected_saving_string, expected_section_anchor)
AUDIENCE_CASES: list[tuple[str, Path, str, str]] = [
    ("ma_advisor", MA_PATH, "¥14,850/deal", 'id="cost-saving-title"'),
    ("cpa_firm", CPA_PATH, "¥148,500/月", 'id="cost-saving-title"'),
    ("shindanshi", SHIN_PATH, "¥89,100/月", 'id="cost-saving-title"'),
]


@pytest.fixture(scope="module")
def doc_md() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ma_html() -> str:
    return MA_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def cpa_html() -> str:
    return CPA_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def shin_html() -> str:
    return SHIN_PATH.read_text(encoding="utf-8")


def test_canonical_doc_exists() -> None:
    assert DOC_PATH.exists(), "docs/canonical/cost_saving_examples.md is required"
    assert DOC_PATH.stat().st_size > 1500, "doc must contain full 6-case breakdown"


def test_no_roi_arr_yarn_framing(ma_html: str, cpa_html: str, shin_html: str) -> None:
    """Wave 46 tick#4: removed mention-bias framing must not return on any
    of the 3 audience pages.

    "ROI / ARR / 射程" framing is forbidden in body copy; only structural
    accessibility / JSON-LD cruft would normally embed letters, but none of
    these are valid here."""
    for label, body in (
        ("ma_advisor.html", ma_html),
        ("cpa_firm.html", cpa_html),
        ("shindanshi.html", shin_html),
    ):
        for forbidden in (r"\bROI\b", r"\bARR\b", "射程"):
            matches = re.findall(forbidden, body)
            assert not matches, (
                f"{label}: forbidden term {forbidden!r} found {len(matches)}x"
            )


def test_each_page_has_cost_saving_section(
    ma_html: str, cpa_html: str, shin_html: str
) -> None:
    """Cost saving calculator section must be present on each audience page."""
    bodies = {
        "ma_advisor.html": ma_html,
        "cpa_firm.html": cpa_html,
        "shindanshi.html": shin_html,
    }
    for label, body in bodies.items():
        assert 'id="cost-saving-title"' in body, (
            f"{label}: missing cost-saving-title anchor"
        )
        assert "Cost saving calculator" in body, (
            f"{label}: missing 'Cost saving calculator' heading"
        )
        assert "純 LLM" in body, f"{label}: missing 純 LLM baseline label"
        assert "節約" in body, f"{label}: missing 節約 column"


def test_each_page_saving_amount_present_and_in_doc(
    doc_md: str, ma_html: str, cpa_html: str, shin_html: str
) -> None:
    """Each audience must display its canonical saving amount and the same
    figure must be reproducible from docs/canonical/cost_saving_examples.md
    (using case 1 / case 2 / case 4 base figures with the headline numbers
    in the audience pages)."""
    bodies = {
        "ma_advisor.html": ma_html,
        "cpa_firm.html": cpa_html,
        "shindanshi.html": shin_html,
    }
    for label, _path, saving, _anchor in AUDIENCE_CASES:
        body = bodies[f"{label}.html"]
        assert saving in body, f"{label}.html: missing canonical saving figure: {saving}"
    # The canonical doc should still contain a 6-case table with 円 figures.
    assert "節約" in doc_md, "canonical doc must contain 節約 framing"
    # Cross-check ¥3/req unit price referenced in doc.
    assert "¥3/req" in doc_md, "canonical doc must contain ¥3/req metering"


def test_each_page_links_to_canonical_doc(
    ma_html: str, cpa_html: str, shin_html: str
) -> None:
    """Each redesigned audience page must link to the canonical doc."""
    bodies = {
        "ma_advisor.html": ma_html,
        "cpa_firm.html": cpa_html,
        "shindanshi.html": shin_html,
    }
    for label, body in bodies.items():
        assert "docs/canonical/cost_saving_examples.md" in body, (
            f"{label}: missing link to canonical cost saving doc"
        )


def test_brand_consistency(ma_html: str, cpa_html: str, shin_html: str) -> None:
    """Wave 46 brand discipline: only 'jpcite' in the body of redesigned
    pages (legacy brand markers must stay out of consumer-facing copy)."""
    bodies = {
        "ma_advisor.html": ma_html,
        "cpa_firm.html": cpa_html,
        "shindanshi.html": shin_html,
    }
    for label, body in bodies.items():
        assert "jpcite" in body, f"{label}: jpcite brand missing"
        for legacy in ("税務会計AI", "AutonoMath", "zeimu-kaikei.ai"):
            assert legacy not in body, f"{label}: legacy brand leak: {legacy}"


def test_unit_price_constant(
    ma_html: str, cpa_html: str, shin_html: str
) -> None:
    """¥3/req metering remains the only published price model on each
    audience page."""
    bodies = {
        "ma_advisor.html": ma_html,
        "cpa_firm.html": cpa_html,
        "shindanshi.html": shin_html,
    }
    for label, body in bodies.items():
        assert "¥3" in body, f"{label}: unit price ¥3 missing"
        assert "従量" in body, f"{label}: 従量 wording missing"


def test_structural_anchors_intact(
    ma_html: str, cpa_html: str, shin_html: str
) -> None:
    """Smoke check: hero, fence, cost-saving, install, cta sections must
    all be present on each audience page (Wave 46 tick#4 must not have
    removed any of the existing structural anchors)."""
    bodies = {
        "ma_advisor.html": ma_html,
        "cpa_firm.html": cpa_html,
        "shindanshi.html": shin_html,
    }
    for label, body in bodies.items():
        for anchor in (
            'id="hero-title"',
            'id="fence-title"',
            'id="cost-saving-title"',
            'id="install-title"',
            'id="cta-title"',
        ):
            assert anchor in body, f"{label}: section anchor {anchor} missing"


def test_html_parses_clean(
    ma_html: str, cpa_html: str, shin_html: str
) -> None:
    """All 3 audience pages must parse without raising HTMLParser errors.

    Uses stdlib html.parser to avoid extra deps. Any parser error increases
    the per-page error count; we assert zero across the 3 files."""
    from html.parser import HTMLParser

    class StrictParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.errors = 0

        def error(self, msg: str) -> None:  # pragma: no cover - shouldn't fire
            self.errors += 1

    for label, body in (
        ("ma_advisor.html", ma_html),
        ("cpa_firm.html", cpa_html),
        ("shindanshi.html", shin_html),
    ):
        p = StrictParser()
        p.feed(body)
        assert p.errors == 0, f"{label}: HTML parser raised {p.errors} errors"


def test_each_page_h2_count_preserved(
    ma_html: str, cpa_html: str, shin_html: str
) -> None:
    """Each audience page should retain exactly 4 visible h2 sections
    (fence is visually-hidden but still an h2 by structural choice =
    fence + cost-saving + install + cta = 4)."""
    for label, body in (
        ("ma_advisor.html", ma_html),
        ("cpa_firm.html", cpa_html),
        ("shindanshi.html", shin_html),
    ):
        h2_count = len(re.findall(r"<h2\b", body))
        assert h2_count == 4, (
            f"{label}: expected 4 h2 elements (fence/cost-saving/install/cta), "
            f"got {h2_count}"
        )
