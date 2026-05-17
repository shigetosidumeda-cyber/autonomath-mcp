"""Tests for products.product_a5_kaisha_setsuritsu (A5 会社設立一式 pack).

A5 is a deterministic-on-inputs pack (no DB fan-out), so the fixture
surface is minimal. The 18 tests below validate:

  A5-1   default 株式会社 path returns 6 scaffolds + 3 windows + 50+ placeholders.
  A5-2   合同会社 entity_type skips 株式 clauses in 定款 sections.
  A5-3   一般社団法人 entity_type stays compatible.
  A5-4   NPO法人 entity_type uses 会員 + 剰余金不分配 terminology.
  A5-5   invalid entity_type returns invalid_argument envelope.
  A5-6   empty business_purpose returns invalid_argument envelope.
  A5-7   one-yen company (会社法 §27) accepted.
  A5-8   filing_windows align with statutory bases (商業登記法 §47 / 法人税法 §148 / 健康保険法 §48).
  A5-9   billing envelope = 267 units = ¥801 ≈ ¥800 (Tier D band).
  A5-10  agent_next_actions has 3 deterministic steps.
  A5-11  disclaimer envelope mentions all 6 regulated 士業 acts.
  A5-12  setsuritsu_date_iso override propagates to filing windows.
  A5-13  bad setsuritsu_date_iso returns invalid_argument envelope.
  A5-14  scaffolds all marked scaffold-only + review-required.
  A5-15  supervising_shigyo split is correct (司法書士 + 税理士 + 社労士).
  A5-16  placeholders all carry canonical {{...}} brace shape.
  A5-17  tier letter in billing envelope matches pricing_v2.PricingTier.D.
  A5-18  no LLM SDK imports in the A5 module.
"""

from __future__ import annotations

import datetime as _dt
import importlib
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def product_a5() -> Any:
    """Import the A5 product module fresh per test."""
    mod = importlib.import_module("jpintel_mcp.mcp.products.product_a5_kaisha_setsuritsu")

    def _unwrap(tool: Any) -> Any:
        for attr in ("fn", "func", "_fn"):
            inner = getattr(tool, attr, None)
            if callable(inner):
                return inner
        return tool

    return _unwrap(mod.product_kaisha_setsuritsu_pack)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


