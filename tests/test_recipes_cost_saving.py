"""Recipe pricing-copy guards for API-fee-delta framing.

Verifies that all 21 `docs/recipes/r*` recipes that previously carried
"ROI 倍率 / ARR 射程" framing on their billable_units 試算 section have been
migrated to the **API fee delta** framing that is consistent with
`docs/canonical/cost_saving_examples.md`.

Anti-pattern guards:
    * Each of the 21 target recipes contains exactly one "API fee delta:" line.
    * No raw "ROI:" prefix remains on any recipe billable_units list.
    * Each migrated line cross-references the canonical doc path.
    * Brand string is consistently "jpcite" (no legacy 税務会計AI /
      AutonoMath / zeimu-kaikei.ai leak in any recipe body).
    * Existing recipe body anchor / heading structure intact (billable_units
      heading present and reachable).

The test is intentionally offline / read-only — no LLM API, no network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPES_ROOT = REPO_ROOT / "docs" / "recipes"
CANONICAL_DOC = REPO_ROOT / "docs" / "canonical" / "cost_saving_examples.md"

# 21 recipes flagged in docs/research/wave46/INVENTORY_roi_expression.md §4.
TARGET_RECIPES: tuple[str, ...] = (
    "r01-tax-firm-monthly-review",
    "r02-pre-closing-subsidy-check",
    "r03-sme-ma-public-dd",
    "r04-shinkin-borrower-watch",
    "r05-gyosei-licensing-eligibility",
    "r06-sharoushi-grant-match",
    "r07-shindanshi-monthly-companion",
    "r08-benrishi-ip-grant-monitor",
    "r09-bpo-grant-triage-1000",
    "r10-cci-municipal-screen",
    "r11-ec-invoice-bulk-verify",
    "r12-audit-firm-kyc-sweep",
    "r13-shihoshoshi-registry-watch",
    "r14-public-bid-watch",
    "r15-grant-saas-internal-enrich",
    "r24-houjin-6source-join",
    "r25-adoption-bulk-export",
    "r27-law-amendment-program-link",
    "r28-edinet-program-trigger",
    "r29-municipal-grant-monitor",
    "r30-invoice-revoke-watch",
)

COST_LINE_REGEX = re.compile(r"^-\s*API fee delta:", re.MULTILINE)
ROI_PREFIX_REGEX = re.compile(r"^-\s*ROI:\s", re.MULTILINE)
LEGACY_BRAND_REGEX = re.compile(r"税務会計AI|AutonoMath|zeimu-kaikei\.ai")
CANONICAL_REF_REGEX = re.compile(r"docs/canonical/cost_saving_examples\.md")
BILLABLE_UNITS_HEADING_REGEX = re.compile(r"^##\s*billable_units\s+試算", re.MULTILINE)


def _read(name: str) -> str:
    path = RECIPES_ROOT / name / "index.md"
    assert path.exists(), f"recipe not found: {path}"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def canonical_text() -> str:
    assert CANONICAL_DOC.exists(), f"canonical SOT missing: {CANONICAL_DOC}"
    return CANONICAL_DOC.read_text(encoding="utf-8")


@pytest.mark.parametrize("recipe", TARGET_RECIPES)
def test_recipe_has_cost_saving_line(recipe: str) -> None:
    text = _read(recipe)
    hits = COST_LINE_REGEX.findall(text)
    assert len(hits) == 1, f"{recipe}: expected exactly 1 'API fee delta:' line, found {len(hits)}"


@pytest.mark.parametrize("recipe", TARGET_RECIPES)
def test_recipe_no_roi_prefix(recipe: str) -> None:
    text = _read(recipe)
    hits = ROI_PREFIX_REGEX.findall(text)
    assert hits == [], (
        f"{recipe}: '- ROI:' prefix is forbidden after Wave 46 tick#3 "
        f"migration, found {len(hits)} occurrence(s)"
    )


@pytest.mark.parametrize("recipe", TARGET_RECIPES)
def test_recipe_references_canonical_doc(recipe: str) -> None:
    text = _read(recipe)
    assert CANONICAL_REF_REGEX.search(text), (
        f"{recipe}: must cross-reference 'docs/canonical/cost_saving_examples.md'"
    )


@pytest.mark.parametrize("recipe", TARGET_RECIPES)
def test_recipe_brand_jpcite_consistent(recipe: str) -> None:
    text = _read(recipe)
    legacy = LEGACY_BRAND_REGEX.findall(text)
    assert legacy == [], (
        f"{recipe}: legacy brand leak detected ({legacy}); brand must remain "
        f"'jpcite' across recipe body"
    )


@pytest.mark.parametrize("recipe", TARGET_RECIPES)
def test_recipe_structure_intact(recipe: str) -> None:
    text = _read(recipe)
    assert BILLABLE_UNITS_HEADING_REGEX.search(text), (
        f"{recipe}: '## billable_units 試算' heading missing or renamed; "
        f"structural anchor must be preserved"
    )


def test_canonical_doc_exists(canonical_text: str) -> None:
    assert "API fee delta" in canonical_text
    assert "business outcome" in canonical_text
    assert "¥3/req" in canonical_text


def test_all_21_target_recipes_present() -> None:
    missing = [name for name in TARGET_RECIPES if not (RECIPES_ROOT / name / "index.md").exists()]
    assert missing == [], f"missing recipes: {missing}"
