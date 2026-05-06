from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ops" / "preflight_production_improvement.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("preflight_production_improvement", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_ok_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE schema_migrations (
                id TEXT PRIMARY KEY,
                checksum TEXT NOT NULL DEFAULT '',
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_migrations(id, applied_at) VALUES
                ('172_corpus_snapshot.sql', '2026-05-06T00:00:00Z'),
                ('173_artifact.sql', '2026-05-06T00:00:00Z'),
                ('174_source_document.sql', '2026-05-06T00:00:00Z'),
                ('175_extracted_fact.sql', '2026-05-06T00:00:00Z'),
                ('176_source_foundation_domain_tables.sql', '2026-05-06T00:00:00Z');

            CREATE TABLE corpus_snapshot (corpus_snapshot_id TEXT PRIMARY KEY);
            CREATE TABLE artifact (artifact_id TEXT PRIMARY KEY);
            CREATE TABLE source_document (
                source_document_id TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                fetched_at TEXT,
                robots_status TEXT,
                tos_note TEXT,
                artifact_id TEXT,
                corpus_snapshot_id TEXT,
                known_gaps_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE extracted_fact (fact_id TEXT PRIMARY KEY);
            CREATE TABLE houjin_change_history (history_id TEXT PRIMARY KEY);
            CREATE TABLE houjin_master_refresh_run (refresh_run_id TEXT PRIMARY KEY);
            CREATE TABLE am_enforcement_source_index (source_index_id TEXT PRIMARY KEY);
            CREATE TABLE law_revisions (law_revision_id TEXT PRIMARY KEY);
            CREATE TABLE law_attachment (attachment_id TEXT PRIMARY KEY);
            CREATE TABLE procurement_award (award_id TEXT PRIMARY KEY);

            CREATE TABLE programs (id TEXT PRIMARY KEY);
            CREATE TABLE jpi_programs (id TEXT PRIMARY KEY);
            CREATE TABLE invoice_registrants (id TEXT PRIMARY KEY);
            CREATE TABLE jpi_invoice_registrants (id TEXT PRIMARY KEY);
            INSERT INTO programs(id) VALUES ('p1');
            INSERT INTO jpi_programs(id) VALUES ('jp1');
            INSERT INTO invoice_registrants(id) VALUES ('i1');
            INSERT INTO jpi_invoice_registrants(id) VALUES ('ji1');
            """
        )
        conn.commit()
    finally:
        conn.close()


def _empty_migrations_dir(path: Path) -> Path:
    path.mkdir()
    return path


def test_build_report_ok_for_applied_migrations_and_contract(tmp_path):
    module = _load_module()
    db = tmp_path / "autonomath.db"
    _seed_ok_db(db)
    migrations_dir = _empty_migrations_dir(tmp_path / "migrations")

    report = module.build_report(db, migrations_dir=migrations_dir)

    assert report["ok"] is True
    assert report["issues"] == []
    assert report["source_document_contract"]["required_columns"]["source_url"] is True
    assert report["migration_files_177"]["active_files"] == []


def test_build_report_flags_missing_migrations_tables_and_source_contract(tmp_path):
    module = _load_module()
    db = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            """
            CREATE TABLE schema_migrations (
                id TEXT PRIMARY KEY,
                checksum TEXT NOT NULL DEFAULT '',
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_migrations(id, applied_at)
                VALUES ('172_corpus_snapshot.sql', '2026-05-06T00:00:00Z');
            CREATE TABLE source_document (
                source_document_id TEXT PRIMARY KEY,
                url TEXT,
                source_fetched_at TEXT,
                robots_note TEXT
            );
            CREATE TABLE programs (id TEXT PRIMARY KEY);
            CREATE TABLE jpi_programs (id TEXT PRIMARY KEY);
            INSERT INTO jpi_programs(id) VALUES ('jp1');
            CREATE TABLE invoice_registrants (id TEXT PRIMARY KEY);
            CREATE TABLE jpi_invoice_registrants (id TEXT PRIMARY KEY);
            """
        )
        conn.commit()
    finally:
        conn.close()

    report = module.build_report(db, migrations_dir=_empty_migrations_dir(tmp_path / "migrations"))

    assert report["ok"] is False
    assert "schema_migrations:missing:173_artifact.sql" in report["issues"]
    assert "tables:missing:artifact" in report["issues"]
    assert "source_document:missing_column:source_url" in report["issues"]
    assert "source_document:forbidden_column_present:url" in report["issues"]
    assert "canonical_pair:jpi_populated_base_empty:programs:jpi_programs" not in report["issues"]
    assert report["canonical_table_pairs"]["pairs"][0]["state"] == "jpi_populated_base_empty"


def test_build_report_flags_empty_and_jpi_empty_canonical_pairs(tmp_path):
    module = _load_module()
    db = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            """
            CREATE TABLE schema_migrations (
                id TEXT PRIMARY KEY,
                checksum TEXT NOT NULL DEFAULT '',
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_migrations(id, applied_at) VALUES
                ('172_corpus_snapshot.sql', '2026-05-06T00:00:00Z'),
                ('173_artifact.sql', '2026-05-06T00:00:00Z'),
                ('174_source_document.sql', '2026-05-06T00:00:00Z'),
                ('175_extracted_fact.sql', '2026-05-06T00:00:00Z'),
                ('176_source_foundation_domain_tables.sql', '2026-05-06T00:00:00Z');

            CREATE TABLE corpus_snapshot (corpus_snapshot_id TEXT PRIMARY KEY);
            CREATE TABLE artifact (artifact_id TEXT PRIMARY KEY);
            CREATE TABLE source_document (
                source_document_id TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                fetched_at TEXT,
                robots_status TEXT,
                tos_note TEXT,
                artifact_id TEXT,
                corpus_snapshot_id TEXT,
                known_gaps_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE extracted_fact (fact_id TEXT PRIMARY KEY);
            CREATE TABLE houjin_change_history (history_id TEXT PRIMARY KEY);
            CREATE TABLE houjin_master_refresh_run (refresh_run_id TEXT PRIMARY KEY);
            CREATE TABLE am_enforcement_source_index (source_index_id TEXT PRIMARY KEY);
            CREATE TABLE law_revisions (law_revision_id TEXT PRIMARY KEY);
            CREATE TABLE law_attachment (attachment_id TEXT PRIMARY KEY);
            CREATE TABLE procurement_award (award_id TEXT PRIMARY KEY);

            CREATE TABLE programs (id TEXT PRIMARY KEY);
            CREATE TABLE jpi_programs (id TEXT PRIMARY KEY);
            CREATE TABLE invoice_registrants (id TEXT PRIMARY KEY);
            CREATE TABLE jpi_invoice_registrants (id TEXT PRIMARY KEY);
            INSERT INTO invoice_registrants(id) VALUES ('i1');
            """
        )
        conn.commit()
    finally:
        conn.close()

    report = module.build_report(db, migrations_dir=_empty_migrations_dir(tmp_path / "migrations"))

    assert report["ok"] is False
    assert "canonical_pair:both_empty:programs:jpi_programs" in report["issues"]
    assert (
        "canonical_pair:base_populated_jpi_empty:invoice_registrants:jpi_invoice_registrants"
        in report["issues"]
    )


def test_build_report_flags_177_active_collision(tmp_path):
    module = _load_module()
    db = tmp_path / "autonomath.db"
    _seed_ok_db(db)
    migrations_dir = _empty_migrations_dir(tmp_path / "migrations")
    (migrations_dir / "177_psf_p0_identity_ingest_ops.sql").write_text("-- ok\n")
    (migrations_dir / "177_evidence_packet_persistence.sql").write_text("-- conflict\n")

    report = module.build_report(db, migrations_dir=migrations_dir)

    assert report["ok"] is False
    assert "migration_files:177_active_collision" in report["issues"]
    assert report["migration_files_177"]["active_files"] == [
        "177_evidence_packet_persistence.sql",
        "177_psf_p0_identity_ingest_ops.sql",
    ]


def test_build_report_ignores_wave24_177_lane(tmp_path):
    module = _load_module()
    db = tmp_path / "autonomath.db"
    _seed_ok_db(db)
    migrations_dir = _empty_migrations_dir(tmp_path / "migrations")
    (migrations_dir / "wave24_177_regulatory_citation_graph.sql").write_text(
        "-- target_db: autonomath\nCREATE TABLE law_cross_reference(id TEXT);",
        encoding="utf-8",
    )

    report = module.build_report(db, migrations_dir=migrations_dir)

    assert report["ok"] is True
    assert report["issues"] == []
    assert report["migration_files_177"]["active_files"] == []
    assert report["migration_files_177"]["wave_files_ignored"] == [
        "wave24_177_regulatory_citation_graph.sql"
    ]


def test_build_report_numeric_177_can_coexist_with_wave24_177(tmp_path):
    module = _load_module()
    db = tmp_path / "autonomath.db"
    _seed_ok_db(db)
    migrations_dir = _empty_migrations_dir(tmp_path / "migrations")
    (migrations_dir / "177_psf_p0_identity_ingest_ops.sql").write_text("-- ok\n")
    (migrations_dir / "wave24_177_regulatory_citation_graph.sql").write_text(
        "-- target_db: autonomath\nCREATE TABLE law_cross_reference(id TEXT);",
        encoding="utf-8",
    )

    report = module.build_report(db, migrations_dir=migrations_dir)

    assert report["ok"] is True
    assert report["issues"] == []
    assert report["migration_files_177"]["active_files"] == ["177_psf_p0_identity_ingest_ops.sql"]
    assert report["migration_files_177"]["wave_files_ignored"] == [
        "wave24_177_regulatory_citation_graph.sql"
    ]


def test_main_warn_only_exits_zero_on_ng(tmp_path, capsys):
    module = _load_module()
    missing_db = tmp_path / "missing.db"
    migrations_dir = _empty_migrations_dir(tmp_path / "migrations")

    exit_code = module.main(
        ["--db", str(missing_db), "--migrations-dir", str(migrations_dir), "--warn-only"]
    )

    assert exit_code == 0
    assert "database:missing" in capsys.readouterr().out
