from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.etl import jgrants_detail_mapping as mapping  # noqa: E402


def test_camel_case_jgrants_detail_maps_to_structured_facts() -> None:
    payload = {
        "subsidyId": "jgrants-2026-001",
        "detailUrl": "https://www.jgrants-portal.go.jp/subsidy/a0W000000000001",
        "applicationPeriod": {
            "startDate": "令和8年5月1日",
            "endDate": "令和8年6月30日(火) 17:00",
        },
        "subsidyMaxAmount": "補助上限額 100万円",
        "subsidyRate": "補助率 2分の1以内",
        "inquiry": {
            "organizationName": "経済産業省",
            "departmentName": "中小企業支援室",
            "phoneNumber": "03-1234-5678",
            "emailAddress": "help@example.go.jp",
        },
        "requiredDocuments": [
            {"documentName": "交付申請書"},
            {"name": "事業計画書"},
            {"fileName": "見積書"},
        ],
    }

    facts = mapping.normalize_jgrants_detail_response(payload)

    assert facts["license"] == "gov_standard_v2.0"
    assert facts["source_id"] == "jgrants-2026-001"
    assert facts["source_url"]["url"].startswith("https://www.jgrants-portal.go.jp/")
    assert facts["deadline"]["value"] == "2026-06-30"
    assert facts["deadline"]["confidence"] > 0.8
    assert facts["max_amount"]["yen"] == 1_000_000
    assert facts["subsidy_rate"]["normalized"] == "1/2"
    assert facts["subsidy_rate"]["percent"] == 50.0
    assert facts["contact"]["organization"] == "経済産業省"
    assert facts["contact"]["department"] == "中小企業支援室"
    assert facts["contact"]["phone"] == "03-1234-5678"
    assert facts["contact"]["email"] == "help@example.go.jp"
    assert facts["required_docs"]["items"] == ["交付申請書", "事業計画書", "見積書"]
    assert facts["validation"] == {"valid": True, "errors": [], "warnings": []}


def test_snake_case_text_variant_parses_amount_rate_contact_and_docs() -> None:
    payload = {
        "source_url": "https://www.jgrants-portal.go.jp/subsidy/detail/2026-abc",
        "source_id": "JG-ABC",
        "application_deadline": "2026/07/31 23:59",
        "amount": {"max_amount_yen": 5_000_000},
        "subsidy_rate_text": "助成率 50%",
        "contact": "お問い合わせ 補助金事務局 03-2222-3333 grants@example.go.jp",
        "required_docs": "提出書類\n1. 申請書\n2. 決算書\n3. 見積書",
    }

    facts = mapping.normalize_jgrants_detail_response(payload)

    assert facts["source_id"] == "JG-ABC"
    assert facts["deadline"]["value"] == "2026-07-31"
    assert facts["max_amount"]["yen"] == 5_000_000
    assert facts["subsidy_rate"]["normalized"] == "1/2"
    assert facts["subsidy_rate"]["percent"] == 50.0
    assert facts["contact"]["phone"] == "03-2222-3333"
    assert facts["contact"]["email"] == "grants@example.go.jp"
    assert facts["required_docs"]["items"] == ["申請書", "決算書", "見積書"]
    assert facts["validation"]["valid"] is True


def test_sparse_payload_returns_missing_reasons_and_validation_warnings() -> None:
    payload = {
        "id": "JG-SPARSE",
        "url": "https://www.jgrants-portal.go.jp/subsidy/detail/sparse",
        "title": "最低限の詳細レスポンス",
    }

    facts = mapping.normalize_jgrants_detail_response(payload)

    assert facts["source_id"] == "JG-SPARSE"
    assert facts["source_url"]["url"].endswith("/sparse")
    assert facts["deadline"] == {
        "value": None,
        "raw": None,
        "confidence": 0.0,
        "reason": "deadline key not found",
    }
    assert facts["max_amount"]["yen"] is None
    assert facts["subsidy_rate"]["normalized"] is None
    assert facts["contact"]["raw"] is None
    assert facts["required_docs"]["items"] == []
    assert facts["validation"]["valid"] is True
    assert set(facts["validation"]["warnings"]) == {
        "deadline not found",
        "max_amount not found",
        "subsidy_rate not found",
        "contact not found",
        "required_docs not found",
    }


def test_invalid_source_url_fails_validation_without_raising() -> None:
    facts = mapping.normalize_jgrants_detail_response(
        {
            "source_url": "not-a-url",
            "applicationEndDate": "2026-06-01",
            "subsidyMaxAmount": "1,000千円",
            "subsidyRate": 0.5,
            "contactPhone": "03-1111-2222",
            "documents": ["申請書"],
        },
    )

    assert facts["deadline"]["value"] == "2026-06-01"
    assert facts["max_amount"]["yen"] == 1_000_000
    assert facts["subsidy_rate"]["normalized"] == "1/2"
    assert facts["validation"]["valid"] is False
    assert facts["validation"]["errors"] == [
        "source_url is not an absolute http(s) URL: 'not-a-url'"
    ]


def test_mapping_module_has_no_fetch_or_db_mutation_path() -> None:
    assert mapping.NETWORK_FETCH_PERFORMED is False
    assert mapping.DB_MUTATION_PERFORMED is False
    assert hasattr(mapping, "normalize_jgrants_detail_response")
