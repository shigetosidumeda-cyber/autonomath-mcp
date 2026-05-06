from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_MIGRATIONS = _REPO / "scripts" / "migrations"


def _apply(conn: sqlite3.Connection, filename: str) -> None:
    conn.executescript((_MIGRATIONS / filename).read_text(encoding="utf-8"))


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _indexes(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA index_list({table})")}


@pytest.mark.parametrize(
    (
        "migration",
        "rollback",
        "table",
        "expected_columns",
    ),
    [
        (
            "170_program_decision_layer.sql",
            "170_program_decision_layer_rollback.sql",
            "am_program_decision_layer",
            {
                "decision_id",
                "layer_name",
                "subject_kind",
                "subject_id",
                "program_id",
                "candidate_rank",
                "fit_score",
                "win_signal_score",
                "urgency_score",
                "documentation_risk_score",
                "eligibility_gap_count",
                "rank_reason_codes_json",
                "next_questions_json",
                "recommended_action",
                "source_fact_ids_json",
                "source_document_ids_json",
                "quality_tier",
                "known_gaps_json",
                "computed_at",
            },
        ),
        (
            "171_corporate_risk_layer.sql",
            "171_corporate_risk_layer_rollback.sql",
            "am_corporate_risk_layer",
            {
                "risk_layer_id",
                "layer_name",
                "subject_kind",
                "subject_id",
                "houjin_no",
                "resolved_entity_id",
                "invoice_status_signal_json",
                "enforcement_signal_json",
                "public_funding_dependency_signal_json",
                "procurement_signal_json",
                "edinet_signal_json",
                "kanpou_signal_json",
                "risk_timeline_json",
                "dd_questions_json",
                "risk_reason_codes_json",
                "source_fact_ids_json",
                "source_document_ids_json",
                "quality_tier",
                "known_gaps_json",
                "computed_at",
            },
        ),
    ],
)
def test_derived_data_layer_migrations_apply_and_rollback(
    migration: str,
    rollback: str,
    table: str,
    expected_columns: set[str],
) -> None:
    conn = sqlite3.connect(":memory:")
    try:
        _apply(conn, migration)

        assert _table_exists(conn, table)
        columns = _columns(conn, table)
        assert expected_columns <= columns
        assert not {
            column
            for column in columns
            if any(
                forbidden in column
                for forbidden in (
                    "price",
                    "billing",
                    "charge",
                    "fee",
                    "amount",
                    "yen",
                    "unit",
                    "conversion",
                )
            )
        }

        _apply(conn, rollback)

        assert not _table_exists(conn, table)
    finally:
        conn.close()


@pytest.mark.parametrize(
    (
        "migration",
        "rollback",
        "table",
        "expected_columns",
    ),
    [
        (
            "172_corpus_snapshot.sql",
            "172_corpus_snapshot_rollback.sql",
            "corpus_snapshot",
            {
                "corpus_snapshot_id",
                "db_name",
                "snapshot_kind",
                "created_at",
                "table_counts_json",
                "table_checksums_json",
                "content_hash",
                "corpus_checksum",
                "source_freshness_json",
                "license_breakdown_json",
                "known_gaps_json",
                "build_tool",
                "build_version",
                "metadata_json",
            },
        ),
        (
            "173_artifact.sql",
            "173_artifact_rollback.sql",
            "artifact",
            {
                "artifact_id",
                "artifact_kind",
                "uri",
                "sha256",
                "bytes",
                "mime_type",
                "retention_class",
                "license",
                "corpus_snapshot_id",
                "created_at",
                "expires_at",
                "metadata_json",
                "known_gaps_json",
            },
        ),
        (
            "174_source_document.sql",
            "174_source_document_rollback.sql",
            "source_document",
            {
                "source_document_id",
                "source_url",
                "canonical_url",
                "domain",
                "title",
                "publisher",
                "publisher_entity_id",
                "document_kind",
                "license",
                "content_hash",
                "bytes",
                "fetched_at",
                "last_verified_at",
                "http_status",
                "artifact_id",
                "corpus_snapshot_id",
                "robots_status",
                "tos_note",
                "known_gaps_json",
                "metadata_json",
                "created_at",
            },
        ),
        (
            "175_extracted_fact.sql",
            "175_extracted_fact_rollback.sql",
            "extracted_fact",
            {
                "fact_id",
                "subject_kind",
                "subject_id",
                "entity_id",
                "source_document_id",
                "field_name",
                "field_kind",
                "value_text",
                "value_number",
                "value_date",
                "value_json",
                "unit",
                "quote",
                "page_number",
                "span_start",
                "span_end",
                "selector_json",
                "extraction_method",
                "extractor_version",
                "confidence_score",
                "confirming_source_count",
                "valid_from",
                "valid_until",
                "observed_at",
                "corpus_snapshot_id",
                "known_gaps_json",
                "created_at",
            },
        ),
    ],
)
def test_public_corpus_foundation_migrations_are_idempotent_and_reversible(
    migration: str,
    rollback: str,
    table: str,
    expected_columns: set[str],
) -> None:
    conn = sqlite3.connect(":memory:")
    try:
        _apply(conn, migration)
        _apply(conn, migration)

        assert _table_exists(conn, table)
        assert expected_columns <= _columns(conn, table)

        _apply(conn, rollback)

        assert not _table_exists(conn, table)
    finally:
        conn.close()


def test_source_foundation_domain_tables_migration_is_idempotent_and_reversible() -> None:
    conn = sqlite3.connect(":memory:")
    expected_columns_by_table = {
        "houjin_change_history": {
            "history_id",
            "houjin_bangou",
            "sequence_number",
            "change_date",
            "process",
            "correct",
            "before_value_json",
            "after_value_json",
            "raw_row_json",
            "diff_zip_filename",
            "source_row_hash",
            "source_url",
            "source_checksum",
            "source_document_id",
            "corpus_snapshot_id",
            "fetched_at",
            "pgp_signature_verified",
            "application_id_used",
            "known_gaps_json",
            "created_at",
        },
        "houjin_master_refresh_run": {
            "refresh_run_id",
            "source_id",
            "acquisition_method",
            "started_at",
            "finished_at",
            "status",
            "row_count",
            "inserted_count",
            "updated_count",
            "unchanged_count",
            "deleted_count",
            "source_url",
            "source_checksum",
            "source_document_id",
            "artifact_id",
            "corpus_snapshot_id",
            "pgp_signature_verified",
            "application_id_used",
            "known_gaps_json",
            "metadata_json",
            "created_at",
        },
        "am_enforcement_source_index": {
            "source_index_id",
            "source_id",
            "source_action_id",
            "source_document_id",
            "artifact_id",
            "enforcement_id",
            "entity_id",
            "houjin_bangou",
            "corp_name_normalized",
            "respondent_name",
            "respondent_kind",
            "authority",
            "authority_code",
            "bureau",
            "sector_category",
            "permit_no",
            "publication_date",
            "action_date",
            "action_kind_raw",
            "enforcement_kind",
            "legal_basis",
            "reason_summary",
            "amount_yen",
            "period_start",
            "period_end",
            "as_of_date",
            "source_url",
            "content_hash",
            "fetched_at",
            "raw_json",
            "known_gaps_json",
            "created_at",
        },
        "law_revisions": {
            "law_revision_id",
            "law_id",
            "law_num",
            "law_canonical_id",
            "law_unified_id",
            "law_title",
            "amendment_promulgate_date",
            "amendment_enforcement_date",
            "amendment_scheduled_enforcement_date",
            "amendment_enforcement_comment",
            "amendment_law_id",
            "amendment_law_num",
            "amendment_law_title",
            "amendment_type",
            "mission",
            "repeal_status",
            "repeal_date",
            "remain_in_force",
            "current_revision_status",
            "source_url",
            "source_document_id",
            "corpus_snapshot_id",
            "fetched_at",
            "content_hash",
            "raw_json",
            "known_gaps_json",
            "created_at",
        },
        "law_attachment": {
            "attachment_id",
            "law_revision_id",
            "law_id",
            "src",
            "updated",
            "attachment_api_url",
            "source_document_id",
            "artifact_id",
            "content_hash",
            "mime_type",
            "bytes",
            "fetched_at",
            "raw_json",
            "known_gaps_json",
            "created_at",
        },
        "procurement_award": {
            "award_id",
            "bid_unified_id",
            "source_id",
            "procurement_item_no",
            "procurement_item_info_id",
            "source_row_hash",
            "award_date",
            "awarded_amount_yen",
            "winner_name",
            "winner_houjin_bangou",
            "winner_kojin_flag",
            "ministry_cd",
            "procuring_entity",
            "bidding_method_cd",
            "source_url",
            "source_document_id",
            "source_checksum",
            "fetched_at",
            "updated_at",
            "raw_json",
            "known_gaps_json",
            "created_at",
        },
    }
    try:
        _apply(conn, "176_source_foundation_domain_tables.sql")
        _apply(conn, "176_source_foundation_domain_tables.sql")

        for table, expected_columns in expected_columns_by_table.items():
            assert _table_exists(conn, table)
            assert expected_columns <= _columns(conn, table)

        assert {
            "idx_houjin_change_history_source_document",
            "uq_houjin_change_history_source_row_hash",
            "uq_houjin_change_history_diff_sequence",
        } <= _indexes(conn, "houjin_change_history")
        assert {
            "idx_houjin_master_refresh_run_source_document",
            "idx_houjin_master_refresh_run_artifact",
        } <= _indexes(conn, "houjin_master_refresh_run")
        assert "uq_law_revisions_law_revision" in _indexes(conn, "law_revisions")
        assert {
            "uq_procurement_award_source_row_hash",
            "uq_procurement_award_source_natural",
        } <= _indexes(conn, "procurement_award")

        _apply(conn, "176_source_foundation_domain_tables_rollback.sql")

        for table in expected_columns_by_table:
            assert not _table_exists(conn, table)
    finally:
        conn.close()


def test_source_foundation_domain_tables_reject_dirty_join_keys() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        _apply(conn, "176_source_foundation_domain_tables.sql")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO houjin_change_history(history_id, houjin_bangou) VALUES (?, ?)",
                ("hch_bad_alpha", "12345678901A3"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_enforcement_source_index("
                "source_index_id, source_id, respondent_name"
                ") VALUES (?, ?, ?)",
                ("aesi_bad_source", "fsa-enforcement", "Test Corp"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO procurement_award(award_id, winner_name, winner_houjin_bangou) "
                "VALUES (?, ?, ?)",
                ("pa_bad_fullwidth", "Test Corp", "１２３４５６７８９０１２３"),
            )
    finally:
        conn.close()


def test_source_foundation_domain_tables_dedupe_procurement_awards_with_null_item_info() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        _apply(conn, "176_source_foundation_domain_tables.sql")

        conn.execute(
            "INSERT INTO procurement_award("
            "award_id, source_id, procurement_item_no, procurement_item_info_id, "
            "winner_name, winner_houjin_bangou, award_date, awarded_amount_yen"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "award_1",
                "p_portal_chotatsu",
                "ITEM-001",
                None,
                "株式会社テスト",
                "1234567890123",
                "2026-05-01",
                1000,
            ),
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO procurement_award("
                "award_id, source_id, procurement_item_no, procurement_item_info_id, "
                "winner_name, winner_houjin_bangou, award_date, awarded_amount_yen"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "award_2",
                    "p_portal_chotatsu",
                    "ITEM-001",
                    None,
                    "株式会社テスト",
                    "1234567890123",
                    "2026-05-01",
                    1000,
                ),
            )
    finally:
        conn.close()


def test_source_foundation_domain_tables_apply_source_defaults() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        _apply(conn, "176_source_foundation_domain_tables.sql")

        conn.execute(
            "INSERT INTO houjin_master_refresh_run("
            "refresh_run_id, acquisition_method, started_at, status, source_document_id"
            ") VALUES (?, ?, ?, ?, ?)",
            (
                "run_default_source",
                "bulk_csv",
                "2026-05-06T00:00:00Z",
                "started",
                "source_document:nta_houjin_bangou:test",
            ),
        )
        conn.execute(
            "INSERT INTO procurement_award(award_id, winner_name) VALUES (?, ?)",
            ("award_default_source", "株式会社テスト"),
        )

        refresh = conn.execute(
            "SELECT source_id FROM houjin_master_refresh_run WHERE refresh_run_id = ?",
            ("run_default_source",),
        ).fetchone()
        award = conn.execute(
            "SELECT source_id FROM procurement_award WHERE award_id = ?",
            ("award_default_source",),
        ).fetchone()

        assert refresh is not None
        assert award is not None
        assert refresh[0] == "nta_houjin_bangou"
        assert award[0] == "p_portal_chotatsu"
    finally:
        conn.close()
