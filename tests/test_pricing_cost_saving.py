"""Wave 46 tick#3: pricing / compare cost-saving page parity.

Verifies that site/pricing.html and site/compare.html present the
"cost saving" framing introduced in Wave 46 tick#3 and that the per-use-case
savings advertised on the page match docs/canonical/cost_saving_examples.md.

Anti-pattern guards:
    * No "ROI", "ARR", or "射程" framing remains on the redesigned pages.
    * Six canonical use cases are present on the pricing page with the
      expected monthly saving amounts.
    * compare.html row 6 mentions the saving range and the canonical doc.
    * Brand string is consistently "jpcite" (no legacy 税務会計AI / AutonoMath /
      zeimu-kaikei.ai in body copy on the redesigned pages).

The test is intentionally offline / read-only — no LLM API, no network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PRICING_PATH = REPO_ROOT / "site" / "pricing.html"
COMPARE_PATH = REPO_ROOT / "site" / "compare.html"
DOC_PATH = REPO_ROOT / "docs" / "canonical" / "cost_saving_examples.md"

# Each tuple = (use case keyword regex on pricing page, expected ¥ monthly saving)
EXPECTED_SAVINGS: list[tuple[str, str]] = [
    (r"税理士\s*顧問先月次レビュー\s*\(50\s*社\)", "¥15,300"),
    (r"M&amp;A\s*advisor\s*公開情報\s*DD\s*\(月\s*10\s*deck\)", "¥19,200"),
    (r"信金\s*制度マッチ\s*pre-screen\s*\(月\s*200\s*件\)", "¥13,600"),
    (r"中小企業診断士\s*申請戦略パック\s*\(月\s*30\s*案件\)", "¥9,000"),
    (r"BPO\s*1000\s*案件\s*triage\s*\(月\s*4\s*batch\s*×\s*250\)", "¥39,000"),
    (r"行政書士\s*補助金前リサーチ\s*\(月\s*80\s*件\)", "¥8,160"),
]


@pytest.fixture(scope="module")
def pricing_html() -> str:
    return PRICING_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def compare_html() -> str:
    return COMPARE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def doc_md() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_canonical_doc_exists() -> None:
    assert DOC_PATH.exists(), "docs/canonical/cost_saving_examples.md is required"
    assert DOC_PATH.stat().st_size > 1500, "doc must contain full 6-case breakdown"


def test_no_roi_arr_yarn_framing(pricing_html: str, compare_html: str) -> None:
    """Wave 46 tick#3: removed mention-bias framing must not return."""
    for label, body in (("pricing.html", pricing_html), ("compare.html", compare_html)):
        # Allow only structural / accessibility cruft. Direct strings forbidden.
        for forbidden in (r"\bROI\b", r"\bARR\b", "射程"):
            matches = re.findall(forbidden, body)
            assert not matches, f"{label}: forbidden term {forbidden!r} found {len(matches)}x"


def test_pricing_has_cost_saving_section(pricing_html: str) -> None:
    """Cost saving calculator section must be present on pricing page."""
    assert 'id="cost-saving-calc-title"' in pricing_html
    assert "Cost saving calculator" in pricing_html
    assert "純 LLM" in pricing_html
    assert "節約" in pricing_html


def test_pricing_use_case_savings_match_doc(pricing_html: str, doc_md: str) -> None:
    """Each of the 6 use cases must appear on pricing.html with the
    canonical saving amount that is also listed in the canonical doc."""
    for kw_regex, saving in EXPECTED_SAVINGS:
        pat = re.compile(kw_regex)
        assert pat.search(pricing_html), f"pricing.html missing use case regex: {kw_regex}"
        assert saving in pricing_html, f"pricing.html missing saving figure: {saving}"
        assert saving in doc_md, f"canonical doc missing saving figure: {saving}"


def test_compare_row_6_mentions_saving(compare_html: str) -> None:
    """compare.html row 6 (価格モデル) must reference the cost saving range
    and link to the canonical doc."""
    assert "節約" in compare_html
    assert "cost_saving_examples" in compare_html


def test_doc_has_6_use_cases(doc_md: str) -> None:
    """Canonical doc must list 6 distinct use case headers."""
    # Headings like `### case 1: ...` through `### case 6: ...`
    headings = re.findall(r"^###\s*case\s*\d+:", doc_md, flags=re.MULTILINE)
    assert len(headings) == 6, f"expected 6 case sections, got {len(headings)}"


def test_brand_consistency(pricing_html: str, compare_html: str) -> None:
    """Wave 46 brand discipline: only 'jpcite' in the body of redesigned
    pages (legacy brand markers must stay out of consumer-facing copy)."""
    for label, body in (("pricing.html", pricing_html), ("compare.html", compare_html)):
        assert "jpcite" in body
        for legacy in ("税務会計AI", "AutonoMath", "zeimu-kaikei.ai"):
            assert legacy not in body, f"{label}: legacy brand leak: {legacy}"


def test_unit_price_constant(pricing_html: str, compare_html: str) -> None:
    """¥3/req metering remains the only published price model."""
    for label, body in (("pricing.html", pricing_html), ("compare.html", compare_html)):
        assert "¥3" in body, f"{label}: unit price ¥3 missing"
        assert "従量" in body, f"{label}: 従量 wording missing"


def test_pricing_html_structurally_intact(pricing_html: str) -> None:
    """Smoke check: hero, calc, examples, paid sections must all be present."""
    for anchor in (
        'id="cost-examples-title"',
        'id="cost-saving-calc-title"',
        'id="vs-websearch-title"',
        'id="break-even-title"',
        'id="api-paid"',
    ):
        assert anchor in pricing_html, f"section anchor {anchor} missing"


def test_compare_table_intact(compare_html: str) -> None:
    """Compare table 14 rows + 8 columns layout must remain intact."""
    # Eight columns: jpcite + 7 competitors.
    assert compare_html.count('<th scope="col"') >= 9
    # 14 axes — feature row index labels.
    for n in range(1, 15):
        prefix = f">{n}. "
        assert prefix in compare_html, f"row {n} of feature table missing"
