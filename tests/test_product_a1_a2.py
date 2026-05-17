"""Tests for jpcite Stage 3 Application products — A1 + A2.

A1 = 税理士月次決算 Pack (``product_tax_monthly_closing_pack``).
A2 = 会計士監査調書 Pack (``product_audit_workpaper_pack``).

18 tests across both products (8 A1 + 7 A2 + 3 boundary).
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any


def _call_a1(**kwargs: Any) -> dict[str, Any]:
    from jpintel_mcp.mcp.products.product_a1_tax_monthly import (
        product_tax_monthly_closing_pack,
    )

    fn = product_tax_monthly_closing_pack
    if hasattr(fn, "fn"):
        fn = fn.fn  # type: ignore[attr-defined]
    coro = fn(**kwargs)
    if inspect.iscoroutine(coro):
        return asyncio.run(coro)
    return coro  # pragma: no cover


def _call_a2(**kwargs: Any) -> dict[str, Any]:
    from jpintel_mcp.mcp.products.product_a2_audit_workpaper import (
        product_audit_workpaper_pack,
    )

    fn = product_audit_workpaper_pack
    if hasattr(fn, "fn"):
        fn = fn.fn  # type: ignore[attr-defined]
    coro = fn(**kwargs)
    if inspect.iscoroutine(coro):
        return asyncio.run(coro)
    return coro  # pragma: no cover


# ---------------------------------------------------------------------------
# A1 — 税理士月次決算 Pack
# ---------------------------------------------------------------------------


def test_a1_skeleton_mode_returns_complete_pack() -> None:
    out = _call_a1(fiscal_year=2026, month=5)
    assert out["tool_name"] == "product_tax_monthly_closing_pack"
    assert out["schema_version"] == "product.a1.v1"
    assert out["primary_result"]["status"] == "ok"
    assert out["primary_result"]["product_id"] == "A1"
    assert out["primary_result"]["is_skeleton"] is True
    assert out["month_label"] == "2026-05"
    assert isinstance(out["profit_loss"], list)
    assert len(out["profit_loss"]) == 13
    pl_codes = [row["account_code"] for row in out["profit_loss"]]
    assert "510" in pl_codes
    assert "910" in pl_codes
    assert "920" in pl_codes
    assert isinstance(out["journal_entries"], list)
    assert len(out["journal_entries"]) == 5
    cstax = out["consumption_tax_calc"]
    assert cstax is not None
    assert cstax["month_label"] == "2026-05"
    assert cstax["fiscal_year"] == 2026
    assert len(cstax["tax_rate_buckets"]) == 4
    rate_labels = [b["rate_label"] for b in cstax["tax_rate_buckets"]]
    assert any("10%" in r for r in rate_labels)
    assert any("8%" in r for r in rate_labels)
    assert out["recipe"] is not None
    assert out["recipe"]["recipe_name"] == "recipe_tax_monthly_closing"
    assert isinstance(out["warnings"], list)
    assert isinstance(out["next_actions"], list)
    assert len(out["next_actions"]) == 3


def test_a1_pricing_envelope_tier_d_and_value_proxy_band() -> None:
    out = _call_a1(fiscal_year=2026, month=1)
    billing = out["billing"]
    assert billing["tier"] == "D"
    assert billing["product_id"] == "A1"
    assert billing["price_per_req_jpy"] == 30
    assert billing["price_per_houjin_monthly_jpy"] == 0
    assert billing["no_llm"] is True
    assert billing["scaffold_only"] is True
    vp = billing["value_proxy"]
    assert vp["model"] == "claude-opus-4-7"
    assert vp["llm_equivalent_low_jpy"] == 30
    assert vp["llm_equivalent_high_jpy"] == 75
    # V3: jpcite ¥30 vs Sonnet 8-turn ¥30 = parity, vs Opus ¥75 = 60% save.
    assert -10.0 <= vp["saving_low_pct"] <= 100.0
    assert -10.0 <= vp["saving_high_pct"] <= 100.0


def test_a1_disclaimer_references_section52_and_primary_source() -> None:
    out = _call_a1(fiscal_year=2026, month=3)
    disclaimer = out["_disclaimer"]
    assert "§52" in disclaimer
    assert "税理士" in disclaimer
    assert "一次資料" in disclaimer


def test_a1_amounts_are_placeholders_for_operator_fill() -> None:
    out = _call_a1(fiscal_year=2026, month=2)
    for row in out["profit_loss"]:
        assert row["debit_jpy"] is None
        assert row["credit_jpy"] is None
    for entry in out["journal_entries"]:
        assert entry["amount_jpy"] is None


def test_a1_month_label_format_and_consumption_tax_fiscal_year() -> None:
    out = _call_a1(fiscal_year=2025, month=12)
    assert out["month_label"] == "2025-12"
    assert out["consumption_tax_calc"]["fiscal_year"] == 2025
    assert out["consumption_tax_calc"]["kakei_filing_due"] == "2026-03-31"


def test_a1_no_llm_import_at_module_scope() -> None:
    import jpintel_mcp.mcp.products.product_a1_tax_monthly as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    for banned in ("import anthropic", "import openai", "import google.generativeai"):
        assert banned not in src


def test_a1_provenance_lists_composed_lanes() -> None:
    out = _call_a1(fiscal_year=2026, month=6)
    prov = out["provenance"]
    assert prov["product_id"] == "A1"
    assert prov["wrap_kind"] == "product_a1_pack"
    composed = prov["composed_lanes"]
    for lane in ("HE-2", "N3", "N4", "N6", "N8"):
        assert lane in composed
    assert out["_provenance"]["product_id"] == "A1"
    assert "HE-2" in out["_provenance"]["composed_lanes"]


def test_a1_next_actions_three_step_plan() -> None:
    out = _call_a1(fiscal_year=2026, month=7)
    actions = out["next_actions"]
    assert len(actions) == 3
    step_names = [a["step"] for a in actions]
    assert step_names[0] == "operator fill amounts"
    assert step_names[1] == "verify with 税理士"
    assert step_names[2] == "submit to filing_window"


# ---------------------------------------------------------------------------
# A2 — 会計士監査調書 Pack
# ---------------------------------------------------------------------------


def test_a2_skeleton_mode_returns_complete_pack() -> None:
    out = _call_a2(fiscal_year=2026, audit_type="年次")
    assert out["tool_name"] == "product_audit_workpaper_pack"
    assert out["schema_version"] == "product.a2.v1"
    assert out["primary_result"]["status"] == "ok"
    assert out["primary_result"]["product_id"] == "A2"
    assert out["primary_result"]["is_skeleton"] is True
    assert out["primary_result"]["audit_type"] == "年次"
    wp = out["workpaper_skeleton"]
    assert isinstance(wp, list)
    assert len(wp) == 4
    ic = out["internal_control_evaluation"]
    assert ic is not None
    assert ic["framework"].startswith("J-SOX")
    assert len(ic["axes"]) == 5
    axis_ids = [a["axis_id"] for a in ic["axes"]]
    for required in (
        "permission_separation",
        "automation",
        "monitoring",
        "risk_assessment",
        "reporting",
    ):
        assert required in axis_ids
    materiality = out["materiality_items"]
    assert isinstance(materiality, list)
    assert len(materiality) >= 3
    samp = out["sampling_recommendation"]
    assert samp is not None
    assert samp["audit_type"] == "年次"
    assert samp["sample_size_baseline"] >= 1
    assert 0.5 <= samp["confidence_level"] <= 1.0
    opin = out["audit_opinion_draft"]
    assert opin is not None
    assert set(opin["opinion_classification_options"]) == {
        "無限定適正意見",
        "限定付適正意見",
        "不適正意見",
        "意見不表明",
    }
    assert set(opin["drafts"].keys()) == set(opin["opinion_classification_options"])
    ra = out["risk_assessment"]
    assert ra is not None
    assert len(ra["risk_axes"]) == 3
    risk_ids = [a["axis_id"] for a in ra["risk_axes"]]
    assert "inherent_risk" in risk_ids
    assert "control_risk" in risk_ids
    assert "detection_risk" in risk_ids


def test_a2_pricing_envelope_tier_d_and_value_proxy_band() -> None:
    out = _call_a2(fiscal_year=2026, audit_type="年次")
    billing = out["billing"]
    assert billing["tier"] == "D"
    assert billing["product_id"] == "A2"
    assert billing["price_per_req_jpy"] == 30
    assert billing["no_llm"] is True
    assert billing["scaffold_only"] is True
    vp = billing["value_proxy"]
    assert vp["model"] == "claude-opus-4-7"
    assert vp["llm_equivalent_low_jpy"] == 30
    assert vp["llm_equivalent_high_jpy"] == 75
    # V3: jpcite ¥30 vs Sonnet 8-turn ¥30 = parity, vs Opus ¥75 = 60% save.
    assert -10.0 <= vp["saving_low_pct"] <= 100.0
    assert -10.0 <= vp["saving_high_pct"] <= 100.0


def test_a2_disclaimer_references_section47_2_and_audit_standards() -> None:
    out = _call_a2(fiscal_year=2026, audit_type="四半期")
    disclaimer = out["_disclaimer"]
    assert "§47条の2" in disclaimer
    assert "会計士" in disclaimer
    assert "監査基準" in disclaimer


def test_a2_sampling_size_monotonic_across_audit_types() -> None:
    annual = _call_a2(fiscal_year=2026, audit_type="年次")
    quarterly = _call_a2(fiscal_year=2026, audit_type="四半期")
    review = _call_a2(fiscal_year=2026, audit_type="レビュー")
    n_annual = annual["sampling_recommendation"]["sample_size_baseline"]
    n_q = quarterly["sampling_recommendation"]["sample_size_baseline"]
    n_r = review["sampling_recommendation"]["sample_size_baseline"]
    assert n_annual >= n_q >= n_r
    c_annual = annual["sampling_recommendation"]["confidence_level"]
    c_q = quarterly["sampling_recommendation"]["confidence_level"]
    c_r = review["sampling_recommendation"]["confidence_level"]
    assert c_annual >= c_q >= c_r


def test_a2_review_rewrites_substantive_section_purpose() -> None:
    out = _call_a2(fiscal_year=2026, audit_type="レビュー")
    st_section = next(s for s in out["workpaper_skeleton"] if s["section_id"] == "st")
    assert "質問" in st_section["purpose"]
    assert "分析的手続" in st_section["purpose"]


def test_a2_provenance_lists_composed_lanes() -> None:
    out = _call_a2(fiscal_year=2026, audit_type="年次")
    prov = out["provenance"]
    assert prov["product_id"] == "A2"
    assert prov["wrap_kind"] == "product_a2_pack"
    composed = prov["composed_lanes"]
    for lane in ("HE-2", "N3", "N7"):
        assert lane in composed


def test_a2_workpaper_section_sequence() -> None:
    out = _call_a2(fiscal_year=2026, audit_type="年次")
    seq = tuple(s["section_id"] for s in out["workpaper_skeleton"])
    assert seq == ("ra", "ct", "st", "cn")


# ---------------------------------------------------------------------------
# Boundary scenarios
# ---------------------------------------------------------------------------


def test_a1_billing_envelope_independent_of_skeleton_mode() -> None:
    out_skel = _call_a1(fiscal_year=2026, month=4)
    out_houjin = _call_a1(houjin_bangou="1234567890123", fiscal_year=2026, month=4)
    assert out_skel["billing"] == out_houjin["billing"]


def test_a2_audit_type_pattern_declared_in_tool_schema() -> None:
    from jpintel_mcp.mcp.products.product_a2_audit_workpaper import (
        product_audit_workpaper_pack,
    )

    fn = product_audit_workpaper_pack
    if hasattr(fn, "fn"):
        fn = fn.fn  # type: ignore[attr-defined]
    sig = inspect.signature(fn)
    audit_param = sig.parameters["audit_type"]
    rendered = repr(audit_param.annotation)
    assert "年次" in rendered
    assert "四半期" in rendered
    assert "レビュー" in rendered


def test_a2_no_llm_import_at_module_scope() -> None:
    import jpintel_mcp.mcp.products.product_a2_audit_workpaper as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    for banned in ("import anthropic", "import openai", "import google.generativeai"):
        assert banned not in src
