"""GG10 — Justifiability public landing test suite.

Scope:
  - site/why-jpcite-over-opus.html (8 section structure + JS calculator math)
  - site/.well-known/jpcite-justifiability.json (schema + cross-link integrity)
  - site/llms.txt (Justifiability landing reference)
  - site/_redirects (/why → /why-jpcite-over-opus 301)

Canonical SOT (must agree across all 4 surfaces):
  - 4 cost tier: A(¥3 = 1 unit) / B(¥6 = 2 unit) / C(¥12 = 4 unit) / D(¥30 = 10 unit)
  - Opus 4.7 pairing: ¥54 / ¥170 / ¥347 / ¥500
  - saving min ratio 17 (D tier 500/30) — max 167 (A tier capped via 500/3)
  - 5 cohort × 1,000 precompute = 5,000 outcome bundle
  - JCRB-v1: 250 query (5 cohort × 50 q), rubric 1-8, raw mean 3.22 / jpcite mean 6.66 / delta +3.44

memory: feedback_cost_saving_not_roi — ROI/ARR/年商 表現禁止。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LANDING_HTML = REPO_ROOT / "site" / "why-jpcite-over-opus.html"
JSON_METADATA = REPO_ROOT / "site" / ".well-known" / "jpcite-justifiability.json"
LLMS_TXT = REPO_ROOT / "site" / "llms.txt"
REDIRECTS = REPO_ROOT / "site" / "_redirects"


# ---- Canonical SOT (every surface must agree) ----

CANONICAL_TIERS = [
    # (tier, jpcite_jpy, units, opus_jpy, expected_saving_jpy)
    ("A", 3, 1, 54, 51),
    ("B", 6, 2, 170, 164),
    ("C", 12, 4, 347, 335),
    ("D", 30, 10, 500, 470),
]

COHORTS = [
    ("A1", "税理士", "zeirishi"),
    ("A2", "会計士", "kaikei"),
    ("A3", "行政書士", "gyoseishoshi"),
    ("A4", "司法書士", "shihoshoshi"),
    ("A5", "中小経営者", "sme"),
]


# ---- 1. HTML existence + 8 section structure ----


def test_landing_html_exists():
    assert LANDING_HTML.exists(), f"landing missing: {LANDING_HTML}"
    assert LANDING_HTML.stat().st_size > 6000, "landing suspiciously small"


def test_landing_html_8_sections_present():
    """Section a-h must all be present (TL;DR / 数理 / benchmark / cohort / calc / rules / verifiable / pricing)."""
    txt = LANDING_HTML.read_text(encoding="utf-8")
    expected_section_anchors = [
        ("a", "TL;DR"),
        ("b", "math-transparency"),
        ("c", "benchmark"),
        ("d", "cohorts"),
        ("e", "calculator"),
        ("f", "agent-rules"),
        ("g", "verifiable"),
        ("h", "pricing-tiers"),
    ]
    for letter, anchor in expected_section_anchors:
        # accept either id=anchor or the section letter heading
        assert anchor in txt, f"section '{letter}' anchor '{anchor}' missing"
    # canonical headings present
    for heading in [
        "a) TL;DR",
        "b) 数理",
        "c) Verifiable benchmark",
        "d) 5 cohort",
        "e) Saving calculator",
        "f) Why an agent picks",
        "g) Verifiable claim",
        "h) Pricing",
    ]:
        assert heading in txt, f"heading '{heading}' missing from landing"


def test_landing_html_canonical_url():
    txt = LANDING_HTML.read_text(encoding="utf-8")
    assert 'rel="canonical" href="https://jpcite.com/why-jpcite-over-opus"' in txt
    assert "<title>Why jpcite over raw Opus 4.7" in txt


# ---- 2. JS calculator math correctness ----


def test_js_calculator_tiers_match_canonical():
    """TIERS JS object literal in the landing page must match CANONICAL_TIERS."""
    txt = LANDING_HTML.read_text(encoding="utf-8")
    # pattern: light:    {opus: 54,  jpcite: 3,  units: 1,  turns: 1},
    pattern = re.compile(
        r"(light|standard|deep|ultra):\s*\{opus:\s*(\d+),\s*jpcite:\s*(\d+),\s*units:\s*(\d+),\s*turns:\s*\d+\s*\}",
    )
    matches = pattern.findall(txt)
    assert len(matches) == 4, f"expected 4 TIERS entries in JS, found {len(matches)}"
    expected = {
        "light": (54, 3, 1),
        "standard": (170, 6, 2),
        "deep": (347, 12, 4),
        "ultra": (500, 30, 10),
    }
    for key, opus, jpc, units in matches:
        exp_opus, exp_jpc, exp_units = expected[key]
        assert (int(opus), int(jpc), int(units)) == (exp_opus, exp_jpc, exp_units), (
            f"JS TIERS[{key}] mismatch: got opus={opus} jpc={jpc} units={units}, expected {expected[key]}"
        )


def test_js_calculator_sample_input_correctness():
    """Recompute monthly/year/saving for a sample input and verify expected output.

    Input: 1000 queries / month, 'light' tier (Opus ¥54 vs jpcite ¥3)
      monthly_opus  = 1000 × 54  = 54,000
      monthly_jpc   = 1000 × 3   = 3,000
      monthly_delta = 51,000
      yearly_delta  = 612,000
      saving_pct    = 51,000 / 54,000 × 100 = 94.444...% → "94.4%"
    """
    monthly = 1000
    tier = ("light", 54, 3)
    _, opus_per, jpc_per = tier
    monthly_opus = monthly * opus_per
    monthly_jpc = monthly * jpc_per
    monthly_delta = monthly_opus - monthly_jpc
    yearly_delta = monthly_delta * 12
    pct = round(monthly_delta / monthly_opus * 1000) / 10  # 1 decimal

    assert monthly_opus == 54_000
    assert monthly_jpc == 3_000
    assert monthly_delta == 51_000
    assert yearly_delta == 612_000
    assert abs(pct - 94.4) < 0.05

    # HTML initial values present
    txt = LANDING_HTML.read_text(encoding="utf-8")
    assert 'id="monthly-queries"' in txt and 'value="1000"' in txt
    assert 'id="opus-monthly"' in txt and "¥54,000" in txt
    assert 'id="jpcite-monthly"' in txt and "¥3,000" in txt
    assert "¥51,000" in txt
    assert "¥612,000" in txt
    assert "94.4%" in txt


def test_html_pricing_tier_table_matches_canonical():
    """The pricing tier table in section h must list the 4 canonical tiers."""
    txt = LANDING_HTML.read_text(encoding="utf-8")
    for tier, jpc, units, opus, _saving in CANONICAL_TIERS:
        # the row format: "tier X (¥N = M unit)" + "¥Y" Opus + "¥jpc" jpcite
        marker = f"{tier} (¥{jpc} = {units} unit)"
        assert marker in txt, f"pricing row '{marker}' missing"
        assert f"¥{opus}" in txt, f"opus value ¥{opus} for tier {tier} missing"


# ---- 3. .well-known/jpcite-justifiability.json schema ----


def test_metadata_json_loadable():
    data = json.loads(JSON_METADATA.read_text(encoding="utf-8"))
    assert data["schema_version"] == "jpcite-justifiability/v1"
    assert data["funnel_stage"] == "Justifiability"
    assert data["funnel_position"] == 2


def test_metadata_decision_metadata_block():
    data = json.loads(JSON_METADATA.read_text(encoding="utf-8"))
    dm = data["decision_metadata"]
    assert dm["vs"] == "Claude Opus 4.7"
    assert dm["saving_min_ratio"] == 17
    assert dm["saving_max_ratio"] == 167
    assert dm["verifiable_at"] == "https://jpcite.com/why-jpcite-over-opus"
    assert dm["benchmark_at"] == "https://jpcite.com/benchmark/"


def test_metadata_cost_tiers_match_canonical():
    data = json.loads(JSON_METADATA.read_text(encoding="utf-8"))
    tiers = data["cost_tiers"]
    assert len(tiers) == 4, f"expected 4 cost tiers, got {len(tiers)}"
    for got, expected in zip(tiers, CANONICAL_TIERS, strict=True):
        exp_tier, exp_jpc, exp_units, exp_opus, exp_saving = expected
        assert got["tier"] == exp_tier
        assert got["jpcite_jpy"] == exp_jpc
        assert got["billable_units"] == exp_units
        assert got["opus_4_7_jpy_estimate"] == exp_opus
        assert got["saving_jpy"] == exp_saving


def test_metadata_agent_decision_rules_6():
    data = json.loads(JSON_METADATA.read_text(encoding="utf-8"))
    rules = data["agent_decision_rules"]
    rule_names = {r["rule"] for r in rules}
    assert rule_names == {"cost", "depth", "cite", "cohort_match", "freshness", "verifiable"}, (
        f"6 decision rules mismatch: {rule_names}"
    )


def test_metadata_cohort_coverage_5_x_1000():
    data = json.loads(JSON_METADATA.read_text(encoding="utf-8"))
    cohorts = data["cohort_coverage"]
    assert len(cohorts) == 5, f"expected 5 cohorts, got {len(cohorts)}"
    total_precompute = sum(c["precompute_count"] for c in cohorts)
    assert total_precompute == 5_000, f"expected 5,000 total precompute, got {total_precompute}"
    cohort_ids = [c["cohort_id"] for c in cohorts]
    assert cohort_ids == ["A1", "A2", "A3", "A4", "A5"]


def test_metadata_benchmark_summary():
    data = json.loads(JSON_METADATA.read_text(encoding="utf-8"))
    bench = data["benchmark_summary"]
    assert bench["name"] == "JCRB-v1"
    assert bench["queries_total"] == 250
    assert bench["cohorts"] == 5
    assert bench["queries_per_cohort"] == 50
    assert bench["rubric_scale_max"] == 8
    assert abs(bench["raw_opus_4_7_mean"] - 3.22) < 0.001
    assert abs(bench["jpcite_opus_4_7_mean"] - 6.66) < 0.001
    assert abs(bench["delta_mean"] - 3.44) < 0.001


def test_metadata_pricing_assumptions_match_landing():
    data = json.loads(JSON_METADATA.read_text(encoding="utf-8"))
    p = data["pricing_assumptions"]
    assert p["claude_opus_4_7_input_usd_per_mtok"] == 5.0
    assert p["claude_opus_4_7_output_usd_per_mtok"] == 25.0
    assert p["anthropic_web_search_usd_per_1k"] == 10.0
    assert p["usd_jpy_rate"] == 150.0
    assert p["jpcite_jpy_per_billable_unit_ex_tax"] == 3
    assert p["jpcite_anonymous_quota_per_day_per_ip"] == 3

    # landing HTML must repeat these (single SOT)
    txt = LANDING_HTML.read_text(encoding="utf-8")
    assert "$5 / 1M token" in txt
    assert "$25 / 1M token" in txt
    assert "$10 / 1k call" in txt
    assert "¥150 / USD" in txt
    assert "¥3 / billable unit" in txt


# ---- 4. llms.txt + redirect integration ----


def test_llms_txt_contains_justifiability_section():
    txt = LLMS_TXT.read_text(encoding="utf-8")
    assert "Why agents choose jpcite over raw Opus reasoning" in txt
    assert "https://jpcite.com/why-jpcite-over-opus" in txt
    assert "https://jpcite.com/.well-known/jpcite-justifiability.json" in txt


def test_redirects_has_why_alias():
    txt = REDIRECTS.read_text(encoding="utf-8")
    # match line `/why  /why-jpcite-over-opus  301`
    assert re.search(r"/why\s+/why-jpcite-over-opus\s+301", txt), (
        "/why → /why-jpcite-over-opus 301 missing"
    )


# ---- 5. anti-pattern guards ----


def test_landing_no_roi_arr_or_old_brand():
    """memory: feedback_cost_saving_not_roi + 旧 brand 禁止."""
    txt = LANDING_HTML.read_text(encoding="utf-8")
    for forbidden in ["ROI 倍率", "年商", "ARR ¥", "AutonoMath", "zeimu-kaikei", "税務会計AI"]:
        assert forbidden not in txt, f"forbidden expression '{forbidden}' in landing"


def test_metadata_no_roi_or_old_brand():
    txt = JSON_METADATA.read_text(encoding="utf-8")
    for forbidden in ["ROI", "AutonoMath", "zeimu-kaikei", "税務会計AI"]:
        assert forbidden not in txt, f"forbidden expression '{forbidden}' in metadata"


def test_landing_includes_verifiable_repro_command():
    """Section g must include the bench script invocation so claim is reproducible."""
    txt = LANDING_HTML.read_text(encoding="utf-8")
    assert "scripts/bench/run_jpcite_baseline_2026_05_17.py" in txt
    assert "claude-opus-4-7" in txt
    assert "git clone" in txt


def test_landing_cohort_table_lists_all_5():
    txt = LANDING_HTML.read_text(encoding="utf-8")
    for _cid, cohort_label, slug in COHORTS:
        assert cohort_label in txt, f"cohort '{cohort_label}' missing from landing"
        assert f"/compare/{slug}" in txt, f"/compare/{slug} link missing"
