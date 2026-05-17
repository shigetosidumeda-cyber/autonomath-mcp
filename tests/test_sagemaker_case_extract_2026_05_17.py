"""Unit tests for the Lane M2 case-extraction pipeline.

These tests exercise the pure extraction primitives (regex, dict, signal
detection) without touching S3 / SageMaker / boto3. The pipeline driver
is end-to-end smoke-tested via DRY_RUN on a fixture autonomath DB in a
separate (slower) integration test — kept out of the default suite so
unit tests stay sub-second.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "aws_credit_ops"
    / "sagemaker_case_extract_2026_05_17.py"
)
spec = importlib.util.spec_from_file_location("m2_extract", SCRIPT_PATH)
assert spec is not None
assert spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules["m2_extract"] = mod
spec.loader.exec_module(mod)


def test_parse_amount_man_yen() -> None:
    assert mod.parse_amount("補助金 500万円交付") == 5_000_000


def test_parse_amount_oku() -> None:
    assert mod.parse_amount("総事業費 2億円規模の投資") == 200_000_000


def test_parse_amount_largest_wins() -> None:
    # Two amounts present; largest in yen wins (10,000 vs 5,000,000).
    assert mod.parse_amount("自己負担1万円 補助500万円") == 5_000_000


def test_parse_amount_no_match() -> None:
    assert mod.parse_amount("板金事業の技術を活かした新商品") is None
    assert mod.parse_amount("") is None


def test_parse_amount_rejects_above_trillion() -> None:
    # 100 trillion yen is noise — sanity bound clips it.
    assert mod.parse_amount("予算1000億円規模を見込む") == 100_000_000_000


def test_parse_fiscal_year_western() -> None:
    assert mod.parse_fiscal_year("IT導入補助金 2023 後期") == 2023


def test_parse_fiscal_year_reiwa() -> None:
    assert mod.parse_fiscal_year("令和5年度ものづくり補助金") == 2023
    assert mod.parse_fiscal_year("令和元年募集要項") == 2019


def test_parse_fiscal_year_heisei() -> None:
    assert mod.parse_fiscal_year("平成30年度予算事業") == 2018


def test_parse_fiscal_year_rn() -> None:
    assert mod.parse_fiscal_year("R5年度実施計画") == 2023


def test_parse_fiscal_year_no_match() -> None:
    assert mod.parse_fiscal_year("補助金") is None
    assert mod.parse_fiscal_year("") is None


def test_parse_jsic_construction() -> None:
    # Plain construction keywords with no "工業" ambiguity.
    assert mod.parse_jsic("塗装 株式会社", "建設 土木") == "D"


def test_parse_jsic_manufacturing() -> None:
    assert mod.parse_jsic("製造業", "ものづくり") == "E"


def test_parse_jsic_no_match_returns_none() -> None:
    assert mod.parse_jsic("") is None
    assert mod.parse_jsic("一般") is None


def test_parse_jsic_tie_returns_none() -> None:
    # Equal hits across two industries -> ambiguous -> NULL (never guess).
    assert mod.parse_jsic("建設 製造") is None


def test_parse_signals_success() -> None:
    sig = mod.parse_signals("新商品でアウトドア市場に新規参入する", mod.SUCCESS_TOKENS)
    assert sig == ["新商品", "新規参入"]


def test_parse_signals_empty() -> None:
    assert mod.parse_signals("", mod.SUCCESS_TOKENS) == []
    assert mod.parse_signals("一般的な事業", mod.SUCCESS_TOKENS) == []


def test_parse_signals_dedup_preserves_first_order() -> None:
    sig = mod.parse_signals(
        "新商品 新商品 販路拡大",
        mod.SUCCESS_TOKENS,
    )
    assert sig == ["新商品", "販路拡大"]


def test_filter_aggregator_url_blocks_banned() -> None:
    assert mod.filter_aggregator_url("https://noukaweb.example/abc") is None
    assert mod.filter_aggregator_url("https://www.hojyokin-portal.jp/p/1") is None
    assert mod.filter_aggregator_url("https://biz.stayway.jp/foo") is None


def test_filter_aggregator_url_allows_primary() -> None:
    url = "https://it-shien.smrj.go.jp/pdf/r4_grantdecision_list_digital_07.pdf"
    assert mod.filter_aggregator_url(url) == url


def test_filter_aggregator_url_none_passthrough() -> None:
    assert mod.filter_aggregator_url(None) is None


def test_compose_confidence_zero_when_empty() -> None:
    f = mod.ExtractedFact(
        case_id="adoption:1",
        source_kind="adoption",
        amount_yen=None,
        fiscal_year=None,
        industry_jsic=None,
        prefecture=None,
        success_signals=[],
        failure_signals=[],
        related_program_ids=[],
    )
    assert mod.compose_confidence(f) == 0.0


def test_compose_confidence_full_one() -> None:
    f = mod.ExtractedFact(
        case_id="adoption:1",
        source_kind="adoption",
        amount_yen=5_000_000,
        fiscal_year=2023,
        industry_jsic="E",
        prefecture="東京都",
        success_signals=["新商品"],
        failure_signals=[],
        related_program_ids=["prog-001"],
    )
    assert mod.compose_confidence(f) == 1.0


def test_compose_confidence_partial() -> None:
    f = mod.ExtractedFact(
        case_id="adoption:1",
        source_kind="adoption",
        amount_yen=None,
        fiscal_year=2023,
        industry_jsic="E",
        prefecture="東京都",
        success_signals=[],
        failure_signals=[],
        related_program_ids=[],
    )
    # 0.20 (fy) + 0.20 (jsic) + 0.10 (pref) = 0.50
    assert mod.compose_confidence(f) == 0.5


def test_estimate_sagemaker_cost_g4dn_default() -> None:
    # 5 instances x $0.61/h x 4 h = $12.20
    assert mod.estimate_sagemaker_cost("ml.g4dn.xlarge", 5, 4.0) == 12.20


def test_estimate_sagemaker_cost_unknown_falls_back_to_g4dn_rate() -> None:
    assert mod.estimate_sagemaker_cost("ml.unknown", 1, 1.0) == 0.61


def test_extract_from_adoption_minimal_row() -> None:
    row = {
        "id": 42,
        "project_title": "新商品で販路拡大",
        "program_name_raw": "ものづくり補助金 令和5年",
        "company_name_raw": "株式会社サンプル",
        "industry_raw": "製造業",
        "prefecture": "東京都",
        "industry_jsic_medium": "E001",
        "program_id": "prog-xyz",
        "source_url": "https://www.meti.go.jp/example.pdf",
    }
    fact = mod.extract_from_adoption(row)
    assert fact.case_id == "adoption:42"
    assert fact.source_kind == "adoption"
    assert fact.amount_yen is None  # No yen surface form in title.
    assert fact.fiscal_year == 2023
    assert fact.industry_jsic == "E"
    assert fact.prefecture == "東京都"
    assert "新商品" in fact.success_signals
    assert "販路拡大" in fact.success_signals
    assert fact.related_program_ids == ["prog-xyz"]
    assert fact.confidence >= 0.7


def test_extract_from_adoption_drops_unknown_jsic_letter() -> None:
    row = {
        "id": 1,
        "project_title": "",
        "program_name_raw": "",
        "company_name_raw": "",
        "industry_raw": "",
        "prefecture": None,
        "industry_jsic_medium": "ZZZ",
        "program_id": None,
        "source_url": None,
    }
    fact = mod.extract_from_adoption(row)
    assert fact.industry_jsic is None
