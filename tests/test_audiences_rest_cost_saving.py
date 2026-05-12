"""Wave 46 tick#4 — audiences rest cost saving migration tests.

Verifies each of 14 audience pages (rest after tick#3 cpa_firm/shindanshi/ma_advisor):

1. cost saving section is present with consistent structure
2. per-case saving amount matches canonical doc
3. no legacy ROI/ARR/年¥/year-cost markers leaked back
4. brand=jpcite preserved, no old brand (AutonoMath/税務会計AI/zeimu-kaikei)
5. h2/h3 structure is intact (HTML structure not corrupted)
6. canonical doc link present
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIENCES_DIR = REPO_ROOT / "site" / "audiences"
CANONICAL_DOC = REPO_ROOT / "docs" / "canonical" / "cost_saving_examples.md"

# 14 pages this tick covers (excluding tick#3 landed: cpa_firm, shindanshi, ma_advisor)
TICK4_PAGES = [
    "admin-scrivener.html",
    "construction.html",
    "dev.html",
    "index.html",
    "journalist.html",
    "manufacturing.html",
    "real_estate.html",
    "shihoshoshi.html",
    "shinkin.html",
    "shokokai.html",
    "smb.html",
    "subsidy-consultant.html",
    "tax-advisor.html",
    "vc.html",
]

# canonical per-case cost saving expectations (from cost_saving_examples.md)
# (page, expected saving JPY)
EXPECTED_SAVINGS = {
    "admin-scrivener.html": 34995,
    "construction.html": 31994,
    "dev.html": 19985,
    "index.html": 26991,  # weighted avg
    "journalist.html": 11991,
    "manufacturing.html": 31994,
    "real_estate.html": 27994,
    "shihoshoshi.html": 29994,
    "shinkin.html": 7194,
    "shokokai.html": 3994,
    "smb.html": 9991,
    "subsidy-consultant.html": 11991,
    "tax-advisor.html": 9994,
    "vc.html": 39988,
}

# legacy patterns we want zero of (post-migration)
LEGACY_ROI_PATTERNS = [
    r"\bROI\b",
    r"\bARR\b",
    r"年¥\d",
    r"年間¥\d",
    r"月¥\d{2,}",  # ¥10+ monthly, exclude lower noise
]

OLD_BRAND_PATTERNS = [
    r"AutonoMath",
    r"税務会計AI",
    r"zeimu-kaikei",
]


@pytest.fixture(scope="module")
def canonical_text() -> str:
    """Read canonical cost saving doc."""
    assert CANONICAL_DOC.exists(), f"canonical doc missing: {CANONICAL_DOC}"
    return CANONICAL_DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pages() -> dict[str, str]:
    """Load all 14 audience pages."""
    result = {}
    for name in TICK4_PAGES:
        p = AUDIENCES_DIR / name
        assert p.exists(), f"page missing: {p}"
        result[name] = p.read_text(encoding="utf-8")
    return result


def test_canonical_doc_exists(canonical_text: str) -> None:
    assert "jpcite Cost Saving Examples" in canonical_text
    assert "¥3/billable unit" in canonical_text
    assert "Wave 46 tick#4" in canonical_text
    # canonical brand
    assert "AutonoMath" not in canonical_text or "AutonoMath EC" in canonical_text  # AutonoMath EC v4 ref ok
    assert "税務会計AI" not in canonical_text


def test_canonical_lists_all_14_audiences(canonical_text: str) -> None:
    for name in TICK4_PAGES:
        stem = name.replace(".html", "")
        assert stem in canonical_text, f"canonical doc missing {stem}"


def test_canonical_saving_amounts_present(canonical_text: str) -> None:
    """canonical doc must list each expected saving amount."""
    for name, amount in EXPECTED_SAVINGS.items():
        # accept ¥X,XXX format with comma
        formatted = f"¥{amount:,}"
        assert formatted in canonical_text, f"canonical doc missing {formatted} for {name}"


@pytest.mark.parametrize("name", TICK4_PAGES)
def test_page_has_cost_saving_section(pages: dict[str, str], name: str) -> None:
    """Each page must have a cost-title section."""
    body = pages[name]
    assert 'aria-labelledby="cost-title"' in body, f"{name}: missing cost-title section"
    assert 'id="cost-title"' in body, f"{name}: missing cost-title heading"
    assert "cost saving" in body, f"{name}: missing 'cost saving' phrase"


@pytest.mark.parametrize("name", TICK4_PAGES)
def test_page_links_canonical_doc(pages: dict[str, str], name: str) -> None:
    """Each page must link to canonical cost saving doc."""
    body = pages[name]
    assert "cost_saving_examples.md" in body, f"{name}: missing canonical doc link"


@pytest.mark.parametrize("name", TICK4_PAGES)
def test_page_expected_saving_in_body(pages: dict[str, str], name: str) -> None:
    """Each page must contain its expected saving amount."""
    body = pages[name]
    expected = EXPECTED_SAVINGS[name]
    formatted = f"¥{expected:,}"
    assert formatted in body, f"{name}: expected {formatted} in body"


@pytest.mark.parametrize("name", TICK4_PAGES)
def test_no_legacy_roi_arr_patterns(pages: dict[str, str], name: str) -> None:
    """No ROI/ARR/年¥/月¥XX patterns should appear (cost saving model only)."""
    body = pages[name]
    for pattern in LEGACY_ROI_PATTERNS:
        matches = re.findall(pattern, body)
        # exception: index.html may mention ¥3/req per FAQ etc -- those are not legacy
        assert not matches, f"{name}: legacy pattern {pattern!r} found {matches}"


@pytest.mark.parametrize("name", TICK4_PAGES)
def test_no_old_brand(pages: dict[str, str], name: str) -> None:
    """No legacy brand names should leak in."""
    body = pages[name]
    for pattern in OLD_BRAND_PATTERNS:
        assert not re.search(pattern, body), f"{name}: old brand {pattern!r} found"


@pytest.mark.parametrize("name", TICK4_PAGES)
def test_brand_jpcite_present(pages: dict[str, str], name: str) -> None:
    """jpcite brand must be present on every page."""
    body = pages[name]
    assert "jpcite" in body, f"{name}: brand 'jpcite' missing"


@pytest.mark.parametrize("name", TICK4_PAGES)
def test_html_structure_h1_h2_intact(pages: dict[str, str], name: str) -> None:
    """h1 must exist exactly once, h2 must exist (structure preserved)."""
    body = pages[name]
    h1_count = len(re.findall(r"<h1\b", body))
    h2_count = len(re.findall(r"<h2\b", body))
    assert h1_count == 1, f"{name}: expected exactly 1 <h1>, got {h1_count}"
    assert h2_count >= 1, f"{name}: expected >=1 <h2>, got {h2_count}"


@pytest.mark.parametrize("name", TICK4_PAGES)
def test_html_close_main_exactly_once(pages: dict[str, str], name: str) -> None:
    """</main> must appear exactly once (no double inject)."""
    body = pages[name]
    close_main = body.count("</main>")
    open_main = body.count("<main")
    assert close_main == 1, f"{name}: expected 1 </main>, got {close_main}"
    assert open_main >= 1, f"{name}: expected >=1 <main, got {open_main}"


@pytest.mark.parametrize("name", TICK4_PAGES)
def test_cost_saving_section_inside_main(pages: dict[str, str], name: str) -> None:
    """cost-title section must be inside <main>...</main>."""
    body = pages[name]
    close_main = body.find("</main>")
    cost_title = body.find('id="cost-title"')
    assert cost_title != -1, f"{name}: cost-title missing"
    assert cost_title < close_main, f"{name}: cost-title appears after </main>"


@pytest.mark.parametrize("name", TICK4_PAGES)
def test_no_llm_api_call_from_jpcite_side(pages: dict[str, str], name: str) -> None:
    """jpcite must not claim to call LLM API server-side."""
    body = pages[name]
    forbidden = ["jpcite が LLM API", "我々が LLM 推論", "jpcite サーバが Anthropic"]
    for phrase in forbidden:
        assert phrase not in body, f"{name}: forbidden LLM-call claim {phrase!r}"


def test_pricing_consistency_3_per_req() -> None:
    """All 14 pages must reference ¥3/req pricing somewhere."""
    for name in TICK4_PAGES:
        body = (AUDIENCES_DIR / name).read_text(encoding="utf-8")
        assert "¥3" in body, f"{name}: ¥3/req pricing not referenced"
