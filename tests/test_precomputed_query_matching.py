from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.services.evidence_packet import (
    EvidencePacketComposer,
    _reset_cache_for_tests,
)

if TYPE_CHECKING:
    from pathlib import Path


def _build_autonomath_db(path: Path) -> None:
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            CREATE TABLE am_source (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_url TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL DEFAULT 'primary',
                domain TEXT,
                content_hash TEXT,
                first_seen TEXT NOT NULL,
                last_verified TEXT,
                license TEXT
            );
            CREATE TABLE jpi_programs (
                unified_id TEXT PRIMARY KEY,
                primary_name TEXT NOT NULL,
                authority_name TEXT,
                prefecture TEXT,
                tier TEXT,
                source_url TEXT,
                source_fetched_at TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE entity_id_map (
                jpi_unified_id TEXT NOT NULL,
                am_canonical_id TEXT NOT NULL,
                match_method TEXT NOT NULL,
                confidence REAL NOT NULL,
                PRIMARY KEY (jpi_unified_id, am_canonical_id)
            );
            CREATE TABLE am_amendment_diff (
                diff_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE am_program_summary (
                entity_id TEXT PRIMARY KEY,
                primary_name TEXT,
                summary_50 TEXT,
                summary_200 TEXT,
                summary_800 TEXT,
                token_50_est INT,
                token_200_est INT,
                token_800_est INT,
                generated_at TEXT DEFAULT (datetime('now')),
                source_quality REAL
            );
            CREATE TABLE am_enforcement_detail (
                enforcement_id TEXT PRIMARY KEY,
                entity_id TEXT,
                houjin_bangou TEXT,
                target_name TEXT,
                enforcement_kind TEXT,
                issuing_authority TEXT,
                issuance_date TEXT,
                reason_summary TEXT,
                source_url TEXT
            );
            CREATE TABLE jpi_enforcement_cases (
                case_id TEXT PRIMARY KEY,
                recipient_houjin_bangou TEXT,
                recipient_name TEXT,
                event_type TEXT,
                ministry TEXT,
                disclosed_date TEXT,
                legal_basis TEXT,
                reason_excerpt TEXT,
                source_url TEXT
            );
            CREATE TABLE jpi_invoice_registrants (
                invoice_registration_number TEXT PRIMARY KEY,
                houjin_bangou TEXT,
                normalized_name TEXT,
                registered_date TEXT,
                prefecture TEXT,
                source_url TEXT,
                fetched_at TEXT
            );
            """
        )
        con.execute(
            "INSERT INTO am_source(source_url, source_type, domain, "
            "content_hash, first_seen, last_verified, license) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                "https://example.metro.tokyo.lg.jp/setsubi",
                "primary",
                "example.metro.tokyo.lg.jp",
                "sha256:setsubi",
                "2026-04-29T00:00:00",
                "2026-04-29T00:00:00",
                "gov_standard_v2.0",
            ),
        )

        programs = [
            (
                "UNI-tokyo-setsubi-1",
                "東京都 中小企業設備投資補助金",
                "program:tokyo:setsubi:1",
                "設備投資の短縮要約。",
                "東京都内の中小企業による設備投資を支援する補助金。",
                "https://example.metro.tokyo.lg.jp/setsubi",
                "東京都",
                "S",
            ),
            (
                "UNI-tokyo-jinzai-1",
                "東京都 人材育成補助金",
                "program:tokyo:jinzai:1",
                "人材育成の短縮要約。",
                "東京都内の人材育成を支援する補助金。",
                "https://example.metro.tokyo.lg.jp/jinzai",
                "東京都",
                "A",
            ),
            (
                "UNI-osaka-setsubi-1",
                "大阪府 中小企業設備投資補助金",
                "program:osaka:setsubi:1",
                "大阪設備投資の短縮要約。",
                "大阪府内の中小企業による設備投資を支援する補助金。",
                "https://example.pref.osaka.lg.jp/setsubi",
                "大阪府",
                "A",
            ),
        ]
        for (
            unified_id,
            primary_name,
            entity_id,
            summary_50,
            summary_200,
            source_url,
            prefecture,
            tier,
        ) in programs:
            con.execute(
                "INSERT INTO jpi_programs(unified_id, primary_name, "
                "authority_name, prefecture, tier, source_url, source_fetched_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    unified_id,
                    primary_name,
                    f"{prefecture}庁",
                    prefecture,
                    tier,
                    source_url,
                    "2026-04-29T00:00:00",
                ),
            )
            con.execute(
                "INSERT INTO entity_id_map(jpi_unified_id, am_canonical_id, "
                "match_method, confidence) VALUES (?,?,?,?)",
                (unified_id, entity_id, "exact_name", 1.0),
            )
            con.execute(
                "INSERT INTO am_program_summary(entity_id, primary_name, "
                "summary_50, summary_200, summary_800, token_50_est, "
                "token_200_est, token_800_est, generated_at, source_quality) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    entity_id,
                    primary_name,
                    summary_50,
                    summary_200,
                    summary_200,
                    12,
                    28,
                    44,
                    "2026-04-29T00:00:00",
                    0.95,
                ),
            )
            con.execute(
                "INSERT INTO am_amendment_diff(entity_id, field_name, detected_at) "
                "VALUES (?,?,?)",
                (entity_id, "summary_200", "2026-04-29T00:00:00"),
            )
        con.commit()
    finally:
        con.close()


@pytest.fixture()
def composer(tmp_path: Path) -> EvidencePacketComposer:
    db_path = tmp_path / "autonomath.db"
    _build_autonomath_db(db_path)
    _reset_cache_for_tests()
    return EvidencePacketComposer(
        jpintel_db=tmp_path / "jpintel.db",
        autonomath_db=db_path,
    )


def test_natural_japanese_query_with_particles_matches_precomputed_programs(
    composer: EvidencePacketComposer,
) -> None:
    envelope = composer.compose_for_query(
        "東京都の設備投資補助金は?",
        limit=5,
        include_facts=False,
        include_rules=False,
        include_compression=False,
    )

    names = [record["primary_name"] for record in envelope["records"]]
    assert "東京都 中小企業設備投資補助金" in names

    matched = next(
        record
        for record in envelope["records"]
        if record["primary_name"] == "東京都 中小企業設備投資補助金"
    )
    assert matched["precomputed"]["basis"] == "am_program_summary"
    assert matched["precomputed"]["summaries"]["50"] == "設備投資の短縮要約。"


def test_corporate_number_enforcement_miss_returns_structured_lookup(
    composer: EvidencePacketComposer,
) -> None:
    envelope = composer.compose_for_query(
        "法人番号 1010001034730 の行政処分有無",
        limit=5,
        include_facts=False,
        include_rules=False,
        include_compression=False,
    )

    record = envelope["records"][0]
    assert record["record_kind"] == "structured_miss"
    assert record["entity_id"] == "structured_miss:enforcement:1010001034730"
    assert record["lookup"]["status"] == "not_found_in_local_mirror"
    assert record["lookup"]["official_absence_proven"] is False
    assert record["lookup"]["checked_tables"] == [
        "am_enforcement_detail",
        "jpi_enforcement_cases",
    ]


def test_invoice_number_miss_returns_structured_lookup(
    composer: EvidencePacketComposer,
) -> None:
    envelope = composer.compose_for_query(
        "適格請求書発行事業者 T8010001213708 登録日",
        limit=5,
        include_facts=False,
        include_rules=False,
        include_compression=False,
    )

    record = envelope["records"][0]
    assert record["record_kind"] == "structured_miss"
    assert record["entity_id"] == "structured_miss:invoice:T8010001213708"
    assert record["source_url"] == "https://www.invoice-kohyo.nta.go.jp/"
    assert record["lookup"]["invoice_registration_number"] == "T8010001213708"
    assert record["lookup"]["status"] == "not_found_in_local_mirror"
    assert record["lookup"]["official_absence_proven"] is False
