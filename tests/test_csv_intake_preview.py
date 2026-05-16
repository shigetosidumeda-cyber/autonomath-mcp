from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from jpintel_mcp.api.jpcite_facade import router
from jpintel_mcp.services.csv_intake_preview import (
    preview_accounting_csv_bytes,
    preview_accounting_csv_text,
)

FREEE_JOURNAL_CSV = """取引日,伝票番号,借方勘定科目,借方金額,貸方勘定科目,貸方金額,借方税区分,摘要
2026/01/31,JV-1,消耗品費,1000,普通預金,1000,課税仕入10%,seed purchase
2026/02/15,JV-2,広告宣伝費,2000,普通預金,2000,課税仕入10%,flyer
"""


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_preview_accounting_csv_text_returns_private_aggregate_only() -> None:
    preview = preview_accounting_csv_text(FREEE_JOURNAL_CSV, filename="client-a.csv")
    serialized = json.dumps(preview, ensure_ascii=False)

    assert preview["schema_version"] == "jpcite.accounting_csv_intake_preview.p0.v1"
    assert preview["status"] == "preview_ready"
    assert preview["billable"] is False
    assert preview["charge_status"] == "not_charged"
    assert preview["raw_csv_retained"] is False
    assert preview["raw_rows_returned"] is False
    assert preview["raw_cell_values_returned"] is False
    assert preview["public_source_receipt_compatible"] is False
    assert preview["public_claim_support"] is False
    assert preview["official_certification_claimed"] is False
    assert preview["row_count"] == 2
    assert preview["column_count"] == 8
    assert preview["profile_detection"]["profile_key"] == "freee_journal_rows"
    assert preview["period_coverage"]["period_start"] == "2026-01-31"
    assert preview["period_coverage"]["period_end"] == "2026-02-15"
    assert preview["routing"]["recommended_outcome_contract_ids"] == [
        "csv_overlay_public_check",
        "cashbook_csv_subsidy_fit_screen",
    ]
    assert "seed purchase" not in serialized
    assert "flyer" not in serialized
    assert "JV-1" not in serialized
    assert "普通預金" not in serialized


def test_preview_accounting_csv_blocks_unknown_or_sensitive_shapes() -> None:
    generic = preview_accounting_csv_text("取引日,摘要,金額\n2026/01/01,memo,100\n")
    sensitive = preview_accounting_csv_text("取引日,口座番号,給与\n2026/01/01,1234567,999\n")

    assert generic["status"] == "blocked_or_limited"
    assert "csv_provider_unknown_or_ambiguous" in generic["known_gaps"]
    assert generic["routing"]["recommended_outcome_contract_ids"] == []

    assert sensitive["status"] == "blocked_or_limited"
    assert "payroll_or_bank_rejected" in sensitive["known_gaps"]
    assert sensitive["privacy_review"]["sensitive_header_count"] == 2
    assert sensitive["privacy_review"]["payroll_or_bank_rejected"] is True
    assert "1234567" not in json.dumps(sensitive, ensure_ascii=False)


def test_preview_accounting_csv_detects_formula_like_cells_without_echoing_values() -> None:
    preview = preview_accounting_csv_text(
        "取引日,伝票番号,借方勘定科目,借方金額,貸方勘定科目,貸方金額,借方税区分,摘要\n"
        '2026/01/01,JV-1,消耗品費,1000,普通預金,1000,課税仕入10%,=IMPORTXML("x")\n'
    )
    serialized = json.dumps(preview, ensure_ascii=False)

    assert "csv_formula_escaped" in preview["known_gaps"]
    assert preview["privacy_review"]["formula_like_cell_count"] == 1
    assert preview["privacy_review"]["formula_like_cell_count_bucket"] == "1-9"
    assert "IMPORTXML" not in serialized


def test_preview_accounting_csv_bytes_handles_yayoi_cp932() -> None:
    text = (
        "識別フラグ,伝票No.,取引日付,借方勘定科目,貸方勘定科目,借方金額,貸方金額,借方税区分,摘要\n"
        "2000,1,2026/03/01,雑費,現金,500,500,対象外,example\n"
    )

    preview = preview_accounting_csv_bytes(text.encode("cp932"))

    assert preview["decoded_encoding"] == "cp932"
    assert preview["profile_detection"]["profile_key"] == "yayoi_journal_rows"
    assert preview["profile_detection"]["provider_family"] == "yayoi"


def test_rest_preview_accounting_csv_is_free_and_does_not_echo_raw_values() -> None:
    response = _client().post(
        "/v1/jpcite/preview_accounting_csv",
        json={"csv_text": FREEE_JOURNAL_CSV, "filename": "client-a.csv"},
    )

    assert response.status_code == 200
    body = response.json()
    preview = body["csv_intake_preview"]
    serialized = json.dumps(body, ensure_ascii=False)
    assert body["charged"] is False
    assert body["accepted_artifact_created"] is False
    assert preview["profile_detection"]["profile_key"] == "freee_journal_rows"
    assert preview["raw_cell_values_returned"] is False
    assert "seed purchase" not in serialized
    assert "普通預金" not in serialized


def test_desktop_csv_samples_are_profiled_without_official_compliance_claims() -> None:
    csv_dir = Path("/Users/shigetoumeda/Desktop/CSV")
    if not csv_dir.exists():
        return

    expected_profiles = {
        "conglomerate_yayoi.csv": "yayoi_journal_rows",
        "freee_personal_freelance.csv": "freee_journal_rows",
        "freee_personal_rental.csv": "freee_journal_rows",
        "freee_sme_agri.csv": "freee_journal_rows",
        "freee_sme_welfare.csv": "freee_journal_rows",
        "media_conglomerate_yayoi.csv": "yayoi_journal_rows",
        "mf_sme_medical.csv": "money_forward_journal_rows",
        "mf_sme_subsidy.csv": "money_forward_journal_rows",
        "yayoi_apple_farm.csv": "yayoi_journal_rows",
    }

    for filename, profile_key in expected_profiles.items():
        preview = preview_accounting_csv_bytes(
            (csv_dir / filename).read_bytes(),
            filename=filename,
        )

        assert preview["status"] == "preview_ready"
        assert preview["profile_detection"]["profile_key"] == profile_key
        assert preview["row_count"] > 0
        assert preview["period_coverage"]["mode"] == "observed_row_date_range"
        assert preview["period_coverage"]["period_start"] is not None
        assert preview["period_coverage"]["period_end"] is not None
        assert preview["official_certification_claimed"] is False
        assert preview["public_source_receipt_compatible"] is False
        assert preview["raw_cell_values_returned"] is False

    formula_preview = preview_accounting_csv_bytes(
        (csv_dir / "media_conglomerate_yayoi.csv").read_bytes(),
        filename="media_conglomerate_yayoi.csv",
    )
    assert "csv_formula_escaped" in formula_preview["known_gaps"]
