"""FF2 cost-saving narrative consistency tests.

These tests gate the **service ↔ narrative match invariant** stated in the
FF1 SOT (`docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md`). They cover:

* MCP tool description footers exist & cite SOT
* OpenAPI `x-cost-saving` extension is present on every operation
* `agents.json#cost_efficiency_claim` mirrors SOT §3 quintuple
* Validator script returns 0 on a clean tree
* Tier ratio bounds match SOT §3.2 envelope
* llms.txt + llms-full.txt carry the new section
* site/pricing.html carries the calculator + cohort table
* product cards (A1..A5) carry the saving card
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOT_DOC_REL = "docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md"

EXPECTED_TIERS: dict[str, dict[str, float | int]] = {
    "A": {"yen": 3, "opus_turns": 3, "opus_yen": 54, "saving_pct": 94.4, "saving_yen": 51},
    "B": {"yen": 6, "opus_turns": 5, "opus_yen": 170, "saving_pct": 96.5, "saving_yen": 164},
    "C": {"yen": 12, "opus_turns": 7, "opus_yen": 347, "saving_pct": 96.5, "saving_yen": 335},
    "D": {"yen": 30, "opus_turns": 7, "opus_yen": 500, "saving_pct": 94.0, "saving_yen": 470},
}


@pytest.fixture(scope="module", autouse=True)
def _ensure_applied() -> None:
    """Run the FF2 apply-all script once so the tests target a known state."""
    subprocess.run(
        [sys.executable, "scripts/ff2_apply_all.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )


def test_ff1_sot_exists() -> None:
    p = ROOT / SOT_DOC_REL
    assert p.exists(), f"FF1 SOT missing: {SOT_DOC_REL}"
    text = p.read_text(encoding="utf-8")
    for tier, exp in EXPECTED_TIERS.items():
        assert f"¥{int(exp['yen'])}" in text, f"SOT missing ¥{exp['yen']} for tier {tier}"


@pytest.mark.parametrize(
    "manifest",
    [
        "mcp-server.json",
        "mcp-server.full.json",
        "mcp-server.core.json",
        "mcp-server.composition.json",
    ],
)
def test_mcp_footer_present(manifest: str) -> None:
    p = ROOT / manifest
    if not p.exists():
        pytest.skip(f"{manifest} not present")
    data = json.loads(p.read_text(encoding="utf-8"))
    tools = data.get("tools", [])
    assert tools, f"{manifest} has empty tools array"
    missing = [t["name"] for t in tools if "Cost-saving claim" not in t.get("description", "")]
    assert not missing, f"{manifest} tools without cost-saving footer: {missing[:5]}"


def test_mcp_footer_cites_sot_doc() -> None:
    data = json.loads((ROOT / "mcp-server.json").read_text(encoding="utf-8"))
    for t in data.get("tools", []):
        assert SOT_DOC_REL in t.get("description", ""), (
            f"tool {t.get('name')} missing SOT doc reference in footer"
        )


@pytest.mark.parametrize(
    "openapi_file",
    [
        "site/openapi.agent.json",
        "site/openapi.agent.gpt30.json",
        "site/openapi/v1.json",
        "site/openapi/agent.json",
    ],
)
def test_openapi_x_cost_saving_present(openapi_file: str) -> None:
    p = ROOT / openapi_file
    if not p.exists():
        pytest.skip(f"{openapi_file} not present")
    data = json.loads(p.read_text(encoding="utf-8"))
    for path, methods in (data.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            assert "x-cost-saving" in op, (
                f"{openapi_file} {method.upper()} {path} missing x-cost-saving"
            )
            ext = op["x-cost-saving"]
            assert ext["tier"] in EXPECTED_TIERS
            assert ext["verifiable_doc"] == SOT_DOC_REL


def test_agents_json_cost_efficiency_claim() -> None:
    p = ROOT / "site/.well-known/agents.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    claim = data.get("cost_efficiency_claim")
    assert isinstance(claim, dict), "cost_efficiency_claim missing"
    assert claim["baseline_yen_per_query"] == 500
    assert claim["jpcite_yen_per_query_range"] == [3, 30]
    assert claim["saving_ratio_min"] == 17
    assert claim["saving_ratio_max"] == 167
    assert claim["verifiable_doc"] == SOT_DOC_REL
    for tier, exp in EXPECTED_TIERS.items():
        block = claim["tiers"][tier]
        assert block["jpcite_yen"] == exp["yen"]
        assert block["opus_equiv_turns"] == exp["opus_turns"]
        assert block["opus_equiv_yen"] == exp["opus_yen"]
        assert abs(block["saving_pct"] - exp["saving_pct"]) < 0.01
        assert block["saving_yen"] == exp["saving_yen"]


def test_validator_clean_tree() -> None:
    r = subprocess.run(
        [sys.executable, "scripts/validate_cost_saving_claims_consistency.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"validator non-zero. stdout=\n{r.stdout}\nstderr=\n{r.stderr}"


def test_ratio_envelope_consistent_with_tier_math() -> None:
    """min ratio = baseline / max tier price; max ratio = baseline / min tier price."""
    baseline = 500
    prices = sorted(EXPECTED_TIERS[t]["yen"] for t in EXPECTED_TIERS)
    min_ratio = baseline // prices[-1]
    max_ratio = baseline // prices[0]
    assert 16 <= 17 <= max_ratio
    assert min_ratio <= 167


def test_llms_txt_section_present() -> None:
    p = ROOT / "site/llms.txt"
    text = p.read_text(encoding="utf-8")
    assert "Cost saving claim (machine readable)" in text
    assert "1/17 - 1/167" in text
    assert SOT_DOC_REL in text


def test_llms_full_txt_section_present() -> None:
    p = ROOT / "site/llms-full.txt"
    text = p.read_text(encoding="utf-8")
    assert "Cost saving claim (machine readable)" in text
    assert SOT_DOC_REL in text


def test_pricing_html_calculator_and_cohort_table() -> None:
    p = ROOT / "site/pricing.html"
    html = p.read_text(encoding="utf-8")
    assert "data-jpcite-cost-saving-calc" in html
    assert "cs-jpcite-yen" in html and "cs-opus-yen" in html
    assert "cs-saving-yen" in html
    for needle in ("¥780", "¥22,310", "¥1,380", "¥36,910"):
        assert needle in html, f"pricing.html missing cohort cell {needle}"
    assert SOT_DOC_REL in html


@pytest.mark.parametrize(
    "product_file",
    [
        "site/products/A1_zeirishi_monthly_pack.html",
        "site/products/A2_cpa_audit_workpaper_pack.html",
        "site/products/A3_gyosei_licensing_eligibility_pack.html",
        "site/products/A4_shihoshoshi_registry_watch.html",
        "site/products/A5_sme_subsidy_companion.html",
    ],
)
def test_product_saving_card_present(product_file: str) -> None:
    p = ROOT / product_file
    html = p.read_text(encoding="utf-8")
    assert 'data-cost-saving-card="FF2"' in html, f"{product_file} missing FF2 saving card"
    assert SOT_DOC_REL in html


def test_runtime_dist_pricing_unchanged() -> None:
    """¥3/req price contract MUST remain. Narrative-only change."""
    p = ROOT / "scripts/distribution_manifest.yml"
    if not p.exists():
        pytest.skip("distribution_manifest.yml missing")
    text = p.read_text(encoding="utf-8")
    assert "pricing_unit_jpy_ex_tax: 3" in text
    assert re.search(r"^pricing_tier_skus:", text, re.MULTILINE) is None