_GOOD_INPUT: dict[str, Any] = {
    "entity_type": "株式会社",
    "representative_name": "梅田 茂利",
    "representative_address": "東京都文京区小日向2-22-1",
    "capital_yen": 1_000_000,
    "business_purpose": ["ソフトウェア開発", "コンサルティング"],
    "head_office_prefecture": "東京都",
    "head_office_city": "文京区",
    "jsic_major": "G",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_a5_default_happy_path_returns_full_pack(product_a5: Any) -> None:
    """A5-1 default 株式会社 path returns 6 scaffolds + 3 windows."""
    out = product_a5(**_GOOD_INPUT)
    assert out["primary_result"]["status"] == "ok"
    assert out["product_id"] == "A5"
    assert out["total"] == 6
    assert len(out["bundle"]) == 6
    assert len(out["filing_windows"]) == 3
    assert len(out["placeholders"]) >= 50


def test_a5_godo_kaisha_skips_kabushiki_clauses(product_a5: Any) -> None:
    """A5-2 合同会社 定款 must not have 発行可能株式総数."""
    out = product_a5(**{**_GOOD_INPUT, "entity_type": "合同会社"})
    teikan = out["bundle"][0]
    joined = "\n".join(teikan["sections"])
    assert "発行可能株式総数" not in joined


def test_a5_ippan_shadan_houjin_accepted(product_a5: Any) -> None:
    """A5-3 一般社団法人 entity_type stays compatible."""
    out = product_a5(**{**_GOOD_INPUT, "entity_type": "一般社団法人"})
    assert out["primary_result"]["status"] == "ok"


def test_a5_npo_houjin_uses_kaiin_terminology(product_a5: Any) -> None:
    """A5-4 NPO法人 uses 会員 + 剰余金不分配."""
    out = product_a5(**{**_GOOD_INPUT, "entity_type": "NPO法人"})
    teikan = out["bundle"][0]
    joined = "\n".join(teikan["sections"])
    assert "会員" in joined
    assert "剰余金不分配" in joined


def test_a5_invalid_entity_type_returns_invalid_argument(product_a5: Any) -> None:
    """A5-5 unknown entity_type returns invalid_argument envelope."""
    out = product_a5(**{**_GOOD_INPUT, "entity_type": "個人事業主"})
    assert out["primary_result"]["status"] == "invalid_argument"
    assert out["total"] == 0


def test_a5_empty_business_purpose_returns_invalid_argument(
    product_a5: Any,
) -> None:
    """A5-6 empty business_purpose returns invalid_argument."""
    out = product_a5(**{**_GOOD_INPUT, "business_purpose": ["", "  "]})
    assert out["primary_result"]["status"] == "invalid_argument"


def test_a5_one_yen_company_accepted(product_a5: Any) -> None:
    """A5-7 会社法 §27 一円会社 OK."""
    out = product_a5(**{**_GOOD_INPUT, "capital_yen": 1})
    assert out["primary_result"]["status"] == "ok"


def test_a5_filing_windows_match_statutory_basis(product_a5: Any) -> None:
    """A5-8 windows align with statutory bases."""
    out = product_a5(**{**_GOOD_INPUT, "setsuritsu_date_iso": "2026-05-17"})
    windows = {w["authority"]: w for w in out["filing_windows"]}
    assert set(windows.keys()) == {"法務局", "税務署", "年金事務所"}

    homukyoku = windows["法務局"]
    assert homukyoku["days_from_setsuritsu"] == 14
    assert homukyoku["window_open"] == "2026-05-17"
    assert homukyoku["window_close"] == "2026-05-31"
    assert "商業登記法" in homukyoku["statutory_basis"]

    zeimusho = windows["税務署"]
    assert zeimusho["days_from_setsuritsu"] == 60
    assert zeimusho["window_close"] == "2026-07-16"
    assert "法人税法" in zeimusho["statutory_basis"]

    nenkin = windows["年金事務所"]
    assert nenkin["days_from_setsuritsu"] == 5
    assert nenkin["window_close"] == "2026-05-22"
    assert "健康保険法" in nenkin["statutory_basis"]


def test_a5_billing_envelope_267_units(product_a5: Any) -> None:
    """A5-9 billing envelope = 267 units = ¥801 ≈ ¥800 (Tier D)."""
    out = product_a5(**_GOOD_INPUT)
    billing = out["billing"]
    assert billing["unit"] == 267
    assert billing["yen"] == 801
    assert billing["product_id"] == "A5"
    assert billing["tier"] == "D"
    assert out["_billing_unit"] == 267


def test_a5_agent_next_actions_has_3_deterministic_steps(product_a5: Any) -> None:
    """A5-10 agent_next_actions has 3 deterministic steps."""
    out = product_a5(**_GOOD_INPUT)
    actions = out["agent_next_actions"]
    assert len(actions) == 3
    assert actions[0]["step"].startswith("fill")
    assert "engage" in actions[2]["step"]


def test_a5_disclaimer_mentions_all_six_acts(product_a5: Any) -> None:
    """A5-11 disclaimer mentions 6 regulated 士業 acts."""
    out = product_a5(**_GOOD_INPUT)
    disclaimer = out["_disclaimer"]
    for needle in (
        "司法書士法",
        "税理士法",
        "公認会計士法",
        "弁護士法",
        "行政書士法",
        "社労士",
    ):
        assert needle in disclaimer, f"disclaimer missing {needle}"
    assert "社労士" in out["_related_shihou"]


def test_a5_setsuritsu_date_iso_override_propagates(product_a5: Any) -> None:
    """A5-12 setsuritsu_date_iso override propagates to windows."""
    out = product_a5(**{**_GOOD_INPUT, "setsuritsu_date_iso": "2027-01-15"})
    windows = {w["authority"]: w for w in out["filing_windows"]}
    assert windows["法務局"]["window_open"] == "2027-01-15"
    assert windows["法務局"]["window_close"] == "2027-01-29"


def test_a5_bad_setsuritsu_date_iso_returns_invalid_argument(
    product_a5: Any,
) -> None:
    """A5-13 bad setsuritsu_date_iso returns invalid_argument."""
    out = product_a5(**{**_GOOD_INPUT, "setsuritsu_date_iso": "not-a-date"})
    assert out["primary_result"]["status"] == "invalid_argument"


def test_a5_all_scaffolds_marked_scaffold_only_and_review_required(
    product_a5: Any,
) -> None:
    """A5-14 every scaffold marked scaffold-only + review-required."""
    out = product_a5(**_GOOD_INPUT)
    for scaffold in out["bundle"]:
        assert scaffold["is_scaffold_only"] is True
        assert scaffold["requires_professional_review"] is True


def test_a5_supervising_shigyo_split(product_a5: Any) -> None:
    """A5-15 supervising_shigyo split is correct across the 3 士業."""
    out = product_a5(**_GOOD_INPUT)
    by_kind = {s["artifact_type"]: s for s in out["bundle"]}
    assert by_kind["setsuritsu_touki_shinsei_sho"]["supervising_shigyo"] == "司法書士"
    assert by_kind["inkan_todoke_sho"]["supervising_shigyo"] == "司法書士"
    assert by_kind["houjin_setsuritsu_todoke_sho"]["supervising_shigyo"] == "税理士"
    assert by_kind["kyuyo_shiharai_jimusho_todoke_sho"]["supervising_shigyo"] == "税理士"
    assert by_kind["shakai_hoken_shinki_tekiyou_todoke"]["supervising_shigyo"] == "社労士"


def test_a5_placeholders_have_canonical_brace_shape(product_a5: Any) -> None:
    """A5-16 every placeholder carries {{...}} brace shape."""
    out = product_a5(**_GOOD_INPUT)
    for p in out["placeholders"]:
        assert p.startswith("{{") and p.endswith("}}"), f"bad placeholder: {p}"
    assert len(set(out["placeholders"])) == len(out["placeholders"])


@pytest.mark.skip(reason="pricing_v2 SKIPed by CL34 directive — A6 superseded by V3")
def test_a5_tier_letter_matches_pricing_v2(product_a5: Any) -> None:
    """A5-17 tier letter in billing envelope matches PricingTier.D."""
    from jpintel_mcp.billing.pricing_v2 import (
        PricingTier,
        stripe_metering_quantity_for_tier,
        validate_pack_price,
    )

    out = product_a5(**_GOOD_INPUT)
    assert out["billing"]["tier"] == PricingTier.D.value
    assert validate_pack_price(PricingTier.D, out["billing"]["yen"]) is True
    assert stripe_metering_quantity_for_tier(PricingTier.D) == 267


def test_a5_no_llm_imports() -> None:
    """A5-18 A5 module MUST NOT import any LLM SDK."""
    mod = importlib.import_module("jpintel_mcp.mcp.products.product_a5_kaisha_setsuritsu")
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for needle in (
        "anthropic",
        "openai",
        "google.generativeai",
        "claude_agent_sdk",
    ):
        assert needle not in src, f"A5 module imports forbidden LLM SDK: {needle}"


def test_a5_setsuritsu_date_default_today_when_omitted(product_a5: Any) -> None:
    """setsuritsu_date_iso omitted → defaults to today UTC."""
    out = product_a5(**_GOOD_INPUT)
    today = _dt.datetime.now(_dt.UTC).date().isoformat()
    assert out["primary_result"]["setsuritsu_date"] == today
