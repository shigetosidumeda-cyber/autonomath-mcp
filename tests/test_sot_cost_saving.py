"""Wave 46 tick5: SOT cost saving expression guard.

Verifies that the two SOT documents (docs/use_cases/by_industry_2026_05_11.md
and docs/pricing/justification_2026_05_11.md) include the ADDENDUM section
expressing per-case savings as "pure LLM token cost (¥300/req)" vs jpcite
fixed ¥3/req. Memory feedback_destruction_free_organization: original body
(including legacy ROI lines) is preserved; new content is append-only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SOT_FILES = {
    "by_industry": REPO_ROOT / "docs" / "use_cases" / "by_industry_2026_05_11.md",
    "justification": REPO_ROOT / "docs" / "pricing" / "justification_2026_05_11.md",
}

ADDENDUM_HEADER = "## ADDENDUM Cost saving 新表現 (2026-05-12 user 指示反映)"
ADDENDUM_FOOTER = "**ADDENDUM Cost saving end**"
WAVE_TAG = "Wave 46 tick5 cost saving SOT migration 2026-05-12"


@pytest.fixture(scope="module")
def sot_texts() -> dict[str, str]:
    out: dict[str, str] = {}
    for name, path in SOT_FILES.items():
        assert path.exists(), f"SOT file missing: {path}"
        out[name] = path.read_text(encoding="utf-8")
    return out


@pytest.mark.parametrize("name", list(SOT_FILES.keys()))
def test_addendum_header_present(sot_texts: dict[str, str], name: str) -> None:
    assert ADDENDUM_HEADER in sot_texts[name], (
        f"ADDENDUM header missing in {name}"
    )


@pytest.mark.parametrize("name", list(SOT_FILES.keys()))
def test_addendum_footer_present(sot_texts: dict[str, str], name: str) -> None:
    text = sot_texts[name]
    assert ADDENDUM_FOOTER in text, f"ADDENDUM footer missing in {name}"
    assert WAVE_TAG in text, f"Wave 46 tick5 tag missing in {name}"


@pytest.mark.parametrize("name", list(SOT_FILES.keys()))
def test_pure_llm_baseline_present(sot_texts: dict[str, str], name: str) -> None:
    text = sot_texts[name]
    assert "¥300/req" in text, f"純 LLM ¥300/req baseline missing in {name}"
    assert "¥3/req" in text, f"jpcite ¥3/req fixed rate missing in {name}"
    assert "99.00%" in text, f"節約率 99.00% missing in {name}"


@pytest.mark.parametrize("name", list(SOT_FILES.keys()))
def test_legacy_roi_preserved(sot_texts: dict[str, str], name: str) -> None:
    # feedback_destruction_free_organization: original ROI body intact.
    text = sot_texts[name]
    assert "ROI" in text, f"legacy ROI mention should remain in {name}"


def test_industry_table_count(sot_texts: dict[str, str]) -> None:
    # Both SOT files must contain 6 core personas + at least 3 additions.
    for name in SOT_FILES.keys():
        assert sot_texts[name].count("99.00%") >= 9, (
            f"{name}: expected >=9 rows at 99.00% saving (6 core + 3 add'l)"
        )


def test_addendum_appears_after_body(sot_texts: dict[str, str]) -> None:
    # ADDENDUM must be append-only (located after main body).
    for name, text in sot_texts.items():
        idx_first_h1 = text.find("# ")
        idx_addendum = text.find(ADDENDUM_HEADER)
        assert 0 <= idx_first_h1 < idx_addendum, (
            f"{name}: ADDENDUM not appended after body"
        )
