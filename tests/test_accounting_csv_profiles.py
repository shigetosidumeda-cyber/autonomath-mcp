from pathlib import Path

import pytest

from jpintel_mcp.agent_runtime.accounting_csv_profiles import (
    ALLOWED_PRIVATE_OUTPUTS,
    BLOCKED_PUBLIC_OUTPUTS,
    CERTIFICATION_NOTICE,
    GROUNDING_RULES,
    build_accounting_csv_profile_catalog_shape,
    build_accounting_csv_profiles,
    build_downstream_output_contract,
    detect_accounting_csv_profile,
    evaluate_accounting_csv_headers,
    summarize_period_coverage,
)


def test_catalog_covers_accounting_provider_families_without_certification_claims() -> None:
    catalog = build_accounting_csv_profile_catalog_shape()
    profiles = build_accounting_csv_profiles()

    assert catalog["schema_version"] == "jpcite.accounting_csv_profiles.p0.v1"
    assert catalog["certification_notice"] == CERTIFICATION_NOTICE
    assert {profile.provider_family for profile in profiles} == {
        "freee",
        "money_forward",
        "yayoi",
        "tkc",
    }
    assert [profile.profile_key for profile in profiles] == [
        "freee_transaction_rows",
        "freee_journal_rows",
        "money_forward_journal_rows",
        "yayoi_journal_rows",
        "tkc_general_journal_layout_v1",
    ]
    assert all(profile.official_certification_claimed is False for profile in profiles)
    assert all("official" in profile.certification_notice for profile in profiles)
    assert all(
        profile.allowed_downstream_outputs == ALLOWED_PRIVATE_OUTPUTS for profile in profiles
    )
    assert all(profile.blocked_downstream_outputs == BLOCKED_PUBLIC_OUTPUTS for profile in profiles)


@pytest.mark.parametrize(
    ("headers", "profile_key", "provider_family"),
    [
        (
            ("発生日", "管理番号", "勘定科目", "税区分", "金額", "税額", "取引先", "メモタグ"),
            "freee_transaction_rows",
            "freee",
        ),
        (
            (
                "発生日",
                "管理番号",
                "借方勘定科目",
                "貸方勘定科目",
                "借方金額",
                "貸方金額",
                "借方税区分",
                "メモタグ",
            ),
            "freee_journal_rows",
            "freee",
        ),
        (
            (
                "取引日",
                "伝票番号",
                "借方勘定科目",
                "借方補助科目",
                "借方部門",
                "借方品目",
                "借方メモタグ",
                "借方取引先",
                "借方税区分",
                "借方税額",
                "借方金額",
                "貸方勘定科目",
                "貸方補助科目",
                "貸方部門",
                "貸方品目",
                "貸方メモタグ",
                "貸方取引先",
                "貸方税区分",
                "貸方税額",
                "貸方金額",
                "摘要",
            ),
            "freee_journal_rows",
            "freee",
        ),
        (
            (
                "取引No",
                "取引日",
                "借方勘定科目",
                "貸方勘定科目",
                "借方金額(円)",
                "貸方金額(円)",
                "借方税区分",
                "貸方税区分",
                "MF仕訳タイプ",
                "摘要",
            ),
            "money_forward_journal_rows",
            "money_forward",
        ),
        (
            (
                "識別フラグ",
                "伝票No.",
                "取引日付",
                "借方勘定科目",
                "貸方勘定科目",
                "借方金額",
                "貸方金額",
                "借方税区分",
                "貸方税区分",
                "付箋1",
            ),
            "yayoi_journal_rows",
            "yayoi",
        ),
        (
            (
                "識別フラグ",
                "伝票No",
                "決算",
                "取引日付",
                "借方勘定科目",
                "借方補助科目",
                "借方部門",
                "借方税区分",
                "借方金額",
                "借方税金額",
                "貸方勘定科目",
                "貸方補助科目",
                "貸方部門",
                "貸方税区分",
                "貸方金額",
                "貸方税金額",
                "摘要",
            ),
            "yayoi_journal_rows",
            "yayoi",
        ),
    ],
)
def test_provider_specific_detection_uses_schema_signals(
    headers: tuple[str, ...],
    profile_key: str,
    provider_family: str,
) -> None:
    detection = detect_accounting_csv_profile(headers)

    assert detection.profile_key == profile_key
    assert detection.provider_family == provider_family
    assert detection.confidence in {"medium", "high"}
    assert detection.missing_required_signals == ()


