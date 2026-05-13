"""Audience page guards for API-fee-delta framing.

The audience pages may compare external provider fees with jpcite fees only
as an API fee delta under explicit assumptions. They must not present labor,
revenue, profit, or business-outcome savings as calculated product claims.
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

AUDIENCE_CASES: list[tuple[str, Path, str]] = [
    ("ma_advisor", MA_PATH, "¥14,850/deal"),
    ("cpa_firm", CPA_PATH, "¥148,500/月"),
    ("shindanshi", SHIN_PATH, "¥89,100/月"),
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
    assert DOC_PATH.stat().st_size > 1500, "doc must contain full breakdown"


def test_no_roi_arr_yarn_framing(ma_html: str, cpa_html: str, shin_html: str) -> None:
    for label, body in (
        ("ma_advisor.html", ma_html),
        ("cpa_firm.html", cpa_html),
        ("shindanshi.html", shin_html),
    ):
        for forbidden in (r"\bROI\b", r"\bARR\b", "射程"):
            matches = re.findall(forbidden, body)
            assert not matches, f"{label}: forbidden term {forbidden!r} found {len(matches)}x"


def test_each_page_has_api_fee_delta_section(ma_html: str, cpa_html: str, shin_html: str) -> None:
    bodies = {
        "ma_advisor.html": ma_html,
        "cpa_firm.html": cpa_html,
        "shindanshi.html": shin_html,
    }
    for label, body in bodies.items():
        assert 'id="cost-saving-title"' in body, f"{label}: missing cost-saving-title anchor"
        assert "API fee delta reference" in body, (
            f"{label}: missing 'API fee delta reference' heading"
        )
        assert "外部 API fee baseline" in body, f"{label}: missing external API fee baseline label"
        assert "API fee delta" in body, f"{label}: missing API fee delta column"


def test_each_page_delta_amount_present_and_canonical_doc_is_safe(
    doc_md: str, ma_html: str, cpa_html: str, shin_html: str
) -> None:
    bodies = {
        "ma_advisor.html": ma_html,
        "cpa_firm.html": cpa_html,
        "shindanshi.html": shin_html,
    }
    for label, _path, delta in AUDIENCE_CASES:
        body = bodies[f"{label}.html"]
        assert delta in body, f"{label}.html: missing canonical API fee delta figure: {delta}"
    assert "API fee delta" in doc_md
    assert "¥3/req" in doc_md
    assert "business outcome" in doc_md


def test_each_page_links_to_public_cost_saving_doc(
    ma_html: str, cpa_html: str, shin_html: str
) -> None:
    bodies = {
        "ma_advisor.html": ma_html,
        "cpa_firm.html": cpa_html,
        "shindanshi.html": shin_html,
    }
    for label, body in bodies.items():
        assert "/tools/cost_saving_examples.md" in body, (
            f"{label}: missing link to public API fee delta doc"
        )


def test_brand_consistency(ma_html: str, cpa_html: str, shin_html: str) -> None:
    bodies = {
        "ma_advisor.html": ma_html,
        "cpa_firm.html": cpa_html,
        "shindanshi.html": shin_html,
    }
    for label, body in bodies.items():
        assert "jpcite" in body, f"{label}: jpcite brand missing"
        for legacy in ("税務会計AI", "AutonoMath", "zeimu-kaikei.ai"):
            assert legacy not in body, f"{label}: legacy brand leak: {legacy}"


def test_unit_price_constant(ma_html: str, cpa_html: str, shin_html: str) -> None:
    bodies = {
        "ma_advisor.html": ma_html,
        "cpa_firm.html": cpa_html,
        "shindanshi.html": shin_html,
    }
    for label, body in bodies.items():
        assert "¥3" in body, f"{label}: unit price ¥3 missing"
        assert "従量" in body, f"{label}: 従量 wording missing"


def test_structural_anchors_intact(ma_html: str, cpa_html: str, shin_html: str) -> None:
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


def test_html_parses_clean(ma_html: str, cpa_html: str, shin_html: str) -> None:
    from html.parser import HTMLParser

    class StrictParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.errors = 0

        def error(self, msg: str) -> None:  # pragma: no cover
            self.errors += 1

    for label, body in (
        ("ma_advisor.html", ma_html),
        ("cpa_firm.html", cpa_html),
        ("shindanshi.html", shin_html),
    ):
        p = StrictParser()
        p.feed(body)
        assert p.errors == 0, f"{label}: HTML parser raised {p.errors} errors"


def test_each_page_h2_count_preserved(ma_html: str, cpa_html: str, shin_html: str) -> None:
    for label, body in (
        ("ma_advisor.html", ma_html),
        ("cpa_firm.html", cpa_html),
        ("shindanshi.html", shin_html),
    ):
        h2_count = len(re.findall(r"<h2\b", body))
        assert h2_count == 4, (
            f"{label}: expected 4 h2 elements (fence/cost-saving/install/cta), got {h2_count}"
        )
