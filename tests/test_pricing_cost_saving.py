"""Public pricing language guards for API-fee-delta comparisons.

The pricing page and calculator may compare jpcite fees with external model
provider fees only as an API fee delta under an explicit baseline. These tests
intentionally avoid legacy business-value assertions.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PRICING_PATH = REPO_ROOT / "site" / "pricing.html"
CALCULATOR_PATH = REPO_ROOT / "site" / "tools" / "cost_saving_calculator.html"
EXAMPLES_PATH = REPO_ROOT / "site" / "tools" / "cost_saving_examples.md"
CANONICAL_PATH = REPO_ROOT / "docs" / "canonical" / "cost_saving_examples.md"

PUBLIC_PATHS = {
    "pricing.html": PRICING_PATH,
    "cost_saving_calculator.html": CALCULATOR_PATH,
    "cost_saving_examples.md": EXAMPLES_PATH,
    "canonical cost_saving_examples.md": CANONICAL_PATH,
}

UNSAFE_PUBLIC_PATTERNS = (
    re.compile(r"\bROI\b"),
    re.compile(r"\bARR\b"),
    re.compile(r"99(?:\.00)?%"),
    re.compile(r"~\s*10x|\b10x\b", re.IGNORECASE),
    re.compile(r"\bguarantee[sd]?\b", re.IGNORECASE),
    re.compile(r"保証"),
    re.compile(r"hallucination-0", re.IGNORECASE),
    re.compile(r"\bno[- ]miss\b", re.IGNORECASE),
    re.compile(r"取りこぼし|機会損失|顧問契約解除"),
    re.compile(r"profit\s+(?:uplift|increase|growth)", re.IGNORECASE),
    re.compile(r"revenue\s+(?:uplift|increase|growth)", re.IGNORECASE),
    re.compile(r"利益\s*(?:向上|増加|改善|アップ)"),
    re.compile(r"売上\s*(?:向上|増加|改善|アップ)"),
)


@pytest.fixture(scope="module")
def public_texts() -> dict[str, str]:
    texts: dict[str, str] = {}
    for label, path in PUBLIC_PATHS.items():
        assert path.exists(), f"required public pricing file missing: {path}"
        texts[label] = path.read_text(encoding="utf-8")
    return texts


def test_public_pricing_copy_avoids_unsafe_claims(public_texts: dict[str, str]) -> None:
    for label, text in public_texts.items():
        for pattern in UNSAFE_PUBLIC_PATTERNS:
            assert not pattern.search(text), f"{label}: unsafe pricing claim {pattern.pattern!r}"


def test_provider_comparison_is_api_fee_delta_only(public_texts: dict[str, str]) -> None:
    for label in (
        "pricing.html",
        "cost_saving_calculator.html",
        "cost_saving_examples.md",
        "canonical cost_saving_examples.md",
    ):
        text = public_texts[label]
        assert "API fee delta" in text or "API 料金差額" in text, (
            f"{label}: provider comparison must use API fee delta framing"
        )
        assert "売上" in text or "revenue" in text, f"{label}: revenue exclusion missing"
        assert "利益" in text or "profit" in text, f"{label}: profit exclusion missing"
        assert "含みません" in text or "excludes" in text or "must not present" in text, (
            f"{label}: explicit exclusion wording missing"
        )


def test_stated_baseline_is_near_public_comparisons(public_texts: dict[str, str]) -> None:
    for label in (
        "pricing.html",
        "cost_saving_calculator.html",
        "cost_saving_examples.md",
        "canonical cost_saving_examples.md",
    ):
        text = public_texts[label]
        for required in ("Claude Sonnet 4.5", "Anthropic web search", "USD/JPY=150", "¥3"):
            assert required in text, f"{label}: stated baseline missing {required!r}"


def test_pricing_page_uses_safe_comparison_section(public_texts: dict[str, str]) -> None:
    pricing_html = public_texts["pricing.html"]
    assert "API 料金差額の参考比較" in pricing_html
    assert "外部 provider の token + search API fee" in pricing_html
    assert "API fee delta <strong>¥477</strong>" in pricing_html
    assert "~10x" not in pricing_html


def test_calculator_labels_are_delta_not_business_outcome(public_texts: dict[str, str]) -> None:
    calc_html = public_texts["cost_saving_calculator.html"]
    assert "<h1>jpcite Evidence Packet cost calculator</h1>" in calc_html
    assert "API fee delta" in calc_html
    assert "external API fee" in calc_html
    assert "Evidence Packet / Company Folder Brief fee" in calc_html
    assert "月次 API fee delta" in calc_html
    assert "労務削減" in calc_html and "含みません" in calc_html


def test_canonical_delta_numbers_match_pricing(public_texts: dict[str, str]) -> None:
    pricing_html = public_texts["pricing.html"]
    canonical_md = public_texts["canonical cost_saving_examples.md"]
    for expected in ("¥528", "¥51", "¥477", "¥7,050", "¥84,600"):
        assert expected in pricing_html, f"pricing.html missing {expected}"
        assert expected in canonical_md, f"canonical doc missing {expected}"


def test_unit_price_and_structural_anchors(public_texts: dict[str, str]) -> None:
    pricing_html = public_texts["pricing.html"]
    calc_html = public_texts["cost_saving_calculator.html"]

    for required in ("¥3", "¥3.30", "billable unit", "従量"):
        assert required in pricing_html, f"pricing.html missing unit price marker {required!r}"
    for anchor in (
        'id="cost-examples-title"',
        'id="structure-vs-websearch-title"',
        'id="break-even-title"',
        'id="api-paid"',
    ):
        assert anchor in pricing_html, f"pricing.html missing section anchor {anchor}"
    assert 'id="cases-tbl"' in calc_html
