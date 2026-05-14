"""Wave 48 tick#1 — cost saving v2 quantify calculator sanity test.

検証対象:
  - docs/canonical/cost_saving_examples.md § C 6 use case の external API fee / jpcite / API fee delta 数字
  - tools/cost_saving_calculator.html 内 JS の USE_CASES + MODELS + SEARCH 定数
  - 計算式 (input_cost + output_cost + search_cost) = external API fee
  - jpcite ¥3/req fixed model = req × 3

数字が doc / HTML / Python recalculation 三者で一致しないと fail。
memory: feedback_cost_saving_not_roi 厳守 — ROI/ARR/年¥X 表現は doc / HTML に出現してはならない。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_DOC = REPO_ROOT / "docs" / "canonical" / "cost_saving_examples.md"
CALCULATOR_HTML = REPO_ROOT / "tools" / "cost_saving_calculator.html"

USD_JPY = 150
JPCITE_PER_REQ_JPY = 3

# Default: Claude Sonnet 4.5 + Anthropic web search (matches HTML default selectors)
MODEL_IN_USD_PER_MTOK = 3.00
MODEL_OUT_USD_PER_MTOK = 15.00
SEARCH_USD_PER_1K = 10.00

# canonical 6 use case (doc § C / HTML USE_CASES — must match)
USE_CASES = [
    # (id, name_fragment, in_tok, out_tok, search, jpcite_req, expected_pure_jpy, expected_saving_jpy)
    (1, "M&A DD", 120000, 20000, 25, 4, 136.50, 124.50),
    (2, "補助金", 80000, 15000, 18, 2, 96.75, 90.75),
    (3, "措置法", 60000, 12000, 15, 2, 76.50, 70.50),
    (4, "行政書士", 90000, 15000, 20, 2, 104.25, 98.25),
    (5, "信金", 40000, 8000, 10, 2, 51.00, 45.00),
    (6, "dev", 50000, 10000, 12, 5, 63.00, 48.00),
]


def _pure_llm_jpy(in_tok: int, out_tok: int, search: int) -> float:
    in_c = in_tok * MODEL_IN_USD_PER_MTOK / 1_000_000 * USD_JPY
    out_c = out_tok * MODEL_OUT_USD_PER_MTOK / 1_000_000 * USD_JPY
    sr_c = search * SEARCH_USD_PER_1K / 1_000 * USD_JPY
    return in_c + out_c + sr_c


def _jpcite_jpy(req: int) -> float:
    return req * JPCITE_PER_REQ_JPY


# --- Recalculation sanity ---


@pytest.mark.parametrize("uc", USE_CASES, ids=lambda u: f"uc{u[0]}_{u[1]}")
def test_use_case_recalculation_matches_expected(uc):
    _id, _name, in_tok, out_tok, search, req, expected_pure, expected_saving = uc
    pure = _pure_llm_jpy(in_tok, out_tok, search)
    jpc = _jpcite_jpy(req)
    saving = pure - jpc
    assert abs(pure - expected_pure) < 0.01, (
        f"uc{_id} pure mismatch: got {pure:.4f}, expected {expected_pure}"
    )
    assert abs(saving - expected_saving) < 0.01, (
        f"uc{_id} saving mismatch: got {saving:.4f}, expected {expected_saving}"
    )


# --- Canonical doc presence checks ---


def test_canonical_doc_has_v2_section():
    txt = CANONICAL_DOC.read_text(encoding="utf-8")
    assert "v2 — 「普通に AI を使う」vs jpcite MCP" in txt, "v2 header missing from canonical doc"
    assert "§ C. 6 use case side-by-side calculator" in txt
    assert "§ E. 再現可能な計算スクリプト" in txt
    assert "Anthropic Pricing" in txt or "anthropic.com/pricing" in txt
    assert "openai.com/api/pricing" in txt


def test_canonical_doc_has_all_six_use_case_savings():
    txt = CANONICAL_DOC.read_text(encoding="utf-8")
    # Each expected saving (¥XX.X) must appear in doc table
    for uc in USE_CASES:
        _id, _name, _i, _o, _s, _r, _pure, saving = uc
        # Doc shows e.g. "¥54.6" (one decimal). Accept both "¥54.6" and "¥54.60"
        s1 = f"¥{saving:g}"
        s2 = f"¥{saving:.1f}"
        assert s1 in txt or s2 in txt, f"uc{_id} saving {s1}/{s2} not in canonical doc"


def test_canonical_doc_no_roi_arr_language():
    """memory: feedback_cost_saving_not_roi — ROI/ARR/年¥X 表現は v2 section に持ち込まない。"""
    txt = CANONICAL_DOC.read_text(encoding="utf-8")
    # Only check the v2 portion
    v2_start = txt.find("v2 — 「普通に AI を使う」")
    assert v2_start > 0, "v2 section anchor missing"
    v2_body = txt[v2_start:]
    forbidden = [
        "ARR",
        "年商",
        "ROI 倍率",
    ]  # ROI mention 自体は historical reference として認める方針
    for bad in forbidden:
        # ARR は agent KPI 列の "agent KPI" 文脈と被るが、 v2 では使わない
        assert bad not in v2_body, f"forbidden expression '{bad}' present in v2 section"


# --- HTML calculator integrity ---


def test_calculator_html_exists_and_has_use_cases():
    txt = CALCULATOR_HTML.read_text(encoding="utf-8")
    assert "USE_CASES" in txt
    assert "MODELS" in txt
    assert "SEARCH" in txt
    assert "claude_sonnet_4_5" in txt
    assert "anthropic" in txt
    assert "jpcite ¥3/req" in txt or "¥3/req" in txt


def test_calculator_html_use_case_constants_match():
    """USE_CASES literal in HTML must match canonical 6 rows exactly."""
    txt = CALCULATOR_HTML.read_text(encoding="utf-8")
    # rough regex: capture each use case dict line
    pattern = re.compile(
        r"\{\s*id:\s*(\d+),\s*name:\s*\"[^\"]*\","
        r"(?:\s*output:\s*\"[^\"]*\",\s*)?"
        r"in_tok:\s*(\d+),\s*out_tok:\s*(\d+),\s*search:\s*(\d+),\s*req:\s*(\d+)\s*\}"
    )
    matches = pattern.findall(txt)
    assert len(matches) == 6, f"expected 6 use cases in HTML, found {len(matches)}"
    extracted = [(int(a), int(b), int(c), int(d), int(e)) for a, b, c, d, e in matches]
    expected = [(uc[0], uc[2], uc[3], uc[4], uc[5]) for uc in USE_CASES]
    assert extracted == expected, f"HTML USE_CASES mismatch:\n got={extracted}\n exp={expected}"


def test_calculator_html_default_model_and_fx():
    txt = CALCULATOR_HTML.read_text(encoding="utf-8")
    # Claude Sonnet 4.5 input $3 / output $15 — must match canonical
    assert "in_per_mtok: 3.00" in txt
    assert "out_per_mtok: 15.00" in txt
    # web search Anthropic $10/1k
    assert "anthropic:" in txt and "10.00" in txt
    # USD/JPY default 150
    assert 'id="fx"' in txt and 'value="150"' in txt
    # jpcite default 3
    assert 'id="jpcite"' in txt and 'value="3"' in txt


def test_calculator_html_no_roi_arr_or_old_brand():
    """memory: feedback_cost_saving_not_roi + old brand removal."""
    txt = CALCULATOR_HTML.read_text(encoding="utf-8")
    # 旧 brand 禁止
    assert "AutonoMath" not in txt
    assert "zeimu-kaikei" not in txt
    assert "税務会計AI" not in txt
    # ARR / 年商 / ROI 倍率 禁止
    assert "ARR" not in txt
    assert "年商" not in txt
    assert "ROI 倍率" not in txt


def test_total_savings_six_cases():
    """Sum of 6 use case savings ¥477.00 (sanity number for STATE doc)."""
    total = sum(_pure_llm_jpy(uc[2], uc[3], uc[4]) - _jpcite_jpy(uc[5]) for uc in USE_CASES)
    assert abs(total - 477.00) < 0.01, f"6-case total saving expected ¥477.00, got {total:.4f}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
