"""TKC FX-compatible general journal profile coverage."""

from __future__ import annotations

import pytest

from jpintel_mcp.agent_runtime.accounting_csv_profiles import (
    ALLOWED_PRIVATE_OUTPUTS,
    BLOCKED_PUBLIC_OUTPUTS,
    GROUNDING_RULES,
    build_accounting_csv_profile_catalog_shape,
    build_accounting_csv_profiles,
    build_downstream_output_contract,
    detect_accounting_csv_profile,
    evaluate_accounting_csv_headers,
    get_accounting_csv_profile,
    summarize_period_coverage,
)

TKC_PROFILE_KEY = "tkc_general_journal_layout_v1"


def test_tkc_profile_is_registered_with_no_certification_claim() -> None:
    profiles = build_accounting_csv_profiles()
    keys = [profile.profile_key for profile in profiles]

    assert TKC_PROFILE_KEY in keys
    assert len(profiles) == 5

    tkc_profile = get_accounting_csv_profile(TKC_PROFILE_KEY)
    assert tkc_profile.provider_family == "tkc"
    assert tkc_profile.official_certification_claimed is False
    assert "TKC" in tkc_profile.display_name
    assert "not an official TKC specification" in tkc_profile.profile_scope
    assert tkc_profile.allowed_downstream_outputs == ALLOWED_PRIVATE_OUTPUTS
    assert tkc_profile.blocked_downstream_outputs == BLOCKED_PUBLIC_OUTPUTS
    assert tkc_profile.grounding_rules == GROUNDING_RULES


def test_tkc_catalog_shape_contains_tkc_provider_family() -> None:
    catalog = build_accounting_csv_profile_catalog_shape()
    families = {profile["provider_family"] for profile in catalog["profiles"]}

    assert "tkc" in families
    assert {"freee", "money_forward", "yayoi", "tkc"} <= families
    assert len(catalog["profiles"]) == 5


def test_tkc_detection_signals_meet_required_minimum() -> None:
    tkc_profile = get_accounting_csv_profile(TKC_PROFILE_KEY)

    # Detection signals are 7 (5 required + 2 strengthening).
    assert len(tkc_profile.detection_signals) == 7
    required_count = sum(1 for signal in tkc_profile.detection_signals if signal.required)
    assert required_count == 5
    assert tkc_profile.minimum_matched_signals == 5


def test_tkc_normalized_fields_cover_double_entry_with_fiscal_year() -> None:
    tkc_profile = get_accounting_csv_profile(TKC_PROFILE_KEY)
    field_keys = {field.field_key for field in tkc_profile.normalized_fields}

    # Required: date, debit_account, debit_amount, credit_account, credit_amount.
    assert {
        "transaction_date",
        "debit_account",
        "debit_amount",
        "credit_account",
        "credit_amount",
        "description",
        "department",
        "fiscal_year",
        "tax_code",
        "tax_amount",
        "entry_id",
        "account_category",
    } <= field_keys
    assert len(tkc_profile.normalized_fields) == 12


def test_tkc_account_category_policy_disables_derivation() -> None:
    tkc_profile = get_accounting_csv_profile(TKC_PROFILE_KEY)

    # TKC 標準勘定科目体系は推測しない.
    assert tkc_profile.account_category_policy.derived_category_allowed is False


def test_tkc_period_coverage_policy_is_observed_only() -> None:
    tkc_profile = get_accounting_csv_profile(TKC_PROFILE_KEY)

    # Observed-only: date_field_keys references the transaction_date normalized field.
    assert tkc_profile.period_coverage_policy.date_field_keys == ("transaction_date",)


def test_tkc_detection_picks_up_fx_journal_layout() -> None:
    headers = (
        "仕訳No",
        "伝票日付",
        "借方科目",
        "借方金額",
        "貸方科目",
        "貸方金額",
        "摘要",
        "部門",
        "会計年度",
        "借方消費税区分",
        "貸方消費税区分",
    )

    detection = detect_accounting_csv_profile(headers)

    assert detection.profile_key == TKC_PROFILE_KEY
    assert detection.provider_family == "tkc"
    assert detection.confidence in {"medium", "high"}
    assert detection.missing_required_signals == ()


def test_tkc_detection_refuses_generic_journal_without_voucher_date() -> None:
    headers = (
        "取引日",
        "借方科目",
        "貸方科目",
        "借方金額",
        "貸方金額",
        "摘要",
    )

    detection = detect_accounting_csv_profile(headers)

    # 伝票日付 must be present — without it the TKC required signal is not met.
    assert detection.profile_key != TKC_PROFILE_KEY


def test_tkc_evaluation_emits_observed_normalized_fields() -> None:
    headers = (
        "仕訳No",
        "伝票日付",
        "借方科目",
        "借方金額",
        "貸方科目",
        "貸方金額",
        "摘要",
        "部門",
        "会計年度",
    )

    evaluation = evaluate_accounting_csv_headers(TKC_PROFILE_KEY, headers)

    assert evaluation.profile_key == TKC_PROFILE_KEY
    assert evaluation.provider_family == "tkc"
    assert evaluation.missing_required_fields == ()
    assert "fiscal_year" in evaluation.observed_normalized_fields
    assert "department" in evaluation.observed_normalized_fields
    assert evaluation.account_category_coverage.mode == "account_label_only"
    assert evaluation.account_category_coverage.derived_category_allowed is False
    assert evaluation.official_certification_claimed is False


def test_tkc_downstream_contract_blocks_all_public_outputs() -> None:
    headers = (
        "仕訳No",
        "伝票日付",
        "借方科目",
        "借方金額",
        "貸方科目",
        "貸方金額",
        "摘要",
    )

    contract = build_downstream_output_contract(TKC_PROFILE_KEY, headers)

    assert contract.allowed_downstream_outputs == ALLOWED_PRIVATE_OUTPUTS
    assert contract.blocked_downstream_outputs == BLOCKED_PUBLIC_OUTPUTS
    assert contract.public_claim_support is False
    assert contract.source_receipt_compatible is False
    assert contract.row_level_export_allowed_without_consent is False
    assert contract.official_certification_claimed is False
    assert not any(output.startswith("public_") for output in contract.allowed_downstream_outputs)
    assert "do_not_infer_account_categories" in contract.grounding_rules


@pytest.mark.parametrize(
    "headers",
    [
        ("発生日", "勘定科目", "金額", "摘要"),
        ("取引日", "借方勘定科目", "貸方勘定科目", "借方金額", "貸方金額", "摘要"),
    ],
)
def test_tkc_detection_is_conservative_for_non_tkc_headers(
    headers: tuple[str, ...],
) -> None:
    detection = detect_accounting_csv_profile(headers)

    assert detection.profile_key != TKC_PROFILE_KEY


def test_tkc_period_coverage_uses_observed_voucher_dates_only() -> None:
    summary = summarize_period_coverage(
        TKC_PROFILE_KEY,
        (
            {"伝票日付": "2026/04/01", "借方金額": "1000"},
            {"伝票日付": "2026-06-30", "借方金額": "2500"},
        ),
    )

    # observed_only policy: no completeness claim, just row-range evidence.
    assert summary.mode == "observed_row_date_range"
    assert summary.period_start == "2026-04-01"
    assert summary.period_end == "2026-06-30"
    assert "not a completeness claim" in summary.limitation
