"""Canonical cost-saving SOT safety guard.

The canonical document is now a public-pricing safety source of truth. It
should preserve request-count examples and API-fee-delta math without reviving
legacy ROI, ratio, certainty, or business-outcome claims.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_PATH = REPO_ROOT / "docs" / "canonical" / "cost_saving_examples.md"
PUBLIC_EXAMPLES_PATH = REPO_ROOT / "site" / "tools" / "cost_saving_examples.md"


@pytest.fixture(scope="module")
def canonical_text() -> str:
    if not CANONICAL_PATH.exists():
        pytest.skip("canonical cost saving SOT is optional in this checkout")
    return CANONICAL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def public_examples_text() -> str:
    assert PUBLIC_EXAMPLES_PATH.exists(), f"public examples missing: {PUBLIC_EXAMPLES_PATH}"
    return PUBLIC_EXAMPLES_PATH.read_text(encoding="utf-8")


def test_canonical_is_api_fee_delta_sot(canonical_text: str) -> None:
    assert "# jpcite API Fee Delta Examples" in canonical_text
    assert "API fee delta under a stated baseline" in canonical_text
    assert "Provider Comparison Baseline" in canonical_text
    assert "Public-Copy Rules" in canonical_text


def test_canonical_formula_is_provider_fee_minus_jpcite_fee(canonical_text: str) -> None:
    for required in (
        "external_api_fee",
        "jpcite_fee = jpcite_billable_units * ¥3",
        "api_fee_delta = external_api_fee - jpcite_fee",
    ):
        assert required in canonical_text


def test_canonical_keeps_six_reference_rows(canonical_text: str) -> None:
    rows = re.findall(r"^\| [1-6] \|", canonical_text, flags=re.MULTILINE)
    assert len(rows) == 6
    for expected in ("¥136.50", "¥96.75", "¥76.50", "¥104.25", "¥51.00", "¥63.00"):
        assert expected in canonical_text


def test_legacy_sot_claims_not_preserved(canonical_text: str) -> None:
    for forbidden in (
        "¥300/req",
        "99.00%",
        "ADDENDUM Cost saving",
        "Wave 46 tick5",
        "legacy ROI",
    ):
        assert forbidden not in canonical_text


def test_public_examples_reference_the_same_safe_baseline(
    canonical_text: str, public_examples_text: str
) -> None:
    for required in ("Claude Sonnet 4.5", "Anthropic web search", "USD/JPY=150", "¥3"):
        assert required in canonical_text
        assert required in public_examples_text
    assert "planning references only" in public_examples_text
    assert "business outcome, revenue, profit" in public_examples_text
