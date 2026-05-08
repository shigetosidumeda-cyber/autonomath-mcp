from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
SCRIPTS_ROOT = REPO_ROOT / "scripts"

sys.path.insert(0, str(SRC_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

from jpintel_mcp.ingest.normalizers.public_source_foundation import (  # noqa: E402
    normalize_source_profile_row,
)
from jpintel_mcp.ingest.schemas.public_source_foundation import (  # noqa: E402
    SourceProfileRow,
)


def _required_fields() -> dict[str, Any]:
    return {
        "priority": "P1",
        "source_type": "html",
        "data_objects": ["program_listing"],
        "acquisition_method": "GET HTML",
        "redistribution_risk": "low",
        "update_frequency": "daily",
        "target_tables": ["programs"],
    }


def test_normalizer_maps_aliases_and_empty_list_defaults():
    raw = {
        "source": "boj_stat_search",
        "url": "https://www.stat-search.boj.or.jp/",
        "name": "日本銀行 時系列統計データ検索サイト",
        "license": "API使用時はクレジット表示必須",
        "robots": "allowed",
        "as_of": "2026-05-06",
        **_required_fields(),
    }

    row = SourceProfileRow.model_validate(normalize_source_profile_row(raw))

    assert row.source_id == "boj_stat_search"
    assert row.source_url == "https://www.stat-search.boj.or.jp/"
    assert row.official_owner == "日本銀行 時系列統計データ検索サイト"
    assert row.license_or_terms == "API使用時はクレジット表示必須"
    assert row.robots_policy == "allowed"
    assert row.checked_at == "2026-05-06T00:00:00+09:00"
    assert row.sample_urls == []
    assert row.sample_fields == []
    assert row.known_gaps == []
    assert row.join_keys == []
    assert row.artifact_outputs_enabled == []
    assert row.target_artifacts == []
    assert row.artifact_sections_filled == []
    assert row.known_gaps_reduced == []
    assert row.new_known_gaps_created == []
    assert row.license_boundary == "full_fact"
    assert row.refresh_frequency == "daily"


def test_normalizer_maps_legacy_artifact_outputs_to_target_artifacts():
    raw = {
        "source": "procurement_portal",
        "url": "https://www.p-portal.go.jp/",
        "name": "調達ポータル",
        "license": "政府標準利用規約2.0",
        "robots": "allowed",
        "as_of": "2026-05-06",
        "artifact_outputs_enabled": [
            "company_public_baseline",
            "company_public_audit_pack",
        ],
        "artifact_sections": ["public_revenue", "evidence_ledger"],
        "known_gaps_if_present": ["procurement_source_not_connected"],
        "known_gaps_if_missing": ["source_license_unknown"],
        **_required_fields(),
    }

    row = SourceProfileRow.model_validate(normalize_source_profile_row(raw))

    assert row.target_artifacts == [
        "company_public_baseline",
        "company_public_audit_pack",
    ]
    assert row.artifact_outputs_enabled == row.target_artifacts
    assert row.artifact_sections_filled == ["public_revenue", "evidence_ledger"]
    assert row.known_gaps_reduced == ["procurement_source_not_connected"]
    assert row.new_known_gaps_created == ["source_license_unknown"]
    assert row.license_boundary == "full_fact"
    assert row.refresh_frequency == "daily"


def test_source_profile_row_accepts_target_artifacts_without_legacy_alias():
    raw = {
        "source_id": "company_public_spine",
        "priority": "P0",
        "official_owner": "国税庁",
        "source_url": "https://www.houjin-bangou.nta.go.jp/",
        "source_type": "api",
        "data_objects": ["corporate_identity"],
        "acquisition_method": "REST API",
        "robots_policy": "allowed",
        "license_or_terms": "政府標準利用規約2.0",
        "redistribution_risk": "low",
        "refresh_frequency": "daily",
        "join_keys": ["houjin_bangou"],
        "target_tables": ["houjin_master"],
        "target_artifacts": ["company_public_baseline"],
        "artifact_sections_filled": "identity",
        "known_gaps_reduced": "identifier_bridge_missing",
        "new_known_gaps_created": "invoice_history_missing",
        "license_boundary": "full",
        "sample_urls": [],
        "sample_fields": [],
        "known_gaps": [],
        "checked_at": "2026-05-06T00:00:00+09:00",
    }

    row = SourceProfileRow.model_validate(raw)

    assert row.update_frequency == "daily"
    assert row.refresh_frequency == "daily"
    assert row.target_artifacts == ["company_public_baseline"]
    assert row.artifact_outputs_enabled == ["company_public_baseline"]
    assert row.artifact_sections_filled == ["identity"]
    assert row.known_gaps_reduced == ["identifier_bridge_missing"]
    assert row.new_known_gaps_created == ["invoice_history_missing"]
    assert row.license_boundary == "full_fact"


def test_normalizer_unwraps_observation_payload_and_uses_host_source_id():
    raw = {
        "payload": {
            "source": "規制改革推進会議",
            "host": "www8.cao.go.jp",
            "root": "https://www8.cao.go.jp/kisei-kaikaku/",
            "authority": "内閣府",
            "license": "政府標準利用規約2.0",
            "robots_status": "allowed",
            **_required_fields(),
        },
        "collected_at": "2026-05-06T09:00:00+09:00",
    }

    row = SourceProfileRow.model_validate(normalize_source_profile_row(raw))

    assert row.source_id == "www8_cao_go_jp"
    assert row.source_url == "https://www8.cao.go.jp/kisei-kaikaku/"
    assert row.official_owner == "内閣府"
    assert row.checked_at == "2026-05-06T09:00:00+09:00"


def test_normalizer_completes_aggregator_shape_with_conservative_notes():
    raw = {
        "aggregator": "mirasapo_plus",
        "host": "mirasapo-plus.go.jp",
        "operator": "中小企業庁",
        "priority": "P2",
        "robots_status": "allowed",
        "license": "pdl_v1.0",
        "fetched_at": "2026-05-06T09:05:00+09:00",
    }

    row = SourceProfileRow.model_validate(normalize_source_profile_row(raw))

    assert row.source_id == "mirasapo_plus"
    assert row.source_url == "https://mirasapo-plus.go.jp/"
    assert row.official_owner == "中小企業庁"
    assert row.robots_policy == "allowed"
    assert "defaulted redistribution_risk=medium_review_required" in row.normalization_notes


def test_normalizer_completes_source_name_url_formats_shape():
    raw = {
        "source": "boj_stat_search",
        "name": "日本銀行 時系列統計データ検索サイト",
        "url": "https://www.stat-search.boj.or.jp/",
        "formats": ["CSV", "API(URL request)"],
        "license": "日本銀行著作権法保護下、引用OK・API使用時はクレジット表示必須",
        "fetched": "2026-05-06",
    }

    row = SourceProfileRow.model_validate(normalize_source_profile_row(raw))

    assert row.source_id == "boj_stat_search"
    assert row.source_type == "api_or_html"
    assert row.robots_policy == "unknown_review_required"
    assert "defaulted robots_policy=unknown_review_required" in row.normalization_notes
    assert "defaulted priority=P3" in row.normalization_notes


def test_normalizer_completes_local_government_index_shape():
    raw = {
        "source_id": "chukaku_city_kashiwa",
        "priority": "P3",
        "city": "柏市",
        "host": "www.city.kashiwa.lg.jp",
        "robots_status": "not_present",
        "sangyou_index": "https://www.city.kashiwa.lg.jp/jigyosha/index.html",
        "subsidy_list": "https://www.city.kashiwa.lg.jp/jigyosha/finance/challenge/index.html",
        "sample_program_url": "https://www.city.kashiwa.lg.jp/sangyoseisaku/jigyosha/finance/safetynet.html",
        "fetched_at": "2026-05-06T10:05:00+09:00",
    }

    row = SourceProfileRow.model_validate(normalize_source_profile_row(raw))

    assert row.official_owner == "柏市"
    assert row.source_url == "https://www.city.kashiwa.lg.jp/jigyosha/finance/challenge/index.html"
    assert row.license_or_terms.startswith("unknown_review_required")
    assert row.sample_urls == [
        "https://www.city.kashiwa.lg.jp/sangyoseisaku/jigyosha/finance/safetynet.html",
        "https://www.city.kashiwa.lg.jp/jigyosha/finance/challenge/index.html",
    ]
    assert (
        "defaulted license_or_terms=unknown_review_required from official public host"
        in row.normalization_notes
    )


def test_normalizer_completes_agency_listing_schema_fields_shape():
    raw = {
        "agency": "デジタル庁",
        "pref": "tokyo",
        "root": "https://www.digital.go.jp/",
        "listing_url": "https://www.digital.go.jp/resources/",
        "schema_fields": ["title", "url", "published_at"],
        "robots_status": "allowed",
        "license": "政府標準利用規約2.0",
        "fetched_at": "2026-05-06",
    }

    row = SourceProfileRow.model_validate(normalize_source_profile_row(raw))

    assert row.source_url == "https://www.digital.go.jp/resources/"
    assert row.official_owner == "デジタル庁"
    assert row.sample_fields == ["title", "url", "published_at"]
    assert row.checked_at == "2026-05-06T00:00:00+09:00"


def test_normalizer_handles_iter5_aliases_and_structured_robots():
    required = _required_fields()
    required.pop("update_frequency")
    raw = {
        "domain": "www.jpo.go.jp",
        "entity": "特許庁",
        "endpoints": [
            {"url": "https://www.jpo.go.jp/support/startup/index.html"},
            {"url": "https://www.jpo.go.jp/system/patent/gaiyo/index.html"},
        ],
        "terms": {"reuse": "政府標準利用規約2.0"},
        "robots": {"status": "allowed", "checked": "robots.txt"},
        "verified": "WebFetch_2026-05-06",
        "method": "GET HTML",
        "update_freq": "monthly",
        **required,
    }

    row = SourceProfileRow.model_validate(normalize_source_profile_row(raw))

    assert row.source_id == "jpo_go_jp"
    assert row.source_url == "https://www.jpo.go.jp/support/startup/index.html"
    assert row.sample_urls == [
        "https://www.jpo.go.jp/support/startup/index.html",
        "https://www.jpo.go.jp/system/patent/gaiyo/index.html",
    ]
    assert row.official_owner == "特許庁"
    assert row.license_or_terms == '{"reuse":"政府標準利用規約2.0"}'
    assert row.robots_policy == '{"checked":"robots.txt","status":"allowed"}'
    assert row.checked_at == "2026-05-06T00:00:00+09:00"
    assert row.update_frequency == "monthly"


def test_normalizer_handles_jst_datetime_checked_at():
    raw = {
        "source": "meti_kanto_index",
        "source_url": "https://www.kanto.meti.go.jp/",
        "owner": "関東経済産業局",
        "license": "政府標準利用規約2.0",
        "robots": "allowed",
        "verified": "2026-05-06 11:12:13 JST",
        **_required_fields(),
    }

    row = SourceProfileRow.model_validate(normalize_source_profile_row(raw))

    assert row.checked_at == "2026-05-06T11:12:13+09:00"


@pytest.mark.parametrize(
    ("field", "raw"),
    [
        (
            "source_url",
            {
                "source": "no_url",
                "name": "URLなし",
                "license": "terms captured",
                "robots": "allowed",
                "fetched": "2026-05-06",
            },
        ),
        (
            "checked_at",
            {
                "source": "no_checked_at",
                "url": "https://example.com/",
                "name": "取得時刻なし",
                "license": "terms captured",
                "robots": "allowed",
            },
        ),
        (
            "license_or_terms",
            {
                "source": "no_license",
                "url": "https://example.com/",
                "name": "規約なし",
                "robots": "allowed",
                "fetched": "2026-05-06",
            },
        ),
        (
            "robots_policy",
            {
                "source": "no_robots",
                "name": "robotsなし",
                "license": "terms captured",
                "fetched": "2026-05-06",
            },
        ),
    ],
)
def test_normalizer_does_not_validize_rows_missing_unrecoverable_fields(field, raw):
    normalized = normalize_source_profile_row(raw)
    assert not normalized.get(field)

    with pytest.raises(ValidationError):
        SourceProfileRow.model_validate(normalized)


def test_cron_processes_public_source_foundation_through_normalizer(
    tmp_path,
    monkeypatch,
):
    sys.modules.pop("ingest_offline_inbox", None)
    spec = importlib.util.spec_from_file_location(
        "ingest_offline_inbox",
        SCRIPTS_ROOT / "cron" / "ingest_offline_inbox.py",
    )
    cron = importlib.util.module_from_spec(spec)
    sys.modules["ingest_offline_inbox"] = cron
    spec.loader.exec_module(cron)

    inbox_root = tmp_path / "_inbox"
    quarantine_root = tmp_path / "_quarantine"
    inbox_dir = inbox_root / "public_source_foundation"
    inbox_dir.mkdir(parents=True)
    quarantine_root.mkdir()
    monkeypatch.setattr(cron, "INBOX_ROOT", inbox_root)
    monkeypatch.setattr(cron, "QUARANTINE_ROOT", quarantine_root)

    row = {
        "slug": "pref-fukuoka",
        "root": "https://www.pref.fukuoka.lg.jp/",
        "agency": "福岡県",
        "license": "政府標準利用規約2.0",
        "robots_status": "allowed",
        "fetched_at": "2026-05-06T08:50:00+09:00",
        **_required_fields(),
    }
    path = inbox_dir / "source_profiles.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    valid, quarantined = cron.process_public_source_foundation_file(
        path,
        SourceProfileRow,
    )

    assert (valid, quarantined) == (1, 0)
    assert not path.exists()
    assert (inbox_dir / "_done" / path.name).exists()
    assert not list((quarantine_root / "public_source_foundation").glob("*.jsonl"))

    backlog = json.loads(
        (inbox_dir / "_backlog" / "source_document_backlog.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert backlog["source_id"] == "pref_fukuoka"
    assert backlog["source_document_fields"]["publisher"] == "福岡県"