@pytest.mark.parametrize(
    "headers",
    [
        ("取引日", "摘要", "勘定科目", "金額"),
        ("取引日", "借方勘定科目", "貸方勘定科目", "借方金額", "貸方金額", "摘要"),
        ("発生日", "勘定科目", "金額", "摘要"),
    ],
)
def test_detection_is_conservative_for_generic_or_incomplete_ledgers(
    headers: tuple[str, ...],
) -> None:
    detection = detect_accounting_csv_profile(headers)

    assert detection.profile_key is None
    assert detection.provider_family == "unknown"
    assert detection.confidence == "none"


def test_profiles_expose_missing_field_limitations_and_account_category_gap() -> None:
    headers = ("発生日", "管理番号", "勘定科目", "金額", "税区分")

    evaluation = evaluate_accounting_csv_headers("freee_transaction_rows", headers)
    limitations = {
        limitation.field_key: limitation for limitation in evaluation.missing_field_limitations
    }

    assert evaluation.missing_required_fields == ()
    assert "account_category" in evaluation.missing_optional_fields
    assert "counterparty" in evaluation.missing_optional_fields
    assert limitations["account_category"].severity == "warning"
    assert "cannot be populated or inferred" in limitations["account_category"].limitation
    assert evaluation.account_category_coverage.mode == "account_label_only"
    assert evaluation.account_category_coverage.derived_category_allowed is False
    assert evaluation.account_category_coverage.limitation is not None


def test_period_coverage_is_observed_range_not_completeness_claim() -> None:
    no_rows = summarize_period_coverage("money_forward_journal_rows", ())
    observed_rows = summarize_period_coverage(
        "money_forward_journal_rows",
        (
            {"取引日": "2026/01/31", "借方金額(円)": "1000"},
            {"取引日": "2026-02-15", "借方金額(円)": "2000"},
        ),
    )

    assert no_rows.mode == "unknown"
    assert no_rows.period_start is None
    assert "cannot prove full fiscal" in no_rows.limitation

    assert observed_rows.mode == "observed_row_date_range"
    assert observed_rows.period_start == "2026-01-31"
    assert observed_rows.period_end == "2026-02-15"
    assert observed_rows.evidence_fields == ("transaction_date",)
    assert "not a completeness claim" in observed_rows.limitation


def test_downstream_outputs_are_private_and_evidence_grounded() -> None:
    headers = ("取引日", "借方勘定科目", "貸方勘定科目", "借方金額", "貸方金額", "摘要")

    contract = build_downstream_output_contract("yayoi_journal_rows", headers)

    assert contract.allowed_downstream_outputs == ALLOWED_PRIVATE_OUTPUTS
    assert contract.blocked_downstream_outputs == BLOCKED_PUBLIC_OUTPUTS
    assert contract.public_claim_support is False
    assert contract.source_receipt_compatible is False
    assert contract.row_level_export_allowed_without_consent is False
    assert contract.official_certification_claimed is False
    assert "account_category" not in contract.observed_normalized_fields
    assert "emit_only_observed_normalized_fields" in contract.grounding_rules
    assert "do_not_infer_account_categories" in contract.grounding_rules
    assert not any(output.startswith("public_") for output in contract.allowed_downstream_outputs)


def test_profile_module_has_no_file_network_db_or_llm_runtime_dependencies() -> None:
    module_source = Path("src/jpintel_mcp/agent_runtime/accounting_csv_profiles.py").read_text()

    forbidden_tokens = (
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "urllib",
        "sqlite3",
        "import csv",
        "open(",
        "OpenAI",
        "anthropic",
    )
    assert not any(token in module_source for token in forbidden_tokens)
    assert set(GROUNDING_RULES) >= {
        "mark_missing_fields_as_limitations",
        "do_not_infer_full_period_coverage",
        "do_not_create_public_source_receipts_from_private_csv",
    }
