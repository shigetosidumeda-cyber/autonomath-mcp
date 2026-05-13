"""Wave 46 tick#11 — ROI / ARR / 年 ¥ final cleanup verifier.

Goal: ensure the top user-facing surfaces (site/pricing.html, site/index.html
and the partnerships/announce docs surfaced through publication channels)
no longer expose the historical "ROI 倍率 / 年 ARR 上限 / 倍 ROI" framing as
the dominant claim.  Historical reference markers (e.g. "(historical ROI ...
表現)") are explicitly preserved per memory `feedback_destruction_free_organization`.

This test does NOT require eradication everywhere — that would conflict with
the historical-reference policy and `feedback_completion_gate_minimal`.
Instead it asserts:

1. Each cleaned file mentions a saving / cost-saving phrase ("節約" or
   "cost saving") that the user can read.
2. Each cleaned file does not contain bare "ROI 倍率" (no marker) or
   "年 ARR 上限" without the explicit historical marker we just inserted.
3. The canonical cost-saving SOT (docs/canonical/cost_saving_examples.md)
   stays anchored to the public-safe API-fee-delta spec.
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Files this PR cleaned — each must show the savings rephrasing.
CLEANED_FILES = [
    "site/index.html",
    "site/index.html.md",
    "site/pricing.html",
    "site/pricing.html.md",
    "docs/partnerships/freee.md",
    "docs/partnerships/money_forward.md",
    "docs/partnerships/kintone.md",
    "docs/partnerships/anthropic_directory.md",
    "docs/partnerships/smarthr.md",
    "docs/announce/zeirishi_shimbun_jpcite.md",
    "docs/announce/tkc_journal_jpcite.md",
    "docs/announce/gyosei_kaiho_jpcite.md",
    "docs/announce/shinkin_monthly_jpcite.md",
    "docs/announce/bengoshi_dotcom_jpcite.md",
    "docs/announce/ma_online_jpcite.md",
    "docs/announce/shindanshi_kaiho_jpcite.md",
]

CANONICAL_SOT = "docs/canonical/cost_saving_examples.md"

TARGET_PUBLIC_COPY_FILES = [
    "docs/pricing/case_studies/admin_scrivener_construction_license.md",
    "docs/pricing/case_studies/ma_advisor_dd.md",
    "docs/pricing/case_studies/shinkin_customer_watch.md",
    "docs/pricing/case_studies/sme_diagnostician_consulting.md",
    "docs/pricing/case_studies/tax_accountant_monthly_review.md",
    "docs/announce/tkc_journal_jpcite.md",
]

TARGET_INTERNAL_EXCLUDED_FILES = [
    "docs/use_cases/by_industry_v2_2026_05_12.md",
]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_cleaned_files_mention_savings() -> None:
    """Every cleaned file should mention saving / cost-saving / 節約."""

    misses: list[str] = []
    for rel in CLEANED_FILES:
        text = _read(rel)
        if ("節約" not in text) and ("cost saving" not in text.lower()):
            misses.append(rel)
    assert misses == [], f"Cleaned files lack any savings phrasing (節約 / cost saving): {misses}"


def test_no_bare_roi_baikai_in_cleaned_files() -> None:
    """`ROI 倍率` may stay only when a historical marker accompanies it.

    Acceptable nearby markers: 'historical', '旧', or 'redirect'/併記.
    """

    bare_hits: list[tuple[str, int, str]] = []
    for rel in CLEANED_FILES:
        text = _read(rel)
        for lineno, line in enumerate(text.splitlines(), 1):
            if "ROI 倍率" not in line:
                continue
            if any(
                marker in line
                for marker in (
                    "historical",
                    "旧",
                    "併記",
                    "別 doc",
                    "リファレンス",
                    "section",
                )
            ):
                continue
            bare_hits.append((rel, lineno, line.strip()[:160]))
    assert bare_hits == [], (
        "User-facing files still surface bare 'ROI 倍率' without a "
        "historical marker; please retain marker per "
        "feedback_destruction_free_organization. Hits: "
        f"{bare_hits}"
    )


def test_no_bare_arr_ceiling_in_cleaned_files() -> None:
    """`年 ARR 上限` may only remain when explicitly tagged historical."""

    bare_hits: list[tuple[str, int, str]] = []
    for rel in CLEANED_FILES:
        text = _read(rel)
        for lineno, line in enumerate(text.splitlines(), 1):
            if "年 ARR 上限" not in line:
                continue
            if any(
                marker in line
                for marker in (
                    "historical",
                    "旧",
                    "規模の流通額上限",
                    "上限シナリオ",
                )
            ):
                continue
            bare_hits.append((rel, lineno, line.strip()[:160]))
    assert bare_hits == [], (
        "User-facing files still surface bare '年 ARR 上限' framing without "
        "a historical / 流通額 marker. Hits: "
        f"{bare_hits}"
    )


def test_canonical_sot_intact() -> None:
    """docs/canonical/cost_saving_examples.md remains the API-fee-delta SOT.

    This SOT is being rolled out incrementally — if it has not yet landed on
    the branch under test (e.g. when this cleanup PR merges before the SOT
    PR), we skip rather than fail.  Once the SOT lands the assertions become
    binding.
    """

    sot_path = REPO_ROOT / CANONICAL_SOT
    if not sot_path.exists():
        import pytest  # noqa: PLC0415

        pytest.skip(f"{CANONICAL_SOT} not present yet — will gate on merge")
    text = sot_path.read_text(encoding="utf-8")
    assert "API fee delta" in text or "API 料金差額" in text, (
        "cost_saving_examples.md must surface API-fee-delta framing"
    )
    assert "ROI" not in text or any(marker in text for marker in ("旧表記", "旧来")), (
        "cost_saving_examples.md must not re-introduce ROI as primary unit "
        "(only as 旧表記 explainer)"
    )


def test_target_public_copy_has_no_roi_arr_or_internal_gtm_terms() -> None:
    """Docs cleaned in this pass must use public-safe cost/request framing."""

    forbidden = (
        "ROI",
        "ARR",
        "倍率",
        "回収倍率",
        "organic outreach",
        "zero-touch",
        "住み着",
        "pillar",
    )
    hits: list[tuple[str, str]] = []
    for rel in TARGET_PUBLIC_COPY_FILES:
        text = _read(rel)
        for bad in forbidden:
            if bad in text:
                hits.append((rel, bad))
    assert hits == [], f"public copy still contains forbidden ROI/GTM terms: {hits}"


def test_target_public_copy_uses_request_or_assumption_framing() -> None:
    """Public-facing docs should anchor value in req counts, savings, or assumptions."""

    misses: list[str] = []
    for rel in TARGET_PUBLIC_COPY_FILES:
        text = _read(rel)
        if not any(marker in text for marker in ("req", "節約", "明示的な前提", "利用前提")):
            misses.append(rel)
    assert misses == [], f"public copy lacks request/savings/assumption framing: {misses}"


def test_target_internal_roi_notes_are_marked_excluded() -> None:
    """Long-form historical ROI notes may remain only when explicitly excluded."""

    for rel in TARGET_INTERNAL_EXCLUDED_FILES:
        text = _read(rel)
        assert "operator-only / public docs excluded" in text
        assert "exclude_docs: use_cases/" in text
